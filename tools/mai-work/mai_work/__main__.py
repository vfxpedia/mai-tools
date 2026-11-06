import argparse
import sys

from . import convert as conv


def main(argv=None):
    p = argparse.ArgumentParser(prog='mai-work')
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('convert', help='move an eight-column WORKLIST.tsv into WORK.tsv + WORK-events.tsv and prove no cell was lost')
    c.add_argument('source')
    c.add_argument('out_dir')
    a = p.parse_args(argv)
    try:
        r = conv.convert(a.source, a.out_dir)
    except conv.ConvertError as e:
        print('convert refused: %s' % e, file=sys.stderr)
        return 2
    print('rows %d · round trip differences %d · rebuilt text identical %s · sha256 %s'
          % (r['rows'], len(r['diffs']), r['same_text'], r['sha256'][:16]))
    return 0 if not r['diffs'] and r['same_text'] else 1


if __name__ == '__main__':
    sys.exit(main())
