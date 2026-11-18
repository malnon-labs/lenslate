"""Fake mouse and keyboard input on X (XTest): xt.py move=X,Y down=1 up=1 key=KEYCODE ... (X pixels; Esc = key 9)."""
import ctypes
import sys
import time

x = ctypes.CDLL("libX11.so.6")
t = ctypes.CDLL("libXtst.so.6")
x.XOpenDisplay.restype = ctypes.c_void_p
d = ctypes.c_void_p(x.XOpenDisplay(None))


def flush():
    x.XFlush(d)
    time.sleep(0.15)


for a in sys.argv[1:]:
    k, _, v = a.partition("=")
    if k == "move":
        px, py = map(int, v.split(","))
        t.XTestFakeMotionEvent(d, 0, px, py, 0)
    elif k == "down":
        t.XTestFakeButtonEvent(d, int(v), 1, 0)
    elif k == "up":
        t.XTestFakeButtonEvent(d, int(v), 0, 0)
    elif k == "key":
        t.XTestFakeKeyEvent(d, int(v), 1, 0)
        flush()
        t.XTestFakeKeyEvent(d, int(v), 0, 0)
    flush()
