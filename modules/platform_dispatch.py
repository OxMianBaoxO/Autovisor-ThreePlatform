"""Validate all configured courses before opening a browser; isolate login accounts."""
from copy import copy
from urllib.parse import urlparse

from modules.configs import ConfigError
from modules.chaoxing_adapter import is_chaoxing_course
from modules.lesson_navigation import is_polymas_course


PLATFORM_NAMES = {"zhihuishu": "智慧树", "chaoxing": "学习通", "polymas": "Polymas"}
ZHS_COURSE_HOSTS = {
    "studyvideoh5.zhihuishu.com", "studyh5.zhihuishu.com",
    "studywisdomh5.zhihuishu.com", "fusioncourseh5.zhihuishu.com",
    "hike.zhihuishu.com", "onlineweb.zhihuishu.com",
}


def course_platform(url: str) -> str:
    try:
        parsed = urlparse(url)
        valid = (parsed.scheme == "https" and parsed.port in (None, 443)
                 and not parsed.username and not parsed.password)
    except ValueError:
        valid = False
    if valid:
        if is_chaoxing_course(url):
            return "chaoxing"
        if is_polymas_course(url):
            return "polymas"
        if (parsed.hostname or "").lower() in ZHS_COURSE_HOSTS:
            return "zhihuishu"
    raise ConfigError("课程链接不受支持，请从智慧树、学习通或 Polymas 的实际课程学习页复制 HTTPS 地址")


def course_runs(config):
    """Separate browser lifetimes and prevent a shared account reaching another platform.

    The legacy user-account section remains valid for a single platform. With mixed
    platforms, only explicit platform-account sections are used; otherwise login is manual.
    """
    platforms = [course_platform(url) for url in config.course_urls]
    mixed = len(set(platforms)) > 1
    runs = []
    for url, platform in zip(config.course_urls, platforms):
        scoped = copy(config)
        scoped.course_urls = [url]
        section = platform + "-account"
        if config._config.has_section(section):
            scoped.username = config._config.get(section, "username", raw=True, fallback="").strip()
            scoped.password = config._config.get(section, "password", raw=True, fallback="")
        elif mixed or platform == "polymas":
            scoped.username = scoped.password = ""
        # All verification remains manual in the distributed build.
        scoped.enableAutoCaptcha = False
        scoped.enableHideWindow = False
        runs.append((platform, scoped))
    return runs


async def dispatch_courses(config, logger, standard_runner, chaoxing_runner) -> bool:
    runs = course_runs(config)  # Validate the whole list before running any course.
    if not runs:
        raise ConfigError("尚未填写课程链接，请编辑 config.ini 的 [course-url] URL1")
    for index, (platform, scoped) in enumerate(runs, 1):
        logger.event("平台分流", 序号=f"{index}/{len(runs)}", 平台=PLATFORM_NAMES[platform])
        runner = chaoxing_runner if platform == "chaoxing" else standard_runner
        result = await runner(scoped, logger) if platform == "chaoxing" else await runner(scoped)
        if not result:
            return False
    return True
