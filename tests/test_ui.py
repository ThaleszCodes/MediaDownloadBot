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
            with patch('bot.access',AsyncMock(return_value={'premium':False,'trial_remaining':0})):
                await bot.menu_action(self.update(q),None)
            q.answer.assert_awaited_once()
            q.edit_message_text.assert_awaited_once()
        self.assertNotIn('https://pay.',ui.PLANS)
