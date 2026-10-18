"""Lossless dual-stream observation. Attention never terminates a child."""
import json
import subprocess
import threading
import time
from .unit import encoded, digest


def observe(command,cwd,stdin_path,attempt,env,attention_after_s=None):
    if not command or any(not isinstance(a,str) for a in command):raise ValueError('command must be argv')
    if attention_after_s is not None and attention_after_s<=0:raise ValueError('positive attention threshold required')
    started=time.monotonic(); attention=False; errors=[]
    def lifecycle(event,**extra):
        with (attempt/'lifecycle.jsonl').open('ab') as f:f.write(encoded(dict(event=event,elapsed_s=time.monotonic()-started,**extra))+b'\n');f.flush()
    # Exclusive destinations prevent accidental overwrite on a replay.
    with (attempt/'stdout.bin').open('xb') as out,(attempt/'stderr.bin').open('xb') as err,stdin_path.open('rb') as request:
        child=subprocess.Popen(command,cwd=cwd,stdin=request,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,shell=False)
        lifecycle('started',pid=child.pid)
        def drain(source,dest):
            try:
                while True:
                    block=source.read(65536)
                    if not block:break
                    dest.write(block);dest.flush()
            except Exception as e:errors.append(type(e).__name__)
            finally:source.close()
        threads=[threading.Thread(target=drain,args=(child.stdout,out)),threading.Thread(target=drain,args=(child.stderr,err))]
        for t in threads:t.start()
        while child.poll() is None:
            if attention_after_s is not None and not attention and time.monotonic()-started>=attention_after_s:
                attention=True;lifecycle('attention',pid=child.pid,status='needs-attention')
            time.sleep(0.02)
        for t in threads:t.join()
        code=child.wait();lifecycle('exited',pid=child.pid,exit_code=code)
    count=0;malformed=0
    # Bounded per-record parser; all bytes remain on disk, including oversized records.
    with (attempt/'stdout.bin').open('rb') as raw,(attempt/'events.jsonl').open('xb') as events:
        while True:
            line=raw.readline(4*1024*1024+1)
            if not line:break
            if len(line)>4*1024*1024:
                malformed+=1
                while line and not line.endswith(b'\n'):line=raw.readline(4*1024*1024+1)
                continue
            try:
                record=json.loads(line.decode('utf-8'))
                if not isinstance(record,dict):raise ValueError('not object')
            except (ValueError,UnicodeError):malformed+=1;continue
            events.write(encoded(record)+b'\n');count+=1
    return dict(pid=child.pid,exit_code=code,status='transport-complete' if code==0 and count and not malformed and not errors else 'needs-attention',stdout='stdout.bin',stderr='stderr.bin',events='events.jsonl',stdout_sha256=digest(attempt/'stdout.bin'),stderr_sha256=digest(attempt/'stderr.bin'),event_count=count,malformed_events=malformed,attention_triggered=attention,drain_errors=errors)
