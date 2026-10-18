"""Owner-fixed unittest commands, with a specific failing negative control."""
import os
import re
import subprocess
from pathlib import Path
from .unit import STAGES,digest,inventory
from .store import acquire_lease,release_lease,new_attempt,write_receipt,immutable,read_json,save_state,record_event
from .workflow import context


def parse_test(output):
    count=re.findall(r'^Ran ([0-9]+) tests? in ',output,re.M)
    return int(count[0]) if len(count)==1 else 0


def verify_unit(run,test_argv,negative_control_argv):
    token=acquire_lease(run,{'pid':os.getpid(),'stage':'verify'})
    child_unknown=False;a=None;state=None
    try:
        state,packet,work,parent,expected=context(run);u=packet['unit']
        if 'verify' in state['completed']:parent=state['completed']['implement']['sha256']
        if state['current']:raise ValueError('unfinished model attempt requires reconciliation')
        if test_argv!=u['test_argv'] or negative_control_argv!=u['negative_control_argv']:raise ValueError('verification argv differs from prepared unit')
        if inventory(work)!=expected:raise ValueError('workspace changed before verification')
        a=new_attempt(run,'verify');results={};hashes={}
        state['completed'].pop('verify',None)
        state['status']='running';state['current']={'attempt_id':a.name,'stage':'verify'}
        save_state(run,state)
        record_event(run,{'type':'verification-started','attempt_id':a.name})
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
        for name,args in [('positive',test_argv),('negative',negative_control_argv)]:
            with (a/(name+'.stdout')).open('xb') as out,(a/(name+'.stderr')).open('xb') as err:
                child_unknown=True
                try:child=subprocess.run(args,cwd=work,stdin=subprocess.DEVNULL,stdout=out,stderr=err,env=env,shell=False)
                except (FileNotFoundError,PermissionError):
                    child_unknown=False
                    raise
                child_unknown=False
            text=(a/(name+'.stdout')).read_text(encoding='utf-8',errors='replace')+'\n'+(a/(name+'.stderr')).read_text(encoding='utf-8',errors='replace')
            results[name]={'exit_code':child.returncode,'count':parse_test(text),'text':text}
            for suffix in ('.stdout','.stderr'):hashes[name+suffix]=digest(a/(name+suffix))
        pos,neg=results['positive'],results['negative']
        bad_ids=re.findall(r'^FAIL: .+ \(([^\n]+)\)$',neg['text'],re.M)
        failures=u['contract']['negative_failures']
        negative=(neg['exit_code']!=0 and neg['count']>0 and neg['count']==pos['count'] and bad_ids==[u['contract']['negative_test_id']]*failures and re.search(r'^FAILED \(failures='+str(failures)+r'\)\s*$',neg['text'],re.M) is not None)
        good=pos['exit_code']==0 and pos['count']>0 and re.search(r'^OK\s*$',pos['text'],re.M) is not None
        unchanged=inventory(work)==expected
        passed=bool(good and negative and unchanged)
        report=dict(passed=passed,discovered_tests=pos['count'],exit_code=pos['exit_code'],negative_control_rejected=bool(negative),workspace_unchanged=unchanged,unit_passed=passed and all(s in state['completed'] for s in STAGES),evidence=str(a))
        receipt=dict(stage='verify',status='passed' if passed else 'failed',parent_sha256=parent,outputs={},evidence_hashes=hashes,report=report,commands={'positive':test_argv,'negative':negative_control_argv})
        write_receipt(a,receipt)
        if report['unit_passed']:state['completed']['verify']={'attempt_id':a.name,'sha256':digest(a/'receipt.json')}
        state['current']=None
        state['status']='passed' if report['unit_passed'] else ('awaiting-verification' if passed else 'failed')
        save_state(run,state)
        record_event(run,{'type':'verification','attempt_id':a.name,'receipt_sha256':digest(a/'receipt.json'),'passed':passed})
        return report
    except BaseException as e:
        if a is not None:
            state['status']='interrupted' if child_unknown else 'failed'
            save_state(run,state)
            record_event(run,{'type':'verification-incomplete','attempt_id':a.name,'error_type':type(e).__name__,'child_liveness_unknown':child_unknown})
        raise
    finally:
        if not child_unknown:release_lease(run,token)


def check_existing(run):
    state,packet,work,parent,expected=context(run)
    if state['current']:raise ValueError('latest verification or model attempt is incomplete')
    if inventory(work)!=expected:raise ValueError('workspace differs from recorded verification')
    events=[__import__('json').loads(line) for line in (run/'events.jsonl').read_text().splitlines()]
    refs=[r['event'] for r in events if r['event'].get('type')=='verification']
    if not refs:raise ValueError('no recorded verification')
    ref=refs[-1];a=run/'attempts'/ref['attempt_id']
    if digest(a/'receipt.json')!=ref['receipt_sha256']:raise ValueError('verification receipt changed')
    receipt=read_json(a/'receipt.json')
    for name,sha in receipt['evidence_hashes'].items():
        if digest(a/name)!=sha:raise ValueError('verification evidence changed')
    return receipt['report']
