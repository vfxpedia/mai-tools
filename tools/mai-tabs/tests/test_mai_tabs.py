"""Known-answer, conformance and mutation tests for mai-tabs M0 and M1. Run: python -I tools/mai-tabs/tests/test_mai_tabs.py

Expected outputs in tests/fixtures (expected.md, expected-proposal.md) were derived by hand from the fixture input before the code ran.
The JavaScript sanitizer and the Python sanitizer run on the same cases and must agree (needs Node.js; a missing Node is a failure, not a skip,
because a skipped conformance test looks like a pass). The browser extension itself is not exercised here: M3 is a real-browser run by the owner.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

try:
    from jsonschema import Draft202012Validator
except ImportError:
    sys.exit('jsonschema is required (pip install jsonschema)')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, ROOT)
from mai_tabs import classify, cli, procs, propose, render, sanitize  # noqa: E402

SCHEMA = os.path.join(ROOT, 'schema', 'export.v1.schema.json')
EX = os.path.join(ROOT, 'schema', 'examples')
FIX = os.path.join(HERE, 'fixtures')
NODE = shutil.which('node')


def readj(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def readt(p):
    with open(p, encoding='utf-8', newline='') as f:
        return f.read()


def validator():
    return Draft202012Validator(readj(SCHEMA))


EXPECTED_REJECTION = {
    'invalid-missing-exported_at.json': ('required', 'exported_at'),
    'invalid-wrong-schema.json': ('const', 'mai-tabs-export-v1'),
    'invalid-url-with-query.json': ('pattern', '?token=SECRET'),
    'invalid-url-with-fragment.json': ('pattern', '#top'),
    'invalid-urls-not-sanitized.json': ('const', 'True'),
    'invalid-time-not-utc.json': ('pattern', '+09:00'),
    'invalid-tab-missing-index.json': ('required', 'index'),
    'invalid-negative-count.json': ('minimum', '0'),
    'invalid-extra-field.json': ('additionalProperties', 'cookies'),
    'invalid-url-id-not-hex.json': ('pattern', 'NOT-HEX'),
    'invalid-collection-complete-not-bool.json': ('type', 'boolean'),
}
SEMANTIC = ('semantic-counts-mismatch.json', 'semantic-unknown-group.json')

# input URL -> expected sanitized URL, fixed from the rules in DESIGN.md before the code was written
SANITIZE_CASES = [
    ('https://github.com/example/repo/pull/5?tab=files#diff-1', 'https://github.com/example/repo/pull/5'),
    ('https://example.com', 'https://example.com/'),
    ('https://example.com/a?x=1', 'https://example.com/a'),
    ('https://example.com/#top', 'https://example.com/'),
    ('https://EXAMPLE.com/Path', 'https://example.com/Path'),
    ('https://example.com:443/a', 'https://example.com/a'),
    ('http://example.com:80/a', 'http://example.com/a'),
    ('https://example.com:8443/a', 'https://example.com:8443/a'),
    ('https://user:pw@example.com/a?t=1', 'https://example.com/a'),
    ('https://claude.ai/chat/0f3a9c1e-1111-2222-3333-444455556666?utm=x', 'https://claude.ai/chat/_redacted_'),
    ('https://example.com/docs/abcdefghijklmnopqrstuvwxyzabcdef', 'https://example.com/docs/abcdefghijklmnopqrstuvwxyzabcdef'),   # no digit: kept
    ('https://example.com/a%20b', 'https://example.com/a%20b'),
    ('https://example.com/a b', 'https://example.com/a%20b'),
    ('https://example.com/%ED%95%9C%EA%B8%80', 'https://example.com/%ED%95%9C%EA%B8%80'),
    ('https://example.com/\ud55c\uae00?q=1', 'https://example.com/%ED%95%9C%EA%B8%80'),
    ('chrome://settings/?search=x', 'chrome://settings/'),
    ('chrome-extension://abcdefghijklmnopabcdefghijklmnop/popup.html#x', 'chrome-extension://abcdefghijklmnopabcdefghijklmnop/popup.html'),
    ('file:///C:/Users/someone/Desktop/report.html?x=1', 'file:///.../report.html'),
    ('about:blank', 'about:blank'),
    ('data:text/html,<h1>secret</h1>', 'data:'),
    ('javascript:alert(1)', 'javascript:'),
    ('mailto:a@b.com?subject=x', 'mailto:'),
    ('not a url', ''),
    ('', ''),
]


class ContractTests(unittest.TestCase):
    def test_schema_valid(self):
        Draft202012Validator.check_schema(readj(SCHEMA))

    def test_examples_present(self):
        names = os.listdir(EX)
        self.assertEqual(sorted(n for n in names if n.startswith('invalid-')), sorted(EXPECTED_REJECTION))
        self.assertEqual(sorted(n for n in names if n.startswith('semantic-')), sorted(SEMANTIC))
        self.assertGreaterEqual(len([n for n in names if n.startswith('valid-')]), 3)

    def test_valid_examples_pass(self):
        v = validator()
        for n in sorted(os.listdir(EX)):
            if n.startswith('valid-') or n.startswith('semantic-'):
                d = readj(os.path.join(EX, n))
                self.assertEqual([e.message for e in v.iter_errors(d)], [], n)
                if n.startswith('valid-'):
                    self.assertEqual(render.consistency_problems(d), [], n)

    def test_invalid_rejected_for_the_stated_reason(self):
        v = validator()
        for n, (kw, text) in EXPECTED_REJECTION.items():
            errs = list(v.iter_errors(readj(os.path.join(EX, n))))
            self.assertTrue(errs, n + ' was accepted')
            self.assertTrue(any(e.validator == kw and text in e.message for e in errs), '%s: %s' % (n, [(e.validator, e.message) for e in errs]))

    def test_semantic_examples_fail_the_consistency_check(self):
        for n in SEMANTIC:
            self.assertTrue(render.consistency_problems(readj(os.path.join(EX, n))), n)

    def test_mutation_url_pattern_removed(self):
        s = readj(SCHEMA)
        del s['properties']['windows']['items']['properties']['tabs']['items']['properties']['url']['pattern']
        self.assertEqual(list(Draft202012Validator(s).iter_errors(readj(os.path.join(EX, 'invalid-url-with-query.json')))), [])

    def test_mutation_urls_sanitized_const_removed(self):
        s = readj(SCHEMA)
        s['properties']['urls_sanitized'] = {'type': 'boolean'}
        self.assertEqual(list(Draft202012Validator(s).iter_errors(readj(os.path.join(EX, 'invalid-urls-not-sanitized.json')))), [])


def node_json(script, payload):
    p = subprocess.run([NODE, '-e', script], input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8')
    if p.returncode != 0:
        raise AssertionError('node failed: ' + p.stderr)
    return json.loads(p.stdout)


JS_SANITIZE = ("const m=require(%r);let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{const c=JSON.parse(s);"
               "console.log(JSON.stringify(c.map(u=>m.sanitizeUrl(u))))})" % os.path.join(ROOT, 'extension', 'export.js').replace(os.sep, '/'))
JS_BUILD = ("const m=require(%r);let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{console.log(JSON.stringify(m.buildExport(JSON.parse(s))))})"
            % os.path.join(ROOT, 'extension', 'export.js').replace(os.sep, '/'))


class SanitizeTests(unittest.TestCase):
    def test_python_known_answers(self):
        for url, want in SANITIZE_CASES:
            self.assertEqual(sanitize.sanitize_url(url), want, url)

    def test_javascript_known_answers(self):
        self.assertIsNotNone(NODE, 'Node.js is required for the conformance test')
        got = node_json(JS_SANITIZE, [u for u, _ in SANITIZE_CASES])
        for (url, want), g in zip(SANITIZE_CASES, got):
            self.assertEqual(g, want, 'JavaScript: ' + url)

    def test_sanitizing_twice_changes_nothing(self):
        for url, want in SANITIZE_CASES:
            self.assertEqual(sanitize.sanitize_url(want), want, want)

    def test_redaction_can_be_switched_off(self):
        self.assertEqual(sanitize.sanitize_url('https://claude.ai/chat/0f3a9c1e-1111-2222-3333-444455556666?x=1', redact_long_segments=False),
                         'https://claude.ai/chat/0f3a9c1e-1111-2222-3333-444455556666')


class PipelineTests(unittest.TestCase):
    """Browser-shaped input -> JavaScript export -> schema -> Python Markdown, against hand-derived expected files."""

    def export(self):
        self.assertIsNotNone(NODE, 'Node.js is required')
        return node_json(JS_BUILD, readj(os.path.join(FIX, 'browser-input.json')))

    def test_export_validates_and_has_no_secrets(self):
        e = self.export()
        self.assertEqual(list(validator().iter_errors(e)), [])
        self.assertEqual(render.consistency_problems(e), [])
        text = json.dumps(e)
        for secret in ('SECRET', 'pw@', 'utm=', 'tab=files', '#frag', '0f3a9c1e', 'abcdefghijklmnopqrstuvwxyz0123456789'):
            self.assertNotIn(secret, text)
        self.assertEqual(e['counts'], {'windows': 2, 'tabs': 8, 'groups': 1})
        tabs = [t for w in e['windows'] for t in w['tabs']]
        self.assertEqual([t['group_id'] for t in tabs], [None, 7, None, None, None, None, None, 7])      # groupId -1 means no group

    def test_markdown_matches_the_hand_derived_file_byte_for_byte(self):
        e = self.export()
        rules = classify.load_rules(cli.DEFAULT_RULES)
        self.assertEqual(render.render(e, rules), readt(os.path.join(FIX, 'expected.md')))

    def test_markdown_has_no_query_fragment_or_em_dash(self):
        md = render.render(self.export(), classify.load_rules(cli.DEFAULT_RULES))
        self.assertNotIn('?', md.replace('Cleanup', ''))
        self.assertNotIn('#frag', md)
        self.assertNotIn('\u2014', md)

    def test_renderer_sanitizes_again_when_given_a_dirty_export(self):
        e = self.export()
        e['windows'][0]['tabs'][0]['url'] = 'https://example.com/x?token=SECRET#frag'
        md = render.render(e, classify.load_rules(cli.DEFAULT_RULES))
        self.assertNotIn('SECRET', md)
        self.assertIn('https://example.com/x)', md)

    def test_proposal_matches_the_hand_derived_file(self):
        text, counts = propose.propose(self.export(), 14)
        self.assertEqual(text, readt(os.path.join(FIX, 'expected-proposal.md')))
        self.assertEqual(counts, {'duplicates_extra': 1, 'stale': 1})

    def test_pinned_and_audible_tabs_are_never_proposed(self):
        e = self.export()
        for t in e['windows'][0]['tabs'] + e['windows'][1]['tabs']:
            t['last_accessed_ms'] = 1000          # ancient
        text, _ = propose.propose(e, 14)
        self.assertNotIn('Pull request', text)        # pinned
        self.assertNotIn('Music', text)               # audible

    def test_cli_writes_the_file_and_refuses_an_inconsistent_export(self):
        with tempfile.TemporaryDirectory() as d:
            ep = os.path.join(d, 'export.json')
            with open(ep, 'w', encoding='utf-8') as f:
                json.dump(self.export(), f)
            out = os.path.join(d, 'out.md')
            code = 'import sys; sys.path.insert(0, %r); from mai_tabs.cli import main; sys.exit(main(sys.argv[1:]))' % ROOT
            r = subprocess.run([sys.executable, '-c', code, 'render', ep, '--out', out], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(readt(out), readt(os.path.join(FIX, 'expected.md')))
            bad = readj(os.path.join(EX, 'semantic-counts-mismatch.json'))
            with open(ep, 'w', encoding='utf-8') as f:
                json.dump(bad, f)
            r = subprocess.run([sys.executable, '-c', code, 'render', ep], capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('inconsistent', r.stderr)


JS_SHA = ("const m=require(%r);let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{console.log(JSON.stringify(JSON.parse(s).map(x=>m.sha256Hex(x))))})"
          % os.path.join(ROOT, 'extension', 'export.js').replace(os.sep, '/'))
JS_CONSISTENCY = ("const m=require(%r);let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{console.log(JSON.stringify(JSON.parse(s).map(x=>m.consistencyProblems(x))))})"
                  % os.path.join(ROOT, 'extension', 'export.js').replace(os.sep, '/'))


def tab(tid, index, title, url, uid, **kw):
    t = {'id': tid, 'index': index, 'title': title, 'url': url, 'url_id': uid, 'pinned': False, 'audible': False, 'discarded': False,
         'group_id': None, 'last_accessed_ms': 1792296000000 - 86400000 * 30}
    t.update(kw)
    return t


def export_of(*tabs):
    return {'schema': 'mai-tabs-export-v1', 'exported_at': '2026-10-18T04:00:00Z', 'browser': {'name': 'chrome', 'version': '1'}, 'urls_sanitized': True,
            'counts': {'windows': 1, 'tabs': len(tabs), 'groups': 0}, 'windows': [{'id': 1, 'focused': True, 'tabs': list(tabs)}], 'groups': []}


class ReviewFindingsTests(unittest.TestCase):
    """independent review T1 to T4, with the probes the reviewer used."""

    def test_t1_audible_duplicate_is_protected(self):
        e = export_of(tab(1, 0, 'Old audible', 'https://e.com/a', 'a' * 16, audible=True), tab(2, 1, 'Newer silent', 'https://e.com/a', 'a' * 16, last_accessed_ms=1792296000000 - 1000))
        text, counts = propose.propose(e, 14)
        self.assertEqual(counts['duplicates_extra'], 1)
        self.assertIn('close candidate: window 1 tab 1 (id 2)', text)
        self.assertNotIn('close candidate: window 1 tab 0', text)
        self.assertIn('same page as window 1 tab 0 (id 1), which stays', text)

    def test_t1_two_protected_copies_give_no_candidate(self):
        e = export_of(tab(1, 0, 'A', 'https://e.com/a', 'a' * 16, audible=True), tab(2, 1, 'B', 'https://e.com/a', 'a' * 16, pinned=True))
        self.assertEqual(propose.propose(e, 14)[1], {'duplicates_extra': 0, 'stale': 0})

    def test_t2_different_queries_are_not_duplicates(self):
        raw = readj(os.path.join(FIX, 'browser-input.json'))
        raw['windows'] = [{'id': 1, 'focused': True, 'tabs': [
            {'id': 1, 'index': 0, 'title': 'First', 'url': 'https://www.youtube.com/watch?v=FIRST', 'lastAccessed': 1},
            {'id': 2, 'index': 1, 'title': 'Second', 'url': 'https://www.youtube.com/watch?v=SECOND', 'lastAccessed': 1}]}]
        raw['groups'] = []
        e = node_json(JS_BUILD, raw)
        self.assertEqual(e['windows'][0]['tabs'][0]['url'], e['windows'][0]['tabs'][1]['url'])
        self.assertNotEqual(e['windows'][0]['tabs'][0]['url_id'], e['windows'][0]['tabs'][1]['url_id'])
        text, counts = propose.propose(e, 14)
        self.assertEqual(counts['duplicates_extra'], 0)
        self.assertIn('they are 2 different pages', text)

    def test_t2_without_identity_nothing_is_proposed_from_address_equality(self):
        e = export_of(tab(1, 0, 'A', 'https://e.com/a', None), tab(2, 1, 'B', 'https://e.com/a', None))
        text, counts = propose.propose(e, 14)
        self.assertEqual(counts['duplicates_extra'], 0)
        self.assertIn('identity is unknown', text)

    def test_t2_same_full_address_gives_same_identity(self):
        raw = {'browser': {'name': 'chrome', 'version': '1'}, 'nowIso': '2026-10-18T04:00:00Z', 'groups': [], 'windows': [{'id': 1, 'focused': True, 'tabs': [
            {'id': 1, 'index': 0, 'title': 'a', 'url': 'https://e.com/a?x=1'}, {'id': 2, 'index': 1, 'title': 'b', 'url': 'https://e.com/a?x=1'},
            {'id': 3, 'index': 2, 'title': 'c', 'url': 'https://e.com/a?x=1#frag'}]}]}
        ids = [t['url_id'] for t in node_json(JS_BUILD, raw)['windows'][0]['tabs']]
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[0], ids[2])

    def test_t3_untrusted_title_never_becomes_raw_html(self):
        title = '<img src="https://example.invalid/TEST_ONLY"> *bold* `code` [x](javascript:alert(1))'
        e = export_of(tab(1, 0, title, 'https://e.com/a(b)', 'a' * 16, group_id=None))
        md = render.render(e, classify.load_rules(cli.DEFAULT_RULES))
        self.assertNotIn('<img', md)
        self.assertNotIn('<', md.replace('<', '', 0).split('Open tabs')[1].replace('&lt;', ''))
        self.assertIn('&lt;img', md)
        self.assertIn('https://e.com/a%28b%29', md)
        self.assertNotIn('](javascript:', md)

    def test_t3_control_characters_are_removed(self):
        e = export_of(tab(1, 0, 'a\x00b\x1b[31mred\nline', 'https://e.com/a', 'a' * 16))
        md = render.render(e, classify.load_rules(cli.DEFAULT_RULES))
        self.assertNotIn('\x00', md)
        self.assertNotIn('\x1b', md)

    def test_t4_group_query_failure_is_marked_incomplete_and_stays_consistent(self):
        raw = readj(os.path.join(FIX, 'browser-input.json'))
        raw['groups'] = []
        raw['groupsError'] = 'Permission denied'
        e = node_json(JS_BUILD, raw)
        self.assertFalse(e['collection']['complete'])
        self.assertIn('Permission denied', ' '.join(e['collection']['notes']))
        self.assertEqual(render.consistency_problems(e), [])
        self.assertEqual(list(validator().iter_errors(e)), [])

    def test_t4_unsupported_groups_api_is_a_note_not_a_failure(self):
        raw = readj(os.path.join(FIX, 'browser-input.json'))
        raw['groups'] = []
        raw['groupsSupported'] = False
        for w in raw['windows']:
            for t in w['tabs']:
                t['groupId'] = -1
        e = node_json(JS_BUILD, raw)
        self.assertTrue(e['collection']['complete'])
        self.assertIn('no tab groups API', ' '.join(e['collection']['notes']))

    def test_t4_javascript_and_python_consistency_checks_agree(self):
        exports = [readj(os.path.join(EX, n)) for n in sorted(os.listdir(EX)) if n.startswith(('valid-', 'semantic-'))]
        js = node_json(JS_CONSISTENCY, exports)
        for e, got in zip(exports, js):
            self.assertEqual(got, render.consistency_problems(e))

    def test_sha256_matches_python_on_boundaries_and_unicode(self):
        import hashlib
        cases = ['', 'abc', 'x' * 55, 'x' * 56, 'x' * 63, 'x' * 64, 'x' * 65, 'x' * 1000, 'https://e.com/한글?q=\U0001f600']
        got = node_json(JS_SHA, cases)
        for c, g in zip(cases, got):
            self.assertEqual(g, hashlib.sha256(c.encode('utf-8')).hexdigest(), repr(c[:20]))

    def test_verify_command_compares_with_the_expected_count(self):
        with tempfile.TemporaryDirectory() as d:
            ep = os.path.join(d, 'e.json')
            with open(ep, 'w', encoding='utf-8') as f:
                json.dump(export_of(tab(1, 0, 'A', 'https://e.com/a', 'a' * 16)), f)
            code = 'import sys; sys.path.insert(0, %r); from mai_tabs.cli import main; sys.exit(main(sys.argv[1:]))' % ROOT
            ok = subprocess.run([sys.executable, '-c', code, 'verify', ep, '--expect-tabs', '1'], capture_output=True, text=True, encoding='utf-8')
            bad = subprocess.run([sys.executable, '-c', code, 'verify', ep, '--expect-tabs', '5'], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual((ok.returncode, bad.returncode), (0, 2))
            self.assertIn('tabs 1', ok.stdout)


class ClassifyTests(unittest.TestCase):
    RULES = {'schema': 'mai-tabs-rules-v1', 'default': 'other', 'categories': [
        {'name': 'a', 'match': [{'host': 'example.com'}]},
        {'name': 'b', 'match': [{'host_suffix': 'example.com'}, {'title_contains': 'Hello'}]},
        {'name': 'c', 'match': [{'url_prefix': 'https://x.org/docs/'}]}]}

    def test_first_matching_category_wins(self):
        self.assertEqual(classify.classify(self.RULES, 'https://example.com/', ''), 'a')
        self.assertEqual(classify.classify(self.RULES, 'https://www.example.com/', ''), 'b')

    def test_host_is_exact_and_suffix_is_suffix(self):
        self.assertEqual(classify.classify(self.RULES, 'https://notexample.com/', ''), 'b')      # suffix matches by design
        self.assertEqual(classify.classify({'schema': 'mai-tabs-rules-v1', 'categories': [{'name': 'a', 'match': [{'host': 'example.com'}]}]},
                                           'https://www.example.com/', ''), 'uncategorized')

    def test_title_and_prefix_rules(self):
        self.assertEqual(classify.classify(self.RULES, 'https://z.org/', 'say hello there'), 'b')
        self.assertEqual(classify.classify(self.RULES, 'https://x.org/docs/a', ''), 'c')
        self.assertEqual(classify.classify(self.RULES, 'https://x.org/other', ''), 'other')

    def test_bad_rules_are_refused(self):
        for bad in ({}, {'schema': 'mai-tabs-rules-v1'}, {'schema': 'mai-tabs-rules-v1', 'categories': [{'name': 'a', 'match': [{'host': 'x', 'host_suffix': 'y'}]}]},
                    {'schema': 'mai-tabs-rules-v1', 'categories': [{'name': 'a', 'match': [{'host': 'x'}]}, {'name': 'a', 'match': [{'host': 'y'}]}]},
                    {'schema': 'mai-tabs-rules-v1', 'categories': [{'name': '', 'match': [{'host': 'x'}]}]}):
            with self.assertRaises(classify.RulesError):
                classify.check_rules(bad)

    def test_default_rules_file_is_valid(self):
        classify.load_rules(cli.DEFAULT_RULES)


class ProcsTests(unittest.TestCase):
    ROWS = [{'pid': 1, 'name': 'chrome.exe', 'rss': 300 * 1048576, 'type': 'browser'},
            {'pid': 2, 'name': 'chrome.exe', 'rss': 200 * 1048576, 'type': 'renderer'},
            {'pid': 3, 'name': 'chrome.exe', 'rss': 100 * 1048576, 'type': 'renderer'},
            {'pid': 4, 'name': 'chrome.exe', 'rss': 50 * 1048576, 'type': 'gpu-process'}]

    def test_summary_known_answer(self):
        s = procs.summarize(self.ROWS)
        self.assertEqual((s['count'], s['rss_mib']), (4, 650.0))
        self.assertEqual([(g['type'], g['count'], g['rss_mib']) for g in s['by_type']],
                         [('browser', 1, 300.0), ('renderer', 2, 300.0), ('gpu-process', 1, 50.0)])

    def test_process_type_from_command_line(self):
        self.assertEqual(procs.process_type(['chrome.exe', '--type=renderer', '--x']), 'renderer')
        self.assertEqual(procs.process_type(['chrome.exe']), 'browser')
        self.assertEqual(procs.process_type(None), 'browser')

    def test_report_never_shows_a_gpu_figure(self):
        text = procs.render(procs.summarize(self.ROWS))
        self.assertIn('No GPU figure', text)
        self.assertNotIn('\u2014', text)

    def test_real_collect_is_read_only_and_well_shaped(self):
        try:
            import psutil  # noqa: F401
        except ImportError:
            if os.environ.get('MAI_TOOLS_STRICT') == '1':
                self.fail('psutil is required in strict mode (pip install psutil)')
            self.skipTest('psutil is not installed; set MAI_TOOLS_STRICT=1 to make this a failure')
        rows = procs.collect_rows()
        for r in rows:
            self.assertEqual(set(r), {'pid', 'name', 'rss', 'type'})


MUTATIONS = [
    ('renderer stops sanitizing', render, 'sanitize_url', lambda u, *a, **k: u, [PipelineTests]),
    ('host rule becomes substring', classify, '_rule_matches',
     lambda rule, url, title: (list(rule.values())[0].lower() in url.lower()) if 'host' in rule else False, [ClassifyTests, PipelineTests]),
    ('categories tried in reverse order', classify, 'classify',
     lambda rules, url, title: next((c['name'] for c in reversed(rules['categories']) if any(classify._rule_matches(r, url, title) for r in c['match'])),
                                    rules.get('default', 'uncategorized')), [ClassifyTests]),
    ('long segments never redacted', sanitize, 'redact_segment', lambda seg: seg, [SanitizeTests, PipelineTests]),
    ('protected tabs can be close candidates', propose, 'protected', lambda t: False, [ReviewFindingsTests, PipelineTests]),
    ('duplicates decided by the shown address', propose, 'flatten', lambda export: [dict(x, url_id=x['url']) for x in render.flatten(export)], [ReviewFindingsTests, PipelineTests]),
    ('titles are not escaped for HTML', render, 'md_text', lambda text: str(text or '(no title)'), [ReviewFindingsTests, PipelineTests]),
    ('process types merged', procs, 'process_type', lambda cmd: 'browser', [ProcsTests]),
    ('proposal ignores pinned flag', propose, 'propose',
     lambda export, stale_days=14: (propose_unpinned(export, stale_days)), [PipelineTests]),
]


def propose_unpinned(export, stale_days):
    for w in export['windows']:
        for t in w['tabs']:
            t['pinned'] = False
            t['audible'] = False
    return _orig_propose(export, stale_days)


_orig_propose = propose.propose


class MutationTests(unittest.TestCase):
    def test_each_broken_rule_makes_its_suite_fail(self):
        for label, module, attr, replacement, suites in MUTATIONS:
            with self.subTest(label):
                failed = False
                with mock.patch.object(module, attr, replacement):
                    for s in suites:
                        res = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestLoader().loadTestsFromTestCase(s))
                        failed = failed or not res.wasSuccessful()
                self.assertTrue(failed, 'the suites still pass with the rule broken: ' + label)


if __name__ == '__main__':
    unittest.main(verbosity=2)
