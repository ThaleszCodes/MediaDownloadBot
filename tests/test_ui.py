import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from access import AccessUnavailable
import bot
import bot_ui as ui

class ChatUI(unittest.IsolatedAsyncioTestCase):
    def update(self, callback=None):
        message=SimpleNamespace(reply_text=AsyncMock())
        return SimpleNamespace(effective_chat=SimpleNamespace(type='private'),
            effective_user=SimpleNamespace(id=42,first_name='<Kaleby & teste>'),
            effective_message=message,callback_query=callback)

    async def test_start_escapes_user_and_has_working_navigation(self):
        update=self.update()
        with patch('bot.access',AsyncMock(return_value={'premium':False,'trial_remaining':5})):
            await bot.start(update,None)
        call=update.effective_message.reply_text.await_args
        self.assertIn('&lt;Kaleby &amp; teste&gt;',call.args[0])
        self.assertEqual(call.kwargs['parse_mode'],'HTML')
        keys=[b.callback_data for row in call.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertEqual(set(keys),{'menu:download','menu:account','menu:plans','menu:help'})

    async def test_menu_routes_to_account_and_formats_local_time(self):
        query=SimpleNamespace(data='menu:account',answer=AsyncMock(),edit_message_text=AsyncMock(),message=SimpleNamespace(chat=SimpleNamespace(type='private')))
        update=self.update(query)
        with patch('bot.access',AsyncMock(return_value={'premium':True,'expires_at':'2026-10-22T03:30:00Z'})):
            await bot.menu_action(update,None)
        query.answer.assert_awaited_once()
        text=query.edit_message_text.await_args.args[0]
        self.assertIn('22/10/2026 às 00h30',text)
        self.assertIn('Premium está ativo',text)

    async def test_backend_failure_keeps_menu_without_false_balance(self):
        update=self.update()
        with patch('bot.access',AsyncMock(side_effect=AccessUnavailable())):
            await bot.start(update,None)
        self.assertIn('indisponível',update.effective_message.reply_text.await_args.args[0])
        self.assertNotIn('5 mídias grátis',update.effective_message.reply_text.await_args.args[0])

    async def test_every_menu_button_answers_and_renders(self):
        for action in ['home','account','download','help','plans']:
            q=SimpleNamespace(data='menu:'+action,answer=AsyncMock(),edit_message_text=AsyncMock(),message=SimpleNamespace(chat=SimpleNamespace(type='private')))
            with patch('bot.access',AsyncMock(side_effect=lambda user, action='status': [] if action=='plans' else {'premium':False,'trial_remaining':0})):
                await bot.menu_action(self.update(q),None)
            q.answer.assert_awaited_once()
            self.assertGreaterEqual(q.edit_message_text.await_count,1)
        self.assertNotIn('https://pay.',ui.PLANS)

    async def test_plans_loaded_from_database_generate_subscription_buttons(self):
        offers=[{'code':'weekly','name':'Semanal','price_cents':500,'period_days':7,'sales_enabled':True},
                {'code':'monthly','name':'Mensal','price_cents':1590,'period_days':None,'sales_enabled':False}]
        update=self.update()
        with patch('bot.access',AsyncMock(return_value=offers)) as api:
            await bot.plans(update,None)
        api.assert_awaited_once_with(42,'plans')
        call=update.effective_message.reply_text.await_args
        self.assertIn('R$5,00',call.args[0])
        buttons=[b.callback_data for row in call.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertIn('subscribe:weekly',buttons)
        self.assertNotIn('subscribe:monthly',buttons)

    async def test_subscription_is_bound_to_callback_user(self):
        q=SimpleNamespace(data='subscribe:weekly',from_user=SimpleNamespace(id=42),answer=AsyncMock(),edit_message_text=AsyncMock(),message=SimpleNamespace(chat=SimpleNamespace(type='private')))
        update=self.update(q)
        with patch('bot.access',AsyncMock(return_value={'checkout_url':'https://example.org/individual-link'})) as api:
            await bot.subscribe(update,None)
        api.assert_awaited_once_with(42,'checkout',plan='weekly')
        buttons=q.edit_message_text.await_args.kwargs['reply_markup'].inline_keyboard
        self.assertEqual(buttons[0][0].url,'https://example.org/individual-link')
        self.assertEqual(buttons[1][0].callback_data,'menu:account')

    async def test_expired_callback_ack_does_not_block_account_or_plans(self):
        from telegram.error import BadRequest
        for action in ('account','plans'):
            q=SimpleNamespace(data='menu:'+action,answer=AsyncMock(side_effect=BadRequest('Query is too old')),
                edit_message_text=AsyncMock(),message=SimpleNamespace(chat=SimpleNamespace(type='private')))
            result=[] if action=='plans' else {'premium':False,'trial_remaining':5}
            with patch('bot.access',AsyncMock(return_value=result)):
                await bot.menu_action(self.update(q),None)
            self.assertEqual(q.edit_message_text.await_count,2)
            self.assertNotIn('Carregando',q.edit_message_text.await_args.args[0])

    async def test_premium_account_opens_without_termux_timezone_database(self):
        from zoneinfo import ZoneInfoNotFoundError
        update=self.update()
        state={'premium':True,'expires_at':'2026-10-28T15:39:47.241383+00:00',
               'telegram_id':42,'plan_name':'Semanal','total_delivered':5}
        with patch('bot.access',AsyncMock(return_value=state)), patch('bot_ui.ZoneInfo',side_effect=ZoneInfoNotFoundError()):
            await bot.account(update,None)
        text=update.effective_message.reply_text.await_args.args[0]
        self.assertIn('Premium está ativo',text)
        self.assertIn('28/10/2026 às 12h39',text)

    async def test_error_log_preserves_cause_without_leaking_token_or_urls(self):
        from telegram.error import BadRequest
        import os
        token='123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':token,'BOT_ACCESS_SECRET':'private-secret'}):
            result=bot.safe_error(BadRequest('File too large '+token+' private-secret https://example.org/private'))
        self.assertIn('BadRequest',result)
        self.assertIn('File too large',result)
        self.assertNotIn(token,result)
        self.assertNotIn('private-secret',result)
        self.assertNotIn('https://',result)
