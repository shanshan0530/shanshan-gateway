-- Gateway-only incremental summary checkpoints. No OrangeChat rows are changed.
create table if not exists public.gateway_summary_checkpoints (
    assistant_id text not null,
    conversation_id text not null,
    last_message_id integer not null default 0,
    updated_at timestamptz not null default now(),
    primary key (assistant_id, conversation_id),
    constraint gateway_summary_conversation_check
        check (conversation_id like 'gw:%'),
    constraint gateway_summary_message_id_check
        check (last_message_id >= 0)
);

alter table public.gateway_summary_checkpoints enable row level security;

revoke all on table public.gateway_summary_checkpoints from public;
grant select, insert, update on table public.gateway_summary_checkpoints
    to anon, authenticated, service_role;

drop policy if exists gateway_summary_checkpoints_select
    on public.gateway_summary_checkpoints;
create policy gateway_summary_checkpoints_select
    on public.gateway_summary_checkpoints
    for select
    to anon, authenticated
    using (true);

drop policy if exists gateway_summary_checkpoints_insert
    on public.gateway_summary_checkpoints;
create policy gateway_summary_checkpoints_insert
    on public.gateway_summary_checkpoints
    for insert
    to anon, authenticated
    with check (
        conversation_id like 'gw:%'
        and btrim(assistant_id) <> ''
        and last_message_id >= 0
    );

drop policy if exists gateway_summary_checkpoints_update
    on public.gateway_summary_checkpoints;
create policy gateway_summary_checkpoints_update
    on public.gateway_summary_checkpoints
    for update
    to anon, authenticated
    using (
        conversation_id like 'gw:%'
        and btrim(assistant_id) <> ''
        and last_message_id >= 0
    )
    with check (
        conversation_id like 'gw:%'
        and btrim(assistant_id) <> ''
        and last_message_id >= 0
    );

create or replace function public.gateway_store_memory_summary(
    p_assistant_id text,
    p_conversation_id text,
    p_expected_last_message_id integer,
    p_new_last_message_id integer,
    p_content text
)
returns boolean
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
    current_last_message_id integer;
begin
    if btrim(coalesce(p_assistant_id, '')) = ''
       or p_conversation_id not like 'gw:%'
       or p_expected_last_message_id < 0
       or p_new_last_message_id <= p_expected_last_message_id
       or btrim(coalesce(p_content, '')) = ''
       or length(p_content) > 8000 then
        return false;
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended(p_assistant_id || ':' || p_conversation_id, 0)
    );

    select last_message_id
      into current_last_message_id
      from public.gateway_summary_checkpoints
     where assistant_id = p_assistant_id
       and conversation_id = p_conversation_id;

    current_last_message_id := coalesce(current_last_message_id, 0);
    if current_last_message_id <> p_expected_last_message_id then
        return false;
    end if;

    insert into public.memory_summaries (content, assistant_id)
    values (btrim(p_content), p_assistant_id);

    insert into public.gateway_summary_checkpoints (
        assistant_id,
        conversation_id,
        last_message_id,
        updated_at
    ) values (
        p_assistant_id,
        p_conversation_id,
        p_new_last_message_id,
        now()
    )
    on conflict (assistant_id, conversation_id)
    do update set
        last_message_id = excluded.last_message_id,
        updated_at = excluded.updated_at;

    return true;
end;
$$;

revoke all on function public.gateway_store_memory_summary(
    text, text, integer, integer, text
) from public;
grant execute on function public.gateway_store_memory_summary(
    text, text, integer, integer, text
) to anon, authenticated, service_role;
