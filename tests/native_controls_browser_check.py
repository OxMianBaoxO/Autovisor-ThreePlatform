"""Offline actionability regression for a poster covering the video element."""
import asyncio
import html
from playwright.async_api import async_playwright, TimeoutError
from modules.chaoxing_adapter import resume_native_video, scroll_ebook_to_bottom


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page()
        await page.set_content('''<style>
        #video {position:relative;width:640px;height:360px;background:#ddd}
        video,.poster {position:absolute;inset:0;width:100%;height:100%}
        .poster {display:flex;align-items:center;justify-content:center;background:#aaa}
        </style><div id="video"><video></video><div class="poster">
        <button onclick="document.getElementById('result').textContent='clicked'">播放视频</button>
        </div></div><div id="result">waiting</div>''')
        try:
            await page.locator("video").hover(timeout=300)
        except TimeoutError:
            pass
        else:
            raise AssertionError("Fixture did not reproduce the poster interception")
        assert await resume_native_video(page)
        assert await page.locator("#result").inner_text() == "clicked"
        print("PASS: poster intercepts media hover; player-container hover and native click succeed")
        # Nested document frames reproduce the real ebook's independent scroll area.
        pdf = '<style>body{margin:0}section{height:900px}</style>' + ''.join(
            f'<section id="anchor{i}">Page {i}</section>' for i in range(1, 7))
        document = '<iframe id="panView" style="height:400px;width:700px" srcdoc="' + html.escape(pdf, quote=True) + '"></iframe>'
        card = '<iframe class="insertdoc-online-ppt" style="height:450px;width:750px" srcdoc="' + html.escape(document, quote=True) + '"></iframe>'
        await page.set_content('<iframe id="iframe" style="height:500px;width:800px" srcdoc="' + html.escape(card, quote=True) + '"></iframe>')
        result = await scroll_ebook_to_bottom(page.frame_locator('#iframe'))
        await page.wait_for_timeout(500)
        viewer = page.frame_locator('#iframe').frame_locator('iframe.insertdoc-online-ppt').frame_locator('#panView')
        bottom = await viewer.locator('body').evaluate('e => {const s=document.scrollingElement;return s.scrollTop+s.clientHeight>=s.scrollHeight-2}')
        assert result['page_count'] == 6 and bottom
        print("PASS: native keyboard/scroll reaches the bottom of the nested ebook viewer")
        await browser.close()


asyncio.run(main())
