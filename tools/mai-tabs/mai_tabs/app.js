/* The library page (DESIGN.md section 12). Served as a file so the page's CSP can forbid inline script. Text from the browser is only
 * ever set with textContent, and links are made only for http and https addresses. */
'use strict';
var LABEL = { 'research': '논문 · 연구', 'code': '코드', 'ai': 'AI', 'docs and notes': '문서 · 노트', 'video and music': '영상 · 음악',
              'chat and mail': '채팅 · 메일', 'browser internal': '브라우저', 'uncategorized': '기타', 'other': '기타' };
var ORDER = ['research', 'code', 'ai', 'docs and notes', 'video and music', 'chat and mail', 'uncategorized', 'other'];
var PAGE = 60;
var state = { view: null, mode: 'cat', q: '', openOnly: false, sel: new Set(), shown: {}, armed: null };

function $(id) { return document.getElementById(id); }
function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
function ago(ms) {
  if (!ms) return '알 수 없음';
  var s = Math.round((Date.now() - ms) / 1000);
  if (s < 90) return s + ' 초 전';
  if (s < 5400) return Math.round(s / 60) + ' 분 전';
  if (s < 172800) return Math.round(s / 3600) + ' 시간 전';
  return Math.round(s / 86400) + ' 일 전';
}
function mib(n) { return n === null || n === undefined ? '못 잼' : (Math.abs(n) >= 1024 ? (n / 1024).toFixed(1) + ' GB' : n + ' MB'); }
function signed(n) { return n === null || n === undefined ? '못 잼' : (n > 0 ? '+' : '') + mib(n); }

async function api(path, body) {
  var r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Mai-Tabs': '1' }, body: JSON.stringify(body) } : { cache: 'no-store' });
  var d = await r.json().catch(function () { return {}; });
  if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
  return d;
}

function note(text, cls) { var n = $('note'); n.textContent = text || ''; n.className = text ? cls : ''; }

async function act(action, ids, group, asleep) {
  try {
    var c = await api('/api/command', { action: action, items: ids, group: group || null, asleep: !!asleep });
    note(c.state === 'pending' ? 'PC 에 보냈습니다. PC 의 Chrome 이 30 초 안에 처리합니다 (2 분 안에 못 받으면 취소).' : '할 일이 없습니다 (' + (c.result || '') + ')', 'warn');
    await load();
  } catch (e) { note('보내지 못했습니다: ' + e.message, 'bad'); }
}

function confirmThen(key, btn, text, fn) {
  if (state.armed === key) { state.armed = null; fn(); return; }
  state.armed = key; btn.textContent = text; btn.classList.add('on');
  setTimeout(function () { if (state.armed === key) { state.armed = null; render(); } }, 4000);
}

function matches(it) {
  if (state.openOnly && !it.open_tabs) return false;
  if (!state.q) return true;
  var q = state.q.toLowerCase();
  return (it.title + ' ' + it.url + ' ' + it.line).toLowerCase().indexOf(q) >= 0;
}

function groupButtons(head, ids, title) {
  var openIds = ids.filter(function (i) { return state.byId[i].open_tabs; });
  var b1 = el('button', 'go', 'PC 에 그룹으로 열기'); b1.type = 'button';
  b1.onclick = function () { act('open', ids, title); };
  var b2 = el('button', '', '잠든 채로 열기'); b2.type = 'button';
  b2.onclick = function () { act('open', ids, title, true); };
  head.append(b1, b2);
  if (openIds.length) {
    var b3 = el('button', '', '모두 재우기'); b3.type = 'button';
    b3.onclick = function () { act('sleep', openIds); };
    var b4 = el('button', 'danger', '모두 닫기'); b4.type = 'button';
    b4.onclick = function () { confirmThen('close:' + title, b4, '한 번 더 누르면 ' + openIds.length + ' 개 닫음', function () { act('close', openIds); }); };
    head.append(b3, b4);
  }
}

function itemRow(it) {
  var li = el('li');
  var cb = el('input'); cb.type = 'checkbox'; cb.checked = state.sel.has(it.id); cb.setAttribute('aria-label', '선택');
  cb.onchange = function () { if (cb.checked) state.sel.add(it.id); else state.sel.delete(it.id); selBar(); };
  var mid = el('div', 't');
  var a = el('a', '', it.title || it.url);
  if (/^https?:\/\//i.test(it.url)) { a.href = it.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; }
  mid.append(a, el('div', 'line', it.line));
  var badges = el('div', 'badges');
  if (it.open_tabs) {
    if (it.awake_tabs) badges.append(el('span', 'b awake', 'PC 깨어 있음 ' + it.awake_tabs));
    if (it.open_tabs - it.awake_tabs) badges.append(el('span', 'b asleep', 'PC 잠듦 ' + (it.open_tabs - it.awake_tabs)));
    if (it.open_tabs > 1) badges.append(el('span', 'b dup', '중복 ' + it.open_tabs + ' 탭'));
  }
  badges.append(el('span', 'line', '마지막으로 본 때 ' + ago(it.last_seen)));
  mid.append(badges);
  var acts = el('div', 'acts');
  var o = el('button', 'go', 'PC 열기'); o.type = 'button'; o.onclick = function () { act('open', [it.id]); };
  acts.append(o);
  if (it.awake_tabs) { var s = el('button', '', '재우기'); s.type = 'button'; s.onclick = function () { act('sleep', [it.id]); }; acts.append(s); }
  if (it.open_tabs) { var c = el('button', 'danger', '닫기'); c.type = 'button'; c.onclick = function () { act('close', [it.id]); }; acts.append(c); }
  if (it.open_tabs > 1) { var d = el('button', '', '하나만 남기기'); d.type = 'button'; d.onclick = function () { act('dedupe', [it.id]); }; acts.append(d); }
  li.append(cb, mid, acts);
  return li;
}

function section(key, title, items) {
  var sec = el('section', 'grp');
  var head = el('div', 'ghead');
  var h = el('h2', '', title); h.append(el('span', 'count', items.length + ' 개'));
  head.append(h);
  groupButtons(head, items.map(function (i) { return i.id; }), title);
  sec.append(head);
  var ul = el('ul');
  var n = state.shown[key] || PAGE;
  items.slice(0, n).forEach(function (it) { ul.append(itemRow(it)); });
  sec.append(ul);
  if (items.length > n) {
    var m = el('button', '', '더 보기 (' + (items.length - n) + ' 개 남음)'); m.type = 'button';
    m.onclick = function () { state.shown[key] = n + PAGE; render(); };
    var w = el('div', 'more'); w.append(m); sec.append(w);
  }
  return sec;
}

function render() {
  var v = state.view; if (!v) return;
  var list = $('list'); list.textContent = '';
  var items = v.items.filter(matches);
  if (state.mode === 'cat') {
    var groups = {};
    items.forEach(function (it) { (groups[it.category] = groups[it.category] || []).push(it); });
    Object.keys(groups).sort(function (a, b) {
      var ia = ORDER.indexOf(a), ib = ORDER.indexOf(b);
      return (ia < 0 ? 50 : ia) - (ib < 0 ? 50 : ib) || groups[b].length - groups[a].length;
    }).forEach(function (k) { list.append(section('c:' + k, LABEL[k] || k, groups[k])); });
  } else {
    Object.keys(v.days).forEach(function (d) {
      var its = v.days[d].map(function (i) { return state.byId[i]; }).filter(function (it) { return it && matches(it); });
      if (its.length) list.append(section('d:' + d, d, its));
    });
  }
  if (!list.children.length) list.append(el('p', '', v.items.length ? '찾는 것이 없습니다.' : '아직 보관된 탭이 없습니다. PC 의 Chrome 에 mai-tabs 확장이 켜져 있는지 보세요.'));
  var logs = $('logs'); logs.textContent = '';
  (v.commands || []).slice(0, 12).forEach(function (c) {
    var name = { open: '열기', sleep: '재우기', close: '닫기', dedupe: '중복 정리' }[c.action] || c.action;
    var st = { pending: 'PC 처리 기다림', delivered: 'PC 가 처리 중', done: '끝남', failed: '일부 실패', expired: '2 분 안에 PC 가 안 받아 취소됨', unknown: 'PC 가 받았지만 답이 없음' }[c.state] || c.state;
    var t = name + ' · 항목 ' + c.items.length + ' · ' + st + ' · ' + ago(c.created);
    if (c.result && typeof c.result === 'object') t += ' · 성공 ' + c.result.done + ', 실패 ' + c.result.failed + (c.result.note ? ' (' + c.result.note + ')' : '');
    var li = el('li', '', t);
    if (c.after && c.after.lost) {
      li.append(el('div', 'line', '메모리 뒤 값을 재지 못함 (그사이 서버가 다시 시작됨)'));
    } else if (c.after && c.after.change) {
      var ch = c.after.change;
      var g = (ch.gpus || []).map(function (x) { return 'GPU' + x.index + ' ' + signed(x.mib); }).join(' · ');
      li.append(el('div', 'line', '실측 (' + ch.seconds + ' 초 사이, 그동안 다른 프로그램이 바꾼 양도 섞임): Chrome 메모리 ' + signed(ch.browser_mib) + (g ? ' · ' + g : '')));
    } else if (c.before && (c.state === 'done' || c.state === 'failed')) {
      li.append(el('div', 'line', '메모리 다시 재는 중 (20 초 뒤)'));
    }
    logs.append(li);
  });
  var live = v.live || {};
  var fresh = v.live_at && Date.now() - v.live_at < 90000;
  $('pc').textContent = v.live_at ? (fresh ? 'PC Chrome 연결됨' : 'PC Chrome 소식 없음') + ' · ' + ago(v.live_at) + ' · 열린 탭 ' + live.tabs + ' (깨어 있음 ' + live.awake + ')' : 'PC Chrome 에서 아직 소식 없음';
  $('pc').style.color = fresh ? 'var(--ok)' : 'var(--warn)';
  var m = v.memory || {};
  $('mem').textContent = 'Chrome 메모리 ' + mib(m.browser_mib) + (m.gpus || []).map(function (g) { return ' · GPU' + g.index + (g.display ? '(화면)' : '') + ' ' + mib(g.used_mib) + ' / ' + mib(g.total_mib); }).join('');
  var dd = $('dedupe'); dd.hidden = !live.duplicates; dd.textContent = 'PC 중복 탭 정리 (' + (live.duplicates || 0) + ')';
  selBar();
}

function selBar() {
  var n = state.sel.size;
  $('sel').classList.toggle('show', n > 0);
  $('selcount').textContent = '선택 ' + n + ' 개';
}

$('sel').addEventListener('click', function (e) {
  var a = e.target.getAttribute && e.target.getAttribute('data-act'); if (!a) return;
  var ids = Array.from(state.sel);
  var stamp = new Date().toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  if (a === 'clear') { state.sel.clear(); render(); return; }
  if (a === 'open-group') act('open', ids, '선택 ' + stamp);
  if (a === 'open-asleep') act('open', ids, '선택 ' + stamp, true);
  if (a === 'sleep') act('sleep', ids);
  if (a === 'close') confirmThen('close:sel', e.target, '한 번 더 누르면 닫음', function () { act('close', ids); });
});
$('by-cat').onclick = function () { state.mode = 'cat'; $('by-cat').classList.add('on'); $('by-day').classList.remove('on'); render(); };
$('by-day').onclick = function () { state.mode = 'day'; $('by-day').classList.add('on'); $('by-cat').classList.remove('on'); render(); };
$('q').oninput = function () { state.q = this.value.trim(); render(); };
$('openonly').onchange = function () { state.openOnly = this.checked; render(); };
$('dedupe').onclick = function () { var b = this; confirmThen('dedupe', b, '한 번 더 누르면 중복 탭 닫음 (가장 최근 것 하나는 남김)', function () { act('dedupe', []); }); };

async function load() {
  try {
    var v = await api('/api/view');
    state.view = v; state.byId = {};
    v.items.forEach(function (it) { state.byId[it.id] = it; });
    state.sel.forEach(function (i) { if (!state.byId[i]) state.sel.delete(i); });
    if ($('note').className === 'bad') note('');
    if (!state.armed) render();
  } catch (e) { note('보관함 서버에 닿지 못했습니다: ' + e.message, 'bad'); }
}
load();
setInterval(function () { if (!document.hidden) load(); }, 10000);
document.addEventListener('visibilitychange', function () { if (!document.hidden) load(); });
