"""Strict owner-authored units and read-only workspace checks."""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PureWindowsPath

FIELDS = {'schema','unit_id','issue_url','workspace','inputs','contract','outputs','engines','test_argv','test_framework','negative_control_argv'}
STAGES = ('analyze','plan','implement')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')


def git(work, *args):
    p = subprocess.run(['git','-C',str(work),*args], capture_output=True, encoding='utf-8', errors='strict')
    if p.returncode: raise ValueError('git workspace check failed')
    return p.stdout.strip()


def native(path):
    if not isinstance(path,str) or not path or '\x00' in path: raise ValueError('invalid path')
    if os.name != 'nt' and (PureWindowsPath(path).drive or '\\' in path): raise ValueError('foreign OS path')
    if os.name == 'nt' and path.startswith('/') and not path.startswith('//'): raise ValueError('foreign OS path')
    return Path(path)


def confined(work, rel):
    p = native(rel)
    if p.is_absolute() or PureWindowsPath(rel).drive or '..' in p.parts: raise ValueError('path escape')
    result = (work/p).resolve()
    if not result.is_relative_to(work.resolve()) or result == work.resolve(): raise ValueError('path escape')
    if p.parts[0].lower() == '.git': raise ValueError('git path forbidden')
    return result


def argv(value):
    if not isinstance(value,list) or not value or any(not isinstance(s,str) or not s or '\x00' in s for s in value): raise ValueError('nonempty test argv required')


def load_unit(path):
    try: u = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError) as e: raise ValueError('invalid unit JSON') from e
    return validate_unit(u)


def validate_unit(u):
    if not isinstance(u,dict) or set(u)!=FIELDS or u['schema']!='mai-code-unit-v1': raise ValueError('unit schema or unknown keys')
    if not isinstance(u['unit_id'],str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', u['unit_id']): raise ValueError('unit ID')
    if not isinstance(u['issue_url'],str) or not re.fullmatch(r'https://github\.com/[^/\s]+/[^/\s]+/issues/[1-9][0-9]*',u['issue_url']): raise ValueError('issue URL')
    work=native(u['workspace'])
    if not work.is_absolute(): raise ValueError('absolute workspace required')
    if not isinstance(u['inputs'],list) or not u['inputs']: raise ValueError('inputs required')
    seen=set()
    for item in u['inputs']:
        if not isinstance(item,dict) or set(item)!={'path','sha256','references'}: raise ValueError('input schema')
        p=confined(work,item['path'])
        if p in seen: raise ValueError('duplicate input')
        seen.add(p)
        if not isinstance(item['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',item['sha256']): raise ValueError('input hash')
        if not isinstance(item['references'],list) or not item['references'] or any(not isinstance(x,str) or not x.strip() for x in item['references']): raise ValueError('references required')
    if not isinstance(u['outputs'],list) or len(u['outputs'])<2: raise ValueError('reserved analysis and plan outputs required')
    outs=[os.path.normcase(str(confined(work,p))) for p in u['outputs']]
    if len(outs)!=len(set(outs)) or any(Path(p) in seen for p in outs): raise ValueError('duplicate output or input overlap')
    if not isinstance(u['engines'],dict) or set(u['engines'])!=set(STAGES): raise ValueError('three engines required')
    for spec in u['engines'].values():
        if not isinstance(spec,dict) or not {'engine'}<=spec.keys() or not set(spec)<={'engine','model'} or spec['engine'] not in ('codex','claude'): raise ValueError('engine schema')
        if 'model' in spec and (not isinstance(spec['model'],str) or not spec['model'].strip() or spec['model'].startswith('-')): raise ValueError('model')
    if not isinstance(u['contract'],dict) or not isinstance(u['contract'].get('module'),str) or not u['contract']['module'].strip(): raise ValueError('module contract required')
    if not isinstance(u['contract'].get('negative_test_id'),str) or not u['contract']['negative_test_id']: raise ValueError('negative test ID required')
    if type(u['contract'].get('negative_failures')) is not int or u['contract']['negative_failures']<1: raise ValueError('negative assertion count required')
    if u['test_framework']!='unittest': raise ValueError('unsupported test framework')
    argv(u['test_argv']); argv(u['negative_control_argv'])
    return u


def fingerprint(work):
    work=Path(work).resolve()
    common=Path(git(work,'rev-parse','--path-format=absolute','--git-common-dir')).resolve()
    top=Path(git(work,'rev-parse','--show-toplevel')).resolve()
    if top!=work: raise ValueError('workspace must be repository root')
    if common.parent==work or (work/'.git').is_dir(): raise ValueError('primary checkout refused; use a linked worktree')
    branch=git(work,'symbolic-ref','--short','HEAD')
    if branch in ('main','master'): raise ValueError('dedicated branch required')
    return dict(real_path=str(work),git_common_dir=str(common),branch=branch,head=git(work,'rev-parse','HEAD'),tracked_status=git(work,'status','--porcelain=v1','--untracked-files=all'))


def validate_workspace(unit):
    f=fingerprint(unit['workspace'])
    if f['tracked_status']: raise ValueError('dirty workspace refused')
    return f


def prepare_packet(unit):
    unit=validate_unit(unit)
    work=Path(unit['workspace']).resolve()
    for item in unit['inputs']:
        p=confined(work,item['path'])
        if not p.is_file() or digest(p)!=item['sha256']: raise ValueError('input hash mismatch')
    return dict(schema='mai-code-packet-v1',unit=unit,fingerprint=validate_workspace(unit),files=inventory(work))


def inventory(work):
    """Includes ignored files: an ignored write is still a workspace change."""
    result={}
    raw=subprocess.check_output(['git','-C',str(work),'ls-files','-z','--cached','--others'])
    for rel in set(raw.decode('utf-8').split('\x00'))- {''}:
        p=confined(Path(work),rel)
        if p.is_file():result[rel]=digest(p)
    return result
