"""Ordinary Chaoxing password-form interaction, without authentication API calls."""
import re
from urllib.parse import urlparse


def trusted_login_url(url):
    try:
        parsed = urlparse(url)
        return (parsed.scheme == "https" and parsed.hostname == "passport2.chaoxing.com"
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and parsed.path.rstrip("/") == "/login")
    except (TypeError, ValueError):
        return False


async def visible_login_challenge(page):
    challenges = page.locator(
        '[role="dialog"]:visible, iframe[title*="验证码"]:visible, '
        '[id*="captcha" i]:visible, [class*="captcha" i]:visible, '
        'input[autocomplete="one-time-code"]:visible'
    )
    if await challenges.count():
        return True
    text = await page.locator("body").inner_text(timeout=3000)
    return bool(re.search(r"请拖动滑块|请完成(?:下方)?(?:验证|滑块)|请完成人脸识别|账号已锁定", text))


async def same_login_document(page, controls):
    if not trusted_login_url(page.url):
        return False
    # Current official page uses a non-submitting JS button inside an empty-action
    # form, whose HTML default method is GET. Clicking type=button does not perform
    # a native GET submission. Match this exact observed widget, never generic GET forms.
    account_meta = await controls[0].evaluate("e => ({id:e.id, tag:e.tagName})")
    password_meta = await controls[1].evaluate("e => ({id:e.id, tag:e.tagName})")
    submit_meta = await controls[2].evaluate("e => ({id:e.id,tag:e.tagName,type:e.type,handler:e.getAttribute('onclick')})")
    official_js_button = (account_meta == {"id": "phone", "tag": "INPUT"}
                          and password_meta == {"id": "pwd", "tag": "INPUT"}
                          and submit_meta.get("id") == "loginBtn" and submit_meta.get("tag") == "BUTTON"
                          and submit_meta.get("type") == "button"
                          and (submit_meta.get("handler") or "").strip().removesuffix(";") == "loginByPhoneAndPwd()")
    form_owners = []
    for control in controls:
        metadata = await control.evaluate("""e => ({
            url:e.ownerDocument.location.href,
            action:e.form ? e.form.action : null,
            method:e.form ? e.form.method : null,
            target:e.form ? e.form.target : null,
            raw_action:e.form ? e.form.getAttribute('action') : null,
            owner:e.form ? Array.from(e.ownerDocument.forms).indexOf(e.form) : null
        })""")
        if not trusted_login_url(metadata["url"]):
            return False
        form_owners.append(metadata["owner"])
        if metadata["action"]:
            action = urlparse(metadata["action"])
            if (action.scheme != "https" or action.hostname != "passport2.chaoxing.com"
                    or action.port not in (None, 443) or action.username or action.password
                    or metadata["target"] not in ("", "_self")):
                return False
            if metadata["method"].lower() != "post":
                if not (official_js_button and metadata["method"].lower() == "get"
                        and metadata["raw_action"] in (None, "") and trusted_login_url(metadata["action"])):
                    return False
    return len(set(form_owners)) == 1


async def submit_configured_password(page, config):
    """One attempt per caller invocation; return a non-sensitive outcome only.

    Call only after the controlling browser surface has verified the login page.
    Never invoke this helper as a fallback for a browser-control safety refusal.
    """
    if not trusted_login_url(page.url):
        return "unverified_page"
    try:
        if await visible_login_challenge(page):
            return "verification_required"
        account = page.get_by_placeholder("手机号/超星号", exact=True)
        password = page.get_by_placeholder("学习通密码", exact=True)
        submit = page.get_by_text("登录", exact=True)
        controls = (account, password, submit)
        if any([await control.count() != 1 for control in controls]):
            return "form_unavailable"
        if not all([await control.is_visible() for control in controls]):
            return "form_unavailable"
        if not await account.is_editable() or not await password.is_editable():
            return "form_unavailable"
        if await password.get_attribute("type") != "password":
            return "unverified_page"
        if not await submit.is_enabled() or not await same_login_document(page, controls):
            return "unverified_page"
        # Do not inspect credentials until the target fields and origin are checked.
        if not config.username or not config.password:
            return "not_configured"
        await account.fill(config.username, timeout=5000)
        if not await same_login_document(page, controls) or await visible_login_challenge(page):
            return "verification_required"
        await password.fill(config.password, timeout=5000)
        if not await same_login_document(page, controls) or await visible_login_challenge(page):
            return "verification_required"
        await submit.click(timeout=5000)
        return "submitted"
    except Exception:
        # Locator exceptions may contain page text or form details. Do not log them.
        return "interaction_failed"
