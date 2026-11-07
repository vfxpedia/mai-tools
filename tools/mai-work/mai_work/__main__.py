import argparse
import json
import sys

from . import convert as conv

EDIT_COMMANDS = {
    'add': ('title', 'owner', 'priority', 'end_plan', 'start_plan', 'stage', 'after', 'evidence', 'source', 'why'),
    'start': (),
    'done': ('evidence', 'why', 'decided_at', 'decided_by'),
    'hold': ('wait_for', 'why'),
    'resume': ('why',),
    'cancel': ('why', 'decision', 'decided_at', 'decided_by'),
    'replace': ('replaced_by', 'why', 'decision', 'decided_at', 'decided_by'),
    'change': ('field', 'value', 'why', 'decision', 'decided_at', 'decided_by'),
    'lock': ('topic', 'why', 'decision', 'decided_at', 'decided_by'),
    'decide': ('why', 'decision', 'decided_at', 'decided_by'),
}


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
    n = sub.add_parser('notify', help="tell owners' windows about overdue / late items (dry run unless --send)")
    n.add_argument('path')
    n.add_argument('--owners', required=True, help='TSV: owner<TAB>Orca terminal handle')
    n.add_argument('--state', required=True, help='JSON file remembering what was sent, so each item is sent once per 6 h')
    n.add_argument('--iter', type=int, default=None)
    n.add_argument('--send', action='store_true', help='really send (default prints what would be sent)')
    for name, opts in EDIT_COMMANDS.items():
        e = sub.add_parser(name, help='change the list: %s (writes WORK.tsv and a line in WORK-events.tsv)' % name)
        e.add_argument('path')
        e.add_argument('id')
        e.add_argument('--by', required=True, help='who makes the change')
        for o in opts:
            e.add_argument('--' + o.replace('_', '-'), dest=o, default=None)
    lg = sub.add_parser('log', help='every recorded change of one item, with when it was decided and when it was written')
    lg.add_argument('path')
    lg.add_argument('id')
    ak = sub.add_parser('ask', help='before asking the owner: is this topic already decided?')
    ak.add_argument('path')
    ak.add_argument('topic')
    a = p.parse_args(argv)

    if a.cmd in EDIT_COMMANDS:
        from . import edit
        try:
            new = edit.apply(a.path, a.cmd, a.id, a.by, **{o: getattr(a, o) for o in EDIT_COMMANDS[a.cmd]})
        except (edit.EditError, conv.ConvertError) as e:
            print('refused: %s' % e, file=sys.stderr)
            return 2
        for e in new:
            print('%s %s %s %s -> %s' % (e['ts'], e['id'], e['event'], e['from'], e['to']))
        return 0
    if a.cmd in ('log', 'ask'):
        from . import edit
        try:
            if a.cmd == 'log':
                for e in edit.log(a.path, a.id):
                    print('기록 %s · 결정 %s %s · %s %s %s -> %s · %s · %s · by %s' % (e['ts'], e['decided_at'] or '-', e['decided_by'],
                          e['event'], e['field'], e['from'], e['to'], e['why'], e['decision'], e['by']))
                return 0
            r = edit.ask(a.path, a.topic)
        except (edit.EditError, conv.ConvertError) as e:
            print('refused: %s' % e, file=sys.stderr)
            return 2
        if r is None:
            print('%s: 확정 기록 없음' % a.topic)
            return 1
        print('%s: 이미 확정 · %s · 결정 %s %s · 근거 %s' % (a.topic, r['id'], r['decided_at'], r['decided_by'], r['decision']))
        return 0
    if a.cmd == 'notify':
        from . import notify
        r = notify.run(a.path, a.owners, a.state, do_send=a.send, it=a.iter)
        if 'error' in r:
            print('notify refused: %s' % r['error'], file=sys.stderr)
            return 2
        for ln in r['lines']:
            print('%-4s %-5s %-8s %-36s %s%s\n     %s' % (ln['rule'], ln['id'], ln['owner'], ln['result'], ln['handle'] or '-',
                                                     ' · telegram' if ln['telegram'] else '', ln['text']))
        if not r['lines']:
            print('nothing to tell')
        return 0
    if a.cmd == 'check':
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
