"""Chaoxing's ordinary browser player, without API/progress manipulation."""
import asyncio
import json
import math
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
from modules.chaoxing_login import submit_configured_password
from modules.browser import resolve_browser_channel, resolve_executable_path
from modules.mixue import install_mixue


def browser_launch_options(config):
    options = {"headless": False, "viewport": None, "args": ["--start-maximized"]}
    driver = getattr(config, "driver", "chrome")
    executable = resolve_executable_path(driver, getattr(config, "exe_path", ""))
    if executable:
        options["executable_path"] = executable
    else:
        options["channel"] = resolve_browser_channel(driver)
    return options


def is_chaoxing_course(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host == "chaoxing.com" or host.endswith(".chaoxing.com")
    ) and parsed.path.startswith(("/mycourse/", "/mooc2-ans/mycourse/"))


def video_finished(state):
    duration = state.get("duration")
    return bool(state.get("ended")) and isinstance(duration, (int, float)) and math.isfinite(duration) and duration > 0


def completed_marker(marker):
    # An absent marker is UNKNOWN, never proof of completion.
    label = marker.get("label") or ""
    classes = ((marker.get("class") or "") + " " + (marker.get("container_class") or "")).split()
    return label in {"任务点已完成", "任务点完成"} or "ans-job-finished" in classes


async def media_snapshot(frame):
    return await frame.locator("video").evaluate("""v => ({
        currentTime: v.currentTime, duration: Number.isFinite(v.duration) ? v.duration : null,
        paused: v.paused, ended: v.ended, playbackRate: v.playbackRate,
        error: v.error ? {code: v.error.code, message: v.error.message} : null
    })""")


async def select_native_speed(player, target):
    """Cycle the real VideoJS rate button with its ordinary keyboard action."""
    await player.locator("#video").hover(timeout=5000)
    button = player.get_by_role("button", name="播放速度", exact=True)
    if not await button.count() or not await button.first.is_visible():
        return False
    seen = set()
    for _ in range(7):
        rate = (await media_snapshot(player))["playbackRate"]
        if rate == target:
            return True
        if rate in seen:
            return False
        seen.add(rate)
        await button.first.press("Enter", timeout=5000)
    return (await media_snapshot(player))["playbackRate"] == target


async def dismiss_optional_overlays(page):
    """User-requested cosmetic assistant removal and native note-tip dismissal."""
    if not await page.locator('style[data-autovisor-cosmetic]').count():
        style = await page.add_style_tag(content='.figure-wrapper.toon[data-scene="course"],.cx-robot-wrapper[data-scene="course"]{display:none!important}')
        await style.evaluate("e => e.setAttribute('data-autovisor-cosmetic', 'true')")
    for frame in page.frames:
        for tip in await frame.locator('.writeNote_vid_blue, .dotNote_blue').all():
            if await tip.is_visible():
                try:
                    await tip.click(timeout=3000)
                except PlaywrightTimeoutError:
                    pass


async def resume_native_video(player):
    """Show ordinary controls before clicking; a transient timeout is retryable."""
    try:
        # VideoJS's poster and big-play button are siblings of the media element.
        # Hover their containing player so the poster cannot intercept the target.
        await player.locator("#video").hover(timeout=5000)
        buttons = player.get_by_role("button", name=re.compile(r"^(播放视频|播放)$"))
        if await buttons.count() and await buttons.first.is_visible():
            await buttons.first.click(timeout=8000)
            return True
    except PlaywrightTimeoutError:
        return False
    return False


async def has_video_question(player):
    """Read assessment controls inside this video iframe without interacting."""
    choices = player.locator('input[type="radio"]:visible, input[type="checkbox"]:visible, '
                             '[role="radio"]:visible, [role="checkbox"]:visible')
    if not await choices.count():
        return False
    submits = player.get_by_text(re.compile(r"^(提交|提交答案|确认答案)$"), exact=True)
    for control in await submits.all():
        if await control.is_visible():
            return True
    return False


async def scroll_ebook_to_bottom(card):
    """Use the embedded viewer's normal scrolling and keyboard controls."""
    document = card.locator("iframe.insertdoc-online-ppt")
    if await document.count() != 1:
        raise RuntimeError("未识别到唯一电子书，未自动处理未知课件结构")
    await document.scroll_into_view_if_needed(timeout=10000)
    viewer = card.frame_locator("iframe.insertdoc-online-ppt").frame_locator("#panView")
    pages = viewer.locator('[id^="anchor"]')
    await pages.first.wait_for(timeout=30000)
    page_count = await pages.count()
    await pages.last.scroll_into_view_if_needed(timeout=15000)
    # Focus this inner viewer so End does not scroll the surrounding course page.
    await pages.last.click(position={"x": 8, "y": 8}, timeout=10000)
    await viewer.locator("body").press("Control+End", timeout=10000)
    return {"page_count": page_count, "action": "native_scroll_to_last_page_and_end"}


class ChaoxingRunner:
    def __init__(self, config, logger):
        self.config, self.logger = config, logger
        self.root = Path(logger.runtime_root)
        self.status_path = self.root / "logs" / "chaoxing-status.json"
        self.previous_pending = set()
        try:
            previous = json.loads(self.status_path.read_text(encoding="utf-8"))
            course_id = (parse_qs(urlparse(config.course_urls[0]).query).get("courseId") or [None])[0]
            if previous.get("course_id") == course_id:
                self.previous_pending = {entry["id"] for entry in previous.get("pending_resource_chapters", [])
                                         if isinstance(entry, dict) and "id" in entry}
        except (OSError, ValueError, TypeError, IndexError):
            pass
        self.state = {"platform": "chaoxing", "status": "starting", "all_complete": False,
                      "durations": {}, "completed_chapters": [], "video_completed_chapters": [],
                      "pending_resource_chapters": [], "transitions": [],
                      "video_completed_tasks": [], "pending_manual_chapters": []}
        self.started = time.monotonic()
        self.page = None
        self.mixue_client = None

    def save(self, **values):
        self.state.update(values)
        self.state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        temp = self.status_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        # Windows readers/OneDrive may briefly hold a handle without delete sharing.
        for attempt in range(6):
            try:
                temp.replace(self.status_path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.1 * (attempt + 1))

    async def stopped(self, reason):
        self.save(status="needs_user", reason=reason)
        self.logger.warn(reason, shift=True)
        await self.safe_screenshot("chaoxing-needs-user.png")
        return False

    async def safe_screenshot(self, name):
        try:
            await self.page.screenshot(path=str(self.root / "logs" / name), timeout=5000,
                                       mask=[self.page.locator("input:visible")])
            return True
        except (PlaywrightError, OSError) as exc:
            # Login/navigation may replace the document while the screenshot is taken.
            # A diagnostic image must not abort normal playback or mask the real error.
            self.logger.event("学习通截图跳过", 原因=type(exc).__name__)
            return False

    async def blocker(self, include_dialogs=True):
        if "passport" in (urlparse(self.page.url).hostname or "") or "login" in urlparse(self.page.url).path:
            return "学习通登录已失效，需要重新登录。"
        # Inspect visible text only; do not solve or dismiss assessments/verification.
        for frame in self.page.frames:
            try:
                text = await frame.locator("body").inner_text(timeout=1500)
            except Exception:
                continue
            if re.search(r"请完成(?:下方)?(?:验证|滑块)|请拖动滑块|请完成人脸识别|请先完成前置|章节已锁定", text):
                return "页面出现验证或课时锁定，需要用户处理。"
            dialogs = frame.locator('[role="dialog"]:visible')
            if include_dialogs and await dialogs.count():
                return "页面出现弹窗，需要用户确认，程序没有自动作答或处理验证。"
        return None

    async def wait_for_manual_question(self, player, task_key):
        """Keep the owned window open until the user handles the video question."""
        reason = "视频出现随堂题，请在浏览器中手动完成；程序保留窗口等待。"
        self.save(status="waiting_question", reason=reason, question_task_key=task_key)
        self.logger.warn(reason, shift=True)
        self.logger.event("学习通等待人工答题", 视频任务=task_key)
        await self.safe_screenshot("chaoxing-question.png")
        absent_samples = 0
        while True:
            if self.page.is_closed():
                return await self.stopped("等待人工答题时浏览器已关闭，需要用户继续。")
            blocker = await self.blocker(include_dialogs=False)
            if blocker:
                return await self.stopped(blocker)
            state = await media_snapshot(player)
            self.save(status="waiting_question", reason=reason, media=state)
            if state["error"]:
                return await self.stopped(f"视频播放错误：{state['error']['code']}")
            if await has_video_question(player):
                absent_samples = 0
            else:
                absent_samples += 1
                # Avoid a brief DOM replacement during manual submission.
                if absent_samples >= 2:
                    self.save(status="playing", reason=None, question_task_key=None)
                    self.logger.event("学习通人工答题弹窗已消失", 视频任务=task_key)
                    return True
            if self.config.limitMaxTime > 0 and time.monotonic() - self.started >= self.config.limitMaxTime * 60:
                self.save(status="time_limit", all_complete=False)
                return False
            await asyncio.sleep(3)

    async def wait_login(self, url):
        await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if "login" in self.page.url or "passport" in self.page.url:
            outcome = await submit_configured_password(self.page, self.config)
            reasons = {
                "submitted": "已提交账号密码，等待平台登录结果；不会自动重复提交。",
                "verification_required": "登录页面要求验证或人工处理，程序没有自动处理。",
                "unverified_page": "未能核实登录页面或表单目的地，未提交账号密码。",
                "not_configured": "请在程序浏览器中手动登录或扫码登录。",
                "form_unavailable": "未识别到唯一可用的账号密码表单，请手动登录。",
                "interaction_failed": "登录表单暂不可操作，请手动登录；程序不会重复尝试密码。",
            }
            self.save(status="waiting_login", reason=reasons[outcome], login_outcome=outcome)
            self.logger.info(reasons[outcome], shift=True)
            await self.safe_screenshot("chaoxing-login.png")
            last_login_snapshot = 0
            while "login" in self.page.url or "passport" in self.page.url:
                if self.page.is_closed():
                    raise RuntimeError("学习通登录浏览器被关闭")
                # Some normal SSO/QR flows finish in a new tab of this owned context.
                # Reuse it without exporting session credentials or submitting a password again.
                candidates = []
                for owned_page in self.page.context.pages:
                    target = urlparse(owned_page.url)
                    host = (target.hostname or "").lower()
                    if target.scheme == "https" and (
                        (host == "i.chaoxing.com" and target.path.startswith("/base")) or
                        (host.endswith(".chaoxing.com") and target.path.startswith(("/mycourse/", "/mooc2-ans/mycourse/")))
                    ):
                        candidates.append(owned_page)
                if candidates:
                    self.page = candidates[-1]
                    break
                now = time.monotonic()
                if now - last_login_snapshot >= 15:
                    last_login_snapshot = now
                    current = urlparse(self.page.url)
                    self.save(status="waiting_login", login_page_host=current.hostname,
                              login_page_path=current.path, owned_tab_count=len(self.page.context.pages))
                    await self.safe_screenshot("chaoxing-login-current.png")
                await asyncio.sleep(2)
            await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await self.page.locator('[id^="cur"] .posCatalog_name').first.wait_for(timeout=60000)

    async def read_catalog(self):
        return await self.page.locator('[id^="cur"] .posCatalog_name').evaluate_all("""els => els.map(e => ({
            id:e.parentElement.id, title:e.getAttribute('title') || e.innerText.trim(),
            pendingText:e.parentElement.querySelector('.prevHoverTips')?.innerText || '',
            classes:e.parentElement.className
        }))""")

    async def markers(self, card):
        return await card.locator(".ans-job-icon").evaluate_all("""els => els.map(e => ({
            label:e.getAttribute('aria-label'), class:e.className,
            container_class:e.parentElement?.className || '',
            video:e.classList.contains('ans-job-video')
        }))""")

    async def wait_for_assessments(self, card):
        """Keep the helper and browser alive until actual exercise markers finish."""
        assessments = card.locator('iframe[src*="work/"], iframe[src*="exam/"]')
        if not await assessments.count():
            return True
        self.logger.warn("本讲有练习，蜜雪面板可查询/填答；请按设置检查并提交，等待平台任务标记。", shift=True)
        self.save(status="waiting_assessment", reason="等待练习完成，可在蜜雪面板处理")
        active = self.page.locator('[id^="cur"].posCatalog_active')
        selected_id = await active.first.get_attribute("id") if await active.count() else None
        while True:
            if self.page.is_closed():
                return await self.stopped("处理练习时浏览器已关闭")
            blocker = await self.blocker(include_dialogs=False)
            if blocker:
                return await self.stopped(blocker)
            if selected_id and (not await active.count() or await active.first.get_attribute("id") != selected_id):
                return await self.stopped("等待练习时章节已切换，未使用其他章节的任务标记。")
            pending = False
            for assessment in await assessments.all():
                scope = assessment.locator("xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' ans-attach-ct ')][1]")
                icons = await self.markers(scope) if await scope.count() == 1 else []
                if not icons or not all(map(completed_marker, icons)):
                    pending = True
            if not pending:
                self.save(status="assessment_complete", reason=None)
                return True
            if self.config.limitMaxTime > 0 and time.monotonic() - self.started >= self.config.limitMaxTime * 60:
                self.save(status="time_limit", all_complete=False)
                return False
            await asyncio.sleep(3)

    async def play_chapter(self, chapter, position, total):
        self.save(status="loading", reason=None, chapter=position, chapter_count=total, title=chapter["title"])
        self.logger.context(课时序号=f"{position}/{total}", 课时名称=chapter["title"])
        self.logger.event("学习通课时开始", 标题=chapter["title"], 序号=f"{position}/{total}")
        item = self.page.locator("#" + chapter["id"])
        if "posCatalog_active" not in (await item.get_attribute("class") or "").split():
            await item.locator(".posCatalog_name").click(timeout=10000)
        # A click can update the selected title before replacing the old iframe.
        # Never interpret the previous chapter's finished markers as the new chapter.
        expected_id = chapter["id"].removeprefix("cur")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            element = await self.page.locator("#iframe").element_handle()
            content = await element.content_frame() if element else None
            if content and parse_qs(urlparse(content.url).query).get("knowledgeid") == [expected_id]:
                await content.wait_for_load_state("domcontentloaded", timeout=30000)
                break
            await asyncio.sleep(0.2)
        else:
            return await self.stopped("章节标题已切换，但对应课程内容没有加载，未使用旧章节的完成状态。")
        card = self.page.frame_locator("#iframe")
        await card.locator("body").wait_for(timeout=30000)
        videos = card.locator("iframe.ans-insertvideo-online")
        assessment_count = await card.locator('iframe[src*="work/"], iframe[src*="exam/"]').count()
        if await videos.count() < 1 and not (self.mixue_client and assessment_count):
            return await self.stopped("本讲未找到视频，需要人工检查，未跳过任务。")
        if not self.mixue_client and not getattr(self.config, "chaoxing_videos_only", False) and assessment_count:
            return await self.stopped("本讲包含练习或考试，需要用户自行完成。")
        video_count = await videos.count()
        for video_index in range(video_count):
            self.save(video_index=video_index + 1, chapter_video_count=video_count)
            player = card.frame_locator("iframe.ans-insertvideo-online").nth(video_index)
            marker_scope = videos.nth(video_index).locator(
                "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' ans-attach-ct ')][1]")
            if await marker_scope.count() != 1:
                return await self.stopped("无法确定本视频对应的任务标记，未将其他视频或练习的标记当作完成。")
            task_key = chapter["id"] if video_count == 1 else f'{chapter["id"]}:video{video_index + 1}'
            if not await self.play_video_task(player, marker_scope, chapter, task_key):
                return False
        if getattr(self.config, "chaoxing_videos_only", False):
            icons = await self.markers(card)
            complete = bool(icons) and all(map(completed_marker, icons))
            self.state["video_completed_chapters"].append(chapter["id"])
            if complete:
                self.state["completed_chapters"].append(chapter["id"])
            else:
                self.state["pending_manual_chapters"].append({"id": chapter["id"], "title": chapter["title"],
                    "remaining_tasks": sum(not completed_marker(m) for m in icons if not m["video"])})
            self.state["transitions"].append({"chapter": position, "title": chapter["title"],
                "video_confirmed": True, "all_tasks_confirmed": complete})
            self.save(status="chapter_complete" if complete else "video_complete_manual_tasks_pending", task_markers=icons)
            self.logger.event("学习通课时视频完成", 序号=f"{position}/{total}", 视频平台确认=True,
                              本讲全部任务确认=complete, 练习处理="保留未完成状态，等待用户自行完成")
            return True

        if self.mixue_client and not await self.wait_for_assessments(card):
            return False

        # The second task requires reaching the end of the actual ebook viewer.
        # Scrolling alone is not completion: wait for the platform's green marker.
        docs = card.locator("iframe.insertdoc-online-ppt")
        icons = await self.markers(card)
        if await docs.count() and not (icons and all(map(completed_marker, icons))):
            self.save(status="viewing_document")
            result = await scroll_ebook_to_bottom(card)
            self.save(document=result)
            self.logger.event("学习通电子书滚至末页", 标题=chapter["title"], 页数=result["page_count"], 方式="原生滚动及End键")
        resources_complete = False
        for _ in range(20):
            icons = await self.markers(card)
            if icons and all(map(completed_marker, icons)):
                resources_complete = True
                break
            active = self.page.locator('[id^="cur"].posCatalog_active')
            if await active.count() and await active.first.get_attribute("id") != chapter["id"]:
                # The page/user moved on: never attribute the new frame's markers to this chapter.
                break
            await asyncio.sleep(3)
        self.state["video_completed_chapters"].append(chapter["id"])
        if resources_complete:
            self.state["completed_chapters"].append(chapter["id"])
        else:
            self.state["pending_resource_chapters"].append({"id": chapter["id"], "title": chapter["title"]})
        self.state["transitions"].append({"chapter": position, "title": chapter["title"],
                                          "video_confirmed": True, "all_tasks_confirmed": resources_complete})
        self.save(status="chapter_complete" if resources_complete else "video_complete_resources_pending", task_markers=icons)
        self.logger.event("学习通课时视频完成", 序号=f"{position}/{total}", 视频平台确认=True,
                          本讲全部任务确认=resources_complete)
        if not resources_complete:
            return await self.stopped("电子书已滚至末页，但平台尚未显示本讲全部任务的绿色完成标记，未切到下一讲。")
        return True

    async def play_video_task(self, player, marker_scope, chapter, task_key):
        await player.locator("video").wait_for(timeout=30000)
        initial_icons = await self.markers(marker_scope)
        await dismiss_optional_overlays(self.page)
        initial_video_icons = [m for m in initial_icons if m["video"]]
        previously_complete = bool(initial_video_icons) and all(map(completed_marker, initial_video_icons))
        if previously_complete:
            self.logger.event("学习通跳过已完成视频", 平台任务确认=True, 标题=chapter["title"])
            self.save(status="video_already_complete", video_confirmed=True, task_markers=initial_icons)
        last_time, last_moved = None, time.monotonic()
        last_log, end_seen, resume_attempt = 0, None, None
        while not previously_complete:
            reason = await self.blocker(include_dialogs=False)
            if reason:
                return await self.stopped(reason)
            state = await media_snapshot(player)
            self.save(media=state)
            if state["error"]:
                return await self.stopped(f"视频播放错误：{state['error']['code']}")
            if await has_video_question(player):
                if not await self.wait_for_manual_question(player, task_key):
                    return False
                # Manual waiting is not playback stagnation. Re-read the media
                # before considering native resume or a platform completion mark.
                last_time, last_moved = None, time.monotonic()
                end_seen, resume_attempt = None, None
                continue
            reason = await self.blocker()
            if reason:
                return await self.stopped(reason)
            target_speed = self.config.chaoxingSpeed
            if state["playbackRate"] != target_speed and not state["paused"] and state["duration"]:
                previous_speed = state["playbackRate"]
                if not await select_native_speed(player, target_speed):
                    return await self.stopped(f"未能从播放器原生菜单选择{target_speed:g}倍速，需要用户处理。")
                self.logger.event("学习通设置原生倍速", 原倍速=previous_speed, 当前倍速=target_speed, 方式="播放器原生倍速按钮键盘操作")
                state = await media_snapshot(player)
                self.save(media=state)
            duration = state["duration"]
            if duration and duration > 0:
                self.state["durations"][task_key] = duration
            now = time.monotonic()
            if last_time is None or state["currentTime"] > last_time + 0.25:
                last_time, last_moved = state["currentTime"], now
                resume_attempt = None
            icons = await self.markers(marker_scope)
            video_icons = [m for m in icons if m["video"]]
            confirmed_video = bool(video_icons) and all(map(completed_marker, video_icons))
            self.save(status="playing", media=state, task_markers=icons, video_confirmed=confirmed_video)
            if now - last_log >= 60:
                self.logger.event("学习通播放进度", 当前秒=round(state["currentTime"], 1),
                                  总秒=duration, 暂停=state["paused"], 视频任务完成=confirmed_video)
                last_log = now
                await self.safe_screenshot("chaoxing-current.png")
            if video_finished(state):
                end_seen = end_seen or now
                if confirmed_video:
                    break
                if now - end_seen > 120:
                    return await self.stopped("视频已自然结束，但平台尚未确认视频任务完成，未切到下一讲。")
            elif state["paused"] and resume_attempt is None:
                # Click the real control once. Never invoke play()/seek or answer a question.
                if await resume_native_video(player):
                    resume_attempt = now
                else:
                    self.logger.event("学习通恢复播放重试", 原因="原生播放控件暂不可操作")
            if now - last_moved > 180 and not video_finished(state):
                return await self.stopped("播放器已超过3分钟没有推进，请检查网络、验证或暂停原因。")
            if self.config.limitMaxTime > 0 and now - self.started >= self.config.limitMaxTime * 60:
                self.save(status="time_limit", all_complete=False)
                return False
            await asyncio.sleep(3)

        if task_key not in self.state["video_completed_tasks"]:
            self.state["video_completed_tasks"].append(task_key)
        self.save(video_confirmed=True)
        return True

    async def run(self):
        urls = self.config.course_urls
        if len(urls) != 1 or not is_chaoxing_course(urls[0]):
            raise RuntimeError("学习通模式每次只运行一门明确配置的课程")
        self.state["course_id"] = (parse_qs(urlparse(urls[0]).query).get("courseId") or [None])[0]
        async with async_playwright() as p:
            # Dedicated persistent profile: Chrome itself saves credentials; no Cookie export/import.
            context = await p.chromium.launch_persistent_context(
                getattr(self.config, 'chaoxing_profile_directory', '') or
                str(self.root / "data" / f"chaoxing-profile-{getattr(self.config, 'driver', 'chrome')}"),
                **browser_launch_options(self.config),
            )
            self.mixue_client = await install_mixue(context, self.config, self.logger)
            self.page = context.pages[0] if context.pages else await context.new_page()
            self.page.set_default_timeout(10000)
            try:
                await self.wait_login(urls[0])
                catalog = await self.read_catalog()
                if not catalog:
                    return await self.stopped("未识别到学习通章节目录")
                self.save(chapter_count=len(catalog), catalog=catalog)
                for index, chapter in enumerate(catalog, 1):
                    if not await self.play_chapter(chapter, index, len(catalog)):
                        return False
                # Do not announce completion merely because the media ended.
                all_complete = not self.state["pending_resource_chapters"] and not self.state["pending_manual_chapters"]
                pending_status = "videos_complete_tasks_pending" if self.state["pending_manual_chapters"] else "videos_complete_resources_pending"
                self.save(status="complete" if all_complete else pending_status,
                          all_complete=all_complete)
                self.logger.event("学习通课程结果", 正常退出=True, 全部完成=all_complete,
                                  视频完成章节=len(catalog), 全部任务确认章节=len(self.state["completed_chapters"]),
                                  待处理课件章节=len(self.state["pending_resource_chapters"]),
                                  待人工任务章节=len(self.state["pending_manual_chapters"]))
                return all_complete
            except Exception as exc:
                self.save(status="error", reason=type(exc).__name__, all_complete=False)
                raise
            finally:
                # Retain a useful screenshot before closing this owned browser.
                if not self.page.is_closed():
                    await self.safe_screenshot("chaoxing-last.png")
                await context.close()


async def run_chaoxing(config, logger):
    return await ChaoxingRunner(config, logger).run()
