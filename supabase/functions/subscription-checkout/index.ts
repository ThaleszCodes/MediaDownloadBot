const page=(text:string,status=200)=>new Response(text.replace(/<[^>]*>/g,' ').trim(),{status,headers:{'Content-Type':'text/plain; charset=utf-8','Cache-Control':'no-store','Referrer-Policy':'no-referrer'}});
Deno.serve(async(req:Request)=>{
 if(!['GET','POST'].includes(req.method))return page('Método não permitido',405);
 const token=new URL(req.url).searchParams.get('token')??'';
 if(!/^[a-f0-9]{64}$/.test(token))return page('<h1>Link inválido</h1><p>Volte ao bot e gere um novo link de assinatura.</p>',400);
 try{
  const keys=JSON.parse(Deno.env.get('SUPABASE_SECRET_KEYS')??'{}');const key=keys.default??Deno.env.get('SUPABASE_SERVICE_ROLE_KEY');
  const headers:Record<string,string>={'apikey':key};if(!key.startsWith('sb_secret_'))headers.Authorization='Bearer '+key;
  const base=Deno.env.get('SUPABASE_URL')+'/rest/v1/';
  const sessionRes=await fetch(base+'bot_checkout_sessions?token=eq.'+token+'&select=plan_code,expires_at,claimed_order_id',{headers});
  if(!sessionRes.ok)throw new Error('database');const session=(await sessionRes.json())[0];
  if(!session||Date.parse(session.expires_at)<Date.now()||session.claimed_order_id)
   return page('<h1>Link encerrado</h1><p>Este link venceu ou já foi utilizado. Volte ao bot para consultar seu acesso ou gerar outro link.</p>',410);
  const planRes=await fetch(base+'bot_plans?code=eq.'+encodeURIComponent(session.plan_code)+'&select=name,price_cents,checkout_url,sales_enabled,period_days',{headers});
  if(!planRes.ok)throw new Error('database');const plan=(await planRes.json())[0];
  if(!plan?.sales_enabled)return page('<h1>Plano indisponível</h1><p>Tente novamente mais tarde.</p>',409);
  const target=new URL(plan.checkout_url);if(target.origin!=='https://pay.cakto.com.br')throw new Error('checkout');
  target.searchParams.set('callback',token);
  return new Response(null,{status:303,headers:{Location:target.toString(),'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}});

 }catch{return page('<h1>Tente novamente em instantes</h1><p>Não foi possível consultar esta assinatura.</p>',503);}
});
