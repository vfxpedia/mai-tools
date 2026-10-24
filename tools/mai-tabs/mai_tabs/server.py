"""Library server (DESIGN.md section 12.3). Two listeners, both on 127.0.0.1 only:

  page port (default 28770), the one Tailscale Serve may expose to the owner's other devices
    GET  /  /app.js       the page
    GET  /api/view        the library, what is open now, recent actions with memory before and after
    POST /api/command     {action: open|sleep|close|dedupe, items: [ids], group: title, asleep: bool}
  extension port (page port + 1), never exposed: only the mai-tabs extension in this computer's Chrome talks to it
    POST /api/sync        the extension's tab report; the answer carries the actions waiting for that browser
    POST /api/ack         the extension's result for one action

Who may do what:
  - Host must name this server (127.0.0.1, localhost, or on the page port a *.ts.net name), which stops DNS rebinding
  - every POST must carry the header X-Mai-Tabs: 1 and a JSON body; a site open in the browser cannot add that header to a request to
    another origin without a preflight, and no preflight is answered, so a site cannot press the buttons for you
  - a request that came through Tailscale Serve (Host is *.ts.net) must carry Tailscale-User-Login equal to one of the owner's logins in
    <data>/config.json ("owner_logins"); tagged devices and other people on the tailnet get 403, and so does everyone while it is unset
  - the extension port refuses anything forwarded and anything whose Origin is not the extension; the first extension that reports is
    remembered in config.json ("extension_origin") and any other extension is refused from then on
"""
import http.server
import json
import os
import re
import threading
import time

from . import library, memory

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, 'app.html')
SCRIPT = os.path.join(HERE, 'app.js')
MAX_BODY = 4 * 2 ** 20
LOCAL_HOST = re.compile(r'^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$')
TS_HOST = re.compile(r'^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.ts\.net(:\d+)?$')
EXT_ORIGIN = re.compile(r'^chrome-extension://[a-p]{32}$')
FORWARD_HEADERS = ('Tailscale-User-Login', 'Tailscale-User-Name', 'X-Forwarded-For', 'X-Forwarded-Host', 'Forwarded')
SETTLE_S = 20


def _reject_constant(name):
    raise ValueError('%s is not allowed' % name)


class Config:
    """<data>/config.json, written by the owner (owner_logins) and once by the server (extension_origin)."""

    def __init__(self, home):
        self.path = os.path.join(home, 'config.json')
        self.lock = threading.Lock()

    def read(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def owner_logins(self):
        v = self.read().get('owner_logins')
        return {x for x in v if isinstance(x, str) and x} if isinstance(v, list) else set()

    def extension_ok(self, origin):
        """True for the remembered extension; the first extension origin seen is remembered."""
        if not EXT_ORIGIN.match(origin or ''):
            return False
        with self.lock:
            d = self.read()
            if not d.get('extension_origin'):
                d['extension_origin'] = origin
                tmp = self.path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(d, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
                return True
            return d['extension_origin'] == origin


class App:
    def __init__(self, lib, measure=memory.measure, settle_s=SETTLE_S, timer=threading.Timer, config=None):
        self.lib, self.measure, self.settle_s, self.timer = lib, measure, settle_s, timer
        self.config = config or Config(lib.home)
        self._mem = None
        self._mem_lock = threading.Lock()

    def memory_now(self, max_age_s=None):
        """The page gets the last background reading and never waits for one; an action's before-reading (max_age_s=0) is taken now."""
        if max_age_s == 0:
            m = self.measure()
            with self._mem_lock:
                self._mem = m
            return m
        with self._mem_lock:
            return self._mem

    def keep_measuring(self, every_s=15):
        def loop():
            while True:
                try:
                    self.memory_now(max_age_s=0)
                except Exception:
                    pass
                time.sleep(every_s)
        threading.Thread(target=loop, daemon=True, name='mai-tabs-memory').start()

    def command(self, body):
        action = body.get('action')
        items = body.get('items') if isinstance(body.get('items'), list) else []
        group = body.get('group') if isinstance(body.get('group'), str) else None
        before = self.memory_now(max_age_s=0) if action in ('sleep', 'close', 'dedupe') else None
        return self.lib.enqueue(action, items, group, before=before, asleep=body.get('asleep') is True)

    def ack(self, body):
        c = self.lib.ack(body.get('id'), body.get('ok'), body.get('done', 0), body.get('failed', 0), body.get('note') or '')
        if c is None:
            raise ValueError('no action waiting for an answer with that id')
        if c.get('before'):
            cid, before = c['id'], c['before']
            t = self.timer(self.settle_s, lambda: self.lib.record_after(cid, self._after(before)))
            t.daemon = True
            t.start()
        return {'ok': True}

    def _after(self, before):
        after = self.measure()
        return dict(after, change=memory.difference(before, after))


class Base(http.server.BaseHTTPRequestHandler):
    server_version = 'mai-tabs'
    app = None

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype='application/json'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype + ('; charset=utf-8' if ctype.startswith(('application/', 'text/')) else ''))
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        if ctype.startswith('text/html'):
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; "
                                                        "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        """The JSON object of a POST, or an (code, message) refusal."""
        if self.headers.get('X-Mai-Tabs') != '1' or not (self.headers.get('Content-Type') or '').startswith('application/json'):
            return None, (403, 'missing X-Mai-Tabs header or JSON body')
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            return None, (413, 'body too large')
        try:
            body = json.loads(self.rfile.read(n) or b'{}', parse_constant=_reject_constant)
        except ValueError as e:
            return None, (400, 'bad JSON: %s' % e)
        if not isinstance(body, dict):
            return None, (400, 'body must be an object')
        return body, None

    def _guard(self, fn):
        try:
            return fn()
        except ValueError as e:
            return self._send(400, {'error': str(e)})
        except Exception as e:                # anything else is a 500 with a reason, never a dropped connection
            return self._send(500, {'error': '%s: %s' % (type(e).__name__, e)})

    def do_OPTIONS(self):
        return self._send(405, {'error': 'no cross-origin requests'})


class PageHandler(Base):
    def _allowed(self):
        host = self.headers.get('Host') or ''
        if LOCAL_HOST.match(host):
            return None
        if TS_HOST.match(host):
            owners = self.app.config.owner_logins()
            if not owners:
                return 'set owner_logins in config.json to use this page from other devices'
            if self.headers.get('Tailscale-User-Login') not in owners:
                return 'this page is only for its owner'
            return None
        return 'unknown host'

    def do_GET(self):
        why = self._allowed()
        if why:
            return self._send(421 if why == 'unknown host' else 403, {'error': why})
        path = self.path.split('?', 1)[0]
        if path in ('/', '/index.html'):
            with open(PAGE, 'rb') as f:
                return self._send(200, f.read(), 'text/html')
        if path == '/app.js':
            with open(SCRIPT, 'rb') as f:
                return self._send(200, f.read(), 'application/javascript')
        if path == '/api/view':
            return self._guard(lambda: self._send(200, dict(self.app.lib.view(), memory=self.app.memory_now())))
        if path == '/healthz':
            return self._send(200, {'ok': True})
        return self._send(404, {'error': 'not found'})

    def do_POST(self):
        why = self._allowed()
        if why:
            return self._send(421 if why == 'unknown host' else 403, {'error': why})
        body, refusal = self._body()
        if refusal:
            return self._send(refusal[0], {'error': refusal[1]})
        if self.path.split('?', 1)[0] == '/api/command':
            return self._guard(lambda: self._send(200, self.app.command(body)))
        return self._send(404, {'error': 'not found'})


class ExtensionHandler(Base):
    def do_GET(self):
        if self.path.split('?', 1)[0] == '/healthz' and LOCAL_HOST.match(self.headers.get('Host') or ''):
            return self._send(200, {'ok': True})
        return self._send(404, {'error': 'not found'})

    def do_POST(self):
        if not LOCAL_HOST.match(self.headers.get('Host') or '') or any(self.headers.get(h) for h in FORWARD_HEADERS):
            return self._send(403, {'error': 'the extension port takes direct local requests only'})
        if not self.app.config.extension_ok(self.headers.get('Origin')):
            return self._send(403, {'error': 'only the mai-tabs extension may report tabs'})
        body, refusal = self._body()
        if refusal:
            return self._send(refusal[0], {'error': refusal[1]})
        path = self.path.split('?', 1)[0]
        if path == '/api/ack':
            return self._guard(lambda: self._send(200, self.app.ack(body)))
        if path == '/api/sync':
            def sync():
                counts = self.app.lib.sync(body)
                return self._send(200, {'counts': counts, 'commands': self.app.lib.pending(body['instance'])})
            return self._guard(sync)
        return self._send(404, {'error': 'not found'})


def handlers(app):
    return type('Page', (PageHandler,), {'app': app}), type('Ext', (ExtensionHandler,), {'app': app})


def serve(port=28770, home=None, ready=None, ext_port=None):
    app = App(library.Library(home))
    app.keep_measuring()
    page_h, ext_h = handlers(app)
    page = http.server.ThreadingHTTPServer(('127.0.0.1', port), page_h)
    ext = http.server.ThreadingHTTPServer(('127.0.0.1', ext_port or port + 1), ext_h)
    threading.Thread(target=ext.serve_forever, daemon=True, name='mai-tabs-extension-port').start()
    if ready:
        ready(page, ext)
    try:
        page.serve_forever()
    finally:
        page.server_close()
        ext.shutdown()
        ext.server_close()
