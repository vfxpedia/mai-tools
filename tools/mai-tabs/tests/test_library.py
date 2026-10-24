"""Tab library and its server (DESIGN.md section 12). Run: python -I tests/test_library.py from tools/mai-tabs."""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mai_tabs import library, memory, server  # noqa: E402


class Clock:
    def __init__(self, t=1792300000.0):
        self.t = t

    def __call__(self):
        return self.t


def tab(i, url, title='', **kw):
    d = {'id': i, 'windowId': 1, 'url': url, 'title': title, 'discarded': False, 'active': False, 'pinned': False, 'audible': False,
         'groupId': -1, 'lastAccessed': 1792300000000 - i}
    d.update(kw)
    return d


class CleanUrlTests(unittest.TestCase):
    def test_secrets_and_tracking_are_dropped_the_page_stays_openable(self):
        u = library.clean_url('https://user:pw@example.org/a/b?q=robots&utm_source=x&access_token=SECRET1&page=2#frag')
        self.assertEqual(u, 'https://example.org/a/b?q=robots&page=2')
        self.assertNotIn('SECRET1', u)
        self.assertNotIn('pw', u)

    def test_long_random_values_are_dropped_but_ordinary_ids_stay(self):
        token = 'aB3' * 20
        self.assertEqual(library.clean_url('https://example.org/x?id=%s&v=dQw4w9WgXcQ' % token), 'https://example.org/x?v=dQw4w9WgXcQ')

    def test_not_stored_hosts_paths_and_schemes(self):
        for raw in ('https://accounts.google.com/x', 'https://mail.google.com/mail/u/0/', 'https://www.kbstar.com/', 'https://obank.kbstar.com/a',
                    'https://example.org/login', 'https://example.org/oauth/authorize?x=1', 'https://example.org/users/password/reset',
                    'chrome://settings/', 'file:///C:/secret.txt', 'about:blank', 'javascript:alert(1)', '', 'not a url'):
            self.assertIsNone(library.clean_url(raw), raw)
        self.assertEqual(library.clean_url('https://example.org/blog/login-tips'), 'https://example.org/blog/login-tips')

    def test_owner_deny_file_adds_hosts(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home)
        with open(os.path.join(home, 'deny.txt'), 'w', encoding='utf-8') as f:
            f.write('# my hosts\nintranet.example.org  # work\n')
        lib = library.Library(home)
        self.assertIsNone(library.clean_url('https://intranet.example.org/a', lib.deny))
        self.assertIsNotNone(library.clean_url('https://example.org/a', lib.deny))

    def test_same_page_variants_share_one_id(self):
        ids = {library.item_id(library.canonical(library.clean_url(u))) for u in
               ('https://www.example.org/a/', 'https://example.org/a', 'https://example.org/a#top', 'https://example.org/a?utm_medium=y')}
        self.assertEqual(len(ids), 1)
        self.assertNotEqual(library.item_id(library.canonical(library.clean_url('https://example.org/a?page=2'))), ids.pop())

    def test_one_arxiv_paper_is_one_page_whatever_the_version_or_format(self):
        ids = {library.canonical(library.clean_url(u)) for u in ('https://arxiv.org/abs/2309.14341', 'https://arxiv.org/abs/2309.14341v2',
               'https://arxiv.org/pdf/2309.14341v1', 'https://arxiv.org/pdf/2309.14341.pdf', 'https://www.arxiv.org/html/2309.14341v3')}
        self.assertEqual(ids, {'https://arxiv.org/abs/2309.14341'})
        self.assertNotEqual(library.canonical('https://arxiv.org/abs/2309.14342'), 'https://arxiv.org/abs/2309.14341')


class DescribeTests(unittest.TestCase):
    def setUp(self):
        self.rules = library.Library(tempfile.mkdtemp()).rules

    def test_papers_go_together(self):
        for url in ('https://arxiv.org/abs/2401.01234v2', 'https://openreview.net/forum?id=abc', 'https://doi.org/10.1145/3528223.3530110',
                    'https://example.org/files/paper.pdf', 'https://www.nature.com/articles/s41586'):
            self.assertEqual(library.describe(url, 'A title', self.rules)[0], 'research', url)
        self.assertEqual(library.describe('https://arxiv.org/abs/2401.01234v2', 'Learning to walk', self.rules)[1], '논문 · arXiv 2401.01234')

    def test_github_line_names_the_kind_and_number(self):
        cat, line = library.describe('https://github.com/foo/bar/pull/12', 'Fix it by x', self.rules)
        self.assertEqual((cat, line), ('code', 'GitHub PR · foo/bar #12'))

    def test_plain_page_line_is_host_and_first_path_part_not_the_title(self):
        self.assertEqual(library.describe('https://www.example.org/blog/x', 'Hello', self.rules), ('uncategorized', 'example.org · blog'))
        self.assertEqual(library.describe('https://example.org/', 'Hello', self.rules), ('uncategorized', 'example.org'))


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        self.clock = Clock()
        self.lib = library.Library(self.home, clock=self.clock)

    def test_duplicates_are_one_item_with_a_tab_count(self):
        c = self.lib.sync({'tabs': [tab(1, 'https://example.org/a'), tab(2, 'https://www.example.org/a/'), tab(3, 'https://example.org/b'),
                                    tab(4, 'https://accounts.google.com/x')]})
        self.assertEqual(c, {'tabs': 4, 'stored': 3, 'not_stored': 1})
        v = self.lib.view()
        self.assertEqual(len(v['items']), 2)
        a = [i for i in v['items'] if i['url'].endswith('/a')][0]
        self.assertEqual((a['open_tabs'], a['awake_tabs']), (2, 2))
        self.assertEqual((v['live']['duplicates'], v['live']['not_stored']), (1, 1))
        self.assertNotIn('accounts.google.com', json.dumps(v))

    def test_days_keep_what_was_open_and_items_survive_closing(self):
        self.lib.sync({'tabs': [tab(1, 'https://example.org/a')]})
        self.clock.t += 86400
        self.lib.sync({'tabs': [tab(2, 'https://example.org/b')]})
        v = library.Library(self.home, clock=self.clock).view()          # read back from disk
        self.assertEqual(len(v['items']), 2)
        self.assertEqual([len(ids) for ids in v['days'].values()], [1, 1])
        self.assertEqual(sum(i['open_tabs'] for i in v['items']), 1)

    def test_plan_only_opens_known_items(self):
        self.lib.sync({'tabs': [tab(1, 'https://example.org/a')]})
        iid = self.lib.view()['items'][0]['id']
        ids, steps = self.lib.plan('open', [iid, 'ffffffffffffffff', iid])
        self.assertEqual((ids, steps), ([iid], [{'do': 'open', 'item': iid, 'url': 'https://example.org/a'}]))
        with self.assertRaises(ValueError):
            self.lib.plan('open', ['ffffffffffffffff'])
        with self.assertRaises(ValueError):
            self.lib.plan('format-disk', [iid])

    def test_sleep_and_close_spare_active_pinned_and_audible_tabs(self):
        self.lib.sync({'tabs': [tab(1, 'https://example.org/a'), tab(2, 'https://example.org/a', active=True),
                                tab(3, 'https://example.org/a', pinned=True), tab(4, 'https://example.org/a', audible=True),
                                tab(5, 'https://example.org/a', discarded=True)]})
        iid = self.lib.view()['items'][0]['id']
        self.assertEqual([s['tab'] for s in self.lib.plan('sleep', [iid])[1]], [1])          # 5 is asleep already
        self.assertEqual([s['tab'] for s in self.lib.plan('close', [iid])[1]], [1, 5])

    def test_dedupe_keeps_the_most_recent_copy(self):
        self.lib.sync({'tabs': [tab(1, 'https://example.org/a', lastAccessed=10), tab(2, 'https://example.org/a', lastAccessed=30),
                                tab(3, 'https://example.org/a', lastAccessed=20), tab(4, 'https://example.org/b')]})
        self.assertEqual(sorted(s['tab'] for s in self.lib.plan('dedupe', [])[1]), [1, 3])

    def test_command_life_cycle(self):
        self.lib.sync({'tabs': [tab(1, 'https://example.org/a')]})
        iid = self.lib.view()['items'][0]['id']
        c = self.lib.enqueue('sleep', [iid], before={'at': 1})
        self.assertEqual([p['id'] for p in self.lib.pending()], [c['id']])
        self.assertIsNone(self.lib.ack(c['id'] + 99, True, 1, 0))
        self.assertEqual(self.lib.ack(c['id'], True, 1, 0)['state'], 'done')
        self.assertEqual(self.lib.pending(), [])
        self.assertIsNone(self.lib.ack(c['id'], True, 1, 0))                              # an action is finished once
        nothing = self.lib.enqueue('close', [iid])
        self.lib.sync({'tabs': []})
        self.assertEqual(self.lib.enqueue('close', [iid])['state'], 'done')                # no open tab: nothing to send
        self.assertEqual(nothing['state'], 'pending')

    def test_broken_file_is_kept_aside_not_overwritten(self):
        with open(os.path.join(self.home, 'library.json'), 'w') as f:
            f.write('{broken')
        library.Library(self.home)
        self.assertTrue(any(n.startswith('library.json.broken-') for n in os.listdir(self.home)))


class MemoryTests(unittest.TestCase):
    def test_difference_keeps_unknown_unknown(self):
        b = {'at': 0, 'browser_mib': 3000, 'gpus': [{'index': 0, 'used_mib': 100}, {'index': 1, 'used_mib': 4000}]}
        a = {'at': 20000, 'browser_mib': 2100, 'gpus': [{'index': 1, 'used_mib': 3600}]}
        self.assertEqual(memory.difference(b, a), {'browser_mib': -900, 'gpus': [{'index': 1, 'mib': -400}], 'seconds': 20})
        self.assertIsNone(memory.difference(dict(b, browser_mib=None), a)['browser_mib'])
        self.assertIsNone(memory.difference(None, a))


class ServerTests(unittest.TestCase):
    EXT = {'Origin': 'chrome-extension://abcdefghijklmnopabcdefghijklmnop'}

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        self.timers = []

        class Timer:
            def __init__(t, delay, fn):
                t.fn = fn
                self.timers.append(t)

            def start(t):
                pass

        self.app = server.App(library.Library(self.home), measure=lambda: {'at': 0, 'browser_mib': 1000, 'gpus': []}, timer=Timer)
        self.httpd = server.http.server.ThreadingHTTPServer(('127.0.0.1', 0), server.make_handler(self.app))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_address[1]

    def req(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        h = {'Host': host or '127.0.0.1:%d' % self.port}
        if body is not None:
            h.update({'Content-Type': 'application/json', 'X-Mai-Tabs': '1'})
        h.update(headers or {})
        c.request(method, path, json.dumps(body).encode() if body is not None else None, h)
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data

    def test_round_trip_page_to_extension_and_back(self):
        st, d = self.req('POST', '/api/sync', {'tabs': [tab(7, 'https://example.org/a', 'A')]}, self.EXT)
        self.assertEqual((st, d['counts']['stored'], d['commands']), (200, 1, []))
        st, v = self.req('GET', '/api/view')
        iid = v['items'][0]['id']
        st, c = self.req('POST', '/api/command', {'action': 'sleep', 'items': [iid]})
        self.assertEqual((st, c['state'], c['steps']), (200, 'pending', [{'do': 'discard', 'tab': 7, 'item': iid}]))
        st, d = self.req('POST', '/api/sync', {'tabs': [tab(7, 'https://example.org/a', 'A')]}, self.EXT)
        self.assertEqual([x['id'] for x in d['commands']], [c['id']])
        st, d = self.req('POST', '/api/ack', {'id': c['id'], 'ok': True, 'done': 1, 'failed': 0}, self.EXT)
        self.assertEqual(st, 200)
        self.timers[0].fn()                                       # the 20-second re-measure, run now
        st, v = self.req('GET', '/api/view')
        self.assertEqual(v['commands'][0]['after']['change']['browser_mib'], 0)

    def test_open_asleep_marks_the_steps(self):
        self.req('POST', '/api/sync', {'tabs': [tab(7, 'https://example.org/a')]}, self.EXT)
        iid = self.req('GET', '/api/view')[1]['items'][0]['id']
        st, c = self.req('POST', '/api/command', {'action': 'open', 'items': [iid], 'group': '논문', 'asleep': True})
        self.assertEqual((c['group'], c['steps'][0]['asleep']), ('논문', True))

    def test_a_web_page_or_the_phone_cannot_report_tabs(self):
        for headers in ({}, {'Origin': 'https://evil.example'}, dict(self.EXT, **{'Tailscale-User-Login': 'someone'})):
            st, d = self.req('POST', '/api/sync', {'tabs': [tab(1, 'https://evil.example/x')]}, headers)
            self.assertEqual(st, 403, headers)
        self.assertEqual(self.req('GET', '/api/view')[1]['items'], [])

    def test_posts_need_the_header_and_json(self):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        c.request('POST', '/api/command', b'{"action":"dedupe","items":[]}', {'Content-Type': 'text/plain'})
        self.assertEqual(c.getresponse().status, 403)
        c.close()
        self.assertEqual(self.req('POST', '/api/command', {'action': 'dedupe'}, {'X-Mai-Tabs': '0'})[0], 403)
        self.assertEqual(self.req('OPTIONS', '/api/command')[0], 405)

    def test_unknown_host_is_refused(self):
        self.assertEqual(self.req('GET', '/api/view', host='evil.example')[0], 421)
        self.assertEqual(self.req('GET', '/api/view', host='ai-ws01.tail0000.ts.net')[0], 200)
        self.assertEqual(self.req('GET', '/api/view', host='ts.net.evil.example')[0], 421)

    def test_bad_requests_are_400_not_crashes(self):
        self.assertEqual(self.req('POST', '/api/command', {'action': 'open', 'items': ['nope']})[0], 400)
        self.assertEqual(self.req('POST', '/api/ack', {'id': 'x'}, self.EXT)[0], 400)
        self.assertEqual(self.req('POST', '/api/ack', {'id': 999}, self.EXT)[0], 400)
        st, page = self.req('GET', '/')
        self.assertEqual(st, 200)
        self.assertIn('탭 보관함'.encode('utf-8'), page)


if __name__ == '__main__':
    unittest.main()
