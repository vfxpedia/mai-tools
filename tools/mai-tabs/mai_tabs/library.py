"""Tab library (DESIGN.md section 12): every page the browser had open, kept once per page, with the days it was open.

Unlike the v1 export, the library keeps addresses that can be opened again, so what it stores is decided here, before anything is written:
  - only http and https pages; user name and password in the address are dropped
  - query parameters whose name says secret (token, key, auth, pass, session, code, invite, ...) or whose value looks like a long random
    value are dropped, tracking parameters (utm_*, fbclid, ...) are dropped, the fragment is dropped unless it is a plain route (#/a/b)
  - a page is not stored at all when it is on a deny-listed host (sign-in, mail, banks by default), when a path part is a sign-in step
    (login, oauth, sso, ...) or names a one-time link (password, reset, verify, confirm, magic, invite, ...), or when a path part looks
    like a token (a JWT, or 24 or more mixed letters and digits that are not a UUID or plain hex, except on hosts whose page ids look
    like that by design, such as Google Docs)
Two tabs are the same page when these cleaned addresses are equal, so a page opened three times is one item that says "3 tabs".

Files (under the data folder, default ~/.mai/tabs, or MAI_TABS_HOME):
  library.json   items by id, and for each local date the ids that were open that day
  live.json      the last tab list each browser (extension instance) reported: what is open now
  commands.json  actions asked for from the page, their steps, state, result and the memory measured before and after
Every write goes to a temporary file, is flushed to disk, and replaces the old one (retried while Windows holds the file), so a crash
or a reader never leaves half a file. An action is written before it can be handed to the browser.
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
SECRET_NAME = re.compile(r'(?i)(token|secret|passw|pwd|^pass$|session|^sid$|ssid|otp|ticket|invite|saml|rlkey|resourcekey|credential|hmac|'
                         r'nonce|^state$|jwt|login_hint|email|x-amz-|x-goog-|awsaccesskeyid|signature|^sig$|_sig$|^sig_|hash|'
                         r'(^|[_.-])code($|[_.-])|^code$|auth(?!or)|(^|[_.-])key($|[_.-])|apikey|api_key|^key$)')
TRACKING_PARAM = re.compile(r'(?i)^(utm_.*|fbclid|gclid|dclid|msclkid|mc_eid|mc_cid|igshid|si|ref_src|ref_url|_hsenc|_hsmi|spm)$')
LONG_RANDOM = re.compile(r'^[A-Za-z0-9_\-.~%+/=]{40,}$')
SIGN_IN_SEGMENT = {'oauth', 'oauth2', 'signin', 'sign-in', 'login', 'logout', 'auth', 'sso', 'saml', 'authorize'}
ONE_TIME_WORDS = re.compile(r'(?i)(password|reset|verify|confirm|magic|invite|activate|unsubscribe)')
JWT = re.compile(r'^eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}')
UUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
HEX = re.compile(r'^[0-9a-fA-F]+$')
TOKENISH = re.compile(r'^[A-Za-z0-9_\-.!~]{24,}$')
LONG_ID_HOSTS = ('docs.google.com', 'drive.google.com', 'sheets.google.com', 'slides.google.com', 'colab.research.google.com',
                 'youtube.com', 'github.com', 'notion.so', 'notion.site', 'figma.com')
HASH_ROUTE = re.compile(r'^!?/[^=&?]*$')
DEFAULT_DENY = ('accounts.google.com', 'mail.google.com', 'myaccount.google.com', 'login.microsoftonline.com', 'login.live.com',
                'outlook.live.com', 'outlook.office.com', 'mail.naver.com', 'nid.naver.com', 'mail.daum.net', 'accounts.kakao.com',
                'paypal.com', 'kbstar.com', 'shinhan.com', 'wooribank.com', 'hanabank.com', 'ibk.co.kr', 'nonghyup.com', 'kakaobank.com',
                'toss.im', 'tossbank.com', 'citibank.co.kr', 'scfirstbank.com', 'kdb.co.kr', 'epostbank.go.kr', 'bank')
MAX_TITLE = 300
MAX_ITEMS = 20000
MAX_COMMANDS = 300
ACTIONS = ('open', 'sleep', 'close', 'dedupe')
COMMAND_TTL_S = 120          # an action not picked up, or picked up and never answered, within this time is not run any more
LIVE_FRESH_S = 120           # a browser that has not reported for this long is "not connected"
MEASURE_LOST_S = 90


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


def _on(host, hosts):
    return any(host == h or host.endswith('.' + h) for h in hosts)


def _path_refused(host, path):
    for seg in path.split('/'):
        if not seg:
            continue
        if seg.lower() in SIGN_IN_SEGMENT or ONE_TIME_WORDS.search(seg) or JWT.match(seg):
            return True
        if (TOKENISH.match(seg) and re.search('[0-9]', seg) and re.search('[A-Za-z]', seg) and not UUID.match(seg)
                and not HEX.match(seg.split('.')[0]) and not _on(host, LONG_ID_HOSTS)):
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
        if _host_denied(host, deny) or _path_refused(host, u.path):
            return None
        port = u.port
        netloc = ('[%s]' % host if ':' in host else host) + (':%d' % port if port and port != {'http': 80, 'https': 443}[scheme] else '')
        keep = []
        for k, v in parse_qsl(u.query, keep_blank_values=True):
            if SECRET_NAME.search(k) or TRACKING_PARAM.match(k):
                continue
            if LONG_RANDOM.match(v) and re.search('[0-9]', v) and re.search('[A-Za-z]', v):
                continue
            keep.append((k, v))
        frag = u.fragment if HASH_ROUTE.match(u.fragment or '') and not _path_refused(host, u.fragment) else ''
        return urlunsplit((scheme, netloc, u.path or '/', urlencode(keep), frag))
    except (ValueError, KeyError, TypeError):
        return None


ARXIV_PATH = re.compile(r'(?i)^/(?:abs|pdf|html)/([0-9]{4}\.[0-9]{4,5}|[a-z\-]+/[0-9]{7})(?:v[0-9]+)?(?:\.pdf)?/?$')


def canonical(url):
    """Equality key: host without www, path without a trailing slash, query parameters in sorted order, the route fragment kept.
    An arXiv paper is one page whatever its version or format (abs, pdf, html, v1, v2)."""
    u = urlsplit(url)
    m = ARXIV_PATH.match(u.path) if (u.hostname or '').lower() in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org') else None
    if m:
        return 'https://arxiv.org/abs/' + m.group(1).lower()
    host = u.netloc[4:] if u.netloc.startswith('www.') else u.netloc
    path = u.path.rstrip('/') or '/'
    q = urlencode(sorted(parse_qsl(u.query, keep_blank_values=True)))
    return '%s://%s%s%s%s' % (u.scheme, host, path, ('?' + q) if q else '', ('#' + u.fragment) if u.fragment else '')


def item_id(canon):
    return hashlib.sha256(canon.encode('utf-8')).hexdigest()[:16]


def same_page(a, b):
    """True when two addresses are the same page by origin and path; used to re-check a tab right before it is closed or put to sleep."""
    try:
        ua, ub = urlsplit(a), urlsplit(b)
        strip = lambda h: (h or '').lower()[4:] if (h or '').lower().startswith('www.') else (h or '').lower()
        return (ua.scheme, strip(ua.hostname), ua.port, ua.path.rstrip('/')) == (ub.scheme, strip(ub.hostname), ub.port, ub.path.rstrip('/'))
    except ValueError:
        return False


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
    path = urlsplit(url).path
    paper = _on(bare, PAPER_HOSTS) or path.lower().endswith('.pdf')
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
    if paper and path.lower().endswith('.pdf'):
        return 'research', '논문 PDF · %s · %s' % (bare, path.rsplit('/', 1)[-1])
    if paper:
        return 'research', '논문 · ' + bare
    return category, bare + ((' · ' + path.strip('/').split('/')[0]) if path.strip('/') else '')


def local_date(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).date().isoformat()


def _int(v, lo=0, hi=10 ** 6):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValueError('expected a whole number from %d to %d' % (lo, hi))
    return v


class Library:
    def __init__(self, home=None, rules=None, deny=None, clock=time.time):
        self.home = os.path.abspath(os.path.expanduser(home or os.environ.get('MAI_TABS_HOME') or '~/.mai/tabs'))
        os.makedirs(self.home, exist_ok=True)
        self.rules = rules or classify.load_rules(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rules.default.json'))
        self.deny = tuple(deny) if deny is not None else self._load_deny()
        self.clock = clock
        self.lock = threading.RLock()
        self.lib = self._read('library.json', {'schema': SCHEMA, 'items': {}, 'days': {}})
        live = self._read('live.json', {'browsers': {}})
        self.live = live if isinstance(live.get('browsers'), dict) else {'browsers': {}}
        self.cmds = self._read('commands.json', {'next': 1, 'commands': []})

    def now_ms(self):
        return int(self.clock() * 1000)

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

    def _write(self, name, data, tries=6):
        p = os.path.join(self.home, name)
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        for i in range(tries):                # Windows refuses to replace a file another process has open (indexer, antivirus, editor)
            try:
                os.replace(tmp, p)
                return
            except PermissionError:
                if i == tries - 1:
                    raise
                time.sleep(0.05 * (i + 1))

    # what the extension reports ---------------------------------------------------------------------------------------------------
    def sync(self, report):
        """report: {'instance': id, 'tabs': [{id, windowId, url, title, discarded, active, pinned, audible, groupId, lastAccessed}],
        'groups': [...]}. Updates that browser's live list and the library. Returns counts for the extension's own check."""
        inst = report.get('instance')
        if not isinstance(inst, str) or not re.match(r'^[A-Za-z0-9_-]{8,64}$', inst):
            raise ValueError('report needs an instance id')
        now = self.now_ms()
        today = local_date(now)
        tabs_in = report.get('tabs') if isinstance(report.get('tabs'), list) else []
        live, stored, skipped = [], 0, 0
        with self.lock:
            items, day = self.lib['items'], set(self.lib['days'].get(today, []))
            for t in tabs_in[:2000]:
                if not isinstance(t, dict) or isinstance(t.get('id'), bool) or not isinstance(t.get('id'), int):
                    continue
                url = clean_url(t.get('url') or t.get('pendingUrl') or '', self.deny)
                iid = None
                if url:
                    iid = item_id(canonical(url))
                    title = str(t.get('title') or '')[:MAX_TITLE]
                    it = items.get(iid)
                    if it is None and len(items) >= MAX_ITEMS:
                        iid = None
                    else:
                        if it is None:
                            it = items[iid] = {'id': iid, 'url': url, 'title': title, 'first_seen': now}
                        if title:
                            it['title'] = title           # the address stays the first one seen, so a duplicate never rewrites it
                        it['category'], it['line'] = describe(it['url'], it['title'], self.rules)
                        it['last_seen'] = now
                        day.add(iid)
                        stored += 1
                if iid is None:
                    skipped += 1
                gid = t.get('groupId')
                la = t.get('lastAccessed')
                live.append({'tab': t['id'], 'window': t.get('windowId') if isinstance(t.get('windowId'), int) else None, 'item': iid,
                             'discarded': t.get('discarded') is True, 'active': t.get('active') is True, 'pinned': t.get('pinned') is True,
                             'audible': t.get('audible') is True, 'group': gid if isinstance(gid, int) and gid >= 0 else None,
                             'last_accessed': la if isinstance(la, (int, float)) and la == la and abs(la) < 1e15 else None})
            self.lib['days'][today] = sorted(day)
            groups = [{'id': g.get('id'), 'title': str(g.get('title') or '')[:100], 'color': str(g.get('color') or '')[:20]}
                      for g in (report.get('groups') or []) if isinstance(g, dict) and isinstance(g.get('id'), int)]
            self.live['browsers'][inst] = {'at': now, 'tabs': live, 'groups': groups}
            for k in [k for k, b in self.live['browsers'].items() if now - b['at'] > 7 * 86400000]:
                del self.live['browsers'][k]
            self._write('library.json', self.lib)
            self._write('live.json', self.live)
        return {'tabs': len(live), 'stored': stored, 'not_stored': skipped}

    def _fresh_browsers(self, now):
        return {k: b for k, b in self.live['browsers'].items() if now - b['at'] <= LIVE_FRESH_S * 1000}

    def _newest(self, now):
        fresh = self._fresh_browsers(now)
        return max(fresh.items(), key=lambda kv: kv[1]['at']) if fresh else (None, None)

    # what the page shows -------------------------------------------------------------------------------------------------------------
    def view(self):
        with self.lock:
            now = self.now_ms()
            fresh = self._fresh_browsers(now)
            tabs = [t for b in fresh.values() for t in b['tabs']]
            open_tabs = {}
            for t in tabs:
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
            commands = []
            for c in self.cmds['commands'][-30:][::-1]:
                c = json.loads(json.dumps(c))                     # a copy taken under the lock
                if c['state'] == 'pending' and now - c['created'] > COMMAND_TTL_S * 1000:
                    c['state'] = 'expired'                        # shown as it will be recorded at the next report
                elif c['state'] == 'delivered' and now - c.get('delivered_at', now) > COMMAND_TTL_S * 1000:
                    c['state'] = 'unknown'
                if c.get('before') and not c.get('after') and c['state'] in ('done', 'failed') and now - (c.get('done_at') or now) > MEASURE_LOST_S * 1000:
                    c['after'] = {'lost': True}
                commands.append(c)
            last = max((b['at'] for b in self.live['browsers'].values()), default=None)
            return {'schema': 'mai-tabs-view-v1', 'live_at': last, 'browsers': len(fresh), 'items': items,
                    'days': {d: ids for d, ids in sorted(self.lib['days'].items(), reverse=True)},
                    'live': {'tabs': len(tabs), 'awake': sum(1 for t in tabs if not t['discarded']),
                             'not_stored': sum(1 for t in tabs if not t['item']),
                             'duplicates': sum(o['tabs'] - 1 for o in open_tabs.values() if o['tabs'] > 1)},
                    'commands': commands}

    # actions -----------------------------------------------------------------------------------------------------------------------
    def plan(self, action, item_ids, asleep=False):
        """Turns a request from the page into exact steps for one browser (the one that reported last). Only items in the library can
        be opened, so the page can never make the browser open an address the browser did not report itself. Steps that touch an open
        tab carry the page's address, so the extension can check right before acting that the tab is still that page."""
        if action not in ACTIONS:
            raise ValueError('unknown action')
        with self.lock:
            now = self.now_ms()
            inst, browser = self._newest(now)
            if inst is None:
                raise ValueError('no browser has reported in the last %d seconds; is Chrome running with the mai-tabs extension?' % LIVE_FRESH_S)
            ids = [i for i in dict.fromkeys(item_ids or []) if isinstance(i, str) and i in self.lib['items']]
            if not ids and action != 'dedupe':
                raise ValueError('no known item')
            url = lambda i: self.lib['items'][i]['url']
            spare = lambda t: t['active'] or t['pinned'] or t['audible']
            steps = []
            if action == 'open':
                steps = [dict({'do': 'open', 'item': i, 'url': url(i)}, **({'asleep': True} if asleep else {})) for i in ids]
            elif action in ('sleep', 'close'):
                want = set(ids)
                steps = [{'do': 'discard' if action == 'sleep' else 'remove', 'tab': t['tab'], 'item': t['item'], 'url': url(t['item'])}
                         for t in browser['tabs'] if t['item'] in want and not spare(t) and (action == 'close' or not t['discarded'])]
            else:                             # dedupe: keep the most recently used tab of each page, close the other copies
                want = set(ids) if ids else None
                by_item = {}
                for t in browser['tabs']:
                    if t['item'] and (want is None or t['item'] in want):
                        by_item.setdefault(t['item'], []).append(t)
                for tabs in by_item.values():
                    if len(tabs) < 2:
                        continue
                    tabs.sort(key=lambda t: (t['active'], t['pinned'], t['audible'], t['last_accessed'] or 0), reverse=True)
                    steps += [{'do': 'remove', 'tab': t['tab'], 'item': t['item'], 'url': url(t['item'])} for t in tabs[1:] if not spare(t)]
            return inst, browser['at'], ids, steps

    def enqueue(self, action, item_ids, group_title=None, before=None, asleep=False):
        inst, live_at, ids, steps = self.plan(action, item_ids, asleep)
        with self.lock:
            cid = self.cmds['next']
            c = {'id': cid, 'action': action, 'items': ids, 'group': (group_title or '')[:60] or None, 'steps': steps,
                 'instance': inst, 'live_at': live_at, 'state': 'pending' if steps else 'done', 'created': self.now_ms(),
                 'result': None if steps else 'nothing to do', 'before': before if steps else None, 'after': None}
            new = {'next': cid + 1, 'commands': (self.cmds['commands'] + [c])[-MAX_COMMANDS:]}
            self._write('commands.json', new)          # written first: an action the file does not hold is never handed out
            self.cmds = new
            return c

    def pending(self, instance):
        """Actions for this browser, each handed out once. An action older than COMMAND_TTL_S is expired instead. Close and sleep steps
        are checked again against the browser's latest report: a tab that is gone, shows another page, or became active, pinned or
        audible is left out."""
        with self.lock:
            now = self.now_ms()
            b = self.live['browsers'].get(instance) or {'tabs': []}
            current = {t['tab']: t for t in b['tabs']}
            out, changed = [], False
            new_cmds = json.loads(json.dumps(self.cmds))
            for c in new_cmds['commands']:
                if c['state'] == 'delivered' and now - c.get('delivered_at', now) > COMMAND_TTL_S * 1000:
                    c['state'], c['result'], changed = 'unknown', 'the browser took it but never answered', True
                if c['state'] != 'pending':
                    continue
                if now - c['created'] > COMMAND_TTL_S * 1000:
                    c['state'], c['result'], changed = 'expired', 'not picked up within %d seconds' % COMMAND_TTL_S, True
                    continue
                if c.get('instance') != instance:
                    continue
                steps = []
                for s in c['steps']:
                    if s['do'] == 'open':
                        steps.append(s)
                        continue
                    t = current.get(s['tab'])
                    if t and t['item'] == s['item'] and not (t['active'] or t['pinned'] or t['audible']):
                        steps.append(s)
                c['steps'], c['state'], c['delivered_at'], changed = steps, 'delivered', now, True
                out.append({'id': c['id'], 'action': c['action'], 'group': c['group'], 'steps': steps})
            if changed:
                self._write('commands.json', new_cmds)
                self.cmds = new_cmds
            return out

    def ack(self, cid, ok, done, failed, note=''):
        cid, done, failed = _int(cid, 1, 10 ** 9), _int(done), _int(failed)
        if not isinstance(ok, bool):
            raise ValueError('ok must be true or false')
        with self.lock:
            for c in self.cmds['commands']:
                if c['id'] == cid and c['state'] in ('delivered', 'pending'):
                    c['state'] = 'done' if ok else 'failed'
                    c['done_at'] = self.now_ms()
                    c['result'] = {'done': done, 'failed': failed, 'note': str(note)[:200]}
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
