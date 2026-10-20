"""mai-resume command line.

  mai-resume run [--once] [--dry-run] [--home DIR] [--limits FILE]   the guard (one per machine)
  mai-resume status [--home DIR]                                     heartbeat check, exit 1 when stale
  mai-resume send --to HANDLE --text TEXT [--wait S]                 send one line to another session, only when
                                                                     nobody is typing there (exit 0 sent, 4 busy)
"""
import argparse
import sys

from . import runner


def main(argv=None):
    ap = argparse.ArgumentParser(prog='mai-resume', description='Warn AI coding sessions before a plan limit runs out, wake them after it resets.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run', help='run the guard loop')
    r.add_argument('--once', action='store_true', help='one round, then exit')
    r.add_argument('--dry-run', action='store_true', help='decide and log, send nothing')
    r.add_argument('--home', help='state and config folder (default ~/.mai/resume)')
    r.add_argument('--limits', help='plan limits file (default ~/.mai/limits.json)')
    s = sub.add_parser('status', help='print the guard state')
    s.add_argument('--home')
    t = sub.add_parser('send', help='send one line to a session only when nobody is typing there')
    t.add_argument('--to', required=True, help='Orca terminal handle')
    t.add_argument('--text', required=True)
    t.add_argument('--wait', type=float, default=600, help='seconds to wait for a quiet prompt (default 600)')
    a = ap.parse_args(argv)
    if a.cmd == 'send':
        exe = runner.find_orca(runner.core.merged(runner.load_json(runner.os.path.join(runner.home_dir(None), 'config.json'), {})))
        if not exe:
            print('orca CLI not found')
            return 2
        return runner.safe_send(runner.Orca(exe), a.to, a.text, wait_s=a.wait)
    if a.cmd == 'run':
        return runner.run(home=a.home, limits_path=a.limits, once=a.once, dry=a.dry_run)
    return runner.status(home=a.home)


if __name__ == '__main__':
    sys.exit(main())
