"""Server-to-server access to the project's restricted Edge Function."""
import os
import httpx

class AccessUnavailable(Exception):
    pass

async def access(user, action='status', job=None, count=0):
    url = os.getenv('SUPABASE_URL', '').rstrip('/')
    secret = os.getenv('BOT_ACCESS_SECRET', '')
    if not url or not secret:
        raise AccessUnavailable('Controle de acesso não configurado.')
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url + '/functions/v1/bot-access',
                headers={'X-Bot-Secret': secret},
                json={'user': user, 'action': action, 'job': job, 'count': count})
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AccessUnavailable('Não foi possível consultar seu acesso. Tente mais tarde.') from exc
