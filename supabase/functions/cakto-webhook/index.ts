import { handler } from './handler.ts';
Deno.serve(handler(Deno.env.get('CAKTO_WEBHOOK_SECRET'), async (event,data)=>{
 const keys=JSON.parse(Deno.env.get('SUPABASE_SECRET_KEYS')??'{}');
 const key=keys.default??Deno.env.get('SUPABASE_SERVICE_ROLE_KEY');
 if(!key) throw new Error('backend key missing');
 const headers:Record<string,string>={'apikey':key,'Content-Type':'application/json'};
 if(!key.startsWith('sb_secret_')) headers.Authorization='Bearer '+key;
 const res=await fetch(Deno.env.get('SUPABASE_URL')+'/rest/v1/rpc/bot_process_payment',{
  method:'POST',headers,body:JSON.stringify({p_event:event,p_data:data}),signal:AbortSignal.timeout(5000)});
 if(!res.ok)throw new Error('database unavailable');
 return res.json();
}));
