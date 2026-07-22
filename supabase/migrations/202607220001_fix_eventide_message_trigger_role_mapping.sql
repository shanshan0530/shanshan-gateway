-- Route OrangeChat/TG rows to the single Eventide identity without hardcoding a UUID.
with source_assistant as (
  select cm.assistant_id
  from public.chat_messages cm
  where cm.assistant_id is not null
    and btrim(cm.assistant_id::text) <> ''
  group by cm.assistant_id
  order by count(*) desc, max(cm.created_at) desc
  limit 1
)
update public.eventide_config ec
set settings = jsonb_set(
  coalesce(ec.settings, '{}'::jsonb),
  '{source_assistant_id}',
  to_jsonb(sa.assistant_id::text),
  true
)
from source_assistant sa
where (
  select count(*) from public.eventide_config
) = 1;

create or replace function public.eventide_on_message()
returns trigger
language plpgsql
as $function$
declare
  msg_content text;
  tw record;
  matched boolean := false;
  aid text;
  sens_delta integer;
  poss_delta integer;
  pres_delta integer;
begin
  -- Only the human counterpart should advance last-message time or trigger words.
  if lower(coalesce(NEW.role, '')) <> 'user' then
    return NEW;
  end if;

  select ec.assistant_id
  into aid
  from public.eventide_config ec
  where ec.assistant_id = NEW.assistant_id::text
     or ec.settings ->> 'source_assistant_id' = NEW.assistant_id::text
  order by
    case when ec.assistant_id = NEW.assistant_id::text then 0 else 1 end,
    ec.assistant_id
  limit 1;

  -- Preserve the one-character setup even before an explicit mapping exists.
  if aid is null then
    select min(ec.assistant_id)
    into aid
    from public.eventide_config ec
    having count(*) = 1;
  end if;

  if aid is null then
    return NEW;
  end if;

  msg_content := lower(coalesce(NEW.content, ''));

  for tw in
    select *
    from public.eventide_trigger_words
    where assistant_id = aid
      and enabled = true
  loop
    if msg_content like '%' || lower(tw.word) || '%' then
      matched := true;
      exit;
    end if;
  end loop;

  if not matched then
    update public.eventide_body_state
    set last_counterpart_message_at = now(),
        updated_at = now()
    where assistant_id = aid;
    return NEW;
  end if;

  sens_delta := 3 + floor(random() * 6)::integer;
  poss_delta := 1 + floor(random() * 3)::integer;
  pres_delta := floor(random() * 5)::integer;

  update public.eventide_body_state
  set sensitivity = public.eventide_clamp(sensitivity + sens_delta, 0, 100)::integer,
      possessiveness = public.eventide_clamp(possessiveness + poss_delta, 40, 100)::integer,
      pressure = public.eventide_clamp(pressure + pres_delta, 0, 100)::integer,
      last_counterpart_message_at = now(),
      updated_at = now()
  where assistant_id = aid;

  return NEW;
end;
$function$;
