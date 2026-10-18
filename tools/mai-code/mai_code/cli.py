"""Explicit CLI operations. Read commands do not start model work."""
import argparse
import json
import sys
from pathlib import Path
from .unit import load_unit,prepare_packet,STAGES
from .store import create_run,load_state,read_json,lease_path
from .workflow import next_action,execute_stage,resume_decision
from .verify import verify_unit,check_existing
from .adapters.base import probe_cli
from . import __version__


def main(argv=None):
    p=argparse.ArgumentParser(prog='mai-code',description='Authenticated CLI module workflow. Draft alpha. No API fallback or automatic Git mutation.')
    p.add_argument('--version',action='version',version=__version__)
    sub=p.add_subparsers(dest='operation',required=True)
    doctor=sub.add_parser('doctor');doctor.add_argument('--engine',choices=['codex','claude','all'],default='all')
    prepare=sub.add_parser('prepare');prepare.add_argument('unit_file',type=Path);prepare.add_argument('--data-root',type=Path,default=Path.home()/'.mai'/'mai-code')
    for operation in ('status','run','resume','verify'):
        op=sub.add_parser(operation);op.add_argument('run',type=Path)
        if operation in ('run','resume'):
            op.add_argument('--through',choices=[*STAGES,'verify'],default='verify')
            op.add_argument('--allow-write',action='append',default=[],metavar='EXACT_OUTPUT',help='Explicit per-invocation native Claude file permission; only declared implementation outputs, no wildcards or global writes')
        if operation=='verify':op.add_argument('--existing',action='store_true')
    args=p.parse_args(argv)
    try:
        if args.operation=='doctor':
            rows=[]
            for engine in ('codex','claude') if args.engine=='all' else (args.engine,):
                try:rows.append(probe_cli(engine))
                except (ValueError,OSError):rows.append({'engine':engine,'diagnostic_codes':['probe-failed; executable/auth environment unavailable']})
            print(json.dumps(rows,ensure_ascii=False));return 0 if all(not r['diagnostic_codes'] for r in rows) else 2
        if args.operation=='prepare':
            packet=prepare_packet(load_unit(args.unit_file));run=create_run(packet,args.data_root)
            print(json.dumps({'run':str(run),'status':'prepared','model_calls':0}));return 0
        run=args.run.expanduser().resolve()
        if args.operation=='status':
            state=load_state(run);action=next_action(run)
            print(json.dumps(dict(state,run=str(run),action=action,lease_present=lease_path(run).exists()),ensure_ascii=False));return 0
        if args.operation=='verify':
            u=read_json(run/'packet.json')['unit']
            result=check_existing(run) if args.existing else verify_unit(run,u['test_argv'],u['negative_control_argv'])
            print(json.dumps(result));return 0 if result['passed'] else 1
        if args.operation=='resume':
            state=load_state(run)
            if state['current']:
                a=run/'attempts'/state['current']['attempt_id'];receipt=read_json(a/'receipt.json')
                decision=resume_decision(run,{'active':False,'session_id':receipt.get('native_session_id')})
                if decision['decision']!='continue_exact_session':raise ValueError(decision['reason'])
                result=execute_stage(run,decision['stage'],resume_id=decision['session_id'],approved_writes=args.allow_write)
                if result['status']!='passed':print(json.dumps(result));return 2
        end=(*STAGES,'verify').index(args.through)
        while True:
            action=next_action(run)
            if action['decision']=='complete':print(json.dumps({'status':'passed','run':str(run)}));return 0
            if action['decision']!='start_next_stage':raise ValueError('run needs explicit attention: '+action['reason'])
            stage=action['stage']
            if (*STAGES,'verify').index(stage)>end:print(json.dumps({'status':'boundary-complete','through':args.through,'next':stage,'run':str(run)}));return 0
            if stage=='verify':
                u=read_json(run/'packet.json')['unit'];result=verify_unit(run,u['test_argv'],u['negative_control_argv']);print(json.dumps(result));return 0 if result['unit_passed'] else 1
            result=execute_stage(run,stage,approved_writes=args.allow_write if stage=='implement' else ())
            if result['status']!='passed':print(json.dumps({'status':'needs-attention','stage':stage,'diagnostic':result.get('diagnostic'),'run':str(run)}));return 2
    except (ValueError,OSError,KeyError) as e:
        # Never include subprocess/environment exception representations or credentials.
        print(json.dumps({'status':'refused','reason':str(e) if isinstance(e,ValueError) else type(e).__name__}),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
