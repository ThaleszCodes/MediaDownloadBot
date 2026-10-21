-- Reproducible initial schema. Only the trusted backend can read or execute.
begin;
create table public.bot_users (
 telegram_id bigint primary key check (telegram_id > 0),
 trial_used integer not null default 0 check (trial_used between 0 and 5),
 created_at timestamptz not null default now()
);
create table public.bot_plans (
 code text primary key, name text not null, price_cents integer not null,
 checkout_url text not null, period_days integer, period_months integer,
 sales_enabled boolean not null default false
);
insert into public.bot_plans values
 ('weekly','Semanal',500,'https://pay.cakto.com.br/365xjdo_1226651',7,null,false),
 ('monthly','Mensal',1590,'https://pay.cakto.com.br/xoxoxcr',null,1,false);
create table public.bot_subscriptions (
 id uuid primary key default gen_random_uuid(),
 telegram_id bigint not null references public.bot_users,
 plan_code text not null references public.bot_plans,
 provider_order_id text unique not null,
 starts_at timestamptz not null,
 expires_at timestamptz not null,
 revoked_at timestamptz,
 check (expires_at > starts_at)
);
create table public.bot_download_jobs (
 id uuid primary key,
 telegram_id bigint not null references public.bot_users,
 quota integer not null check (quota between 0 and 50),
 trial boolean not null,
 delivered integer not null default 0,
 status text not null default 'reserved' check (status in ('reserved','finished')),
 created_at timestamptz not null default now(),
 finished_at timestamptz,
 check (delivered between 0 and quota)
);
create index bot_subscriptions_user on public.bot_subscriptions(telegram_id, expires_at);
create index bot_download_jobs_user on public.bot_download_jobs(telegram_id, status);
alter table public.bot_users enable row level security;
alter table public.bot_plans enable row level security;
alter table public.bot_subscriptions enable row level security;
alter table public.bot_download_jobs enable row level security;
revoke all on public.bot_users, public.bot_plans, public.bot_subscriptions, public.bot_download_jobs from public, anon, authenticated;
grant all on public.bot_users, public.bot_plans, public.bot_subscriptions, public.bot_download_jobs to service_role;

create function public.bot_access(p_user bigint, p_action text, p_job uuid default null, p_count integer default 0)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare u public.bot_users; j public.bot_download_jobs; expiry timestamptz; reserved integer; available integer; allowed integer;
begin
 if p_user <= 0 then raise exception 'invalid user'; end if;
 insert into public.bot_users(telegram_id) values(p_user) on conflict do nothing;
 select * into u from public.bot_users where telegram_id=p_user for update;
 select max(expires_at) into expiry from public.bot_subscriptions
 where telegram_id=p_user and starts_at <= now() and expires_at > now() and revoked_at is null;
 -- Expired reservations remain charged conservatively until reconciled: a crash or
 -- upload timeout cannot silently replenish already delivered trial media.
 select coalesce(sum(quota-delivered),0) into reserved from public.bot_download_jobs
 where telegram_id=p_user and trial and status='reserved';
 available := greatest(0,5-u.trial_used-reserved);
 if p_action='status' then
  return jsonb_build_object('trial_remaining',available,'premium',expiry is not null,'expires_at',expiry);
 elsif p_action='reserve' then
  if p_job is null or p_count < 1 or p_count > 50 then raise exception 'invalid reservation'; end if;
  select * into j from public.bot_download_jobs where id=p_job;
  if found then
   if j.telegram_id <> p_user then raise exception 'wrong owner'; end if;
   return jsonb_build_object('quota',case when j.status='reserved' then j.quota else 0 end,'trial',j.trial);
  end if;
  -- One active request across instances/restarts. Reconcile abandoned jobs manually.
  if exists(select 1 from public.bot_download_jobs where telegram_id=p_user and status='reserved') then
   return jsonb_build_object('quota',0,'busy',true);
  end if;
  allowed := case when expiry is not null then p_count else least(p_count,available) end;
  if allowed > 0 then
   insert into public.bot_download_jobs(id,telegram_id,quota,trial) values(p_job,p_user,allowed,expiry is null);
  end if;
  return jsonb_build_object('quota',allowed,'trial',expiry is null);
 elsif p_action in ('progress','finish') then
  select * into j from public.bot_download_jobs where id=p_job and telegram_id=p_user for update;
  if not found then raise exception 'unknown job'; end if;
  if j.status='finished' then return jsonb_build_object('ok',true); end if;
  if p_count < j.delivered or p_count > j.quota then raise exception 'invalid delivery count'; end if;
  if j.trial then update public.bot_users set trial_used=trial_used+p_count-j.delivered where telegram_id=p_user; end if;
  update public.bot_download_jobs set delivered=p_count,
   status=case when p_action='finish' then 'finished' else 'reserved' end,
   finished_at=case when p_action='finish' then now() else null end where id=p_job;
  return jsonb_build_object('ok',true);
 end if;
 raise exception 'unknown action';
end $$;
revoke all on function public.bot_access(bigint,text,uuid,integer) from public,anon,authenticated;
grant execute on function public.bot_access(bigint,text,uuid,integer) to service_role;
commit;
