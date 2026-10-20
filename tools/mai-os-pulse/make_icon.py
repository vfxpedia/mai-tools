from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt
# Qt generates the PNG; ICO encoder uses stdlib, avoiding another dependency.
import struct
root=Path(__file__).resolve().parent/'assets'
app=QApplication([])
image=QImage(256,256,QImage.Format_ARGB32); image.fill(Qt.transparent)
painter=QPainter(image); QSvgRenderer(str(root/'pulse.svg')).render(painter); painter.end()
image.save(str(root/'pulse.png'))
png=(root/'pulse.png').read_bytes()
(root/'pulse.ico').write_bytes(struct.pack('<HHH',0,1,1)+struct.pack('<BBBBHHII',0,0,0,0,1,32,len(png),22)+png)
