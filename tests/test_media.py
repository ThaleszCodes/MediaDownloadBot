import unittest
import httpx
from media import album_id, safe_url, parse_album, fetch_to

class Parser(unittest.TestCase):
    def test_links(self):
        self.assertEqual(album_id('https://www.erome.com/a/Ab12'), 'Ab12')
        for url in ['http://erome.com/a/a', 'https://erome.com.evil/a/a', 'https://erome.com/a/a?x=1']:
            with self.assertRaises(ValueError): album_id(url)
    def test_media(self):
        html = '''<img src="avatar"><div class="media-group"><div class="img"><img data-src="https://s1.erome.com/a.jpg"></div><video><source src="https://v1.erome.com/a.mp4"></video></div>'''
        self.assertEqual(parse_album(html, 'https://erome.com/a/test'), [('photo', 'https://s1.erome.com/a.jpg'), ('video', 'https://v1.erome.com/a.mp4')])
    def test_empty_and_external(self):
        with self.assertRaises(ValueError): parse_album('', 'https://erome.com/a/a')
        for url in ['https://localhost/a', 'https://erome.com@evil.com/a', 'https://erome.com:444/a']:
            with self.assertRaises(ValueError): safe_url(url)
    def test_dedupe_and_limit(self):
        item = '<video src="https://erome.com/0.mp4"></video>'
        self.assertEqual(len(parse_album('<div class="media-group">'+item*2+'</div>', 'https://erome.com/a/a')), 1)
        html = '<div class="media-group">'+''.join(f'<video src="https://erome.com/{i}.mp4"></video>' for i in range(51))+'</div>'
        with self.assertRaises(ValueError): parse_album(html, 'https://erome.com/a/a')

class Transfer(unittest.IsolatedAsyncioTestCase):
    async def test_limit(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'1234'))) as client:
            self.assertEqual(await fetch_to(client, 'https://erome.com/a/a', 4), b'1234')
            with self.assertRaises(ValueError): await fetch_to(client, 'https://erome.com/a/a', 3)
    async def test_redirect(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={'location':'https://evil.com'}))) as client:
            with self.assertRaises((ValueError, httpx.HTTPError)): await fetch_to(client, 'https://erome.com/a/a', 10)
