"""Render the real viewer with a public-safe fixture and measure geometry in Chrome.

Optional manual check, no extra Python packages. Supply --browser with a local Chrome/Chromium executable.
--ref HEAD checks the baseline without editing it. Only a temporary loopback server and this check's browser are started.
"""
import argparse
import http.server
import json
from pathlib import Path
import subprocess
import threading
import time

TOOL = Path(__file__).resolve().parents[1]
REPO = TOOL.parents[1]


def fixture():
    now = time.time()
    iso = lambda t: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t))
    samples = []
    for i in range(121):
        gpus = []
        for n in range(2):
            processes = [{'pid': p + 1, 'process': 'desktop-%d.exe' % p, 'vram_mib': None} for p in range(37)]
            if n == 0:
                processes = [{'pid': 90, 'process': 'trainer.exe', 'run_name': 'terrain', 'elapsed_s': 5400, 'vram_mib': 8192}]
            gpus.append({'index': n, 'uuid': 'GPU-%d' % n, 'name': 'Example GPU 16 GiB', 'util_pct': 30 + n * 40 + i % 8,
                         'vram_used_mib': 8192 + n * 4096, 'vram_total_mib': 16384, 'temperature_c': 52 + n * 4,
                         'power_w': 120, 'power_limit_w': 360, 'sm_clock_mhz': 2100, 'sm_clock_max_mhz': 3000,
                         'throttle': [], 'processes': processes})
        samples.append({'t': iso(now - 120 + i), 'cpu_pct': 30, 'cpu_per_core': [float((j * 7) % 100) for j in range(64)],
                        'ram_pct': 42, 'ram_used_gib': 108, 'ram_total_gib': 256, 'swap_total_gib': 16, 'swap_used_gib': 1,
                        'ram_processes': [{'pid': j + 100, 'process': 'worker-%d.exe' % j, 'rss_mib': 4000 - j * 400} for j in range(5)],
                        'cpu_processes': [{'pid': j + 200, 'process': 'compute-%d.exe' % j, 'cpu_pct': 125 - j * 30} for j in range(3)], 'cpu_process_age_s': 2,
                        'gpus': gpus, 'disks': [],
                        'nics': [{'nic': 'Ethernet', 'kind': 'wired', 'rx_mib_s': 1.2, 'tx_mib_s': 0.3, 'link_mbps': 100}]})
    limits = [{'engine': name, 'five_hour': {'pct': 15, 'read_at': iso(now)},
               'seven_day': {'pct': 75, 'read_at': iso(now)}} for name in ('claude', 'codex')]
    judgments = [{'kind': 'disk_space', 'subject': 'volume-%d' % i, 'level': 'bad' if i < 2 else 'warn',
                  'text': text} for i, text in enumerate(['Archive volume has 7 GiB free', 'Cache volume is almost full',
                    'Project volume has 12 GiB free', 'Wired link is 100 Mbps', 'Backup volume needs review'])]
    return {'schema': 'mai-watch-live-v1', 'interval_s': 1, 'history_s': 600,
            'host': {'available': True, 'logical_cpus': 64}, 'samples': samples, 'judgments': judgments, 'disks': {},
            'diagnostics': {'schema': 'mai-watch-diagnostic-v1', 'checks': [{'source': 'gpu', 'state': 'available', 'reason': 'measurement available', 'next_check': 'No change needed'}]},
            'incidents': [{'last_seen': now - 10, 'state': 'cleared', 'text': 'Earlier GPU temperature warning'}],
            'slow': {'paths': [], 'usage': {'available': True, 'limits': limits, 'sessions': []}}}


PROBE = r"""<script>
setTimeout(function () {
  function rect(e) { var r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom}; }
  function visible(e) { return !!e && !e.closest('details:not([open])') && e.getBoundingClientRect().height>0; }
  var result={width:innerWidth,height:innerHeight,overflow:document.documentElement.scrollWidth>innerWidth,
    coreGrid:document.querySelector('.cores')?rect(document.querySelector('.cores')):null,
    gpus:Array.from(document.querySelectorAll('.gpu-row')).map(rect),
    hosts:Array.from(document.querySelectorAll('.host-band > *')).map(rect),
    attention:document.querySelector('.attention')?rect(document.querySelector('.attention')):null,
    cores:Array.from(document.querySelectorAll('.core')).map(rect),
    warningsVisible:Array.from(document.querySelectorAll('.att-text')).every(visible),
    highlightsVisible:Array.from(document.querySelectorAll('.usage-highlight')).every(visible),
    processes:Array.from(document.querySelectorAll('.gpu-process')).map(function(e){return e.textContent;}),
    gpuCount:document.querySelectorAll('.gpu-row').length,
    warningCount:document.querySelectorAll('.att-text').length,
    error:document.getElementById('error').style.display==='block'?document.getElementById('error').textContent:''};
  var pre=document.createElement('pre');pre.id='layout-check';pre.hidden=true;pre.textContent=JSON.stringify(result);document.body.appendChild(pre);
},1800);
</script>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--browser', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--ref', default='')
    ap.add_argument('--label', default='after')
    ap.add_argument('--recovery', action='store_true')
    ap.add_argument('--product', action='store_true')
    args = ap.parse_args()
    assets = {}
    for name in ('viewer.html', 'viewer-live.js', 'viewer-health.js', 'viewer-connection.js', 'manifest.webmanifest', 'viewer-icon.svg'):
        if args.ref:
            p = subprocess.run(['git', 'show', args.ref + ':tools/mai-watch/mai_watch/' + name], cwd=REPO, capture_output=True)
            if p.returncode and name == 'viewer-connection.js' and b'viewer-connection.js' not in assets['viewer.html']:
                continue  # Older HTML never requested the new helper.
            p.check_returncode()
            assets[name] = p.stdout
        else:
            assets[name] = (TOOL / 'mai_watch' / name).read_bytes()
    page = assets['viewer.html'].decode('utf-8')
    page = page.replace('</body>', PROBE + '</body>')
    page = page.replace('<h1>mai-watch</h1>', '<h1>mai-watch</h1><span class="quiet">Review fixture · not live system</span>')
    assets['viewer.html'] = page.encode('utf-8')

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def do_GET(self):
            name = self.path.split('?')[0].lstrip('/') or 'viewer.html'
            if name == 'live.json':
                payload = json.dumps(fixture()).encode('utf-8')
                content = 'application/json'
            elif name == 'diagnostic.json':
                payload = json.dumps(fixture()['diagnostics']).encode('utf-8')
                content = 'application/json'
            elif name in assets:
                payload = assets[name]
                content = 'text/html' if name.endswith('.html') else 'text/javascript' if name.endswith('.js') else 'application/octet-stream'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', content + '; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        for width, height in ((1920, 1080), (390, 844)):
            shot = out / ('%s-%d.png' % (args.label, width))
            command = ['node', str(TOOL / 'tests' / 'capture_cdp.mjs'), args.browser,
                       'http://127.0.0.1:%d/' % server.server_address[1], str(width), str(height), str(shot)]
            if args.product:
                command.append('product')
            elif args.recovery:
                command.append('recovery')
            p = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45)
            if p.returncode or not p.stdout.strip() or not shot.is_file():
                raise RuntimeError('Browser did not produce the layout measurement: ' + p.stderr[-500:])
            result = json.loads(p.stdout)
            errors = []
            if result['width'] != width or result['overflow'] or result['gpuCount'] != 2 or result['error']:
                errors.append('viewport, overflow, GPU count or page error')
            if not result['warningsVisible'] or not result['highlightsVisible'] or result['warningCount'] != 5:
                errors.append('warnings or limits hidden')
            if len(result['processes']) != 1 or not result['processes'][0].startswith('trainer.exe'):
                errors.append('unverified desktop processes shown')
            if width == 390:
                a, b = result['gpus']
                if abs(a['x'] - b['x']) > 1 or b['y'] < a['bottom']:
                    errors.append('mobile GPUs are not stacked')
            else:
                hosts = result['hosts']
                if len(hosts) != 3 or max(h['y'] for h in hosts) - min(h['y'] for h in hosts) > 1 or max(h['height'] for h in hosts) - min(h['height'] for h in hosts) > 1:
                    errors.append('host card edges do not align')
                if not result['cores'] or min(c['height'] for c in result['cores']) < (6 if args.product else 18):
                    errors.append('CPU core cells too small')
                if args.product and result['coreGrid']['height'] > 101:
                    errors.append('CPU core area not reduced to approximately half')
                if args.product and any(abs(h['height'] - 327) > 1 for h in hosts):
                    errors.append('existing desktop host card height changed')
                alert = result['attention']
                if len(hosts) == 3 and (not alert or abs(alert['x'] - hosts[2]['x']) > 1 or
                        abs(result['gpus'][0]['x'] + result['gpus'][0]['width'] - hosts[1]['x'] - hosts[1]['width']) > 1):
                    errors.append('overview and host columns do not share grid edges')
            result['failures'] = errors
            results.append(result)
        (out / (args.label + '-layout.json')).write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
    print(json.dumps([{'width': r['width'], 'failures': r['failures']} for r in results]))
    return int(any(r['failures'] for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
