"""Collectors run off the UI thread. No CUDA contexts or management writes."""
import os, platform, time, socket
from async_cache import AsyncCache
import psutil
from metrics import rate, observations
from sensors import read_sensors, selected
from processes import ProcessSampler

class Collector:
    def __init__(self, settings=None):
        self.settings = settings or {}
        self.last = time.monotonic()
        self.net = {}
        self.io = {}
        self.net_at = None
        self.io_at = None
        self.cache = AsyncCache()
        self.physical = None
        self.host = socket.gethostname()
        self.slow_at = 0
        self.slow = {'volumes':[], 'sensors':[], 'processes':[]}
        self.nv = None
        self.gpu_error = ''
        self.nv_retry_at = 0
        self.process_sampler = ProcessSampler()
        try:
            self.own = psutil.Process()
            self.own.cpu_percent()
        except psutil.Error:
            self.own = None
        psutil.cpu_percent(percpu=True)
        self.cpu_name = os.environ.get('PROCESSOR_IDENTIFIER') or platform.machine()
        if platform.system() == 'Linux':
            try:
                with open('/proc/cpuinfo') as cpuinfo:
                    for line in cpuinfo:
                        if line.startswith('model name'):
                            self.cpu_name = line.split(':',1)[1].strip(); break
            except OSError: pass
        if os.name == 'nt':
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                    self.cpu_name = winreg.QueryValueEx(key,'ProcessorNameString')[0].strip()
            except OSError: pass

    def reconnect_gpu(self, now):
        if self.nv or now < self.nv_retry_at: return
        self.nv_retry_at = now + 30
        try:
            import pynvml
            pynvml.nvmlInit(); self.nv = pynvml; self.gpu_error = ''
        except Exception as exc: self.gpu_error = type(exc).__name__

    def gpu_read(self):
        nv = self.nv
        if not nv: return []
        def safe(fn, *args):
            try: return fn(*args)
            except nv.NVMLError: return None
        def decode(x): return x.decode() if isinstance(x,bytes) else x
        gpus = []
        try: count = nv.nvmlDeviceGetCount()
        except nv.NVMLError:
            self.gpu_error = 'NVML connection lost'
            try: nv.nvmlShutdown()
            except nv.NVMLError: pass
            self.nv = None; return []
        for i in range(count):
            try: h = nv.nvmlDeviceGetHandleByIndex(i)
            except nv.NVMLError: continue
            mem = safe(nv.nvmlDeviceGetMemoryInfo,h)
            util = safe(nv.nvmlDeviceGetUtilizationRates,h)
            pci = safe(nv.nvmlDeviceGetPciInfo,h)
            power = safe(nv.nvmlDeviceGetPowerUsage,h)
            processes = safe(nv.nvmlDeviceGetComputeRunningProcesses,h)
            gpus.append({'index':i,'uuid':decode(safe(nv.nvmlDeviceGetUUID,h)),
                         'pci':decode(pci.busId) if pci else None,
                         'name':decode(safe(nv.nvmlDeviceGetName,h)) or 'NVIDIA GPU',
                         'used':mem.used if mem else None,'total':mem.total if mem else None,
                         'util':util.gpu if util else None,'temperature':safe(nv.nvmlDeviceGetTemperature,h,0),
                         'power':power/1000 if power is not None else None,
                         'pids':[p.pid for p in processes] if processes is not None else None})
        return gpus

    def collect_volumes(self):
        volumes = []
        for p in psutil.disk_partitions(all=False):
            if p.fstype.lower() in ('nfs','nfs4','cifs','smbfs','fuse.sshfs'):
                continue
            if os.name == 'nt':
                import ctypes
                if ctypes.windll.kernel32.GetDriveTypeW(p.mountpoint) != 3: continue
            try:
                usage = psutil.disk_usage(p.mountpoint)
                volumes.append({'device':p.device,'mount':p.mountpoint,'used':usage.used,'total':usage.total,'free':usage.free})
            except OSError: continue
        return volumes

    def collect_networks(self):
        now=time.monotonic(); elapsed=max(.001,now-self.net_at) if self.net_at else 1
        current_net=psutil.net_io_counters(pernic=True); stats=psutil.net_if_stats(); networks=[]
        for name,n in current_net.items():
            if name.lower().startswith(('lo','loopback')) or (name in stats and not stats[name].isup): continue
            prev=self.net.get(name)
            networks.append({'name':name,'rx':rate(n.bytes_recv,prev.bytes_recv if prev else None,elapsed),
                             'tx':rate(n.bytes_sent,prev.bytes_sent if prev else None,elapsed)})
        self.net,self.net_at=current_net,now
        return networks

    def collect_disks(self):
        now=time.monotonic(); elapsed=max(.001,now-self.io_at) if self.io_at else 1
        current_io=psutil.disk_io_counters(perdisk=True) or {}; disks=[]
        for name,d in current_io.items():
            if name.startswith(('loop','ram')): continue
            prev=self.io.get(name)
            disks.append({'name':name,'read':rate(d.read_bytes,prev.read_bytes if prev else None,elapsed),
                          'write':rate(d.write_bytes,prev.write_bytes if prev else None,elapsed),
                          'busy':min(100,rate(d.busy_time,prev.busy_time if prev else None,elapsed)/10) if prev and hasattr(d,'busy_time') else None})
        self.io,self.io_at=current_io,now
        return disks

    def collect_gpu(self):
        self.reconnect_gpu(time.monotonic())
        return {'gpus':self.gpu_read(),'gpu_error':self.gpu_error}

    def sample(self):
        # CPU/RAM must not wait for GPU, volumes, process enumeration or sensor export.
        cores=psutil.cpu_percent(percpu=True); ram=psutil.virtual_memory()
        monitor={'cpu':None,'rss':None}
        if self.own:
            try: monitor={'cpu':self.own.cpu_percent(),'rss':self.own.memory_info().rss}
            except psutil.Error: pass
        for name,fn,interval in [('gpu',self.collect_gpu,2),('volumes',self.collect_volumes,10),
                ('sensors',read_sensors,10),
                ('network',self.collect_networks,2),('disk_io',self.collect_disks,2),
                ('physical',lambda:psutil.cpu_count(logical=False),3600),
                ('swap',lambda:psutil.swap_memory()._asdict(),10)]:
            self.cache.request(name,fn,interval)
        if self.settings.get('process_diagnostics',False):
            self.cache.request('processes',self.process_sampler.sample,10)
        sensors=self.cache.value('sensors',[])
        temp=selected(sensors,self.settings.get('cpu_temperature'))
        if temp is None and not self.settings.get('cpu_temperature') and platform.system()=='Linux':
            choices=[r for r in sensors if r['id'].startswith(('k10temp/Tctl/','coretemp/Package id 0/'))]
            if len(choices)==1: temp=choices[0]['value']
        snap={'time':time.time(),'host':self.host,'os':platform.system(),'cpu_name':self.cpu_name,
              'physical':self.cache.value('physical',None,7200),'cores':cores,
              'cpu_temperature':temp,'cpu_power':selected(sensors,self.settings.get('cpu_power')),
              'ram':{'used':ram.used,'available':ram.available,'total':ram.total,'percent':ram.percent},
              'swap':self.cache.value('swap',{'used':None}),
              **self.cache.value('gpu',{'gpus':[],'gpu_error':'초기화 중'}),
              'networks':self.cache.value('network',[]),'disks':self.cache.value('disk_io',[]),
              'volumes':self.cache.value('volumes',[]),'sensors':sensors,
              'processes':self.cache.value('processes',[]) if self.settings.get('process_diagnostics',False) else [],'monitor':monitor,
              'adapter_status':{name:self.cache.status(name) for name in ['gpu','volumes','processes','sensors','network','disk_io','swap']}}
        snap['observations']=observations(snap)
        return snap

    def close(self):
        self.cache.close()
        self.process_sampler.close()
        if self.nv and self.cache.status('gpu')['state'] != 'blocked' and not self.cache.jobs.get('gpu',{}).get('busy'):
            try: self.nv.nvmlShutdown()
            except self.nv.NVMLError: pass
