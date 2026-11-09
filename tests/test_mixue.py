"""Offline API contract and real-browser checks for the MiXue port."""
import configparser
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from playwright.async_api import async_playwright

from modules.mixue import (MixueClient, MixueError, MixueOptions, allowed_frame,
                           build_browser_script, extract_answer, install_mixue)
from modules.chaoxing_adapter import ChaoxingRunner


def configuration(**values):
    parser = configparser.ConfigParser()
    parser.read_dict({"mixue-option": {"enabled": "True", "apiKey": "OFFLINE_SECRET_KEY",
        "autoAnswer": "False", "autoSubmit": "False", "hintsOnly": "False", **values}})
    return SimpleNamespace(_config=parser)


class MixueContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_tiku_contract_cache_and_no_redirect(self):
        client = MixueClient(MixueOptions(api_key="offline-key"))
        response = Mock(status_code=200, content=b'{}')
        response.json.return_value = {"code": 1000, "data": {"answer": "A"}}
        with patch('modules.mixue.requests.post', return_value=response) as post:
            q = {"text": "题目", "type": 0, "options": ["选项一", "选项二"]}
            self.assertEqual(await client.answer(q), {"answer": "A", "source": "题库"})
            await client.answer(q)
            post.assert_called_once()
            args = post.call_args
            self.assertEqual(args.args[0], 'https://tk.mixuelo.cc/api.php')
            self.assertEqual(args.kwargs['data'], {"key":"offline-key", "question":"题目", "type":"0", "options":"选项一|选项二"})
            self.assertFalse(args.kwargs['allow_redirects'])

    async def test_missing_answer_falls_back_to_ai_with_options(self):
        client = MixueClient(MixueOptions(api_key="offline", use_ai=True))
        with patch.object(client, '_post', side_effect=[
            {"code": 0, "msg": "未找到答案"}, {"code": 200, "data": {"answer": "B"}}
        ]) as post:
            result = await client.answer({"text":"选择", "type":0, "options":["甲","乙"]})
            self.assertEqual(result, {"answer":"B", "source":"AI"})
            self.assertEqual(post.call_args.args[0], 'autoai')
            self.assertIn('B. 乙', post.call_args.kwargs['json']['messages'][1]['content'])

    async def test_invalid_key_is_not_retried_or_randomly_answered(self):
        client = MixueClient(MixueOptions(api_key="secret", use_ai=True))
        with patch.object(client, '_post', return_value={"code":0,"msg":"Key验证失败 secret"}) as post:
            with self.assertRaises(MixueError) as error:
                await client.answer({"text":"测试", "type":0})
            self.assertNotIn('secret',str(error.exception))
            post.assert_called_once()

    async def test_missing_key_and_bad_payload_never_make_request(self):
        with patch('modules.mixue.requests.post') as post:
            for options, q in [(MixueOptions(), {"text":"题目"}),
                               (MixueOptions(api_key="x"), {"text":"题目", "type":9})]:
                with self.assertRaises(MixueError):
                    await MixueClient(options).answer(q)
            post.assert_not_called()

    def test_legacy_config_disabled_and_browser_has_no_key(self):
        self.assertFalse(MixueOptions.from_config(SimpleNamespace(_config=configparser.ConfigParser())).enabled)
        script = build_browser_script(MixueOptions(api_key='DO_NOT_INJECT_THIS_KEY'))
        self.assertNotIn('DO_NOT_INJECT_THIS_KEY', script)
        self.assertFalse(allowed_frame('https://chaoxing.com.attacker.test/work/'))
        self.assertFalse(allowed_frame('http://mooc1.chaoxing.com/work/'))
        self.assertTrue(allowed_frame('https://mooc1.chaoxing.com/mooc2/work/dowork'))
        self.assertIsNone(extract_answer({'code':0,'msg':'未找到答案'}))


FORM = '''<form><div class="questionLi" typename="单选题">
    <h3 class="mark_name">中国首都是哪里？</h3><div class="stem_answer">
    <label class="answerBg"><input type="radio" name="city" value="a"><span class="answer_p">A. 北京</span></label>
    <label class="answerBg"><input type="radio" name="city" value="b"><span class="answer_p">B. 上海</span></label>
    </div></div><button type="button" onclick="window.submits=(window.submits||0)+1">提交</button></form>'''


class MixueBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def open_fixture(self, config, html=FORM, url='https://mooc1.chaoxing.com/mooc2/work/dowork'):
        playwright = await async_playwright().start()
        self.addAsyncCleanup(playwright.stop)
        browser = await playwright.chromium.launch(channel='chrome', headless=True)
        self.addAsyncCleanup(browser.close)
        context = await browser.new_context()
        await context.route('**/*', lambda route: route.fulfill(status=200,content_type='text/html; charset=utf-8',
            body=html if route.request.url == url else '<html><body></body></html>'))
        client = await install_mixue(context, config, Mock())
        page = await context.new_page()
        self.errors = []
        page.on('pageerror', lambda e:self.errors.append(str(e)))
        await page.goto(url)
        return context, page, client

    async def test_real_panel_tiku_fill_and_submit(self):
        context, page, client = await self.open_fixture(configuration(autoSubmit='True'))
        with patch.object(client, '_post', return_value={"code":200,"data":{"answer":"北京"}}) as post:
            await page.locator('#autovisor-mixue-panel').wait_for()
            await page.get_by_role('button',name='处理当前页题目',exact=True).click()
            await page.wait_for_function('window.submits === 1')
            self.assertTrue(await page.locator('input[value=a]').is_checked())
            self.assertFalse(await page.locator('input[value=b]').is_checked())
            self.assertEqual(post.call_args.kwargs['data']['options'],'北京|上海')
            self.assertEqual(self.errors,[])
            self.assertNotIn('OFFLINE_SECRET_KEY',await page.content())
            self.assertEqual(await page.locator('#autovisor-mixue-panel').count(),1)

    async def test_hint_mode_and_ambiguous_answer_do_not_submit(self):
        _, page, client = await self.open_fixture(configuration(autoSubmit='True',hintsOnly='True'))
        with patch.object(client, '_post', return_value={"code":200,"data":{"answer":"A"}}):
            await page.evaluate('window.__autovisorMixue.processQuestions()')
            self.assertFalse(await page.locator('input[value=a]').is_checked())
            self.assertEqual(await page.evaluate('window.submits||0'),0)
        client.cache.clear()
        await page.evaluate('window.__autovisorMixue.settings.hintsOnly=false')
        with patch.object(client, '_post', return_value={"code":200,"data":{"answer":"I think A or B might work"}}):
            await page.evaluate('window.__autovisorMixue.processQuestions()')
            self.assertFalse(await page.locator('input[value=a]').is_checked())
            self.assertEqual(await page.evaluate('window.submits||0'),0)

    async def test_nested_iframe_injection_and_dynamic_question(self):
        outer = '<iframe src="https://mooc1.chaoxing.com/mooc2/work/dowork"></iframe>'
        context, page, client = await self.open_fixture(configuration(autoAnswer='True'), outer,
            'https://mooc1.chaoxing.com/mycourse/studentstudy')
        await context.route('**/mooc2/work/dowork',lambda route:route.fulfill(status=200,content_type='text/html; charset=utf-8',body=FORM))
        with patch.object(client,'_post',return_value={"code":200,"data":{"answer":"A"}}):
            await page.reload()
            frame = page.frame_locator('iframe')
            await frame.locator('input[value=a]').wait_for()
            await page.wait_for_function("document.querySelector('iframe').contentDocument.querySelector('input[value=a]').checked")
            self.assertEqual(await frame.locator('#autovisor-mixue-panel').count(),1)
            self.assertEqual(self.errors,[])

    async def test_matching_multi_judgment_and_fill_blank(self):
        _, page, client = await self.open_fixture(configuration())
        results=await page.evaluate('''() => {const m=window.__autovisorMixue.matchChoices;return [
            m('AC',['甲','乙','丙'],1),m('正确',['正确','错误'],3),
            m('选项甲|选项丙',['选项甲','选项乙','选项丙'],1),
            m('A or B',['甲','乙'],0),m('AB',['甲','乙'],0),m('Z',['甲','乙'],0)];}''')
        self.assertEqual(results,[[0,2],[0],[0,2],[],[],[]])
        await page.locator('form').evaluate('''form => {form.innerHTML='<div class="questionLi" typename="填空题"><h3 class="mark_name">两个空</h3><textarea></textarea><textarea></textarea></div>';}''')
        with patch.object(client,'_post',return_value={"code":200,"data":{"answer":"甲|乙"}}):
            await page.evaluate('window.__autovisorMixue.processQuestions()')
            self.assertEqual(await page.locator('textarea').evaluate_all('els=>els.map(e=>e.value)'),['甲','乙'])

    async def test_unknown_font_does_not_send_garbled_question(self):
        html=FORM.replace('class="mark_name"','class="mark_name font-cxsecret"')
        _, page, client=await self.open_fixture(configuration(), html)
        with patch.object(client,'_post') as post:
            await page.evaluate('window.__autovisorMixue.processQuestions()')
            post.assert_not_called()
            self.assertIn('字体解码失败',await page.locator('#autovisor-mixue-panel').inner_text())

    async def test_key_entry_stays_in_python_and_other_hosts_have_no_panel(self):
        context,page,client=await self.open_fixture(configuration(apiKey=''))
        await page.locator('#autovisor-mixue-panel input[type=password]').fill('TEMPORARY_KEY')
        await page.get_by_role('button',name='使用 Key',exact=True).click()
        await page.wait_for_function("document.querySelector('#autovisor-mixue-panel input[type=password]').value === ''")
        self.assertEqual(client.options.api_key,'TEMPORARY_KEY')
        self.assertEqual(await page.evaluate('Object.keys(localStorage).length'),0)
        foreign=await context.new_page(); await foreign.goto('https://example.org/work/')
        self.assertEqual(await foreign.locator('#autovisor-mixue-panel').count(),0)
        self.assertIn('error',await foreign.evaluate("window.__autovisorMixueCall('answer',{text:'x'})"))

    async def test_key_entered_in_parent_restarts_automatic_iframe_query(self):
        outer='<iframe src="https://mooc1.chaoxing.com/mooc2/work/dowork"></iframe>'
        context,page,client=await self.open_fixture(configuration(apiKey='',autoAnswer='True'),outer,
            'https://mooc1.chaoxing.com/mycourse/studentstudy')
        await context.route('**/mooc2/work/dowork',lambda r:r.fulfill(status=200,content_type='text/html; charset=utf-8',body=FORM))
        with patch.object(client,'_post',return_value={"code":200,"data":{"answer":"A"}}) as post:
            await page.reload()
            await page.frame_locator('iframe').locator('#autovisor-mixue-panel').wait_for()
            post.assert_not_called()
            await page.locator('#autovisor-mixue-panel input[type=password]').fill('PARENT_KEY')
            await page.get_by_role('button',name='使用 Key',exact=True).click()
            await page.wait_for_function("document.querySelector('iframe').contentDocument.querySelector('input[value=a]').checked")
            self.assertEqual(post.call_args.kwargs['data']['key'],'PARENT_KEY')

    async def test_runner_waits_for_real_assessment_marker(self):
        _,page,_=await self.open_fixture(configuration(),'<div class="ans-attach-ct"><span class="ans-job-icon" aria-label="任务点未完成"></span><iframe src="/work/offline"></iframe></div>')
        with TemporaryDirectory() as folder:
            Path(folder,'logs').mkdir()
            config=SimpleNamespace(course_urls=['https://mooc1.chaoxing.com/mycourse/studentstudy?courseId=1'],limitMaxTime=0)
            runner=ChaoxingRunner(config,Mock(runtime_root=folder)); runner.page=page
            runner.blocker=AsyncMock(return_value=None)
            real_sleep=asyncio.sleep
            async def tick(_): await real_sleep(.02)
            with patch('modules.chaoxing_adapter.asyncio',SimpleNamespace(sleep=tick)):
                task=asyncio.create_task(runner.wait_for_assessments(page))
                try:
                    await real_sleep(.1)
                    self.assertFalse(task.done())
                    self.assertEqual(runner.state['status'],'waiting_assessment')
                    self.assertFalse(runner.state['all_complete'])
                    await page.locator('.ans-attach-ct').evaluate("el=>el.classList.add('ans-job-finished')")
                    self.assertTrue(await asyncio.wait_for(task,2))
                finally:
                    task.cancel(); await asyncio.gather(task,return_exceptions=True)
