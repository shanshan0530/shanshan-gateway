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
