import importlib.util
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mai_code.store import immutable


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('mai_code.adapters'),'adapters missing')
        from mai_code.adapters import base
        self.a=base
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'space & 유니코드'; self.path.mkdir()

    def test_argv_and_exact_id(self):
        immutable(self.path/'cli.json',{'engine':'codex','executable':sys.executable,'resume_supported':True})
        args=self.a.build_command('codex','analyze',self.path,'model-1','12345678-1234-4234-8234-123456789abc')
        self.assertEqual(args[:2],[sys.executable,'exec'])
        self.assertEqual(args[args.index('resume')+1],'12345678-1234-4234-8234-123456789abc')
        self.assertEqual(args[-1],'-')
        self.assertIn(str(self.path/'final.json'),args)
        self.assertFalse(set(args)&{'--last','--continue','--dangerously-bypass-approvals-and-sandbox','--dangerously-skip-permissions'})
        with self.assertRaises(ValueError): self.a.build_command('codex','analyze',self.path,None,'--last')

    def test_environment_names_not_values(self):
        env={'PATH':'x','CODEX_HOME':'home','CODEX_THREAD_ID':'parent','ORCA_TERMINAL_HANDLE':'parent','ANTHROPIC_API_KEY':'must-not-appear'}
        with self.assertRaises(ValueError) as ctx:self.a.child_environment('claude',env)
        self.assertNotIn('must-not-appear',str(ctx.exception))
        env.pop('ANTHROPIC_API_KEY')
        result=self.a.child_environment('codex',env)
        self.assertEqual(result,{'PATH':'x','CODEX_HOME':'home'})

    def test_auth_probe_supported_and_unknown(self):
        class Result:
            returncode=0
            def __init__(self,text):self.stdout=text;self.stderr=''
        def call(args,**kwargs):
            if args[-1]=='--version':return Result('codex-cli 1.0')
            if args[-2:]==['login','status']:return Result('Logged in using ChatGPT')
            return Result('--json --output-last-message --output-schema --model SESSION_ID')
        with patch.object(self.a,'resolve_launcher',return_value=sys.executable), patch.object(self.a.subprocess,'run',side_effect=call):
            result=self.a.probe_cli('codex',Path(sys.executable))
        self.assertEqual(result['reported_auth_mode'],'subscription')
        self.assertTrue(result['resume_supported'])
        for message in ('Logged in using an API key','unknown login'):
            def bad(args,**kwargs):return Result(message) if args[-2:]==['login','status'] else call(args,**kwargs)
            with patch.object(self.a,'resolve_launcher',return_value=sys.executable),patch.object(self.a.subprocess,'run',side_effect=bad):
                self.assertNotEqual(self.a.probe_cli('codex',Path(sys.executable))['reported_auth_mode'],'subscription')

    def test_event_contract(self):
        self.assertEqual(self.a.parse_event('codex',{'type':'thread.started','thread_id':'id'})['session_id'],'id')
        self.assertEqual(self.a.parse_event('claude',{'type':'result','subtype':'success','session_id':'id','result':'{}','usage':{'input_tokens':2}})['usage'],{'input_tokens':2})
        self.assertEqual(self.a.parse_event('codex',{'type':'alien','mystery':5})['kind'],'unknown')
        self.assertEqual(self.a.parse_event('claude',{'type':'result','is_error':True,'subtype':'error_during_execution'})['kind'],'error')

    def test_missing_shim_refused(self):
        shim=self.path/'codex.ps1';shim.write_text('not an executable')
        with self.assertRaises(ValueError):self.a.resolve_launcher('codex',shim)

    def test_claude_uses_native_schema(self):
        immutable(self.path/'cli.json',{'engine':'claude','executable':sys.executable,'resume_supported':True})
        immutable(self.path/'response-schema.json',{'type':'object'})
        args=self.a.build_command('claude','analyze',self.path)
        self.assertIn('--json-schema',args)
        self.assertEqual(json.loads(args[args.index('--json-schema')+1]),{'type':'object'})

    def test_exact_write_grants_are_explicit_and_confined(self):
        rules=self.a.exact_write_rules(self.path,['affine.py'],['analysis.json','plan.json','affine.py'])
        target=(self.path.resolve()/'affine.py').as_posix()
        if sys.platform=='win32':target='/'+target[0].lower()+target[2:]
        self.assertEqual(rules,['Edit(/'+target+')'])
        for rel in ('../escape','affine*.py','analysis.json'):
            with self.subTest(rel=rel),self.assertRaises(ValueError):self.a.exact_write_rules(self.path,[rel],['analysis.json','plan.json','affine.py'])

    def test_windows_permission_drive_normalization(self):
        from pathlib import PureWindowsPath
        self.assertEqual(self.a.native_edit_rule(PureWindowsPath('C:/owned/affine.py')),'Edit(//c/owned/affine.py)')

    def test_stage_permissions_new_and_exact_resume(self):
        # Removing a policy flag, widening a tool list or putting sandbox after
        # the resume subcommand must fail this literal, independently chosen contract.
        sid='12345678-1234-4234-8234-123456789abc'
        for engine in ('codex','claude'):
            attempt=self.path/engine;attempt.mkdir()
            immutable(attempt/'cli.json',{'engine':engine,'executable':sys.executable,'resume_supported':True})
            immutable(attempt/'response-schema.json',{'type':'object'})
            for stage,sandbox,tools in (
                ('analyze','read-only','Read,Glob,Grep'),
                ('plan','read-only','Read,Glob,Grep'),
                ('implement','workspace-write','Read,Glob,Grep,Edit,Write')):
                for resume in (None,sid):
                    with self.subTest(engine=engine,stage=stage,resume=bool(resume)):
                        args=self.a.build_command(engine,stage,attempt,resume_id=resume)
                        if engine=='codex':
                            self.assertIn('--sandbox',args)
                            self.assertEqual(args[args.index('--sandbox')+1],sandbox)
                            self.assertIn('approval_policy="never"',args)
                            self.assertIn('--ignore-user-config',args)
                            self.assertIn('--ignore-rules',args)
                            if resume:self.assertLess(args.index('--sandbox'),args.index('resume'))
                        else:
                            self.assertIn('--permission-mode',args)
                            self.assertEqual(args[args.index('--permission-mode')+1],'default')
                            self.assertIn('--tools',args)
                            self.assertEqual(args[args.index('--tools')+1],tools)
                            self.assertIn('--restricted',args)
                            self.assertIn('--strict-mcp-config',args)
                            self.assertEqual(args[args.index('--disallowedTools')+1],'mcp__*')
                            self.assertEqual(args[args.index('--permission-prompts')+1],'none')
                        self.assertFalse(set(args)&{'--full-auto','--dangerously-skip-permissions','--dangerously-bypass-approvals-and-sandbox'})

    def test_unknown_stage_has_no_permission_fallback(self):
        immutable(self.path/'cli.json',{'engine':'codex','executable':sys.executable,'resume_supported':True})
        with self.assertRaisesRegex(ValueError,'stage'):
            self.a.build_command('codex','typo',self.path)

    def test_missing_permission_capability_is_reported(self):
        # The external CLI is a boundary double, not a replacement for probe_cli.
        caps={
            'codex':['--json','--output-last-message','--output-schema','--model','--sandbox','--config','--ignore-user-config','--ignore-rules'],
            'claude':['--print','--output-format','--json-schema','--resume','--model','--permission-mode','--tools','--allowedTools','--restricted','--strict-mcp-config','--disallowedTools','--permission-prompts']}
        class Result:
            returncode=0
            def __init__(self,text):self.stdout=text;self.stderr=''
        for engine,flags in caps.items():
            for removed in [None,*flags]:
                def call(args,**kwargs):
                    if args[-1]=='--version':return Result('codex-cli 1.0' if engine=='codex' else '2.1.302 (Claude Code)')
                    if args[1:]==['login','status']:return Result('Logged in using ChatGPT')
                    if args[1:]==['auth','status','--json']:return Result('{"loggedIn":true,"authMethod":"claude.ai"}')
                    return Result(' '.join(f for f in flags if f!=removed)+' SESSION_ID')
                with self.subTest(engine=engine,removed=removed),patch.object(self.a,'resolve_launcher',return_value=sys.executable),patch.object(self.a.subprocess,'run',side_effect=call):
                    result=self.a.probe_cli(engine)
                    if removed:self.assertIn('missing-capability:'+removed,result['diagnostic_codes'])
                    else:self.assertEqual(result['diagnostic_codes'],[])
                    # Exercise the public doctor result, not only its helper.
                    from mai_code.cli import main
                    output=io.StringIO()
                    with contextlib.redirect_stdout(output):code=main(['doctor','--engine',engine])
                    self.assertEqual(code,2 if removed else 0)
                    if removed:self.assertIn('missing-capability:'+removed,json.loads(output.getvalue())[0]['diagnostic_codes'])

if __name__=='__main__':unittest.main()
