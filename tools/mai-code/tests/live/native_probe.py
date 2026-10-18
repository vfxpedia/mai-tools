"""Opt-in TEST ONLY fixture. Default prepares locally without any model call."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from mai_code.unit import digest,prepare_packet,inventory
from mai_code.store import create_run,immutable,read_json,load_state
from mai_code.workflow import execute_stage,RESPONSE_SCHEMA
from mai_code.verify import verify_unit
from mai_code.adapters.base import build_command,child_environment,parse_event
from mai_code.transport import observe


def git(path,*args):
    subprocess.run(['git','-C',str(path),*args],check=True,capture_output=True)


def prepare(root,engine):
    root.mkdir(parents=True,exist_ok=False)
    primary=root/'primary';primary.mkdir()
    git(primary,'init','-q');git(primary,'config','user.name','Fixture');git(primary,'config','user.email','fixture@example.invalid')
    source=primary/'paper.txt'
    source.write_text('TEST ONLY. Section 1: Implement affine_loss(x,w,b,target) with Python standard library. x,w must be nonempty equal-length lists of finite numbers; b,target finite. On invalid shape or nonfinite values raise ValueError. Prediction y=sum(x_i*w_i)+b; loss=(y-target)**2; dw_i=2*(y-target)*x_i; db=2*(y-target); dx_i=2*(y-target)*w_i. Return (y,loss,dw,db,dx). This is a synthetic affine/MSE fixture, not a real paper. Output file affine.py, no dependency installation. Read the fixed test but never modify it. Analysis/plan are returned as structured JSON, do not write files for those stages.',encoding='utf-8')
    shutil.copyfile(Path(__file__).parents[1]/'fixtures/test_affine.py',primary/'test_affine.py')
    git(primary,'add','.');git(primary,'commit','-qm','TEST ONLY affine fixture')
    work=root/'owned';git(primary,'worktree','add','-qb','mai-code-fixture-'+engine,str(work))
    inputs=[dict(path=p.name,sha256=digest(p),references=['section 1' if p.name=='paper.txt' else 'fixed acceptance tests']) for p in (work/'paper.txt',work/'test_affine.py')]
    u=dict(schema='mai-code-unit-v1',unit_id='affine-'+engine,issue_url='https://github.com/vfxpedia/mai-tools/issues/1',workspace=str(work),inputs=inputs,contract={'module':'TEST ONLY affine_loss returning prediction,loss,dw,db,dx. No dependency or acceptance-test edits. First analyze structure, then plan, then implement affine.py.','negative_test_id':'__main__.AffineTests.test_known_gradients','negative_failures':1},outputs=['analysis.json','plan.json','affine.py'],engines={s:{'engine':engine} for s in ('analyze','plan','implement')},test_argv=[sys.executable,'-B','test_affine.py'],test_framework='unittest',negative_control_argv=[sys.executable,'-B','test_affine.py','--negative'])
    immutable(root/'unit.json',u)
    return create_run(prepare_packet(u),root/'data')


def resume_check(run):
    state=load_state(run);ref=state['completed']['analyze'];original=run/'attempts'/ref['attempt_id']
    old=read_json(original/'receipt.json');engine=old['engine'];sid=old['native_session_id']
    # A read-only conversation continuation, not a replay of a completed workflow stage.
    a=run/'native-continuation';a.mkdir(exist_ok=False)
    immutable(a/'cli.json',old['cli']);immutable(a/'response-schema.json',RESPONSE_SCHEMA)
    immutable(a/'request.json',{'instruction':'Read-only continuation check of your own completed synthetic fixture analysis. Do not edit files or use tools. Return stage analyze, summary MAI-CODE-CONTINUATION-OK, assumptions [], references [section 1], changes []. No analysis replay is requested.'})
    work=Path(read_json(run/'packet.json')['unit']['workspace']);before=inventory(work)
    result=observe(build_command(engine,'analyze',a,old['requested_model'],sid),work,a/'request.json',a,child_environment(engine),120)
    events=[parse_event(engine,json.loads(line)) for line in (a/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    ids={e['session_id'] for e in events if e.get('session_id')}
    passed=result['status']=='transport-complete' and ids=={sid} and not any(e['kind']=='error' for e in events) and any(e['kind']=='complete' for e in events) and inventory(work)==before and digest(original/'receipt.json')==ref['sha256']
    report={'passed':passed,'exact_session_id':sid,'original_receipt_unchanged':digest(original/'receipt.json')==ref['sha256'],'transport':result}
    immutable(a/'report.json',report);return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--engine',choices=['codex','claude'],required=True)
    p.add_argument('--execute',action='store_true');p.add_argument('--existing',type=Path);p.add_argument('--resume-check',action='store_true')
    args=p.parse_args()
    run=args.existing.resolve() if args.existing else prepare(args.root.resolve(),args.engine)
    print(json.dumps({'run':str(run),'model_calls':0,'execute_requested':args.execute}),flush=True)
    if not args.execute:return 0
    for stage in ('analyze','plan','implement'):
        if stage in load_state(run)['completed']:continue
        r=execute_stage(run,stage)
        print(json.dumps({'stage':stage,'status':r['status'],'session_id':r['native_session_id'],'diagnostic':r.get('diagnostic'),'usage':r['usage']}),flush=True)
        if r['status']!='passed':return 2
    u=read_json(run/'packet.json')['unit'];result=verify_unit(run,u['test_argv'],u['negative_control_argv']);print(json.dumps(result),flush=True)
    if not result['unit_passed']:return 1
    if args.resume_check:
        report=resume_check(run);print(json.dumps(report),flush=True)
        if not report['passed']:return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
