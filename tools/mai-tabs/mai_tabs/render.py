"""Markdown rendering of an export. The Markdown is a pure function of the export JSON and the rules, so the two never disagree.

Defense in depth: the renderer sanitizes every URL again (idempotent), so an export from another tool can never put a query string
or a fragment into the Markdown. It never prints em dashes.
"""
import datetime
import re

from . import classify as classify_mod
from .sanitize import sanitize_url


CONTROL = re.compile('[\x00-\x1f\x7f]')


def md_text(text):
    """Text from the browser (titles, group names) made safe for Markdown and for viewers that allow raw HTML (T3):
    control characters become spaces, HTML-significant characters become entities, Markdown-significant ones get a backslash."""
    t = ' '.join(CONTROL.sub(' ', str(text or '')).split())
    t = t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    for ch in ('\\', '[', ']', '(', ')', '|', '*', '_', '`'):
        t = t.replace(ch, '\\' + ch)
    return t or '(no title)'


def md_url(url):
    """A link destination that cannot end the link early or open an HTML tag."""
    out = CONTROL.sub('', str(url or ''))
    for ch, code in ((' ', '%20'), ('(', '%28'), (')', '%29'), ('<', '%3C'), ('>', '%3E'), ('`', '%60'), ('"', '%22'), ('\\', '%5C')):
        out = out.replace(ch, code)
    return out


escape_title = md_text


def flatten(export):
    """Tabs in window and index order, each with its window id and group title."""
    groups = {g['id']: g for g in export.get('groups', [])}
    out = []
    for w in export['windows']:
        for t in sorted(w['tabs'], key=lambda x: x['index']):
            g = groups.get(t.get('group_id'))
            out.append(dict(t, window_id=w['id'], group_title=(g['title'] or '(untitled group)') if g else None,
                            url=sanitize_url(t.get('url', ''))))
    return out


def categorize(export, rules):
    cats = {}
    for t in flatten(export):
        cats.setdefault(classify_mod.classify(rules, t['url'], t['title']), []).append(t)
    return cats


def render(export, rules):
    cats = categorize(export, rules)
    order = [c['name'] for c in rules['categories']] + [rules.get('default', 'uncategorized')]
    names = [n for n in order if n in cats]
    c = export['counts']
    lines = ['# Open tabs', '',
             'Exported: %s' % export['exported_at'],
             'Browser: %s %s' % (export['browser']['name'], export['browser']['version']),
             'Windows: %d · tabs: %d · groups: %d' % (c['windows'], c['tabs'], c['groups']),
             'URLs have no query string and no fragment.', '']
    for n in names:
        lines.append('## %s (%d)' % (md_text(n), len(cats[n])))
        lines.append('')
        for t in cats[n]:
            flags = []
            if t.get('pinned'):
                flags.append('pinned')
            if t.get('audible'):
                flags.append('audible')
            if t.get('discarded'):
                flags.append('discarded')
            if t['group_title']:
                flags.append('group: ' + md_text(t['group_title']))
            flags.append('window %s' % t['window_id'])
            link = '[%s](%s)' % (md_text(t['title']), md_url(t['url'])) if t['url'] else md_text(t['title'])
            lines.append('- %s (%s)' % (link, ', '.join(flags)))
        lines.append('')
    return '\n'.join(lines).rstrip('\n') + '\n'


def parse_time(s):
    return datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')


def consistency_problems(export):
    """Semantic rules the JSON Schema cannot express: the counts must match the content."""
    out = []
    n = sum(len(w['tabs']) for w in export['windows'])
    c = export['counts']
    if c['windows'] != len(export['windows']):
        out.append('counts.windows is %d but there are %d windows' % (c['windows'], len(export['windows'])))
    if c['tabs'] != n:
        out.append('counts.tabs is %d but there are %d tabs' % (c['tabs'], n))
    if c['groups'] != len(export['groups']):
        out.append('counts.groups is %d but there are %d groups' % (c['groups'], len(export['groups'])))
    ids = [g['id'] for g in export['groups']]
    for w in export['windows']:
        for t in w['tabs']:
            if t['group_id'] is not None and t['group_id'] not in ids:
                out.append('tab %s refers to unknown group %s' % (t['id'], t['group_id']))
    return out
