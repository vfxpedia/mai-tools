#!/usr/bin/env python3
"""mai-approve: owner-run standing approval with expiry for unattended runs (M1, hardened after independent review A1 to A6).

The owner types `grant` in his own shell. A launcher calls `receipt` right before it starts a run: `receipt` re-checks everything and
reserves the run under a store-wide lock, so two launchers cannot both take the last allowed run. `check` is an advisory read of the
same rules (add --inquiry when you only want to know whether an approval is live). Standard library only; same on Windows, Linux, macOS.

Exit codes of `check`, `receipt` and `finish`: 0 allowed, 2 refused (reason on stderr and one JSON line on stdout).
Honest limits: this is a coordination and audit mechanism, not a security boundary against a process of the same OS user. The audit hash
chain detects an edited or removed line inside the log; it cannot detect that the last lines were cut off unless the owner has recorded
the head hash elsewhere (`audit-head`, then `audit-verify --expect-head`).
"""
import argparse
import contextlib
import datetime
import getpass
import hashlib
import json
import os
import re
import socket
import sys
import time

SCHEMA = 'mai-approve-approval-v1'
RECEIPT_SCHEMA = 'mai-approve-receipt-v1'
# ids used before the naming rule (2026-10-18); files written with them are still read, new files never use them
LEGACY_SCHEMAS = {'mai-approval-v1'}
LEGACY_RECEIPT_SCHEMAS = {'mai-run-receipt-v1'}
TS_RE = re.compile('^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$')
NAME_RE = re.compile('^[a-z0-9][a-z0-9._-]{0,63}$')
RUN_ID_RE = re.compile('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
SHA_RE = re.compile('^[0-9a-f]{64}$')
EXCLUSIONS = ['paid_or_external_resource', 'data_deletion', 'kill_foreign_process',
              'system_or_security_setting', 'external_send', 'out_of_scope_experiment']
MAX_DAYS = 31
DEFAULT_DAYS = 7
ATTEMPT_KINDS = ['normal', 'canary_retry']
RECEIPT_STATUS = ['started', 'ended', 'failed', 'aborted']
LOCK_TIMEOUT_S = 15
LOCK_STALE_S = 120

APPROVAL_KEYS = {'schema', 'scope', 'granted_at', 'valid_until', 'granted_by', 'method', 'eula', 'execution_mode', 'limits', 'exclusions', 'note', 'sha256'}
LIMIT_KEYS = {'allowed_paths', 'devices', 'max_runs_per_unit', 'canary_retries', 'count_per'}
RECEIPT_KEYS = {'schema', 'run_id', 'experiment_unit_id', 'attempt_kind', 'approval_sha256', 'started_at', 'ended_at', 'status', 'note'}


class Refused(Exception):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code
        self.text = text


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)


def fmt(t):
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_ts(s):
    if not isinstance(s, str) or not TS_RE.fullmatch(s):
        raise Refused('bad_time', 'time must be a full UTC timestamp like 2026-10-24T14:59:00Z, got %r. A date alone is refused on purpose: it would silently become UTC midnight.' % (s,))
    try:
        return datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        raise Refused('bad_time', 'not a real calendar time: %r' % (s,))


def canon_hash(doc):
    d = {k: v for k, v in doc.items() if k != 'sha256'}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()


def store_dir(arg=None):
    d = arg or os.environ.get('MAI_APPROVE_DIR') or os.path.join(os.path.expanduser('~'), '.mai', 'approvals')
    os.makedirs(d, exist_ok=True)
    return d


def approval_path(d, scope):
    if not isinstance(scope, str) or not NAME_RE.fullmatch(scope):
        raise Refused('bad_scope', 'scope must match %s, got %r' % (NAME_RE.pattern, scope))
    return os.path.join(d, scope + '.json')


def write_json(path, doc):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, path)


# ---------- store-wide lock (A2) ----------

@contextlib.contextmanager
def store_lock(d):
    """One lock for every mutating command, so check, count, receipt and audit append happen as one step."""
    path = os.path.join(d, '.lock')
    deadline = time.time() + LOCK_TIMEOUT_S
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > LOCK_STALE_S:
                    os.remove(path)
                    continue
            except OSError:
                continue
            if time.time() > deadline:
                raise Refused('busy', 'another mai-approve command holds %s. Remove it only if you know it is dead.' % path)
            time.sleep(0.02)
    try:
        yield
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ---------- audit log (append-only, hash chain) ----------

def audit_path(d):
    return os.path.join(d, 'audit.log')


def audit_last_hash(d):
    p = audit_path(d)
    if not os.path.exists(p):
        return '0' * 64
    last = None
    with open(p, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                last = line
    return json.loads(last)['hash'] if last else '0' * 64


def audit_append(d, action, scope, approval_sha, now, detail=''):
    rec = {'ts': fmt(now), 'action': action, 'scope': scope, 'approval_sha256': approval_sha, 'detail': detail, 'prev': audit_last_hash(d)}
    rec['hash'] = hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
    with open(audit_path(d), 'a', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def audit_verify(d, expect_head=None):
    """Returns (lines, head, problem). Detects an edited or removed line inside the log; a cut-off tail only against expect_head."""
    p = audit_path(d)
    prev, n = '0' * 64, 0
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                rec = json.loads(line)
                h = rec.pop('hash')
                if rec.get('prev') != prev:
                    return n, prev, 'line %d: prev hash does not match the line before it (a line was removed or reordered)' % i
                if hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest() != h:
                    return n, prev, 'line %d: content does not match its hash (the line was edited)' % i
                prev, n = h, n + 1
    if expect_head is not None and expect_head != prev:
        return n, prev, 'head hash %s does not match the expected %s (lines were cut off or added)' % (prev, expect_head)
    return n, prev, None


# ---------- validation (A4): same contract as schema/approval.v1.schema.json ----------

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_str(v):
    return isinstance(v, str) and len(v) > 0


def validate(doc):
    """Problem strings; empty means valid. Never raises: a malformed document is a refusal, not a traceback."""
    try:
        return _validate(doc)
    except Refused as e:
        return [e.text]
    except (TypeError, KeyError, AttributeError, ValueError) as e:
        return ['malformed document: %s' % e]


def _validate(doc):
    if not isinstance(doc, dict):
        return ['document is not a JSON object']
    out = []
    for k in ('schema', 'scope', 'granted_at', 'valid_until', 'granted_by', 'method', 'eula', 'execution_mode', 'limits', 'exclusions', 'sha256'):
        if k not in doc:
            out.append('missing ' + k)
    if out:
        return out
    for k in doc:
        if k not in APPROVAL_KEYS:
            out.append('unknown field ' + k)
    if doc['schema'] != SCHEMA and doc['schema'] not in LEGACY_SCHEMAS:
        out.append('schema must be %s' % SCHEMA)
    if not isinstance(doc['scope'], str) or not NAME_RE.fullmatch(doc['scope']):
        out.append('scope must match %s' % NAME_RE.pattern)
    gb = doc['granted_by']
    if not (isinstance(gb, dict) and set(gb) == {'os_user', 'host'} and is_str(gb['os_user']) and is_str(gb['host'])):
        out.append('granted_by must be exactly os_user and host, both non-empty strings')
    if doc['method'] != 'owner-run mai-approve':
        out.append('method must be owner-run mai-approve')
    e = doc['eula']
    if not (isinstance(e, dict) and set(e) == {'accepted', 'license', 'subject', 'consent_source'} and e['accepted'] is True
            and is_str(e['license']) and is_str(e['subject']) and is_str(e['consent_source'])):
        out.append('eula must be exactly accepted=true, license, subject, consent_source (non-empty strings)')
    if doc['execution_mode'] not in ('attended', 'unattended'):
        out.append('execution_mode must be attended or unattended')
    lim = doc['limits']
    if not isinstance(lim, dict):
        out.append('limits must be an object')
    else:
        for k in lim:
            if k not in LIMIT_KEYS:
                out.append('unknown limits field ' + k)
        ap = lim.get('allowed_paths')
        if not (isinstance(ap, list) and ap and all(is_str(x) for x in ap)):
            out.append('limits.allowed_paths must be a non-empty array of non-empty strings')
        if 'devices' in lim and not (isinstance(lim['devices'], list) and all(is_str(x) for x in lim['devices'])):
            out.append('limits.devices must be an array of non-empty strings')
        if not (is_int(lim.get('max_runs_per_unit')) and lim['max_runs_per_unit'] >= 1):
            out.append('limits.max_runs_per_unit must be an integer >= 1')
        if 'canary_retries' in lim and not (is_int(lim['canary_retries']) and lim['canary_retries'] >= 0):
            out.append('limits.canary_retries must be an integer >= 0')
        if lim.get('count_per') != 'experiment_unit_id':
            out.append('limits.count_per must be experiment_unit_id')
    ex = doc['exclusions']
    if not (isinstance(ex, list) and ex and len(set(map(str, ex))) == len(ex) and all(x in EXCLUSIONS for x in ex)):
        out.append('exclusions must be a non-empty array of unique known categories')
    if 'note' in doc and not isinstance(doc['note'], str):
        out.append('note must be a string')
    if not (isinstance(doc['sha256'], str) and SHA_RE.fullmatch(doc['sha256'])):
        out.append('sha256 must be 64 lowercase hex characters')
    try:
        g, v = parse_ts(doc['granted_at']), parse_ts(doc['valid_until'])
        if v <= g:
            out.append('valid_until is not after granted_at')
        elif v - g > datetime.timedelta(days=MAX_DAYS):
            out.append('window is longer than %d days' % MAX_DAYS)
    except Refused as r:
        out.append(r.text)
    if not out and canon_hash(doc) != doc['sha256']:
        out.append('sha256 does not match the content (the file was edited after grant)')
    return out


def validate_receipt(rec, filename):
    if not isinstance(rec, dict):
        return ['receipt is not a JSON object']
    out = []
    for k in ('schema', 'run_id', 'experiment_unit_id', 'attempt_kind', 'approval_sha256', 'started_at'):
        if k not in rec:
            out.append('missing ' + k)
    if out:
        return out
    for k in rec:
        if k not in RECEIPT_KEYS:
            out.append('unknown field ' + k)
    if rec['schema'] != RECEIPT_SCHEMA and rec['schema'] not in LEGACY_RECEIPT_SCHEMAS:
        out.append('schema must be %s' % RECEIPT_SCHEMA)
    if not (isinstance(rec['run_id'], str) and RUN_ID_RE.fullmatch(rec['run_id'])):
        out.append('run_id is not a valid id')
    elif rec['run_id'] + '.json' != filename:
        out.append('run_id %r does not match the file name %r' % (rec['run_id'], filename))
    if not (isinstance(rec['experiment_unit_id'], str) and NAME_RE.fullmatch(rec['experiment_unit_id'])):
        out.append('experiment_unit_id is not a valid id')
    if rec['attempt_kind'] not in ATTEMPT_KINDS:
        out.append('attempt_kind must be one of %s' % ATTEMPT_KINDS)
    if not (isinstance(rec['approval_sha256'], str) and SHA_RE.fullmatch(rec['approval_sha256'])):
        out.append('approval_sha256 must be 64 lowercase hex characters')
    for k in ('started_at', 'ended_at'):
        if k in rec:
            try:
                parse_ts(rec[k])
            except Refused:
                out.append('%s is not a valid UTC time' % k)
    if 'status' in rec and rec['status'] not in RECEIPT_STATUS:
        out.append('status must be one of %s' % RECEIPT_STATUS)
    return out


def load_approval(d, scope):
    p = approval_path(d, scope)
    if not os.path.exists(p):
        raise Refused('missing', 'no approval for scope %r (expected %s)' % (scope, p))
    try:
        with open(p, encoding='utf-8') as f:
            doc = json.load(f)
    except Exception as e:
        raise Refused('unreadable', 'approval file is not valid JSON: %s' % e)
    problems = validate(doc)
    if problems:
        raise Refused('invalid', 'approval is not valid: ' + '; '.join(problems))
    return doc


# ---------- grant, extend, revoke, show ----------

def build(scope, granted_at, valid_until, args):
    doc = {
        'schema': SCHEMA, 'scope': scope, 'granted_at': fmt(granted_at), 'valid_until': fmt(valid_until),
        'granted_by': {'os_user': getpass.getuser(), 'host': socket.gethostname()},
        'method': 'owner-run mai-approve',
        'eula': {'accepted': True, 'license': args.eula_license, 'subject': args.eula_subject, 'consent_source': args.eula_source},
        'execution_mode': 'unattended' if args.unattended else 'attended',
        'limits': {'allowed_paths': [os.path.realpath(p).replace(os.sep, '/') for p in args.allowed_path],
                   'max_runs_per_unit': args.runs_per_unit, 'canary_retries': args.canary_retries, 'count_per': 'experiment_unit_id'},
        'exclusions': sorted(set(args.exclude or EXCLUSIONS)),
    }
    if args.device:
        doc['limits']['devices'] = args.device
    if args.note:
        doc['note'] = args.note
    doc['sha256'] = canon_hash(doc)
    return doc


def cmd_grant(args, now):
    d = store_dir(args.dir)
    p = approval_path(d, args.scope)
    if not args.eula_accept:
        raise Refused('eula', 'grant needs --eula-accept: the owner states the license acceptance himself (with --eula-license, --eula-subject, --eula-source)')
    with store_lock(d):
        if os.path.exists(p):
            try:
                cur = load_approval(d, args.scope)
                if parse_ts(cur['valid_until']) > now:
                    raise Refused('exists', 'scope %r already has a live approval until %s. Use extend or revoke first.' % (args.scope, cur['valid_until']))
            except Refused as e:
                if e.code == 'exists':
                    raise
        valid_until = parse_ts(args.until) if args.until else now + datetime.timedelta(days=args.days)
        doc = build(args.scope, now, valid_until, args)
        problems = validate(doc)
        if problems:
            raise Refused('invalid', '; '.join(problems))
        write_json(p, doc)
        audit_append(d, 'grant', args.scope, doc['sha256'], now, 'until ' + doc['valid_until'])
    return {'ok': True, 'scope': args.scope, 'valid_until': doc['valid_until'], 'sha256': doc['sha256'], 'file': p}


def cmd_extend(args, now):
    d = store_dir(args.dir)
    with store_lock(d):
        cur = load_approval(d, args.scope)
        doc = {k: v for k, v in cur.items() if k != 'sha256'}
        doc['granted_at'] = fmt(now)
        doc['valid_until'] = fmt(parse_ts(args.until))
        doc['sha256'] = canon_hash(doc)
        problems = validate(doc)
        if problems:
            raise Refused('invalid', '; '.join(problems))
        write_json(approval_path(d, args.scope), doc)
        audit_append(d, 'extend', args.scope, doc['sha256'], now, 'until %s (was %s)' % (doc['valid_until'], cur['valid_until']))
    return {'ok': True, 'scope': args.scope, 'valid_until': doc['valid_until'], 'sha256': doc['sha256'],
            'note': 'run counts are kept per experiment_unit_id and are not reset by extend'}


def cmd_revoke(args, now):
    d = store_dir(args.dir)
    p = approval_path(d, args.scope)
    with store_lock(d):
        if not os.path.exists(p):
            raise Refused('missing', 'no approval for scope %r' % args.scope)
        try:
            with open(p, encoding='utf-8') as f:
                sha = json.load(f).get('sha256', '')
        except Exception:
            sha = ''
        dest = os.path.join(d, '%s.revoked.%s.json' % (args.scope, now.strftime('%Y%m%dT%H%M%SZ')))
        os.replace(p, dest)
        audit_append(d, 'revoke', args.scope, sha, now, 'moved to ' + os.path.basename(dest))
    return {'ok': True, 'scope': args.scope, 'revoked_copy': dest}


def cmd_show(args, now):
    d = store_dir(args.dir)
    doc = dict(load_approval(d, args.scope))
    left = parse_ts(doc['valid_until']) - now
    doc['_status'] = 'expired' if left.total_seconds() <= 0 else 'live, %.1f hours left' % (left.total_seconds() / 3600)
    return doc


# ---------- receipts, counts, check ----------

def receipts_dir(d, scope):
    r = os.path.join(d, 'receipts', scope)
    os.makedirs(r, exist_ok=True)
    return r


def count_attempts(d, scope, unit):
    """Counts per experiment_unit_id across all approvals of the scope. A receipt that cannot be read or fails its contract stops the count
    with a refusal: an unreadable record must never be read as zero runs (A3)."""
    n = {'normal': 0, 'canary_retry': 0}
    r = receipts_dir(d, scope)
    for name in sorted(os.listdir(r)):
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(r, name), encoding='utf-8') as f:
                rec = json.load(f)
        except Exception as e:
            raise Refused('receipt_corrupt', 'receipt %s cannot be read: %s. Counting stopped; fix or move the file on purpose.' % (name, e))
        problems = validate_receipt(rec, name)
        if problems:
            raise Refused('receipt_corrupt', 'receipt %s fails its contract: %s. Counting stopped.' % (name, '; '.join(problems)))
        if rec['experiment_unit_id'] == unit:
            n[rec['attempt_kind']] += 1
    return n


def real(p):
    return os.path.normcase(os.path.realpath(p)).replace(os.sep, '/').rstrip('/')


def foreign_notation(p):
    """True when p is written the way another OS writes absolute paths (A7). An approval or a request in that notation would otherwise be read as a relative
    path under the current folder and could match for the wrong reason. Windows hosts refuse a rooted POSIX path, POSIX hosts refuse a drive or UNC path."""
    if os.name == 'nt':
        return p.startswith('/') and not p.startswith('//')
    return bool(re.match(r'^[A-Za-z]:', p)) or p.startswith('\\\\')


def inside(path, allowed):
    """Containment on resolved paths: symlinks and junctions are followed, so a link inside an allowed folder to outside is refused (A5).
    Relative request paths are resolved against the current directory of the caller."""
    p = real(path)
    for a in allowed:
        q = real(a)
        if p == q or p.startswith(q + '/'):
            return True
    return False


def evaluate(args, now, d, write_receipt=False):
    doc = load_approval(d, args.scope)
    if parse_ts(doc['valid_until']) <= now:
        raise Refused('expired', 'approval expired at %s (now %s)' % (doc['valid_until'], fmt(now)))
    if args.unattended and doc['execution_mode'] != 'unattended':
        raise Refused('mode', 'this approval does not allow unattended execution')
    out = {'ok': True, 'scope': args.scope, 'approval_sha256': doc['sha256'], 'valid_until': doc['valid_until']}
    if args.inquiry and not write_receipt:
        return out, doc
    # a real run request must say what it will do: the contract is checked against the request, never against nothing (A5)
    if not args.path:
        raise Refused('path_required', 'a run request needs at least one --path (use --inquiry to only ask whether the approval is live)')
    if not args.experiment_unit:
        raise Refused('unit_required', 'a run request needs --experiment-unit')
    for a in args.action or []:
        if a not in EXCLUSIONS:
            raise Refused('unknown_action', 'action %r is not a known category. Known: %s' % (a, ', '.join(EXCLUSIONS)))
        if a in doc['exclusions']:
            raise Refused('excluded', 'action %r is excluded: it always asks the owner' % a)
    allowed_devices = doc['limits'].get('devices')
    if allowed_devices:
        if not args.device:
            raise Refused('device_required', 'this approval limits devices; pass every device the run will use with --device')
        for dv in args.device:
            if dv not in allowed_devices:
                raise Refused('device', 'device %r is not in the approved devices' % dv)
    for a in doc['limits']['allowed_paths']:
        if foreign_notation(a):
            raise Refused('foreign_path_notation', 'allowed path %r is written for another operating system. The owner must grant again on this machine; an approval is not moved between systems' % a)
    for p in args.path:
        if foreign_notation(p):
            raise Refused('foreign_path_notation', 'request path %r is written for another operating system' % p)
    for p in args.path:
        if not inside(p, doc['limits']['allowed_paths']):
            raise Refused('path', 'path %r (resolved: %s) is outside allowed_paths' % (p, os.path.realpath(p)))
    if args.attempt_kind not in ATTEMPT_KINDS:
        raise Refused('attempt_kind', 'attempt kind must be one of %s' % ATTEMPT_KINDS)
    if not NAME_RE.fullmatch(args.experiment_unit):
        raise Refused('bad_unit', 'experiment unit id must match %s' % NAME_RE.pattern)
    n = count_attempts(d, args.scope, args.experiment_unit)
    lim = doc['limits']
    if args.attempt_kind == 'normal' and n['normal'] >= lim['max_runs_per_unit']:
        raise Refused('runs_exhausted', 'unit %r already used %d of %d normal runs' % (args.experiment_unit, n['normal'], lim['max_runs_per_unit']))
    if args.attempt_kind == 'canary_retry' and n['canary_retry'] >= lim.get('canary_retries', 0):
        raise Refused('canary_exhausted', 'unit %r already used %d of %d canary retries' % (args.experiment_unit, n['canary_retry'], lim.get('canary_retries', 0)))
    out['counts_before'] = n
    if write_receipt:
        if not isinstance(args.run_id, str) or not RUN_ID_RE.fullmatch(args.run_id):
            raise Refused('run_id', 'run id must match %s (no path separators, no ..)' % RUN_ID_RE.pattern)
        rdir = receipts_dir(d, args.scope)
        rp = os.path.join(rdir, args.run_id + '.json')
        if os.path.dirname(os.path.realpath(rp)) != os.path.realpath(rdir):
            raise Refused('run_id', 'receipt path would leave the receipt folder')
        if os.path.exists(rp):
            raise Refused('run_id_used', 'run id %r already has a receipt. A new run id never resets a count, so reuse is an error.' % args.run_id)
        rec = {'schema': RECEIPT_SCHEMA, 'run_id': args.run_id, 'experiment_unit_id': args.experiment_unit, 'attempt_kind': args.attempt_kind,
               'approval_sha256': doc['sha256'], 'started_at': fmt(now), 'status': 'started'}
        write_json(rp, rec)
        audit_append(d, 'receipt', args.scope, doc['sha256'], now, '%s %s %s' % (args.experiment_unit, args.attempt_kind, args.run_id))
        out['receipt'] = rp
    return out, doc


def cmd_check(args, now):
    d = store_dir(args.dir)
    return evaluate(args, now, d)[0]


def cmd_receipt(args, now):
    d = store_dir(args.dir)
    with store_lock(d):
        return evaluate(args, now, d, write_receipt=True)[0]


def cmd_finish(args, now):
    """Marks how a run ended. It never changes the counts: every started attempt counts, whatever its end."""
    d = store_dir(args.dir)
    if not isinstance(args.run_id, str) or not RUN_ID_RE.fullmatch(args.run_id):
        raise Refused('run_id', 'run id must match %s' % RUN_ID_RE.pattern)
    with store_lock(d):
        rdir = receipts_dir(d, args.scope)
        rp = os.path.join(rdir, args.run_id + '.json')
        if not os.path.exists(rp):
            raise Refused('missing', 'no receipt for run id %r' % args.run_id)
        with open(rp, encoding='utf-8') as f:
            rec = json.load(f)
        problems = validate_receipt(rec, args.run_id + '.json')
        if problems:
            raise Refused('receipt_corrupt', '; '.join(problems))
        rec['status'] = args.status
        rec['ended_at'] = fmt(now)
        write_json(rp, rec)
        audit_append(d, 'finish', args.scope, rec['approval_sha256'], now, '%s %s' % (args.run_id, args.status))
    return {'ok': True, 'run_id': args.run_id, 'status': args.status}


def cmd_audit_verify(args, now):
    n, head, problem = audit_verify(store_dir(args.dir), args.expect_head)
    if problem:
        raise Refused('audit', problem)
    return {'ok': True, 'lines': n, 'head': head}


def cmd_audit_head(args, now):
    n, head, problem = audit_verify(store_dir(args.dir))
    if problem:
        raise Refused('audit', problem)
    return {'ok': True, 'lines': n, 'head': head, 'note': 'record this hash somewhere the same OS user cannot rewrite, then audit-verify --expect-head'}


def main(argv=None):
    ap = argparse.ArgumentParser(prog='mai-approve', description=__doc__.split('\n')[0])
    ap.add_argument('--dir', help='approval store (default ~/.mai/approvals, or MAI_APPROVE_DIR)')
    ap.add_argument('--now', help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest='cmd', required=True)
    g = sub.add_parser('grant', help='owner writes a standing approval')
    g.add_argument('--scope', required=True)
    g.add_argument('--until', help='full UTC timestamp, e.g. 2026-10-24T14:59:00Z')
    g.add_argument('--days', type=int, default=DEFAULT_DAYS, help='used only when --until is absent (default 7, max 31)')
    g.add_argument('--allowed-path', action='append', required=True)
    g.add_argument('--device', action='append')
    g.add_argument('--runs-per-unit', type=int, default=1)
    g.add_argument('--canary-retries', type=int, default=0)
    g.add_argument('--exclude', action='append', choices=EXCLUSIONS, help='default: all six')
    g.add_argument('--unattended', action='store_true', help='allow unattended execution')
    g.add_argument('--eula-accept', action='store_true')
    g.add_argument('--eula-license', default='')
    g.add_argument('--eula-subject', default='')
    g.add_argument('--eula-source', default='')
    g.add_argument('--note', default='')
    e = sub.add_parser('extend'); e.add_argument('--scope', required=True); e.add_argument('--until', required=True)
    r = sub.add_parser('revoke'); r.add_argument('--scope', required=True)
    s = sub.add_parser('show'); s.add_argument('--scope', required=True)
    for name, helptext in (('check', 'advisory read of the rules; exit 0 allowed, 2 refused'), ('receipt', 'reserve a run under the lock and write its receipt; launchers call this right before starting')):
        c = sub.add_parser(name, help=helptext)
        c.add_argument('--scope', required=True)
        c.add_argument('--path', action='append', help='every path the run will touch (required unless --inquiry)')
        c.add_argument('--device', action='append', help='every device the run will use (required when the approval limits devices)')
        c.add_argument('--action', action='append', help='every excluded-category action the run involves, if any')
        c.add_argument('--unattended', action='store_true')
        c.add_argument('--inquiry', action='store_true', help='only ask whether the approval is live (check only)')
        c.add_argument('--experiment-unit')
        c.add_argument('--attempt-kind', default='normal')
        c.add_argument('--run-id')
    f = sub.add_parser('finish', help='mark how a run ended; counts are unchanged')
    f.add_argument('--scope', required=True); f.add_argument('--run-id', required=True); f.add_argument('--status', required=True, choices=RECEIPT_STATUS[1:])
    av = sub.add_parser('audit-verify'); av.add_argument('--expect-head')
    sub.add_parser('audit-head')
    args = ap.parse_args(argv)
    try:
        now = parse_ts(args.now) if args.now else now_utc()
        if args.cmd == 'grant':
            for k in ('eula_license', 'eula_subject', 'eula_source'):
                if args.eula_accept and not getattr(args, k):
                    raise Refused('eula', 'grant needs --%s: the acceptance must name its license, subject and source, not be implied' % k.replace('_', '-'))
        fn = {'grant': cmd_grant, 'extend': cmd_extend, 'revoke': cmd_revoke, 'show': cmd_show, 'check': cmd_check, 'receipt': cmd_receipt,
              'finish': cmd_finish, 'audit-verify': cmd_audit_verify, 'audit-head': cmd_audit_head}[args.cmd]
        out = fn(args, now)
    except Refused as ex:
        print(json.dumps({'ok': False, 'reason': ex.code, 'text': ex.text}, ensure_ascii=False))
        print('mai-approve refused (%s): %s' % (ex.code, ex.text), file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
