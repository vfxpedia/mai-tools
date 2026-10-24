"""Tab library and its server (DESIGN.md section 12). Run: python -I tests/test_library.py from tools/mai-tabs."""
import http.client
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mai_tabs import library, memory, server  # noqa: E402

INST = 'browserA1'
OTHER = 'browserB2'


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


def report(*tabs, inst=INST):
    return {'instance': inst, 'tabs': list(tabs)}


class CleanUrlTests(unittest.TestCase):
    def test_secrets_and_tracking_are_dropped_the_page_stays_openable(self):
        u = library.clean_url('https://user:pw@example.org/a/b?q=robots&utm_source=x&access_token=SECRET1&page=2#frag')
        self.assertEqual(u, 'https://example.org/a/b?q=robots&page=2')
        self.assertNotIn('pw', u)

    def test_secret_parameter_names_are_matched_inside_longer_names(self):
        # review finding 5: whole-name matching kept these
        raw = ('https://example.org/x?private_token=glpat-AAA&auth_token=B&csrf_token=C&reset_token=D&token_hash=E&invite_code=F&rlkey=G'
               '&resourcekey=H&SAMLRequest=I&api_key=J&sig=K&X-Amz-Signature=L&code=M&author=kept&q=kept')
        self.assertEqual(library.clean_url(raw), 'https://example.org/x?author=kept&q=kept')

    def test_long_random_values_are_dropped_but_ordinary_ids_stay(self):
        token = 'aB3' * 20
        self.assertEqual(library.clean_url('https://example.org/x?id=%s&v=dQw4w9WgXcQ' % token), 'https://example.org/x?v=dQw4w9WgXcQ')

    def test_not_stored_hosts_paths_and_schemes(self):
        for raw in ('https://accounts.google.com/x', 'https://mail.google.com/mail/u/0/', 'https://www.kbstar.com/', 'https://obank.kbstar.com/a',
                    'https://example.org/login', 'https://example.org/oauth/authorize?x=1', 'https://example.org/users/password/reset',
                    'https://example.org/auth/confirm?token_hash=abc', 'https://example.org/reset-password/abcDEF123456ghiJKL789',
                    'https://example.org/magic/eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig', 'https://example.org/invite/abc',
                    'https://example.org/s/k3J9xQ2mP7vL4nB8wR1tY6zC', 'https://example.org/sso',
                    'chrome://settings/', 'file:///C:/secret.txt', 'about:blank', 'javascript:alert(1)', '', 'not a url'):
            self.assertIsNone(library.clean_url(raw), raw)

    def test_ordinary_long_ids_are_kept(self):
        for raw in ('https://example.org/blog/login-tips', 'https://claude.ai/chat/0f8fad5b-d9cb-469f-a165-70867728950e',
                    'https://github.com/a/b/commit/1b2c3d4e5f60718293a4b5c6d7e8f90112233445',
                    'https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit',
                    'https://www.notion.so/My-page-0123456789abcdef0123456789abcdef'):
            self.assertIsNotNone(library.clean_url(raw), raw)

    def test_route_fragments_are_kept_other_fragments_dropped(self):
        self.assertEqual(library.clean_url('https://app.example.org/#/doc/1'), 'https://app.example.org/#/doc/1')
        self.assertEqual(library.clean_url('https://app.example.org/#access_token=abc&x=1'), 'https://app.example.org/')
        self.assertEqual(library.clean_url('https://example.org/a#section-2'), 'https://example.org/a')
        self.assertNotEqual(library.canonical('https://app.example.org/#/doc/1'), library.canonical('https://app.example.org/#/doc/2'))

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
        self.assertEqual(library.describe('https://github.com/foo/bar/pull/12', 'Fix it by x', self.rules), ('code', 'GitHub PR · foo/bar #12'))

    def test_plain_page_line_is_host_and_first_path_part_not_the_title(self):
        self.assertEqual(library.describe('https://www.example.org/blog/x', 'Hello', self.rules), ('uncategorized', 'example.org · blog'))
        self.assertEqual(library.describe('https://example.org/', 'Hello', self.rules), ('uncategorized', 'example.org'))


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        self.clock = Clock()
        self.lib = library.Library(self.home, clock=self.clock)

    def iid(self, url_end):
        return [i for i in self.lib.view()['items'] if i['url'].endswith(url_end)][0]['id']

    def test_a_report_needs_an_instance(self):
        with self.assertRaises(ValueError):
            self.lib.sync({'tabs': []})

    def test_duplicates_are_one_item_with_a_tab_count(self):
        c = self.lib.sync(report(tab(1, 'https://example.org/a'), tab(2, 'https://www.example.org/a/'), tab(3, 'https://example.org/b'),
                                 tab(4, 'https://accounts.google.com/x')))
        self.assertEqual(c, {'tabs': 4, 'stored': 3, 'not_stored': 1})
        v = self.lib.view()
        self.assertEqual(len(v['items']), 2)
        a = [i for i in v['items'] if i['url'] == 'https://example.org/a'][0]
        self.assertEqual((a['open_tabs'], a['awake_tabs']), (2, 2))
        self.assertEqual((v['live']['duplicates'], v['live']['not_stored']), (1, 1))
        self.assertNotIn('accounts.google.com', json.dumps(v))

    def test_days_keep_what_was_open_and_items_survive_closing(self):
        self.lib.sync(report(tab(1, 'https://example.org/a')))
        self.clock.t += 86400
        self.lib.sync(report(tab(2, 'https://example.org/b')))
        v = library.Library(self.home, clock=self.clock).view()          # read back from disk
        self.assertEqual(len(v['items']), 2)
        self.assertEqual([len(ids) for ids in v['days'].values()], [1, 1])
        self.assertEqual(sum(i['open_tabs'] for i in v['items']), 1)

    def test_plan_only_opens_known_items_and_needs_a_connected_browser(self):
        with self.assertRaises(ValueError):
            self.lib.plan('open', [])                                    # nobody reported yet
        self.lib.sync(report(tab(1, 'https://example.org/a')))
        iid = self.iid('/a')
        inst, _, ids, steps = self.lib.plan('open', [iid, 'ffffffffffffffff', iid], asleep=True)
        self.assertEqual((inst, ids, steps), (INST, [iid], [{'do': 'open', 'item': iid, 'url': 'https://example.org/a', 'asleep': True}]))
        with self.assertRaises(ValueError):
            self.lib.plan('open', ['ffffffffffffffff'])
        with self.assertRaises(ValueError):
            self.lib.plan('format-disk', [iid])
        self.clock.t += library.LIVE_FRESH_S + 1
        with self.assertRaises(ValueError):
            self.lib.plan('open', [iid])                                 # the browser went quiet

    def test_sleep_and_close_spare_active_pinned_and_audible_tabs(self):
        self.lib.sync(report(tab(1, 'https://example.org/a'), tab(2, 'https://example.org/a', active=True),
                             tab(3, 'https://example.org/a', pinned=True), tab(4, 'https://example.org/a', audible=True),
                             tab(5, 'https://example.org/a', discarded=True)))
        iid = self.iid('/a')
        self.assertEqual([s['tab'] for s in self.lib.plan('sleep', [iid])[3]], [1])          # 5 is asleep already
        self.assertEqual([s['tab'] for s in self.lib.plan('close', [iid])[3]], [1, 5])
        self.assertTrue(all(s['url'] == 'https://example.org/a' for s in self.lib.plan('close', [iid])[3]))

    def test_dedupe_keeps_the_most_recent_copy_and_never_closes_pinned_or_audible(self):
        self.lib.sync(report(tab(1, 'https://example.org/a', lastAccessed=10), tab(2, 'https://example.org/a', lastAccessed=30),
                             tab(3, 'https://example.org/a', lastAccessed=20), tab(4, 'https://example.org/b'),
                             tab(5, 'https://example.org/c', active=True), tab(6, 'https://example.org/c', pinned=True),
                             tab(7, 'https://example.org/c', audible=True), tab(8, 'https://example.org/c', lastAccessed=99)))
        self.assertEqual(sorted(s['tab'] for s in self.lib.plan('dedupe', [])[3]), [1, 3, 8])

    def test_actions_go_only_to_the_browser_they_were_planned_from(self):
        self.lib.sync(report(tab(1, 'https://example.org/a'), inst=OTHER))
        self.clock.t += 1
        self.lib.sync(report(tab(1, 'https://example.org/a')))
        c = self.lib.enqueue('sleep', [self.iid('/a')])
        self.assertEqual(c['instance'], INST)
        self.assertEqual(self.lib.pending(OTHER), [])
        self.assertEqual([p['id'] for p in self.lib.pending(INST)], [c['id']])

    def test_stale_steps_are_dropped_at_hand_out(self):
        # review finding 1: the tab became active, or now shows another page, between planning and hand-out
        self.lib.sync(report(tab(1, 'https://example.org/a'), tab(2, 'https://example.org/a')))
        c = self.lib.enqueue('close', [self.iid('/a')])
        self.lib.sync(report(tab(1, 'https://example.org/a', active=True), tab(2, 'https://example.org/zzz')))
        self.assertEqual(self.lib.pending(INST), [{'id': c['id'], 'action': 'close', 'group': None, 'steps': []}])

    def test_actions_expire_and_are_handed_out_once(self):
        self.lib.sync(report(tab(1, 'https://example.org/a')))
        iid = self.iid('/a')
        old = self.lib.enqueue('sleep', [iid])
        self.clock.t += library.COMMAND_TTL_S + 1
        self.lib.sync(report(tab(1, 'https://example.org/a')))
        self.assertEqual(self.lib.pending(INST), [])
        self.assertEqual([c['state'] for c in self.lib.view()['commands'] if c['id'] == old['id']], ['expired'])
        fresh = self.lib.enqueue('sleep', [iid])
        self.assertEqual(len(self.lib.pending(INST)), 1)
        self.assertEqual(self.lib.pending(INST), [])                    # a second report does not run it again
        self.clock.t += library.COMMAND_TTL_S + 1
        self.assertEqual([c['state'] for c in self.lib.view()['commands'] if c['id'] == fresh['id']], ['unknown'])

    def test_ack_checks_its_input_before_changing_anything(self):
        # review finding 8
        self.lib.sync(report(tab(1, 'https://example.org/a')))
        c = self.lib.enqueue('sleep', [self.iid('/a')], before={'at': 1})
        self.lib.pending(INST)
        for bad in (('x', True, 1, 0), (c['id'], 'yes', 1, 0), (c['id'], True, 'x', 0), (c['id'], True, float('inf'), 0), (c['id'], True, -1, 0)):
            with self.assertRaises(ValueError):
                self.lib.ack(*bad)
        self.assertEqual(self.lib.cmds['commands'][-1]['state'], 'delivered')
        self.assertEqual(self.lib.ack(c['id'], True, 1, 0)['state'], 'done')
        self.assertIsNone(self.lib.ack(c['id'], True, 1, 0))           # an action is finished once

    def test_nothing_to_do_is_done_at_once(self):
        self.lib.sync(report(tab(1, 'https://example.org/a')))
        iid = self.iid('/a')
        self.lib.sync(report())
        self.assertEqual(self.lib.enqueue('close', [iid])['state'], 'done')

    def test_a_failed_write_hands_out_nothing(self):
        # review finding 6: the action must be on disk before the browser can get it
        self.lib.sync(report(tab(1, 'https://example.org/a')))
        iid = self.iid('/a')
        with mock.patch('mai_tabs.library.os.replace', side_effect=PermissionError(13, 'in use')), mock.patch('mai_tabs.library.time.sleep'):
            with self.assertRaises(PermissionError):
                self.lib.enqueue('sleep', [iid])
        self.assertEqual(self.lib.pending(INST), [])

    def test_write_retries_while_windows_holds_the_file(self):
        calls = []
        real = os.replace

        def flaky(a, b):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(13, 'in use')
            return real(a, b)
        with mock.patch('mai_tabs.library.os.replace', side_effect=flaky), mock.patch('mai_tabs.library.time.sleep'):
            self.lib.sync(report(tab(1, 'https://example.org/a')))
        self.assertGreaterEqual(len(calls), 3)

    def test_broken_file_is_kept_aside_not_overwritten(self):
        with open(os.path.join(self.home, 'library.json'), 'w') as f:
            f.write('{broken')
        library.Library(self.home)
        self.assertTrue(any(n.startswith('library.json.broken-') for n in os.listdir(self.home)))

    def test_a_lost_after_reading_is_shown_as_lost(self):
        # review finding 10
        self.lib.sync(report(tab(1, 'https://example.org/a')))
        c = self.lib.enqueue('sleep', [self.iid('/a')], before={'at': 1})
        self.lib.pending(INST)
        self.lib.ack(c['id'], True, 1, 0)
        self.clock.t += library.MEASURE_LOST_S + 1
        self.assertEqual(self.lib.view()['commands'][0]['after'], {'lost': True})


class MemoryTests(unittest.TestCase):
    def test_difference_keeps_unknown_unknown(self):
        b = {'at': 0, 'browser_mib': 3000, 'gpus': [{'index': 0, 'used_mib': 100}, {'index': 1, 'used_mib': 4000}]}
        a = {'at': 20000, 'browser_mib': 2100, 'gpus': [{'index': 1, 'used_mib': 3600}]}
        self.assertEqual(memory.difference(b, a), {'browser_mib': -900, 'gpus': [{'index': 1, 'mib': -400}], 'seconds': 20})
        self.assertIsNone(memory.difference(dict(b, browser_mib=None), a)['browser_mib'])
        self.assertIsNone(memory.difference(None, a))


class ServerTests(unittest.TestCase):
    EXT = {'Origin': 'chrome-extension://abcdefghijklmnopabcdefghijklmnop'}
    TS = 'ai-ws01.tail0000.ts.net'

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
        page_h, ext_h = server.handlers(self.app)
        self.ports = {}
        for name, h in (('page', page_h), ('ext', ext_h)):
            httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), h)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            self.addCleanup(httpd.server_close)
            self.addCleanup(httpd.shutdown)
            self.ports[name] = httpd.server_address[1]

    def req(self, method, path, body=None, headers=None, host=None, port='page', raw=None):
        c = http.client.HTTPConnection('127.0.0.1', self.ports[port], timeout=5)
        h = {'Host': host or '127.0.0.1:%d' % self.ports[port]}
        if body is not None or raw is not None:
            h.update({'Content-Type': 'application/json', 'X-Mai-Tabs': '1'})
        h.update(headers or {})
        c.request(method, path, raw if raw is not None else (json.dumps(body).encode() if body is not None else None), h)
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data

    def sync(self, *tabs, headers=None):
        return self.req('POST', '/api/sync', report(*tabs), dict(self.EXT, **(headers or {})), port='ext')

    def set_owner(self, *logins):
        with open(os.path.join(self.home, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'owner_logins': list(logins)}, f)

    def test_round_trip_page_to_extension_and_back(self):
        st, d = self.sync(tab(7, 'https://example.org/a', 'A'))
        self.assertEqual((st, d['counts']['stored'], d['commands']), (200, 1, []))
        iid = self.req('GET', '/api/view')[1]['items'][0]['id']
        st, c = self.req('POST', '/api/command', {'action': 'sleep', 'items': [iid]})
        self.assertEqual((st, c['state'], c['steps']), (200, 'pending', [{'do': 'discard', 'tab': 7, 'item': iid, 'url': 'https://example.org/a'}]))
        st, d = self.sync(tab(7, 'https://example.org/a', 'A'))
        self.assertEqual([x['id'] for x in d['commands']], [c['id']])
        self.assertEqual(self.req('POST', '/api/ack', {'id': c['id'], 'ok': True, 'done': 1, 'failed': 0}, self.EXT, port='ext')[0], 200)
        self.timers[0].fn()                                       # the 20-second re-measure, run now
        self.assertEqual(self.req('GET', '/api/view')[1]['commands'][0]['after']['change']['browser_mib'], 0)

    def test_open_asleep_is_in_the_written_steps(self):
        # review finding 7: the flag is part of the plan, not added afterwards
        self.sync(tab(7, 'https://example.org/a'))
        iid = self.req('GET', '/api/view')[1]['items'][0]['id']
        st, c = self.req('POST', '/api/command', {'action': 'open', 'items': [iid], 'group': '논문', 'asleep': True})
        self.assertEqual((c['group'], c['steps'][0]['asleep']), ('논문', True))
        with open(os.path.join(self.home, 'commands.json'), encoding='utf-8') as f:
            self.assertTrue(json.load(f)['commands'][-1]['steps'][0]['asleep'])

    def test_tabs_are_reported_only_on_the_extension_port_by_the_first_extension(self):
        # review finding 3: the page port never takes reports, forwarded requests are refused, and a second extension is refused
        self.assertEqual(self.req('POST', '/api/sync', report(tab(1, 'https://evil.example/x')), self.EXT)[0], 404)
        for headers in ({'Origin': ''}, {'Origin': 'https://evil.example'}, {'Origin': 'chrome-extension://short'},
                        dict(self.EXT, **{'Tailscale-User-Login': 'someone'}), dict(self.EXT, **{'X-Forwarded-For': '100.64.0.9'})):
            self.assertEqual(self.req('POST', '/api/sync', report(tab(1, 'https://evil.example/x')), headers, port='ext')[0], 403, headers)
        self.assertEqual(self.req('POST', '/api/sync', report(), self.EXT, host=self.TS, port='ext')[0], 403)
        self.assertEqual(self.sync(tab(1, 'https://example.org/a'))[0], 200)
        self.assertEqual(self.req('POST', '/api/sync', report(), {'Origin': 'chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'}, port='ext')[0], 403)
        self.assertNotIn('evil.example', json.dumps(self.req('GET', '/api/view')[1]))

    def test_through_tailscale_only_the_owner_gets_in(self):
        # review finding 4
        self.assertEqual(self.req('GET', '/api/view', host=self.TS)[0], 403)                                   # owner not set yet
        self.set_owner('owner@example.com')
        self.assertEqual(self.req('GET', '/api/view', host=self.TS)[0], 403)                                   # tagged device, no login
        self.assertEqual(self.req('GET', '/api/view', host=self.TS, headers={'Tailscale-User-Login': 'other@example.com'})[0], 403)
        self.assertEqual(self.req('GET', '/api/view', host=self.TS, headers={'Tailscale-User-Login': 'owner@example.com'})[0], 200)
        self.assertEqual(self.req('POST', '/api/command', {'action': 'dedupe'}, host=self.TS, headers={'Tailscale-User-Login': 'x@example.com'})[0], 403)
        self.assertEqual(self.req('GET', '/api/view')[0], 200)                                                 # on the computer itself

    def test_posts_need_the_header_and_json(self):
        c = http.client.HTTPConnection('127.0.0.1', self.ports['page'], timeout=5)
        c.request('POST', '/api/command', b'{"action":"dedupe","items":[]}', {'Content-Type': 'text/plain'})
        self.assertEqual(c.getresponse().status, 403)
        c.close()
        self.assertEqual(self.req('POST', '/api/command', {'action': 'dedupe'}, {'X-Mai-Tabs': '0'})[0], 403)
        self.assertEqual(self.req('OPTIONS', '/api/command')[0], 405)

    def test_unknown_host_is_refused(self):
        self.assertEqual(self.req('GET', '/api/view', host='evil.example')[0], 421)
        self.assertEqual(self.req('GET', '/api/view', host='ts.net.evil.example')[0], 421)

    def test_bad_requests_are_400_or_500_never_a_dropped_connection(self):
        self.sync(tab(7, 'https://example.org/a'))
        self.assertEqual(self.req('POST', '/api/command', {'action': 'open', 'items': ['nope']})[0], 400)
        self.assertEqual(self.req('POST', '/api/ack', {'id': 'x'}, self.EXT, port='ext')[0], 400)
        self.assertEqual(self.req('POST', '/api/ack', {'id': 999, 'ok': True}, self.EXT, port='ext')[0], 400)
        self.assertEqual(self.req('POST', '/api/sync', raw=b'{"instance":"browserA1","tabs":[{"id":NaN}]}', headers=self.EXT, port='ext')[0], 400)
        with mock.patch.object(self.app.lib, 'enqueue', side_effect=PermissionError(13, 'in use')):
            st, d = self.req('POST', '/api/command', {'action': 'dedupe'})
        self.assertEqual(st, 500)
        self.assertIn('PermissionError', d['error'])

    def test_page_and_script_are_served_with_a_strict_policy(self):
        c = http.client.HTTPConnection('127.0.0.1', self.ports['page'], timeout=5)
        c.request('GET', '/', headers={'Host': '127.0.0.1'})
        r = c.getresponse()
        page = r.read()
        self.assertIn('탭 보관함'.encode('utf-8'), page)
        self.assertNotIn(b"'unsafe-inline'; style", r.getheader('Content-Security-Policy').encode())
        self.assertIn("script-src 'self';", r.getheader('Content-Security-Policy'))
        self.assertNotIn(b'<script>', page)
        c.close()
        st, js = self.req('GET', '/app.js')
        self.assertEqual(st, 200)
        self.assertIn(b'textContent', js)
        self.assertNotIn(b'innerHTML', js)


if __name__ == '__main__':
    unittest.main()
