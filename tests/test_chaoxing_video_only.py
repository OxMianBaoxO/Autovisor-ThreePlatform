"""Offline DOM integration for a chapter with two videos and an inline exercise."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from playwright.async_api import async_playwright
from modules.chaoxing_adapter import ChaoxingRunner


class VideoOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_videos_do_not_submit_or_complete_the_inline_exercise(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            try:
                page = await browser.new_page()
                cards = '''<div class="ans-attach-ct videoContainer" id="video-a"><i class="ans-job-icon ans-job-video"></i>
                <iframe class="ans-insertvideo-online" src="/video/1"></iframe></div>
                <div class="ans-attach-ct videoContainer" id="video-b"><i class="ans-job-icon ans-job-video"></i>
                <iframe class="ans-insertvideo-online" src="/video/2"></iframe></div>
                <div class="ans-attach-ct" id="exercise"><i class="ans-job-icon"></i>
                <iframe src="/ananas/modules/work/index.html"></iframe></div>'''

                async def fixture(route):
                    path = route.request.url
                    body = cards if "/cards?" in path else '<button onclick="window.submissions++">提交</button><script>window.submissions=0;</script>'
                    await route.fulfill(status=200, content_type="text/html", body=body)

                await page.route("**/*", fixture)
                await page.set_content('<div id="cur1" class="posCatalog_active"><span class="posCatalog_name">Offline chapter</span></div>'
                    '<iframe id="iframe" src="https://mooc1.chaoxing.com/cards?knowledgeid=1"></iframe>')
                with TemporaryDirectory() as root:
                    Path(root, "logs").mkdir()
                    runner = ChaoxingRunner(SimpleNamespace(course_urls=["https://mooc1.chaoxing.com/mycourse/studentstudy?courseId=1"],
                                                            chaoxing_videos_only=True), Mock(runtime_root=root))
                    runner.page = page
                    scopes = []

                    async def completed_offline_video(player, marker_scope, chapter, key):
                        self.assertEqual(await marker_scope.locator('.ans-job-video').count(), 1)
                        scopes.append(await marker_scope.get_attribute('id'))
                        # Only the locally fulfilled fixture is modified, never a live task record.
                        await marker_scope.locator('.ans-job-video').evaluate("e => e.classList.add('ans-job-finished')")
                        return True

                    runner.play_video_task = AsyncMock(side_effect=completed_offline_video)
                    self.assertTrue(await runner.play_chapter({'id': 'cur1', 'title': 'Offline chapter'}, 1, 1))
                    self.assertEqual(scopes, ['video-a', 'video-b'])
                    self.assertEqual(runner.state['video_completed_chapters'], ['cur1'])
                    self.assertEqual(runner.state['completed_chapters'], [])
                    self.assertEqual(runner.state['pending_manual_chapters'][0]['remaining_tasks'], 1)
                    self.assertFalse(runner.state['all_complete'])
                    exercise = page.frame_locator('#iframe').frame_locator('iframe[src*="work/"]')
                    self.assertEqual(await exercise.locator('body').evaluate('() => window.submissions'), 0)
            finally:
                await browser.close()
