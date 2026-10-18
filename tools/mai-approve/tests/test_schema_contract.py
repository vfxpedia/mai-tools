"""Contract test for mai-approve-approval-v1 (M0). Run: python -I tools/mai-approve/tests/test_schema_contract.py

Valid examples must pass the schema AND the semantic rules (hash matches, valid_until after granted_at, window at most 31 days).
Invalid examples must be rejected by the named schema keyword. Semantic examples pass the schema but must fail a semantic rule.
Mutation checks: with a weakened schema or weakened semantic rule, the matching bad example must start to pass.
Missing jsonschema is a failure, not a skip.
"""
import copy, datetime, hashlib, json, os, sys, unittest
try:
    from jsonschema import Draft202012Validator
except ImportError:
    sys.exit('jsonschema is required for the contract test (pip install jsonschema)')

HERE = os.path.dirname(os.path.abspath(__file__))
RECEIPT_SCHEMA = os.path.join(HERE, '..', 'schema', 'receipt.v1.schema.json')
SCHEMA_PATH = os.path.join(HERE, '..', 'schema', 'approval.v1.schema.json')
EX = os.path.join(HERE, '..', 'schema', 'examples')
MAX_DAYS = 31

EXPECTED_REJECTION = {
    'invalid-missing-valid_until.json': ('required', 'valid_until'),
    'invalid-unknown-schema.json': ('enum', 'mai-approve-approval-v1'),
    'invalid-method-agent.json': ('const', 'owner-run mai-approve'),
    'invalid-time-not-utc.json': ('pattern', '+09:00'),
    'invalid-empty-exclusions.json': ('minItems', '[]'),
    'invalid-unknown-exclusion.json': ('enum', 'everything'),
    'invalid-no-allowed-paths.json': ('minItems', '[]'),
    'invalid-extra-field.json': ('additionalProperties', 'auto_renew'),
    'invalid-scope-space.json': ('pattern', 'my lab'),
    'invalid-missing-eula.json': ('required', 'eula'),
    'invalid-eula-not-accepted.json': ('const', 'True'),
    'invalid-execution-mode.json': ('enum', 'sometimes'),
    'invalid-count-per-run-id.json': ('const', 'experiment_unit_id'),
}
RECEIPT_REJECTION = {
    'receipt-invalid-missing-unit.json': ('required', 'experiment_unit_id'),
    'receipt-invalid-attempt-kind.json': ('enum', 'fresh_start'),
}
EXPECTED_SEMANTIC = {
    'semantic-tampered-hash.json': 'hash',
    'semantic-window-over-31-days.json': 'window',
    'semantic-expires-before-grant.json': 'order',
}

def load(p):
    with open(p, encoding='utf-8') as f: return json.load(f)

def schema(): return load(SCHEMA_PATH)
def errs(sch, doc): return list(Draft202012Validator(sch).iter_errors(doc))
def files(prefix): return sorted(n for n in os.listdir(EX) if n.startswith(prefix) and n.endswith('.json'))
def ts(s): return datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')

def canon_hash(doc):
    d = {k: v for k, v in doc.items() if k != 'sha256'}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()

def semantic_failures(doc, check_hash=True, max_days=MAX_DAYS):
    out = []
    if check_hash and canon_hash(doc) != doc['sha256']: out.append('hash')
    g, v = ts(doc['granted_at']), ts(doc['valid_until'])
    if v <= g: out.append('order')
    elif (v - g) > datetime.timedelta(days=max_days): out.append('window')
    return out

class Contract(unittest.TestCase):
    def test_schema_valid(self):
        Draft202012Validator.check_schema(schema())
        Draft202012Validator.check_schema(load(RECEIPT_SCHEMA))

    def test_receipts(self):
        rs = load(RECEIPT_SCHEMA)
        self.assertEqual(set(files('receipt-invalid-')), set(RECEIPT_REJECTION))
        for n in files('receipt-valid-'):
            self.assertEqual(errs(rs, load(os.path.join(EX, n))), [], n)
        for n, (kw, text) in RECEIPT_REJECTION.items():
            es = errs(rs, load(os.path.join(EX, n)))
            self.assertTrue(any(e.validator == kw and text in e.message for e in es), n)

    def test_mutation_receipt_unit_not_required(self):
        rs = copy.deepcopy(load(RECEIPT_SCHEMA)); rs['required'].remove('experiment_unit_id')
        self.assertEqual(errs(rs, load(os.path.join(EX, 'receipt-invalid-missing-unit.json'))), [])

    def test_examples_exist(self):
        self.assertGreaterEqual(len(files('valid-')), 3)
        self.assertEqual(set(files('invalid-')), set(EXPECTED_REJECTION))
        self.assertEqual(set(files('semantic-')), set(EXPECTED_SEMANTIC))

    def test_valid_pass_schema_and_semantics(self):
        s = schema()
        for n in files('valid-'):
            d = load(os.path.join(EX, n))
            self.assertEqual(errs(s, d), [], n)
            self.assertEqual(semantic_failures(d), [], n)

    def test_invalid_rejected_for_named_reason(self):
        s = schema()
        for n, (kw, text) in EXPECTED_REJECTION.items():
            es = errs(s, load(os.path.join(EX, n)))
            self.assertTrue(es, n + ' was accepted')
            self.assertTrue(any(e.validator == kw and text in e.message for e in es), f'{n}: wanted {kw}/{text}, got {[(e.validator, e.message) for e in es]}')

    def test_semantic_cases(self):
        s = schema()
        for n, want in EXPECTED_SEMANTIC.items():
            d = load(os.path.join(EX, n))
            self.assertEqual(errs(s, d), [], n + ' must pass schema')
            self.assertIn(want, semantic_failures(d), n)

    def test_mutation_schema_const_removed(self):
        s = copy.deepcopy(schema()); s['properties']['method'] = {'type': 'string'}
        self.assertEqual(errs(s, load(os.path.join(EX, 'invalid-method-agent.json'))), [])

    def test_mutation_schema_exclusions_minitems_removed(self):
        s = copy.deepcopy(schema()); del s['properties']['exclusions']['minItems']
        self.assertEqual(errs(s, load(os.path.join(EX, 'invalid-empty-exclusions.json'))), [])

    def test_mutation_semantic_hash_check_removed(self):
        d = load(os.path.join(EX, 'semantic-tampered-hash.json'))
        self.assertEqual(semantic_failures(d, check_hash=False), [])

    def test_mutation_semantic_window_widened(self):
        d = load(os.path.join(EX, 'semantic-window-over-31-days.json'))
        self.assertEqual(semantic_failures(d, max_days=400), [])

if __name__ == '__main__':
    unittest.main(verbosity=2)
