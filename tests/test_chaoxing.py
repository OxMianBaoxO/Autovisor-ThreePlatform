import unittest
from unittest.mock import AsyncMock, Mock
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

from modules.chaoxing_adapter import completed_marker, is_chaoxing_course, video_finished, resume_native_video, ChaoxingRunner
from pathlib import Path


class ChaoxingSafetyTests(unittest.TestCase):
    def test_only_actual_course_hosts_and_paths(self):
        self.assertTrue(is_chaoxing_course("https://mooc1.chaoxing.com/mycourse/studentstudy?courseId=1"))
        self.assertFalse(is_chaoxing_course("https://chaoxing.com.attacker.test/mycourse/studentstudy"))
        self.assertFalse(is_chaoxing_course("https://example.com/?next=https://mooc1.chaoxing.com/mycourse/"))
        self.assertFalse(is_chaoxing_course("https://passport2.chaoxing.com/login"))

    def test_natural_end_and_finite_metadata_required(self):
        self.assertFalse(video_finished({"ended": False, "duration": 2100, "currentTime": 2099.9}))
        self.assertFalse(video_finished({"ended": True, "duration": float("nan")}))
        self.assertFalse(video_finished({"ended": True, "duration": 0}))
        self.assertFalse(video_finished({"ended": True, "duration": None}))
        self.assertTrue(video_finished({"ended": True, "duration": 2100}))

    def test_unknown_and_unfinished_are_never_complete(self):
        self.assertFalse(completed_marker({}))
        self.assertFalse(completed_marker({"label": "任务点未完成", "class": "ans-job-icon ans-job-video"}))
        self.assertFalse(completed_marker({"class": "ans-job-icon"}))
        self.assertFalse(completed_marker({"class": "ans-job-finished-other"}))
        self.assertTrue(completed_marker({"label": "任务点已完成"}))
        self.assertTrue(completed_marker({"class": "ans-job-icon ans-job-finished"}))
        self.assertTrue(completed_marker({"class": "ans-job-icon", "container_class": "ans-attach-ct ans-job-finished"}))


class NativeResumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_navigation_during_diagnostic_screenshot_is_nonfatal(self):
        runner = object.__new__(ChaoxingRunner)
        runner.root, runner.logger = Path("unused-test-root"), Mock()
        runner.page = Mock()
        runner.page.screenshot = AsyncMock(side_effect=PlaywrightError("Execution context was destroyed"))
        self.assertFalse(await runner.safe_screenshot("diagnostic.png"))
        runner.logger.event.assert_called_once()

    async def test_transient_control_timeout_does_not_end_the_runner(self):
        player = Mock()
        player.locator.return_value.hover = AsyncMock()
        buttons = player.get_by_role.return_value
        buttons.count = AsyncMock(return_value=1)
        buttons.first.is_visible = AsyncMock(return_value=True)
        buttons.first.click = AsyncMock(side_effect=[PlaywrightTimeoutError("temporarily hidden"), None])
        self.assertFalse(await resume_native_video(player))
        self.assertTrue(await resume_native_video(player))
        self.assertEqual(player.locator.return_value.hover.await_count, 2)
        for call in buttons.first.click.await_args_list:
            self.assertNotIn("force", call.kwargs)


if __name__ == "__main__":
    unittest.main()
