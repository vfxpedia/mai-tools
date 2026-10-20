"""Read-only probes in child processes; only these probes are timed out."""
import os, sys, subprocess, time, traceback
from pathlib import Path
STAGES=['cpu_ram','gpu','volumes','disk_io','network','sensors','processes']

def probe(stage):
    from collector import Collector
    import psutil
    print('START '+stage,flush=True); t=time.monotonic(); c=None
    try:
        if stage=='cpu_ram':
            cores=psutil.cpu_percent(percpu=True); m=psutil.virtual_memory()
            print('logical='+str(len(cores))+' ram_total='+str(m.total),flush=True)
        elif stage=='sensors':
            from sensors import read_sensors
            print('sensors='+str(len(read_sensors())),flush=True)
        else:
            c=Collector()
            funcs={'gpu':c.collect_gpu,'volumes':c.collect_volumes,'disk_io':c.collect_disks,'network':c.collect_networks,'processes':c.process_sampler.sample}
            result=funcs[stage]()
            print(str(result)[:6000],flush=True)
        print(f'OK {stage} {time.monotonic()-t:.3f}s',flush=True)
    except Exception: traceback.print_exc(); raise
    finally:
        if c: c.close()

def main():
    if len(sys.argv)>2 and sys.argv[1]=='--probe': probe(sys.argv[2]); return
    target=Path(sys.argv[1]) if len(sys.argv)>1 else Path.cwd()/'Pulse-Diagnostics.txt'
    with target.open('w',encoding='utf-8') as out:
        def emit(text): print(text,flush=True);out.write(text+'\n');out.flush()
        emit('mai-os Pulse 0.1.2 diagnostics · '+time.strftime('%Y-%m-%d %H:%M:%S'))
        emit('No termination/optimization of user processes. Process names and interface information may appear.')
        env=dict(os.environ,PYTHONIOENCODING='utf-8')
        for stage in STAGES:
            emit('\n=== '+stage+' ===')
            try:
                result=subprocess.run([sys.executable,'-u',__file__,'--probe',stage],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=12,env=env)
                emit(result.stdout); emit(result.stderr); emit('EXIT '+str(result.returncode))
            except subprocess.TimeoutExpired as exc:
                emit('TIMEOUT after 12s · only the diagnostic child was stopped')
                data=exc.stdout or b'';emit(data.decode('utf-8',errors='replace') if isinstance(data,bytes) else data)
        try:
            from logging_setup import log_directory
            logfile=log_directory()/'pulse.log'
            if logfile.exists(): emit('\n=== recent app log ===\n'+logfile.read_text(encoding='utf-8',errors='replace')[-16000:])
        except OSError as exc: emit(str(exc))
    print('Saved: '+str(target),flush=True)
if __name__=='__main__': main()
