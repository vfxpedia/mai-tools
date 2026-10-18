"""Known-answer tests for the mai-approve CLI (M1). Run: python -I tools/mai-approve/tests/test_cli.py

Each test names a case whose answer is known in advance: expired, tampered hash, missing file, out of limits, excluded action,
date-only time, run counts that must not reset, audit log edits. One test runs the real script as a subprocess, the way a launcher does.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, '..', 'mai_approve.py')
sys.path.insert(0, os.path.join(HERE, '..'))
import mai_approve as M  # noqa: E402

T0 = '2026-10-18T02:00:00Z'
UNTIL = '2026-10-24T14:59:00Z'
EULA = ['--eula-accept', '--eula-license', 'NVIDIA Omniverse License', '--eula-subject', 'owner', '--eula-source', 'typed by the owner']


def run(d, *argv, now=T0):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = M.main(['--dir', d, '--now', now] + list(argv))
    text = out.getvalue()
    try:
        data = json.loads(text.strip().splitlines()[-1]) if text.strip().startswith('{') and '\n' not in text.strip() else json.loads(text)
    except Exception:
        data = {}
    return code, data


def grant(d, *extra, scope='lab', until=UNTIL, unattended=True):
    argv = ['grant', '--scope', scope, '--until', until, '--allowed-path', os.path.join(d, 'work'), '--runs-per-unit', '1', '--canary-retries', '1'] + EULA + list(extra)
    if unattended:
        argv.append('--unattended')
    return run(d, *argv)


class Cli(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = self._t.name
        os.makedirs(os.path.join(self.d, 'work', 'a'))

    def tearDown(self):
        self._t.cleanup()

    def check(self, *extra, now=T0, inquiry=False):
        base = [] if inquiry or '--path' in extra else ['--path', os.path.join(self.d, 'work', 'a')]
        unit = [] if inquiry or '--experiment-unit' in extra else ['--experiment-unit', 'u1']
        return run(self.d, 'check', '--scope', 'lab', *(base + unit + list(extra) + (['--inquiry'] if inquiry else [])), now=now)

    def test_grant_then_check_allowed(self):
        self.assertEqual(grant(self.d)[0], 0)
        code, data = self.check('--unattended', '--path', os.path.join(self.d, 'work', 'a'))
        self.assertEqual((code, data['ok']), (0, True))

    def test_exact_valid_until_is_kept(self):
        code, data = grant(self.d)
        self.assertEqual(data['valid_until'], UNTIL)

    def test_expired(self):
        grant(self.d)
        code, data = self.check(now='2026-10-24T14:59:00Z')
        self.assertEqual((code, data['reason']), (2, 'expired'))
        self.assertEqual(self.check(now='2026-10-24T14:58:59Z')[0], 0)

    def test_tampered_hash(self):
        grant(self.d)
        p = os.path.join(self.d, 'lab.json')
        doc = json.load(open(p, encoding='utf-8'))
        doc['limits']['max_runs_per_unit'] = 99
        json.dump(doc, open(p, 'w', encoding='utf-8'))
        code, data = self.check()
        self.assertEqual((code, data['reason']), (2, 'invalid'))
        self.assertIn('sha256', data['text'])

    def test_missing_file(self):
        code, data = self.check()
        self.assertEqual((code, data['reason']), (2, 'missing'))

    def test_out_of_allowed_path(self):
        grant(self.d)
        code, data = self.check('--path', os.path.join(self.d, 'other'))
        self.assertEqual((code, data['reason']), (2, 'path'))
        self.assertEqual(self.check('--path', os.path.join(self.d, 'work2'))[1]['reason'], 'path')

    def test_excluded_action(self):
        grant(self.d)
        code, data = self.check('--action', 'data_deletion')
        self.assertEqual((code, data['reason']), (2, 'excluded'))

    def test_unattended_not_allowed_when_attended_grant(self):
        grant(self.d, unattended=False)
        code, data = self.check('--unattended')
        self.assertEqual((code, data['reason']), (2, 'mode'))

    def test_date_only_is_refused_not_defaulted(self):
        code, data = grant(self.d, until='2026-10-24')
        self.assertEqual((code, data['reason']), (2, 'bad_time'))
        self.assertFalse(os.path.exists(os.path.join(self.d, 'lab.json')))

    def test_window_over_31_days_refused(self):
        code, data = grant(self.d, until='2026-12-01T00:00:00Z')
        self.assertEqual((code, data['reason']), (2, 'invalid'))

    def test_grant_without_eula_accept_refused(self):
        code, data = run(self.d, 'grant', '--scope', 'lab', '--until', UNTIL, '--allowed-path', self.d)
        self.assertEqual((code, data['reason']), (2, 'eula'))

    def test_eula_needs_license_subject_source(self):
        code, data = run(self.d, 'grant', '--scope', 'lab', '--until', UNTIL, '--allowed-path', self.d, '--eula-accept')
        self.assertEqual((code, data['reason']), (2, 'eula'))

    def test_live_grant_cannot_be_overwritten(self):
        grant(self.d)
        code, data = grant(self.d)
        self.assertEqual((code, data['reason']), (2, 'exists'))

    def receipt(self, run_id, kind='normal', unit='unit-b', now=T0):
        return run(self.d, 'receipt', '--scope', 'lab', '--path', os.path.join(self.d, 'work', 'a'), '--experiment-unit', unit, '--attempt-kind', kind, '--run-id', run_id, now=now)

    def test_counts_do_not_reset(self):
        grant(self.d)
        self.assertEqual(self.receipt('r1')[0], 0)
        code, data = self.receipt('r2')
        self.assertEqual((code, data['reason']), (2, 'runs_exhausted'))      # a new run id does not reset
        run(self.d, 'extend', '--scope', 'lab', '--until', '2026-10-25T00:00:00Z')
        code, data = self.receipt('r3')
        self.assertEqual((code, data['reason']), (2, 'runs_exhausted'))      # a renewed approval does not reset
        self.assertEqual(self.receipt('r4', unit='other-unit')[0], 0)       # another unit has its own count
        self.assertEqual(self.receipt('c1', kind='canary_retry')[0], 0)
        code, data = self.receipt('c2', kind='canary_retry')
        self.assertEqual((code, data['reason']), (2, 'canary_exhausted'))

    def test_run_id_reuse_refused(self):
        grant(self.d)
        self.receipt('r1')
        code, data = self.receipt('r1', unit='other-unit')
        self.assertEqual((code, data['reason']), (2, 'run_id_used'))

    def test_revoke_then_check_refused(self):
        grant(self.d)
        self.assertEqual(run(self.d, 'revoke', '--scope', 'lab')[0], 0)
        self.assertEqual(self.check()[1]['reason'], 'missing')

    def test_audit_chain_detects_edit_and_removal(self):
        grant(self.d)
        run(self.d, 'extend', '--scope', 'lab', '--until', '2026-10-25T00:00:00Z')
        run(self.d, 'revoke', '--scope', 'lab')
        self.assertEqual(run(self.d, 'audit-verify')[0], 0)
        p = os.path.join(self.d, 'audit.log')
        lines = open(p, encoding='utf-8').read().splitlines()
        edited = list(lines)
        edited[1] = edited[1].replace('extend', 'grant')
        open(p, 'w', encoding='utf-8').write('\n'.join(edited) + '\n')
        self.assertEqual(run(self.d, 'audit-verify')[0], 2)
        removed = lines[:1] + lines[2:]
        open(p, 'w', encoding='utf-8').write('\n'.join(removed) + '\n')
        self.assertEqual(run(self.d, 'audit-verify')[0], 2)

    def test_real_subprocess_like_a_launcher(self):
        py = [sys.executable, '-I', TOOL, '--dir', self.d]
        g = subprocess.run(py + ['--now', T0, 'grant', '--scope', 'lab', '--until', UNTIL, '--allowed-path', os.path.join(self.d, 'work'), '--unattended'] + EULA, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(g.returncode, 0, g.stderr)
        ok = subprocess.run(py + ['--now', T0, 'check', '--scope', 'lab', '--unattended', '--path', os.path.join(self.d, 'work'), '--experiment-unit', 'u1'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(ok.returncode, 0, ok.stderr)
        late = subprocess.run(py + ['--now', '2026-10-25T00:00:00Z', 'check', '--scope', 'lab', '--inquiry'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(late.returncode, 2)
        self.assertIn('expired', late.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
