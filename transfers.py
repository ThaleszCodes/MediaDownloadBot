"""Bounded ordered download pipeline and Telegram albums."""
import asyncio
from collections import deque
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path

import httpx
from telegram import InputMediaPhoto, InputMediaVideo, InputFile
from telegram.error import BadRequest, RetryAfter, TelegramError, NetworkError

from media import fetch_to, MAX_FILE

# Shared across all users; never more than three active media downloads.
DOWNLOAD_SLOTS = asyncio.Semaphore(3)
GROUP_BYTES = 64 * 1024 * 1024


async def ordered_downloads(client, items, directory):
    """Keep three files ahead, yield in album order, cancel before deleting tempdir."""
    async def fetch(index, kind, url):
        path = Path(directory) / f'{index}{".jpg" if kind == "photo" else ".mp4"}'
        try:
            async with DOWNLOAD_SLOTS:
                size = await fetch_to(client, url, MAX_FILE, path)
            return kind, path, size
        except (ValueError, httpx.HTTPError, OSError):
            path.unlink(missing_ok=True)
            return None

    source = iter(enumerate(items))
    pending = deque()
    def schedule():
        entry = next(source, None)
        if entry is not None:
            index, (kind, url) = entry
            pending.append(asyncio.create_task(fetch(index, kind, url)))

    for _ in range(3):
        schedule()
    current = None
    try:
        while pending:
            current = pending.popleft()
            result = await current
            current = None
            schedule()
            yield result
    finally:
        tasks = list(pending)
        if current is not None:
            tasks.append(current)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def telegram_call(factory):
    """Retry only explicit flood limits, never ambiguous transport timeouts."""
    for attempt in range(3):
        try:
            return await factory()
        except RetryAfter as exc:
            if attempt == 2:
                raise
            delay = exc.retry_after
            if isinstance(delay, timedelta):
                delay = delay.total_seconds()
            await asyncio.sleep(float(delay) + 0.1)


async def send_batch(bot, chat_id, batch):
    """Returns (sent, failed), falling back only for a definite BadRequest."""
    options = dict(chat_id=chat_id, write_timeout=180, read_timeout=180)

    async def single(kind, path):
        async def attempt():
            with path.open('rb') as stream:
                method = bot.send_photo if kind == 'photo' else bot.send_video
                key = 'photo' if kind == 'photo' else 'video'
                return await method(**{key: InputFile(stream, read_file_handle=False)}, **options)
        try:
            await telegram_call(attempt)
        except BadRequest:
            async def document():
                with path.open('rb') as stream:
                    return await bot.send_document(document=InputFile(stream, read_file_handle=False), **options)
            await telegram_call(document)

    try:
        if len(batch) > 1:
            async def group():
                with ExitStack() as stack:
                    media = []
                    for kind, path, _ in batch:
                        stream = stack.enter_context(path.open('rb'))
                        cls = InputMediaPhoto if kind == 'photo' else InputMediaVideo
                        media.append(cls(media=InputFile(stream, attach=True, read_file_handle=False)))
                    return await bot.send_media_group(media=media, **options)
            try:
                await telegram_call(group)
                return len(batch), 0
            except BadRequest:
                pass
            except NetworkError:
                raise  # Keep the reservation: delivery outcome is unknown.
            except TelegramError:
                # A timeout may mean Telegram received the whole album: do not duplicate it.
                return 0, len(batch)
        sent = failed = 0
        for kind, path, _ in batch:
            try:
                await single(kind, path)
                sent += 1
            except BadRequest:
                failed += 1
            except NetworkError:
                raise
            except TelegramError:
                failed += 1
        return sent, failed
    finally:
        for _, path, _ in batch:
            path.unlink(missing_ok=True)


async def transfer_items(client, items, directory, bot, chat_id, progress):
    """Upload batches while the bounded download window fills the next files."""
    sent = failed = total_bytes = 0
    batch = []

    async def flush():
        nonlocal sent, failed, total_bytes
        ok, errors = await send_batch(bot, chat_id, batch)
        sent += ok
        failed += errors
        batch.clear()
        total_bytes = 0
        await progress(sent, failed)

    stream = ordered_downloads(client, items, directory)
    try:
        async for result in stream:
            if result is None:
                failed += 1
                continue
            kind, path, size = result
            if batch and total_bytes + size > GROUP_BYTES:
                await flush()
            batch.append((kind, path, size))
            total_bytes += size
            # Start delivering after three files instead of waiting for ten.
            # Later batches stay large to minimize Telegram API requests.
            if len(batch) == (3 if sent == 0 and failed == 0 else 10):
                await flush()
        if batch:
            await flush()
    finally:
        await stream.aclose()
    return sent, failed
