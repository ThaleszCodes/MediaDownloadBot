-- Self-service closure of interrupted jobs; preserve delivery totals and trial accounting.
create or replace function public.bot_abandon(p_user bigint)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare j public.bot_download_jobs; closed integer := 0; charged integer := 0;
begin
 if p_user is null or p_user <= 0 then raise exception 'invalid user'; end if;
 perform 1 from public.bot_users where telegram_id=p_user for update;
 for j in select * from public.bot_download_jobs where telegram_id=p_user and status='reserved' for update loop
  if j.trial then charged := charged + j.quota-j.delivered; end if;
  update public.bot_download_jobs set status='finished',finished_at=now() where id=j.id;
  closed := closed+1;
 end loop;
 -- Unknown Telegram delivery must not allow the free allowance to be refilled.
 update public.bot_users set trial_used=least(5,trial_used+charged) where telegram_id=p_user;
 return jsonb_build_object('busy',false,'closed',closed);
end $$;
revoke all on function public.bot_abandon(bigint) from public,anon,authenticated;
grant execute on function public.bot_abandon(bigint) to service_role;
