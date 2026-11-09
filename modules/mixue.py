"""MiXue 1.1.0 API adapter, hosted by the existing Chaoxing browser runner.

API contracts and font matching are adapted from MIT-licensed Greasy Fork
533346 by mxbc_666 / MiXue-Lo. See resources/mixue/NOTICE.md.
"""
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests


API_URL = "https://tk.mixuelo.cc/api.php"
TYPE_NAMES = {0: "单选题", 1: "多选题", 2: "填空题", 3: "判断题", 4: "简答题"}


@dataclass
class MixueOptions:
    enabled: bool = False
    api_key: str = ""
    model: str = "deepseek-chat"
    use_tiku: bool = True
    use_ai: bool = False
    auto_answer: bool = False
    auto_submit: bool = False
    hints_only: bool = True
    decrypt: bool = True

    @classmethod
    def from_config(cls, config):
        parser = config._config
        section = "mixue-option"
        def boolean(name, default):
            return parser.getboolean(section, name, fallback=default)
        return cls(
            enabled=boolean("enabled", False),
            api_key=parser.get(section, "apiKey", raw=True, fallback="").strip(),
            model=parser.get(section, "model", raw=True, fallback="deepseek-chat").strip(),
            use_tiku=boolean("useTiku", True), use_ai=boolean("useAI", False),
            auto_answer=boolean("autoAnswer", False), auto_submit=boolean("autoSubmit", False),
            hints_only=boolean("hintsOnly", True), decrypt=boolean("decrypt", True),
        )

    def browser_settings(self):
        # The key is held by Python; it is never injected into the page.
        return {"autoAnswer": self.auto_answer, "autoSubmit": self.auto_submit,
                "hintsOnly": self.hints_only, "decrypt": self.decrypt,
                "hasKey": bool(self.api_key), "model": self.model}


class MixueError(Exception):
    pass


def allowed_frame(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "chaoxing.com" or host.endswith(".chaoxing.com"))


def extract_answer(payload):
    """Both xxt and autoai return {code: 200|1000, data: {answer: ...}}."""
    if not isinstance(payload, dict):
        raise MixueError("题库返回格式错误")
    data = payload.get("data")
    if payload.get("code") in (200, 1000) and isinstance(data, dict):
        answer = data.get("answer")
        if isinstance(answer, str) and answer.strip() not in ("", "无法回答", "我不知道", "暂无答案"):
            return answer.strip()
    message = str(payload.get("msg", ""))
    if "Key" in message or "key" in message or payload.get("code") == 1001:
        raise MixueError("题库 Key 无效、额度不足或服务拒绝，请检查 Key")
    if payload.get("code") == 0 and "未找到答案" not in message:
        raise MixueError("题库服务拒绝查询，请检查 Key 或服务状态")
    return None


class MixueClient:
    def __init__(self, options):
        self.options = options
        self.cache = {}
        self.lock = asyncio.Lock()
        self.key_revision = 0

    def _post(self, action, **kwargs):
        try:
            response = requests.post(
                API_URL, params={"act": action},
                headers={"Authorization": "Bearer " + self.options.api_key},
                timeout=(8, 120), allow_redirects=False, **kwargs,
            )
            if response.status_code != 200:
                raise MixueError(f"题库服务响应 HTTP {response.status_code}")
            if len(response.content) > 2_000_000:
                raise MixueError("题库响应过大")
            return response.json()
        except (requests.RequestException, ValueError):
            # Never propagate requests' URLs, headers or a response containing keys.
            raise MixueError("题库连接失败、超时或返回了非 JSON 内容") from None

    async def answer(self, question):
        if not self.options.api_key:
            raise MixueError("请先在面板输入题库 Key，或填写 config.ini 的 apiKey")
        text = str(question.get("text", "")).strip()
        choices = question.get("options", [])
        kind = question.get("type", 0)
        if kind not in TYPE_NAMES or not text or len(text) > 20000:
            raise MixueError("无法识别题目内容或题型")
        if not isinstance(choices, list) or len(choices) > 50 or any(not isinstance(c, str) or len(c) > 5000 for c in choices):
            raise MixueError("选项格式错误")
        cache_key = json.dumps([kind, text, choices, self.options.model], ensure_ascii=False)
        async with self.lock:
            if cache_key in self.cache:
                return self.cache[cache_key]
            answer = None
            source = "题库"
            if self.options.use_tiku:
                payload = await asyncio.to_thread(self._post, "xxt", data={
                    "key": self.options.api_key, "question": text,
                    "type": str(kind), "options": "|".join(choices),
                })
                answer = extract_answer(payload)
            if not answer and self.options.use_ai:
                prompt = TYPE_NAMES[kind] + ":" + text
                if choices:
                    prompt += "\n" + "\n".join(f"{chr(65+i)}. {c}" for i, c in enumerate(choices))
                payload = await asyncio.to_thread(self._post, "autoai", json={
                    "model": self.options.model,
                    "messages": [
                        {"role": "system", "content": "回答给出的练习题。选择题只回答选项字母，判断题只回答正确或错误，填空题用|分隔各空。"},
                        {"role": "user", "content": prompt},
                    ],
                })
                answer = extract_answer(payload)
                source = "AI"
            if not answer:
                raise MixueError("未找到答案，请手动完成此题")
            result = {"answer": answer, "source": source}
            self.cache[cache_key] = result
            return result


def resource_root():
    # Resources live next to the executable, matching Autovisor's distribution.
    import sys
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "resources" / "mixue"


def build_browser_script(options, assets=None):
    root = assets or resource_root()
    # All assets are pinned local files; no CDN loading or upstream script execution.
    table = json.loads((root / "table.json").read_text(encoding="utf-8-sig"))
    library = (root / "TyprMd5.js").read_text(encoding="utf-8-sig")
    helper = (root / "helper.js").read_text(encoding="utf-8")
    return """(() => {
      if (location.protocol !== 'https:' || !(location.hostname === 'chaoxing.com' || location.hostname.endsWith('.chaoxing.com'))) return;
      if (window.__autovisorMixueBoot) return;
      window.__autovisorMixueBoot = true;
    """ + library + "\nconst MIXUE_TABLE=" + json.dumps(table) + ";\nconst MIXUE_SETTINGS=" + json.dumps(options.browser_settings()) + ";\n" + helper + "\n})();"


async def install_mixue(context, config, logger):
    options = MixueOptions.from_config(config)
    if not options.enabled:
        return None
    client = MixueClient(options)

    async def bridge(source, action, payload=None):
        if not allowed_frame(source["frame"].url):
            return {"error": "只在学习通页面提供此功能"}
        try:
            if action == "status":
                return {"hasKey": bool(options.api_key), "revision": client.key_revision}
            if action == "key":
                value = str((payload or {}).get("key", "")).strip()
                if not value or len(value) > 1000:
                    raise MixueError("Key 不能为空或过长")
                async with client.lock:
                    options.api_key = value
                    client.cache.clear()
                    client.key_revision += 1
                return {"ok": True}
            if action == "answer" and isinstance(payload, dict):
                return await client.answer(payload)
            raise MixueError("未知面板操作")
        except MixueError as error:
            return {"error": str(error)}
        except Exception:
            return {"error": "查询发生错误，请重试"}

    await context.expose_binding("__autovisorMixueCall", bridge)
    await context.add_init_script(script=build_browser_script(options))
    logger.event("蜜雪辅助已接入", 题库=options.use_tiku, AI=options.use_ai,
                 自动填答=options.auto_answer, 自动提交=options.auto_submit, 仅提示=options.hints_only)
    return client
