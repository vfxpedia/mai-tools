import importlib.util
import json
import sys
import unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from support import Fixture
from mai_code.unit import prepare_packet
from mai_code.store import create_run,load_state


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('mai_code.workflow'),'workflow missing')
        from mai_code import workflow
        self.w=workflow;self.f=Fixture();self.addCleanup(self.f.close)
        self.run=create_run(prepare_packet(self.f.unit),self.f.root/'data')

    def command(self,stage,mode='good'):
        answer={'stage':stage,'summary':'TEST ONLY known fixture','assumptions':[],'references':['section 1'],'changes':['module.py'] if stage=='implement' else []}
        script='import json,sys;from pathlib import Path;sys.stdin.read();'
        if mode=='write-outside': script+='Path("unrelated.txt").write_text("bad");'
        if stage=='implement' and mode=='good':script+='Path("module.py").write_text("value=4\\n");'
        if mode=='empty':return [sys.executable,'-c',script]
        if mode=='bad':answer['assumptions']='not a list'
        script+='print(json.dumps({"type":"thread.started","thread_id":"12345678-1234-4234-8234-123456789abc"}));'
        script+='print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":'+repr(json.dumps(answer))+'}}));'
        script+='print(json.dumps({"type":"turn.completed","usage":{"input_tokens":2}}))'
        return [sys.executable,'-c',script]

    def test_sequence_and_no_duplicate(self):
        for stage in ('analyze','plan','implement'):
            self.assertEqual(self.w.next_action(self.run)['stage'],stage)
            receipt=self.w.execute_stage(self.run,stage,self.command(stage))
            self.assertEqual(receipt['status'],'passed')
            with self.assertRaises(ValueError):self.w.execute_stage(self.run,stage,self.command(stage))
        self.assertEqual(self.w.next_action(self.run)['stage'],'verify')
        self.assertEqual(len(list((self.run/'attempts').iterdir())),3)

    def test_missing_invalid_and_unrelated_output(self):
        for mode in ('empty','bad','write-outside'):
            with self.subTest(mode=mode):
                # Separate workspaces avoid making a failed run look freshly prepared.
                f=Fixture();self.addCleanup(f.close)
                run=create_run(prepare_packet(f.unit),f.root/'data')
                result=self.w.execute_stage(run,'analyze',self.command('analyze',mode))
                self.assertNotEqual(result['status'],'passed')
                self.assertEqual(self.w.next_action(run)['decision'],'needs_attention')

    def test_input_revision_refused(self):
        (self.f.work/'paper.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'input'):self.w.execute_stage(self.run,'analyze',self.command('analyze'))
        self.assertEqual(len(list((self.run/'attempts').iterdir())),0)

    def test_receipt_tampering(self):
        self.w.execute_stage(self.run,'analyze',self.command('analyze'))
        attempt=next((self.run/'attempts').iterdir())
        data=json.loads((attempt/'receipt.json').read_text());data['parent_sha256']='0'*64
        (attempt/'receipt.json').write_text(json.dumps(data))
        with self.assertRaises(ValueError):self.w.next_action(self.run)

    def test_unknown_liveness_and_wrong_id(self):
        self.assertEqual(self.w.resume_decision(self.run,{'active':'unknown'})['decision'],'needs_attention')
        self.w.execute_stage(self.run,'analyze',self.command('analyze','empty'))
        self.assertEqual(self.w.resume_decision(self.run,{'active':False,'session_id':'wrong'})['decision'],'needs_attention')

if __name__=='__main__':unittest.main()
