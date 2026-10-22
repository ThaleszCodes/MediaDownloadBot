begin;
do $$
declare uid bigint := 890000000000001; jid uuid := gen_random_uuid(); r jsonb; used integer;
begin
 insert into public.bot_users(telegram_id,trial_used) values(uid,2);
 insert into public.bot_download_jobs(id,telegram_id,quota,delivered,trial,created_at)
 values(jid,uid,5,2,true,now());
 r := public.bot_abandon(uid+1);
 if (r->>'closed')::integer <> 0 then raise exception 'wrong user closure'; end if;
 r := public.bot_abandon(uid);
 if (r->>'closed')::integer <> 1 then raise exception 'stale request not closed'; end if;
 select trial_used into used from public.bot_users where telegram_id=uid;
 if used<>5 then raise exception 'trial replenished'; end if;
 if (select delivered from public.bot_download_jobs where id=jid)<>2 then raise exception 'delivery history changed'; end if;
 r := public.bot_abandon(uid);
 if (r->>'closed')::integer <> 0 then raise exception 'not idempotent'; end if;
 insert into public.bot_download_jobs(id,telegram_id,quota,delivered,trial,created_at)
 values(gen_random_uuid(),uid,50,15,false,now()-interval '12 minutes');
 perform public.bot_abandon(uid);
 if (select trial_used from public.bot_users where telegram_id=uid)<>5 then raise exception 'premium affected trial'; end if;
 if has_function_privilege('anon','public.bot_abandon(bigint)','execute') or
    has_function_privilege('authenticated','public.bot_abandon(bigint)','execute') then
  raise exception 'function is public';
 end if;
end $$;
rollback;
