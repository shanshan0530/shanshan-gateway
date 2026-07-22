create table if not exists public.gateway_message_receipts (
  fingerprint text primary key,
  assistant_id text not null,
  conversation_id text not null,
  role text not null check (role in ('user', 'assistant')),
  created_at timestamptz not null default now()
);

alter table public.gateway_message_receipts enable row level security;

revoke all on public.gateway_message_receipts
from public, anon, authenticated;

drop policy if exists gateway_receipts_insert
on public.gateway_message_receipts;

create policy gateway_receipts_insert
on public.gateway_message_receipts
for insert
to anon, authenticated
with check (
  length(fingerprint) = 64
  and role in ('user', 'assistant')
  and btrim(assistant_id) <> ''
  and btrim(conversation_id) <> ''
);

grant insert on public.gateway_message_receipts to anon, authenticated;

create or replace function public.gateway_store_chat_message(
  p_fingerprint text,
  p_role text,
  p_content text,
  p_assistant_id text,
  p_conversation_id text
)
returns boolean
language plpgsql
security invoker
set search_path = public
as $function$
begin
  if p_role not in ('user', 'assistant')
     or btrim(coalesce(p_content, '')) = ''
     or btrim(coalesce(p_fingerprint, '')) = ''
     or btrim(coalesce(p_assistant_id, '')) = ''
     or btrim(coalesce(p_conversation_id, '')) = '' then
    return false;
  end if;

  begin
    insert into public.gateway_message_receipts (
      fingerprint,
      assistant_id,
      conversation_id,
      role
    )
    values (
      p_fingerprint,
      p_assistant_id,
      p_conversation_id,
      p_role
    );
  exception
    when unique_violation then
      return false;
  end;

  insert into public.chat_messages (
    role,
    content,
    assistant_id,
    conversation_id
  )
  values (
    p_role,
    btrim(p_content),
    p_assistant_id,
    p_conversation_id
  );

  return true;
end;
$function$;

revoke all on function public.gateway_store_chat_message(text, text, text, text, text)
from public;

grant execute on function public.gateway_store_chat_message(text, text, text, text, text)
to anon, authenticated, service_role;
