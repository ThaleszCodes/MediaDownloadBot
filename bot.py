"""Telegram bot for authorized, non-explicit public media. Run: python bot.py."""
import asyncio
import logging
import re
import os
import tempfile
import time
import uuid
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters
import httpx
from media import album_id, parse_album, fetch_to, client_for
from transfers import transfer_items
from access import access, AccessUnavailable
import bot_ui as ui

log = logging.getLogger(__name__)
ACTIVE = set()
LAST = {}
SLOTS = asyncio.Semaphore(2)
VERSION = '2026.10.21-telegram-diagnostics'


def safe_error(error):
    detail = str(error)
    for name in ('TELEGRAM_BOT_TOKEN', 'BOT_ACCESS_SECRET'):
        secret = os.getenv(name, '')
        if secret:
            detail = detail.replace(secret, '[segredo oculto]')
    detail = re.sub(r'https?://[^\s]+', '[URL oculta]', detail)
    detail = re.sub(r'\b\d{5,}:[A-Za-z0-9_-]{20,}', '[token oculto]', detail)
    return f'{type(error).__name__}: {detail[:300]}'


async def answer_callback(query, text=None):
    try:
        await query.answer(text)
    except TelegramError as exc:
        # Old callback IDs can no longer be acknowledged, but the menu must still open.
        log.warning('Confirmação de botão: %s', safe_error(exc))


async def show(update, text, keyboard=None):
    keyboard = keyboard if keyboard is not None else ui.menu()
    options = dict(parse_mode='HTML', reply_markup=keyboard)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, **options)
        except TelegramError:
            # Editing can fail for old or unchanged messages; send a fresh menu.
            await update.effective_message.reply_text(text, **options)
    else:
        await update.effective_message.reply_text(text, **options)


async def start(update, context):
    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text('👋 Abra minha conversa privada e envie /start para começar.')
        return
    try:
        state = await access(update.effective_user.id)
    except AccessUnavailable:
        state = None
    await show(update, ui.welcome(update.effective_user.first_name, state))


async def account(update, context):
    if update.effective_chat.type != 'private':
        return
    try:
        state = await access(update.effective_user.id, 'account')
        text = ui.account_text(state)
    except AccessUnavailable:
        text = '⏳ <b>Seu saldo está indisponível agora</b>\n\nTente novamente em instantes. Seu saldo continua salvo.'
    await show(update, text)


async def help_command(update, context):
    if update.effective_chat.type == 'private':
        await show(update, ui.HELP, ui.back())


async def plans(update, context):
    if update.effective_chat.type != 'private':
        return
    try:
        offers = await access(update.effective_user.id, 'plans')
        await show(update, ui.plans_text(offers), ui.plans_keyboard(offers))
    except AccessUnavailable:
        await show(update, '⏳ <b>Não consegui carregar os planos</b>\n\nTente novamente em instantes.')


async def subscribe(update, context):
    query = update.callback_query
    await answer_callback(query, 'Preparando seu acesso…')
    if not query.message or query.message.chat.type != 'private':
        return
    plan = query.data.split(':', 1)[1]
    try:
        result = await access(query.from_user.id, 'checkout', plan=plan)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton('🌐 Continuar no site', url=result['checkout_url'])],
            [InlineKeyboardButton('🔄 Verificar pagamento', callback_data='menu:account')],
            [InlineKeyboardButton('⬅️ Voltar aos planos', callback_data='menu:plans')],
        ])
        await show(update, '🔐 <b>Seu link individual está pronto</b>\n\n'
                   'Continue no site da Cakto para conferir o plano e efetuar o pagamento.\n'
                   'O acesso será vinculado a <b>esta conta do Telegram</b>; não compartilhe o link.\n\n'
                   'Após o pagamento, toque em <b>Verificar pagamento</b>. '
                   'A liberação depende da confirmação enviada pela Cakto.', keyboard)
    except AccessUnavailable:
        await show(update, '⏳ <b>Não consegui preparar a assinatura</b>\n\n'
                   'O plano pode estar temporariamente indisponível. Tente novamente em instantes.')


async def menu_action(update, context):
    query = update.callback_query
    await answer_callback(query)
    if not query.message or query.message.chat.type != 'private':
        return
    action = query.data.split(':', 1)[1]
    if action == 'home':
        await start(update, context)
    elif action == 'account':
        await show(update, '⏳ <b>Abrindo sua conta…</b>', ui.back())
        await account(update, context)
    elif action == 'help':
        await help_command(update, context)
    elif action == 'plans':
        await show(update, '⏳ <b>Carregando os planos…</b>', ui.back())
        await plans(update, context)
    elif action == 'download':
        await show(update, ui.DOWNLOAD, ui.back())


async def setup_commands(app):
    await app.bot.set_my_commands([
        BotCommand('start', '🏠 Abrir menu inicial'),
        BotCommand('conta', '👤 Consultar saldo e assinatura'),
        BotCommand('planos', '💎 Conhecer os planos'),
        BotCommand('help', '❓ Como usar o bot'),
    ])


async def link(update, context):
    if update.effective_chat.type != 'private':
        return
    label = update.message.text.strip().casefold()
    if label in ('conta', 'minha conta', '👤 minha conta', '👤 conta'):
        await account(update, context)
        return
    if label in ('planos', '💎 planos'):
        await plans(update, context)
        return
    try:
        aid = album_id(update.message.text)
    except ValueError:
        await show(update, '🔗 <b>Preciso de um link de álbum válido</b>\n\nEnvie só o link, neste formato:\n<code>https://www.erome.com/a/IDDOALBUM</code>\n\nVocê pode consultar <b>Como funciona</b> no menu.')
        return
    keyboard = [[InlineKeyboardButton(label, callback_data=f'{kind}:{aid}')]
                for label, kind in [('📸 Baixar fotos', 'photo'), ('🎬 Baixar vídeos', 'video'), ('📦 Baixar todos', 'all')]]
    await update.message.reply_text('🔗 <b>Link recebido!</b>\n\nO que você quer baixar deste álbum? 👇', parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def download(query, kind, aid):
    url = f'https://www.erome.com/a/{aid}'
    status = await query.message.reply_text('🔎 Buscando as mídias do seu álbum…')
    sent, failed = 0, 0
    async with client_for(url) as client:
        html = await fetch_to(client, url, 4 * 1024 * 1024)
        items = [(k, u) for k, u in parse_album(html, url) if kind == 'all' or kind == k]
        if not items:
            await status.edit_text('📭 Não encontrei esse tipo de mídia no álbum. Envie o link de novo e escolha outra opção.')
            return
        job = str(uuid.uuid4())
        reservation = await access(query.from_user.id, 'reserve', job, len(items))
        quota = reservation['quota']
        if quota == 0:
            await status.edit_text('⏳ Seu pedido anterior ainda tem mídias reservadas. Se ele foi interrompido, será necessário revisar o saldo antes de tentar novamente.' if reservation.get('busy')
                                   else '🎁 Você usou suas 5 mídias grátis! As assinaturas estão em preparação. Acompanhe a disponibilidade em /planos.')
            return
        items = items[:quota]

        async def progress(sent, failed):
            await access(query.from_user.id, 'progress', job, sent)
            try:
                await status.edit_text(ui.progress(sent, failed, len(items)), parse_mode='HTML')
            except TelegramError:
                pass  # A progress message must never interrupt the transfer.

        await status.edit_text(f'📦 <b>Preparando {len(items)} mídia(s)</b>\n\nVou enviar até o limite disponível na sua conta.\n<i>Já já seus arquivos aparecem por aqui…</i>', parse_mode='HTML')
        with tempfile.TemporaryDirectory(prefix='media-bot-') as tmp:
            sent, failed = await transfer_items(
                client, items, tmp, query.get_bot(), query.message.chat_id, progress)
        # Only release reservations after a fully confirmed transfer. In a crash or
        # ambiguous Telegram timeout, keep the reservation for support reconciliation.
        await access(query.from_user.id, 'finish', job, sent)
    await status.edit_text(ui.complete(sent, failed), parse_mode='HTML', reply_markup=ui.again())


async def choose(update, context):
    query = update.callback_query
    if query.message is None or query.message.chat.type != 'private':
        await query.answer()
        return
    uid = query.from_user.id
    if uid in ACTIVE:
        await query.answer('⏳ Já estou preparando seu álbum. Aguarde ele terminar.', show_alert=True)
        return
    if time.monotonic() - LAST.get(uid, -100) < 30:
        await query.answer('⏱ Aguarde alguns segundos antes de iniciar outro pedido.', show_alert=True)
        return
    kind, aid = query.data.split(':', 1)
    await query.answer('✅ Vamos lá!')
    ACTIVE.add(uid)
    LAST[uid] = time.monotonic()
    # Bound memory without retaining a permanent user history.
    if len(LAST) > 1000:
        cutoff = time.monotonic() - 30
        for key in list(LAST):
            if LAST[key] < cutoff:
                LAST.pop(key, None)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text('⏳ Pedido recebido! Vou começar assim que houver uma vaga na fila.')
        async with SLOTS:
            await asyncio.wait_for(download(query, kind, aid), timeout=600)
    except asyncio.TimeoutError:
        await query.message.reply_text('⏳ Este pedido demorou mais que o esperado e foi interrompido. As mídias já enviadas continuam aqui. Se o saldo ficou reservado, será necessário revisar o pedido.')
    except (ValueError, httpx.HTTPError, AccessUnavailable) as exc:
        message = ('⏳ Não consegui consultar seu acesso. Tente novamente em instantes.' if isinstance(exc, AccessUnavailable) else '⚠️ Não consegui concluir este álbum. Confira se ele é público e está disponível, ou tente outro link. Se o envio já tinha começado, seu saldo pode precisar de revisão.')
        await query.message.reply_text(message)
    except TelegramError as exc:
        log.warning('Falha no pedido: %s', safe_error(exc))
        try:
            await query.message.reply_text('📡 A conexão com o Telegram foi interrompida. Confira as mídias recebidas; para evitar duplicação, não reenviei os arquivos automaticamente.', reply_markup=ui.again())
        except TelegramError:
            pass
    finally:
        ACTIVE.discard(uid)


async def error_handler(update, context):
    # Never log raw errors/URLs: they can contain the bot token or album links.
    log.error('Erro não tratado: %s', safe_error(context.error))
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text('⚠️ Algo não saiu como esperado. Tente novamente em instantes ou abra o menu com /start.')
        except TelegramError:
            pass


def build_application(token, request=None):
    builder = Application.builder().token(token).concurrent_updates(8).post_init(setup_commands)
    if request is not None:
        builder = builder.request(request).get_updates_request(request)
    app = builder.build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('planos', plans))
    app.add_handler(CommandHandler(['conta', 'account'], account))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, link))
    app.add_handler(CallbackQueryHandler(subscribe, pattern=r'^subscribe:(weekly|monthly)$'))
    app.add_handler(CallbackQueryHandler(menu_action, pattern=r'^menu:(home|account|help|plans|download)$'))
    app.add_handler(CallbackQueryHandler(choose, pattern=r'^(photo|video|all):[A-Za-z0-9]+$'))
    app.add_error_handler(error_handler)
    return app


def main():
    load_dotenv()
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        raise SystemExit('Preencha TELEGRAM_BOT_TOKEN no arquivo .env antes de iniciar.')
    logging.basicConfig(level=logging.WARNING)
    app = build_application(token)
    print(f'Bot {VERSION} iniciado. Abra /start no Telegram. Ctrl+C para parar.', flush=True)
    app.run_polling(allowed_updates=['message', 'callback_query'], drop_pending_updates=True)


if __name__ == '__main__':
    main()
