"""Contract test for the maiwatch status schema (M0).

Every example under schema/examples is checked against schema/status.v1.schema.json by an independent
validator (jsonschema). Valid examples must pass. Each invalid example must be rejected for the reason
named in EXPECTED_REJECTION, not merely rejected. Two mutation checks prove that the expectations are
sensitive: with a deliberately broken schema, the matching invalid example must start to pass.

Run:  python -I tools/maiwatch/tests/test_schema_contract.py
A missing jsonschema package is a failure, not a skip: a skipped contract test looks like a pass.
"""
import copy
import json
import os
import sys
import unittest

try:
    from jsonschema import Draft202012Validator
except ImportError:  # fail loudly (a quiet skip would look like success)
    sys.exit('jsonschema is required for the contract test (pip install jsonschema)')

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.path.join(HERE, '..', 'schema')
EXAMPLES = os.path.join(SCHEMA_DIR, 'examples')

# example file -> (JSON Schema keyword that must fire, text that must appear in the error message)
EXPECTED_REJECTION = {
    'invalid-missing-updated_at.json': ('required', 'updated_at'),
    'invalid-unknown-schema-version.json': ('const', '1'),
    'invalid-state-idle.json': ('enum', 'idle'),
    'invalid-waiting-without-reason.json': ('required', 'hold_reason'),
    'invalid-heartbeat-interval-zero.json': ('exclusiveMinimum', '0'),
    'invalid-id-with-space.json': ('pattern', 'train a'),
    'invalid-time-not-utc.json': ('pattern', '+09:00'),
    'invalid-artifacts-not-array.json': ('type', 'array'),
    'invalid-empty-hold-reason.json': ('minLength', '', 'hold_reason'),
}


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def schema():
    return load(os.path.join(SCHEMA_DIR, 'status.v1.schema.json'))


def errors(sch, doc):
    return list(Draft202012Validator(sch).iter_errors(doc))


def example_files(prefix):
    return sorted(n for n in os.listdir(EXAMPLES) if n.startswith(prefix) and n.endswith('.json'))


class SchemaContract(unittest.TestCase):
    def test_schema_itself_is_valid(self):
        Draft202012Validator.check_schema(schema())

    def test_examples_exist(self):
        # guards against a test that loops over nothing
        self.assertGreaterEqual(len(example_files('valid-')), 4)
        self.assertEqual(sorted(example_files('invalid-')), sorted(EXPECTED_REJECTION))

    def test_valid_examples_pass(self):
        for name in example_files('valid-'):
            with self.subTest(name):
                self.assertEqual([e.message for e in errors(schema(), load(os.path.join(EXAMPLES, name)))], [])

    def test_invalid_examples_rejected_for_the_stated_reason(self):
        for name, expected in EXPECTED_REJECTION.items():
            keyword, text = expected[0], expected[1]
            path_key = expected[2] if len(expected) > 2 else None  # field the error must point at (empty text matches anything)
            with self.subTest(name):
                errs = errors(schema(), load(os.path.join(EXAMPLES, name)))
                self.assertTrue(errs, f'{name} was accepted')
                hit = [e for e in errs if e.validator == keyword and text in e.message
                       and (path_key is None or (list(e.path) and list(e.path)[-1] == path_key))]
                self.assertTrue(hit, f'{name}: expected {keyword!r} with {text!r}, got '
                                     f'{[(e.validator, e.message) for e in errs]}')

    def test_mutation_dropping_a_required_field_is_detected(self):
        sch = copy.deepcopy(schema())
        sch['required'].remove('updated_at')
        doc = load(os.path.join(EXAMPLES, 'invalid-missing-updated_at.json'))
        self.assertEqual(errors(sch, doc), [], 'mutant schema should accept the document, proving the expectation is sensitive')

    def test_mutation_allowing_idle_state_is_detected(self):
        sch = copy.deepcopy(schema())
        sch['properties']['state']['enum'].append('idle')
        doc = load(os.path.join(EXAMPLES, 'invalid-state-idle.json'))
        self.assertEqual(errors(sch, doc), [], 'mutant schema should accept the document, proving the expectation is sensitive')

    def test_mutation_removing_conditional_reason_rule_is_detected(self):
        sch = copy.deepcopy(schema())
        del sch['if'], sch['then']
        doc = load(os.path.join(EXAMPLES, 'invalid-waiting-without-reason.json'))
        self.assertEqual(errors(sch, doc), [], 'mutant schema should accept the document, proving the expectation is sensitive')


if __name__ == '__main__':
    unittest.main(verbosity=2)
