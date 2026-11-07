import argparse
import sys

from . import convert as conv


def main(argv=None):
    p = argparse.ArgumentParser(prog='mai-work')
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('convert', help='move an eight-column WORKLIST.tsv into WORK.tsv + WORK-events.tsv and prove no cell was lost')
    c.add_argument('source')
    c.add_argument('out_dir')
    k = sub.add_parser('check', help='check a WORK.tsv (or the old WORKLIST.tsv) against rules C1 to C10; exit 1 on any FAIL')
    k.add_argument('path')
    k.add_argument('--iter', type=int, default=None, help='current training update, for iter:N deadlines')
    k.add_argument('--json', action='store_true', help='print the document the mai-watch tab shows')
    a = p.parse_args(argv)
    if a.cmd == 'check':
        import json
        from . import check as chk
        d = chk.document(a.path, it=a.iter)
        if a.json:
            print(json.dumps(d, ensure_ascii=False, indent=1))
        elif 'error' in d:
            print('check refused: %s' % d['error'], file=sys.stderr)
        else:
            for f in d['findings']:
                print('%-4s %-4s %-5s %-2s %-8s %s' % (f['level'], f['rule'], f['id'], f['priority'], f['owner'], f['msg']))
            c = d['counts']
            print('FAIL %d · WARN %d · INFO %d · items %d (%s)' % (c['FAIL'], c['WARN'], c['INFO'], len(d['items']), d['format']))
        return 2 if 'error' in d else (1 if d['counts']['FAIL'] else 0)
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
