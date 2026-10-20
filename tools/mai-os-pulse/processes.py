"""On-demand process diagnostics in a bounded child, separate from GUI and core metrics."""
from collections import deque
import json, os, subprocess, sys, tempfile, threading, time
from pathlib import Path
import psutil

def growth_per_minute(history):
    if len(history)<2: return None
    elapsed=history[-1][0]-history[0][0]
    return (history[-1][1]-history[0][1])*60/elapsed if elapsed>0 else None

def scan_raw():
    rows=[]
    # Avoid Windows all-process parent/status lookups and repeated cpu_percent queries.
    for p in psutil.process_iter(['pid','name','memory_info','create_time','cpu_times']):
        try:
            info=p.info; mem=info['memory_info']; cpu=info['cpu_times']
            if mem is None: continue
            rows.append({'pid':info['pid'],'name':info['name'] or '?','rss':mem.rss,
                         'born':info['create_time'],'cpu_seconds':cpu.user+cpu.system if cpu else None})
        except (psutil.Error,OSError,TypeError):continue
    return rows

class ProcessSampler:
    def __init__(self):
        self.history={};self.previous={};self.lock=threading.Lock();self.child=None;self.closed=False
    def _raw(self):
        with self.lock:
            if self.closed: raise RuntimeError('Process diagnostics stopped')
        with tempfile.TemporaryDirectory(prefix='mai-pulse-probe-') as tmp:
            output=Path(tmp)/'processes.json'
            if getattr(sys,'frozen',False):cmd=[sys.executable,'--process-probe',str(output)]
            else:cmd=[sys.executable,str(Path(__file__).with_name('main.py')),'--process-probe',str(output)]
            with self.lock:
                if self.closed: raise RuntimeError('Process diagnostics stopped')
                child=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                self.child=child
            try:
                try: code=child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill();child.wait(timeout=2)
                    raise TimeoutError('프로세스 조회 5초 초과 · CPU/RAM 수집은 계속됩니다')
                if code!=0: raise RuntimeError(f'Process probe failed (exit {code})')
                data=json.loads(output.read_text(encoding='utf-8'))
                if not isinstance(data,list): raise ValueError('Invalid process probe data')
                return data
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=2)
                with self.lock:
                    if self.child is child:self.child=None
    def sample(self):
        raw=self._raw();now=time.monotonic();wall=time.time();rows=[];alive=set()
        for info in raw:
            born=info['born'];key=(info['pid'],born);alive.add(key);rss=info['rss'];cpu=None
            hist=self.history.setdefault(key,deque(maxlen=7));hist.append((now,rss))
            previous=self.previous.get(key);seconds=info['cpu_seconds']
            if previous and seconds is not None and previous[1] is not None and now>previous[0]:
                cpu=max(0,(seconds-previous[1])*100/(now-previous[0]))
            self.previous[key]=(now,seconds)
            rows.append({'pid':info['pid'],'ppid':None,'name':info['name'],'rss':rss,'cpu':cpu,
                         'age':max(0,wall-born) if born else None,'status':None,
                         'growth':growth_per_minute(hist),'history_seconds':hist[-1][0]-hist[0][0]})
        self.history={k:v for k,v in self.history.items() if k in alive};self.previous={k:v for k,v in self.previous.items() if k in alive}
        return rows
    def close(self):
        with self.lock:
            self.closed=True;child=self.child
            if child and child.poll() is None:child.terminate()
