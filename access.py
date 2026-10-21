"""Server-to-server access to the project's restricted Edge Function."""
import os
import logging
import httpx

class AccessUnavailable(Exception):
    pass

async def access(user, action='status', job=None, count=0, plan=None):
    url = os.getenv('SUPABASE_URL', '').rstrip('/')
    secret = os.getenv('BOT_ACCESS_SECRET', '')
    if not url or not secret:
        raise AccessUnavailable('Controle de acesso não configurado.')
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8, connect=4)) as client:
            response = await client.post(url + '/functions/v1/bot-access',
                headers={'X-Bot-Secret': secret},
                json={'user': user, 'action': action, 'job': job, 'count': count, 'plan': plan})
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        code = getattr(getattr(exc, 'response', None), 'status_code', None)
        logging.getLogger(__name__).warning('Access action=%s failed: %s status=%s', action, type(exc).__name__, code)
        raise AccessUnavailable('Não foi possível consultar seu acesso. Tente mais tarde.') from exc
