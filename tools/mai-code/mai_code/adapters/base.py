import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from . import codex,claude
from ..store import read_json

PARENT_ENV={'CODEX_THREAD_ID','CODEX_TURN_ID','CLAUDECODE','CLAUDE_CODE_SESSION_ID','ORCA_TERMINAL_HANDLE','ORCA_AGENT_SESSION_ID'}
CONFLICTS={'codex':{'OPENAI_API_KEY','CODEX_API_KEY','OPENAI_BASE_URL','CODEX_BASE_URL'},'claude':{'ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','ANTHROPIC_BASE_URL','CLAUDE_CODE_USE_BEDROCK','CLAUDE_CODE_USE_VERTEX','CLAUDE_CODE_USE_FOUNDRY'}}


def child_environment(engine,env=None):
    source=dict(os.environ if env is None else env)
    conflicts=sorted(CONFLICTS[engine]&source.keys())
    if conflicts: raise ValueError('subscription authentication conflict in environment names: '+', '.join(conflicts))
    return {k:v for k,v in source.items() if k not in PARENT_ENV}


def resolve_launcher(engine,executable=None):
    found=str(executable) if executable else shutil.which(engine)
    if not found: raise ValueError(engine+' executable not found')
    p=Path(found).resolve()
    if not p.is_file(): raise ValueError(engine+' executable missing')
    if p.suffix.lower() in ('.ps1','.cmd','.bat'):
        if engine!='codex': raise ValueError('unsupported launcher shim; select native executable')
        root=p.parent/'node_modules/@openai/codex'
        candidates=list(root.glob('node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe'))+list(root.glob('vendor/*/codex/codex.exe'))
        if len(candidates)!=1: raise ValueError('cannot resolve official npm native launcher; select codex.exe explicitly')
        p=candidates[0].resolve()
    if os.name=='nt' and p.suffix.lower()!='.exe': raise ValueError('native executable required on Windows')
    return str(p)


def probe_cli(engine,executable=None):
    if engine not in ('codex','claude'): raise ValueError('unknown engine')
    p=resolve_launcher(engine,executable)
    env=child_environment(engine)
    def call(args):
        result=subprocess.run([p,*args],capture_output=True,encoding='utf-8',errors='replace',env=env)
        return result.returncode,result.stdout+result.stderr
    rc,version=call(['--version'])
    if rc or (engine=='codex' and not version.startswith('codex-cli ')) or (engine=='claude' and '(Claude Code)' not in version): raise ValueError('unrecognized official executable version')
    _,helptext=call(['exec','--help'] if engine=='codex' else ['--help'])
    flags=['--json','--output-last-message','--output-schema','--model'] if engine=='codex' else ['--print','--output-format','--json-schema','--resume','--model']
    missing=[f for f in flags if f not in helptext]
    auth_rc,auth=call(['login','status'] if engine=='codex' else ['auth','status','--json'])
    mode='unknown'
    if not auth_rc:
        if engine=='codex':
            if 'Logged in using ChatGPT' in auth:mode='subscription'
            elif 'API key' in auth:mode='api'
        else:
            try:
                info=json.loads(auth)
                if info.get('loggedIn') is True and info.get('authMethod')=='claude.ai':mode='subscription'
                elif info.get('loggedIn') is True:mode='api-or-other'
            except ValueError:pass
    resume_help=call(['exec','resume','--help'])[1] if engine=='codex' else helptext
    resume_supported=('--json' in resume_help and '--output-schema' in resume_help and 'SESSION_ID' in resume_help) if engine=='codex' else '--resume' in helptext
    return dict(engine=engine,executable=p,version=version.strip(),supported_flags=[f for f in flags if f in helptext],reported_auth_mode=mode,resume_supported=resume_supported,diagnostic_codes=(['missing-capability:'+f for f in missing]+([] if mode=='subscription' else ['subscription-not-confirmed'])),effective_home=str(Path(env.get('CODEX_HOME' if engine=='codex' else 'CLAUDE_CONFIG_DIR',str(Path.home()/('.codex' if engine=='codex' else '.claude')))).expanduser()))


def build_command(engine,stage,attempt,model=None,resume_id=None):
    info=read_json(attempt/'cli.json')
    if info['engine']!=engine: raise ValueError('engine identity mismatch')
    if resume_id:
        try:uuid.UUID(resume_id)
        except (ValueError,AttributeError) as e:raise ValueError('exact native UUID required') from e
        if not info.get('resume_supported'):raise ValueError('exact resume unsupported')
    return (codex if engine=='codex' else claude).command(info['executable'],attempt,model,resume_id)


def parse_event(engine,record):
    if not isinstance(record,dict):raise ValueError('native event must be an object')
    return (codex if engine=='codex' else claude).parse(record)
