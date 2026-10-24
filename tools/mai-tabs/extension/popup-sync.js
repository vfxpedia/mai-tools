/* Popup, library part: shows when the worker last reached the library server and lets the owner send the tabs now. */
(function () {
  'use strict';
  var el = document.getElementById('libstate');

  function show(st) {
    if (!st) { el.textContent = '탭 보관함: 아직 보낸 적 없음 (서버가 켜져 있는지 확인)'; return; }
    var ago = Math.round((Date.now() - st.at) / 1000);
    el.textContent = st.ok
      ? '탭 보관함: ' + ago + ' 초 전에 보냄 · 탭 ' + st.counts.tabs + ' · 보관 ' + st.counts.stored + ' · 보관 안 함 ' + st.counts.not_stored
      : '탭 보관함: 보내지 못함 (' + st.error + ') · 서버 http://127.0.0.1:28766 확인';
  }

  chrome.storage.local.get('status').then(function (d) { show(d.status); });
  document.getElementById('syncnow').addEventListener('click', function () {
    el.textContent = '보내는 중...';
    chrome.runtime.sendMessage({ type: 'sync-now' }).then(function () {
      return chrome.storage.local.get('status');
    }).then(function (d) { show(d.status); });
  });
})();
