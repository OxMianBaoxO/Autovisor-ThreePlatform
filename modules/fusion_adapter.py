# encoding=utf-8
"""智慧树融合课目录展开及正常播放适配；练习由用户完成。"""
from playwright.async_api import Page
from playwright._impl._errors import TargetClosedError

from modules.logger import Logger

logger = Logger()

# AI 随堂练习弹窗，只读检测。
AI_CLASS_EXERCISE_DIALOG = ".ai-class-exercise-dialog"
# 折叠章节头(Element-UI collapse), 需展开以采集完整课时列表。
COLLAPSE_HEADER_SELECTOR = ".el-collapse-item__header"


class FusionAdapter:
    """融合课适配层: 只做官方 run_course / tasks 未覆盖的融合页附加行为。"""

    @staticmethod
    async def ai_exercise_visible(page: Page) -> bool:
        """AI 随堂弹窗当前是否可见(考虑祖先 display/visibility, 过滤隐藏的)。"""
        try:
            return bool(
                await page.evaluate(
                    """() => {
                        const dlg = document.querySelector(%s);
                        if (!dlg) return false;
                        let p = dlg.parentElement;
                        while (p && p !== document.body) {
                            const s = getComputedStyle(p);
                            if (s.display==='none' || s.visibility==='hidden')
                                return false;
                            p = p.parentElement;
                        }
                        return dlg.offsetWidth > 0 &&
                               getComputedStyle(dlg).display !== 'none';
                    }"""
                    % ("'" + AI_CLASS_EXERCISE_DIALOG + "'",)
                )
            )
        except Exception as exc:
            logger.debug_throttled(
                "fusion:ai_visible",
                f"AI随堂弹窗检测跳过: {logger.summarize_exception(exc)}",
            )
            return False

    @staticmethod
    async def expand_catalog(page: Page) -> int:
        """展开折叠目录里未激活的章节头, 返回展开个数。"""
        try:
            n = await page.evaluate(
                """() => {
                    let n = 0;
                    document.querySelectorAll('.el-collapse-item').forEach(it => {
                        if ((it.className||'').indexOf('is-active') < 0) {
                            const h = it.querySelector('.el-collapse-item__header');
                            if (h) { h.click(); n++; }
                        }
                    });
                    return n;
                }"""
            )
            if n:
                await page.wait_for_timeout(400)
                logger.debug(f"融合目录已展开 {n} 个折叠项")
            return n or 0
        except Exception as e:
            logger.debug_throttled(
                "fusion:expand", f"展开折叠目录失败: {logger.summarize_exception(e)}"
            )
            return 0

    @staticmethod
    async def resume_video(page: Page) -> None:
        """AI弹窗关闭后/任意暂停时, 恢复视频播放(静音兜底防自动暂停)。"""
        try:
            await page.evaluate(
                """() => {
                    const v = document.querySelector('video');
                    if (v) { v.muted = true; v.play().catch(()=>{}); }
                }"""
            )
        except TargetClosedError:
            logger.debug("fusion:resume 浏览器已关闭.")
        except Exception as exc:
            logger.debug_throttled(
                "fusion:resume",
                f"恢复视频播放跳过: {logger.summarize_exception(exc)}",
            )

