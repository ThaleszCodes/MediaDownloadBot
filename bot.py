"""Telegram bot for authorized, non-explicit public media. Run: python bot.py."""
import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters
import httpx
from media import album_id, parse_album, fetch_to, client_for, MAX_FILE

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
        'Não faço classificação automática do conteúdo.')


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
        with tempfile.TemporaryDirectory(prefix='media-bot-') as tmp:
            for index, (media_kind, media_url) in enumerate(items, 1):
                await status.edit_text(f'Enviando {index}/{len(items)} · {sent} enviados · {failed} falhas')
                suffix = '.mp4' if media_kind == 'video' else '.jpg'
                path = Path(tmp) / f'media-{index}{suffix}'
                try:
                    await fetch_to(client, media_url, MAX_FILE, path)
                    with path.open('rb') as stream:
                        options = dict(chat_id=query.message.chat_id, write_timeout=120, read_timeout=120)
                        try:
                            if media_kind == 'photo':
                                await query.get_bot().send_photo(photo=stream, **options)
                            else:
                                await query.get_bot().send_video(video=stream, **options)
                        except BadRequest:
                            # Photos with dimensions/size Telegram cannot display are sent intact.
                            stream.seek(0)
                            await query.get_bot().send_document(document=stream, **options)
                    sent += 1
                except (ValueError, httpx.HTTPError, TelegramError):
                    failed += 1
                finally:
                    path.unlink(missing_ok=True)
                await asyncio.sleep(1.1)
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
        await query.message.reply_text('Pedido na fila. Até dois downloads simultâneos.')
        async with SLOTS:
            await asyncio.wait_for(download(query, kind, aid), timeout=600)
    except asyncio.TimeoutError:
        await query.message.reply_text('Tempo limite atingido. As mídias já enviadas permanecem no chat.')
    except (ValueError, httpx.HTTPError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'Não consegui acessar o álbum. Tente novamente mais tarde.'
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, link))
    app.add_handler(CallbackQueryHandler(choose, pattern=r'^(photo|video|all):[A-Za-z0-9]+$'))
    app.add_error_handler(error_handler)
    print('Bot iniciado. Abra o Telegram e envie /start. Ctrl+C para parar.', flush=True)
    app.run_polling(allowed_updates=['message', 'callback_query'], drop_pending_updates=True)


if __name__ == '__main__':
    main()
