/* "받은편지함" tab (owner 11/10). Reads inbox.json: Orca orchestration messages between sessions, newest first. The first thing on each
 * message is who wrote to whom; then the subject; the body opens on demand past its first lines. Filters (person, questions only,
 * words) stay as chosen across refreshes. Read-only: nothing here sends or marks a message read. */
(function (root) {
  'use strict';
  var doc = root.document;
  if (!doc || !doc.getElementById('inbox-section')) return;
  function $(id) { return doc.getElementById(id); }
  function el(tag, text, cls) { var e = doc.createElement(tag); if (text !== undefined && text !== null) e.textContent = text; if (cls) e.className = cls; return e; }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  var TYPE = { status: ['보고', 'off'], question: ['질문', 'warn'], decision_gate: ['결정 요청', 'warn'], worker_done: ['끝', 'ok'],
               dispatch: ['의뢰', 'ok'], escalation: ['막힘', 'bad'], heartbeat: ['살아 있음', 'off'] };
  var SHOWN_LINES = 3;
  var loop = null, received = null, last = null;
  var pick = { who: '', kind: '', words: '' };

  function two(n) { return ('0' + n).slice(-2); }
  function clockText(epoch) { var d = new Date(epoch * 1000); return two(d.getHours()) + ':' + two(d.getMinutes()); }
  function dayText(epoch) { var d = new Date(epoch * 1000); return (d.getMonth() + 1) + '월 ' + d.getDate() + '일'; }
  function blocked(m) { return /막힘|막음 [1-9]|FAIL|REFUSED/.test(m.subject); }

  function tools(people) {
    var bar = el('div', undefined, 'inbox-tools');
    var who = el('select'); who.setAttribute('aria-label', '보낸 이 · 받는 이');
    who.appendChild(new root.Option('모든 세션', ''));
    people.forEach(function (p) { who.appendChild(new root.Option(p, p)); });
    who.value = people.indexOf(pick.who) >= 0 ? pick.who : '';
    who.addEventListener('change', function () { pick.who = who.value; if (last) draw(last); });
    var kind = el('select'); kind.setAttribute('aria-label', '종류');
    [['모든 글', ''], ['질문 · 결정 요청만', 'ask'], ['막힘만', 'block']].forEach(function (k) { kind.appendChild(new root.Option(k[0], k[1])); });
    kind.value = pick.kind;
    kind.addEventListener('change', function () { pick.kind = kind.value; if (last) draw(last); });
    var words = el('input'); words.type = 'search'; words.placeholder = '낱말로 찾기'; words.value = pick.words;
    words.setAttribute('aria-label', '낱말로 찾기');
    words.addEventListener('input', function () { pick.words = words.value; if (last) draw(last, true); });
    bar.appendChild(who); bar.appendChild(kind); bar.appendChild(words);
    return bar;
  }

  function keep(m) {
    if (pick.who && m.from !== pick.who && m.to !== pick.who) return false;
    if (pick.kind === 'ask' && m.type !== 'question' && m.type !== 'decision_gate') return false;
    if (pick.kind === 'block' && !blocked(m)) return false;
    if (pick.words) {
      var w = pick.words.toLowerCase();
      if ((m.subject + '\n' + m.body + '\n' + m.from + '\n' + m.to).toLowerCase().indexOf(w) < 0) return false;
    }
    return true;
  }

  function message(m) {
    var t = TYPE[m.type] || [m.type || '글', 'off'];
    var box = el('article', undefined, 'inbox-msg' + (m.type === 'question' || m.type === 'decision_gate' ? ' question' : '') + (blocked(m) ? ' blocked' : ''));
    var route = el('div', undefined, 'inbox-route');
    route.appendChild(el('span', m.from, 'who'));
    route.appendChild(el('span', '→', 'arrow'));
    route.appendChild(el('span', m.to, 'who'));
    route.appendChild(el('span', t[0], 'pill ' + t[1]));
    route.appendChild(el('span', (m.at ? clockText(m.at) : '--') + ' · #' + m.seq, 'quiet mono'));
    box.appendChild(route);
    box.appendChild(el('div', m.subject, 'inbox-subject'));
    var lines = m.body ? m.body.split('\n') : [];
    if (lines.length) {
      box.appendChild(el('div', lines.slice(0, SHOWN_LINES).join('\n'), 'inbox-body'));
      if (lines.length > SHOWN_LINES || m.cut) {
        var more = el('details'); more.appendChild(el('summary', '나머지 ' + Math.max(0, lines.length - SHOWN_LINES) + ' 줄' + (m.cut ? ' (길어서 잘림)' : '')));
        more.appendChild(el('div', lines.slice(SHOWN_LINES).join('\n'), 'inbox-body'));
        box.appendChild(more);
      }
    }
    return box;
  }

  function draw(d, keepFocus) {
    last = d;
    var box = $('inbox-board');
    var focused = keepFocus && doc.activeElement && doc.activeElement.tagName === 'INPUT';
    if (focused) {
      while (box.childNodes.length > 1) box.removeChild(box.lastChild);
    } else {
      clear(box);
    }
    if (d.error) {
      box.appendChild(el('p', '받은편지함을 못 읽음 (Orca 가 꺼졌거나 다시 켜지는 중): ' + d.error, 'pill bad'));
      return;
    }
    var msgs = d.messages;
    var dayStart = new Date(d.now * 1000); dayStart.setHours(0, 0, 0, 0); dayStart = dayStart.getTime() / 1000;
    var today = msgs.filter(function (m) { return m.at >= dayStart; });
    var asks = today.filter(function (m) { return m.type === 'question' || m.type === 'decision_gate'; });
    var hour = msgs.filter(function (m) { return m.at >= d.now - 3600; });
    if (!focused) {
      var band = el('section', undefined, 'work-band' + (asks.length ? ' warn' : ''));
      [['오늘', today.length, ''], ['질문 · 결정 요청', asks.length, 'warn'], ['최근 1 시간', hour.length, '']].forEach(function (x) {
        var k = el('div', undefined, 'work-count' + (x[1] && x[2] ? ' ' + x[2] : ''));
        k.appendChild(el('span', String(x[1]), 'num-big')); k.appendChild(el('span', x[0], 'num-label')); band.appendChild(k);
      });
      var head = el('div'); head.appendChild(band); head.appendChild(tools(d.people || []));
      box.appendChild(head);
    }
    var shown = msgs.filter(keep);
    var list = el('section', undefined, 'live-block');
    if (!shown.length) list.appendChild(el('p', msgs.length ? '고른 조건에 맞는 글 없음' : '아직 글 없음', 'quiet'));
    var day = null;
    shown.forEach(function (m) {
      var dt = m.at ? dayText(m.at) : '날짜 모름';
      if (dt !== day) { day = dt; list.appendChild(el('h3', dt, 'inbox-day')); }
      list.appendChild(message(m));
    });
    list.appendChild(el('p', '읽기 전용 · 보내기 · 읽음 표시 없음 · 최근 ' + msgs.length + ' 통' + (d.run ? ' · ' + d.run : '') + ' · 이름은 targets.txt · Orca 탭 제목에서', 'quiet work-foot'));
    box.appendChild(list);
    $('inbox-freshness').textContent = '확인 ' + clockText(d.now);
  }

  loop = root.MaiWatchConnection.createLoop({
    task: function (signal) { return root.MaiWatchConnection.read('inbox.json', 'json', signal); },
    interval: function () { return 5000; },
    onData: function (d) {
      if (!d || d.schema !== 'mai-watch-inbox-v1') throw new Error('inbox.json has an unknown schema');
      received = Date.now(); $('inbox-status').className = 'pill ok'; $('inbox-status').textContent = '5 초마다';
      var typing = doc.activeElement && doc.activeElement.closest && doc.activeElement.closest('#inbox-board');
      if (typing && doc.activeElement.tagName === 'SELECT') { last = d; return; }   // do not rebuild a menu that is open
      draw(d, true);
    },
    onError: function () {
      $('inbox-status').className = 'pill bad';
      $('inbox-status').textContent = '끊김 · 다시 시도 중' + (received ? ' · 마지막 ' + Math.round((Date.now() - received) / 1000) + ' 초 전' : '');
    }
  });
  root.MaiWatchConnection.bind(loop);
  root.MaiWatchConnection.read('inbox.json?probe=1', 'json').then(function () {
    root.MaiWatchTabs.add('inbox', { start: function () { loop.start(); }, stop: function () { loop.stop(); } });
  }, function () {});
})(typeof window !== 'undefined' ? window : globalThis);
