"""Exercise real PTB Updates and Application routing, not simplified callback objects."""
import json
import unittest
from unittest.mock import AsyncMock, patch
from telegram import Update
from telegram.request import BaseRequest
from bot import build_application

class Request(BaseRequest):
    def __init__(self): self.calls=[]
    @property
    def read_timeout(self): return 5
    async def initialize(self): pass
    async def shutdown(self): pass
    async def do_request(self,url,method,request_data=None,**kwargs):
        endpoint=url.rsplit('/',1)[-1]
        args=request_data.parameters if request_data else {}
        self.calls.append((endpoint,args))
        if endpoint=='getMe':
            result={'id':999,'is_bot':True,'first_name':'Test','username':'test_bot'}
        elif endpoint=='answerCallbackQuery':
            return 400,json.dumps({'ok':False,'error_code':400,'description':'Bad Request: query is too old'}).encode()
        else:
            result={'message_id':10,'date':1792590000,'chat':{'id':42,'type':'private'},'text':args.get('text','')}
        return 200,json.dumps({'ok':True,'result':result}).encode()

class Dispatcher(unittest.IsolatedAsyncioTestCase):
    async def test_real_callbacks_survive_expired_ack_and_open_both_screens(self):
        request=Request();app=build_application('123:TEST',request=request)
        async with app:
            for index,action in enumerate(('account','plans')):
                payload={'update_id':index,'callback_query':{'id':str(index),'chat_instance':'instance',
                    'from':{'id':42,'is_bot':False,'first_name':'Kaleby'},'data':'menu:'+action,
                    'message':{'message_id':10,'date':1792590000,'chat':{'id':42,'type':'private'},
                    'from':{'id':999,'is_bot':True,'first_name':'Bot'},'text':'Menu'}}}
                data={'premium':False,'trial_remaining':5} if action=='account' else [
                    {'code':'weekly','name':'Semanal','price_cents':500,'period_days':7,'sales_enabled':True}]
                with patch('bot.access',AsyncMock(return_value=data)):
                    await app.process_update(Update.de_json(payload,app.bot))
                texts=[args.get('text','') for name,args in request.calls if name in ('editMessageText','sendMessage')]
                self.assertIn('Minha conta' if action=='account' else 'Planos Premium',texts[-1])

    async def test_paid_download_flow_delivers_media_after_trial_is_exhausted(self):
        import httpx
        import bot
        request=Request()
        original=request.do_request
        async def do_request(url,method,request_data=None,**kwargs):
            if url.endswith('/answerCallbackQuery'):
                return 200, json.dumps({'ok':True,'result':True}).encode()
            if url.endswith('/sendMediaGroup'):
                args=request_data.parameters
                request.calls.append(('sendMediaGroup',args))
                count=len(args['media'])
                return 200,json.dumps({'ok':True,'result':[
                    {'message_id':100+i,'date':1792590000,'chat':{'id':42,'type':'private'}}
                    for i in range(count)]}).encode()
            return await original(url,method,request_data,**kwargs)
        request.do_request=do_request
        html='<div class="media-group">'+''.join(
            f'<div class="img"><img src="https://s1.erome.com/{i}.jpg"></div>' for i in range(7))+'</div>'
        def serve(req):
            return httpx.Response(200, content=html.encode() if '/a/' in req.url.path else b'test-photo')
        def client(url):
            return httpx.AsyncClient(transport=httpx.MockTransport(serve))
        actions=[]
        async def access(uid,action='status',job=None,count=0,**kwargs):
            actions.append((action,count))
            if action=='reserve': return {'quota':7,'trial':False}
            return {'premium':True,'trial_remaining':0}
        app=build_application('123:TEST',request=request)
        payload={'update_id':88,'callback_query':{'id':'download','chat_instance':'instance',
            'from':{'id':42,'is_bot':False,'first_name':'Kaleby'},'data':'all:Example',
            'message':{'message_id':10,'date':1792590000,'chat':{'id':42,'type':'private'},
            'from':{'id':999,'is_bot':True,'first_name':'Bot'},'text':'Escolha'}}}
        async with app:
            with patch('bot.client_for',client),patch('bot.access',access):
                await bot.choose(Update.de_json(payload,app.bot),None)
        texts=[args.get('text','') for name,args in request.calls if name in ('editMessageText','sendMessage')]
        self.assertTrue(any('7 mídia(s) enviada(s)' in text for text in texts))
        self.assertIn(('reserve',7), actions)
        self.assertIn(('finish',7), actions)
        self.assertEqual([len(args['media']) for name,args in request.calls if name=='sendMediaGroup'],[3,4])
        self.assertNotIn(42,bot.ACTIVE)
