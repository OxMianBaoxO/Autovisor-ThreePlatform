"""离线 DOM 集成检查: 空白浏览器上下文, 无账号, 无网络请求。"""
import asyncio

from playwright.async_api import async_playwright

from modules.lesson_navigation import POLYMAS_CATALOG, detect_catalog, get_lesson_title, lesson_progress, wait_for_lesson_active
from modules.polymas_adapter import wait_until_unlocked
from modules.utils import get_filtered_class


def leaf(title, progress="", locked=False, active=False, completed=False):
    lock = '<i class="aloha-icon-resource-lock"></i>' if locked else ''
    progress_html = '' if completed else f'<div class="node-action-rate-text">{progress}</div>'
    status = 'success' if completed else 'info'
    return f'''<div class="el-tree-node {'is-current' if active else ''}"><div class="el-tree-node__content">
    <i class="el-tree-node__expand-icon is-leaf"></i><span class="custom-tree-node"><div class="node-left"><img class="file-icon">
    <div class="file-name"><div class="tool-tip-pro">{title}</div></div></div><div class="node-actions">{lock}
    {progress_html}<label class="el-checkbox is-checked agent-course-form-item-checkbox {status}"><input type="checkbox" checked></label></div></span></div></div>'''


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        try:
            page = await browser.new_page()
            await page.route("**/*", lambda route: route.abort())
            await page.set_content('<div class="el-tree"><div class="el-tree-node is-expanded"><div class="el-tree-node__content">第一章</div><div class="el-tree-node__children">' + leaf("当前课.mp4", "14.97%", active=True) + leaf("下一课.mp4", locked=True) + leaf("课件.pdf") + leaf("已完成课.mp4", completed=True) + '</div></div></div>')
            catalog = await detect_catalog(page, "https://hike-teaching-center.polymas.com/test")
            assert catalog is POLYMAS_CATALOG
            lessons = await get_filtered_class(page, catalog)
            assert len(lessons) == 2, len(lessons)
            assert await get_lesson_title(page, lessons[0], catalog) == "当前课.mp4"
            assert await lesson_progress(lessons[0], catalog) == 14
            assert await wait_for_lesson_active(lessons[0], catalog)
            assert not await wait_until_unlocked(lessons[1], timeout_seconds=0)
            all_lessons = await get_filtered_class(page, catalog, include_all=True)
            assert len(all_lessons) == 3
            assert await lesson_progress(all_lessons[-1], catalog) == 100
            print("PASS: real Playwright selectors, title, progress, checked-checkbox handling, PDF filtering, active state, locked lesson; no account or network.")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
