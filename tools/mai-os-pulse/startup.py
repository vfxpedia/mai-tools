"""Current-user login startup only. Never modifies global startup or services."""
import os, sys, subprocess
from pathlib import Path

def launch_command():
    if getattr(sys, 'frozen', False): return [sys.executable]
    executable = Path(sys.executable)
    if os.name == 'nt': executable = executable.with_name('pythonw.exe')
    return [str(executable),str(Path(__file__).resolve().with_name('main.py'))]

def set_startup(enabled):
    cmd = launch_command()
    if os.name == 'nt':
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            if enabled: winreg.SetValueEx(key,'MaiOsPulse',0,winreg.REG_SZ,subprocess.list2cmdline(cmd))
            else:
                try: winreg.DeleteValue(key,'MaiOsPulse')
                except FileNotFoundError: pass
    elif sys.platform.startswith('linux'):
        root = Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'autostart'
        target = root/'mai-os-pulse.desktop'
        if enabled:
            root.mkdir(parents=True,exist_ok=True)
            # Desktop Entry quoting is not shell quoting; percent must be escaped.
            escaped = ['"'+s.replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"' for s in cmd]
            target.write_text('[Desktop Entry]\nType=Application\nName=mai-os Pulse\nExec='+ ' '.join(escaped)+'\nTerminal=false\nX-GNOME-Autostart-enabled=true\n',encoding='utf-8')
        else: target.unlink(missing_ok=True)
    else:
        raise RuntimeError('이 버전의 자동 시작은 Windows와 Linux 데스크톱만 지원합니다.')
