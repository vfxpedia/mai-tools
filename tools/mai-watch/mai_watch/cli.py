"""Command line: mai-watch [live|demo|status|collect|check|show|serve|validate|init]. With no command it starts the live view.
Read-only toward workloads: no stop, kill or launch."""
import argparse
import datetime
import json
import os
import sys

from . import collector, status

DEFAULT_TOML = """# mai_watch configuration. Paths are relative to this file.
status_dir = "status"
out_dir = "out"
interval_s = 10
idle_window_s = 600
idle_utilization_pct = 5
idle_min_s = 600
idle_resume_s = 60
stale_factor = 3
# nvidia_smi = ["nvidia-smi"]
# folders shown in the live view with free space and answer time; empty means every local drive
# watch_paths = ["D:/runs", "//nas/share"]
# notifications: the command gets each message on stdin (and in notify_file when set); mai-watch never holds a token
# notify_cmd = ["powershell", "-File", "C:/path/send.ps1"]
# notify_file = "C:/path/outbox.txt"
# notify_level = "warn"        # bad, warn or info
# notify_hold_s = 60           # a finding must last this long before it is announced, and be gone this long before it is cleared
# ignore_processes = ["explorer.exe", "chatgpt.exe"]
# [baseline_memory_mib]
# "GPU-00000000-0000-0000-0000-000000000000" = 5645
"""


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):    # an OS message or a Korean name the console code page cannot show must not change the exit code
        try:
            stream.reconfigure(errors='replace')
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog='mai-watch', description='Resource and workload status monitor (read-only).')
    sub = ap.add_subparsers(dest='cmd')
    for name in ('collect', 'check', 'show', 'serve'):
        p = sub.add_parser(name)
        p.add_argument('--config', default='mai-watch.toml')
    sub.choices['collect'].add_argument('--once', action='store_true')
    sub.choices['serve'].add_argument('--port', type=int, default=28765)
    sub.choices['check'].add_argument('--ignore', action='append', default=[], help='alert type to ignore, e.g. device_idle')
    lv = sub.add_parser('live', help='the default: live resources in the browser; with --config also records workloads and idle state')
    dm = sub.add_parser('demo', help='live view plus a sample job, in a new folder (default: ~/mai-watch-demo)')
    dm.add_argument('dir', nargs='?', default=os.path.join(os.path.expanduser('~'), 'mai-watch-demo'))
    for p in (lv, dm):
        p.add_argument('--port', type=int, default=28765)
        p.add_argument('--interval', type=float, default=1.0, help='seconds between live samples (0.2 to 60)')
        p.add_argument('--history', type=float, default=600, help='seconds of live history kept in memory')
        p.add_argument('--nvidia-smi', default='nvidia-smi')
        p.add_argument('--path', action='append', default=[], help='folder to watch for free space and answer time, e.g. a NAS share; repeatable')
        p.add_argument('--mai-home', default=None, help='where the session gauges write usage (default ~/.mai or $MAI_HOME)')
        p.add_argument('--no-usage', action='store_true', help='do not show Claude and Codex usage')
        p.add_argument('--no-browser', action='store_true', help='do not open the page in a browser')
        p.add_argument('--notify-cmd', default=None, help='command that receives each notification on stdin, e.g. "python send.py"')
        p.add_argument('--notify-file', default=None, help='also write each notification to this file before running the command')
        p.add_argument('--notify-level', default=None, choices=('bad', 'warn', 'info'), help='lowest level announced (default warn)')
        p.add_argument('--notify-hold', type=float, default=None, help='seconds a finding must last before it is announced (default 60)')
    st = sub.add_parser('status', help='print what needs attention now, from a running mai-watch; exit 1 when anything is at warn or bad')
    st.add_argument('--url', default='http://127.0.0.1:28765/status.json')
    st.add_argument('--json', action='store_true', help='print the whole status document')
    lv.add_argument('--config', default=None, help='optional: also run the workload collector of this configuration')
    v = sub.add_parser('validate'); v.add_argument('files', nargs='+')
    i = sub.add_parser('init'); i.add_argument('dir')
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith('-') and argv[0] not in ('-h', '--help')):
        argv = ['live'] + argv               # no command: the live view, which is what most people want first
    a = ap.parse_args(argv)

    if a.cmd == 'init':
        os.makedirs(a.dir, exist_ok=True)
        p = os.path.join(a.dir, 'mai-watch.toml')
        if os.path.exists(p):
            print('refusing to overwrite %s' % p, file=sys.stderr)
            return 2
        open(p, 'w', encoding='utf-8', newline='\n').write(DEFAULT_TOML)
        print('wrote', p)
        return 0
    if a.cmd == 'validate':
        bad = 0
        for f in a.files:
            try:
                doc = json.load(open(f, encoding='utf-8'))
            except Exception as e:
                print('%s: not readable as JSON: %s' % (f, e)); bad += 1; continue
            problems = status.validate(doc)
            for w in status.secret_like_fields(doc) if isinstance(doc, dict) else []:
                print('%s: warning: field name looks like a secret: %s' % (f, w))
            print('%s: %s' % (f, 'valid' if not problems else 'INVALID: ' + '; '.join(problems)))
            bad += bool(problems)
        return 1 if bad else 0
    if a.cmd == 'live':
        return run_live(a)
    if a.cmd == 'demo':
        return run_demo(a)
    if a.cmd == 'status':
        return run_status(a)
    try:
        cfg = collector.load_config(a.config)
    except FileNotFoundError:
        print('config not found: %s (create one with: python -m mai_watch init <dir>)' % a.config, file=sys.stderr)
        return 2
    except (KeyError, ValueError) as e:
        print('config problem in %s: %s' % (a.config, e), file=sys.stderr)
        return 2
    if a.cmd == 'collect':
        try:
            collector.collect(cfg, once=a.once)
        except collector.LockHeld as e:
            print(str(e), file=sys.stderr)
            return 2
        return 0
    if a.cmd == 'serve':
        from . import server
        try:
            srv = server.make_server(cfg.out_dir, a.port)
        except OSError as e:
            print('cannot listen on 127.0.0.1:%d (%s). Pick another port with --port; on Windows some ranges are reserved (netsh int ipv4 show excludedportrange protocol=tcp).' % (a.port, e.strerror or e), file=sys.stderr)
            return 2
        print('mai_watch viewer: http://127.0.0.1:%d/ (Ctrl+C to stop)' % a.port)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    if a.cmd == 'show':
        print(open(os.path.join(cfg.out_dir, 'snapshot.json'), encoding='utf-8').read())
        return 0
    alerts = collector.check(cfg.out_dir, ignore=a.ignore)
    print(json.dumps({'ok': not alerts, 'alerts': alerts}, indent=2))
    return 1 if alerts else 0


DEMO_MARKER = '.mai-watch-demo'


def write_demo(folder, now=None):
    """A folder with a configuration and one sample job that reports running now. Returns the configuration path.
    The demo writes only into a folder that does not exist yet, an empty folder, or a folder that carries the marker file it left there
    itself. Any other folder is refused untouched, so a real configuration or a real job file is never overwritten (review R2)."""
    folder = os.path.expanduser(folder)
    marker = os.path.join(folder, DEMO_MARKER)
    if os.path.isdir(folder) and os.listdir(folder) and not os.path.isfile(marker):
        raise FileExistsError('%s is not empty and was not made by mai-watch demo; nothing was changed. Pick a new folder, or for a real '
                              'setup use: mai-watch live --config <folder>/mai-watch.toml' % folder)
    os.makedirs(os.path.join(folder, 'status'), exist_ok=True)
    if not os.path.isfile(marker):
        with open(marker, 'w', encoding='utf-8', newline='\n') as f:
            f.write('made by mai-watch demo; the demo rewrites only folders that carry this file\n')
    cfg = os.path.join(folder, 'mai-watch.toml')
    if not os.path.exists(cfg):
        with open(cfg, 'w', encoding='utf-8', newline='\n') as f:
            f.write(DEFAULT_TOML)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    job = {'schema_version': 1, 'id': 'my-first-job', 'kind': 'job', 'state': 'running', 'updated_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
           'heartbeat_interval_s': 60, 'device_uuids': []}
    with open(os.path.join(folder, 'status', 'my-first-job.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(job, f, indent=2)
    return cfg


def status_problems(doc):
    """Why a status document cannot be trusted, or [] (review R16). Counts are recomputed from the checked judgments, never taken."""
    if not isinstance(doc, dict):
        return ['not a JSON object']
    p = []
    if doc.get('schema') != 'mai-watch-status-v1':
        p.append('schema is not mai-watch-status-v1')
    found = doc.get('judgments')
    if not isinstance(found, list):
        p.append('judgments is not a list')
    else:
        for i, f in enumerate(found):
            if not isinstance(f, dict) or f.get('level') not in ('bad', 'warn', 'info') or not isinstance(f.get('text'), str):
                p.append('judgment %d is malformed' % i)
    if not isinstance(doc.get('fresh'), bool):
        p.append('freshness is missing')
    counts = doc.get('counts')
    if isinstance(found, list) and not p:
        mine = {k: sum(1 for f in found if f['level'] == k) for k in ('bad', 'warn', 'info')}
        if not isinstance(counts, dict) or any(counts.get(k) != v for k, v in mine.items()):
            p.append('counts do not match the judgments')
    return p


def run_status(a):
    """For people and AI agents: the judgment list of a running mai-watch, one line each with its level. Exit 0 when nothing is at
    warn or bad, 1 when something is, 2 when no valid and fresh status could be had (unreachable, a malformed document, or samples
    that stopped). Exit 2 is never "all clear"."""
    import urllib.request
    try:
        with urllib.request.urlopen(a.url, timeout=10) as r:
            doc = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print('cannot read %s: %s (is mai-watch running?)' % (a.url, e), file=sys.stderr)
        return 2
    try:
        problems = status_problems(doc)
        if problems:
            print('%s is not a usable mai-watch status document: %s' % (a.url, '; '.join(problems)), file=sys.stderr)
            return 2
        if a.json:
            print(json.dumps(doc, indent=2, ensure_ascii=False))
        found = doc['judgments']
        bad = sum(1 for f in found if f['level'] == 'bad')
        warn = sum(1 for f in found if f['level'] == 'warn')
        if not a.json:
            print('mai-watch status at %s (last sample %s): %d act now, %d look soon, %d notes' % (
                doc.get('generated_at'), doc.get('last_sample_at'), bad, warn, len(found) - bad - warn))
            for f in found:
                print('%-5s %s' % (f['level'], f['text']))
            if not found:
                print('nothing needs attention')
        if not doc['fresh']:
            print('samples are not fresh: %s; this is not a current reading' % (doc.get('stale_reason') or 'unknown'), file=sys.stderr)
            return 2
        return 1 if (bad or warn) else 0
    except Exception as e:                         # anything unexpected in the document is "no valid status", not a traceback
        print('%s could not be read as a status document: %s' % (a.url, type(e).__name__), file=sys.stderr)
        return 2


def run_demo(a):
    try:
        a.config = write_demo(a.dir)
    except (OSError, FileExistsError) as e:
        print(str(e), file=sys.stderr)
        return 2
    print('demo folder: %s (the sample job stops updating, so after 3 minutes it turns stale: that is the alarm working)' % a.dir)
    return run_live(a)


def run_live(a):
    """One process: live sampler, optional workload collector, local server. Ctrl+C stops all of them."""
    import threading
    from . import live, server
    cfg = None
    if a.config:
        try:
            cfg = collector.load_config(a.config)
        except (FileNotFoundError, KeyError, ValueError) as e:
            print('config problem in %s: %s' % (a.config, e), file=sys.stderr)
            return 2
    cmd = a.notify_cmd or (cfg.notify_cmd if cfg else None)
    notifier = None
    if cmd:
        from . import notify
        try:                                       # review R17: a bad notify setting stops here, before any thread or server starts
            cmd = notify.split_cmd(cmd) if isinstance(cmd, str) else [str(x) for x in cmd]
            if not cmd:
                raise ValueError('notify command is empty')
            notifier = notify.Notifier(level=a.notify_level or (cfg.notify_level if cfg else 'warn'),
                                       hold_s=a.notify_hold if a.notify_hold is not None else (cfg.notify_hold_s if cfg else 60))
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
    try:
        paths = [os.path.expanduser(p) for p in a.path] + (cfg.watch_paths if cfg else [])
        sampler = live.LiveSampler(nvidia_cmd=[a.nvidia_smi] if cfg is None else cfg.nvidia_smi, interval_s=a.interval, history_s=a.history,
                                   paths=paths or None, mai_home=a.mai_home or (cfg.mai_home if cfg else None), usage_on=not a.no_usage)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    try:
        srv = server.make_server(cfg.out_dir if cfg else None, a.port, live=sampler)
    except OSError as e:
        print('cannot listen on 127.0.0.1:%d (%s). Pick another port with --port.' % (a.port, e.strerror or e), file=sys.stderr)
        return 2
    stop = threading.Event()
    threading.Thread(target=sampler.run, args=(stop,), daemon=True).start()
    if notifier is not None:
        nfile = os.path.abspath(os.path.expanduser(a.notify_file)) if a.notify_file else (cfg.notify_file if cfg else None)
        threading.Thread(target=notify.loop, args=(sampler, notifier, cmd, stop), kwargs={'notify_file': nfile,
                         'log': lambda m: print(m, file=sys.stderr)}, daemon=True).start()
        print('notifications: %s (level %s and above)' % (' '.join(cmd), notifier.level))
    if cfg is not None:
        def record():
            try:
                collector.collect(cfg)
            except collector.LockHeld as e:
                print('workload collector not started: %s (another collector already writes this folder; the live view still runs)' % e, file=sys.stderr)
        threading.Thread(target=record, daemon=True).start()
    url = 'http://127.0.0.1:%d/' % srv.server_address[1]
    print('mai-watch live: %s  every %gs, %gs of history%s (Ctrl+C to stop)' % (
        url, a.interval, a.history, ', workloads from ' + a.config if cfg else ''))
    if not a.no_browser and not os.environ.get('CI'):
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        srv.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
