begin;
create function public.bot_account(p_user bigint) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare state jsonb; active public.bot_subscriptions; used integer; pending integer; total bigint;
begin
 state:=public.bot_access(p_user,'status');
 select trial_used into used from public.bot_users where telegram_id=p_user;
 select coalesce(sum(quota-delivered),0) into pending from public.bot_download_jobs where telegram_id=p_user and trial and status='reserved';
 select coalesce(sum(delivered),0) into total from public.bot_download_jobs where telegram_id=p_user;
 select * into active from public.bot_subscriptions where telegram_id=p_user and revoked_at is null
 and starts_at<=now() and expires_at>now() order by expires_at desc limit 1;
 return state||jsonb_build_object('telegram_id',p_user,'trial_used',used,'trial_reserved',pending,
 'total_delivered',total,'plan_name',(select name from public.bot_plans where code=active.plan_code));
end $$;
create function public.bot_list_plans() returns jsonb
language sql security invoker set search_path='' as $$
 select coalesce(jsonb_agg(jsonb_build_object('code',code,'name',name,'price_cents',price_cents,
 'period_days',period_days,'period_months',period_months,'sales_enabled',sales_enabled) order by price_cents),'[]'::jsonb)
 from public.bot_plans;
$$;
revoke all on function public.bot_account(bigint), public.bot_list_plans() from public,anon,authenticated;
grant execute on function public.bot_account(bigint), public.bot_list_plans() to service_role;
commit;
