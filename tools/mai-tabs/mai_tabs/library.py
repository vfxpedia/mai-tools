"""Tab library (DESIGN.md section 12): every page the browser had open, kept once per page, with the days it was open.

Unlike the v1 export, the library keeps addresses that can be opened again, so what it stores is decided here, before anything is written:
  - only http and https pages; user name and password in the address are dropped
  - query parameters that carry secrets (token, code, sig, key, session, ...) or look like a long random value are dropped,
    tracking parameters (utm_*, fbclid, ...) are dropped, the fragment is dropped
  - pages on deny-listed hosts (sign-in, mail, banks by default) and sign-in or password-reset paths are not stored at all
Two tabs are the same page when these cleaned addresses are equal, so a page opened three times is one item that says "3 tabs".

Files (under the data folder, default ~/.mai/tabs, or MAI_TABS_HOME):
  library.json   items by id, and for each local date the ids that were open that day
  live.json      the last tab list the extension reported (what is open now)
  commands.json  actions asked for from the page (open, sleep, close), their result and the memory measured before and after
Every write goes to a temporary file first and replaces the old one, so a crash never leaves half a file.
"""
import datetime
import hashlib
import json
import os
import re
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import classify

SCHEMA = 'mai-tabs-library-v1'
SECRET_PARAM = re.compile(r'(?i)^(access_?token|id_?token|refresh_?token|token|auth|authorization|code|state|nonce|sig|signature|key|'
                          r'api_?key|apikey|secret|client_secret|password|passwd|pwd|pass|session|session_?id|sid|ssid|otp|ticket|jwt|'
                          r'x-amz-.*|x-goog-.*|awsaccesskeyid|credential|hmac|hash|login_hint|email)$')
TRACKING_PARAM = re.compile(r'(?i)^(utm_.*|fbclid|gclid|dclid|msclkid|mc_eid|mc_cid|igshid|si|ref_src|ref_url|_hsenc|_hsmi|spm)$')
LONG_RANDOM = re.compile(r'^[A-Za-z0-9_\-.~%+/=]{40,}$')
SKIP_PATH = re.compile(r'(?i)/(oauth2?|signin|sign-in|login|logout|auth/|password|reset|verify-email|sso)(/|$|\?)')
DEFAULT_DENY = ('accounts.google.com', 'mail.google.com', 'myaccount.google.com', 'login.microsoftonline.com', 'login.live.com',
                'outlook.live.com', 'outlook.office.com', 'mail.naver.com', 'nid.naver.com', 'mail.daum.net', 'accounts.kakao.com',
                'paypal.com', 'kbstar.com', 'shinhan.com', 'wooribank.com', 'hanabank.com', 'ibk.co.kr', 'nonghyup.com', 'kakaobank.com',
                'toss.im', 'tossbank.com', 'citibank.co.kr', 'scfirstbank.com', 'kdb.co.kr', 'epostbank.go.kr', 'bank')
MAX_TITLE = 300
MAX_ITEMS = 20000
MAX_COMMANDS = 300
ACTIONS = ('open', 'sleep', 'close', 'dedupe')


def _host_denied(host, deny):
    host = host.lower().rstrip('.')
    for d in deny:
        d = d.lower().lstrip('.')
        if '.' not in d:                      # a bare word such as "bank" matches a label anywhere in the host
            if d in host.split('.') or any(label.endswith(d) for label in host.split('.')[:-1]):
                return True
        elif host == d or host.endswith('.' + d):
            return True
    return False


def clean_url(raw, deny=DEFAULT_DENY):
    """The address as the library keeps it, or None when the page is not stored. Never raises."""
    try:
        u = urlsplit(str(raw).strip())
        scheme = u.scheme.lower()
        if scheme not in ('http', 'https') or not u.hostname:
            return None
        host = u.hostname.lower()
        if _host_denied(host, deny) or SKIP_PATH.search(u.path + '?'):
            return None
        port = u.port
        netloc = ('[%s]' % host if ':' in host else host) + (':%d' % port if port and port != {'http': 80, 'https': 443}[scheme] else '')
        keep = []
        for k, v in parse_qsl(u.query, keep_blank_values=True):
            if SECRET_PARAM.match(k) or TRACKING_PARAM.match(k):
                continue
            if LONG_RANDOM.match(v) and re.search('[0-9]', v) and re.search('[A-Za-z]', v):
                continue
            keep.append((k, v))
        path = u.path or '/'
        return urlunsplit((scheme, netloc, path, urlencode(keep), ''))
    except (ValueError, KeyError, TypeError):
        return None


ARXIV_PATH = re.compile(r'(?i)^/(?:abs|pdf|html)/([0-9]{4}\.[0-9]{4,5}|[a-z\-]+/[0-9]{7})(?:v[0-9]+)?(?:\.pdf)?/?$')


def canonical(url):
    """Equality key: host without www, path without a trailing slash, query parameters in sorted order.
    An arXiv paper is one page whatever its version or format (abs, pdf, html, v1, v2)."""
    u = urlsplit(url)
    m = ARXIV_PATH.match(u.path) if (u.hostname or '').lower() in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org') else None
    if m:
        return 'https://arxiv.org/abs/' + m.group(1).lower()
    host = u.netloc[4:] if u.netloc.startswith('www.') else u.netloc
    path = u.path.rstrip('/') or '/'
    q = urlencode(sorted(parse_qsl(u.query, keep_blank_values=True)))
    return '%s://%s%s%s' % (u.scheme, host, path, ('?' + q) if q else '')


def item_id(canon):
    return hashlib.sha256(canon.encode('utf-8')).hexdigest()[:16]


ARXIV = re.compile(r'(?i)arxiv\.org/(?:abs|pdf|html)/([0-9]{4}\.[0-9]{4,5}|[a-z\-]+/[0-9]{7})(?:v[0-9]+)?')
DOI = re.compile(r'(?i)doi\.org/(10\.[0-9]{4,9}/\S+)')
GH = re.compile(r'(?i)^https?://github\.com/([^/]+)/([^/?#]+)(?:/(issues|pull|blob|tree|discussions|releases|actions|wiki)(?:/([^/?#]+))?)?')
YT = re.compile(r'(?i)^https?://(?:www\.|m\.)?(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/)([A-Za-z0-9_-]{6,})')
PAPER_HOSTS = ('arxiv.org', 'openreview.net', 'doi.org', 'semanticscholar.org', 'paperswithcode.com', 'ieeexplore.ieee.org',
               'dl.acm.org', 'sciencedirect.com', 'link.springer.com', 'nature.com', 'biorxiv.org', 'researchgate.net',
               'proceedings.mlr.press', 'proceedings.neurips.cc', 'openaccess.thecvf.com', 'aclanthology.org', 'scholar.google.com')


def describe(url, title, rules):
    """(category, one line saying what kind of page it is; the title is shown next to it, so the line does not repeat it).
    Rule-based from the address and the title only: no page content, no model, nothing sent anywhere."""
    host = (urlsplit(url).hostname or '').lower()
    bare = host[4:] if host.startswith('www.') else host
    t = re.sub(r'\s+', ' ', title or '').strip()
    paper = any(bare == h or bare.endswith('.' + h) for h in PAPER_HOSTS) or urlsplit(url).path.lower().endswith('.pdf')
    category = 'research' if paper else classify.classify(rules, url, t)
    m = ARXIV.search(url)
    if m:
        return 'research', '논문 · arXiv %s' % m.group(1)
    m = DOI.search(url)
    if m:
        return 'research', '논문 · DOI %s' % m.group(1)
    m = GH.match(url)
    if m:
        kind = {'issues': '이슈', 'pull': 'PR', 'blob': '파일', 'tree': '폴더', 'discussions': '토론', 'releases': '릴리스', 'actions': 'CI',
                'wiki': '위키'}.get((m.group(3) or '').lower(), '저장소')
        ref = (' #' + m.group(4)) if m.group(3) in ('issues', 'pull') and m.group(4) else ''
        return category, 'GitHub %s · %s/%s%s' % (kind, m.group(1), m.group(2), ref)
    if YT.match(url):
        return 'video and music', '영상 · ' + bare
    if paper and urlsplit(url).path.lower().endswith('.pdf'):
        return 'research', '논문 PDF · %s · %s' % (bare, urlsplit(url).path.rsplit('/', 1)[-1])
    if paper:
        return 'research', '논문 · ' + bare
    return category, bare + ((' · ' + urlsplit(url).path.strip('/').split('/')[0]) if urlsplit(url).path.strip('/') else '')


def local_date(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).date().isoformat()


class Library:
    def __init__(self, home=None, rules=None, deny=None, clock=time.time):
        self.home = os.path.abspath(os.path.expanduser(home or os.environ.get('MAI_TABS_HOME') or '~/.mai/tabs'))
        os.makedirs(self.home, exist_ok=True)
        self.rules = rules or classify.load_rules(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rules.default.json'))
        self.deny = tuple(deny) if deny is not None else self._load_deny()
        self.clock = clock
        self.lock = threading.RLock()
        self.lib = self._read('library.json', {'schema': SCHEMA, 'items': {}, 'days': {}})
        self.live = self._read('live.json', {'at': None, 'tabs': [], 'groups': []})
        self.cmds = self._read('commands.json', {'next': 1, 'commands': []})

    # files --------------------------------------------------------------------------------------------------------------------------
    def _load_deny(self):
        p = os.path.join(self.home, 'deny.txt')
        extra = []
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                extra = [ln.split('#', 1)[0].strip() for ln in f if ln.split('#', 1)[0].strip()]
        return DEFAULT_DENY + tuple(extra)

    def _read(self, name, default):
        p = os.path.join(self.home, name)
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else default
        except FileNotFoundError:
            return default
        except ValueError:                    # a broken file is kept aside, never silently overwritten
            os.replace(p, p + '.broken-%d' % int(self.clock()))
            return default

    def _write(self, name, data):
        p = os.path.join(self.home, name)
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp, p)

    # what the extension reports ---------------------------------------------------------------------------------------------------
    def sync(self, report):
        """report: {'tabs': [{id, windowId, url, title, discarded, active, pinned, audible, groupId, lastAccessed}], 'groups': [...]}
        Updates the live list and the library. Returns counts for the extension's own check."""
        now_ms = int(self.clock() * 1000)
        today = local_date(now_ms)
        tabs_in = report.get('tabs') if isinstance(report.get('tabs'), list) else []
        live, stored, skipped = [], 0, 0
        with self.lock:
            items, day = self.lib['items'], set(self.lib['days'].get(today, []))
            for t in tabs_in[:2000]:
                if not isinstance(t, dict):
                    continue
                url = clean_url(t.get('url') or t.get('pendingUrl') or '', self.deny)
                iid = None
                if url:
                    canon = canonical(url)
                    iid = item_id(canon)
                    title = str(t.get('title') or '')[:MAX_TITLE]
                    it = items.get(iid)
                    if it is None:
                        if len(items) >= MAX_ITEMS:
                            skipped += 1
                            continue
                        it = items[iid] = {'id': iid, 'url': url, 'title': title, 'first_seen': now_ms}
                    if title:
                        it['title'] = title           # the address stays the first one seen, so a duplicate never rewrites it
                    it['category'], it['line'] = describe(url, it['title'], self.rules)
                    it['last_seen'] = now_ms
                    day.add(iid)
                    stored += 1
                else:
                    skipped += 1
                gid = t.get('groupId')
                live.append({'tab': t.get('id'), 'window': t.get('windowId'), 'item': iid, 'discarded': bool(t.get('discarded')),
                             'active': bool(t.get('active')), 'pinned': bool(t.get('pinned')), 'audible': bool(t.get('audible')),
                             'group': gid if isinstance(gid, int) and gid >= 0 else None,
                             'last_accessed': t.get('lastAccessed') if isinstance(t.get('lastAccessed'), (int, float)) else None})
            self.lib['days'][today] = sorted(day)
            groups = [{'id': g.get('id'), 'title': str(g.get('title') or '')[:100], 'color': str(g.get('color') or '')}
                      for g in (report.get('groups') or []) if isinstance(g, dict)]
            self.live = {'at': now_ms, 'tabs': live, 'groups': groups}
            self._write('library.json', self.lib)
            self._write('live.json', self.live)
        return {'tabs': len(live), 'stored': stored, 'not_stored': skipped}

    # what the page shows -------------------------------------------------------------------------------------------------------------
    def view(self):
        with self.lock:
            open_tabs = {}
            for t in self.live['tabs']:
                if t['item']:
                    o = open_tabs.setdefault(t['item'], {'tabs': 0, 'awake': 0})
                    o['tabs'] += 1
                    o['awake'] += 0 if t['discarded'] else 1
            items = []
            for it in self.lib['items'].values():
                o = open_tabs.get(it['id'], {'tabs': 0, 'awake': 0})
                items.append({'id': it['id'], 'url': it['url'], 'title': it.get('title', ''), 'line': it.get('line', ''),
                              'category': it.get('category', 'uncategorized'), 'first_seen': it.get('first_seen'),
                              'last_seen': it.get('last_seen'), 'open_tabs': o['tabs'], 'awake_tabs': o['awake']})
            items.sort(key=lambda x: -(x['last_seen'] or 0))
            unstored = sum(1 for t in self.live['tabs'] if not t['item'])
            return {'schema': 'mai-tabs-view-v1', 'live_at': self.live['at'], 'items': items,
                    'days': {d: ids for d, ids in sorted(self.lib['days'].items(), reverse=True)},
                    'live': {'tabs': len(self.live['tabs']), 'awake': sum(1 for t in self.live['tabs'] if not t['discarded']),
                             'not_stored': unstored, 'duplicates': sum(o['tabs'] - 1 for o in open_tabs.values() if o['tabs'] > 1)},
                    'commands': self.cmds['commands'][-30:][::-1]}

    # actions -----------------------------------------------------------------------------------------------------------------------
    def plan(self, action, item_ids, group_title=None):
        """Turns a request from the page into exact steps for the extension. Only items that are in the library can be opened, so the
        page can never make the browser open an address it was not given by the browser itself."""
        if action not in ACTIONS:
            raise ValueError('unknown action')
        with self.lock:
            ids = [i for i in dict.fromkeys(item_ids or []) if isinstance(i, str) and i in self.lib['items']]
            if not ids and action != 'dedupe':
                raise ValueError('no known item')
            steps = []
            if action == 'open':
                steps = [{'do': 'open', 'item': i, 'url': self.lib['items'][i]['url']} for i in ids]
            elif action in ('sleep', 'close'):
                want = set(ids)
                steps = [{'do': 'discard' if action == 'sleep' else 'remove', 'tab': t['tab'], 'item': t['item']}
                         for t in self.live['tabs'] if t['item'] in want and not t['active'] and not t['pinned'] and not t['audible']
                         and (action == 'close' or not t['discarded'])]
            else:                             # dedupe: keep the most recently used tab of each page, close the other copies
                want = set(ids) if ids else None
                by_item = {}
                for t in self.live['tabs']:
                    if t['item'] and (want is None or t['item'] in want):
                        by_item.setdefault(t['item'], []).append(t)
                for tabs in by_item.values():
                    if len(tabs) < 2:
                        continue
                    tabs.sort(key=lambda t: (t['active'], t['pinned'], t['audible'], t['last_accessed'] or 0), reverse=True)
                    steps += [{'do': 'remove', 'tab': t['tab'], 'item': t['item']} for t in tabs[1:] if not (t['active'] or t['pinned'] or t['audible'])]
            return ids, steps

    def enqueue(self, action, item_ids, group_title=None, before=None):
        ids, steps = self.plan(action, item_ids, group_title)
        with self.lock:
            cid = self.cmds['next']
            self.cmds['next'] = cid + 1
            c = {'id': cid, 'action': action, 'items': ids, 'group': (group_title or '')[:60] or None, 'steps': steps,
                 'state': 'pending' if steps else 'done', 'created': int(self.clock() * 1000), 'result': None if steps else 'nothing to do',
                 'before': before, 'after': None}
            self.cmds['commands'] = (self.cmds['commands'] + [c])[-MAX_COMMANDS:]
            self._write('commands.json', self.cmds)
            return c

    def pending(self):
        with self.lock:
            return [{'id': c['id'], 'action': c['action'], 'group': c['group'], 'steps': c['steps']} for c in self.cmds['commands']
                    if c['state'] == 'pending']

    def ack(self, cid, ok, done, failed, note=''):
        with self.lock:
            for c in self.cmds['commands']:
                if c['id'] == cid and c['state'] == 'pending':
                    c['state'] = 'done' if ok else 'failed'
                    c['done_at'] = int(self.clock() * 1000)
                    c['result'] = {'done': int(done), 'failed': int(failed), 'note': str(note)[:200]}
                    self._write('commands.json', self.cmds)
                    return c
        return None

    def record_after(self, cid, after):
        with self.lock:
            for c in self.cmds['commands']:
                if c['id'] == cid:
                    c['after'] = after
                    self._write('commands.json', self.cmds)
                    return c
        return None
