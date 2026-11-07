/* "작업" tab (owner 11/06 · W42). Reads work.json, which the server builds with mai-work's own check, so this page shows the same
 * findings as `python -m mai_work check`. Read-only. Order follows what needs a hand first: the count band, then findings, then open
 * work by stage and deadline, then waits and recent changes; finished work is folded. Every item is a two-line card, so a phone at
 * 390 px reads it without a sideways scroll. */
(function (root) {
  'use strict';
  var doc = root.document;
  if (!doc || !doc.getElementById('work-section')) return;
  function $(id) { return doc.getElementById(id); }
  function el(tag, text, cls) { var e = doc.createElement(tag); if (text !== undefined && text !== null) e.textContent = text; if (cls) e.className = cls; return e; }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  var RULE = { C1: '마감 지남', C2: '시작 늦음', C3: '순서 어김', C4: '우선순위 역전', C5: '기록 결함', C6: '확정 재안건',
               C7: '끝 처리 안 함', C8: '멈춘 일', C9: '팀장 결정 대기', C10: '결정 시각 없음' };
  var STATUS = { open: ['열림', 'warn'], doing: ['진행', 'ok'], done: ['끝', 'off'], hold: ['보류', 'off'], cancelled: ['취소', 'off'], replaced: ['대체', 'off'] };
  var PRI = { P0: 0, P1: 1, P2: 2, P3: 3 };
  var loop = null, received = null;

  function two(n) { return ('0' + n).slice(-2); }
  function clockText(epoch) { var d = new Date(epoch * 1000); return two(d.getHours()) + ':' + two(d.getMinutes()) + ':' + two(d.getSeconds()); }
  function span(min) {
    var a = Math.abs(min);
    return a < 60 ? a + ' 분' : a < 48 * 60 ? Math.round(a / 6) / 10 + ' 시간' : Math.round(a / 144) / 10 + ' 일';
  }
  function dueText(it) {
    var v = it.end_plan || '-';
    if (v.indexOf('at:') === 0) {
      var when = Number(v.slice(11, 13)) + '일 ' + v.slice(14, 19);      // at:YYYY-MM-DDTHH:MM
      if (it.due === 'passed') return when + ' · ' + span(it.due_by) + ' 지남';
      return when + ' · ' + span(-it.due_by) + ' 남음';
    }
    if (v.indexOf('iter:') === 0) return v.slice(5) + ' 회' + (it.due === 'iter-unknown' ? ' · 지금 회차 모름' : '');
    return '마감 없음';
  }
  function dueKey(it) { return it.due === 'none' || it.due_by === null ? 1e9 : -it.due_by; }

  function card(it, extra) {
    var c = el('article', undefined, 'work-item' + (it.rules.length ? ' flagged' : ''));
    var top = el('div', undefined, 'work-meta');
    var s = STATUS[it.status] || [it.status, ''];
    top.appendChild(el('span', s[0], 'pill ' + s[1]));
    top.appendChild(el('strong', it.id));
    top.appendChild(el('span', it.priority, 'work-pri p' + (PRI[it.priority] === undefined ? 9 : PRI[it.priority])));
    top.appendChild(el('span', it.owner, 'quiet'));
    top.appendChild(el('span', dueText(it), it.due === 'passed' ? 'work-due bad-text' : it.due === 'soon' ? 'work-due warn-text' : 'work-due'));
    if (extra) top.appendChild(el('span', extra, 'quiet'));
    c.appendChild(top);
    c.appendChild(el('div', it.title, 'work-title'));
    return c;
  }

  function block(title, note) {
    var b = el('section', undefined, 'live-block work-block');
    var h = el('h3', title); if (note) h.appendChild(el('span', ' ' + note, 'quiet')); b.appendChild(h);
    return b;
  }

  function draw(d) {
    var box = $('work-board');
    clear(box);
    if (d.error) {
      box.appendChild(el('p', '작업 목록을 못 읽음: ' + d.error, 'pill bad'));
      if (d.path) box.appendChild(el('p', d.path, 'quiet mono'));
      return;
    }
    var c = d.counts, items = d.items;
    var band = el('section', undefined, 'work-band' + (c.FAIL ? ' bad' : c.WARN ? ' warn' : ''));
    [['막힘', c.FAIL, 'bad'], ['팀장 결정 대기', c.owner_wait, 'warn'], ['주의', c.WARN, 'warn'], ['열림', c.open + c.doing, ''], ['끝', c.done, '']]
      .forEach(function (x) { var k = el('div', undefined, 'work-count' + (x[1] && x[2] ? ' ' + x[2] : '')); k.appendChild(el('span', String(x[1]), 'num-big')); k.appendChild(el('span', x[0], 'num-label')); band.appendChild(k); });
    box.appendChild(band);

    var byId = {}; items.forEach(function (it) { byId[it.id] = it; });
    var act = block('지금 손이 가야 할 것', d.findings.length ? d.findings.length + ' 건' : '');
    if (!d.findings.length) act.appendChild(el('p', '마감 지남 · 순서 어김 · 기록 결함 없음', 'quiet'));
    d.findings.forEach(function (f) {
      var row = el('div', undefined, 'work-finding ' + f.level.toLowerCase());
      var top = el('div', undefined, 'work-meta');
      top.appendChild(el('span', RULE[f.rule] || f.rule, 'pill ' + (f.level === 'FAIL' ? 'bad' : f.level === 'WARN' ? 'warn' : 'off')));
      top.appendChild(el('strong', f.id)); top.appendChild(el('span', f.priority, 'quiet')); top.appendChild(el('span', f.owner, 'quiet'));
      row.appendChild(top);
      row.appendChild(el('div', f.msg, 'work-title'));
      if (byId[f.id]) row.appendChild(el('div', byId[f.id].title, 'work-sub quiet'));
      act.appendChild(row);
    });
    box.appendChild(act);

    var open = items.filter(function (it) { return it.status === 'open' || it.status === 'doing'; });
    open.sort(function (a, b) { return (a.status === 'doing' ? -1 : 0) - (b.status === 'doing' ? -1 : 0) || dueKey(a) - dueKey(b) || (PRI[a.priority] || 9) - (PRI[b.priority] || 9); });
    var stages = {}, order = [];
    open.forEach(function (it) { var s = it.stage || '단계 미정'; if (!stages[s]) { stages[s] = []; order.push(s); } stages[s].push(it); });
    var work = block('열린 일 · 마감 순', open.length + ' 건');
    order.forEach(function (s) {
      if (order.length > 1 || s !== '단계 미정') work.appendChild(el('h4', s, 'work-stage'));
      stages[s].forEach(function (it) {
        var wait = it.after.filter(function (a) { return !byId[a] || byId[a].status !== 'done'; });
        work.appendChild(card(it, wait.length ? '선행 ' + wait.join(', ') + ' 기다림' : ''));
      });
    });
    if (order.length === 1 && order[0] === '단계 미정') work.appendChild(el('p', '단계 칸이 비어 있어 단계별로 나누지 않았다 (목록 주인이 채우면 나뉨)', 'quiet'));
    box.appendChild(work);

    var waits = items.filter(function (it) { return it.status === 'hold' || /^(팀장|owner)/.test(it.wait_for || ''); });
    if (waits.length) {
      var w = block('보류 · 팀장 결정 대기', waits.length + ' 건');
      waits.forEach(function (it) { w.appendChild(card(it, it.wait_for ? '기다림: ' + it.wait_for : '')); });
      box.appendChild(w);
    }

    var ch = block('최근 바뀐 기록');
    if (!d.events.length) ch.appendChild(el('p', d.format === 'legacy' ? '변경 기록 파일 없음 · 아직 옛 WORKLIST.tsv 를 읽는 중' : '기록 없음', 'quiet'));
    d.events.slice().reverse().forEach(function (e) {
      var row = el('div', undefined, 'work-event');
      row.appendChild(el('span', (e.ts || '').slice(5, 16).replace('T', ' '), 'quiet mono'));
      row.appendChild(el('span', e.id + ' ' + e.event + (e.field ? ' ' + e.field + ' ' + (e.from || '') + ' → ' + (e.to || '') : '')));
      row.appendChild(el('span', '결정 ' + (e.decided_at || '-'), 'quiet'));
      ch.appendChild(row);
    });
    box.appendChild(ch);

    var closed = items.filter(function (it) { return ['done', 'cancelled', 'replaced'].indexOf(it.status) >= 0; });
    var fold = el('details', undefined, 'work-fold'); fold.appendChild(el('summary', '끝 · 취소 · 대체 ' + closed.length + ' 건'));
    closed.forEach(function (it) { fold.appendChild(card(it, it.replaced_by ? '→ ' + it.replaced_by : '')); });
    box.appendChild(fold);

    box.appendChild(el('p', '읽기 전용 · 목록을 고치거나 알림을 보내지 않음 · 규칙은 mai-work check 와 같음 · ' + (d.format === 'legacy' ? '옛 형식 WORKLIST.tsv' : 'WORK.tsv') + ' · ' + d.path, 'quiet work-foot'));
    $('work-freshness').textContent = '확인 ' + clockText(d.now) + ' · 목록 파일 ' + clockText(d.mtime);
  }

  loop = root.MaiWatchConnection.createLoop({
    task: function (signal) { return root.MaiWatchConnection.read('work.json', 'json', signal); },
    interval: function () { return 5000; },
    onData: function (d) {
      if (!d || d.schema !== 'mai-work-check-v1') throw new Error('work.json has an unknown schema');
      received = Date.now(); $('work-status').className = 'pill ok'; $('work-status').textContent = '5 초마다';
      draw(d);
    },
    onError: function () {
      $('work-status').className = 'pill bad';
      $('work-status').textContent = '끊김 · 다시 시도 중' + (received ? ' · 마지막 ' + Math.round((Date.now() - received) / 1000) + ' 초 전' : '');
    }
  });
  root.MaiWatchConnection.bind(loop);
  root.MaiWatchConnection.read('work.json?probe=1', 'json').then(function () {
    root.MaiWatchTabs.add('work', { start: function () { loop.start(); }, stop: function () { loop.stop(); } });
  }, function () {});
})(typeof window !== 'undefined' ? window : globalThis);
