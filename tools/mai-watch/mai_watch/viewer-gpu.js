/* "GPU 작업" tab (owner 11/03). Reads gpu_jobs.json, which the server builds by calling the GPU job board's own functions, so this page
 * shows the same values as `gpu_jobs.py board`. Read-only: nothing here starts, stops or queues work. The tab is shown only when the
 * server was started with --gpu-jobs; it polls once a second and only while the tab is open. */
(function (root) {
  'use strict';
  var doc = root.document;
  if (!doc || !doc.getElementById('gpu-section')) return;
  function $(id) { return doc.getElementById(id); }
  function el(tag, text, cls) { var e = doc.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  var STATE_CLASS = { '실행': 'ok', '대기': 'warn', '실패': 'bad', '보류': 'off', '끝': 'off' };
  var tabs = doc.querySelectorAll('.tabs [data-tab]');
  var current = 'live', loop = null, received = null;

  function clockText(epoch) { var d = new Date(epoch * 1000); return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2) + ':' + ('0' + d.getSeconds()).slice(-2); }

  function gpuCard(g) {
    var card = el('article', undefined, 'job-gpu');
    card.appendChild(el('h3', g.title));
    g.lines.forEach(function (line, i) {
      if (typeof line.bar === 'number') {
        var row = el('div', undefined, 'job-bar');
        var m = el('span', undefined, 'meter'), f = el('span', undefined, 'meter-fill');
        f.style.width = Math.max(0, Math.min(100, line.bar * 100)).toFixed(1) + '%';
        m.appendChild(f); row.appendChild(m); row.appendChild(el('span', line.text, 'strong'));
        card.appendChild(row);
      } else {
        card.appendChild(el('div', line.text, i === 0 ? 'job-now' : 'job-line'));
      }
    });
    return card;
  }

  function draw(d) {
    var box = $('gpu-board');
    clear(box);
    if (d.error) {
      box.appendChild(el('p', 'GPU 관리판을 못 읽음: ' + d.error, 'pill bad'));
      if (d.path) box.appendChild(el('p', d.path, 'quiet mono'));
      return;
    }
    var gpus = el('section', undefined, 'job-gpus');
    if (!d.gpu_read_ok) gpus.appendChild(el('p', 'nvidia-smi 읽기 실패 · GPU 상태 미확인', 'pill bad'));
    d.gpus.forEach(function (g) { gpus.appendChild(gpuCard(g)); });
    box.appendChild(gpus);

    var list = el('section', undefined, 'live-block');
    list.appendChild(el('h3', '작업 목록'));
    if (!d.entries.length) list.appendChild(el('p', '예정 없음', 'quiet'));
    else {
      var t = el('table', undefined, 'compact job-table'), head = el('tr');
      ['#', '상태', 'GPU', '우선', '시작', '끝', '띄움', '내용'].forEach(function (h, i) { head.appendChild(el('th', h, i === 7 ? 'job-title' : undefined)); });
      t.appendChild(head);
      d.entries.forEach(function (e) {
        var tr = el('tr');
        tr.appendChild(el('td', String(e.n), 'quiet'));
        var st = el('td'); st.appendChild(el('span', e.state, 'pill ' + (STATE_CLASS[e.state] || ''))); tr.appendChild(st);
        [e.gpu, e.priority, e.start, e.end, e.launcher].forEach(function (v) { tr.appendChild(el('td', v)); });
        tr.appendChild(el('td', e.title, 'job-title'));
        t.appendChild(tr);
        // on a narrow screen the title moves to its own line under the job, like "doing" in AI sessions (owner 11/03)
        var under = el('tr', undefined, 'job-title-row'), td = el('td', e.title);
        td.colSpan = 7; under.appendChild(el('td')); under.appendChild(td); t.appendChild(under);
      });
      var wrap = el('div', undefined, 'scroll'); wrap.appendChild(t); list.appendChild(wrap);
    }
    box.appendChild(list);

    var warn = el('section', undefined, 'live-block');
    warn.appendChild(el('h3', '경고'));
    if (!d.warnings.length) warn.appendChild(el('p', '경고 없음', 'quiet'));
    d.warnings.forEach(function (w) { warn.appendChild(el('div', w, 'job-warn')); });
    box.appendChild(warn);

    var notes = el('section', undefined, 'live-block');
    notes.appendChild(el('h3', '근거'));
    d.notes.forEach(function (n) {
      var row = el('div', undefined, 'job-note');
      row.appendChild(el('span', String(n.n), 'quiet')); row.appendChild(el('span', n.text));
      notes.appendChild(row);
    });
    notes.appendChild(el('p', '감시: ' + (d.guards.length ? d.guards.join(' · ') : '없음'), 'quiet'));
    if (d.parked.length) notes.appendChild(el('p', 'GPU 안 잡은 실행기: ' + d.parked.join(' · '), 'quiet'));
    notes.appendChild(el('p', '읽기 전용 · 프로세스를 띄우거나 멈추지 않음 · 끝 시각은 추정 · GPU 는 1 초, 대기열 · 명령줄 · 파일은 10 초마다 다시 읽음', 'quiet'));
    box.appendChild(notes);

    $('gpu-freshness').textContent = '측정 ' + clockText(d.now) + (d.slow_read_at ? ' · 대기열 · 파일 ' + clockText(d.slow_read_at) : '');
  }

  function show(name) {
    current = name === 'gpu' && !$('tab-gpu').hidden ? 'gpu' : 'live';
    tabs.forEach(function (b) { b.setAttribute('aria-selected', String(b.getAttribute('data-tab') === current)); });
    doc.body.setAttribute('data-tab', current);
    try { root.localStorage.setItem('mai-watch-tab', current); } catch (_) {}
    if (current === 'gpu') { if (loop) loop.start(); } else if (loop) loop.stop();
  }

  loop = root.MaiWatchConnection.createLoop({
    task: function (signal) { return root.MaiWatchConnection.read('gpu_jobs.json', 'json', signal); },
    interval: function () { return 1000; },
    onData: function (d) {
      if (!d || d.schema !== 'mai-watch-gpu-jobs-v1') throw new Error('gpu_jobs.json has an unknown schema');
      received = Date.now(); $('gpu-status').className = 'pill ok'; $('gpu-status').textContent = '1 초마다';
      draw(d);
    },
    onError: function (e) {
      $('gpu-status').className = 'pill bad';
      $('gpu-status').textContent = '끊김 · 다시 시도 중' + (received ? ' · 마지막 ' + Math.round((Date.now() - received) / 1000) + ' 초 전' : '');
    }
  });
  root.MaiWatchConnection.bind(loop);

  tabs.forEach(function (b) { b.addEventListener('click', function () { show(b.getAttribute('data-tab')); }); });
  // the tab exists only when the server has a board; a 404 keeps the page exactly as it was
  root.MaiWatchConnection.read('gpu_jobs.json', 'json').then(function () {
    $('tab-gpu').hidden = false; $('tabs').hidden = false;
    var want = /gpu/.test(root.location.hash) ? 'gpu' : null;
    if (!want) { try { want = root.localStorage.getItem('mai-watch-tab'); } catch (_) { want = null; } }
    show(want || 'live');
  }, function () { show('live'); });
})(typeof window !== 'undefined' ? window : globalThis);
