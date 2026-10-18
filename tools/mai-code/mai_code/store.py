"""Local evidence, immutable attempts and conservative workspace leases."""
import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from .unit import encoded, digest


def read_json(path):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError) as e: raise ValueError('missing or invalid evidence: '+Path(path).name) from e


def immutable(path,value):
    with Path(path).open('xb') as f:
        f.write(encoded(value)); f.flush(); os.fsync(f.fileno())


def atomic(path,value):
    path=Path(path)
    fd,name=tempfile.mkstemp(prefix='.state-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f: f.write(encoded(value)); f.flush(); os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)


def create_run(packet,data_root):
    root=Path(data_root).expanduser().resolve()
    work=Path(packet['fingerprint']['real_path'])
    if root.is_relative_to(work) or work.is_relative_to(root): raise ValueError('evidence root must be outside workspace and not its ancestor')
    project=hashlib.sha256(str(work).encode()).hexdigest()[:20]
    run=root/project/packet['unit']['unit_id']
    run.mkdir(parents=True,exist_ok=False)
    (run/'inputs').mkdir(); (run/'attempts').mkdir()
    immutable(run/'packet.json',packet)
    for i,item in enumerate(packet['unit']['inputs']):
        dest=run/'inputs'/str(i)
        with dest.open('xb') as out, (work/item['path']).open('rb') as source: shutil.copyfileobj(source,out)
        if digest(dest)!=item['sha256']: raise ValueError('input changed during preparation')
    save_state(run,dict(schema='mai-code-state-v1',status='prepared',completed={},current=None,packet_sha256=digest(run/'packet.json')))
    record_event(run,dict(type='prepared'))
    return run


def load_state(run):
    s=read_json(run/'state.json')
    if not isinstance(s,dict) or set(s)!={'schema','status','completed','current','packet_sha256'} or s['schema']!='mai-code-state-v1' or not isinstance(s['completed'],dict): raise ValueError('invalid state schema')
    if s['status'] not in ('prepared','running','awaiting-verification','passed','failed','paused-quota','needs-attention','interrupted'): raise ValueError('invalid state status')
    if digest(run/'packet.json')!=s['packet_sha256']: raise ValueError('packet hash changed')
    for line in (run/'events.jsonl').read_text(encoding='utf-8').splitlines():
        try: event=json.loads(line)
        except ValueError as e: raise ValueError('truncated event ledger') from e
        if not isinstance(event,dict) or event.get('schema')!='mai-code-event-v1': raise ValueError('invalid event schema')
    return s


def save_state(run,state): atomic(run/'state.json',state)


def record_event(run,event):
    with (run/'events.jsonl').open('ab') as f:
        f.write(encoded(dict(schema='mai-code-event-v1',time_ns=time.time_ns(),event=event))+b'\n'); f.flush(); os.fsync(f.fileno())


def new_attempt(run,stage):
    if stage not in ('analyze','plan','implement','verify'): raise ValueError('invalid stage')
    attempt=run/'attempts'/(str(time.time_ns())+'-'+stage+'-'+uuid.uuid4().hex[:8])
    attempt.mkdir()
    immutable(attempt/'attempt.json',dict(schema='mai-code-attempt-v1',attempt_id=attempt.name,stage=stage))
    return attempt


def write_receipt(attempt,receipt):
    immutable(attempt/'receipt.json',dict(schema='mai-code-receipt-v1',**receipt))


def lease_path(run):
    load_state(run)
    work=Path(read_json(run/'packet.json')['fingerprint']['real_path']).resolve()
    identity=hashlib.sha256(os.path.normcase(str(work)).encode()).hexdigest()
    return work.parent/'.mai-code-locks'/(identity+'.json')


def acquire_lease(run,owner):
    path=lease_path(run)
    # Old-format locks remain a stop condition; migration never removes them.
    if (run.parent/'workspace.lease.json').exists():raise ValueError('legacy workspace lease requires reconciliation')
    path.parent.mkdir(exist_ok=True)
    if path.parent.is_symlink() or (hasattr(path.parent,'is_junction') and path.parent.is_junction()) or path.parent.resolve()!=path.parent:
        raise ValueError('workspace lease directory must not be a link')
    token=uuid.uuid4().hex
    try: immutable(path,dict(schema='mai-code-lease-v1',token=token,owner=owner,time_ns=time.time_ns()))
    except FileExistsError as e: raise ValueError('workspace lease exists; liveness is unknown, no automatic removal') from e
    return token


def release_lease(run,token):
    lease=read_json(lease_path(run))
    if lease.get('schema')!='mai-code-lease-v1' or lease.get('token')!=token: raise ValueError('not lease owner')
    lease_path(run).unlink()
