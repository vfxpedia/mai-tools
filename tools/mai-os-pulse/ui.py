import json, threading, time, os, shutil, subprocess, logging
from logging_setup import log_directory
from collections import deque
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QTimer, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QIcon, QAction
from PySide6.QtWidgets import (QApplication,QWidget,QFrame,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QProgressBar,QScrollArea,QDialog,QGridLayout,QComboBox,QCheckBox,QSystemTrayIcon,QMenu,QFileDialog,QMessageBox,QTableWidget,QTableWidgetItem,QHeaderView)
from collector import Collector
from startup import set_startup

GIB = 1024**3

def fmt(value, suffix='', precision=0):
    return ' · ' if value is None else f'{value:.{precision}f}{suffix}'

def gib(value): return ' · ' if value is None else f'{value/GIB:.1f}'

def bandwidth(value):
    if value is None: return ' · '
    return f'{value/1024**2:.1f} MB/s' if value >= 1024**2 else f'{value/1024:.0f} KB/s'

STYLE = '''
QWidget { background:#10151c; color:#e1eaf1; font-family:"Segoe UI","Noto Sans CJK KR"; font-size:12px; }
QFrame#card { background:#18212b; border:1px solid #283443; border-radius:12px; }
QFrame#card QLabel { background:transparent; border:0; }
QLabel#muted { color:#93a5b6; font-size:11px; }
QLabel#eyebrow { color:#59dfbe; font-size:10px; font-weight:700; }
QLabel#hero { font-size:26px; font-weight:650; }
QPushButton { background:#202d3a; border:1px solid #354657; border-radius:6px; padding:6px 9px; }
QPushButton:hover { background:#2b4150; border-color:#59dfbe; }
QProgressBar { border:0; background:#263442; border-radius:3px; height:6px; }
QProgressBar::chunk { background:#59dfbe; border-radius:3px; }
QScrollArea { border:0; } QScrollBar:vertical { width:6px; background:#10151c; }
QScrollBar::handle:vertical { background:#354657; border-radius:3px; min-height:25px; }
QComboBox { border:1px solid #354657; padding:5px; background:#202d3a; }
QToolTip { background:#202d3a; color:#eef6ff; border:1px solid #59dfbe; }
'''

class Spark(QWidget):
    def __init__(self, color='#59dfbe'):
        super().__init__(); self.values=deque(maxlen=60); self.color=color; self.setFixedHeight(28)
        self.setToolTip('최근 60개 표본 · 기본 2초 간격, 숨김 시 10초 간격')
    def push(self, value): self.values.append(value); self.update()
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(self.color),1.5))
        previous=None
        for i,v in enumerate(self.values):
            if v is None: previous=None; continue
            point=QPointF(i*self.width()/59,self.height()-3-max(0,min(100,v))*(self.height()-6)/100)
            if previous is not None: p.drawLine(previous,point)
            previous=point

class Card(QFrame):
    def __init__(self,title,subtitle=''):
        super().__init__(); self.setObjectName('card')
        self.box=QVBoxLayout(self); self.box.setContentsMargins(13,10,13,10); self.box.setSpacing(6)
        self.title=QLabel(title); self.title.setObjectName('eyebrow'); self.box.addWidget(self.title)
        self.value=QLabel('수집 대기'); self.value.setObjectName('hero'); self.box.addWidget(self.value)
        self.bar=QProgressBar(); self.bar.setRange(0,100); self.bar.setTextVisible(False); self.bar.setFixedHeight(6); self.box.addWidget(self.bar)
        self.meta=QLabel(subtitle); self.meta.setObjectName('muted'); self.meta.setWordWrap(True); self.box.addWidget(self.meta)
        self.spark=Spark(); self.box.addWidget(self.spark)
    def update_value(self,text,percent,meta):
        self.value.setText(text); self.meta.setText(meta)
        self.bar.setValue(round(percent or 0)); self.bar.setVisible(percent is not None)
        self.spark.push(percent)

class Worker(QThread):
    sample_ready=Signal(dict); failed=Signal(str)
    def __init__(self,settings):
        super().__init__(); self.settings=settings; self.stop=threading.Event(); self.paused=False; self.hidden=False; self.interval=2
    def run(self):
        collector=None
        try:
            collector=Collector(self.settings)
            while not self.stop.is_set():
                if not self.paused:
                    try:
                        collector.settings=dict(self.settings)
                        self.sample_ready.emit(collector.sample())
                    except Exception as exc:
                        logging.getLogger('pulse').exception('CPU/RAM sampling failed')
                        self.failed.emit(f'{type(exc).__name__}: {exc}')
                self.stop.wait(10 if self.hidden else self.interval)
        except Exception as exc:
            logging.getLogger('pulse').exception('Collector initialization failed')
            self.failed.emit(f'{type(exc).__name__}: {exc}')
        finally:
            if collector: collector.close()

class Details(QDialog):
    def __init__(self,parent):
        super().__init__(parent); self.setWindowTitle('mai-os Pulse · 상세 관찰'); self.resize(680,780)
        box=QVBoxLayout(self)
        info=QLabel('논리 프로세서별 부하 · 물리 코어와 SMT를 합산하지 않습니다.'); info.setWordWrap(True); box.addWidget(info)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); self.body=QWidget(); self.layout=QVBoxLayout(self.body)
        scroll.setWidget(self.body); box.addWidget(scroll)
        self.cores=QWidget(); self.grid=QGridLayout(self.cores); self.cells=[]; self.layout.addWidget(self.cores)
        self.text=QLabel(); self.text.setWordWrap(True); self.text.setTextInteractionFlags(Qt.TextSelectableByMouse); self.layout.addWidget(self.text)
        self.layout.addStretch()
    def update_snapshot(self,s):
        if len(self.cells)!=len(s['cores']):
            for c in self.cells: self.grid.removeWidget(c); c.deleteLater()
            self.cells=[]
            for i in range(len(s['cores'])):
                cell=QLabel(); cell.setMinimumSize(66,36); cell.setAlignment(Qt.AlignCenter)
                self.grid.addWidget(cell,i//8,i%8); self.cells.append(cell)
        for i,(cell,v) in enumerate(zip(self.cells,s['cores'])):
            cell.setText(f'LP {i}\n{v:.0f}%'); cell.setStyleSheet(f'background:rgba(89,223,190,{int(25+v*1.6)});border-radius:4px;')
        lines=['GPU 식별 · UUID / PCI 버스 주소']
        for gpu in s['gpus']:
            lines.extend([f"GPU {gpu['index']} · {gpu['name']}",f"{gpu['uuid']} / {gpu['pci']}",
                          'Compute PID: '+(', '.join(map(str,gpu['pids'])) if gpu['pids'] is not None else '지원되지 않음')])
        lines.extend(['','로컬 볼륨 · 물리 SSD와 1:1 매핑을 추정하지 않음'])
        for v in s['volumes']:
            lines.append(f"{v['mount']} ({v['device']}) · {gib(v['used'])}/{gib(v['total'])} GiB · 여유 {gib(v['free'])} GiB")
        lines.extend(['','물리 디스크/블록 장치 I/O'])
        for d in s['disks']:
            lines.append(f"{d['name']} · R {bandwidth(d['read'])} / W {bandwidth(d['write'])} · busy {fmt(d['busy'],'%')}")
        lines.extend(['','메모리 사용 상위 프로세스 · 종료 기능 없음'])
        for p in sorted(s['processes'],key=lambda p:p['rss'],reverse=True)[:8]: lines.append(f"{p['name']} · PID {p['pid']} · RSS {gib(p['rss'])} GiB")
        lines.extend(['','추가 온도·전력 센서 · 갱신 10초'])
        for r in s['sensors']: lines.append(f"{r['label']} · {fmt(r['value'],r['unit'],1)} ({r['source']})")
        if not s['sensors']: lines.append('센서 미연결 · Windows: HWiNFO Gadget 설정 / Linux: hwmon 노출 확인')
        lines.extend(['',f"Swap/pagefile 사용량: {gib(s['swap']['used'])} GiB · RAM RSS와 의미가 다름",
                      'WDDM에서는 프로세스별 GPU VRAM을 신뢰할 수 없어 표시하지 않습니다.'])
        self.text.setText('\n'.join(lines))

class ProcessView(QDialog):
    def __init__(self,parent):
        super().__init__(parent); self.panel=parent; self.setWindowTitle('mai-os Pulse · 프로세스 진단'); self.resize(990,560)
        box=QVBoxLayout(self)
        label=QLabel('정리 후보를 판단하는 자료입니다. 오래 실행됨·높은 RSS만으로 종료를 권하지 않습니다.\nCPU 100% = 논리 프로세서 1개 · RSS에는 공유 메모리가 포함될 수 있음 · RAM 증가 추세는 누수 확정이 아님')
        label.setWordWrap(True); box.addWidget(label)
        controls=QHBoxLayout(); self.order=QComboBox()
        for label,key in [('RAM 사용량','rss'),('CPU 부하','cpu'),('오래 실행됨','age'),('RAM 증가량','growth')]: self.order.addItem(label,key)
        self.order.currentIndexChanged.connect(self.refresh); controls.addWidget(self.order)
        copy=QPushButton('선택 PID 복사'); copy.clicked.connect(self.copy_pid); controls.addWidget(copy)
        manager=QPushButton('시스템 작업 관리자 열기'); manager.clicked.connect(self.open_manager); controls.addWidget(manager); box.addLayout(controls)
        self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(['프로세스','PID','CPU %','RSS GiB','실행 시간','증가 MiB/분'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents); self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.setEditTriggers(QTableWidget.NoEditTriggers); box.addWidget(self.table)
        self.note=QLabel('최대 40개 · 10초 표본 · 프로세스를 종료하거나 메모리를 변경하지 않습니다.'); box.addWidget(self.note)
        self.refresh()
    def refresh(self):
        key=self.order.currentData() or 'rss'
        rows=sorted(self.panel.snapshot.get('processes',[]),key=lambda p:p.get(key) if p.get(key) is not None else -1,reverse=True)[:40]
        self.table.setRowCount(len(rows))
        for r,p in enumerate(rows):
            age=p['age']; hours=int(age//3600) if age is not None else None
            values=[p['name'],str(p['pid']),fmt(p['cpu'],precision=1),gib(p['rss']),f'{hours}h {int(age%3600//60)}m' if age is not None else ' · ',fmt(p['growth']/1024**2 if p['growth'] is not None else None,precision=1)]
            for c,value in enumerate(values): self.table.setItem(r,c,QTableWidgetItem(value))
        self.note.setText('열려 있을 때만 조회 · 별도 프로세스/5초 제한 · CPU는 두 번째 표본부터 표시')
    def copy_pid(self):
        row=self.table.currentRow()
        if row>=0: QApplication.clipboard().setText(self.table.item(row,1).text())
    def open_manager(self):
        try:
            if os.name=='nt': subprocess.Popen(['taskmgr.exe'])
            else:
                path=next((shutil.which(x) for x in ['gnome-system-monitor','plasma-systemmonitor','xfce4-taskmanager'] if shutil.which(x)),None)
                if not path: raise RuntimeError('설치된 시스템 모니터를 찾지 못했습니다.')
                subprocess.Popen([path])
        except Exception as exc: QMessageBox.information(self,'작업 관리자',str(exc))

class Preferences(QDialog):
    def __init__(self,parent):
        super().__init__(parent); self.setWindowTitle('mai-os Pulse · 설정'); self.resize(570,420); self.parent_panel=parent
        box=QVBoxLayout(self)
        desc=QLabel('온도·전력은 실제 센서를 선택합니다. 미지원 값은 · 로 표시합니다.\nHWiNFO 데이터는 15초 이상 레지스트리 갱신이 없으면 사용하지 않습니다.'); desc.setWordWrap(True); box.addWidget(desc)
        self.temp=QComboBox(); self.power=QComboBox()
        for combo,role,unit in [(self.temp,'cpu_temperature','°C'),(self.power,'cpu_power','W')]:
            combo.addItem('미지정 (Linux CPU 온도는 인식 가능한 경우 자동)',None)
            for r in parent.snapshot.get('sensors',[]):
                if r['unit']==unit: combo.addItem(r['label'],r['id'])
            idx=combo.findData(parent.mapping.get(role)); combo.setCurrentIndex(max(0,idx))
        box.addWidget(QLabel('CPU 온도 (Tctl/Tdie 또는 package)')); box.addWidget(self.temp)
        box.addWidget(QLabel('CPU 패키지 전력 (W)')); box.addWidget(self.power)
        self.screen=QComboBox()
        for i,s in enumerate(QApplication.screens()): self.screen.addItem(f'{i+1}: {s.name()}',i)
        self.screen.setCurrentIndex(min(parent.settings.value('screen',0,type=int),self.screen.count()-1))
        box.addWidget(QLabel('오른쪽 패널을 배치할 모니터')); box.addWidget(self.screen)
        self.interval=QComboBox()
        for seconds in [2,5,10]: self.interval.addItem(f'{seconds}초',seconds)
        self.interval.setCurrentIndex(max(0,self.interval.findData(parent.worker.interval)))
        box.addWidget(QLabel('표본 간격 · 숨김 상태는 최소 10초')); box.addWidget(self.interval)
        self.auto=QCheckBox('로그인 시 자동 시작'); self.auto.setChecked(parent.settings.value('autostart',False,type=bool)); box.addWidget(self.auto)
        note=QLabel('CPU·RAM·GPU·네트워크 기본 2초 / 공간·센서·프로세스 10초\n자동 시작은 현재 사용자에게만 적용됩니다.'); note.setObjectName('muted'); box.addWidget(note)
        save=QPushButton('저장'); save.clicked.connect(self.save); box.addWidget(save)
    def save(self):
        p=self.parent_panel
        try: set_startup(self.auto.isChecked())
        except Exception as exc:
            QMessageBox.warning(self,'자동 시작',str(exc)); return
        p.settings.setValue('autostart',self.auto.isChecked())
        p.mapping={'cpu_temperature':self.temp.currentData(),'cpu_power':self.power.currentData()}
        p.settings.setValue('sensors',json.dumps(p.mapping)); p.worker.settings=dict(p.mapping)
        p.settings.setValue('interval',self.interval.currentData()); p.worker.interval=self.interval.currentData()
        p.settings.setValue('screen',self.screen.currentIndex()); p.dock(); self.accept()

class Panel(QWidget):
    def __init__(self,icon):
        super().__init__(); self.setWindowTitle('mai-os Pulse 0.1.2'); self.setWindowIcon(icon)
        self.settings=QSettings('mai-os','Pulse'); self.mapping={}
        try: self.mapping=json.loads(self.settings.value('sensors','{}'))
        except (ValueError,TypeError): pass
        self.snapshot={}; self.history=deque(maxlen=60); self.detail=None; self.process_view=None; self.gpu_cards={}; self.last_received=0; self.last_error=''; self.launch_time=time.monotonic()
        self.setMinimumWidth(340); self.resize(380,880)
        outer=QVBoxLayout(self); outer.setContentsMargins(14,12,14,12); outer.setSpacing(8)
        brand=QLabel('mai-os  /  PULSE'); brand.setObjectName('eyebrow'); outer.addWidget(brand)
        self.host=QLabel('HOST · 연결 중'); self.host.setStyleSheet('font-size:21px;font-weight:650'); outer.addWidget(self.host)
        self.status=QLabel('읽기 전용 · 로컬 수집'); self.status.setObjectName('muted'); outer.addWidget(self.status)
        actions=QHBoxLayout()
        for text,fn in [('상세',self.show_details),('프로세스',self.show_processes),('설정',self.show_settings),('저장',self.export)]:
            b=QPushButton(text); b.clicked.connect(fn); actions.addWidget(b)
        outer.addLayout(actions)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); body=QWidget(); self.cards=QVBoxLayout(body); self.cards.setContentsMargins(0,0,5,0); self.cards.setSpacing(9)
        self.cpu=Card('CPU / COMPUTE'); self.ram=Card('MEMORY / HEADROOM')
        self.cards.addWidget(self.cpu); self.cards.addWidget(self.ram)
        self.gpu_placeholder=QLabel('GPU · NVML 연결 확인 중'); self.gpu_placeholder.setWordWrap(True); self.cards.addWidget(self.gpu_placeholder)
        self.gpu_box=QVBoxLayout(); self.cards.addLayout(self.gpu_box)
        self.storage=Card('STORAGE / LOCAL VOLUMES'); self.storage.spark.hide(); self.cards.addWidget(self.storage)
        self.net=Card('NETWORK / ACTIVE ADAPTERS'); self.net.spark.hide(); self.cards.addWidget(self.net)
        self.insight=QLabel('첫 표본 수집 중'); self.insight.setWordWrap(True); self.insight.setStyleSheet('color:#b4c4d3;padding:6px;'); self.cards.addWidget(self.insight)
        self.cards.addStretch(); scroll.setWidget(body); outer.addWidget(scroll)
        bottom=QHBoxLayout(); self.pause=QPushButton('수집 일시정지'); self.pause.clicked.connect(self.toggle_pause); bottom.addWidget(self.pause)
        hide=QPushButton('트레이로'); hide.clicked.connect(self.to_tray); bottom.addWidget(hide); outer.addLayout(bottom)
        self.cost=QLabel('앱 자체 부하 측정 중'); self.cost.setObjectName('muted'); outer.addWidget(self.cost)
        self.tray=QSystemTrayIcon(icon,self); menu=QMenu()
        for text,fn in [('패널 열기',self.reveal),('설정',self.show_settings),('완전히 종료',self.shutdown)]:
            action=menu.addAction(text); action.triggered.connect(fn)
        self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason:self.reveal() if reason==QSystemTrayIcon.Trigger else None)
        if QSystemTrayIcon.isSystemTrayAvailable(): self.tray.show()
        self.worker=Worker(self.mapping); self.worker.interval=self.settings.value('interval',2,type=int)
        self.worker.sample_ready.connect(self.safe_receive); self.worker.failed.connect(self.failure); self.worker.start()
        self.timer=QTimer(self); self.timer.timeout.connect(self.freshness); self.timer.start(1000)
        self.dock()
    def dock(self):
        screens=QApplication.screens(); idx=min(max(0,self.settings.value('screen',0,type=int)),len(screens)-1)
        rect=screens[idx].availableGeometry(); self.resize(min(380,rect.width()),min(900,rect.height()-24))
        self.move(rect.right()-self.width()-12,rect.top()+12)
    def receive(self,s):
        self.snapshot=s; self.history.append(s); self.last_received=time.monotonic()
        self.host.setText(s['host']); self.status.setText(f"{s['os']} · LIVE · {time.strftime('%H:%M:%S',time.localtime(s['time']))}")
        self.last_error=''
        cores=s['cores']; cpu=sum(cores)/len(cores) if cores else 0
        self.cpu.update_value(f'{cpu:.0f}%',cpu,
            f"{s['cpu_name']}\n{fmt(s['physical'])} cores / {len(cores)} logical · 최다 부하 {max(cores,default=0):.0f}%\n온도 {fmt(s['cpu_temperature'],'°C')} · 패키지 {fmt(s['cpu_power'],' W')}")
        ram=s['ram']; self.ram.update_value(f"{gib(ram['used'])} / {gib(ram['total'])} GiB",ram['percent'],f"사용 {ram['percent']:.0f}% · 사용 가능 {gib(ram['available'])} GiB")
        self.ram.value.setStyleSheet('font-size:21px;font-weight:650;')
        self.gpu_placeholder.setVisible(not s['gpus']); self.gpu_placeholder.setText('NVIDIA 센서 · '+(s.get('adapter_status',{}).get('gpu',{}).get('error') or s['gpu_error']))
        seen=set()
        for g in s['gpus']:
            key=g['uuid'] or str(g['index']); seen.add(key)
            if key not in self.gpu_cards:
                self.gpu_cards[key]=Card(f"GPU {g['index']} / {g['name']}"); self.gpu_box.addWidget(self.gpu_cards[key])
            card=self.gpu_cards[key]; card.title.setText(f"GPU {g['index']} / {g['name']}")
            card.update_value(f"{fmt(g['util'],'%')}  ·  {gib(g['used'])} / {gib(g['total'])} GiB",100*g['used']/g['total'] if g['total'] and g['used'] is not None else None,
                f"VRAM 할당 · 온도 {fmt(g['temperature'],'°C')} · 전력 {fmt(g['power'],' W')}")
            card.value.setStyleSheet('font-size:20px;font-weight:650;'); card.spark.setToolTip('VRAM 할당 비율 · GPU 연산 사용률과 별도 지표')
        for key,card in list(self.gpu_cards.items()):
            if key not in seen: self.gpu_box.removeWidget(card); card.deleteLater(); del self.gpu_cards[key]
        self.storage.value.setStyleSheet('font-size:15px;font-weight:600;')
        self.storage.update_value(f"{len(s['volumes'])} local volumes" if s.get('adapter_status',{}).get('volumes',{}).get('state','ready')=='ready' else '볼륨 수집 대기/확인 필요',None,'\n'.join([f"{v['mount']} · 여유 {gib(v['free'])} / {gib(v['total'])} GiB" for v in s['volumes']] + [f"{d['name']} · R {bandwidth(d['read'])} / W {bandwidth(d['write'])}" for d in s['disks'][:4]]) or '볼륨 정보 없음')
        self.net.value.setStyleSheet('font-size:15px;font-weight:600;')
        self.net.update_value(f"{len(s['networks'])} active adapters" if s.get('adapter_status',{}).get('network',{}).get('state','ready')=='ready' else '네트워크 수집 대기/확인 필요',None,'\n'.join(f"{n['name']}  ↓{bandwidth(n['rx'])}  ↑{bandwidth(n['tx'])}" for n in s['networks']) or '활성 어댑터 없음')
        issues=[f"{name}: {state['state']} {state.get('error','')}" for name,state in s.get('adapter_status',{}).items() if state['state'] in ('error','blocked','stale')]
        self.insight.setText('관찰 / '+ '\n'.join(s['observations'])+ ('\n수집 확인 필요 / '+'\n'.join(issues) if issues else ''))
        self.cost.setText(f"Pulse · CPU {fmt(s['monitor']['cpu'],'%',1)} (1코어 기준) · RAM {fmt(s['monitor']['rss']/1024**2 if s['monitor']['rss'] is not None else None,' MiB')}")
        if self.detail and self.detail.isVisible(): self.detail.update_snapshot(s)
        if self.process_view and self.process_view.isVisible(): self.process_view.refresh()
    def safe_receive(self,s):
        try:
            self.worker.settings['process_diagnostics']=bool(self.process_view and self.process_view.isVisible())
            self.receive(s)
        except Exception as exc:
            logging.getLogger('pulse').exception('UI snapshot rendering failed')
            self.failure(f'화면 갱신 오류: {type(exc).__name__}: {exc}')
    def freshness(self):
        self.pause.setText('수집 재개' if self.worker.paused else '수집 일시정지')
        if self.worker.paused:
            self.status.setText('PAUSED · 수집 재개 버튼을 누르세요'); return
        if self.last_error:
            self.status.setText('ERROR · '+self.last_error); return
        age=time.monotonic()-self.last_received if self.last_received else time.monotonic()-self.launch_time
        if not self.last_received and age>10:
            self.status.setText(f'첫 CPU/RAM 수집 지연 · {age:.0f}초 · 로그 확인 필요')
        elif self.last_received and age>max(15,self.worker.interval*3):
            self.status.setText(f'STALE · 마지막 수집 {age:.0f}초 전 · 표시값 확인 필요')
    def failure(self,error):
        self.last_error=error; self.status.setText('ERROR · '+error); self.status.setWordWrap(True)
        self.insight.setText('수집 오류: '+error+'\n진단 로그: '+str(log_directory()/'pulse.log'))
        self.status.setToolTip(error)
    def toggle_pause(self):
        self.worker.paused=not self.worker.paused; self.pause.setText('수집 재개' if self.worker.paused else '수집 일시정지')
    def show_details(self):
        if not self.snapshot: return
        if self.detail is None: self.detail=Details(self)
        self.detail.update_snapshot(self.snapshot); self.detail.show(); self.detail.raise_()
    def show_processes(self):
        if self.process_view is None: self.process_view=ProcessView(self)
        self.worker.settings['process_diagnostics']=True
        self.process_view.refresh(); self.process_view.show(); self.process_view.raise_()
    def show_settings(self): Preferences(self).exec()
    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'최근 표본 저장 · 프로세스명/PID 포함','mai-os-pulse-snapshot.json','JSON (*.json)')
        if path:
            try: Path(path).write_text(json.dumps({'version':'0.1.2','samples':list(self.history)},ensure_ascii=False,indent=2),encoding='utf-8')
            except OSError as exc: QMessageBox.warning(self,'저장 실패',str(exc))
    def to_tray(self):
        if self.tray.isVisible(): self.hide(); self.worker.hidden=True
        else: self.showMinimized()
    def reveal(self): self.worker.hidden=False; self.showNormal(); self.raise_(); self.activateWindow()
    def closeEvent(self,event):
        if self.tray.isVisible(): self.to_tray(); event.ignore()
        else: event.accept(); self.shutdown()
    def shutdown(self):
        self.timer.stop()
        # Connect before setting the event: a fast worker can finish immediately.
        self.worker.finished.connect(QApplication.instance().quit)
        self.hide(); self.tray.hide(); self.worker.stop.set()
        if not self.worker.isRunning(): QApplication.instance().quit()
