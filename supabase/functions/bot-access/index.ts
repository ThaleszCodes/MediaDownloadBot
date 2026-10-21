// SHA-256 verifier of a random backend-only credential. Override via Edge secrets for rotation.
const credentialHash = Deno.env.get('BOT_ACCESS_SECRET_SHA256') ?? 'be4c8b83d50a7cca6cc73c688c5f03537650676630220fa7cdc04c66216ca727';
Deno.serve(async (req: Request) => {
  if (req.method !== 'POST') return new Response('method', { status: 405 });
  const secret = req.headers.get('X-Bot-Secret') ?? '';
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(secret));
  const hash = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2,'0')).join('');
  if (!secret || hash !== credentialHash) return new Response('unauthorized', { status: 401 });
  try {
    const body = await req.text();
    if (body.length > 2048) return new Response('too large', { status: 413 });
    const {user,action,job,count} = JSON.parse(body);
    if (!Number.isSafeInteger(user) || user <= 0 || !['status','reserve','progress','finish'].includes(action)
       || !Number.isInteger(count) || count < 0 || count > 50
       || (job !== null && !/^[0-9a-f-]{36}$/i.test(job))) {
      return new Response('invalid', { status: 400 });
    }
    const keys = JSON.parse(Deno.env.get('SUPABASE_SECRET_KEYS') ?? '{}');
    const key = keys.default ?? Deno.env.get('SUPABASE_SERVICE_ROLE_KEY');
    const authHeaders: Record<string,string> = {'apikey':key,'Content-Type':'application/json'};
    if (!key.startsWith('sb_secret_')) authHeaders.Authorization = 'Bearer '+key;
    const res = await fetch(Deno.env.get('SUPABASE_URL') + '/rest/v1/rpc/bot_access', {
      method:'POST', headers:authHeaders,
      body:JSON.stringify({p_user:user,p_action:action,p_job:job,p_count:count})
    });
    if (!res.ok) return new Response('database unavailable', { status: 503 });
    return new Response(await res.text(), {headers:{'Content-Type':'application/json'}});
  } catch { return new Response('invalid request', {status:400}); }
});
