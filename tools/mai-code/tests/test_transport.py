import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('mai_code.transport'),'observer missing')
        from mai_code.transport import observe
        self.observe=observe
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.a=Path(self.tmp.name);self.prompt=self.a/'prompt';self.prompt.write_text('TEST ONLY 한글',encoding='utf-8')

    def run_child(self,mode,threshold=None):
        return self.observe([sys.executable,str(Path(__file__).parent/'fixtures/fake_cli.py'),mode],self.a,self.prompt,self.a,dict(os.environ),threshold)

    def test_success_is_transport_not_stage(self):
        result=self.run_child('valid')
        self.assertEqual(result['exit_code'],0)
        self.assertEqual(result['event_count'],2)
        self.assertEqual(result['status'],'transport-complete')

    def test_empty_malformed_and_nonzero(self):
        for mode in ('empty','malformed','exit'):
            with self.subTest(mode=mode):
                a=self.a/mode;a.mkdir()
                result=self.observe([sys.executable,str(Path(__file__).parent/'fixtures/fake_cli.py'),mode],self.a,self.prompt,a,dict(os.environ),None)
                self.assertEqual(result['status'],'needs-attention')

    def test_partial_utf8_preserved(self):
        result=self.run_child('utf8')
        self.assertEqual((self.a/'stdout.bin').read_bytes(),'{"type":"note","text":"한글"}\n'.encode())
        self.assertEqual(result['malformed_events'],0)

    def test_16mib_each_no_deadlock(self):
        result=self.run_child('large')
        self.assertEqual(result['exit_code'],0)
        # Independent fixed byte-pattern oracle, not the transport's hash routine.
        self.assertEqual(hashlib.sha256((self.a/'stdout.bin').read_bytes()).hexdigest(),hashlib.sha256(b'A'*(16*1024*1024)).hexdigest())
        self.assertEqual((self.a/'stderr.bin').read_bytes(),b'B'*(16*1024*1024))

    def test_attention_does_not_kill(self):
        result=self.run_child('slow',0.01)
        self.assertEqual(result['exit_code'],0)
        self.assertTrue(result['attention_triggered'])
        lifecycle=[json.loads(s) for s in (self.a/'lifecycle.jsonl').read_text().splitlines()]
        self.assertEqual([r['event'] for r in lifecycle],['started','attention','exited'])
        self.assertGreater(lifecycle[-1]['elapsed_s'],0.1)

if __name__=='__main__':unittest.main()
