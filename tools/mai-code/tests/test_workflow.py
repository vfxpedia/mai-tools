import importlib.util
import json
import sys
import unittest
from unittest.mock import patch
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

    def test_closed_failed_implementation_resumes_without_rewriting_code(self):
        for s in ('analyze','plan'):self.w.execute_stage(self.run,s,self.command(s))
        bad=self.command('implement');bad[-1]=bad[-1].replace("'changes': ['module.py']","'changes': ['Added module.py']")
        # JSON text is embedded in the subprocess string, so change its actual serialized value.
        bad[-1]=bad[-1].replace('"changes": ["module.py"]','"changes": ["Added module.py"]')
        first=self.w.execute_stage(self.run,'implement',bad)
        self.assertEqual(first['status'],'failed')
        source=(self.f.work/'module.py').read_bytes()
        result=self.w.execute_stage(self.run,'implement',self.command('implement'),resume_id='12345678-1234-4234-8234-123456789abc')
        self.assertEqual(result['status'],'passed',result.get('diagnostic'))
        self.assertEqual((self.f.work/'module.py').read_bytes(),source)

    def test_repeated_verification_keeps_chain(self):
        from mai_code.verify import verify_unit,check_existing
        for s in ('analyze','plan','implement'):self.w.execute_stage(self.run,s,self.command(s))
        for _ in range(2):
            self.assertTrue(verify_unit(self.run,self.f.unit['test_argv'],self.f.unit['negative_control_argv'])['unit_passed'])
            self.assertTrue(check_existing(self.run)['passed'])

    def test_failed_attempt_receipt_and_raw_log_are_pinned(self):
        sid='12345678-1234-4234-8234-123456789abc'
        for target in ('receipt.json','stdout.bin'):
            with self.subTest(target=target):
                f=Fixture();self.addCleanup(f.close)
                run=create_run(prepare_packet(f.unit),f.root/'data')
                self.w.execute_stage(run,'analyze',self.command('analyze','bad'))
                attempt=run/'attempts'/load_state(run)['current']['attempt_id']
                candidate=sid
                if target=='receipt.json':
                    data=json.loads((attempt/target).read_text())
                    candidate='87654321-1234-4234-8234-123456789abc'
                    data['native_session_id']=candidate
                    (attempt/target).write_text(json.dumps(data))
                else:(attempt/target).write_bytes(b'forged raw evidence')
                with self.assertRaisesRegex(ValueError,'receipt|evidence'):
                    self.w.resume_decision(run,{'active':False,'session_id':candidate})
                before=len(list((run/'attempts').iterdir()))
                with self.assertRaisesRegex(ValueError,'receipt|evidence'):
                    self.w.execute_stage(run,'analyze',self.command('analyze'),resume_id=candidate)
                self.assertEqual(len(list((run/'attempts').iterdir())),before)

    def test_repeat_verification_launch_failure_invalidates_pass(self):
        from mai_code import verify
        for s in ('analyze','plan','implement'):self.w.execute_stage(self.run,s,self.command(s))
        self.assertTrue(verify.verify_unit(self.run,self.f.unit['test_argv'],self.f.unit['negative_control_argv'])['unit_passed'])
        previous=load_state(self.run)['completed']['verify']['attempt_id']
        real_run=verify.subprocess.run
        def missing(args,**kwargs):
            if args==self.f.unit['test_argv']:raise FileNotFoundError('fixture executable disappeared')
            return real_run(args,**kwargs)
        with patch.object(verify.subprocess,'run',side_effect=missing):
            with self.assertRaises(OSError):verify.verify_unit(self.run,self.f.unit['test_argv'],self.f.unit['negative_control_argv'])
        self.assertNotEqual(load_state(self.run)['status'],'passed')
        self.assertNotEqual(self.w.next_action(self.run)['decision'],'complete')
        with self.assertRaises(ValueError):verify.check_existing(self.run)
        self.assertTrue((self.run/'attempts'/previous/'receipt.json').is_file())

    def test_verification_unknown_child_keeps_lease(self):
        from mai_code import verify
        from mai_code.store import lease_path
        real_run=verify.subprocess.run
        def interrupted(args,**kwargs):
            if args==self.f.unit['test_argv']:raise KeyboardInterrupt()
            return real_run(args,**kwargs)
        with patch.object(verify.subprocess,'run',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):verify.verify_unit(self.run,self.f.unit['test_argv'],self.f.unit['negative_control_argv'])
        self.assertTrue(lease_path(self.run).exists())
        self.assertNotEqual(load_state(self.run)['status'],'passed')
        with self.assertRaises(ValueError):verify.check_existing(self.run)

if __name__=='__main__':unittest.main()
