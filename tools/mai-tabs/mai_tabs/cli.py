"""Command line: python -m mai_tabs {render,propose,procs,check-rules,verify,serve}.

The report commands are read-only. `serve` runs the tab library (DESIGN.md section 12): it closes or sleeps tabs only when the owner
presses a button on its page, and only through the extension in the owner's own browser."""
import argparse
import json
import os
import sys

from . import classify, procs, propose, render

DEFAULT_RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rules.default.json')


def load_export(path):
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    if d.get('schema') != 'mai-tabs-export-v1':
        raise SystemExit('not a mai-tabs export (schema must be mai-tabs-export-v1)')
    problems = render.consistency_problems(d)
    if problems:
        raise SystemExit('export is inconsistent: ' + '; '.join(problems))
    return d


def main(argv=None):
    ap = argparse.ArgumentParser(prog='mai-tabs', description='Saved-tab report: Markdown by category, cleanup proposal, browser process report.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('render'); r.add_argument('export'); r.add_argument('--rules', default=DEFAULT_RULES); r.add_argument('--out')
    p = sub.add_parser('propose'); p.add_argument('export'); p.add_argument('--days', type=int, default=14); p.add_argument('--out')
    q = sub.add_parser('procs'); q.add_argument('--json', action='store_true'); q.add_argument('--name', action='append', help='process name to include (repeatable, case-insensitive), e.g. chrome.exe; default: Chrome, Edge, Brave and Firefox')
    c = sub.add_parser('check-rules'); c.add_argument('rules')
    v = sub.add_parser('verify', help='re-read a downloaded export and print what it contains, to compare with the popup message'); v.add_argument('export'); v.add_argument('--expect-tabs', type=int)
    s = sub.add_parser('serve', help='run the tab library on 127.0.0.1 (reach it from a phone through Tailscale Serve)')
    s.add_argument('--port', type=int, default=28766, help='page port; the extension port is this plus one'); s.add_argument('--home', help='data folder (default ~/.mai/tabs or MAI_TABS_HOME)')
    a = ap.parse_args(argv)
    if a.cmd == 'serve':
        from . import server
        server.serve(a.port, a.home, ready=lambda page, ext: print('mai-tabs library on http://127.0.0.1:%d (extension port %d)'
                                                                  % (page.server_address[1], ext.server_address[1]), flush=True))
        return 0
    try:
        if a.cmd == 'render':
            text = render.render(load_export(a.export), classify.load_rules(a.rules))
        elif a.cmd == 'propose':
            text, _ = propose.propose(load_export(a.export), a.days)
        elif a.cmd == 'procs':
            s = procs.summarize(procs.collect_rows(tuple(n.lower() for n in a.name) if a.name else procs.BROWSER_NAMES))
            text = json.dumps(s, indent=2) + '\n' if a.json else procs.render(s)
        elif a.cmd == 'verify':
            d = load_export(a.export)
            col = d.get('collection') or {}
            text = 'windows %d, tabs %d, groups %d; collection %s%s\n' % (d['counts']['windows'], d['counts']['tabs'], d['counts']['groups'],
                                                                         'complete' if col.get('complete', True) else 'INCOMPLETE', ('; ' + '; '.join(col.get('notes', []))) if col.get('notes') else '')
            if a.expect_tabs is not None and a.expect_tabs != d['counts']['tabs']:
                print('tab count %d does not match the expected %d' % (d['counts']['tabs'], a.expect_tabs), file=sys.stderr)
                return 2
        else:
            classify.load_rules(a.rules)
            text = 'rules ok\n'
    except classify.RulesError as e:
        print('rules problem: %s' % e, file=sys.stderr)
        return 2
    except ImportError:
        print('psutil is required for the process report (pip install psutil)', file=sys.stderr)
        return 2
    out = getattr(a, 'out', None)
    if out:
        with open(out, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        print('wrote', out)
    else:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
