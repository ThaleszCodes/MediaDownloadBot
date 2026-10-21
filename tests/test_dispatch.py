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
