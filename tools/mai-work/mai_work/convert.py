"""Move an eight-column WORKLIST.tsv into WORK.tsv + WORK-events.tsv without losing a cell, and prove it.

Every legacy column has one place in the new row (schema.LEGACY_TO_WORK). The proof is a round trip: the legacy rows are rebuilt
from the new file and must equal the original, cell by cell. A status the converter does not know, a missing or extra column, or
a duplicate id stops the conversion instead of guessing.

New columns that the old list never had (stage, start_plan, after, decided_at, ...) are left empty, except `decided_at`, which is
`unknown` for rows whose state is a decision (cancelled): the check that comes with the tool flags those so the owner fills in
the real time from the original message instead of a guess.
"""
import csv
import datetime
import hashlib
import io
import os

from . import schema


class ConvertError(ValueError):
    pass


def read_tsv(path):
    """Plain TSV: a quote is an ordinary character (QUOTE_NONE), so a cell is exactly the text between two tabs."""
    with open(path, encoding='utf-8', newline='') as f:
        text = f.read()
    reader = csv.DictReader(io.StringIO(text), delimiter='\t', quoting=csv.QUOTE_NONE)
    rows = list(reader)
    return text, tuple(reader.fieldnames or ()), rows


def tsv_text(columns, rows):
    lines = ['\t'.join(columns)]
    for r in rows:
        cells = [r.get(c, '') or '' for c in columns]
        for c, v in zip(columns, cells):
            if '\t' in v or '\n' in v or '\r' in v:
                raise ConvertError('%s: cell %s holds a tab or line break' % (r.get('id'), c))
        lines.append('\t'.join(cells))
    return '\n'.join(lines) + '\n'


def write_tsv(path, columns, rows):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(tsv_text(columns, rows))
    os.replace(tmp, path)


def legacy_extras(header):
    """Columns after the eight old ones, when each is a WORK.tsv column name (a list moving over one column at a time, 11/07:
    lead added `decision` and `decided_at`). None when the header is not the old list at all."""
    n = len(schema.LEGACY_COLUMNS)
    if tuple(header[:n]) != schema.LEGACY_COLUMNS:
        return None
    extra = tuple(header[n:])
    taken = set(schema.LEGACY_TO_WORK.values())
    if len(set(extra)) != len(extra) or any(c not in schema.WORK_COLUMNS or c in taken for c in extra):
        return None
    return extra


def convert_rows(header, rows, source_name, source_sha, now):
    extra = legacy_extras(header)
    if extra is None:
        raise ConvertError('columns are %s, expected %s (optionally followed by WORK.tsv column names)'
                           % (list(header), list(schema.LEGACY_COLUMNS)))
    seen, work, events = set(), [], []
    for n, r in enumerate(rows, 2):            # line 1 is the header
        if None in r or any(v is None for v in r.values()):
            raise ConvertError('line %d has a different number of cells' % n)
        if r['id'] in seen:
            raise ConvertError('line %d repeats id %s' % (n, r['id']))
        seen.add(r['id'])
        if r['status'] not in schema.LEGACY_STATUS:
            raise ConvertError('line %d (%s) has status %r, not one of %s' % (n, r['id'], r['status'], list(schema.LEGACY_STATUS)))
        new = dict.fromkeys(schema.WORK_COLUMNS, '')
        for old, col in schema.LEGACY_TO_WORK.items():
            new[col] = r[old]
        new['status'] = schema.LEGACY_STATUS[r['status']]
        for col in extra:
            new[col] = r[col]
        if new['status'] == 'cancelled' and not new['decided_at']:
            new['decided_at'] = 'unknown'
        work.append(new)
        events.append({'ts': now, 'decided_at': new['decided_at'], 'decided_by': '', 'id': r['id'], 'event': 'add',
                       'field': 'status', 'from': r['status'], 'to': new['status'],
                       'why': 'imported from %s line %d (sha256 %s)' % (source_name, n, source_sha[:16]),
                       'decision': '', 'by': 'mai-work convert'})
    return work, events


def back_to_legacy(work_rows, extra=()):
    reverse = {v: k for k, v in schema.LEGACY_STATUS.items()}
    out = []
    for w in work_rows:
        r = {old: w[col] for old, col in schema.LEGACY_TO_WORK.items()}
        r['status'] = reverse.get(w['status'], w['status'])
        for col in extra:
            # a cancelled row without a time was marked `unknown` by the converter; the original cell was empty
            r[col] = '' if col == 'decided_at' and w[col] == 'unknown' and w['status'] == 'cancelled' else w[col]
        out.append(r)
    return out


def round_trip(legacy_rows, work_rows, extra=()):
    """Differences between the original rows and the rows rebuilt from WORK.tsv: [] means no cell was lost or changed."""
    rebuilt = back_to_legacy(work_rows, extra)
    diffs = []
    if len(rebuilt) != len(legacy_rows):
        diffs.append(('*', 'rows', len(legacy_rows), len(rebuilt)))
    for a, b in zip(legacy_rows, rebuilt):
        for c in schema.LEGACY_COLUMNS + tuple(extra):
            if a.get(c) != b.get(c):
                diffs.append((a.get('id'), c, a.get(c), b.get(c)))
    return diffs


def report(source, source_sha, work, events, diffs, rebuilt_text_same):
    count = lambda col, v: sum(1 for w in work if w[col] == v)
    lines = [
        '# WORKLIST.tsv -> WORK.tsv conversion report', '',
        '- source: `%s` (sha256 %s)' % (source, source_sha),
        '- rows: %d · events: %d' % (len(work), len(events)),
        '- round trip: %s' % ('every cell of every row matches (0 differences)' if not diffs else '%d DIFFERENCES' % len(diffs)),
        '- rebuilt legacy text equals the original file byte for byte: %s' % ('yes' if rebuilt_text_same else 'no'),
        '', '## Where each old column went', '', '| old | new | note |', '|---|---|---|',
    ]
    notes = {'due': 'same value (`at:` / `iter:` / `-`)', 'status': 'open -> open · done -> done · dropped -> cancelled',
             'what': 'renamed'}
    for old, col in schema.LEGACY_TO_WORK.items():
        lines.append('| `%s` | `%s` | %s |' % (old, col, notes.get(old, 'same value')))
    added = [c for c in schema.WORK_COLUMNS if c not in schema.LEGACY_TO_WORK.values()]
    lines += ['', 'New columns, empty after conversion (to be filled by the list owner): ' + ' · '.join('`%s`' % c for c in added), '',
              '## States', '', '| new status | rows |', '|---|---:|']
    for s in schema.STATUSES:
        lines.append('| %s | %d |' % (s, count('status', s)))
    lines += ['', 'Rows with `decided_at = unknown` (cancelled; the check will ask for the real decision time): ' +
              (', '.join(w['id'] for w in work if w['decided_at'] == 'unknown') or 'none'), '',
              '## Row by row', '', '| id | old status | new status | end_plan | owner | evidence kept |', '|---|---|---|---|---|---|']
    old_status = {e['id']: e['from'] for e in events}
    for w in work:
        lines.append('| %s | %s | %s | `%s` | %s | %s |' % (w['id'], old_status[w['id']], w['status'], w['end_plan'], w['owner'],
                                                          'yes' if w['evidence'] else '(empty)'))
    if diffs:
        lines += ['', '## Differences', '', '| id | column | original | rebuilt |', '|---|---|---|---|']
        lines += ['| %s | %s | %s | %s |' % d for d in diffs]
    return '\n'.join(lines) + '\n'


def convert(source, out_dir, now=None):
    now = now or datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    text, header, rows = read_tsv(source)
    sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
    work, events = convert_rows(header, rows, os.path.basename(source), sha, now)
    os.makedirs(out_dir, exist_ok=True)
    work_path = os.path.join(out_dir, 'WORK.tsv')
    write_tsv(work_path, schema.WORK_COLUMNS, work)
    write_tsv(os.path.join(out_dir, 'WORK-events.tsv'), schema.EVENT_COLUMNS, events)
    _, _, written = read_tsv(work_path)                 # prove it from the file on disk, not from memory
    extra = legacy_extras(header)
    diffs = round_trip(rows, written, extra)
    same_text = tsv_text(schema.LEGACY_COLUMNS + extra, back_to_legacy(written, extra)) == text
    with open(os.path.join(out_dir, 'CONVERT-REPORT.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(report(source, sha, written, events, diffs, same_text))
    return {'rows': len(written), 'diffs': diffs, 'same_text': same_text, 'sha256': sha}
