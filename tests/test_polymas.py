import unittest
from unittest.mock import AsyncMock, Mock, patch

from modules.course_playback import learn_lesson
from modules.lesson_navigation import POLYMAS_CATALOG, catalog_candidates, lesson_progress, is_polymas_course
from modules.polymas_adapter import is_video_lesson, open_polymas_course, wait_until_unlocked


URL = "https://hike-teaching-center.polymas.com/custom-stu-hike/agent-course-full/course/resource-detail"


class PolymasTests(unittest.IsolatedAsyncioTestCase):
    def test_course_host_is_exact(self):
        self.assertEqual(catalog_candidates(URL), (POLYMAS_CATALOG,))
        self.assertFalse(is_polymas_course("https://hike-teaching-center.polymas.com.attacker.test/"))
        self.assertFalse(is_polymas_course("https://example.com/?next=" + URL))

    async def test_checked_required_checkbox_does_not_mean_complete(self):
        progress = Mock(count=AsyncMock(return_value=1), text_content=AsyncMock(return_value="14.97%"))
        progress.first = progress
        finish = Mock(count=AsyncMock(return_value=0))
        lesson = Mock(locator=Mock(side_effect=lambda selector: finish if selector == POLYMAS_CATALOG.finish else progress))
        self.assertEqual(await lesson_progress(lesson, POLYMAS_CATALOG), 14)
        lesson.locator.assert_any_call(POLYMAS_CATALOG.progress)

    async def test_success_marker_is_complete_without_percentage(self):
        finish = Mock(count=AsyncMock(return_value=1))
        lesson = Mock(locator=Mock(return_value=finish))
        self.assertEqual(await lesson_progress(lesson, POLYMAS_CATALOG), 100)
        lesson.locator.assert_called_once_with(POLYMAS_CATALOG.finish)

    async def test_missing_percentage_without_success_is_not_complete(self):
        absent = Mock(count=AsyncMock(return_value=0))
        absent.first = absent
        lesson = Mock(locator=Mock(return_value=absent))
        self.assertEqual(await lesson_progress(lesson, POLYMAS_CATALOG), 0)

    async def test_locked_lesson_is_not_opened(self):
        lesson = Mock(locator=Mock(return_value=Mock(count=AsyncMock(return_value=1))))
        self.assertFalse(await wait_until_unlocked(lesson, timeout_seconds=0))
        self.assertFalse(lesson.click.called)

    async def test_documents_are_excluded(self):
        for title, expected in [("必学.mp4", True), ("VIDEO.MP4", True), ("课件.pdf", False), ("笔记.docx", False)]:
            with self.subTest(title=title), patch("modules.polymas_adapter.get_lesson_title", AsyncMock(return_value=title)):
                self.assertEqual(await is_video_lesson(Mock(), Mock()), expected)

    async def test_sso_redirect_is_preserved(self):
        page = Mock(goto=AsyncMock(), wait_for_selector=AsyncMock())
        await open_polymas_course(page, URL, Mock())
        page.goto.assert_awaited_once_with(URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector.assert_awaited_once()

    async def test_ended_video_without_platform_completion_does_not_pass_or_seek(self):
        page = Mock(is_closed=Mock(return_value=False), evaluate=AsyncMock())
        config = Mock(limitMaxTime=0)
        with patch("modules.course_playback._wait_for_duration", AsyncMock(return_value=(788.04, 0))), \
             patch("modules.course_playback.has_visible_verification", AsyncMock(return_value=False)), \
             patch("modules.course_playback.has_visible_element", AsyncMock(return_value=False)), \
             patch("modules.course_playback.lesson_progress", AsyncMock(return_value=99)), \
             patch("modules.course_playback.get_video_attr", AsyncMock(side_effect=[788.04, True])), \
             patch("modules.course_playback.STALL_TIMEOUT_SECONDS", 0):
            result = await learn_lesson(page, 0, 0, Mock(), POLYMAS_CATALOG, config, Mock())
        self.assertEqual(result, (0, False, False))
        page.evaluate.assert_not_awaited()

    async def test_platform_completion_is_required_to_continue(self):
        page = Mock(is_closed=Mock(return_value=False), evaluate=AsyncMock())
        with patch("modules.course_playback._wait_for_duration", AsyncMock(return_value=(788.04, 0))), \
             patch("modules.course_playback.has_visible_verification", AsyncMock(return_value=False)), \
             patch("modules.course_playback.has_visible_element", AsyncMock(return_value=False)), \
             patch("modules.course_playback.lesson_progress", AsyncMock(return_value=100)):
            result = await learn_lesson(page, 0, 0, Mock(), POLYMAS_CATALOG, Mock(limitMaxTime=0), Mock())
        self.assertEqual(result, (0, True, False))
        page.evaluate.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
