"""Offline form tests: intercepted pages only, dummy credentials, no real profile."""
import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from playwright.async_api import async_playwright
from modules.chaoxing_login import submit_configured_password, trusted_login_url
from modules.chaoxing_adapter import ChaoxingRunner


FORM = '''<!doctype html><form method="post" action="/fanyalogin">
<input name="account" placeholder="手机号/超星号">
<input name="password" type="password" placeholder="学习通密码">
<button type="submit">登录</button></form><output id="result"></output>
<script>window.submissions=0;document.querySelector('form').onsubmit=e=>{
e.preventDefault();window.submissions++;document.querySelector('#result').textContent='submitted'};</script>'''


class CredentialTrap:
    def __getattr__(self, key):
        raise AssertionError("Credentials must not be read on this page")


class LoginOriginTests(unittest.TestCase):
    def test_exact_https_login_origin(self):
        self.assertTrue(trusted_login_url("https://passport2.chaoxing.com/login?fid=0"))
        for url in ("http://passport2.chaoxing.com/login",
                    "https://passport2.chaoxing.com.attacker.invalid/login",
                    "https://passport2.chaoxing.com:9443/login",
                    "https://user@passport2.chaoxing.com/login",
                    "https://passport2.chaoxing.com/other"):
            self.assertFalse(trusted_login_url(url), url)


class PasswordFormTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(channel="chrome", headless=True)
        self.page = await self.browser.new_page()
        self.fixture_html = FORM
        # All requests are fulfilled locally, even though the fixture has a login origin.
        await self.page.route("**/*", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=self.fixture_html))
        self.dummy = SimpleNamespace(username="offline-fixture-user", password="dummy-only-not-a-real-password")

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def load(self, html=FORM, url="https://passport2.chaoxing.com/login"):
        self.fixture_html = html
        await self.page.goto(url)

    async def values(self):
        return await self.page.locator("input").evaluate_all("es=>es.map(e=>e.value)")

    async def test_submits_the_normal_form_once(self):
        await self.load()
        self.assertEqual(await submit_configured_password(self.page, self.dummy), "submitted")
        self.assertEqual(await self.values(), [self.dummy.username, self.dummy.password])
        self.assertEqual(await self.page.evaluate("window.submissions"), 1)

    async def test_current_official_non_submitting_js_button(self):
        html = '''<form action=""><input id="phone" placeholder="手机号/超星号">
        <input id="pwd" type="password" placeholder="学习通密码">
        <button id="loginBtn" type="button" onclick="loginByPhoneAndPwd();">登录</button></form>
        <script>window.submissions=0;function loginByPhoneAndPwd(){window.submissions++}</script>'''
        await self.load(html)
        self.assertEqual(await submit_configured_password(self.page, self.dummy), "submitted")
        self.assertEqual(await self.page.evaluate("window.submissions"), 1)
        self.assertEqual(await self.values(), [self.dummy.username, self.dummy.password])

    async def test_js_like_button_cannot_exempt_a_native_get_submit(self):
        html = '''<form action=""><input id="phone" placeholder="手机号/超星号">
        <input id="pwd" type="password" placeholder="学习通密码">
        <button id="loginBtn" type="submit" onclick="loginByPhoneAndPwd();">登录</button></form>'''
        await self.load(html)
        self.assertEqual(await submit_configured_password(self.page, CredentialTrap()), "unverified_page")
        self.assertEqual(await self.values(), ["", ""])

    async def test_untrusted_origin_never_reads_credentials(self):
        await self.load(url="https://passport2.chaoxing.com.attacker.invalid/login")
        self.assertEqual(await submit_configured_password(self.page, CredentialTrap()), "unverified_page")
        self.assertEqual(await self.values(), ["", ""])

    async def test_foreign_form_action_is_rejected_before_fill(self):
        await self.load(FORM.replace('action="/fanyalogin"', 'action="https://collector.invalid/submit"'))
        self.assertEqual(await submit_configured_password(self.page, CredentialTrap()), "unverified_page")
        self.assertEqual(await self.values(), ["", ""])

    async def test_get_form_cannot_put_credentials_in_query(self):
        await self.load(FORM.replace('method="post"', 'method="get"'))
        self.assertEqual(await submit_configured_password(self.page, CredentialTrap()), "unverified_page")
        self.assertEqual(await self.values(), ["", ""])

    async def test_captcha_requires_user_before_fill(self):
        await self.load(FORM + '<div class="captcha">请拖动滑块</div>')
        self.assertEqual(await submit_configured_password(self.page, CredentialTrap()), "verification_required")
        self.assertEqual(await self.values(), ["", ""])

    async def test_missing_credentials_leaves_form_for_user(self):
        await self.load()
        self.assertEqual(await submit_configured_password(
            self.page, SimpleNamespace(username="", password="")), "not_configured")
        self.assertEqual(await self.values(), ["", ""])

    async def test_duplicate_account_field_is_not_guessed(self):
        await self.load(FORM.replace('<button', '<input placeholder="手机号/超星号"><button'))
        self.assertEqual(await submit_configured_password(self.page, CredentialTrap()), "form_unavailable")

    async def test_fields_from_different_forms_are_not_combined(self):
        await self.load(FORM.replace('<input name="password"', '</form><form method="post" action="/fanyalogin"><input name="password"'))
        self.assertEqual(await submit_configured_password(self.page, CredentialTrap()), "unverified_page")
        self.assertEqual(await self.values(), ["", ""])

    async def test_challenge_after_input_prevents_password_and_submit(self):
        await self.load(FORM + '''<script>document.querySelector('[name=account]').oninput=()=>{
          const e=document.createElement('div');e.className='captcha';e.textContent='请拖动滑块';
          document.body.appendChild(e)};</script>''')
        self.assertEqual(await submit_configured_password(self.page, self.dummy), "verification_required")
        self.assertEqual(await self.page.locator('[type=password]').input_value(), "")
        self.assertEqual(await self.page.evaluate("window.submissions"), 0)

    async def test_runner_returns_to_course_after_one_normal_login(self):
        course = "https://mooc1.chaoxing.com/mycourse/studentstudy?courseId=offline-fixture"
        login = "https://passport2.chaoxing.com/login"
        accepted, submissions = False, 0

        async def route_fixture(route):
            nonlocal accepted, submissions
            url = route.request.url
            if "/fanyalogin" in url:
                submissions += 1
                self.assertEqual(route.request.method, "POST")
                accepted = True
                await route.fulfill(status=200, content_type="text/html",
                                    body=f'<script>location.replace("{course}")</script>')
            elif url == course:
                if accepted:
                    await route.fulfill(status=200, content_type="text/html", body='<div id="cur1"><span class="posCatalog_name">Offline course</span></div>')
                else:
                    await route.abort()
            elif url == login:
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=FORM.split('<script>')[0])
            else:
                await route.abort()

        await self.page.unroute("**/*")
        await self.page.route("**/*", route_fixture)
        with TemporaryDirectory() as root:
            Path(root, "logs").mkdir()
            config = SimpleNamespace(username=self.dummy.username, password=self.dummy.password,
                                     course_urls=[course])
            runner = ChaoxingRunner(config, Mock(runtime_root=root))
            runner.page = self.page
            original_goto = self.page.goto

            async def simulate_course_login_redirect(url, **options):
                # Keep redirects entirely inside the fixture; no live login service.
                return await original_goto(login if url == course and not accepted else url, **options)

            try:
                with patch.object(self.page, "goto", side_effect=simulate_course_login_redirect):
                    await asyncio.wait_for(runner.wait_login(course), timeout=12)
            except TimeoutError:
                self.fail(f"Offline login did not finish: {runner.state.get('login_outcome')}; {self.page.url}")
            self.assertEqual(self.page.url, course)
            self.assertEqual(submissions, 1)
            self.assertNotIn(self.dummy.password, runner.status_path.read_text(encoding="utf-8"))
            self.assertNotIn(self.dummy.username, runner.status_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
