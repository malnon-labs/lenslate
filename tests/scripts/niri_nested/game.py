"""A stand-in game for nested niri: a picture in a Wayland window.   game.py PICTURE [--full]"""
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel
app = QApplication(sys.argv[:1])
w = QLabel(); w.setWindowTitle("lenslate test game"); w.setAlignment(Qt.AlignCenter); w.setStyleSheet("background:black")
pm = QPixmap(sys.argv[1]); w.resize(1000, 600)
w.setPixmap(pm.scaled(1200, 700, Qt.KeepAspectRatio, Qt.SmoothTransformation))
w.showFullScreen() if "--full" in sys.argv else w.show()
app.exec()
