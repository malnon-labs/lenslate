"""Screenshot of the whole X screen: shot.py OUT.png [MAX_WIDTH] (run from the lenslate folder)."""
import os
import sys

sys.path.insert(0, os.getcwd())
from PySide6.QtGui import QImage  # noqa: E402

import x11  # noqa: E402

d, w, h, st = x11.grab_root()
im = QImage(d, w, h, st, QImage.Format_RGB32)
if len(sys.argv) > 2 and w > int(sys.argv[2]):
    im = im.scaledToWidth(int(sys.argv[2]))
im.save(sys.argv[1])
