import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from support import Fixture
from mai_code.unit import prepare_packet, digest


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('mai_code.store'),'store not implemented')
        from mai_code import store
        self.s=store; self.f=Fixture(); self.addCleanup(self.f.close)
        self.run=self.s.create_run(prepare_packet(self.f.unit),self.f.root/'data')

    def test_immutable_inputs_and_creation(self):
        self.assertEqual(digest(self.run/'inputs/0'),self.f.unit['inputs'][0]['sha256'])
        with self.assertRaises(FileExistsError): self.s.create_run(prepare_packet(self.f.unit),self.f.root/'data')

    def test_atomic_state_and_immutable_receipt(self):
        state=self.s.load_state(self.run); state['status']='running'; self.s.save_state(self.run,state)
        self.assertEqual(self.s.load_state(self.run)['status'],'running')
        a=self.s.new_attempt(self.run,'analyze'); self.s.write_receipt(a,{'stage':'analyze','status':'failed'})
        raw=(a/'receipt.json').read_bytes()
        with self.assertRaises(FileExistsError): self.s.write_receipt(a,{'stage':'analyze','status':'passed'})
        self.assertEqual((a/'receipt.json').read_bytes(),raw)
        self.assertFalse(list(self.run.glob('*.tmp')))

    def test_corrupt_or_foreign_state(self):
        for value in ('{','{"schema":"unknown"}'):
            (self.run/'state.json').write_text(value)
            with self.assertRaises(ValueError): self.s.load_state(self.run)

    def test_unknown_lease_never_removed(self):
        token=self.s.acquire_lease(self.run,{'pid':999999999})
        with self.assertRaises(ValueError): self.s.acquire_lease(self.run,{'pid':os.getpid()})
        with self.assertRaises(ValueError): self.s.release_lease(self.run,'not-owner')
        self.s.release_lease(self.run,token)

    def test_two_processes_one_lease(self):
        script='import sys;sys.path.insert(0,sys.argv[1]);from mai_code.store import acquire_lease;from pathlib import Path;acquire_lease(Path(sys.argv[2]),{"pid":0})'
        args=[sys.executable,'-I','-c',script,str(Path(__file__).resolve().parents[1]),str(self.run)]
        children=[subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
        codes=[]
        for p in children: p.communicate(); codes.append(p.returncode)
        self.assertEqual(sorted(codes),[0,1])

    def test_ledger_truncation_detected(self):
        with (self.run/'events.jsonl').open('ab') as f: f.write(b'{')
        with self.assertRaises(ValueError): self.s.load_state(self.run)

if __name__=='__main__': unittest.main()
