begin;
alter table public.bot_plans add column provider_offer_id text;
alter table public.bot_plans add column provider_product_id text;
alter table public.bot_subscriptions add column provider_subscription_id text;
create index bot_subscription_provider on public.bot_subscriptions(provider_subscription_id);
create table public.bot_checkout_sessions (
 token text primary key,
 telegram_id bigint not null references public.bot_users,
 plan_code text not null references public.bot_plans,
 created_at timestamptz not null default now(),
 expires_at timestamptz not null default (now()+interval '24 hours'),
 claimed_order_id text unique
);
create table public.bot_payment_events (
 order_id text not null,
 event text not null,
 plan_code text references public.bot_plans,
 provider_subscription_id text,
 checkout_token text,
 status text not null default 'received',
 payment_details jsonb,
 received_at timestamptz not null default now(),
 processed_at timestamptz,
 primary key(order_id,event)
);
alter table public.bot_checkout_sessions enable row level security;
alter table public.bot_payment_events enable row level security;
revoke all on public.bot_checkout_sessions, public.bot_payment_events from public,anon,authenticated;
grant all on public.bot_checkout_sessions, public.bot_payment_events to service_role;

-- Invoked exclusively by a trusted external sales backend. No checkout links in bot.
create function public.bot_create_checkout(p_user bigint,p_plan text) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare p public.bot_plans; t text;
begin
 select * into p from public.bot_plans where code=p_plan and sales_enabled;
 if not found then raise exception 'sales disabled'; end if;
 perform public.bot_access(p_user,'status');
 t:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');
 insert into public.bot_checkout_sessions(token,telegram_id,plan_code) values(t,p_user,p_plan);
 return jsonb_build_object('checkout_url',p.checkout_url||'?callback='||t,'token',t);
end $$;
revoke all on function public.bot_create_checkout(bigint,text) from public,anon,authenticated;
grant execute on function public.bot_create_checkout(bigint,text) to service_role;

create function public.bot_process_payment(p_event text,p_data jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare oid text:=p_data->>'id'; p public.bot_plans; sess public.bot_checkout_sessions;
 uid bigint; subid text:=nullif(p_data->>'subscription_id',''); paid timestamptz;
 from_date timestamptz; to_date timestamptz; saved public.bot_subscriptions;
 net_cents integer; extras integer; pricing_ok boolean;
 result text; callback text:=p_data->>'callback'; previous text;
begin
 if oid is null or length(oid)>255 or length(oid)=0 then raise exception 'invalid order'; end if;
 if p_event not in ('purchase_approved','subscription_renewed','subscription_late_recovered',
 'refund','chargeback','subscription_canceled','subscription_paused','subscription_resumed',
 'subscription_late','subscription_renewal_refused','refund_requested') then
 return jsonb_build_object('result','ignored_event'); end if;
 perform pg_advisory_xact_lock(hashtextextended('cakto:'||oid,0));
 select * into saved from public.bot_subscriptions where provider_order_id=oid;
 select status into previous from public.bot_payment_events where order_id=oid and event=p_event;
 if previous in ('applied','revoked','observed') then return jsonb_build_object('result','duplicate'); end if;
 -- Prefer verified offer IDs; known checkout URLs are a fallback until account metadata is connected.
 select * into p from public.bot_plans where
 (provider_offer_id is not null and provider_offer_id=p_data->>'offer_id'
  and (provider_product_id is null or provider_product_id=p_data->>'product_id'))
 or (provider_offer_id is null and checkout_url=p_data->>'checkout_url');
 if p.code is null and saved.id is not null then select * into p from public.bot_plans where code=saved.plan_code; end if;
 if p.code is null and subid is not null then
  select bp.* into p from public.bot_plans bp join public.bot_subscriptions bs on bs.plan_code=bp.code
  where bs.provider_subscription_id=subid order by bs.expires_at desc limit 1;
 end if;
 if p.code is null then return jsonb_build_object('result','ignored_offer'); end if;
 insert into public.bot_payment_events(order_id,event,plan_code,provider_subscription_id,checkout_token)
 values(oid,p_event,p.code,subid,callback) on conflict do nothing;
 update public.bot_payment_events set payment_details=jsonb_build_object('status',p_data->'status',
 'currency',p_data->'currency','amount_cents',p_data->'amount_cents','expected_cents',p.price_cents,
 'base_amount_cents',p_data->'base_amount_cents','discount_cents',p_data->'discount_cents',
 'charged_fees_cents',p_data->'charged_fees_cents','interest_cents',p_data->'interest_cents',
 'additional_interest_cents',p_data->'additional_interest_cents','coupon_code',p_data->'coupon_code',
 'paid_at',p_data->'paid_at','offer_id',p_data->'offer_id','product_id',p_data->'product_id')
 where order_id=oid and event=p_event;
 if p_event in ('refund','chargeback') then
  update public.bot_subscriptions set revoked_at=coalesce(revoked_at,now()) where provider_order_id=oid;
  update public.bot_payment_events set status='revoked',processed_at=now() where order_id=oid and event=p_event;
  return jsonb_build_object('result','revoked');
 end if;
 if p_event not in ('purchase_approved','subscription_renewed','subscription_late_recovered') then
  -- Cancellation stops future renewal, but does not erase an already paid interval.
  update public.bot_payment_events set status='observed',processed_at=now() where order_id=oid and event=p_event;
  return jsonb_build_object('result','observed');
 end if;
 if exists(select 1 from public.bot_payment_events where order_id=oid and event in ('refund','chargeback')) then
  update public.bot_payment_events set status='revoked',processed_at=now() where order_id=oid and event=p_event;
  return jsonb_build_object('result','revoked');
 end if;
 if saved.id is not null then
  update public.bot_payment_events set status='applied',processed_at=now() where order_id=oid and event=p_event;
  return jsonb_build_object('result','duplicate_order');
 end if;
 -- Validate the advertised base price, then reconcile only provider-reported
 -- discount and buyer-paid extras. Never subtract producer processing fees.
 pricing_ok := false;
 if p_data->>'base_amount_cents' is null then
  -- Backward compatibility for old full-price normalized events only.
  pricing_ok := (p_data->>'amount_cents')::integer = p.price_cents
                and coalesce((p_data->>'discount_cents')::integer,0)=0;
 elsif (p_data->>'base_amount_cents')::integer=p.price_cents then
  net_cents:=p.price_cents-coalesce((p_data->>'discount_cents')::integer,0);
  extras:=coalesce((p_data->>'charged_fees_cents')::integer,0)
         +coalesce((p_data->>'interest_cents')::integer,0)
         +coalesce((p_data->>'additional_interest_cents')::integer,0);
  pricing_ok:=net_cents>0 and net_cents<=p.price_cents and extras>=0
   and (coalesce((p_data->>'discount_cents')::integer,0)=0 or nullif(p_data->>'coupon_code','') is not null)
   and (p_data->>'amount_cents')::integer in (net_cents,net_cents+extras);
 end if;
 if (p_data->>'status') is distinct from 'paid' or (p_data->>'currency') is distinct from 'BRL'
 or pricing_ok is not true then
  update public.bot_payment_events set status='payment_mismatch' where order_id=oid and event=p_event;
  return jsonb_build_object('result','payment_mismatch');
 end if;
 paid:=(p_data->>'paid_at')::timestamptz;
 if paid is null or paid>now()+interval '5 minutes' then raise exception 'invalid paid date'; end if;
 if subid is not null then
  select telegram_id into uid from public.bot_subscriptions where provider_subscription_id=subid order by expires_at desc limit 1;
 end if;
 if uid is null then
  select * into sess from public.bot_checkout_sessions where token=callback for update;
  if sess.token is not null and sess.plan_code=p.code and paid>=sess.created_at-interval '5 minutes'
   and paid<=sess.expires_at and (sess.claimed_order_id is null or sess.claimed_order_id=oid) then
   uid:=sess.telegram_id;
   update public.bot_checkout_sessions set claimed_order_id=oid where token=callback;
  end if;
 end if;
 if uid is null then
  update public.bot_payment_events set status='pending_identity' where order_id=oid and event=p_event;
  return jsonb_build_object('result','pending_identity');
 end if;
 perform 1 from public.bot_users where telegram_id=uid for update;
 select greatest(paid,coalesce(max(expires_at),paid)) into from_date from public.bot_subscriptions
 where telegram_id=uid and revoked_at is null;
 to_date:=from_date+make_interval(days=>coalesce(p.period_days,0),months=>coalesce(p.period_months,0));
 insert into public.bot_subscriptions(telegram_id,plan_code,provider_order_id,provider_subscription_id,starts_at,expires_at)
 values(uid,p.code,oid,subid,from_date,to_date);
 update public.bot_payment_events set status='applied',processed_at=now() where order_id=oid and event=p_event;
 return jsonb_build_object('result','applied');
end $$;
revoke all on function public.bot_process_payment(text,jsonb) from public,anon,authenticated;
grant execute on function public.bot_process_payment(text,jsonb) to service_role;
commit;
