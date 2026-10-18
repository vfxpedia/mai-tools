import importlib.util
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
        self.assertEqual(args[:4],[sys.executable,'exec','resume','12345678-1234-4234-8234-123456789abc'])
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

if __name__=='__main__':unittest.main()
