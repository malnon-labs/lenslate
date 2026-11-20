"""X11 sessions: find the game window and capture it, with Xlib through ctypes (no extra package).

Window capture uses the Composite extension the way OBS's "Window capture (Xcomposite)" does: the window is
redirected to an off-screen pixmap (automatic mode: it is still drawn on screen as before) and that pixmap is read.
The picture holds only that window - never lenslate's own cards, and other windows on top of it do not matter - with
or without a compositing manager. Whole-screen capture (the area picker, areas that belong to no window) reads the
root window, i.e. what is on screen.

Every function returns None (or False) when X answers with an error, e.g. the window was just closed. Coordinates
are X pixels (physical); lenslate.py converts to Qt's logical ones.
"""
import ctypes
import ctypes.util
import threading
from ctypes import POINTER, byref, c_char_p, c_int, c_long, c_uint, c_ulong, c_void_p

_LOCK = threading.RLock()
_X = None           # libX11
_XC = None          # libXcomposite (None: not installed)
_DPY = None
_ERR = [0]
_REDIRECTED = set()
_ATOMS = {}


class _XImage(ctypes.Structure):
    _fields_ = [("width", c_int), ("height", c_int), ("xoffset", c_int), ("format", c_int), ("data", c_void_p),
                ("byte_order", c_int), ("bitmap_unit", c_int), ("bitmap_bit_order", c_int), ("bitmap_pad", c_int),
                ("depth", c_int), ("bytes_per_line", c_int), ("bits_per_pixel", c_int)]


class _XErrorEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("display", c_void_p), ("resourceid", c_ulong), ("serial", c_ulong),
                ("error_code", ctypes.c_ubyte), ("request_code", ctypes.c_ubyte), ("minor_code", ctypes.c_ubyte)]


class _XWindowAttributes(ctypes.Structure):
    _fields_ = [("x", c_int), ("y", c_int), ("width", c_int), ("height", c_int), ("border_width", c_int),
                ("depth", c_int), ("visual", c_void_p), ("root", c_ulong), ("class_", c_int), ("bit_gravity", c_int),
                ("win_gravity", c_int), ("backing_store", c_int), ("backing_planes", c_ulong),
                ("backing_pixel", c_ulong), ("save_under", c_int), ("colormap", c_ulong), ("map_installed", c_int),
                ("map_state", c_int), ("all_event_masks", c_long), ("your_event_mask", c_long),
                ("do_not_propagate_mask", c_long), ("override_redirect", c_int), ("screen", c_void_p)]


class _XClassHint(ctypes.Structure):
    _fields_ = [("res_name", c_void_p), ("res_class", c_void_p)]     # raw pointers: they are freed with XFree


@ctypes.CFUNCTYPE(c_int, c_void_p, POINTER(_XErrorEvent))
def _on_error(_dpy, ev):
    _ERR[0] = ev.contents.error_code      # Xlib's default handler would end the whole process
    return 0


def _open():
    """Connect once; False when there is no X server (or no libX11)."""
    global _X, _XC, _DPY
    if _DPY:
        return True
    if _X is False:
        return False
    try:
        x = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    except OSError:
        _X = False
        return False
    x.XInitThreads()
    x.XOpenDisplay.restype = c_void_p
    x.XOpenDisplay.argtypes = [c_char_p]
    dpy = x.XOpenDisplay(None)
    if not dpy:
        _X = False
        return False
    for name, res, args in (
            ("XDefaultRootWindow", c_ulong, [c_void_p]),
            ("XInternAtom", c_ulong, [c_void_p, c_char_p, c_int]),
            ("XGetWindowProperty", c_int, [c_void_p, c_ulong, c_ulong, c_long, c_long, c_int, c_ulong,
                                           POINTER(c_ulong), POINTER(c_int), POINTER(c_ulong), POINTER(c_ulong),
                                           POINTER(c_void_p)]),
            ("XFree", c_int, [c_void_p]),
            ("XGetGeometry", c_int, [c_void_p, c_ulong, POINTER(c_ulong), POINTER(c_int), POINTER(c_int),
                                     POINTER(c_uint), POINTER(c_uint), POINTER(c_uint), POINTER(c_uint)]),
            ("XTranslateCoordinates", c_int, [c_void_p, c_ulong, c_ulong, c_int, c_int, POINTER(c_int),
                                              POINTER(c_int), POINTER(c_ulong)]),
            ("XGetImage", POINTER(_XImage), [c_void_p, c_ulong, c_int, c_int, c_uint, c_uint, c_ulong, c_int]),
            ("XDestroyImage", c_int, [POINTER(_XImage)]),
            ("XFreePixmap", c_int, [c_void_p, c_ulong]),
            ("XSync", c_int, [c_void_p, c_int]),
            ("XGetClassHint", c_int, [c_void_p, c_ulong, POINTER(_XClassHint)]),
            ("XQueryPointer", c_int, [c_void_p, c_ulong, POINTER(c_ulong), POINTER(c_ulong), POINTER(c_int),
                                      POINTER(c_int), POINTER(c_int), POINTER(c_int), POINTER(c_uint)]),
            ("XGetSelectionOwner", c_ulong, [c_void_p, c_ulong]),
            ("XDefaultScreen", c_int, [c_void_p]),
            ("XChangeProperty", c_int, [c_void_p, c_ulong, c_ulong, c_ulong, c_int, c_int, c_void_p, c_int]),
            ("XRaiseWindow", c_int, [c_void_p, c_ulong]),
            ("XQueryTree", c_int, [c_void_p, c_ulong, POINTER(c_ulong), POINTER(c_ulong), POINTER(c_void_p),
                                   POINTER(c_uint)]),
            ("XGetWindowAttributes", c_int, [c_void_p, c_ulong, POINTER(_XWindowAttributes)])):
        f = getattr(x, name)
        f.restype, f.argtypes = res, args
    x.XSetErrorHandler(_on_error)
    try:
        xc = ctypes.CDLL(ctypes.util.find_library("Xcomposite") or "libXcomposite.so.1")
        xc.XCompositeQueryExtension.argtypes = [c_void_p, POINTER(c_int), POINTER(c_int)]
        xc.XCompositeRedirectWindow.argtypes = [c_void_p, c_ulong, c_int]
        xc.XCompositeNameWindowPixmap.restype = c_ulong
        xc.XCompositeNameWindowPixmap.argtypes = [c_void_p, c_ulong]
        a, b = c_int(), c_int()
        if not xc.XCompositeQueryExtension(dpy, byref(a), byref(b)):
            xc = None
    except OSError:
        xc = None
    _X, _XC, _DPY = x, xc, dpy
    return True


def available():
    with _LOCK:
        return _open()


def _atom(name):
    if name not in _ATOMS:
        _ATOMS[name] = _X.XInternAtom(_DPY, name.encode(), 0)
    return _ATOMS[name]


def _ok():
    """Flush and report whether the requests since the last check went through."""
    _X.XSync(_DPY, 0)
    bad, _ERR[0] = _ERR[0], 0
    return not bad


def _root():
    return _X.XDefaultRootWindow(_DPY)


def active_window():
    """Id of the focused top-level window (EWMH _NET_ACTIVE_WINDOW, set by every usual window manager), or None."""
    with _LOCK:
        if not _open():
            return None
        typ, fmt, n, left, data = c_ulong(), c_int(), c_ulong(), c_ulong(), c_void_p()
        st = _X.XGetWindowProperty(_DPY, _root(), _atom("_NET_ACTIVE_WINDOW"), 0, 1, 0, 0, byref(typ), byref(fmt),
                                   byref(n), byref(left), byref(data))
        if st != 0 or not data.value:
            _ok()
            return None
        wid = ctypes.cast(data, POINTER(c_ulong))[0] if n.value else 0
        _X.XFree(data)
        _ok()
        return int(wid) or None


def _ids(wid, name):
    """A list-of-ids property (windows or atoms, format 32) of a window, or []."""
    with _LOCK:
        if not _open():
            return []
        typ, fmt, n, left, data = c_ulong(), c_int(), c_ulong(), c_ulong(), c_void_p()
        st = _X.XGetWindowProperty(_DPY, wid, _atom(name), 0, 4096, 0, 0, byref(typ), byref(fmt), byref(n),
                                   byref(left), byref(data))
        if st != 0 or not data.value:
            _ok()
            return []
        arr = ctypes.cast(data, POINTER(c_ulong))
        out = [int(arr[i]) for i in range(n.value)] if fmt.value == 32 else []
        _X.XFree(data)
        _ok()
        return out


def stacking():
    """The window manager's top-level windows, bottom to top (EWMH _NET_CLIENT_LIST_STACKING), or []."""
    return _ids(_root(), "_NET_CLIENT_LIST_STACKING")


def hidden(wid):
    """The window is minimised (EWMH _NET_WM_STATE_HIDDEN)."""
    with _LOCK:
        if not _open():
            return False
        atom = _atom("_NET_WM_STATE_HIDDEN")
    return atom in _ids(wid, "_NET_WM_STATE")


def geometry(wid):
    """(x, y, w, h) of a window's contents on the screen, or None if it is gone."""
    with _LOCK:
        if not _open():
            return None
        root, x, y, w, h, bw, depth = c_ulong(), c_int(), c_int(), c_uint(), c_uint(), c_uint(), c_uint()
        child = c_ulong()
        _ok()
        if not _X.XGetGeometry(_DPY, wid, byref(root), byref(x), byref(y), byref(w), byref(h), byref(bw), byref(depth)):
            _ok()
            return None
        ax, ay = c_int(), c_int()
        _X.XTranslateCoordinates(_DPY, wid, root.value, 0, 0, byref(ax), byref(ay), byref(child))
        if not _ok():
            return None
        return ax.value, ay.value, int(w.value), int(h.value)


def window_class(wid):
    """The window's class name (Wine/Proton games: the exe name), or ""."""
    with _LOCK:
        if not _open():
            return ""
        hint = _XClassHint()
        _ok()
        got = _X.XGetClassHint(_DPY, wid, byref(hint))
        if not _ok() or not got:
            return ""
        p = hint.res_class or hint.res_name
        name = ctypes.string_at(p).decode("utf-8", "replace") if p else ""
        for p in (hint.res_name, hint.res_class):
            if p:
                _X.XFree(p)
        return name


def pointer():
    """(x, y) of the mouse on the screen, or None."""
    with _LOCK:
        if not _open():
            return None
        r, c, rx, ry, wx, wy, mask = c_ulong(), c_ulong(), c_int(), c_int(), c_int(), c_int(), c_uint()
        ok = _X.XQueryPointer(_DPY, _root(), byref(r), byref(c), byref(rx), byref(ry), byref(wx), byref(wy), byref(mask))
        _ok()
        return (rx.value, ry.value) if ok else None


def compositing():
    """A compositing manager runs (windows can be see-through). Without one, cards have to be opaque."""
    with _LOCK:
        if not _open():
            return False
        owner = _X.XGetSelectionOwner(_DPY, _atom("_NET_WM_CM_S%d" % _X.XDefaultScreen(_DPY)))
        _ok()
        return bool(owner)


def raise_window(wid):
    """Put a window on top of the others again (an unmanaged overlay is covered when a game window is raised)."""
    with _LOCK:
        if _open():
            _X.XRaiseWindow(_DPY, wid)
            _ok()


def _image(drawable, x, y, w, h):
    """Pixels of a drawable as (bytes, width, height, bytes per line), 32 bits per pixel (BGRX), or None."""
    _ok()
    img = _X.XGetImage(_DPY, drawable, x, y, w, h, 0xFFFFFFFF, 2)     # all planes, ZPixmap
    if not _ok() or not img:
        return None
    try:
        i = img.contents
        if i.bits_per_pixel != 32 or not i.data:
            return None
        return ctypes.string_at(i.data, i.bytes_per_line * i.height), i.width, i.height, i.bytes_per_line
    finally:
        _X.XDestroyImage(img)


def grab_root():
    """What is on the whole X screen (all monitors): (bytes, w, h, stride) or None."""
    with _LOCK:
        if not _open():
            return None
        g = geometry(_root())
        if g is None:
            return None
        return _image(_root(), 0, 0, g[2], g[3])


def grab_window(wid):
    """The window's own picture, whatever covers it: (bytes, w, h, stride), or None (no Composite extension, the
    window is minimised or gone)."""
    with _LOCK:
        if not _open() or _XC is None:
            return None
        g = geometry(wid)
        if g is None:
            return None
        if wid not in _REDIRECTED:
            _XC.XCompositeRedirectWindow(_DPY, wid, 0)       # 0 = automatic: still drawn on screen by the server
            if not _ok():
                return None
            _REDIRECTED.add(wid)
            if len(_REDIRECTED) > 64:
                _REDIRECTED.clear()
                _REDIRECTED.add(wid)
        pix = _XC.XCompositeNameWindowPixmap(_DPY, wid)
        if not _ok() or not pix:
            _REDIRECTED.discard(wid)
            return None
        try:
            return _image(pix, 0, 0, g[2], g[3])
        finally:
            _X.XFreePixmap(_DPY, pix)
            _ok()


NOTIFICATION_TYPES = ("_NET_WM_WINDOW_TYPE_NOTIFICATION", "_KDE_NET_WM_WINDOW_TYPE_ON_SCREEN_DISPLAY",
                      "_KDE_NET_WM_WINDOW_TYPE_CRITICAL_NOTIFICATION")


def _children(wid):
    """The direct children of a window (for the root: WM frames and unmanaged windows such as notification popups)."""
    root, parent, kids, n = c_ulong(), c_ulong(), c_void_p(), c_uint()
    _ok()
    if not _X.XQueryTree(_DPY, wid, byref(root), byref(parent), byref(kids), byref(n)):
        _ok()
        return []
    out = []
    if kids.value:
        arr = ctypes.cast(kids, POINTER(c_ulong))
        out = [int(arr[i]) for i in range(n.value)]
        _X.XFree(kids)
    _ok()
    return out


def _viewable(wid):
    a = _XWindowAttributes()
    _ok()
    got = _X.XGetWindowAttributes(_DPY, wid, byref(a))
    return bool(_ok() and got and a.map_state == 2)       # IsViewable


def notification_rects():
    """(x, y, w, h) in X pixels of every notification window on screen (EWMH _NET_WM_WINDOW_TYPE_NOTIFICATION:
    xfce4-notifyd, MATE, dunst, KDE on X11). Cinnamon and GNOME draw theirs inside the shell: no window to find."""
    with _LOCK:
        if not _open():
            return []
        wanted = {_atom(n) for n in NOTIFICATION_TYPES}
        out = []
        for wid in dict.fromkeys(stacking() + _children(_root())):
            if wanted.intersection(_ids(wid, "_NET_WM_WINDOW_TYPE")) and _viewable(wid):
                g = geometry(wid)
                if g is not None and g[2] > 1 and g[3] > 1:
                    out.append(g)
        return out
