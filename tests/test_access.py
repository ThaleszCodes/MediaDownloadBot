import os
import unittest
from unittest.mock import patch
import httpx
from access import access, AccessUnavailable

class Access(unittest.IsolatedAsyncioTestCase):
    async def test_missing_configuration_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AccessUnavailable): await access(1)

    async def test_authenticated_request(self):
        real_client = httpx.AsyncClient
        def handler(req):
            self.assertEqual(req.headers['X-Bot-Secret'], 'private-test')
            self.assertEqual(req.url.path, '/functions/v1/bot-access')
            return httpx.Response(200, json={'trial_remaining':5,'premium':False})
        with patch.dict(os.environ, {'SUPABASE_URL':'https://example.com','BOT_ACCESS_SECRET':'private-test'}), patch('access.httpx.AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw)):
            self.assertEqual((await access(123))['trial_remaining'], 5)

    async def test_backend_failure_fails_closed(self):
        real_client = httpx.AsyncClient
        with patch.dict(os.environ, {'SUPABASE_URL':'https://example.com','BOT_ACCESS_SECRET':'test'}), patch('access.httpx.AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(lambda req:httpx.Response(503)),**kw)):
            with self.assertRaises(AccessUnavailable): await access(123)
