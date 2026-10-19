"""mai-resume command line.

  mai-resume run [--once] [--dry-run] [--home DIR] [--limits FILE]   the guard (one per machine)
  mai-resume status [--home DIR]                                     heartbeat check, exit 1 when stale
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
    a = ap.parse_args(argv)
    if a.cmd == 'run':
        return runner.run(home=a.home, limits_path=a.limits, once=a.once, dry=a.dry_run)
    return runner.status(home=a.home)


if __name__ == '__main__':
    sys.exit(main())
