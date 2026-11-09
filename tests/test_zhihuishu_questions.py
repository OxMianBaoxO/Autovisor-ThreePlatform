"""Offline regression for the official 3.18.4 ZHS popup behavior and isolation."""
import asyncio
import unittest

from playwright.async_api import async_playwright

from modules.tasks import skip_questions


FIXTURE = '''<div class="el-dialog" tabindex="0"
 onkeydown="if(event.key==='Escape'){window.popupClosed++;this.style.display='none'}">
 <div class="el-scrollbar__view"><button class="number">1</button></div>
 <button class="topic-item" onclick="window.chosen.push(0)">A</button>
 <button class="topic-item" onclick="window.chosen.push(1)">B</button>
 <button class="topic-item" onclick="window.chosen.push(2)">C</button>
 {answer}
 </div><script>window.chosen=[];window.popupClosed=0;</script>'''


class ZhihuishuQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = await async_playwright().start()
        self.browser = await self.runtime.chromium.launch(channel="chrome", headless=True)
        self.page = await self.browser.new_page()

    async def asyncTearDown(self):
        await self.browser.close()
        await self.runtime.stop()

    async def open_fixture(self, host, answer="", extra=""):
        html = FIXTURE.replace("{answer}", answer) + extra
        await self.page.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html"))
        await self.page.goto(f"https://{host}/stuStudy")

    async def run_until_answered(self):
        event = asyncio.Event()
        task = asyncio.create_task(skip_questions(self.page, event))
        try:
            await asyncio.wait_for(event.wait(), timeout=8)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_legacy_follows_upstream_first_two_choices_and_closes(self):
        await self.open_fixture("studyvideoh5.zhihuishu.com")
        await self.run_until_answered()
        self.assertEqual(await self.page.evaluate("window.chosen"), [0, 1])
        self.assertEqual(await self.page.evaluate("window.popupClosed"), 1)
        self.assertFalse(await self.page.locator(".el-dialog").is_visible())

    async def test_already_answered_question_is_not_clicked_again(self):
        await self.open_fixture("studyvideoh5.zhihuishu.com", '<span class="answer">已答</span>')
        await self.run_until_answered()
        self.assertEqual(await self.page.evaluate("window.chosen"), [])
        self.assertEqual(await self.page.evaluate("window.popupClosed"), 1)

    async def test_chaoxing_and_polymas_are_untouched(self):
        for host in ("mooc1.chaoxing.com", "hike-teaching-center.polymas.com"):
            with self.subTest(host=host):
                await self.page.unroute("**/*")
                await self.open_fixture(host)
                task = asyncio.create_task(skip_questions(self.page, asyncio.Event()))
                try:
                    await asyncio.sleep(2.3)
                    self.assertEqual(await self.page.evaluate("[window.chosen,window.popupClosed]"), [[], 0])
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_new_wisdom_layout_preserves_upstream_manual_wait(self):
        await self.open_fixture("studywisdomh5.zhihuishu.com", extra='<div class="topic-title">新版题目</div>')
        task = asyncio.create_task(skip_questions(self.page, asyncio.Event()))
        try:
            await asyncio.sleep(2.3)
            self.assertEqual(await self.page.evaluate("[window.chosen,window.popupClosed]"), [[], 0])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
