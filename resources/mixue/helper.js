// Adapted MiXue helper. MIT; see NOTICE.md. Runs once per Chaoxing document.
const settings = {...MIXUE_SETTINGS};
const norm = s => String(s || '').replace(/\s+/g, '').replace(/^[A-Z][.、．:：]\s*/i, '').trim();
const visible = el => !!(el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
const state = {busy: false, polling: false, keyRevision: -1, lastSignature: '', fontError: '', handled: new WeakMap()};
let panel, status, answers, keyInput;

function log(message) { if (status) status.textContent = message; }
function decodeFonts() {
  if (!settings.decrypt) return true;
  const styles = [...document.querySelectorAll('style')].filter(s => s.textContent.includes('font-cxsecret'));
  const targets = [...document.querySelectorAll('.font-cxsecret')];
  if (!targets.length) return true;
  try {
    const match = styles.map(s => s.textContent).join('\n').match(/base64,([A-Za-z0-9+/=\s]+)["')]/);
    if (!match) throw Error('未找到内嵌字体');
    const bytes = Uint8Array.from(atob(match[1].replace(/\s/g,'')), c => c.charCodeAt(0));
    const font = Typr.parse(bytes.buffer)[0], mapping = new Map();
    for (let code = 19968; code < 40870; code++) {
      const glyph = Typr.U.codeToGlyph(font, code);
      if (!glyph) continue;
      const fingerprint = md5(JSON.stringify(Typr.U.glyphToPath(font, glyph))).slice(24);
      if (MIXUE_TABLE[fingerprint] !== undefined) mapping.set(String.fromCharCode(code), String.fromCharCode(MIXUE_TABLE[fingerprint]));
    }
    for (const el of targets) {
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let node;
      const nodes = []; while ((node = walker.nextNode())) nodes.push(node);
      if (nodes.some(n => [...n.nodeValue].some(c => /[\u4e00-\u9fff]/.test(c) && !mapping.has(c)))) {
        throw Error('字体表未匹配全部汉字');
      }
      for (const n of nodes) n.nodeValue = [...n.nodeValue].map(c => mapping.get(c) ?? c).join('');
      el.classList.remove('font-cxsecret');
    }
    state.fontError = ''; return true;
  } catch (e) { state.fontError = '字体解码失败：' + e.message; log(state.fontError); return false; }
}

function questionRoots() {
  const roots = [...document.querySelectorAll('.questionLi,.singleQuesId,.Py-mian1,.TiMu,.whiteDiv,[data-mixue-question]')].filter(visible);
  const leaves = roots.filter(r => !roots.some(other => other !== r && r.contains(other)));
  if (leaves.length) return leaves;
  // Some in-video questions have no named wrapper; constrain the fallback to
  // a visible dialog or video question container, never the entire course body.
  return [...document.querySelectorAll('[role="dialog"],.ans-videoquiz,.videoquiz,.video-question')]
    .filter(el => visible(el) && el.querySelector('input[type="radio"],input[type="checkbox"],[role="radio"],[role="checkbox"]'));
}

function readQuestion(root) {
  const heading = root.querySelector('.mark_name,.Zy_TItle,.Zy_TItle>div,.question-title,.title,[data-question-title]');
  const text = (heading?.innerText || root.getAttribute('data-question-text') || root.innerText).trim().slice(0, 20000);
  const typeText = (root.getAttribute('typename') || '') + text;
  let type = /多选/.test(typeText) ? 1 : /判断/.test(typeText) ? 3 : /填空/.test(typeText) ? 2 : /简答|论述|写作|翻译/.test(typeText) ? 4 : 0;
  let optionNodes = [...root.querySelectorAll('.answer_p,.Zy_ulTop li a,.Zy_ulTop li label,.option-content,[data-option]')].filter(visible);
  let controls = [...root.querySelectorAll('input[type="radio"],input[type="checkbox"],[role="radio"],[role="checkbox"]')].filter(visible);
  if (!optionNodes.length) optionNodes = controls.map(el => root.querySelector(`label[for="${CSS.escape(el.id)}"]`) || el.closest('label') || el.parentElement);
  if (controls.some(c => c.type === 'checkbox' || c.getAttribute('role') === 'checkbox')) type = 1;
  const fields = [...root.querySelectorAll('textarea,input[type="text"],[contenteditable="true"]')]
    .filter(el => visible(el) || !!window.UE?.instants?.[el.id || el.name]);
  if (!optionNodes.length && fields.length) type = /简答|论述|写作|翻译/.test(typeText) ? 4 : 2;
  return {root, text, type, options: optionNodes.map(el => norm(el.innerText || el.textContent)), optionNodes, controls, fields};
}

function matchChoices(answer, options, type) {
  const clean = String(answer || '').trim().replace(/^答案\s*[:：]\s*/, '');
  if (type === 3) {
    const truth = /^(正确|对|是|√|true|T)$/i.test(clean) ? true : /^(错误|错|否|×|false|F)$/i.test(clean) ? false : null;
    if (truth !== null) {
      const i = options.findIndex(o => truth ? /^(正确|对|是|√|true|T)$/i.test(o) : /^(错误|错|否|×|false|F)$/i.test(o));
      return i >= 0 ? [i] : [];
    }
  }
  // Require the complete response to be a letter/list or exact option text;
  // prose containing a letter cannot accidentally select an answer.
  if (/^[A-Z](?:[A-Z\s,，、|;；]*)$/i.test(clean)) {
    const indexes = [...new Set(clean.toUpperCase().replace(/[^A-Z]/g,'').split('').map(c => c.charCodeAt(0)-65))];
    if (indexes.every(i => i < options.length) && (type === 1 || indexes.length === 1)) return indexes;
  }
  const exact = options.map((o,i) => norm(clean) === norm(o) ? i : -1).filter(i => i >= 0);
  if (exact.length === 1) return exact;
  if (type === 1) {
    const parts = clean.split(/[|\n;；]/).map(norm).filter(Boolean);
    const indexes = parts.map(p => options.findIndex(o => norm(o) === p));
    if (indexes.length && indexes.every(i => i >= 0)) return [...new Set(indexes)];
  }
  return [];
}

function fillQuestion(q, answer) {
  if (q.options.length) {
    const indexes = matchChoices(answer, q.options, q.type);
    if (!indexes.length) return false;
    for (let i = 0; i < q.options.length; i++) {
      const control = q.controls[i];
      const selected = indexes.includes(i);
      const checked = control ? (control.checked ?? control.getAttribute('aria-checked') === 'true') : q.optionNodes[i].closest('li, label, .answerBg')?.querySelector('.check_answer,.check_answer_dx');
      if ((selected && !checked) || (q.type === 1 && !selected && checked)) {
        (control || q.optionNodes[i].closest('li,label,.answerBg') || q.optionNodes[i]).click();
      }
    }
    if (q.controls.length === q.options.length && q.controls.some((el,i) => {
      const checked = el.checked ?? el.getAttribute('aria-checked') === 'true';
      return checked !== indexes.includes(i);
    })) return false;
    state.handled.set(q.root, answer); return true;
  }
  if (!q.fields.length) return false;
  const parts = q.type === 2 ? String(answer).split('|') : [String(answer)];
  if (parts.length !== q.fields.length) return false;
  for (let i = 0; i < q.fields.length; i++) {
    const field = q.fields[i], id = field.id || field.name;
    if (window.UE?.getEditor && id) window.UE.getEditor(id).setContent(parts[i]);
    else if (field.isContentEditable) field.textContent = parts[i];
    else {
      const proto = field.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(field, parts[i]);
    }
    field.dispatchEvent(new Event('input', {bubbles:true}));
    field.dispatchEvent(new Event('change', {bubbles:true}));
  }
  state.handled.set(q.root, answer); return true;
}

async function processQuestions() {
  if (state.busy) return;
  state.busy = true;
  const submittedForms = new Set();
  try {
    if (!decodeFonts()) return;
    const questions = questionRoots().map(readQuestion).filter(q => q.text);
    if (!questions.length) { log('未识别到题目；视频由 Autovisor 控制'); return; }
    answers.replaceChildren();
    let filled = 0;
    const results = [];
    for (let index = 0; index < questions.length; index++) {
      const q = questions[index]; log(`查询第 ${index+1}/${questions.length} 题…`);
      const result = await window.__autovisorMixueCall('answer', {text:q.text,type:q.type,options:q.options});
      const row = document.createElement('div'); row.style.cssText = 'margin:6px 0;white-space:pre-wrap;overflow-wrap:anywhere';
      row.textContent = `${index+1}. ${result.error || '['+result.source+'] '+result.answer}`;
      answers.append(row);
      let applied = false;
      if (!result.error && result.answer && settings.autoAnswer && !settings.hintsOnly) applied = fillQuestion(q, result.answer);
      if (applied) filled++;
      results.push({q,applied});
    }
    if (filled === questions.length && settings.autoSubmit && settings.autoAnswer && !settings.hintsOnly) {
      // Submit only a form whose every recognized question was filled. Unknown
      // or ambiguous answers never trigger a force/confirm submission.
      for (const {q} of results) {
        const scope = q.root.closest('form') || q.root.closest('[role="dialog"],.ans-videoquiz,.videoquiz,.video-question');
        if (!scope || submittedForms.has(scope)) continue;
        const buttons = [...scope.querySelectorAll('button,a,input[type="submit"],input[type="button"]')].filter(visible)
          .filter(b => /^(提交|提交答案|确认答案)$/.test((b.innerText || b.value || '').trim()));
        if (buttons.length === 1) { buttons[0].click(); submittedForms.add(scope); }
      }
    }
    log((settings.hintsOnly || !settings.autoAnswer) ? `已查询 ${questions.length} 题，仅显示答案` : `已匹配填入 ${filled}/${questions.length} 题` + (settings.autoSubmit ? '；提交仍以平台结果为准' : '；请检查后手动提交'));
  } catch (_) { log('查询失败或页面已切换，请重试'); }
  finally { state.busy = false; }
}

function mount() {
  if (!document.body || panel) return;
  // No login pages, no empty video frames. Parent course panel and actual
  // assessment frames each get one independent panel.
  if (!/studentstudy|knowledge\/cards|\/work\/|\/exam\//.test(location.pathname) && !questionRoots().length) return;
  panel = document.createElement('aside'); panel.id = 'autovisor-mixue-panel';
  panel.style.cssText = 'position:fixed;right:12px;top:80px;width:290px;max-height:65vh;overflow:auto;z-index:2147483000;background:#fff;color:#222;padding:12px;border:1px solid #56cabf;border-radius:10px;box-shadow:0 4px 16px #0003;font:14px/1.5 "Microsoft YaHei",sans-serif;text-align:left';
  const title = document.createElement('strong'); title.textContent = 'Autovisor · 蜜雪助手（F9 显隐）'; panel.append(title);
  const note = document.createElement('p'); note.textContent = '默认使用答案提示。查询会向蜜雪发送题目和选项；自动填答和自动提交可能影响成绩及账号，请先确认学校和平台允许。'; panel.append(note);
  keyInput = document.createElement('input'); keyInput.type = 'password'; keyInput.placeholder = '题库 Key（仅本次运行）'; keyInput.style.width='95%'; panel.append(keyInput);
  const save = document.createElement('button'); save.textContent = '使用 Key'; save.onclick = async () => {
    const result = await window.__autovisorMixueCall('key',{key:keyInput.value});
    if (!result.error) { keyInput.value=''; state.lastSignature=''; }
    log(result.error || 'Key 已设定，可查询当前页面');
  }; panel.append(save);
  for (const [field,label] of [['hintsOnly','答案提示'],['autoAnswer','自动填答'],['autoSubmit','自动提交（默认关闭）']]) {
    const line=document.createElement('label'); line.style.display='block';
    const box=document.createElement('input'); box.type='checkbox'; box.checked=settings[field];
    box.onchange=()=>{settings[field]=box.checked;state.lastSignature='';};
    line.append(box,document.createTextNode(label)); panel.append(line);
  }
  const run=document.createElement('button'); run.textContent='查询本页参考答案'; run.onclick=processQuestions; panel.append(run);
  const notify=document.createElement('button'); notify.textContent='启用桌面通知'; notify.onclick=async()=>{
    if (!('Notification' in window)) return log('浏览器不支持通知');
    const permission=await Notification.requestPermission();
    log(permission==='granted' ? '已启用；需手动答题时会提醒' : '未获得通知权限');
  }; panel.append(notify);
  status=document.createElement('p'); answers=document.createElement('div'); panel.append(status,answers); document.body.append(panel);
  log(settings.hasKey ? '已读取配置中的 Key' : '等待输入题库 Key');
  document.addEventListener('keydown', e=>{if(e.key==='F9') panel.hidden=!panel.hidden;});
  // Allow dragging without overwriting the course's mouse handlers.
  title.style.cursor='move'; title.onpointerdown=e=>{
    const rect=panel.getBoundingClientRect(), dx=e.clientX-rect.left,dy=e.clientY-rect.top;
    title.setPointerCapture(e.pointerId);
    title.onpointermove=p=>{panel.style.left=Math.max(0,Math.min(innerWidth-panel.offsetWidth,p.clientX-dx))+'px';panel.style.top=Math.max(0,p.clientY-dy)+'px';panel.style.right='auto';};
    title.onpointerup=()=>{title.onpointermove=null;};
  };
}

window.__autovisorMixue = {processQuestions, matchChoices, decodeFonts, readQuestion, questionRoots, settings};
async function tick() {
  mount();
  if (!panel || state.busy || state.polling) return;
  state.polling = true;
  try {
    const current = await window.__autovisorMixueCall('status');
    if (current.revision !== state.keyRevision) { state.keyRevision=current.revision; state.lastSignature=''; }
    settings.hasKey=!!current.hasKey;
  } catch (_) { return; } finally { state.polling=false; }
  const questions=questionRoots().map(readQuestion);
  const signature=JSON.stringify(questions.map(q=>[q.text,q.type,q.options]));
  if (questions.length && signature!==state.lastSignature) {
    state.lastSignature=signature;
    if (settings.autoAnswer && settings.hasKey) processQuestions();
    else if ('Notification' in window && Notification.permission==='granted') new Notification('Autovisor 蜜雪助手',{body:'页面有题目，请打开浏览器处理'});
  }
}
if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',tick,{once:true}); else tick();
setInterval(tick,2000);
