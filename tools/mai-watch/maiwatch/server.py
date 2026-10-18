"""Local viewer server (DESIGN.md section 9). Binds 127.0.0.1 only and serves exactly four things: the viewer page and three output files."""
import http.server
import os

ALLOWED = ('snapshot.json', 'collector_heartbeat.json', 'events.jsonl')
PACKAGE_FILES = ('viewer-health.js',)
TAIL_BYTES = 128 * 1024      # events.jsonl is served as its last lines only, so a long log cannot make every poll heavy
VIEWER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'viewer.html')
TYPES = {'viewer-health.js': 'application/javascript; charset=utf-8', 'snapshot.json': 'application/json', 'collector_heartbeat.json': 'application/json', 'events.jsonl': 'text/plain; charset=utf-8'}


def make_handler(out_dir):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            if path in ('/', '/index.html'):
                with open(VIEWER, 'rb') as f:
                    return self._send(200, f.read(), 'text/html; charset=utf-8')
            name = path.lstrip('/')
            if name in PACKAGE_FILES:
                with open(os.path.join(os.path.dirname(VIEWER), name), 'rb') as f:
                    return self._send(200, f.read(), TYPES[name])
            if name in ALLOWED:
                try:
                    with open(os.path.join(out_dir, name), 'rb') as f:
                        if name == 'events.jsonl':
                            size = f.seek(0, 2)
                            f.seek(max(0, size - TAIL_BYTES))
                            data = f.read()
                            if size > TAIL_BYTES:
                                data = data.split(b'\n', 1)[-1]      # drop the first, possibly cut, line
                            return self._send(200, data, TYPES[name])
                        return self._send(200, f.read(), TYPES[name])
                except OSError:
                    return self._send(404, b'not written yet', 'text/plain')
            return self._send(404, b'not found', 'text/plain')
    return Handler


def make_server(out_dir, port=28765):
    return http.server.ThreadingHTTPServer(('127.0.0.1', port), make_handler(out_dir))
