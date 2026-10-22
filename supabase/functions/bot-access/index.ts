// SHA-256 verifier of a random backend-only credential. Override via Edge secrets for rotation.
const credentialHash = Deno.env.get('BOT_ACCESS_SECRET_SHA256') ?? '3a71828280f311c7c20d17ca46747eaf79363fe54fa7f38f068ae0a18ff42e8c';
Deno.serve(async (req: Request) => {
  if (req.method !== 'POST') return new Response('method', { status: 405 });
  const secret = req.headers.get('X-Bot-Secret') ?? '';
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(secret));
  const hash = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2,'0')).join('');
  if (!secret || hash !== credentialHash) return new Response('unauthorized', { status: 401 });
  try {
    const body = await req.text();
    if (body.length > 2048) return new Response('too large', { status: 413 });
    const {user,action,job,count,plan} = JSON.parse(body);
    if (!Number.isSafeInteger(user) || user <= 0 || !['status','reserve','progress','finish','account','plans','checkout','abandon'].includes(action)
       || !Number.isInteger(count) || count < 0 || count > 50
       || (job !== null && !/^[0-9a-f-]{36}$/i.test(job))) {
      return new Response('invalid', { status: 400 });
    }
    const keys = JSON.parse(Deno.env.get('SUPABASE_SECRET_KEYS') ?? '{}');
    const key = keys.default ?? Deno.env.get('SUPABASE_SERVICE_ROLE_KEY');
    const authHeaders: Record<string,string> = {'apikey':key,'Content-Type':'application/json'};
    if (!key.startsWith('sb_secret_')) authHeaders.Authorization = 'Bearer '+key;
    if(action==='checkout' && !['weekly','monthly'].includes(plan)) return new Response('invalid plan',{status:400});
    const rpc = action==='abandon'?'bot_abandon':action==='checkout'?'bot_create_checkout':action==='account'?'bot_account':action==='plans'?'bot_list_plans':'bot_access';
    const args = action==='abandon'?{p_user:user}:action==='checkout'?{p_user:user,p_plan:plan}:action==='account'?{p_user:user}:action==='plans'?{}:{p_user:user,p_action:action,p_job:job,p_count:count};
    const res = await fetch(Deno.env.get('SUPABASE_URL') + '/rest/v1/rpc/'+rpc, {
      method:'POST', headers:authHeaders,
      body:JSON.stringify(args)
    });
    if (!res.ok) return new Response('database unavailable', { status: 503 });
    const result=await res.json();
    if(action==='checkout') result.checkout_url=Deno.env.get('SUPABASE_URL')+'/functions/v1/subscription-checkout?token='+encodeURIComponent(result.token);
    return Response.json(result);
  } catch { return new Response('invalid request', {status:400}); }
});
