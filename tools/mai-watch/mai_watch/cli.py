"""Command line: python -m mai_watch {collect,check,show,validate,init}. Read-only toward workloads: no stop, kill or launch."""
import argparse
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
# ignore_processes = ["explorer.exe", "chatgpt.exe"]
# [baseline_memory_mib]
# "GPU-00000000-0000-0000-0000-000000000000" = 5645
"""


def main(argv=None):
    ap = argparse.ArgumentParser(prog='mai-watch', description='Resource and workload status monitor (read-only).')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('collect', 'check', 'show', 'serve'):
        p = sub.add_parser(name)
        p.add_argument('--config', default='mai-watch.toml')
    sub.choices['collect'].add_argument('--once', action='store_true')
    sub.choices['serve'].add_argument('--port', type=int, default=28765)
    sub.choices['check'].add_argument('--ignore', action='append', default=[], help='alert type to ignore, e.g. device_idle')
    v = sub.add_parser('validate'); v.add_argument('files', nargs='+')
    i = sub.add_parser('init'); i.add_argument('dir')
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


if __name__ == '__main__':
    sys.exit(main())
