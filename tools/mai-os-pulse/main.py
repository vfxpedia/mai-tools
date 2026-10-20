import os, sys
from pathlib import Path
def main():
    if len(sys.argv)>2 and sys.argv[1]=='--process-probe':
        import json
        from processes import scan_raw
        Path(sys.argv[2]).write_text(json.dumps(scan_raw(),ensure_ascii=False),encoding='utf-8')
        return 0
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtCore import QTimer
    from ui import Panel, STYLE
    from logging_setup import configure
    configure()
    app=QApplication(sys.argv); app.setApplicationName('mai-os Pulse'); app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    # QLocalServer is local IPC, not a TCP server; a second launch raises the existing panel.
    name='mai-os-pulse-'+os.environ.get('USERNAME',os.environ.get('USER','default'))
    client=QLocalSocket(); client.connectToServer(name)
    if client.waitForConnected(250):
        client.write(b'open'); client.flush(); client.waitForBytesWritten(250); return 0
    QLocalServer.removeServer(name); server=QLocalServer(); server.listen(name)
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    icon=QIcon(str(root/'assets'/'pulse.svg')); app.setWindowIcon(icon)
    panel=Panel(icon)
    def reveal():
        socket=server.nextPendingConnection()
        if socket: socket.close(); socket.deleteLater()
        panel.reveal()
    server.newConnection.connect(reveal); panel.show()
    if '--screenshot' in sys.argv:
        idx=sys.argv.index('--screenshot'); target=sys.argv[idx+1]
        def capture(): panel.grab().save(target); panel.shutdown()
        QTimer.singleShot(3500,capture)
    return app.exec()

if __name__=='__main__': raise SystemExit(main())
