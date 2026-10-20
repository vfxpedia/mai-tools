"""Bounded per-adapter jobs: never wait or create duplicates for a stuck probe."""
import logging, threading, time

class AsyncCache:
    def __init__(self):
        self.lock=threading.Lock(); self.jobs={}; self.closed=False
    def request(self,name,fn,interval):
        now=time.monotonic()
        with self.lock:
            if self.closed: return
            job=self.jobs.setdefault(name,{'busy':False,'started':0,'finished':0,'value':None,'error':'','starts':0,'done':threading.Event()})
            if job['busy'] or (job['started'] and now-job['started'] < interval): return
            job.update(busy=True,started=now,error='',starts=job['starts']+1); job['done'].clear()
        def run():
            value=None; error=''
            try: value=fn()
            except Exception as exc:
                error=f'{type(exc).__name__}: {exc}'; logging.getLogger('pulse').exception('Adapter failed: %s',name)
            finally:
                with self.lock:
                    job.update(value=value,error=error,finished=time.monotonic(),busy=False); job['done'].set()
        threading.Thread(target=run,name=f'Pulse-{name}',daemon=True).start()
    def status(self,name,max_age=25):
        now=time.monotonic()
        with self.lock:
            j=self.jobs.get(name)
            if not j: return {'state':'waiting','error':'','starts':0,'age':None}
            age=now-j['finished'] if j['finished'] else None
            state='error' if j['error'] else ('ready' if j['finished'] else 'waiting')
            if j['busy'] and now-j['started'] > max_age: state='blocked'
            elif age is not None and age > max_age: state='stale'
            return {'state':state,'error':j['error'],'starts':j['starts'],'age':age}
    def value(self,name,default,max_age=25):
        status=self.status(name,max_age)
        with self.lock:
            j=self.jobs.get(name)
            return j['value'] if j and j['value'] is not None and status['state']=='ready' else default
    def wait(self,name,timeout):
        with self.lock: event=self.jobs[name]['done']
        return event.wait(timeout)
    def close(self):
        with self.lock: self.closed=True
