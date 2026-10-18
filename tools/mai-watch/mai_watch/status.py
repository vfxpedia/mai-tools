"""Runtime validator for status documents v1 (DESIGN.md section 4). Standard library only.

The JSON Schema in schema/status.v1.schema.json is the contract. This validator must agree with it on every example;
the contract test checks that. Unknown fields are ignored (forward compatibility).
"""
import datetime
import math
import re

ID_RE = re.compile(r'^[A-Za-z0-9._-]{1,128}$')
TIME_RE = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?Z$')
KINDS = ('job', 'service')
STATES = ('running', 'waiting', 'blocked', 'done', 'failed')
TERMINAL = ('done', 'failed')
SECRET_WORDS = ('password', 'passwd', 'secret', 'token', 'apikey', 'api_key', 'credential')


def is_number(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:      # an integer too large for a float is not a usable number (M02)
        return False


def parse_time(s):
    """RFC 3339 UTC (suffix Z) to a naive UTC datetime. Raises ValueError for anything else."""
    if not isinstance(s, str) or not TIME_RE.match(s):
        raise ValueError('not an RFC 3339 UTC time: %r' % (s,))
    base, _, frac = s[:-1].partition('.')
    t = datetime.datetime.strptime(base, '%Y-%m-%dT%H:%M:%S')
    if frac:
        t = t.replace(microsecond=int((frac + '000000')[:6]))
    return t


def format_time(t):
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


def validate(doc):
    """Returns a list of problem strings. Empty means valid. Never raises: a malformed document is a problem, not a crash."""
    try:
        return _validate(doc)
    except (OverflowError, ValueError, TypeError, KeyError) as e:
        return ['malformed document: %s' % e]


def _validate(doc):
    if not isinstance(doc, dict):
        return ['document is not a JSON object']
    out = []
    for k in ('schema_version', 'id', 'kind', 'state', 'updated_at', 'heartbeat_interval_s', 'device_uuids'):
        if k not in doc:
            out.append('missing required field %s' % k)
    if out:
        return out
    if doc['schema_version'] != 1 or isinstance(doc['schema_version'], bool):
        out.append('schema_version must be 1')
    if not isinstance(doc['id'], str) or not ID_RE.match(doc['id']):
        out.append('id must match [A-Za-z0-9._-]{1,128}')
    if doc['kind'] not in KINDS:
        out.append('kind must be job or service')
    if doc['state'] not in STATES:
        out.append('state must be one of %s' % ', '.join(STATES))
    for k in ('updated_at', 'started_at', 'deadline'):
        if k in doc:
            try:
                parse_time(doc[k])           # a real calendar time, not only the right shape (W5)
            except ValueError:
                out.append('%s must be a real RFC 3339 UTC time (suffix Z)' % k)
    if not is_number(doc['heartbeat_interval_s']) or doc['heartbeat_interval_s'] <= 0:
        out.append('heartbeat_interval_s must be a number greater than 0')
    du = doc['device_uuids']
    if not isinstance(du, list) or not all(isinstance(x, str) and x for x in du) or len(set(du)) != len(du):
        out.append('device_uuids must be an array of unique non-empty strings')
    if 'hold_reason' in doc and (not isinstance(doc['hold_reason'], str) or not doc['hold_reason']):
        out.append('hold_reason must be a non-empty string')
    if doc['state'] in ('waiting', 'blocked') and 'hold_reason' not in doc:
        out.append('hold_reason is required when state is waiting or blocked')
    if 'progress' in doc:
        p = doc['progress']
        if not (isinstance(p, dict) and is_number(p.get('done')) and is_number(p.get('total')) and p['done'] >= 0 and p['total'] >= 0):
            out.append('progress needs numeric done and total, both >= 0')
    if 'labels' in doc:
        lb = doc['labels']
        if not (isinstance(lb, dict) and all(isinstance(v, str) for v in lb.values())):
            out.append('labels must map strings to strings')
    if 'artifacts' in doc:
        a = doc['artifacts']
        if not (isinstance(a, list) and all(isinstance(x, str) and x for x in a)):
            out.append('artifacts must be an array of non-empty path strings')
    return out


def secret_like_fields(doc):
    """Names that look like secrets. A warning only; the tool never reads credentials."""
    found = []

    def walk(o, prefix=''):
        if isinstance(o, dict):
            for k, v in o.items():
                if any(w in str(k).lower() for w in SECRET_WORDS):
                    found.append(prefix + str(k))
                walk(v, prefix + str(k) + '.')
    walk(doc)
    return found


def is_stale(now, updated_at, heartbeat_interval_s, factor):
    """Stale when now - updated_at > factor * heartbeat_interval_s (DESIGN.md section 4)."""
    return (now - updated_at).total_seconds() > factor * heartbeat_interval_s
