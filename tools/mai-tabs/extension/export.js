/* mai-tabs export core. Pure functions, no browser API, so the same file runs in the extension popup and under Node for tests.
 * sanitizeUrl must stay behaviorally identical to mai_tabs/sanitize.py, sha256Hex to Python hashlib, and consistencyProblems to
 * mai_tabs/render.py; tests/test_mai_tabs.py runs both sides on the same cases. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MaiTabs = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var HIERARCHICAL = { 'http:': 80, 'https:': 443, 'ftp:': 21, 'ws:': 80, 'wss:': 443 };
  var BROWSER_INTERNAL = ['chrome:', 'chrome-extension:', 'edge:', 'brave:', 'vivaldi:', 'opera:', 'moz-extension:'];
  var REDACTED = '_redacted_';

  function redactSegment(seg) {
    if (seg.length >= 32 && /^[A-Za-z0-9_-]+$/.test(seg) && /[0-9]/.test(seg) && /[A-Za-z]/.test(seg)) return REDACTED;
    return seg;
  }

  function cleanPath(path, redact) {
    if (!redact) return path;
    return path.split('/').map(redactSegment).join('/');
  }

  /* Removes userinfo, query and fragment. Never returns more than scheme, host, port (when not default) and path. */
  function sanitizeUrl(url, opts) {
    var redact = !(opts && opts.redactLongSegments === false);
    var u;
    try { u = new URL(String(url)); } catch (e) { return ''; }
    var scheme = u.protocol;
    if (Object.prototype.hasOwnProperty.call(HIERARCHICAL, scheme)) {
      var port = u.port && String(HIERARCHICAL[scheme]) !== u.port ? ':' + u.port : '';
      return scheme + '//' + u.hostname + port + cleanPath(u.pathname || '/', redact);
    }
    if (scheme === 'file:') {
      var parts = u.pathname.split('/');
      return 'file:///.../' + parts[parts.length - 1];
    }
    if (BROWSER_INTERNAL.indexOf(scheme) >= 0) {
      return scheme + '//' + u.hostname + u.pathname;
    }
    if (scheme === 'about:') return 'about:' + u.pathname;
    return scheme;
  }

  /* SHA-256 of a string (UTF-8), synchronous, so the export can stay a plain function. Verified against Python hashlib in the tests. */
  var K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];

  function sha256Hex(str) {
    var bytes = new TextEncoder().encode(String(str));
    var bitLen = bytes.length * 8;
    var padded = new Uint8Array(((bytes.length + 9 + 63) >> 6) << 6);
    padded.set(bytes);
    padded[bytes.length] = 0x80;
    var view = new DataView(padded.buffer);
    view.setUint32(padded.length - 8, Math.floor(bitLen / 4294967296));
    view.setUint32(padded.length - 4, bitLen >>> 0);
    var h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var w = new Array(64);
    function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }
    for (var off = 0; off < padded.length; off += 64) {
      for (var i = 0; i < 16; i++) w[i] = view.getUint32(off + i * 4);
      for (i = 16; i < 64; i++) {
        var s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
        var s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
      var a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
      for (i = 0; i < 64; i++) {
        var S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        var ch = (e & f) ^ (~e & g);
        var t1 = (hh + S1 + ch + K[i] + w[i]) | 0;
        var S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) | 0;
        hh = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      h[0] = (h[0] + a) | 0; h[1] = (h[1] + b) | 0; h[2] = (h[2] + c) | 0; h[3] = (h[3] + d) | 0;
      h[4] = (h[4] + e) | 0; h[5] = (h[5] + f) | 0; h[6] = (h[6] + g) | 0; h[7] = (h[7] + hh) | 0;
    }
    return h.map(function (x) { return ('00000000' + (x >>> 0).toString(16)).slice(-8); }).join('');
  }

  /* The sanitized address is for display. Two tabs are the same page only when their full original addresses are equal, so the export keeps
   * a short one-way identity (first 16 hex characters of SHA-256 of the full original address) and never the address itself. */
  function urlId(rawUrl) { return sha256Hex(String(rawUrl)).slice(0, 16); }

  /* Rules the schema cannot express: counts match the content, and every group id refers to a listed group. */
  function consistencyProblems(exp) {
    var out = [];
    var n = exp.windows.reduce(function (s, w) { return s + w.tabs.length; }, 0);
    if (exp.counts.windows !== exp.windows.length) out.push('counts.windows is ' + exp.counts.windows + ' but there are ' + exp.windows.length + ' windows');
    if (exp.counts.tabs !== n) out.push('counts.tabs is ' + exp.counts.tabs + ' but there are ' + n + ' tabs');
    if (exp.counts.groups !== exp.groups.length) out.push('counts.groups is ' + exp.counts.groups + ' but there are ' + exp.groups.length + ' groups');
    var ids = exp.groups.map(function (g) { return g.id; });
    exp.windows.forEach(function (w) {
      w.tabs.forEach(function (t) {
        if (t.group_id !== null && ids.indexOf(t.group_id) < 0) out.push('tab ' + t.id + ' refers to unknown group ' + t.group_id);
      });
    });
    return out;
  }

  /* input: { browser: {name, version}, nowIso, windows: [{id, focused, tabs: [...]}], groups: [...], groupsError: string|null,
   *          groupsSupported: bool } as the browser reports them. Output follows schema/export.v1.schema.json.
   * A failed group query is not an empty list: the export is marked incomplete and tabs keep their group ids with placeholder groups,
   * so a partial collection can never be mistaken for a full one. */
  function buildExport(input, opts) {
    var notes = [];
    var windows = (input.windows || []).map(function (w) {
      return {
        id: w.id,
        focused: !!w.focused,
        tabs: (w.tabs || []).map(function (t) {
          var accessed = typeof t.lastAccessed === 'number' ? Math.round(t.lastAccessed) : null;
          var gid = typeof t.groupId === 'number' && t.groupId >= 0 ? t.groupId : null;
          var raw = t.url || t.pendingUrl || '';
          return {
            id: t.id,
            index: t.index,
            title: String(t.title || ''),
            url: sanitizeUrl(raw, opts),
            url_id: raw ? urlId(raw) : null,
            pinned: !!t.pinned,
            audible: !!t.audible,
            discarded: !!t.discarded,
            group_id: gid,
            last_accessed_ms: accessed
          };
        })
      };
    });
    var groups = (input.groups || []).map(function (g) {
      return { id: g.id, title: String(g.title || ''), color: String(g.color || ''), collapsed: !!g.collapsed };
    });
    if (input.groupsError) {
      notes.push('tab group query failed: ' + input.groupsError + '; group titles are missing');
      windows.forEach(function (w) {
        w.tabs.forEach(function (t) {
          if (t.group_id !== null && !groups.some(function (g) { return g.id === t.group_id; })) groups.push({ id: t.group_id, title: '', color: '', collapsed: false });
        });
      });
    } else if (input.groupsSupported === false) {
      notes.push('this browser has no tab groups API; tabs are listed without groups');
    }
    var count = windows.reduce(function (n, w) { return n + w.tabs.length; }, 0);
    var exp = {
      schema: 'mai-tabs-export-v1',
      exported_at: input.nowIso,
      browser: { name: String((input.browser || {}).name || 'unknown'), version: String((input.browser || {}).version || '') },
      urls_sanitized: true,
      collection: { complete: !input.groupsError, scope: 'windows of the current browser profile that the extension API returned; incognito only if allowed for the extension', notes: notes },
      counts: { windows: windows.length, tabs: count, groups: groups.length },
      windows: windows,
      groups: groups
    };
    return exp;
  }

  return { sanitizeUrl: sanitizeUrl, sha256Hex: sha256Hex, urlId: urlId, consistencyProblems: consistencyProblems, buildExport: buildExport };
});
