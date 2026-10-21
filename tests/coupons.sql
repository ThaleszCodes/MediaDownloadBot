begin;
set local role service_role;
do $$
declare s jsonb; d jsonb; token text;
begin
 s:=public.bot_create_checkout(900000000301,'weekly');token:=s->>'token';
 d:=jsonb_build_object('id','coupon-test-1','status','paid','currency','BRL',
 'checkout_url','https://pay.cakto.com.br/365xjdo_1226651','callback',token,'paid_at',now(),
 'amount_cents',499,'base_amount_cents',500,'discount_cents',100,'charged_fees_cents',99,'coupon_code','TEST1');
 s:=public.bot_process_payment('purchase_approved',d); assert s->>'result'='applied','coupon with buyer fee failed';
 s:=public.bot_process_payment('purchase_approved',d); assert s->>'result'='duplicate';
 assert (select count(*) from public.bot_subscriptions where telegram_id=900000000301)=1;
 s:=public.bot_create_checkout(900000000302,'weekly');
 s:=public.bot_process_payment('purchase_approved',d||jsonb_build_object('id','coupon-test-2','callback',s->>'token','amount_cents',400));
 assert s->>'result'='applied','net-only provider amount failed';
 s:=public.bot_process_payment('purchase_approved',d||jsonb_build_object('id','coupon-test-3','amount_cents',399));
 assert s->>'result'='payment_mismatch','unexplained amount accepted';
 s:=public.bot_process_payment('purchase_approved',d||jsonb_build_object('id','coupon-test-4','base_amount_cents',400));
 assert s->>'result'='payment_mismatch','wrong base price accepted';
 s:=public.bot_process_payment('purchase_approved',(d-'coupon_code')||jsonb_build_object('id','coupon-test-5'));
 assert s->>'result'='payment_mismatch','discount without coupon accepted';
 s:=public.bot_process_payment('purchase_approved',(d-'charged_fees_cents')||jsonb_build_object('id','coupon-test-6'));
 assert s->>'result'='payment_mismatch','unexplained fee accepted';
 assert exists(select 1 from public.bot_payment_events where order_id='coupon-test-1' and payment_details->>'discount_cents'='100');
end $$;
rollback;
