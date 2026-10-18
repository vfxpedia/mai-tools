import importlib.util
import json
import sys
import unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from support import Fixture
from mai_code.unit import prepare_packet
from mai_code.store import create_run


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('mai_code.verify'),'verifier missing')
        from mai_code.verify import verify_unit
        self.verify=verify_unit;self.f=Fixture();self.addCleanup(self.f.close)
        self.f.unit['test_argv'][0]=sys.executable;self.f.unit['negative_control_argv'][0]=sys.executable
        self.run=create_run(prepare_packet(self.f.unit),self.f.root/'data')

    def test_good_and_expected_negative(self):
        r=self.verify(self.run,self.f.unit['test_argv'],self.f.unit['negative_control_argv'])
        self.assertTrue(r['passed']);self.assertEqual(r['discovered_tests'],1);self.assertTrue(r['negative_control_rejected'])

    def test_zero_tests_refused(self):
        self.f.unit['test_argv']=[sys.executable,'-c','print("no tests")']
        with self.assertRaises(ValueError):self.verify(self.run,self.f.unit['test_argv'],self.f.unit['negative_control_argv'])

    def test_wrong_negative_does_not_count(self):
        # Commands are fixed before preparation, never accepted from the model.
        for code in ('raise ImportError("broken")','import unittest;unittest.main()','print("Ran 1 test\\nFAILED (errors=1)")'):
            f=Fixture();self.addCleanup(f.close)
            f.unit['test_argv'][0]=sys.executable;f.unit['negative_control_argv']=[sys.executable,'-c',code]
            run=create_run(prepare_packet(f.unit),f.root/'data')
            self.assertFalse(self.verify(run,f.unit['test_argv'],f.unit['negative_control_argv'])['passed'])

    def test_recorded_evidence_tamper_rejected(self):
        self.verify(self.run,self.f.unit['test_argv'],self.f.unit['negative_control_argv'])
        a=next((self.run/'attempts').iterdir());(a/'positive.stderr').write_bytes(b'fake')
        from mai_code.verify import check_existing
        with self.assertRaises(ValueError):check_existing(self.run)

if __name__=='__main__':unittest.main()
