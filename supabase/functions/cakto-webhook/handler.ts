// No payload, customer data, or secret is ever logged or stored verbatim.
const EVENTS = new Set(['purchase_approved','subscription_renewed','subscription_late_recovered',
 'refund','chargeback','subscription_canceled','subscription_paused','subscription_resumed',
 'subscription_late','subscription_renewal_refused','refund_requested']);
const enc = new TextEncoder();

async function equal(a: string,b: string): Promise<boolean> {
 const [x,y] = await Promise.all([a,b].map(s=>crypto.subtle.digest('SHA-256',enc.encode(s))));
 const xa=new Uint8Array(x), ya=new Uint8Array(y); let diff=0;
 for(let i=0;i<xa.length;i++) diff|=xa[i]^ya[i];
 return diff===0;
}

export async function authentic(raw: string,headers: Headers,secret: string,now=Date.now()):Promise<boolean> {
 const signature=headers.get('X-Cakto-Signature');
 if(signature || headers.has('X-Cakto-Timestamp')) {
  const ts=headers.get('X-Cakto-Timestamp')??'';
  if(!/^\d+$/.test(ts) || Math.abs(now/1000-Number(ts))>300) return false;
  const key=await crypto.subtle.importKey('raw',enc.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);
  const sig=await crypto.subtle.sign('HMAC',key,enc.encode(ts+'.'+raw));
  const expected='v1='+Array.from(new Uint8Array(sig), b=>b.toString(16).padStart(2,'0')).join('');
  for(const part of (signature??'').split(',')) if(await equal(part.trim(),expected)) return true;
  return false; // Never downgrade a bad signature to body-secret authentication.
 }
 // Documented legacy deliveries: body secret still supported.
 try { const body=JSON.parse(raw); return typeof body.secret==='string' && await equal(body.secret,secret); }
 catch { return false; }
}

export function normalize(data: any): Record<string,unknown> {
 if(!data || typeof data!=='object' || Array.isArray(data) || typeof data.id!=='string' || !data.id || data.id.length>255)
  throw new Error('invalid order');
 const url=data.checkoutUrl ? new URL(data.checkoutUrl) : null;
 const amount=data.amount;
 if(amount!==null && amount!==undefined && (typeof amount!=='number' || !Number.isFinite(amount) || amount<0)) throw new Error('invalid amount');
 const cents=typeof amount==='number'? Math.round(amount*100):null;
 const callback=typeof data.callback==='string' && /^[A-Za-z0-9._~-]{1,255}$/.test(data.callback)?data.callback:null;
 return {id:data.id, status:data.status??null, currency:data.currency??null, amount_cents:cents,
  checkout_url:url && url.protocol==='https:' && url.hostname==='pay.cakto.com.br' && !url.username && !url.password && !url.port
   ? 'https://pay.cakto.com.br'+url.pathname.replace(/\/$/,''):null,
  offer_id:data.offer?.id??null,product_id:data.product?.id??null,
  subscription_id:data.subscription?.id?String(data.subscription.id):null,callback,
  paid_at:data.paidAt??null};
}

export function handler(secret: string|undefined, process: (event:string,data:Record<string,unknown>)=>Promise<unknown>) {
 return async (req:Request):Promise<Response> => {
  if(req.method!=='POST') return new Response('method not allowed',{status:405});
  if(!secret) return new Response('webhook secret not configured',{status:503});
  try {
   // Bound bytes even when content-length is missing or dishonest.
   const reader=req.body?.getReader(); if(!reader) return new Response('empty',{status:400});
   const chunks:Uint8Array[]=[]; let size=0;
   while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;
    if(size>262144){await reader.cancel();return new Response('too large',{status:413});}chunks.push(value);}
   const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
   const raw=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
   if(!await authentic(raw,req.headers,secret)) return new Response('unauthorized',{status:401});
   const payload=JSON.parse(raw);
   if(!EVENTS.has(payload.event)) return Response.json({result:'ignored_event'});
   const rows=Array.isArray(payload.data)?payload.data:[payload.data];
   if(rows.length===0 || rows.length>20) return new Response('invalid batch',{status:400});
   // Validate every entry before processing. Database operations are idempotent
   // if an entry fails after earlier ones committed; operator can safely replay.
   const data=rows.map(normalize);
   const results=[];
   for(const row of data) results.push(await process(payload.event,row));
   return Response.json({results});
  } catch(error) {
   return new Response(error instanceof TypeError || error instanceof SyntaxError?'invalid payload':'processing failed',
    {status:error instanceof TypeError || error instanceof SyntaxError?400:503});
  }
 };
}
