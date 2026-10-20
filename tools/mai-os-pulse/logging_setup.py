import logging, os, sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

def log_directory():
    if os.name=='nt': return Path(os.environ.get('LOCALAPPDATA',Path.home()))/'MaiOsPulse'/'logs'
    return Path(os.environ.get('XDG_STATE_HOME',Path.home()/'.local/state'))/'mai-os-pulse'

def configure():
    logger=logging.getLogger('pulse'); logger.setLevel(logging.INFO)
    try:
        root=log_directory();root.mkdir(parents=True,exist_ok=True)
        handler=RotatingFileHandler(root/'pulse.log',maxBytes=1024**2,backupCount=2,encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s'));logger.addHandler(handler)
    except OSError: logger.addHandler(logging.NullHandler())
    logger.info('mai-os Pulse 0.1.2 launch; platform=%s',sys.platform)
    def hook(kind,value,tb): logger.error('Unhandled exception',exc_info=(kind,value,tb))
    sys.excepthook=hook
