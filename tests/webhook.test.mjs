import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import {handler,authentic,normalize} from '../supabase/functions/cakto-webhook/handler.ts';
const secret='local-test-secret';
const order={id:'order-1',status:'paid',currency:'BRL',amount:5,paidAt:'2026-10-21T00:00:00Z',
 checkoutUrl:'https://pay.cakto.com.br/365xjdo_1226651?callback=abc',callback:'abc',
 customer:{email:'do-not-persist@example.org'},offer:{id:'offer-1'},product:{id:'prod-1'},subscription:{id:'sub-1'}};
function signed(body,ts=Math.floor(Date.now()/1000)){
 const raw=JSON.stringify(body); const sig=createHmac('sha256',secret).update(ts+'.'+raw).digest('hex');
 return new Request('https://example.org',{method:'POST',body:raw,headers:{'X-Cakto-Signature':'v1='+sig,'X-Cakto-Timestamp':String(ts)}});
}
test('valid HMAC authenticates exact bytes',async()=>{const r=signed({data:order});assert.equal(await authentic(await r.text(),r.headers,secret),true)});
test('tampering, stale timestamps and downgrade rejected',async()=>{
 const r=signed({secret,data:order});const raw=await r.text();
 assert.equal(await authentic(raw+' ',r.headers,secret),false);
 const stale=signed({secret,data:order},1);assert.equal(await authentic(await stale.text(),stale.headers,secret),false);
 const bad=new Headers({'X-Cakto-Signature':'v1=wrong','X-Cakto-Timestamp':String(Math.floor(Date.now()/1000))});
 assert.equal(await authentic(raw,bad,secret),false);
});
test('legacy body secret accepted, wrong secret denied',async()=>{
 assert.equal(await authentic(JSON.stringify({secret}),new Headers(),secret),true);
 assert.equal(await authentic(JSON.stringify({secret:'wrong'}),new Headers(),secret),false);
});
test('normalization strips PII/secret and url query',()=>{
 const n=normalize({...order,secret});assert.equal(n.amount_cents,500);
 assert.equal(n.checkout_url,'https://pay.cakto.com.br/365xjdo_1226651');
 assert.equal(n.subscription_id,'sub-1');assert.ok(!('customer' in n));assert.ok(!('secret' in n));
 assert.equal(normalize({...order,checkoutUrl:'https://evil.com/foo'}).checkout_url,null);
 assert.throws(()=>normalize({...order,amount:'5.00'}));
});
test('unconfigured webhook fails closed',async()=>{
 const process=()=>{throw new Error('must not run')};assert.equal((await handler(undefined,process)(signed({}))).status,503);
});
test('V1 and V2 are processed, one delivery per order',async()=>{
 const calls=[];const h=handler(secret,async(e,d)=>{calls.push([e,d.id]);return {result:'applied'}});
 assert.equal((await h(signed({event:'purchase_approved',data:order}))).status,200);
 assert.equal((await h(signed({event:'subscription_renewed',data:[order,{...order,id:'order-2'}]}))).status,200);
 assert.equal(calls.length,3);
});
test('unauthorized, ignored event, malformed and oversized body',async()=>{
 let calls=0;const h=handler(secret,async()=>{calls++;});
 assert.equal((await h(new Request('https://example.org',{method:'POST',body:'{}'}))).status,401);
 assert.equal((await h(signed({event:'checkout_abandonment',data:{}}))).status,200);
 assert.equal((await h(signed({event:'purchase_approved',data:[]}))).status,400);
 assert.equal((await h(new Request('https://example.org',{method:'POST',body:'x'.repeat(262145)}))).status,413);
 assert.equal(calls,0);
});
test('database error is not acknowledged as success',async()=>{
 const h=handler(secret,async()=>{throw new Error('database down')});
 assert.equal((await h(signed({event:'purchase_approved',data:order}))).status,503);
});
