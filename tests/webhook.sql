-- All fixtures and access grants are rolled back. Run against a disposable or existing project.
begin;
set local role service_role;
do $$
declare s jsonb; token text; d jsonb; count_before bigint; expiry timestamptz;
begin
 update public.bot_plans set sales_enabled=true where code='weekly';
 s:=public.bot_create_checkout(900000000101,'weekly'); token:=s->>'token';
 d:=jsonb_build_object('id','test-order-1','status','paid','currency','BRL','amount_cents',500,
 'checkout_url','https://pay.cakto.com.br/365xjdo_1226651','callback',token,
 'subscription_id','test-sub-1','paid_at',now());
 s:=public.bot_process_payment('purchase_approved',d); assert s->>'result'='applied','approval failed';
 s:=public.bot_access(900000000101,'status'); assert (s->>'premium')::boolean,'no premium';
 s:=public.bot_process_payment('purchase_approved',d); assert s->>'result'='duplicate','replay extended';
 s:=public.bot_process_payment('subscription_renewed',d); assert s->>'result'='duplicate_order','same order double-granted';
 select count(*) into count_before from public.bot_subscriptions where telegram_id=900000000101; assert count_before=1;
 s:=public.bot_process_payment('subscription_renewed',(d-'callback')||jsonb_build_object('id','test-order-2'));
 assert s->>'result'='applied','renewal not bound to subscription';
 s:=public.bot_process_payment('subscription_canceled',d); assert s->>'result'='observed';
 s:=public.bot_access(900000000101,'status'); assert (s->>'premium')::boolean,'cancellation removed paid access';
 s:=public.bot_process_payment('refund',d); assert s->>'result'='revoked';
 s:=public.bot_process_payment('purchase_approved',d); assert s->>'result'='duplicate';
 assert exists(select 1 from public.bot_subscriptions where provider_order_id='test-order-1' and revoked_at is not null),'refund revived';
 -- Tombstone before approval, even when first delivery is a refund.
 s:=public.bot_process_payment('chargeback',d||jsonb_build_object('id','test-order-3')); assert s->>'result'='revoked';
 s:=public.bot_process_payment('purchase_approved',d||jsonb_build_object('id','test-order-3')); assert s->>'result'='revoked';
 -- A second purchase cannot steal the original checkout session.
 s:=public.bot_process_payment('purchase_approved',(d-'subscription_id')||jsonb_build_object('id','test-order-4'));
 assert s->>'result'='pending_identity','session reuse accepted';
 -- Unbound, wrong amount, absent status/currency, and foreign offers fail closed.
 s:=public.bot_process_payment('purchase_approved',(d-'subscription_id'-'callback')||jsonb_build_object('id','test-order-5'));
 assert s->>'result'='pending_identity';
 s:=public.bot_process_payment('purchase_approved',d||jsonb_build_object('id','test-order-6','amount_cents',1)); assert s->>'result'='payment_mismatch';
 s:=public.bot_process_payment('purchase_approved',(d-'status')||jsonb_build_object('id','test-order-7')); assert s->>'result'='payment_mismatch';
 s:=public.bot_process_payment('purchase_approved',(d-'currency')||jsonb_build_object('id','test-order-8')); assert s->>'result'='payment_mismatch';
 s:=public.bot_process_payment('purchase_approved',(d-'subscription_id')||jsonb_build_object('id','test-order-9','checkout_url','https://pay.cakto.com.br/foreign'));
 assert s->>'result'='ignored_offer';
 -- Monthly uses calendar months, not fixed thirty-day expiry.
 update public.bot_plans set sales_enabled=true where code='monthly';
 s:=public.bot_create_checkout(900000000102,'monthly');
 s:=public.bot_process_payment('purchase_approved',jsonb_build_object('id','test-monthly','status','paid','currency','BRL','amount_cents',1590,
 'checkout_url','https://pay.cakto.com.br/xoxoxcr','callback',s->>'token','paid_at',now()));
 assert s->>'result'='applied';
 select expires_at into expiry from public.bot_subscriptions where provider_order_id='test-monthly';
 assert expiry=now()+interval '1 month','monthly duration incorrect';
end $$;
rollback;
