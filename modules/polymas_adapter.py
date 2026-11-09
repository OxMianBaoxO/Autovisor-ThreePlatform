"""AI 教学中心的目录、登录等待与正常播放支持。"""
import asyncio
import re
import time

from playwright.async_api import TimeoutError

from modules.lesson_navigation import POLYMAS_CATALOG, get_lesson_title

VIDEO_SUFFIX = re.compile(r"\.(?:mp4|m4v|mov|webm|m3u8|flv|avi)(?:\s|$)", re.I)
LOCK_SELECTOR = ":scope > .el-tree-node__content .aloha-icon-resource-lock"
EXPAND_SELECTOR = ".el-tree-node:not(.is-expanded) > .el-tree-node__content .expand-icon-wrapper"


async def open_polymas_course(page, course_url, logger):
    # 保留课程自带的 OAuth redirect, 不返回主站登录页丢失回跳地址。
    await page.goto(course_url, wait_until="domcontentloaded", timeout=60_000)
    logger.info("正在等待 AI 教学中心课程目录；如显示登录或验证，请在浏览器中手动完成。")
    try:
        await page.wait_for_selector(".el-tree-node", state="attached", timeout=300_000)
    except TimeoutError as exc:
        raise RuntimeError("AI 教学中心目录等待超时，请确认已登录且拥有此课程的访问权限。") from exc


async def expand_polymas_catalog(page):
    for _ in range(100):
        headers = page.locator(EXPAND_SELECTOR)
        if not await headers.count():
            return
        await headers.first.click(timeout=5_000)
        await page.wait_for_timeout(100)
    raise RuntimeError("AI 教学中心目录展开次数超限，请手动检查目录。")


async def is_video_lesson(page, lesson):
    title = await get_lesson_title(page, lesson, POLYMAS_CATALOG)
    return bool(VIDEO_SUFFIX.search(title))


async def wait_until_unlocked(lesson, timeout_seconds=15):
    deadline = time.monotonic() + timeout_seconds
    while await lesson.locator(LOCK_SELECTOR).count():
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.5)
    return True
