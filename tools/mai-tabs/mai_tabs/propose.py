"""Cleanup proposal. Text only: this module can never close a tab or end a process. The owner confirms the list first.

Rules (independent review T1, T2):
- Pinned and audible tabs are never close candidates, in any section. A protected tab in a duplicate set is the one that stays.
- Two tabs are duplicates only when their full original addresses are equal. The export keeps that as a short one-way identity (url_id);
  the shortened address shown in the report is for display and is not used to decide. Without url_id (older exports) nothing is proposed
  from address equality; the report only says which shown addresses are shared.
- Every candidate lists window, tab index, tab id, title and address so a person can find it and compare.
"""
from collections import defaultdict

from .render import flatten, md_text, md_url, parse_time

DAY_MS = 86400 * 1000


def protected(t):
    return bool(t.get('pinned') or t.get('audible'))


def where(t):
    return 'window %s tab %s (id %s)' % (t['window_id'], t['index'], t['id'])


def propose(export, stale_days=14):
    tabs = flatten(export)
    exported_ms = int((parse_time(export['exported_at']) - parse_time('1970-01-01T00:00:00Z')).total_seconds() * 1000)
    by_identity = defaultdict(list)
    for t in tabs:
        if t.get('url_id'):
            by_identity[t['url_id']].append(t)
    duplicate_sets = [ts for ts in by_identity.values() if len(ts) > 1]
    candidates, kept_of = [], {}
    for ts in duplicate_sets:
        prot = [t for t in ts if protected(t)]
        keep = prot[0] if prot else max(ts, key=lambda t: (t.get('last_accessed_ms') is not None, t.get('last_accessed_ms') or 0, -t['index']))
        for t in ts:
            if t is not keep and not protected(t):
                candidates.append(t)
                kept_of[id(t)] = keep
    cand_ids = {id(t) for t in candidates}
    stale = [t for t in tabs if not protected(t) and t.get('last_accessed_ms') is not None
             and exported_ms - t['last_accessed_ms'] > stale_days * DAY_MS and id(t) not in cand_ids]
    shown = defaultdict(list)
    for t in tabs:
        if t['url']:
            shown[t['url']].append(t)
    lines = ['# Cleanup proposal', '',
             'Proposal only. Nothing was closed. Pinned and audible tabs are never listed.',
             'This is a review list, not a backup: addresses here have no query string or fragment, so a closed tab cannot be restored from this file.',
             'Duplicates are decided from the full original address (kept only as a short hash), not from the shortened address shown here.', '',
             '## Duplicates (%d extra tabs)' % len(candidates), '']
    for t in candidates:
        lines.append('- close candidate: %s "%s" %s, same page as %s, which stays' % (where(t), md_text(t['title']), md_url(t['url']), where(kept_of[id(t)])))
    mixed = []
    for u, ts in shown.items():
        if len(ts) > 1:
            ids = {t.get('url_id') for t in ts}
            if None in ids or len(ids) > 1:
                mixed.append((u, ts, ids))
    lines += ['', '## Same shown address, different or unknown pages (not duplicates, not proposed)', '']
    for u, ts, ids in mixed:
        known = len({i for i in ids if i})
        lines.append('- %s: %d tabs show it; %s' % (md_url(u), len(ts), ('they are %d different pages' % known) if None not in ids else 'identity is unknown for some of them'))
    lines += ['', '## Not used for more than %d days (%d tabs)' % (stale_days, len(stale)), '']
    for t in stale:
        days = (exported_ms - t['last_accessed_ms']) // DAY_MS
        lines.append('- %s "%s" %s, not used for %d days' % (where(t), md_text(t['title']), md_url(t['url']), days))
    return '\n'.join(lines).rstrip('\n') + '\n', {'duplicates_extra': len(candidates), 'stale': len(stale)}
