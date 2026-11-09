"""Offline browser regression: assessment options and submit must remain untouched."""
import asyncio
import unittest
from playwright.async_api import async_playwright
from modules.tasks import has_blocking_overlay, wait_until_question_hidden
from modules.lesson_navigation import WISDOM_CATALOG, FUSION_CATALOG, detect_catalog, lesson_progress


class ManualQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_wisdom_and_fusion_catalogs_and_manual_assessment_wait(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            try:
                page = await browser.new_page()
                await page.route("**/*", lambda route: route.abort())
                await page.set_content('''<div class="chapter-item"><span class="item-name">第一讲</span>
                <span class="el-progress" aria-valuenow="34"></span></div>
                <div class="ai-class-exercise-dialog"><button class="option" onclick="window.clicks++">选项</button>
                <button onclick="window.submits++">提交</button></div><script>window.clicks=0;window.submits=0;</script>''')
                catalog = await detect_catalog(page, "https://fusioncourseh5.zhihuishu.com/course")
                self.assertEqual(catalog, FUSION_CATALOG)
                self.assertEqual(await lesson_progress(page.locator('.chapter-item'), catalog), 34)
                self.assertTrue(await has_blocking_overlay(page))
                waiting = asyncio.create_task(wait_until_question_hidden(page))
                try:
                    await asyncio.sleep(0.6)
                    self.assertFalse(waiting.done())
                    self.assertEqual(await page.evaluate('[window.clicks,window.submits]'), [0, 0])
                    await page.locator('.ai-class-exercise-dialog').evaluate('e => e.remove()')
                    await asyncio.wait_for(waiting, 2)
                finally:
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
                self.assertFalse(await has_blocking_overlay(page))
                await page.set_content('''<div class="child-info hasvideo"><span class="child-name">第二讲</span>
                <i class="child-check"></i><div role="progressbar" aria-valuenow="100"></div></div>''')
                catalog = await detect_catalog(page, "https://studywisdomh5.zhihuishu.com/course")
                self.assertEqual(catalog, WISDOM_CATALOG)
                self.assertEqual(await lesson_progress(page.locator('.child-info'), catalog), 100)
            finally:
                await browser.close()
