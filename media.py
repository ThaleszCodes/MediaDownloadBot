"""Public album parsing and bounded downloads; no login or access bypass."""
import re
from urllib.parse import urlsplit, urljoin
from bs4 import BeautifulSoup
import httpx

ALBUM = re.compile(r'https://(?:www\.)?erome\.com/a/([A-Za-z0-9]+)/*', re.I)
MAX_FILE = 49 * 1024 * 1024
MAX_ITEMS = 50


def album_id(text):
    match = ALBUM.fullmatch(text.strip())
    if not match:
        raise ValueError('Envie somente um link https://www.erome.com/a/IDDOALBUM')
    return match[1]


def safe_url(url):
    p = urlsplit(url)
    host = (p.hostname or '').lower()
    if (p.scheme != 'https' or p.username or p.password or p.port not in (None, 443)
            or not (host == 'erome.com' or host.endswith('.erome.com'))):
        raise ValueError('Endereço de mídia não permitido.')
    return url


def parse_album(html, base):
    soup = BeautifulSoup(html, 'html.parser')
    found, seen = [], set()
    for node in soup.select('.media-group .img img, .media-group video source, .media-group video[src]'):
        kind = 'photo' if node.name == 'img' else 'video'
        url = node.get('data-src') or node.get('src')
        if not url:
            continue
        url = safe_url(urljoin(base, url))
        if url not in seen:
            seen.add(url)
            found.append((kind, url))
    if len(found) > MAX_ITEMS:
        raise ValueError('Álbum grande demais: máximo de 50 mídias por pedido.')
    if not found:
        raise ValueError('Nenhuma mídia pública encontrada. Álbum removido, bloqueado ou formato alterado.')
    return found


async def fetch_to(client, url, limit, path=None):
    safe_url(url)
    # Redirects are intentionally refused, including redirects to login pages.
    async with client.stream('GET', url, follow_redirects=False) as response:
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError('O site redirecionou o pedido; não foi possível acessar.')
        length = response.headers.get('content-length', '')
        if length.isdigit() and int(length) > limit:
            raise ValueError('Arquivo acima do limite de envio do bot.')
        size, data = 0, bytearray()
        stream = path.open('wb') if path else None
        try:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > limit:
                    raise ValueError('Arquivo acima do limite de envio do bot.')
                if stream:
                    stream.write(chunk)
                else:
                    data.extend(chunk)
        finally:
            if stream:
                stream.close()
        return bytes(data) if path is None else size


def client_for(album):
    return httpx.AsyncClient(timeout=httpx.Timeout(60, connect=20), headers={
        'User-Agent': 'Mozilla/5.0', 'Referer': album,
    }, trust_env=False)
