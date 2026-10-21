import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from telegram.error import BadRequest, RetryAfter, TimedOut
import transfers as t


class Pipeline(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        t.DOWNLOAD_SLOTS = asyncio.Semaphore(3)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bot = type('Bot', (), {})()
        for name in ['send_photo', 'send_video', 'send_document', 'send_media_group']:
            setattr(self.bot, name, AsyncMock())
        self.progress = AsyncMock()

    async def fake_fetch(self, client, url, limit, path):
        path.write_bytes(url.encode())
        await asyncio.sleep(0)
        return len(url)

    def items(self, count):
        return [('photo' if i % 2 else 'video', str(i)) for i in range(count)]

    async def test_batches_ten_then_single_preserve_order_and_cleanup(self):
        with patch.object(t, 'fetch_to', self.fake_fetch):
            result = await t.transfer_items(None, self.items(21), self.tmp.name, self.bot, 1, self.progress)
        self.assertEqual(result, (21, 0))
        self.assertEqual(self.bot.send_media_group.await_count, 2)
        self.assertEqual(self.bot.send_video.await_count, 1)
        media = self.bot.send_media_group.await_args_list[0].kwargs['media']
        self.assertEqual([m.media.input_file_content for m in media], [str(i).encode() for i in range(10)])
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    async def test_download_failure_does_not_stop_other_media(self):
        async def fetch(client, url, limit, path):
            if url == '1': raise ValueError('failed')
            return await self.fake_fetch(client, url, limit, path)
        with patch.object(t, 'fetch_to', fetch):
            result = await t.transfer_items(None, self.items(4), self.tmp.name, self.bot, 1, self.progress)
        self.assertEqual(result, (3, 1))

    async def test_downloads_overlap_upload_and_have_global_cap(self):
        active = peak = 0
        overlap = asyncio.Event()
        uploading = False
        async def fetch(client, url, limit, path):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.005)
                if uploading: overlap.set()
                path.write_bytes(b'x')
                return 1
            finally:
                active -= 1
        async def send(**kwargs):
            nonlocal uploading
            uploading = True
            await asyncio.wait_for(overlap.wait(), 1)
        self.bot.send_media_group.side_effect = send
        with patch.object(t, 'fetch_to', fetch):
            await t.transfer_items(None, self.items(20), self.tmp.name, self.bot, 1, self.progress)
        self.assertTrue(overlap.is_set())
        self.assertLessEqual(peak, 3)
        self.assertGreater(peak, 1)

    async def test_memory_budget_splits_before_count_limit(self):
        with patch.object(t, 'GROUP_BYTES', 3), patch.object(t, 'fetch_to', self.fake_fetch):
            self.assertEqual(await t.transfer_items(None, self.items(8), self.tmp.name, self.bot, 1, self.progress), (8, 0))
        self.assertEqual([len(c.kwargs['media']) for c in self.bot.send_media_group.await_args_list], [3, 3, 2])

    async def test_bad_group_falls_back_to_single_then_document(self):
        self.bot.send_media_group.side_effect = BadRequest('bad media')
        self.bot.send_photo.side_effect = BadRequest('bad size')
        with patch.object(t, 'fetch_to', self.fake_fetch):
            self.assertEqual(await t.transfer_items(None, self.items(2), self.tmp.name, self.bot, 1, self.progress), (2, 0))
        self.bot.send_document.assert_awaited_once()

    async def test_timeout_does_not_duplicate_album(self):
        self.bot.send_media_group.side_effect = TimedOut()
        with patch.object(t, 'fetch_to', self.fake_fetch):
            with self.assertRaises(TimedOut):
                await t.transfer_items(None, self.items(3), self.tmp.name, self.bot, 1, self.progress)
        self.bot.send_photo.assert_not_awaited()
        self.bot.send_video.assert_not_awaited()
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    async def test_retryafter_reopens_files(self):
        self.bot.send_media_group.side_effect = [RetryAfter(0), []]
        with patch.object(t, 'fetch_to', self.fake_fetch):
            self.assertEqual(await t.transfer_items(None, self.items(2), self.tmp.name, self.bot, 1, self.progress), (2, 0))
        self.assertEqual(self.bot.send_media_group.await_count, 2)
        self.bot.send_photo.assert_not_awaited()

    async def test_cancel_waits_for_download_tasks(self):
        active = 0
        started = asyncio.Event()
        async def fetch(client, url, limit, path):
            nonlocal active
            active += 1
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1
        with patch.object(t, 'fetch_to', fetch):
            task = asyncio.create_task(t.transfer_items(None, self.items(20), self.tmp.name, self.bot, 1, self.progress))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(active, 0)
