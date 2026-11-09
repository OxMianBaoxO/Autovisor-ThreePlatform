import configparser
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from modules.configs import ConfigError
from modules.platform_dispatch import course_platform, course_runs, dispatch_courses
from modules.chaoxing_adapter import browser_launch_options


ZHS = "https://studywisdomh5.zhihuishu.com/stuStudy?courseId=1"
XXT = "https://mooc1.chaoxing.com/mycourse/studentstudy?courseId=2"
POLY = "https://hike-teaching-center.polymas.com/custom-stu-hike/a/stu/study/resource-detail"


def config(urls):
    return SimpleNamespace(course_urls=urls, username="shared-dummy", password="dummy-only",
                           _config=configparser.ConfigParser(), enableAutoCaptcha=True,
                           enableHideWindow=True)


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    def test_exact_hosts_and_course_destinations(self):
        self.assertEqual([course_platform(url) for url in (ZHS, XXT, POLY)],
                         ["zhihuishu", "chaoxing", "polymas"])
        for url in ("https://example.test/?next=" + ZHS,
                    ZHS.replace(".com/", ".com.attacker.test/"),
                    XXT.replace("https://", "http://"),
                    POLY.replace(".com/", ".com:9443/"),
                    ZHS.replace("https://", "https://user@"),
                    "https://passport2.chaoxing.com/login"):
            with self.assertRaises(ConfigError, msg=url):
                course_platform(url)

    async def test_mixed_queue_runs_each_platform_with_isolated_credentials(self):
        settings = config([ZHS, XXT, POLY])
        settings._config["chaoxing-account"] = {"username": "xxt-dummy", "password": "xxt-dummy-pass"}
        seen = []

        async def standard(scoped):
            seen.append((scoped.course_urls, scoped.username, scoped.password))
            self.assertFalse(scoped.enableAutoCaptcha)
            return True

        async def chaoxing(scoped, logger):
            seen.append((scoped.course_urls, scoped.username, scoped.password))
            return True

        self.assertTrue(await dispatch_courses(settings, Mock(), standard, chaoxing))
        self.assertEqual(seen, [([ZHS], "", ""), ([XXT], "xxt-dummy", "xxt-dummy-pass"), ([POLY], "", "")])
        self.assertEqual(settings.course_urls, [ZHS, XXT, POLY])
        self.assertEqual(settings.username, "shared-dummy")

    def test_single_platform_keeps_legacy_account_compatible(self):
        runs = course_runs(config([ZHS, ZHS]))
        self.assertEqual([scoped.username for _, scoped in runs], ["shared-dummy"] * 2)

    async def test_invalid_later_url_is_rejected_before_first_browser(self):
        standard, chaoxing = AsyncMock(), AsyncMock()
        with self.assertRaises(ConfigError):
            await dispatch_courses(config([ZHS, "https://attacker.test/course"]), Mock(), standard, chaoxing)
        standard.assert_not_awaited()
        chaoxing.assert_not_awaited()

    async def test_failure_stops_queue_without_opening_another_platform(self):
        standard, chaoxing = AsyncMock(return_value=False), AsyncMock(return_value=True)
        self.assertFalse(await dispatch_courses(config([ZHS, XXT]), Mock(), standard, chaoxing))
        chaoxing.assert_not_awaited()

    def test_browser_selection_applies_to_chaoxing_too(self):
        self.assertEqual(browser_launch_options(SimpleNamespace(driver="edge", exe_path=""))["channel"], "msedge")
        custom = browser_launch_options(SimpleNamespace(driver="chrome", exe_path=r"C:\Browser\chrome.exe"))
        self.assertEqual(custom["executable_path"], r"C:\Browser\chrome.exe")
        self.assertNotIn("channel", custom)


if __name__ == "__main__":
    unittest.main()
