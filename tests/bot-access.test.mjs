import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const secret='test-backend-only';let handle;
globalThis.Deno={env:{get(name){return {
 BOT_ACCESS_SECRET_SHA256:createHash('sha256').update(secret).digest('hex'),
 SUPABASE_SECRET_KEYS:JSON.stringify({default:'sb_secret_test'}),SUPABASE_URL:'https://project.supabase.co'
}[name]}},serve(fn){handle=fn}};
await import('../supabase/functions/bot-access/index.ts');
const req=(action,extra={})=>new Request('https://example.org',{method:'POST',headers:{'X-Bot-Secret':secret},body:JSON.stringify({user:42,action,job:null,count:0,...extra})});
test('routes account, plans, checkout to restricted RPC and binds user',async()=>{
 const original=globalThis.fetch;
 try{
  for(const [action,rpc,args] of [['account','bot_account',{p_user:42}],['plans','bot_list_plans',{}],['checkout','bot_create_checkout',{p_user:42,p_plan:'weekly'}]]){
   globalThis.fetch=async(url,opts)=>{
    assert.equal(url,'https://project.supabase.co/rest/v1/rpc/'+rpc);
    assert.deepEqual(JSON.parse(opts.body),args);
    assert.equal(opts.headers.apikey,'sb_secret_test');assert.ok(!opts.headers.Authorization);
    return Response.json(action==='checkout'?{token:'a'.repeat(64),checkout_url:'https://pay.cakto.com.br/example'}:{});
   };
   const res=await handle(req(action,{plan:'weekly'}));assert.equal(res.status,200);
   if(action==='checkout')assert.equal((await res.json()).checkout_url,'https://project.supabase.co/functions/v1/subscription-checkout?token='+'a'.repeat(64));
  }
 }finally{globalThis.fetch=original}
});
test('rejects missing auth and invalid plan before DB access',async()=>{
 assert.equal((await handle(new Request('https://example.org',{method:'POST',body:'{}'}))).status,401);
 assert.equal((await handle(req('checkout',{plan:'fake'}))).status,400);
});
