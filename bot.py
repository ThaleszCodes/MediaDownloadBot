"""Telegram bot for authorized, non-explicit public media. Run: python bot.py."""
import asyncio
import logging
import os
import tempfile
import time
import uuid
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters
import httpx
from media import album_id, parse_album, fetch_to, client_for
from transfers import transfer_items
from access import access, AccessUnavailable

log = logging.getLogger(__name__)
ACTIVE = set()
LAST = {}
SLOTS = asyncio.Semaphore(2)


async def start(update, context):
    await update.effective_message.reply_text(
        'Envie um link público https://www.erome.com/a/IDDOALBUM\n'
        'Vou mostrar as opções: fotos, vídeos ou todos.\n'
        'Use somente mídias não explícitas que você tem autorização para baixar.\n'
        'Limites: 50 mídias, 49 MiB por arquivo e 10 minutos por pedido.\n'
        'Você tem 5 mídias gratuitas por conta. Consulte /conta.\n'
        'Não faço classificação automática do conteúdo.')
    await account(update, context)


async def account(update, context):
    if update.effective_chat.type != 'private':
        return
    try:
        state = await access(update.effective_user.id)
        if state['premium']:
            text = f"Premium ativo. Vencimento: {state['expires_at']}"
        else:
            text = f"Teste grátis: {state['trial_remaining']} mídias restantes.\nEnvios confirmados descontam 1 por foto ou vídeo."
        await update.effective_message.reply_text(text)
    except AccessUnavailable as exc:
        await update.effective_message.reply_text(str(exc))


async def link(update, context):
    if update.effective_chat.type != 'private':
        return
    try:
        aid = album_id(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    keyboard = [[InlineKeyboardButton(label, callback_data=f'{kind}:{aid}')]
                for label, kind in [('Baixar fotos', 'photo'), ('Baixar vídeos', 'video'), ('Baixar Todos', 'all')]]
    await update.message.reply_text('O que você quer baixar?', reply_markup=InlineKeyboardMarkup(keyboard))


async def download(query, kind, aid):
    url = f'https://www.erome.com/a/{aid}'
    status = await query.message.reply_text('Consultando álbum…')
    sent, failed = 0, 0
    async with client_for(url) as client:
        html = await fetch_to(client, url, 4 * 1024 * 1024)
        items = [(k, u) for k, u in parse_album(html, url) if kind == 'all' or kind == k]
        if not items:
            await status.edit_text('Este álbum não tem mídias desse tipo.')
            return
        job = str(uuid.uuid4())
        reservation = await access(query.from_user.id, 'reserve', job, len(items))
        quota = reservation['quota']
        if quota == 0:
            await status.edit_text('Você já tem um pedido reservado. Consulte o suporte.' if reservation.get('busy')
                                   else 'Suas 5 mídias gratuitas acabaram. As assinaturas ainda estão em preparação.')
            return
        items = items[:quota]

        async def progress(sent, failed):
            await access(query.from_user.id, 'progress', job, sent)
            try:
                await status.edit_text(f'Enviando em álbuns · {sent}/{len(items)} enviados · {failed} falhas')
            except TelegramError:
                pass  # A progress message must never interrupt the transfer.

        await status.edit_text(f'Preparando {len(items)} mídias · até 3 downloads simultâneos…')
        with tempfile.TemporaryDirectory(prefix='media-bot-') as tmp:
            sent, failed = await transfer_items(
                client, items, tmp, query.get_bot(), query.message.chat_id, progress)
        # Only release reservations after a fully confirmed transfer. In a crash or
        # ambiguous Telegram timeout, keep the reservation for support reconciliation.
        await access(query.from_user.id, 'finish', job, sent)
    await status.edit_text(f'Concluído: {sent} enviados e {failed} falhas.\n'
                           'Falhas podem ser arquivos grandes, indisponíveis ou recusados pelo Telegram.')


async def choose(update, context):
    query = update.callback_query
    if query.message is None or query.message.chat.type != 'private':
        await query.answer()
        return
    uid = query.from_user.id
    if uid in ACTIVE:
        await query.answer('Você já tem um download em andamento.', show_alert=True)
        return
    if time.monotonic() - LAST.get(uid, -100) < 30:
        await query.answer('Aguarde 30 segundos entre pedidos.', show_alert=True)
        return
    kind, aid = query.data.split(':', 1)
    await query.answer('Pedido recebido')
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
        await query.message.reply_text('Pedido na fila. Até dois pedidos simultâneos.')
        async with SLOTS:
            await asyncio.wait_for(download(query, kind, aid), timeout=600)
    except asyncio.TimeoutError:
        await query.message.reply_text('Tempo limite atingido. As mídias já enviadas permanecem no chat.')
    except (ValueError, httpx.HTTPError, AccessUnavailable) as exc:
        message = str(exc) if isinstance(exc, (ValueError, AccessUnavailable)) else 'Não consegui acessar o álbum. Tente novamente mais tarde.'
        await query.message.reply_text(message)
    except TelegramError:
        log.warning('Falha de comunicação com Telegram (detalhes omitidos).')
    finally:
        ACTIVE.discard(uid)


async def error_handler(update, context):
    # Never log raw errors/URLs: they can contain the bot token or album links.
    log.error('Erro não tratado: %s', type(context.error).__name__)
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text('Ocorreu um erro. Tente novamente.')
        except TelegramError:
            pass


def main():
    load_dotenv()
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        raise SystemExit('Preencha TELEGRAM_BOT_TOKEN no arquivo .env antes de iniciar.')
    logging.basicConfig(level=logging.WARNING)
    app = Application.builder().token(token).concurrent_updates(8).build()
    app.add_handler(CommandHandler(['start', 'help'], start))
    app.add_handler(CommandHandler('conta', account))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, link))
    app.add_handler(CallbackQueryHandler(choose, pattern=r'^(photo|video|all):[A-Za-z0-9]+$'))
    app.add_error_handler(error_handler)
    print('Bot iniciado. Abra o Telegram e envie /start. Ctrl+C para parar.', flush=True)
    app.run_polling(allowed_updates=['message', 'callback_query'], drop_pending_updates=True)


if __name__ == '__main__':
    main()
