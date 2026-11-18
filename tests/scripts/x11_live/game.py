"""A stand-in game window for live X11 tests: shows a picture.
  game.py PICTURE [--fullscreen] [--at X,Y] [--mark-active]
--mark-active: set _NET_ACTIVE_WINDOW on the root window itself (a bare X server without a window manager)."""
import os
import subprocess
import sys

os.environ["QT_QPA_PLATFORM"] = "xcb"
from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

app = QApplication(sys.argv[:1])
args = sys.argv[1:]
w = QLabel()
w.setWindowTitle("lenslate test game")
pm = QPixmap(args[0])
if "--fullscreen" in args:
    g = app.primaryScreen().geometry()
    pm = pm.scaled(g.width(), g.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    w.setPixmap(pm)
    w.showFullScreen()
else:
    g = app.primaryScreen().availableGeometry()
    if pm.width() > g.width() * 0.6:
        pm = pm.scaled(int(g.width() * 0.6), int(g.height() * 0.6), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    w.setPixmap(pm)
    if "--at" in args:
        x, y = map(int, args[args.index("--at") + 1].split(","))
        w.move(x, y)
    w.show()


def mark():
    if "--mark-active" in args:
        subprocess.run(["xprop", "-root", "-f", "_NET_ACTIVE_WINDOW", "32x", "-set", "_NET_ACTIVE_WINDOW",
                        hex(int(w.winId()))])
    w.raise_()
    w.activateWindow()
    print("game window", hex(int(w.winId())), flush=True)


QTimer.singleShot(600, mark)
sys.exit(app.exec())
