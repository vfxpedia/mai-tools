"""Tests for the independent review findings A1 to A6 on mai-approve. Run: python -I tools/mai-approve/tests/test_hardening.py

Each test reproduces the probe that the reviewer used and expects the refusal. They use fixtures in a temporary folder only; the real
~/.mai/approvals is never touched. A missing jsonschema is a failure, not a skip.
"""
import contextlib
import copy
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest

try:
    from jsonschema import Draft202012Validator
except ImportError:
    sys.exit('jsonschema is required (pip install jsonschema)')

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.abspath(os.environ.get('MAI_APPROVE_TOOL') or os.path.join(HERE, '..', 'mai_approve.py'))
sys.path.insert(0, os.path.dirname(TOOL))
import mai_approve as M  # noqa: E402

SCHEMA = json.load(open(os.path.join(HERE, '..', 'schema', 'approval.v1.schema.json'), encoding='utf-8'))
EX = os.path.join(HERE, '..', 'schema', 'examples')
T0 = '2026-10-18T02:00:00Z'
UNTIL = '2026-10-24T14:59:00Z'
EULA = ['--eula-accept', '--eula-license', 'NVIDIA Omniverse License', '--eula-subject', 'owner', '--eula-source', 'typed by owner']


def run(d, *argv, now=T0):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = M.main(['--dir', d, '--now', now] + list(argv))
    text = out.getvalue().strip()
    try:
        data = json.loads(text)
    except Exception:
        data = {}
    return code, data


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._t.name)
        self.d = os.path.join(self.root, 'store')
        self.work = os.path.join(self.root, 'work')
        os.makedirs(os.path.join(self.work, 'a'))
        self.outside = os.path.join(self.root, 'outside')
        os.makedirs(self.outside)

    def tearDown(self):
        self._t.cleanup()

    def grant(self, *extra, runs='1', canary='1'):
        code, data = run(self.d, 'grant', '--scope', 'lab', '--until', UNTIL, '--allowed-path', self.work, '--runs-per-unit', runs,
                         '--canary-retries', canary, '--unattended', *EULA, *extra)
        self.assertEqual(code, 0, data)

    def receipt(self, run_id, unit='u1', kind='normal', extra=()):
        return run(self.d, 'receipt', '--scope', 'lab', '--path', os.path.join(self.work, 'a'), '--experiment-unit', unit,
                   '--attempt-kind', kind, '--run-id', run_id, *extra)

    def reseal(self, mutate):
        p = os.path.join(self.d, 'lab.json')
        with open(p, encoding='utf-8') as f:
            doc = json.load(f)
        mutate(doc)
        doc['sha256'] = M.canon_hash(doc)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(doc, f)


class A1RunIdTraversal(Base):
    def test_traversal_absolute_and_separators_are_refused(self):
        self.grant()
        marker = os.path.join(self.root, 'escaped-fixture.json')
        for bad in ('../../../escaped-fixture', '..', '../x', 'a/b', 'a\\b', os.path.join(self.outside, 'abs'), '.hidden', '', 'x' * 200):
            code, data = self.receipt(bad)
            self.assertEqual((code, data.get('reason')), (2, 'run_id'), repr(bad))
        self.assertFalse(os.path.exists(marker))
        self.assertEqual(os.listdir(self.outside), [])
        self.assertEqual(os.listdir(os.path.join(self.d, 'receipts', 'lab')), [])

    def test_good_run_id_still_works(self):
        self.grant()
        self.assertEqual(self.receipt('r-20261018.01_a')[0], 0)


class A2Concurrency(Base):
    def test_only_one_of_many_simultaneous_launchers_gets_the_last_run(self):
        for rnd in range(3):
            self.grant() if rnd == 0 else None
            unit = 'race%d' % rnd
            go = os.path.join(self.root, 'go%d' % rnd)
            code = ('import os,sys,time\nsys.path.insert(0,%r)\nimport mai_approve as M\n'
                    'go=%r\nwhile not os.path.exists(go): time.sleep(0.001)\n'
                    'sys.exit(M.main(["--dir",%r,"--now",%r,"receipt","--scope","lab","--path",%r,"--experiment-unit",%r,"--run-id",sys.argv[1]]))'
                    % (os.path.dirname(TOOL), go, self.d, T0, os.path.join(self.work, 'a'), unit))
            procs = [subprocess.Popen([sys.executable, '-I', '-c', code, 'p%d_%d' % (rnd, i)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(8)]
            time.sleep(1.0)
            open(go, 'w').close()
            results = [p.wait(timeout=60) for p in procs]
            for p in procs:
                p.stdout.close()
                p.stderr.close()
            self.assertEqual(results.count(0), 1, 'round %d: exit codes %s' % (rnd, results))
            files = [n for n in os.listdir(os.path.join(self.d, 'receipts', 'lab')) if n.startswith('p%d_' % rnd)]
            self.assertEqual(len(files), 1, files)
        n, head, problem = M.audit_verify(self.d)
        self.assertIsNone(problem)

    def test_finish_does_not_free_a_run(self):
        self.grant()
        self.assertEqual(self.receipt('r1')[0], 0)
        self.assertEqual(run(self.d, 'finish', '--scope', 'lab', '--run-id', 'r1', '--status', 'aborted')[0], 0)
        self.assertEqual(self.receipt('r2')[1]['reason'], 'runs_exhausted')
        rec = json.load(open(os.path.join(self.d, 'receipts', 'lab', 'r1.json'), encoding='utf-8'))
        self.assertEqual(rec['status'], 'aborted')


class A3CorruptReceipts(Base):
    def test_corrupt_or_foreign_receipts_stop_counting(self):
        self.grant()
        rdir = os.path.join(self.d, 'receipts', 'lab')
        os.makedirs(rdir, exist_ok=True)
        cases = {'previous.json': '{not json', 'odd.json': json.dumps({'schema': 'something-else'}),
                 'mismatch.json': json.dumps({'schema': 'mai-run-receipt-v1', 'run_id': 'other', 'experiment_unit_id': 'u1', 'attempt_kind': 'normal',
                                              'approval_sha256': 'a' * 64, 'started_at': T0}),
                 'empty.json': ''}
        for name, body in cases.items():
            path = os.path.join(rdir, name)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(body)
            code, data = self.receipt('fresh-' + name[:-5])
            self.assertEqual((code, data.get('reason')), (2, 'receipt_corrupt'), name)
            os.remove(path)
        self.assertEqual(self.receipt('fresh-ok')[0], 0)


class A4RuntimeContract(Base):
    def test_resealed_invalid_values_are_refused_without_traceback(self):
        self.grant()
        for label, mutate in (('negative runs', lambda d: d['limits'].update(max_runs_per_unit=-1)),
                              ('string runs', lambda d: d['limits'].update(max_runs_per_unit='x')),
                              ('bool runs', lambda d: d['limits'].update(max_runs_per_unit=True)),
                              ('devices type', lambda d: d['limits'].update(devices='GPU-0')),
                              ('unknown exclusion', lambda d: d.update(exclusions=['everything'])),
                              ('unknown field', lambda d: d.update(auto_renew=True)),
                              ('eula key missing', lambda d: d['eula'].pop('license')),
                              ('allowed_paths string', lambda d: d['limits'].update(allowed_paths='/x')),
                              ('granted_by list', lambda d: d.update(granted_by=[])),
                              ('limits null', lambda d: d.update(limits=None)),
                              ('exclusions null', lambda d: d.update(exclusions=None))):
            with self.subTest(label):
                self.grant() if not os.path.exists(os.path.join(self.d, 'lab.json')) else None
                self.reseal(mutate)
                code, data = run(self.d, 'check', '--scope', 'lab', '--inquiry')
                self.assertEqual((code, data.get('reason')), (2, 'invalid'), label)
                os.remove(os.path.join(self.d, 'lab.json'))

    def test_runtime_never_accepts_what_the_json_schema_rejects(self):
        v = Draft202012Validator(SCHEMA)
        rnd = random.Random(7)
        base = json.load(open(os.path.join(EX, 'valid-full.json'), encoding='utf-8'))
        wrong = [None, -1, 0, 1.5, 'x', '', [], {}, True, ['a'], 'GPU-0']
        paths = [('scope',), ('granted_by',), ('granted_by', 'os_user'), ('eula',), ('eula', 'accepted'), ('eula', 'license'), ('execution_mode',),
                 ('limits',), ('limits', 'allowed_paths'), ('limits', 'devices'), ('limits', 'max_runs_per_unit'), ('limits', 'canary_retries'),
                 ('limits', 'count_per'), ('exclusions',), ('note',), ('method',)]
        checked = 0
        for _ in range(400):
            doc = copy.deepcopy(base)
            path = rnd.choice(paths)
            cur = doc
            for k in path[:-1]:
                cur = cur[k]
            cur[path[-1]] = rnd.choice(wrong)
            doc['sha256'] = M.canon_hash(doc) if isinstance(doc, dict) else ''
            schema_ok = not list(v.iter_errors(doc))
            runtime_ok = M.validate(doc) == []
            self.assertFalse(runtime_ok and not schema_ok, 'runtime accepts what the schema rejects: %s -> %r' % (path, cur[path[-1]]))
            self.assertEqual(runtime_ok, schema_ok, 'runtime and schema disagree: %s -> %r' % (path, cur[path[-1]]))
            checked += 1
        self.assertEqual(checked, 400)

    def test_every_example_agrees(self):
        v = Draft202012Validator(SCHEMA)
        for n in sorted(os.listdir(EX)):
            if n.startswith('valid-') or n.startswith('invalid-'):
                if n.startswith('receipt'):
                    continue
                d = json.load(open(os.path.join(EX, n), encoding='utf-8'))
                self.assertEqual(M.validate(d) == [], not list(v.iter_errors(d)) and n.startswith('valid-'), n)


class A5RequestMustBeStated(Base):
    def test_run_request_without_path_or_unit_is_refused(self):
        self.grant()
        self.assertEqual(run(self.d, 'check', '--scope', 'lab', '--experiment-unit', 'u1')[1]['reason'], 'path_required')
        self.assertEqual(run(self.d, 'check', '--scope', 'lab', '--path', self.work)[1]['reason'], 'unit_required')
        self.assertEqual(run(self.d, 'receipt', '--scope', 'lab', '--run-id', 'r1')[1]['reason'], 'path_required')
        self.assertEqual(run(self.d, 'check', '--scope', 'lab', '--inquiry')[0], 0)

    def test_devices_are_matched_against_the_request(self):
        self.grant('--device', 'GPU-0')
        base = ['check', '--scope', 'lab', '--path', self.work, '--experiment-unit', 'u1']
        self.assertEqual(run(self.d, *base)[1]['reason'], 'device_required')
        self.assertEqual(run(self.d, *base, '--device', 'GPU-1')[1]['reason'], 'device')
        self.assertEqual(run(self.d, *base, '--device', 'GPU-0', '--device', 'GPU-1')[1]['reason'], 'device')
        self.assertEqual(run(self.d, *base, '--device', 'GPU-0')[0], 0)

    def make_link(self, link, target):
        if os.name == 'nt':
            r = subprocess.run(['cmd', '/c', 'mklink', '/J', link, target], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, 'could not create a junction for the test: ' + r.stdout + r.stderr)
        else:
            os.symlink(target, link)

    def test_link_inside_allowed_folder_pointing_outside_is_refused(self):
        self.grant()
        link = os.path.join(self.work, 'escape')
        self.make_link(link, self.outside)
        code, data = run(self.d, 'check', '--scope', 'lab', '--path', os.path.join(link, 'secret.txt'), '--experiment-unit', 'u1')
        self.assertEqual((code, data.get('reason')), (2, 'path'))
        self.assertEqual(run(self.d, 'check', '--scope', 'lab', '--path', os.path.join(self.work, 'a'), '--experiment-unit', 'u1')[0], 0)

    def test_dotdot_inside_the_request_is_resolved(self):
        self.grant()
        sneaky = os.path.join(self.work, 'a', '..', '..', 'outside')
        self.assertEqual(run(self.d, 'check', '--scope', 'lab', '--path', sneaky, '--experiment-unit', 'u1')[1]['reason'], 'path')


class A7ForeignPathNotation(Base):
    """An approval written on one OS is not read on another as if it covered the same place (finding A7)."""

    def foreign(self):
        return '/data/run' if os.name == 'nt' else 'C:/lab/runs'

    def test_request_in_another_oss_notation_is_refused(self):
        self.grant()
        code, data = run(self.d, 'check', '--scope', 'lab', '--path', self.foreign() + '/child', '--experiment-unit', 'u1')
        self.assertEqual((code, data.get('reason')), (2, 'foreign_path_notation'))

    def test_approval_carrying_another_oss_paths_is_refused_even_for_a_native_request(self):
        self.grant()
        self.reseal(lambda doc: doc['limits'].update(allowed_paths=[self.foreign(), self.work]))
        code, data = run(self.d, 'check', '--scope', 'lab', '--path', os.path.join(self.work, 'a'), '--experiment-unit', 'u1')
        self.assertEqual((code, data.get('reason')), (2, 'foreign_path_notation'))
        self.assertEqual(run(self.d, 'check', '--scope', 'lab', '--inquiry')[0], 0)     # liveness alone does not read paths

    def test_native_paths_still_pass(self):
        self.grant()
        self.assertEqual(run(self.d, 'check', '--scope', 'lab', '--path', os.path.join(self.work, 'a'), '--experiment-unit', 'u1')[0], 0)


class A6AuditHead(Base):
    def test_cut_off_tail_is_caught_only_with_a_recorded_head(self):
        self.grant()
        self.receipt('r1')
        self.receipt('r2', unit='u2')
        code, head = run(self.d, 'audit-head')
        self.assertEqual(code, 0)
        recorded = head['head']
        p = os.path.join(self.d, 'audit.log')
        lines = open(p, encoding='utf-8').read().splitlines()
        with open(p, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines[:-1]) + '\n')
        self.assertEqual(run(self.d, 'audit-verify')[0], 0, 'the chain alone cannot see a cut-off tail (stated limit)')
        code, data = run(self.d, 'audit-verify', '--expect-head', recorded)
        self.assertEqual((code, data.get('reason')), (2, 'audit'))

    def test_expect_head_passes_when_nothing_changed(self):
        self.grant()
        recorded = run(self.d, 'audit-head')[1]['head']
        self.assertEqual(run(self.d, 'audit-verify', '--expect-head', recorded)[0], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
