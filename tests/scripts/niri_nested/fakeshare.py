"""Real lenslate with the portal stream replaced by a fixed picture (nested niri cannot screen-share): everything after
the capture - reading, translation, the layer-shell cards on niri - is the real code."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
PIC = sys.argv[1]                   # fakeshare.py PICTURE lenslate-arguments...
sys.argv = ["lenslate.py"] + sys.argv[2:]
import lenslate, portalcap
from PySide6.QtGui import QImage

class FakeStream:
    kind, size, position = portalcap.WINDOW, (1280, 800), None
    def frame(self, newer_than=0.0, wait=2.0):
        im = QImage(PIC).convertToFormat(QImage.Format_RGB32)
        return bytes(im.constBits()), im.width(), im.height(), im.bytesPerLine()
    def stop(self):
        pass

def fake_start(cls, on_error=None):
    cls.stream, cls.error, cls.starting = FakeStream(), None, False
lenslate.Shared.start = classmethod(fake_start)
sys.exit(lenslate.main())
