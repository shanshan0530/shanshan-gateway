-- device_data.timestamp is written by the OrangeChat sync plugin as local
-- Asia/Taipei wall-clock text (YYYY-MM-DD HH24:MI:SS).  Cast it explicitly
-- before comparing it with the two-day retention cutoff.
do $$
declare
  retention_job_id bigint;
begin
  select jobid
    into retention_job_id
    from cron.job
   where jobname = 'clean_device_data';

  if retention_job_id is null then
    raise exception 'cron job clean_device_data does not exist';
  end if;

  perform cron.alter_job(
    job_id := retention_job_id,
    command := $command$
      delete from public.device_data
       where "timestamp" ~ '^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}'
         and substring("timestamp" from 1 for 19)::timestamp
             < (now() at time zone 'Asia/Taipei') - interval '2 days'
    $command$
  );
end
$$;
