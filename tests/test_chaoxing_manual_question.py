"""Offline assessment handoff: no answer clicks, no timeout while waiting."""
import asyncio
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from playwright.async_api import async_playwright
from modules.chaoxing_adapter import ChaoxingRunner, has_video_question


class ManualVideoQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_past_stall_timeout_and_continues_after_manual_submission(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            try:
                page = await browser.new_page()
                await page.route("**/*", lambda route: route.abort())
                await page.set_content('''<div id="video"><video></video>
                    <div id="question" role="dialog"><input type="checkbox" aria-label="Offline option">
                    <button onclick="window.submits++;document.querySelector('#question').remove()">提交</button></div>
                    <button aria-label="播放" onclick="window.plays++">播放</button></div>
                    <script>window.submits=0;window.plays=0;</script>''')
                with TemporaryDirectory() as root:
                    Path(root, "logs").mkdir()
                    config = SimpleNamespace(course_urls=["https://mooc1.chaoxing.com/mycourse/studentstudy?courseId=1"],
                                             chaoxingSpeed=2, limitMaxTime=0)
                    runner = ChaoxingRunner(config, Mock(runtime_root=root))
                    runner.page = page
                    runner.safe_screenshot = AsyncMock(return_value=True)
                    async def markers(scope):
                        played = await page.evaluate("window.plays > 0")
                        return [{"video": True, "label": "任务点已完成" if played else "任务点未完成"}]

                    runner.markers = AsyncMock(side_effect=markers)
                    clock = [0]
                    real_sleep = asyncio.sleep

                    async def tick(seconds):
                        clock[0] += 60
                        await real_sleep(0.03)

                    async def snapshot(player):
                        played = await page.evaluate("window.plays > 0")
                        return {"currentTime": 746.816 if played else 413.499,
                                "duration": 746.816, "paused": True,
                                "ended": played, "playbackRate": 2, "error": None}

                    with patch('modules.chaoxing_adapter.time', SimpleNamespace(monotonic=lambda: clock[0], strftime=time.strftime)), \
                         patch('modules.chaoxing_adapter.asyncio', SimpleNamespace(sleep=tick)), \
                         patch('modules.chaoxing_adapter.media_snapshot', side_effect=snapshot):
                        task = asyncio.create_task(runner.play_video_task(page, page, {'title': 'Offline'}, 'cur1'))
                        try:
                            for _ in range(100):
                                if runner.state['status'] == 'waiting_question' and clock[0] > 240:
                                    break
                                await real_sleep(0.02)
                            self.assertEqual(runner.state['status'], 'waiting_question')
                            self.assertGreater(clock[0], 180)
                            self.assertFalse(task.done())
                            self.assertEqual(await page.evaluate('[window.submits,window.plays]'), [0, 0])
                            self.assertFalse(await page.get_by_role('checkbox').is_checked())
                            self.assertEqual(runner.state['video_completed_tasks'], [])
                            # Test harness represents manual action on a local fixture only.
                            await page.get_by_role('button', name='提交', exact=True).click()
                            self.assertTrue(await asyncio.wait_for(task, 5))
                            self.assertEqual(runner.state['video_completed_tasks'], ['cur1'])
                            self.assertEqual(await page.evaluate('[window.submits,window.plays]'), [1, 1])
                            self.assertIsNone(runner.state['question_task_key'])
                        finally:
                            task.cancel()
                            await asyncio.gather(task, return_exceptions=True)
            finally:
                await browser.close()

    async def test_verification_during_manual_wait_still_requires_user_action(self):
        with TemporaryDirectory() as root:
            Path(root, "logs").mkdir()
            runner = ChaoxingRunner(SimpleNamespace(course_urls=["https://mooc1.chaoxing.com/mycourse/studentstudy?courseId=1"]),
                                    Mock(runtime_root=root))
            runner.page = Mock()
            runner.page.is_closed.return_value = False
            runner.safe_screenshot = AsyncMock(return_value=True)
            runner.blocker = AsyncMock(return_value="页面出现验证或课时锁定，需要用户处理。")
            self.assertFalse(await runner.wait_for_manual_question(Mock(), 'cur1'))
            self.assertEqual(runner.state['status'], 'needs_user')
            self.assertEqual(runner.state['video_completed_tasks'], [])

    async def test_hidden_controls_or_unrelated_exercise_do_not_block_video_frame(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            try:
                page = await browser.new_page()
                await page.set_content('''<input type="radio"><button>提交</button>
                    <iframe srcdoc='<video></video><div hidden><input type="checkbox"><button>提交</button></div>'></iframe>''')
                player = page.frame_locator('iframe')
                await player.locator('video').wait_for(state='attached')
                self.assertFalse(await has_video_question(player))
                self.assertTrue(await has_video_question(page))
            finally:
                await browser.close()
