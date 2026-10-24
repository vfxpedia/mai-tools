"""Library server (DESIGN.md section 12.3). Binds 127.0.0.1 only; phones and other computers reach it through Tailscale Serve.

  GET  /                the page (app.html): the library by category or by date, open and sleep buttons
  GET  /api/view        the library, what is open now, recent actions with memory before and after
  POST /api/command     {action: open|sleep|close|dedupe, items: [ids], group: title, asleep: bool} from the page
  POST /api/sync        the extension's tab report; the answer carries the actions waiting for the browser
  POST /api/ack         the extension's result for one action

Who may do what:
  - every request must name this server in Host (127.0.0.1, localhost or a *.ts.net name), which stops DNS rebinding
  - every POST must carry the header X-Mai-Tabs: 1 and a JSON body. A web page in the browser cannot add that header to a request to
    another origin without a preflight, and this server answers no preflight, so a site cannot press the buttons for you
  - /api/sync and /api/ack come only from the extension: an Origin of chrome-extension:// and not through Tailscale Serve (Serve adds
    Tailscale-User-Login). So the library only ever holds addresses the browser itself reported, and the page can only ask to open those
"""
import http.server
import json
import os
import re
import threading
import time

from . import library, memory

PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.html')
MAX_BODY = 4 * 2 ** 20
HOST_OK = re.compile(r'^(127\.0\.0\.1|localhost|\[::1\]|[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.ts\.net)(:\d+)?$')
SETTLE_S = 20


class App:
    def __init__(self, lib, measure=memory.measure, settle_s=SETTLE_S, timer=threading.Timer):
        self.lib, self.measure, self.settle_s, self.timer = lib, measure, settle_s, timer
        self._mem, self._mem_at = None, 0
        self._mem_lock = threading.Lock()

    def memory_now(self, max_age_s=None):
        """The page gets the last background reading and never waits for one; an action's before-reading (max_age_s=0) is taken now."""
        if max_age_s == 0:
            m = self.measure()
            with self._mem_lock:
                self._mem, self._mem_at = m, time.time()
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
        c = self.lib.enqueue(action, items, body.get('group') if isinstance(body.get('group'), str) else None,
                             before=self.memory_now(max_age_s=0) if action in ('sleep', 'close', 'dedupe') else None)
        if body.get('asleep') is True and action == 'open':
            for s in c['steps']:
                s['asleep'] = True
        return c

    def ack(self, body):
        cid = body.get('id')
        if not isinstance(cid, int):
            raise ValueError('id must be a number')
        c = self.lib.ack(cid, body.get('ok') is True, body.get('done') or 0, body.get('failed') or 0, body.get('note') or '')
        if c is None:
            raise ValueError('no pending action with that id')
        if c.get('before'):
            t = self.timer(self.settle_s, lambda: self.lib.record_after(cid, self._after(c['before'])))
            t.daemon = True
            t.start()
        return {'ok': True}

    def _after(self, before):
        after = self.measure()
        return dict(after, change=memory.difference(before, after))


def make_handler(app):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = 'mai-tabs'

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, ctype='application/json'):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
            elif isinstance(body, str):
                body = body.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', ctype + ('; charset=utf-8' if ctype.startswith(('application/json', 'text/')) else ''))
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            if ctype.startswith('text/html'):
                self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
                                                            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self):
            return bool(HOST_OK.match(self.headers.get('Host') or ''))

        def do_GET(self):
            if not self._host_ok():
                return self._send(421, {'error': 'unknown host'})
            path = self.path.split('?', 1)[0]
            if path in ('/', '/index.html'):
                with open(PAGE, 'rb') as f:
                    return self._send(200, f.read(), 'text/html')
            if path == '/api/view':
                v = app.lib.view()
                v['memory'] = app.memory_now()
                return self._send(200, v)
            if path == '/healthz':
                return self._send(200, {'ok': True})
            return self._send(404, {'error': 'not found'})

        def do_OPTIONS(self):
            return self._send(405, {'error': 'no cross-origin requests'})

        def do_POST(self):
            if not self._host_ok():
                return self._send(421, {'error': 'unknown host'})
            if self.headers.get('X-Mai-Tabs') != '1' or not (self.headers.get('Content-Type') or '').startswith('application/json'):
                return self._send(403, {'error': 'missing X-Mai-Tabs header or JSON body'})
            try:
                n = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                return self._send(413, {'error': 'body too large'})
            try:
                body = json.loads(self.rfile.read(n) or b'{}')
                if not isinstance(body, dict):
                    raise ValueError('body must be an object')
            except ValueError as e:
                return self._send(400, {'error': 'bad JSON: %s' % e})
            path = self.path.split('?', 1)[0]
            from_extension = (self.headers.get('Origin') or '').startswith('chrome-extension://') and not self.headers.get('Tailscale-User-Login')
            try:
                if path == '/api/command':
                    return self._send(200, app.command(body))
                if path in ('/api/sync', '/api/ack'):
                    if not from_extension:
                        return self._send(403, {'error': 'only the browser extension may report tabs'})
                    if path == '/api/ack':
                        return self._send(200, app.ack(body))
                    counts = app.lib.sync(body)
                    return self._send(200, {'counts': counts, 'commands': app.lib.pending()})
            except ValueError as e:
                return self._send(400, {'error': str(e)})
            return self._send(404, {'error': 'not found'})

    return Handler


def serve(port=28766, home=None, ready=None):
    app = App(library.Library(home))
    app.keep_measuring()
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', port), make_handler(app))
    if ready:
        ready(httpd)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
