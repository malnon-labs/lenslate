#!/usr/bin/env python3
"""lenslate - live-ish screen translation overlay (KDE Plasma Wayland; X11 and portal capture are new).

Pick a screen region once. lenslate reads the text in it with a local OCR model (RapidOCR), translates new lines
with the chosen translator (quickmt / Sugoi on the processor, a language model on the graphics card, or an online
service) and paints the translations over the original text in a click-through, always-on-top overlay. Already-translated lines come from a saved text cache; only areas of the picture
that changed are read again.

Commands (sent to the running instance, which is started on demand):
  lenslate select   choose the region (drag a box), then translate it
  lenslate now      read + translate the whole chosen region again
  lenslate auto     toggle auto-refresh (re-reads only what changed)
  lenslate toggle   hide / show the overlay (hiding pauses auto-refresh); "clear" is the same
  lenslate reset    remove the overlay and forget the current screen
  lenslate opacity [0.1-1]   card background opacity (saved in config.toml; default 1)
  lenslate preset [nogpu | balanced | fastest]   several settings at once (see config.py PRESETS)
  lenslate setup    the first-launch setup window again (languages, preset with hardware check, downloads)
  lenslate testbench [--presets a,b] [IMAGES]   time every preset on test screens + preview the translations
  lenslate hwcheck  what lenslate found in this PC (processor, graphics, memory) and which presets fit it
  lenslate translator [llm [MODEL] | mt | sugoi | online]   who translates new text (saved in config.toml):
                    llm = a language model on the GPU (default Gemma 4 E2B; `lenslate models` lists them), mt =
                    quickmt on the CPU (literal, OK for menus), sugoi = quickmt for menus + Sugoi v4 for dialogue
                    (CPU), online = the chosen online service; mt/sugoi use no VRAM
  lenslate serve    hook mode: translation endpoint for XUnity.AutoTranslator (Unity games), see hookserve.py
  lenslate names [GAME | scan FOLDER [MODEL] | ok GAME all|NAME...]   per-game character names (see names.py)
  lenslate models [list | get NAME | remove NAME]   translation models (see models.py)
  lenslate hook [status | install | remove | pretranslate] GAME_FOLDER   translate inside the game (see hooks.py)
  lenslate region X Y W H [SCREEN]   set the region directly (screen-local px, e.g. DP-2)
  lenslate status   one line of JSON: auto, hidden, region, translator (used by the GUI)
  lenslate capture  how lenslate takes its picture on this desktop, and what to know about it (docs/CAPTURE.md)
  lenslate share    (screen-sharing portal only) choose another window or screen to share
  lenslate hotkeys [install | remove | DESKTOP]   the keys for select / now / auto / toggle on this desktop:
                    ready-to-paste lines (Hyprland, Sway, i3, niri, Xfce, MATE); writes them on Cinnamon and GNOME
  lenslate version  the version of lenslate (also --version)
  lenslate gui      settings window and tray icon
  lenslate quit     stop lenslate

Settings: ~/.config/lenslate/config.toml (every setting is explained in the file; see config.py).
Each can be overridden for one run with its environment variable, e.g. LENSLATE_DEBUG=1.
"""
import base64
import json
import os
import re
import subprocess
import sys
import queue
import tempfile
import threading
import time
import urllib.request

import numpy as np
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QLockFile, QObject, QPoint, QRect, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QImage, QPainter
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtQml import QQmlApplicationEngine

import names as nm
import notifications as notif
import textflow as tf

# X11 session (no Wayland compositor), or forced for a test with LENSLATE_PLATFORM=x11: windows, capture and the
# overlay go through X (x11.py, overlay-x11.qml). Otherwise Wayland with KWin + layer-shell.
import captureinfo  # noqa: E402 - the one place that decides the capture method (and explains it)

CAPTURE = captureinfo.platform()        # "kwin", "x11" or "portal"
X11 = CAPTURE == "x11"
if X11:
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    import x11 as xb
else:
    # Layer-shell makes the overlay a real Wayland overlay-layer surface (above fullscreen games).
    os.environ.setdefault("QT_WAYLAND_SHELL_INTEGRATION", "layer-shell")
# The overlay is plain 2D. The software renderer needs no VRAM, which matters because the game and the
# vision model already fill the GPU (the GPU renderer then silently draws nothing).
os.environ.setdefault("QT_QUICK_BACKEND", "software")
HERE = os.path.dirname(os.path.abspath(__file__))
APP_ID = "lenslate"
SOCK = "lenslate-%d" % os.getuid()
import config as cfgmod
import version

cfgmod.migrate()   # old config.json -> config.toml, once
# Settings that need a restart are read once here; the rest are read where used (see config.py for all of them).
# Screen-sharing portal + PipeWire (portalcap.py): the capture path of Wayland desktops other than KDE, or chosen
# with [capture] backend = "portal".
PORTAL = CAPTURE == "portal"
MODEL = cfgmod.get("ocr.vlm_model")          # image model for the vlm engine
LANG = cfgmod.get("translator.language")
OLLAMA = cfgmod.get("translator.ollama_url")
SEND_WIDTH = 1280  # downscale the crop before sending; faster, still accurate
def fast_reading():
    """[ocr] reading = fast: the quick detector's lines go straight to the reader (may miss small text)."""
    return cfgmod.get("ocr.reading") in ("fast", "ultrafast") and os.environ.get("LENSLATE_FAST_LINES", "1") != "0"



SERIAL_TRANSLATE = os.environ.get("LENSLATE_SERIAL_TRANSLATE") == "1"   # testing: no reading/translating overlap
BIG_TEXT = 48                    # [ocr] big_text = half: areas whose lines are this tall are read at half size
FAST_LINES_MAX = 300             # fast reading: areas with more found lines than this are read the full way (testbench
                                 # 2026-11-10: the fast route (no re-checks) was 1.5-3x faster on
                                 # menus and text pages at almost the same text; 6 sent every busy menu down the slow way)
FAST_FULL_READ_PX = 900 * 600   # bigger first/forced reads: the detector finds the lines, the reader reads only those
JUNK_SECONDS = 30.0             # an area re-read without finding anything to translate is ignored this long
ENGINE = cfgmod.get("ocr.engine")
CONFIG_PATH = cfgmod.CONFIG_PATH
DEBUG = cfgmod.get("debug.enabled")


STARTED = time.time()


def code_changed_since(t):
    """lenslate's own files changed after this process started (it runs an older version)."""
    try:
        return any(os.path.getmtime(os.path.join(HERE, f)) > t for f in os.listdir(HERE) if f.endswith(".py"))
    except OSError:
        return False


def settle_step():
    return cfgmod.get("refresh.settle_step")


def settle_max():
    return cfgmod.get("refresh.settle_max")


def wanted_translator():
    """(kind, llm model) from config.toml [translator] (or LENSLATE_TRANSLATOR / LENSLATE_MODEL)."""
    return cfgmod.get("translator.kind"), cfgmod.get("translator.llm_model")


def clamp_opacity(v):
    return max(0.1, min(1.0, float(v)))
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir())
CACHE_PATH = cfgmod.cache_path()

PROMPT = (
    "Find every separate block of readable text in this image (dialogue, menus, buttons, labels, signs). "
    "Output one line per block and nothing else, in exactly this format:\n"
    "x1,y1,x2,y2|original text|%s translation\n"
    "Coordinates are the block's tight bounding box on a 0-1000 scale relative to the image. "
    "Put a multi-line block on one line (join its lines with a space). "
    "Skip text that is already in %s. If there is no other text, output NONE."
) % (LANG, LANG)
MAX_BLOCKS = 30
LINE_RE = re.compile(r"^\W*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\W*\|(.*?)\|(.*)$")


# ----------------------------------------------------------------------------- capture
def capture_all():
    """Full capture of every monitor via Spectacle (one retry: a concurrent Spectacle run makes it fail)."""
    try:
        return _capture_all()
    except (RuntimeError, subprocess.SubprocessError):
        QThread.msleep(300)
        return _capture_all()


def x_image(got):
    """QImage from x11.py's (bytes, width, height, bytes per line)."""
    if got is None:
        return QImage()
    data, w, h, stride = got
    return QImage(data, w, h, stride, QImage.Format_RGB32).copy()    # copy: own the pixels


def x_to_logical(x, y):
    """An X pixel position as a Qt logical one. Qt keeps each screen's top-left corner in X pixels and divides only
    the distance inside the screen by the scale; so with monitors side by side one global factor is wrong for every
    monitor but the first (KDE XWayland at 100 % + 125 %: DP-3 starts at X 2400 and at logical 2400, not 1920 -
    lenslate never found the game window there, 2026-11-13)."""
    best = None
    for s in QGuiApplication.screens():
        g, k = s.geometry(), s.devicePixelRatio() or 1.0
        nw, nh = g.width() * k, g.height() * k
        if g.x() <= x < g.x() + nw and g.y() <= y < g.y() + nh:
            best = (g, k)
            break
        d = max(g.x() - x, 0, x - (g.x() + nw)) + max(g.y() - y, 0, y - (g.y() + nh))
        if best is None or d < best[2]:
            best = (g, k, d)
    if best is None:
        return QPoint(round(x), round(y))
    g, k = best[0], best[1]
    return QPoint(g.x() + round((x - g.x()) / k), g.y() + round((y - g.y()) / k))


def x_target(wid):
    g = xb.geometry(wid)
    if g is None:
        return None
    tl = x_to_logical(g[0], g[1])
    k = x_scale_at(g[0], g[1])
    return Target(str(wid), QRect(tl.x(), tl.y(), round(g[2] / k), round(g[3] / k)))


def x_scale_at(x, y):
    """X pixels per logical pixel on the screen at an X position."""
    p = x_to_logical(x, y)
    sc = QGuiApplication.screenAt(p) or QGuiApplication.primaryScreen()
    return (sc.devicePixelRatio() or 1.0) if sc is not None else 1.0


class Shared:
    """The window or screen shared through the portal (PORTAL mode). The desktop's dialog is answered once, in a
    background thread started with lenslate; until then captures say that sharing is not ready."""
    stream = None
    error = None
    starting = False
    told = False

    @classmethod
    def start(cls, on_error=None):
        if cls.starting or cls.stream is not None:
            return
        cls.starting, cls.error = True, None

        def work():
            import portalcap
            if not portalcap._load_token():      # the desktop is about to ask: say what to pick
                notify("Your desktop now asks what lenslate may see. " + captureinfo.PORTAL_CHOICE)
            try:
                gone = portalcap.missing()
                if gone:
                    raise portalcap.PortalError("screen capture needs " + gone)
                cls.stream = portalcap.Stream().start()
                dbg("portal: sharing a %s, size %s" % ("window" if cls.stream.kind == portalcap.WINDOW else "screen",
                                                       cls.stream.size))
            except Exception as e:  # noqa: BLE001 - shown to the user
                cls.error = str(e)
                if on_error:
                    on_error(cls.error)
            finally:
                cls.starting = False
        threading.Thread(target=work, daemon=True).start()

    @classmethod
    def stop(cls):
        st, cls.stream = cls.stream, None
        if st is not None:
            st.stop()

    @classmethod
    def is_window(cls):
        import portalcap
        return cls.stream is not None and cls.stream.kind == portalcap.WINDOW

    @classmethod
    def image(cls, fresh=False):
        """The newest picture (fresh: one drawn after now-ish, e.g. after the cards were hidden)."""
        if cls.stream is None:
            raise RuntimeError(cls.error or ("answer your desktop's screen-sharing question first" if cls.starting
                                             else "screen sharing is not running (lenslate share)"))
        img = x_image(cls.stream.frame(newer_than=time.time() - 0.05 if fresh else 0.0, wait=0.7 if fresh else 2.0))
        if img.isNull():
            raise RuntimeError("no picture from the shared %s yet" % ("window" if cls.is_window() else "screen"))
        return img

    @classmethod
    def screen_rect(cls, img=None):
        """The monitor the shared picture belongs to: a shared screen by its reported position and size; a shared
        window is taken to fill a monitor (the portal does not say where a window is): the one with its shape."""
        screens = QGuiApplication.screens()
        st = cls.stream
        if st is not None and not cls.is_window() and st.position is not None:
            for s in screens:
                if (s.geometry().x(), s.geometry().y()) == tuple(st.position):
                    return s.geometry()
        if img is not None and not img.isNull():
            shape = img.width() / max(1, img.height())
            best = min(screens, key=lambda s: (abs(s.geometry().width() / max(1, s.geometry().height()) - shape),
                                               s is not QGuiApplication.primaryScreen()))
            return best.geometry()
        return QGuiApplication.primaryScreen().geometry()


def _capture_all():
    if PORTAL:
        img = Shared.image(fresh=not Shared.is_window())     # a shared screen shows our cards: wait for them to go
        return img, Shared.screen_rect(img)
    if X11:
        img = x_image(xb.grab_root())
        if img.isNull():
            raise RuntimeError("screen capture failed")
        bounds = QRect()
        for s in QGuiApplication.screens():
            bounds = bounds.united(s.geometry())
        return img, bounds
    fd, path = tempfile.mkstemp(suffix=".png", prefix="lenslate-")
    os.close(fd)
    try:
        subprocess.run(["spectacle", "-f", "-b", "-n", "-o", path], check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        img = QImage(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if img.isNull():
        raise RuntimeError("screen capture failed")
    bounds = QRect()
    for s in QGuiApplication.screens():
        bounds = bounds.united(s.geometry())
    return img, bounds


class Target:
    """A window by KWin id (what kdotool prints, e.g. {6c4d...}; on X11 the window id as text) and its global
    logical geometry."""
    def __init__(self, uuid, rect):
        self.uuid, self.rect = uuid, rect

    def __repr__(self):
        return "Target(%s, %s)" % (self.uuid, self.rect.getRect())


def _kdotool_geometry(args):
    try:
        out = subprocess.run(["kdotool"] + args, capture_output=True, text=True, timeout=2).stdout
        uuid = re.search(r"Window (\{[0-9a-f-]+\})", out).group(1)
        # KWin 6.8 reports fractional positions/sizes (e.g. 262.42000000000695): parse decimals and round them
        # (whole numbers only made every such window unknown, so auto refresh never found its target)
        num = r"(-?\d+(?:\.\d+)?)"
        x, y = [round(float(v)) for v in re.search(r"Position:\s*%s,\s*%s" % (num, num), out).groups()]
        w, h = [round(float(v)) for v in re.search(r"Geometry:\s*%sx%s" % (num, num), out).groups()]
        return Target(uuid, QRect(x, y, w, h))
    except Exception:  # noqa: BLE001
        return None


def covers(win_rect, region):
    """The window is the capture target for this area: it holds the whole area (2 px slack for rounded fractional
    window edges), or most of it - a windowed game with a title bar and the taskbar inside a whole-monitor area
    (a test on 2026-11-10: auto mode skipped every refresh there), or an area drawn a bit bigger than the window.
    A small window somewhere inside the area (a terminal, lenslate's own settings window) is not the target.
    The part of the area outside the window is captured as black (no text, no change)."""
    if win_rect.contains(region.adjusted(2, 2, -2, -2)):
        return True
    inter = win_rect.intersected(region)
    if inter.isEmpty():
        return False
    return inter.width() * inter.height() >= 0.6 * region.width() * region.height()


def moved_region(region, old, new):
    """An area (global logical px) carried along with its window from rect old to rect new: shifted when the window
    was moved, scaled with it when it was resized (windowed -> fullscreen: games scale their picture)."""
    if old.width() <= 0 or old.height() <= 0 or old.size() == new.size():
        return region.translated(new.topLeft() - old.topLeft())
    fx, fy = new.width() / old.width(), new.height() / old.height()
    return QRect(round(new.x() + (region.x() - old.x()) * fx), round(new.y() + (region.y() - old.y()) * fy),
                 max(1, round(region.width() * fx)), max(1, round(region.height() * fy)))


def vanished_cards(cards, mask, known, width, height, share=0.8):
    """Old cards whose text is gone for sure: nearly all of the picture under the card changed (a new scene, a
    closed dialogue box) AND the quick text finder sees no line there any more. They come down at the start of a
    refresh instead of staying over the new picture until their area has been read (seconds on a big change).
    A card on text that is still there (moving background, text being typed out) is never in this list."""
    out = []
    for c in cards:
        r = c["rect"]
        box = [r.x(), r.y(), r.right() + 1, r.bottom() + 1]
        if tf.cells_share(mask, box, width, height) >= share and not any(tf._hit(box, k) for k in known):
            out.append(c)
    return out


WEAK_SCORE = 0.8      # a reading below this is doubtful ...
STEADY_SCORE = 0.9    # ... and does not replace a card that was read at least this well in the same place


def box_overlap(a, b):
    """Shared area of two boxes (x1,y1,x2,y2) as a share of the smaller one."""
    w, h = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    return w * h / max(1.0, min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])))


def steady_card(cards, rect):
    """The old card that stood where rect is and was read with confidence, or None."""
    rb = [rect.x(), rect.y(), rect.right() + 1, rect.bottom() + 1]
    for o in cards:
        ob = [o["rect"].x(), o["rect"].y(), o["rect"].right() + 1, o["rect"].bottom() + 1]
        if o.get("score", 0.0) >= STEADY_SCORE and o.get("tr") and box_overlap(ob, rb) >= 0.5:
            return o
    return None


def active_window():
    """The focused window as a Target, or None."""
    if PORTAL:     # the shared window, taken to fill its monitor; a shared screen is not a window (cards are in it)
        if not Shared.is_window():
            return None
        try:
            return Target("portal", Shared.screen_rect(Shared.image()))
        except RuntimeError:
            return None
    if X11:
        wid = xb.active_window()
        return x_target(wid) if wid else None
    return _kdotool_geometry(["getactivewindow", "getwindowgeometry"])


def x_top_window(area):
    """X11: the window the player sees over the area - the topmost one under its centre - when it covers the area.
    The focused window is not always it: a game started from Steam's launcher came up fullscreen over Steam while
    Steam kept the focus (Cinnamon, Hotline Miami, 2026-11-13), and lenslate read Steam's library through the game.
    None when a smaller window (a terminal, lenslate's settings) sits on top there: then the focused window counts."""
    for wid in reversed(xb.stacking()):
        t = x_target(wid)
        if t is None or not t.rect.contains(area.center()) or xb.hidden(wid):
            continue
        return t if covers(t.rect, area) else None
    return None


_GAME_OF = {}


def window_game(uuid):
    """Name-list id of a window: its class (Wine/Proton games: the exe name), cached per window."""
    if PORTAL:
        return nm.game_id("")
    if uuid not in _GAME_OF and X11:
        _GAME_OF[uuid] = nm.game_id(xb.window_class(int(uuid)))
    if uuid not in _GAME_OF:
        try:
            cls = subprocess.run(["kdotool", "getwindowclassname", uuid], capture_output=True, text=True,
                                 timeout=2).stdout.strip()
        except Exception:  # noqa: BLE001
            cls = ""
        _GAME_OF[uuid] = nm.game_id(cls)
    return _GAME_OF[uuid]


def window_target(uuid):
    """Current geometry of a known window, or None if it is gone."""
    if PORTAL:
        return active_window()
    if X11:
        return x_target(int(uuid))
    return _kdotool_geometry(["getwindowgeometry", uuid])


# Direct window capture through KWin's ScreenShot2 D-Bus interface. KWin only allows it for executables listed with
# X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2 in a desktop file; lenslate runs on a private copy of the
# Python interpreter (~/.local/libexec/lenslate/lenslate-python, net.local.lenslate-capture.desktop) that has it.
# It captures a window even when it is NOT focused, never includes the overlay, and takes ~25 ms instead of ~0.5 s.
KWIN_DIRECT = [True]   # set to False after the first "not authorized" answer (then Spectacle is used)


def kwin_capture_window(uuid):
    import dbus
    bus = dbus.SessionBus(private=True)
    r, w = os.pipe()
    chunks = []
    reader = threading.Thread(target=lambda: chunks.append(os.fdopen(r, "rb").read()), daemon=True)
    reader.start()
    try:
        iface = dbus.Interface(bus.get_object("org.kde.KWin", "/org/kde/KWin/ScreenShot2"), "org.kde.KWin.ScreenShot2")
        res = iface.CaptureWindow(uuid, {"include-decoration": True, "include-shadow": False, "native-resolution": True},
                                  dbus.types.UnixFd(w), timeout=5)
    finally:
        os.close(w)          # EOF for the reader even if KWin refused
        reader.join(5)
        bus.close()
    data = chunks[0] if chunks else b""
    W, H, stride = int(res["width"]), int(res["height"]), int(res["stride"])
    if len(data) < stride * H:
        raise RuntimeError("short KWin capture")
    return QImage(data, W, H, stride, QImage.Format(int(res["format"]))).convertToFormat(QImage.Format_RGB32)


def capture_window(target, global_region):
    """Capture just the target window (the overlay is a separate layer surface, so it is never in the picture) and
    crop the region from it. Uses KWin directly when authorised (works unfocused), else Spectacle's active-window
    mode (caller makes sure the target is the active window then). Returns None if it does not line up."""
    img = None
    if PORTAL:
        try:
            img = Shared.image()
        except RuntimeError as e:
            dbg("portal capture:", e)
            return None
        shape = img.width() / max(1, img.height())
        if abs(shape - target.rect.width() / max(1, target.rect.height())) > 0.03 and not Shared.told:
            Shared.told = True
            notify("The shared window does not fill the screen. Your desktop does not tell lenslate where a window "
                   "is, so make the game fullscreen or borderless - or run `lenslate share` and share the whole "
                   "screen (the cards then blink while lenslate reads).")
    elif X11:
        img = x_image(xb.grab_window(int(target.uuid)))     # the window's own picture (Composite): no cards in it
        if img.isNull():
            return None
    elif KWIN_DIRECT[0]:
        try:
            img = kwin_capture_window(target.uuid)
        except Exception as e:  # noqa: BLE001
            if "NoAuthorized" in str(e) or "not authorized" in str(e):
                KWIN_DIRECT[0] = False
                dbg("KWin direct capture not authorised (run lenslate with ~/.local/libexec/lenslate/lenslate-python); "
                    "using Spectacle")
            else:
                dbg("KWin capture failed:", str(e)[:120])
    if img is None:
        fd, path = tempfile.mkstemp(suffix=".png", prefix="lenslate-")
        os.close(fd)
        try:
            subprocess.run(["spectacle", "-a", "-b", "-n", "-o", path], check=True, timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            img = QImage(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    if img.isNull():
        return None
    win_rect = target.rect
    scale = img.width() / max(1, win_rect.width())
    if abs(img.height() - win_rect.height() * scale) > 2:  # decorations/shadow mismatch: don't guess
        dbg("window capture size mismatch", img.width(), img.height(), win_rect)
        return None
    r = global_region.translated(-win_rect.x(), -win_rect.y())
    return img.copy(int(r.x() * scale), int(r.y() * scale), int(r.width() * scale), int(r.height() * scale))


NOTIF_PAD = 8  # logical px around a notification window: its shadow is drawn outside the window's rectangle
_CLEAN = {}   # area -> its last whole-screen picture with the notifications covered (see cover_notifications)


def notification_rects():
    """Global logical rectangles of the desktop's notifications on screen now, where the desktop can say (KDE,
    X11 notification windows); [] elsewhere, and while the bus watcher saw no notification lately."""
    if not notif.enabled(cfgmod.get) or (notif.WATCH.running and not notif.WATCH.active()):
        return []
    if "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper() and os.environ.get("WAYLAND_DISPLAY"):
        return [QRect(*r) for r in notif.kde_rects()]
    if X11:
        out = []
        for x, y, w, h in notif.x11_rects():
            tl, k = x_to_logical(x, y), x_scale_at(x, y)
            out.append(QRect(tl.x(), tl.y(), round(w / k), round(h / k)))
        return out
    return []


def cover_notifications(crop, region):
    """Paint over the notifications inside a whole-screen crop of the global logical region, before anything reads
    or records it: with the same spot of the area's previous picture when there is one (nothing changes there while
    the notification is up, and the game's text under it is read again once it goes), else with a flat colour."""
    key = region.getRect()
    hit = [r.adjusted(-NOTIF_PAD, -NOTIF_PAD, NOTIF_PAD, NOTIF_PAD).intersected(region) for r in notification_rects()]
    hit = [r for r in hit if not r.isEmpty()]
    if not hit:
        _CLEAN[key] = crop
        return crop
    s = crop.width() / max(1, region.width())
    prev = _CLEAN.get(key)
    same = prev is not None and prev.size() == crop.size()
    out = crop.copy()
    p = QPainter(out)
    for r in hit:
        rr = QRect(int((r.x() - region.x()) * s), int((r.y() - region.y()) * s),
                   int(round(r.width() * s)) + 1, int(round(r.height() * s)) + 1).intersected(out.rect())
        if same:
            p.drawImage(rr.topLeft(), prev, rr)
        else:
            p.fillRect(rr, crop.pixelColor(max(0, rr.x() - 2), max(0, rr.y() - 2)))
    p.end()
    dbg("covered %d notification(s) in the picture: %s" % (len(hit), [r.getRect() for r in hit]))
    _CLEAN[key] = out
    return out


def blank_boxes(img, boxes):
    """A copy of the picture with the boxes painted black (lines of notifications, for debug recordings)."""
    out = img.copy()
    p = QPainter(out)
    for x1, y1, x2, y2 in boxes:
        p.fillRect(QRect(int(x1), int(y1), int(x2 - x1) + 1, int(y2 - y1) + 1), QColor(0, 0, 0))
    p.end()
    return out


def crop_screen_region(img, bounds, screen_geo, region):
    """region is in screen-local logical px. Returns the cropped QImage."""
    scale = img.width() / max(1, bounds.width())
    x = (screen_geo.x() - bounds.x() + region.x()) * scale
    y = (screen_geo.y() - bounds.y() + region.y()) * scale
    return img.copy(int(x), int(y), int(region.width() * scale), int(region.height() * scale))


def pixel_scale(crop, region):
    """Captured pixels per logical pixel. Captures are in physical pixels (KWin native resolution, Spectacle), the
    region and the overlay are in logical ones: at a 150 % display scale this is 1.5. OCR boxes and card rects stay in
    captured pixels (change detection compares them between frames); layout_cards() converts them for the overlay."""
    if region.width() <= 0:
        return 1.0
    s = crop.width() / region.width()
    return 1.0 if abs(s - 1.0) < 0.02 else s


def to_logical(c):
    """A card with its rect and line height converted from captured to logical (overlay) pixels."""
    s = c.get("px_scale") or 1.0
    r = c["rect"]
    if s == 1.0:
        return dict(c, rect=QRect(r))
    x1, y1 = int(round(r.x() / s)), int(round(r.y() / s))
    x2, y2 = int(round((r.right() + 1) / s)), int(round((r.bottom() + 1) / s))
    return dict(c, rect=QRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1)), lh=max(1, int(round(c["lh"] / s))), px_scale=1.0)


def image_to_b64(img):
    if img.width() > SEND_WIDTH:
        img = img.scaledToWidth(SEND_WIDTH, Qt.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return base64.b64encode(bytes(ba)).decode()


def signature(img):
    """Tiny grayscale fingerprint used to decide whether the picture changed."""
    small = img.scaled(64, 36, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_Grayscale8)
    return bytes(small.constBits())[: 64 * 36]


def sig_diff(a, b):
    if a is None or b is None or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def qimage_grid(img):
    """Grayscale change-detection grid of the crop: one SAMPLES x SAMPLES patch per CELL x CELL cell."""
    rows, cols = tf.grid_shape(img.width(), img.height())
    g = img.convertToFormat(QImage.Format_Grayscale8).scaled(
        cols * tf.SAMPLES, rows * tf.SAMPLES, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    arr = np.frombuffer(g.constBits(), np.uint8, count=g.bytesPerLine() * g.height())
    return arr.reshape(g.height(), g.bytesPerLine())[:, :g.width()].astype(np.int16)


# --------------------------------------------------------------------------- translate
def _norm(t):
    return re.sub(r"[\W_]+", "", t).casefold()


def parse_line(line):
    m = LINE_RE.match(line.strip())
    if not m:
        return None
    x1, y1, x2, y2 = [min(1000.0, float(v)) for v in m.groups()[:4]]
    orig, tr = m.group(5).strip(), m.group(6).strip().strip("|").strip()
    if not tr or x2 <= x1 or y2 <= y1 or _norm(tr) == _norm(orig) or not _norm(tr):
        return None
    return (x1 / 1000, y1 / 1000, x2 / 1000, y2 / 1000, tr)


def ask_model(b64, on_item=None, stop=lambda: False):
    """Streams the answer; calls on_item(item) as soon as each line is complete. Returns all items."""
    body = json.dumps({
        "model": MODEL, "stream": True, "keep_alive": "30m",
        "options": {"temperature": 0, "num_predict": 900, "repeat_penalty": 1.05, "num_ctx": tf.NUM_CTX},
        "messages": [{"role": "user", "content": PROMPT, "images": [b64]}],
    }).encode()
    req = urllib.request.Request(OLLAMA, body, {"Content-Type": "application/json"})
    out, seen, buf, raw = [], set(), "", []

    def take(line):
        it = parse_line(line)
        if it is None:
            return
        key = (_norm(it[4]), round(it[0], 2), round(it[1], 2))
        if key in seen:  # the model looping on the same block
            return
        seen.add(key)
        out.append(it)
        if on_item:
            on_item(it)

    with urllib.request.urlopen(req, timeout=120) as r:
        for chunk in r:
            if stop():  # closing the connection makes Ollama stop generating
                break
            msg = json.loads(chunk)
            piece = msg.get("message", {}).get("content", "")
            raw.append(piece)
            buf += piece
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                take(line)
            if len(out) >= MAX_BLOCKS or len(seen) > MAX_BLOCKS * 2:
                break
            if msg.get("done"):
                break
    take(buf)
    dbg("model said:", "".join(raw)[:600].replace("\n", " / "))
    return out


class Pipeline(QThread):
    """capture -> (change check) -> model. Runs off the UI thread."""
    captured = Signal()          # frame grabbed: UI may show the cards again
    hide_cards = Signal()        # window capture failed: hide the cards before a full-screen capture
    partial = Signal(list)       # cards found so far (streamed)
    done = Signal(object, object)  # cards (None = picture unchanged), signature
    failed = Signal(str)

    def __init__(self, screen_geo, region, last_sig, force, win_rect):
        super().__init__()
        self.screen_geo, self.region, self.last_sig, self.force = screen_geo, region, last_sig, force
        self.win_rect = win_rect
        self.cancelled = False
        self.screen_shot = False     # the last picture was a whole-screen one (desktop notifications can be in it)
        self.notif_boxes = []        # lines dropped as part of a notification (blacked out in debug recordings)

    def grab(self):
        """The area's picture. A whole-screen picture (no window, or a screen shared through the portal) can hold
        the desktop's notifications: self.screen_shot says so, and those the desktop can locate are covered."""
        area = self.region.translated(self.screen_geo.topLeft())
        if self.win_rect is not None:
            crop = capture_window(self.win_rect, area)
            if crop is not None:
                self.screen_shot = PORTAL and not Shared.is_window()
                return cover_notifications(crop, area) if self.screen_shot else crop
            # the cards are on screen: a full capture now would read our own overlay
            self.hide_cards.emit()
            QThread.msleep(250)
        img, bounds = capture_all()
        self.screen_shot = True
        return cover_notifications(crop_screen_region(img, bounds, self.screen_geo, self.region), area)

    def run(self):
        try:
            crop = self.grab()
            self.captured.emit()
            sig = signature(crop)
            dbg("crop %dx%d window=%s" % (crop.width(), crop.height(), self.win_rect))
            if DEBUG:
                crop.save(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "lenslate-last-crop.png"))
            diff = sig_diff(sig, self.last_sig)
            dbg("picture change %.2f" % diff)
            if not self.force and diff < 2.0:
                self.done.emit(None, sig)  # unchanged picture: keep current cards
                return
            cards = []

            def on_item(it):
                x1, y1, x2, y2, tr = it
                rect = QRect(int(x1 * crop.width()), int(y1 * crop.height()),
                             max(1, int((x2 - x1) * crop.width())), max(1, int((y2 - y1) * crop.height())))
                bg, fg = sample_colors(crop, rect)
                cards.append({"rect": rect, "orig": "", "tr": tr, "bg": bg, "fg": fg,
                              "lh": int(rect.height() * 0.83), "px_scale": pixel_scale(crop, self.region)})
                self.partial.emit(list(cards))

            ask_model(image_to_b64(crop), on_item, lambda: self.cancelled)
            self.done.emit(cards, sig)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e)[:120])


class OcrPipeline(QThread):
    """capture -> compare with recent frames -> OCR only the changed areas -> text cache -> translate misses."""
    captured = Signal()
    hide_cards = Signal()
    partial = Signal(list)
    done = Signal(object, object)  # cards (None = unchanged), {"grid", "replace"}
    failed = Signal(str)

    def __init__(self, screen_geo, region, history, force, win_rect, ocr, cache, scale, junk=None, mem=None,
                 ocr_ultra=None):
        super().__init__()
        self.ocr_ultra = ocr_ultra   # Ultrafast (meikiocr) as a second reader for sparse Japanese areas, or None
        # [(rect, until)]: areas whose re-read found nothing to translate (pixel-art signs next to an animated
        # sprite were re-read every second); shared with the daemon so it survives between refreshes
        self.junk = junk if junk is not None else []
        self.mem = mem if mem is not None else {}   # small per-area memory shared across refreshes (see read_rects)
        self.screen_geo, self.region, self.history, self.force = screen_geo, region, history, force
        self.win_rect, self.ocr, self.cache = win_rect, ocr, cache
        self.scale = scale   # None = not known yet for this region; 1.0 or 2.0 once measured
        self.cancelled = False
        self.screen_shot = False
        self.notif_boxes = []

    grab = Pipeline.grab

    def run(self):
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            if LOG is not None:   # a debug recording shows the refreshes that failed too, with the reason
                LOG.record({"kind": "failed", "forced": self.force, "error": "%s: %s" % (type(e).__name__, str(e)[:300])})
            self.failed.emit(str(e)[:120])

    def _run(self):
        t0 = time.time()
        crop = self.grab()
        t_cap = time.time() - t0
        self.captured.emit()
        W, H = crop.width(), crop.height()
        ps = pixel_scale(crop, self.region)   # captured pixels per logical pixel (display scale), for the cards
        g = qimage_grid(crop)
        if DEBUG:
            crop.save(os.path.join(RUNTIME, "lenslate-last-crop.png"))

        # closest of the remembered frames
        base_i, mask = None, None
        if not self.force:
            best = None
            for i, (hg, _cards) in enumerate(self.history):
                m = tf.changed_cells(g, hg)
                if m is not None and (best is None or m.sum() < best):
                    best, base_i, mask = int(m.sum()), i, m
        if base_i is not None and not mask.any():
            dbg("unchanged vs frame %d" % base_i)
            if LOG is not None:
                LOG.record({"kind": "unchanged" if base_i == 0 else "history", "base": base_i,
                            "capture_s": round(t_cap, 3), "total_s": round(time.time() - t0, 3)})
            self.done.emit(None if base_i == 0 else [dict(c) for c in self.history[base_i][1]],
                           {"grid": g, "replace": base_i, "scale": self.scale})
            return

        base_cards = self.history[base_i][1] if base_i is not None else []
        gate_s, dropped = 0.0, 0
        if base_i is None and W * H > FAST_FULL_READ_PX and (fast_reading() or cfgmod.get("ocr.gpu") == "all"):
            # Whole-screen read: the detector finds the lines once (~0.3-0.8 s at 1080p) and only those spots go to
            # the reader, instead of a full OCR pass over the whole frame (measured 2-4x slower).
            boxes, gate_s = self.detect_rect(crop, [0, 0, W, H], side=min(1920, max(W, H)))
            if boxes is None:
                return
            known = list(boxes)
            pads = [tf.pad_box(t, W, H, (t[3] - t[1]) * 1.0, (t[3] - t[1]) * 0.5) for t in boxes]
            rects, kept = tf.merge_boxes(pads), []
        elif base_i is None:
            rects, kept, known = [[0, 0, W, H]], [], None
            if cfgmod.get("ocr.big_text") == "half" and W * H > FAST_FULL_READ_PX:
                # [ocr] big_text = half (4K screens): the quick finder measures the lines first (~1 s), so a whole
                # screen of big text can be read at half size (rect_scale); its boxes are used for nothing else
                boxes, gate_s = self.detect_rect(crop, [0, 0, W, H], side=min(1920, max(W, H)))
                if boxes is None:
                    return
                known = boxes
        else:
            # Pre-OCR gate: a fast text detector looks at the changed areas. Only text whose own pixels changed
            # (or that sits on a card whose pixels changed) goes to the expensive OCR. Animated backgrounds and
            # moving sprites next to unchanged text cost ~0.1 s instead of a 5 s re-read.
            boxes = [[c["rect"].x(), c["rect"].y(), c["rect"].right() + 1, c["rect"].bottom() + 1] for c in base_cards]
            lh = sorted(c["lh"] for c in base_cards)[len(base_cards) // 2] if base_cards else 2 * tf.CELL
            bands = [[0, 0, W, H]] if mask.mean() > 0.3 else tf.to_bands(tf.mask_rects(mask, W, H), W, H, lh)
            text_boxes, gate_s = [], 0.0
            known = text_boxes
            for band in bands:
                got, s = self.detect_rect(crop, band)
                if got is None:
                    return
                text_boxes += got
                gate_s += s
            # Old cards whose own pixels changed are always re-read by the real OCR (the fast detector misses small
            # text, so "no text detected" is not proof the text is gone). New text = detected boxes that changed.
            touched = [b for b in boxes if tf.cells_hit(mask, b, W, H)]
            now = time.time()
            self.junk[:] = [j for j in self.junk if j[1] > now]

            def in_junk(t):
                cx, cy = (t[0] + t[2]) / 2, (t[1] + t[3]) / 2
                return any(j[0][0] <= cx <= j[0][2] and j[0][1] <= cy <= j[0][3] for j in self.junk)
            want = [t for t in text_boxes if tf.cells_hit(mask, t, W, H) and not in_junk(t)] + touched
            rects = tf.merge_boxes([tf.pad_box(t, W, H, (t[3] - t[1]) * 1.0, (t[3] - t[1]) * 0.5) for t in want])
            rects = tf.merge_boxes(tf.grow_rects(rects, boxes, W, H))
            if sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects) > 0.6 * W * H:
                rects = [[0, 0, W, H]]
            kept = [dict(c) for c, b in zip(base_cards, boxes) if not any(tf._hit(b, r) for r in rects)]
            dropped = len(base_cards) - len(kept)
        # Any big read (most of the screen changed: a fade, a new picture, a menu): the detector at full resolution
        # finds the text in ~0.3-0.8 s and only those spots go to the reader (same as the first read).
        if base_i is not None and sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects) > FAST_FULL_READ_PX:
            big, small = [], []
            for r in rects:
                (big if (r[2] - r[0]) * (r[3] - r[1]) > FAST_FULL_READ_PX // 4 else small).append(r)
            found = []
            for r in big:
                got, s = self.detect_rect(crop, r, side=min(1920, max(r[2] - r[0], r[3] - r[1])))
                if got is None:
                    return
                gate_s += s
                found += [tf.pad_box(t, W, H, (t[3] - t[1]) * 1.0, (t[3] - t[1]) * 0.5) for t in got]
                known = list(known) + got
            rects = tf.merge_boxes(found + small)
            # old cards inside the big area are read again (or dropped if their text is gone) - and so are the ones
            # in the small areas, as before this step (they used to be put back among the kept cards here: read
            # again, nothing found, and the card stayed for good; a button got one more card on every refresh)
            kept = [dict(c) for c, b in zip(base_cards, boxes) if not any(tf._hit(b, r) for r in big + small)]
            dropped = len(base_cards) - len(kept)
        dbg("base=%s changed=%s gate=%.2fs rects=%s kept=%d dropped=%d" % (
            base_i, None if mask is None else int(mask.sum()), gate_s, rects, len(kept), dropped))
        if not rects:
            # nothing worth reading: keep the cards (minus text that disappeared)
            if LOG is not None:
                LOG.record({"kind": "gated", "base": base_i, "changed_cells": int(mask.sum()), "gate_s": round(gate_s, 3),
                            "dropped": dropped, "capture_s": round(t_cap, 3), "total_s": round(time.time() - t0, 3)})
            self.done.emit(kept, {"grid": g, "replace": None, "scale": self.scale})
            return

        # Typewriter / word-by-word text: wait until the text being drawn stops growing, so a half-shown line is
        # never read, translated or cached. Only with direct window capture (a Spectacle capture flashes the cards).
        settle_s = 0.0
        if base_i is not None and self.win_rect is not None and settle_step() > 0 and rects \
                and sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects) <= FAST_FULL_READ_PX:
            t_set = time.time()
            got = self.settle(crop, g, rects, lh)
            if got is None:
                return
            crop, g, rects = got
            settle_s = time.time() - t_set

        # OCR the areas. Small text (lines under SMALL_TEXT px) is read at 2x: at 1x the detector skips whole
        # lines and the reader drops characters. The first read of a region finds out which one is needed.
        scale = self.scale or 1.0
        # an old card the fast detector found no line in (small text): its area is read the full way, so a card
        # is never dropped on the fast detector's word
        if base_i is not None and known:
            for c in base_cards:
                cb = [c["rect"].x(), c["rect"].y(), c["rect"].right() + 1, c["rect"].bottom() + 1]
                if not any(tf._hit(cb, k) for k in known):
                    for r in rects:
                        if tf._hit(cb, r):
                            known = [k for k in known if not tf._hit(k, r)]
        # Area by area: each area's cards appear as soon as it is read (a few menu buttons show after ~1 s while a
        # big settings panel is still being read), and its new lines go to the translator on a second thread at
        # once, so translating overlaps with reading the next area. Small areas first: they are quick.
        rects = sorted(rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
        cards = list(kept)
        # cards of the areas being read again: a line typed out further (typewriter text) keeps its old card,
        # marked "…", until the longer line's translation arrives - no blank gap, and the reader keeps reading
        kept_keys = {(c["orig"], c["rect"].getRect()) for c in kept}
        gone = [c for c in base_cards if c.get("tr") and (c["orig"], c["rect"].getRect()) not in kept_keys]
        stale = vanished_cards(gone, mask, known, W, H) if (mask is not None and known is not None) else []
        if stale:
            dbg("text gone under %d old cards: taken down before the read" % len(stale))
            gone = [c for c in gone if not any(c is o for o in stale)]
        misses, pending, tr_times = [], {}, {}
        lock = threading.Lock()
        work = queue.Queue()
        stream = cfgmod.get("translator.stream")
        placeholder = cfgmod.get("overlay.placeholder")
        # until its own area has been read, an old card stays up (areas are read one by one, smallest first: the
        # others' cards used to vanish at the start of the refresh and come back a moment later)
        for o in gone:
            pending[("old", id(o))] = o

        first = []

        def show():
            with lock:
                now = list(cards) + list(pending.values())
                fresh = list(cards) + [v for k, v in pending.items() if not isinstance(k, tuple)]
                if fresh and not first:   # ("first cards" timing: old cards still up do not count)
                    first.append(time.time() - t0)
            self.partial.emit(now)

        def translator():
            while True:
                batch = work.get()
                if batch is None:
                    return
                if self.cancelled:
                    continue
                last = [0.0]

                def on_item(i, tr, batch=batch):
                    c = batch[i]
                    tr_times[id(c)] = round(time.time() - t0, 2)
                    c["tr"] = tr
                    with lock:
                        cards.append(c)
                        pending.pop(id(c), None)
                    self.cache.put(c["orig"], tr)
                    show()

                def on_partial(i, so_far, batch=batch):   # streaming: the card fills in as the model writes
                    now = time.time()
                    if now - last[0] < 0.1 or not so_far.strip():
                        return
                    last[0] = now
                    with lock:
                        pending[id(batch[i])] = dict(batch[i], tr=so_far.strip() + " …")
                    show()
                try:
                    self.cache.translate_batch([c["orig"] for c in batch], on_item, lambda: self.cancelled,
                                               on_partial if stream else None)
                except Exception as e:  # noqa: BLE001 - shown like before: the failure ends this refresh
                    dbg("translation failed: %s" % e)
                    tr_errors.append(str(e))
                finally:
                    work.task_done()
        if stale:   # the cards without the vanished ones, now (the rest follows area by area)
            show()
        tr_errors = []
        worker = threading.Thread(target=translator, daemon=True)
        worker.start()
        lines, blocks, secs = [], [], 0.0
        try:
            for rect in rects:
                got, s = self.read_rects(crop, [rect], scale, known)
                if got is None:
                    return
                secs += s
                with lock:   # this area is read: its old cards make way for what was found there
                    for o in gone:
                        ob = [o["rect"].x(), o["rect"].y(), o["rect"].right() + 1, o["rect"].bottom() + 1]
                        if tf._hit(ob, rect):
                            pending.pop(("old", id(o)), None)
                if self.scale is None and cfgmod.get("ocr.reading") != "ultrafast":
                    # first read of this region: small text (under SMALL_TEXT px) is read again at 2x, area by area
                    # (not in Ultrafast: meikiocr scales every line to 32 px itself, a 2x read only repeats the work)
                    hs = sorted(r["box"][3] - r["box"][1] for r in tf.merge_rows(got) if tf.LETTER.search(r["text"]))
                    if hs and hs[len(hs) // 2] < tf.SMALL_TEXT:
                        dbg("small text (median %dpx) in %s: reading again at 2x" % (hs[len(hs) // 2], rect))
                        got, s2 = self.read_rects(crop, [rect], 2.0)
                        secs += s2
                        if got is None:
                            return
                # sparse Japanese (small pixel fonts): a second reading with Ultrafast, the fuller one is kept
                if self.ocr_ultra is not None and cfgmod.get("ocr.ultrafast_fallback") and tf.ultrafast_wanted(
                        got, tf.langs.sources(cfgmod.get("translator.sources")), cfgmod.get("ocr.reading"),
                        tf.langs.reader_script(cfgmod.get("translator.sources")), self.mem, rect[3] - rect[1]):
                    try:
                        alt, s3 = self.read_rect(crop, rect, 1.0, self.ocr_ultra)
                    except RuntimeError as e:     # no meikiocr model, or its helper failed: the first reading stays
                        dbg("ultrafast fallback failed: %s" % e)
                        alt, s3 = [], 0.0
                    if alt is None:
                        return
                    secs += s3
                    won = tf.reads_more(alt, got)
                    tf.note_ultrafast(self.mem, won)
                    dbg("ultrafast fallback in %s: %d -> %d lines (%s)" % (rect, len(got), len(alt), "kept" if won else "not better"))
                    if won:
                        got = alt
                # readings the reader itself doubts (before the junk filter takes the worst of them away)
                weak = [ln["box"] for ln in got if ln.get("score", 1.0) < WEAK_SCORE]
                got = tf.split_touching(tf.plausible(got, H))
                for ln in got:   # kana anywhere on this screen: its kanji-only words are Japanese too (langs.source_of)
                    ln["text"] = tf.strip_stray_brackets(tf.langs.fix_lookalikes(ln["text"]))   # ЖypHал -> Журнал, モ力 -> モカ, "НОВИНКА]"
                    tf.langs.note(ln["text"])
                if self.screen_shot and notif.enabled(cfgmod.get) and notif.WATCH.active():
                    # a notification the desktop gave no position for (Cinnamon, GNOME, the portal): its lines
                    drop = [ln for ln in got if notif.WATCH.matches(ln["text"])]
                    if drop:
                        dbg("notification text left out: %s" % " | ".join(ln["text"] for ln in drop)[:200])
                        self.notif_boxes += [ln["box"] for ln in drop]
                        got = [ln for ln in got if not any(ln is d for d in drop)]
                lines += got
                new = []
                here = []      # card rects made from this area
                for b in [b for b in tf.group_blocks(tf.merge_rows(got)) if tf.wants_translation(b["text"])]:
                    blocks.append(b)
                    x1, y1, x2, y2 = [int(round(v)) for v in b["box"]]
                    rect_q = QRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1)).intersected(crop.rect())
                    here.append(rect_q)
                    if b["score"] < WEAK_SCORE:
                        # A doubtful reading where a confident card stood: the text did not change, its look did
                        # (a button under the mouse lights up and glows - "Back" came back as "Lu San"). The card
                        # that was read well stays.
                        steady = steady_card(gone, rect_q)
                        if steady is not None:
                            with lock:
                                cards.append(dict(steady))
                            continue
                    bg, fg = sample_colors(crop, rect_q)
                    card = {"rect": rect_q, "orig": b["text"], "tr": self.cache.get(b["text"]), "bg": bg, "fg": fg,
                            "lh": int(b["line_h"]), "px_scale": ps, "score": b["score"]}
                    if card["tr"] is None:
                        new.append(card)
                        old = next((o for o in gone if o["rect"].intersects(rect_q) and tf.grows(o["orig"], card["orig"])),
                                   None)
                        if old is not None:
                            card["grew_from"] = old["tr"]
                    else:
                        with lock:
                            cards.append(card)
                # ... and the same when the doubtful reading was thrown away altogether (nothing left to replace it)
                for o in gone:
                    ob = [o["rect"].x(), o["rect"].y(), o["rect"].right() + 1, o["rect"].bottom() + 1]
                    if o.get("score", 0.0) >= STEADY_SCORE and tf._hit(ob, rect) \
                            and not any(o["rect"].intersects(r) for r in here) \
                            and any(box_overlap(ob, w) >= 0.3 for w in weak):
                        with lock:
                            cards.append(dict(o))
                misses += new
                with lock:
                    for c in new:
                        if c.get("grew_from"):   # typed out further: the old translation stays up until the new one
                            pending[id(c)] = dict(c, tr=c["grew_from"].rstrip(" …") + " …")
                        elif placeholder:        # optional "…" cards on new text while it is being translated
                            pending[id(c)] = dict(c, tr="…")
                if cards or pending:
                    show()
                if new and not self.cancelled:
                    work.put(new)
                    if SERIAL_TRANSLATE:   # (testing) translate this area before reading the next one
                        work.join()
        finally:
            t_read_end = time.time()
            work.put(None)
            worker.join()   # the lines still being translated
            with lock:
                for o in gone:
                    pending.pop(("old", id(o)), None)
        if self.scale is None:   # the region's scale from now on: 2x if most of its text is small
            hs = sorted(r["box"][3] - r["box"][1] for r in tf.merge_rows(lines) if tf.LETTER.search(r["text"]))
            self.scale = 2.0 if hs and hs[len(hs) // 2] < tf.SMALL_TEXT else 1.0
        if blocks:
            en = sum(1 for b in blocks if tf.langs.detect(b["text"]) == "en")
            self.mem["latin_streak"] = self.mem.get("latin_streak", 0) + 1 if en * 2 > len(blocks) else 0
        if base_i is not None:
            # areas re-read because something moved there, holding nothing to translate and no card: ignore them
            # for a while (an animated sprite next to pixel-art signs cost a ~1.5 s read every second)
            card_boxes = [[c["rect"].x(), c["rect"].y(), c["rect"].right(), c["rect"].bottom()] for c in base_cards]
            for r in rects:
                if not any(tf._hit(b["box"], r) for b in blocks) and not any(tf._hit(cb, r) for cb in card_boxes):
                    self.junk.append((r, time.time() + JUNK_SECONDS))
        t_first = first[0] if first else None
        dbg("ocr %.2fs blocks=%d new=%d first cards after %s s: %s" % (
            secs, len(blocks), len(misses), None if t_first is None else round(t_first, 2),
            " | ".join(c["orig"] for c in misses)[:300]))
        if tr_errors and not any(c.get("tr") for c in misses):
            raise RuntimeError(tr_errors[0])
        t_ocr_done = t_read_end   # "translate_s" in the debug record = waiting for translations after the reading
        if misses:
            self.cache.save()
        if LOG is not None:
            kept_ids = {id(c) for c in kept}
            LOG.record({
                "kind": "read", "forced": self.force, "base": base_i, "region": self.region.getRect(),
                "window_capture": self.win_rect is not None,
                "changed_cells": None if mask is None else int(mask.sum()),
                "total_cells": int(g.size // (tf.SAMPLES * tf.SAMPLES)), "rects": rects, "scale": self.scale,
                "capture_s": round(t_cap, 3), "gate_s": round(gate_s, 3), "settle_s": round(settle_s, 2), "dropped": dropped, "ocr_s": round(secs, 2), "translate_s": round(time.time() - t_ocr_done, 2),
                "total_s": round(time.time() - t0, 2), "cancelled": self.cancelled,
                "ocr_lines": [{"box": [round(v) for v in ln["box"]], "text": ln["text"], "score": round(ln["score"], 3)}
                              for ln in lines],
                "new": [{"orig": c["orig"], "tr": c["tr"], "after_s": tr_times.get(id(c))} for c in misses],
                "first_card_s": None if t_first is None else round(t_first, 3),
                "cards": [card_json(c, id(c) in kept_ids) for c in cards],
                "notification_lines": len(self.notif_boxes),
            }, blank_boxes(crop, self.notif_boxes) if self.notif_boxes else crop)
        if self.cancelled:
            return
        self.done.emit(cards, {"grid": g, "replace": None, "scale": self.scale})

    def settle(self, crop, g, rects, lh):
        """Re-capture every settle_step() s until nothing NEW is drawn in the text areas (or settle_max() passes).
        "New" = cells that had not changed yet during this wait: a typewriter keeps writing into fresh cells, while
        a blinking "next" arrow or a sparkle changes the same cells again and does not hold the read up.
        The zone is the full-width rows of the areas to read plus two lines below (text wrapping onto the next line).
        Returns (crop, grid, rects) or None if cancelled. The returned grid takes the new picture only where it will
        be read, so anything that appeared elsewhere during the wait is still seen as a change on the next tick."""
        W, H = crop.width(), crop.height()
        rows, cols = tf.grid_shape(W, H)
        zone = np.zeros((rows, cols), bool)
        for x1, y1, x2, y2 in rects:
            # full width: a typed line grows sideways out of the box where its first characters appeared
            zone[int(y1) // tf.CELL:int(min(H, y2 + 2 * lh)) // tf.CELL + 1, :] = True
        seen = np.zeros_like(zone)
        g0, prev, last = g, g, crop
        deadline = time.time() + settle_max()
        steps = 0
        while True:
            time.sleep(settle_step())
            if self.cancelled:
                return None
            c2 = self.grab()
            g2 = qimage_grid(c2)
            m = tf.changed_cells(g2, prev)
            if m is None:            # window resized: read what we have
                return last, g, rects
            new = m & zone & ~seen
            seen |= m
            prev, last = g2, c2
            steps += 1
            if not new.any() or time.time() > deadline:
                break
        grown = tf.changed_cells(prev, g0)
        grown = grown & zone if grown is not None else None
        if grown is not None and grown.any():
            rects = tf.merge_boxes(rects + tf.mask_rects(grown, W, H))
        read = np.zeros((rows, cols), bool)
        for x1, y1, x2, y2 in rects:
            read[int(y1) // tf.CELL:(int(y2) + tf.CELL - 1) // tf.CELL, int(x1) // tf.CELL:(int(x2) + tf.CELL - 1) // tf.CELL] = True
        sel = np.repeat(np.repeat(read, tf.SAMPLES, 0), tf.SAMPLES, 1)[:g0.shape[0], :g0.shape[1]]
        hybrid = g0.copy()
        hybrid[sel] = prev[sel]
        dbg("settle: %d steps, %s" % (steps, "stable" if time.time() <= deadline else "gave up (still changing)"))
        return last, hybrid, rects

    def read_rects(self, crop, rects, scale, known=None):
        """OCR the areas. known: the fast detector's line boxes (crop coordinates) - with fast reading, areas that
        contain some are read with the recogniser only (no second, slower detection, no re-checks)."""
        lines, secs = [], 0.0
        H = crop.height()
        fast_rects = []
        # English text: the recogniser alone is unreliable there, so every line would be read twice; after two
        # mostly-English reads in a row this area skips the fast route until other text shows up
        if known and scale == 1.0 and fast_reading() and self.mem.get("latin_streak", 0) < 2:
            rest = []
            for rect in rects:
                inside = [b for b in known if rect[0] <= (b[0] + b[2]) / 2 <= rect[2] and rect[1] <= (b[1] + b[3]) / 2 <= rect[3]]
                # the found lines are read directly (no second, slower finding pass); only areas with no found
                # line, or an extreme number of fragments, are read the full way
                (fast_rects if 0 < len(inside) <= FAST_LINES_MAX else rest).append((rect, inside))
            rects = [r for r, _ in rest]
            if rects:
                dbg("fast lines: no known lines in %s (read the full way)" % rects)
            for rect, inside in fast_rects:
                got, s = self.read_known(crop, rect, inside)
                if got is None:
                    return None, secs
                secs += s
                # fast reading = quickest: a line the reader is unsure about keeps its best guess and is translated
                # anyway (re-checking one line cost 0.3 s at 1080p, 2 s at 4K - testbench 2026-11-10)
                lines.extend(g for g in got if g["text"])
        for rect in rects:
            got, s = self.read_rect(crop, rect, self.rect_scale(rect, scale, known))
            if got is None:
                return None, secs
            secs += s
            ext = tf.cut_edges(rect, [g["box"] for g in got], H)
            if ext is not None and rect != [0, 0, crop.width(), H]:
                # a line was cut by the band edge: widen the band by a line and read it again
                rect = [rect[0], max(0, rect[1] - ext[0]), rect[2], min(H, rect[3] + ext[1])]
                dbg("band cut a line; re-reading %s" % rect)
                got, s = self.read_rect(crop, rect, scale)
                if got is None:
                    return None, secs
                secs += s
            lines.extend(got)
        return lines, secs

    @staticmethod
    def rect_scale(rect, scale, known):
        """[ocr] big_text = half: an area whose found lines are big (4K screens) is read at half size."""
        if scale != 1.0 or not known or cfgmod.get("ocr.big_text") != "half":
            return scale
        hs = sorted(b[3] - b[1] for b in known
                    if rect[0] <= (b[0] + b[2]) / 2 <= rect[2] and rect[1] <= (b[1] + b[3]) / 2 <= rect[3])
        if hs and hs[len(hs) // 2] >= BIG_TEXT:
            dbg("big text (median %dpx) in %s: reading at half size" % (hs[len(hs) // 2], rect))
            return 0.5
        return scale

    def read_known(self, crop, rect, boxes):
        """Recogniser-only read of known line boxes inside one area; boxes come back in crop coordinates."""
        x1, y1, x2, y2 = rect
        if self.cancelled:
            return None, 0.0
        path = os.path.join(RUNTIME, "lenslate-ocr-%d.bmp" % os.getpid())   # BMP: 0.01 s vs 0.3 s PNG on 4K areas (RAM dir)
        crop.copy(x1, y1, x2 - x1, y2 - y1).save(path, "BMP")
        try:
            got, s = self.ocr.read_lines(path, [[b[0] - x1, b[1] - y1, b[2] - x1, b[3] - y1] for b in boxes])
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        for ln in got:
            b = ln["box"]
            ln["box"] = [b[0] + x1, b[1] + y1, b[2] + x1, b[3] + y1]
        return got, s

    def detect_rect(self, crop, rect, side=1280):
        """Fast text detection on one area; boxes in crop coordinates."""
        x1, y1, x2, y2 = rect
        if self.cancelled:
            return None, 0.0
        path = os.path.join(RUNTIME, "lenslate-gate-%d.bmp" % os.getpid())
        crop.copy(x1, y1, x2 - x1, y2 - y1).save(path, "BMP")
        try:
            got, s = self.ocr.detect(path, side)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        return [[b[0] + x1, b[1] + y1, b[2] + x1, b[3] + y1] for b in got], s

    def read_rect(self, crop, rect, scale, ocr=None):
        """OCR one area (with ocr, or the region's own reader); boxes come back in crop coordinates."""
        x1, y1, x2, y2 = rect
        if self.cancelled:
            return None, 0.0
        path = os.path.join(RUNTIME, "lenslate-ocr-%d.bmp" % os.getpid())   # BMP: 0.01 s vs 0.3 s PNG on 4K areas (RAM dir)
        crop.copy(x1, y1, x2 - x1, y2 - y1).save(path, "BMP")
        try:
            got, s = (ocr or self.ocr).read(path, scale)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        for ln in got:
            b = ln["box"]
            ln["box"] = [b[0] + x1, b[1] + y1, b[2] + x1, b[3] + y1]
        return got, s


def sample_colors(crop, rect):
    """Background = average of a thin ring just outside the text box; text = contrasting."""
    pad = 4
    r = rect.adjusted(-pad, -pad, pad, pad).intersected(crop.rect())
    rs = gs = bs = n = 0
    step = max(1, min(r.width(), r.height()) // 24)
    for x in range(r.left(), r.right() + 1, step):
        for y in (r.top(), r.bottom()):
            c = QColor(crop.pixel(x, y)); rs += c.red(); gs += c.green(); bs += c.blue(); n += 1
    for y in range(r.top(), r.bottom() + 1, step):
        for x in (r.left(), r.right()):
            c = QColor(crop.pixel(x, y)); rs += c.red(); gs += c.green(); bs += c.blue(); n += 1
    n = max(n, 1)
    bg = QColor(rs // n, gs // n, bs // n)
    lum = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
    return bg, QColor(255, 255, 255) if lum < 140 else QColor(20, 20, 20)


# ------------------------------------------------------------------------------- layout
def layout_card(rect, text, region, line_h, widen=True, family=None):
    """Place a translation over its original text block. rect is region-local; the result is screen-local.
    - The card keeps the original block's height, so it never spills onto neighbouring lines.
    - Font starts at ~80% of the original line height (11-48 px); the card may grow to the right by up to
      ~30% + 2 line heights (English needs more room than Japanese), then the text wraps, then the font shrinks.
    - Only if even the smallest font does not fit does the card grow taller.
    - Short labels/buttons are centred on the original; longer lines and paragraphs are left-aligned."""
    mx, my = max(2, line_h // 6), 1
    box = rect.translated(region.x(), region.y()).adjusted(-mx, -my, mx, my)
    short = rect.width() < 8 * line_h
    max_w = max(box.width(), min(region.width() - 4, int(box.width() * 1.3 + 2 * line_h))) if widen else box.width()
    base = QGuiApplication.font()
    if family:   # measure with the font the overlay draws the card in (overlay.qml: win.family)
        base = QFont(base)
        base.setFamily(family)
    size = int(max(11, min(48, line_h * 0.8)))   # (was capped at 30 px: half-size text over big 4K lines)
    while True:
        f = QFont(base); f.setPixelSize(size)
        fm = QFontMetrics(f)
        width = min(max(box.width(), fm.horizontalAdvance(text) + 2 * mx + 2), max_w)
        br = fm.boundingRect(QRect(0, 0, width - 2 * mx, 4000), Qt.TextWordWrap, text)
        # a word longer than the card cannot wrap: Qt reports it at full width and the card would cut it off at
        # both sides ("Settings" over 設定 drawn as "etting", seen in Slay the Spire 2) - shrink instead
        too_wide = br.width() > width - 2 * mx
        if (br.height() + 2 * my <= box.height() and not too_wide) or size <= 10:
            break
        size -= 1
    card = QRect(0, 0, width, max(box.height(), br.height() + 2 * my))
    if short:
        card.moveCenter(box.center())
    else:
        card.moveTopLeft(box.topLeft())
        card.moveTop(box.top() + (box.height() - card.height()) // 2)
    if card.right() > region.right():
        card.moveRight(region.right())
    if card.bottom() > region.bottom():
        card.moveBottom(region.bottom())
    card.moveLeft(max(card.left(), region.left()))
    card.moveTop(max(card.top(), region.top()))
    return card, size, ("center" if short else "left"), mx, my


class SessionLog:
    """Debug recording for long test sessions. On when LENSLATE_DEBUG is set or ~/.cache/lenslate/debug-on exists
    (the hotkeys cannot pass environment variables). Writes to ~/.cache/lenslate/debug/<start time>/:
      session.log   every debug line, with time stamps
      runs.jsonl    one record per refresh (what was compared, read, translated, timings, final cards)
      NNNNN.jpg     the captured region, saved whenever OCR actually ran (not for unchanged frames)"""
    FLAG = os.path.join(os.path.dirname(CACHE_PATH), "debug-on")
    MAX_IMAGES = 3000
    # older sessions are deleted (oldest first) above this: 34 sessions took 186 MB. Generous, because recorded
    # sessions are also the benchmark material (replays through OcrPipeline)
    KEEP_BYTES = 2 * 1024 * 1024 * 1024

    def __init__(self):
        self.on = DEBUG or os.path.exists(self.FLAG)
        self.dir = os.path.join(os.path.dirname(CACHE_PATH), "debug", time.strftime("%Y%m%d-%H%M%S"))
        self.lock = threading.Lock()
        self.n = 0
        self.images = 0

    def _ready(self):
        if not os.path.isdir(self.dir):
            # the recordings hold screen text and screenshots: readable by this user only
            os.makedirs(os.path.dirname(self.dir), mode=0o700, exist_ok=True)
            os.makedirs(self.dir, mode=0o700, exist_ok=True)
            self._prune()

    def _prune(self):
        """Delete the oldest recorded sessions while all of them together are above KEEP_BYTES."""
        import shutil
        root = os.path.dirname(self.dir)
        try:
            sessions = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
        except OSError:
            return
        sizes = {}
        for d in sessions:
            total = 0
            for dirpath, _dirs, files in os.walk(os.path.join(root, d)):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(dirpath, f))
                    except OSError:
                        pass
            sizes[d] = total
        used = sum(sizes.values())
        for d in sessions:   # names are start times: oldest first
            if used <= self.KEEP_BYTES or os.path.join(root, d) == self.dir:
                break
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)
            used -= sizes[d]

    def text(self, line):
        if not self.on:
            return
        with self.lock:
            self._ready()
            with open(os.path.join(self.dir, "session.log"), "a", encoding="utf-8") as f:
                f.write("%s %s\n" % (time.strftime("%H:%M:%S"), line))

    def record(self, rec, image=None):
        if not self.on:
            return
        with self.lock:
            self._ready()
            self.n += 1
            rec = dict(rec, n=self.n, time=time.strftime("%H:%M:%S"))
            if image is not None and self.images < self.MAX_IMAGES:
                name = "%05d.jpg" % self.n
                image.save(os.path.join(self.dir, name), "JPG", 88)
                rec["image"] = name
                self.images += 1
            with open(os.path.join(self.dir, "runs.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


LOG = None   # created by the daemon only (the short-lived client never logs)


def layout_cards(cards, region):
    """Lay out all cards, then stop them from covering each other: a card that widened over another text's
    original box is laid out again at its own width (it wraps / shrinks instead). Cards whose original boxes
    overlap anyway are drawn smallest last, so the small one stays readable."""
    cards = [to_logical(c) for c in cards]   # captured pixels -> the overlay's logical pixels (display scale)
    # neighbouring blocks whose boxes overlap a little (the short last line of one sentence right above the next
    # one in a dialogue box): split the shared strip between them so neither card covers the other
    for a in cards:
        for b in cards:
            ra, rb = a["rect"], b["rect"]
            if a is b or ra.top() > rb.top():
                continue
            ov = ra.bottom() - rb.top() + 1
            if ov > 0 and ra.left() <= rb.right() and rb.left() <= ra.right() \
                    and ov < 0.5 * min(ra.height(), rb.height()):
                mid = rb.top() + ov // 2
                ra.setBottom(mid - 1)
                rb.setTop(mid)
    origs = [c["rect"].translated(region.x(), region.y()) for c in cards]
    fam = card_family() if cards else None
    out, placed = [], []

    def collides(i, r):
        """r covers another text's original box, or a card already placed (cards that grew taller, centred labels
        and cards pushed in by the region's edges are not where their original box is)."""
        return any(j != i and r.intersects(o) and not origs[i].intersects(o) for j, o in enumerate(origs)) or \
            any(r.intersects(p) and not origs[i].intersects(origs[j]) for j, p in placed)
    for i, c in enumerate(cards):
        lay = layout_card(c["rect"], c["tr"], region, max(8, c["lh"]), family=fam)
        if collides(i, lay[0]):
            lay = layout_card(c["rect"], c["tr"], region, max(8, c["lh"]), widen=False, family=fam)
        placed.append((i, lay[0]))
        out.append(dict(c, layout=lay))
    out.sort(key=lambda c: -(c["layout"][0].width() * c["layout"][0].height()))
    return out


def dbg(*a):
    if DEBUG:
        print("[lenslate]", *a, file=sys.stderr, flush=True)
    if LOG is not None:
        LOG.text(" ".join(str(x) for x in a))


def card_family(language=None):
    """Font of the translation cards. Chinese: a Simplified Chinese font, so shared characters are drawn the way
    Chinese readers expect (the default fallback can pick the Japanese forms of 直, 骨, 写 ...)."""
    if tf.langs.target_code(language or cfgmod.get("translator.language")) == "zh":
        from PySide6.QtGui import QFontDatabase
        fams = set(QFontDatabase.families())
        for f in ("Noto Sans CJK SC", "Source Han Sans SC", "Noto Sans SC", "WenQuanYi Micro Hei"):
            if f in fams:
                return f
    return QGuiApplication.font().family()


def card_json(c, kept=False):
    r = c["rect"]
    return {"rect": [r.x(), r.y(), r.width(), r.height()], "orig": c["orig"], "tr": c["tr"], "lh": c["lh"],
            "bg": c["bg"].name(), "fg": c["fg"].name(), "kept": kept}


_SEE = [0.0, True]


def see_through():
    """Cards can be see-through. Not on X11 without a compositing manager (asked every 5 s: it can be switched)."""
    if not X11:
        return True
    if time.time() - _SEE[0] > 5:
        _SEE[:] = [time.time(), xb.compositing()]
    return _SEE[1]


def notify(msg):
    subprocess.Popen(["notify-send", "-a", "lenslate", "-t", "4000", "lenslate", msg],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def mouse_screen():
    if X11:
        p = xb.pointer()
        if p is not None:
            q = x_to_logical(p[0], p[1])
            for s in QGuiApplication.screens():
                if s.geometry().contains(q):
                    return s
        return QGuiApplication.primaryScreen()
    try:
        out = subprocess.run(["kdotool", "getmouselocation"], capture_output=True, text=True, timeout=2).stdout
        x, y = [int(v) for v in re.findall(r"[xy]:(-?\d+)", out)[:2]]
        for s in QGuiApplication.screens():
            if s.geometry().contains(x, y):
                return s
    except Exception:  # noqa: BLE001
        pass
    return QGuiApplication.primaryScreen()




class QmlWindow:
    """A QML layer-shell window placed on a chosen monitor (ScreenFromQWindow). A layer surface is bound to its
    output when it is mapped, so moving it means hide -> setScreen -> show. KWin ignores the screen on the very
    first map, hence the one-time check-and-retry in place()."""

    def __init__(self, engine, name, cut=False, keys=False):
        """X11 only: cut = the window is cut down to its cards (a window mask: it shows without a compositing
        manager too, and never covers more of the game than the cards); keys = it takes the keyboard while shown."""
        if X11:
            name = name.replace(".qml", "-x11.qml")
        before = len(engine.rootObjects())
        engine.load(QUrl.fromLocalFile(os.path.join(HERE, name)))
        self.root = engine.rootObjects()[before]
        self.root.setProperty("family", card_family())
        self.want = None
        self.cut, self.keys = cut and X11, keys and X11
        self.vals = {}        # what was last set (a QML list comes back from property() as a script value)
        if self.cut:
            self.remask()
            self.raiser = QTimer()          # a raised game window covers an unmanaged overlay: put it back on top
            self.raiser.setInterval(1000)
            self.raiser.timeout.connect(self.raise_)
            self.raiser.start()

    def set(self, name, value):
        ok = self.root.setProperty(name, value)
        self.vals[name] = value
        dbg("set", name, "->", ok, (str(value)[:60]))
        if self.cut and name in ("cards", "badge", "showCards", "regionX", "regionY", "visible"):
            self.remask()
            self.raise_()
        if self.keys and name == "visible" and not value:
            self.root.setKeyboardGrabEnabled(False)

    def remask(self):
        from PySide6.QtGui import QRegion
        reg = QRegion()
        if self.vals.get("showCards", True):
            for c in self.vals.get("cards") or []:
                reg += QRect(int(c["x"]), int(c["y"]), int(c["w"]) + 1, int(c["h"]) + 1)
            b = self.root.property("badgeRect")
            if b is not None and b.width() > 0:
                reg += b.toAlignedRect()
        if reg.isEmpty():
            reg = QRegion(-4, -4, 1, 1)     # nothing to show (an empty mask would mean "the whole window")
        self.root.setMask(reg)

    def raise_(self):
        if self.root.property("visible"):
            xb.raise_window(int(self.root.winId()))

    def show(self):
        self.root.setProperty("visible", True)

    def place(self, screen, retry=True):
        if X11:        # an ordinary window: put it over the monitor
            if screen is not None:
                self.want = screen.name()
                self.root.setScreen(screen)
                self.root.setGeometry(screen.geometry())
            self.root.setProperty("visible", True)
            self.root.raise_()
            if self.cut:
                self.remask()
            if self.keys:
                self.root.requestActivate()
                self.root.setKeyboardGrabEnabled(True)
            return
        if screen is None:
            self.show(); return
        self.want = screen.name()
        if self.root.property("visible") and self.output() == screen.name():
            return
        self.root.setProperty("visible", False)
        self.root.setScreen(screen)
        self.root.setProperty("visible", True)
        if retry:
            QTimer.singleShot(250, lambda: self._check(screen))

    def _check(self, screen):
        # only the latest request counts, and only while the window is still shown
        if self.want != screen.name() or not self.root.property("visible") or self.output() == screen.name():
            return
        dbg("window landed on", self.output(), "instead of", screen.name(), "- re-mapping")
        self.root.setProperty("visible", False)
        self.place(screen, retry=False)

    def output(self):
        """Name of the monitor this window actually landed on (updated by the compositor after it is shown)."""
        if X11 and self.want:
            return self.want
        sc = self.root.screen()
        return sc.name() if sc is not None else None


class Daemon(QObject):
    def __init__(self):
        super().__init__()
        self.engine = QQmlApplicationEngine()
        self.overlay = QmlWindow(self.engine, "overlay.qml", cut=True)
        self.selwin = QmlWindow(self.engine, "selector.qml", keys=True)
        self.selwin.root.chosen.connect(self.on_chosen_xywh)
        self.selwin.root.cancelled.connect(self.on_cancel)
        self.screen = None
        self.region = QRect()
        self.worker = None
        self.selecting = False
        self.last_sig = None
        self.cards = []
        self.raw_cards = []
        # card background opacity: config.toml [overlay] opacity, or `lenslate opacity X`
        self.opacity = cfgmod.get("overlay.opacity")
        # pick up manual edits of the config file while running (checked every 2 s; a stat() call, no cost)
        self._cfg_mtime = self._config_mtime()
        self.cfg_timer = QTimer(self)
        self.cfg_timer.setInterval(2000)
        self.cfg_timer.timeout.connect(self.reload_config)
        self.cfg_timer.start()
        self.history = []          # OCR engine: [(grid, cards)] newest first, up to tf.HISTORY
        self.junk = []             # [(rect, until)] areas that only held untranslatable "text" (see OcrPipeline)
        self.mem = {}              # small memory of the chosen area (e.g. mostly English text: see read_rects)
        self.target = None         # Target window the region belongs to (captured directly, even unfocused)
        self.text_scale = None     # OCR read scale for this region (None = measure on the first read)
        self.hidden = False        # toggled off by the user
        self.auto_was = False      # auto-refresh state to restore when shown again
        self._fresh = True
        self.engine_name = ENGINE
        self.ocr = tf.OcrClient(HERE, DEBUG)
        self.ocr.on_notice = notify   # graphics-card reading fell back to the processor (not enough memory free)
        # the second reader for sparse Japanese areas (started only when first needed; see tf.ultrafast_wanted)
        self.ocr_ultra = tf.OcrClient(HERE, DEBUG, env={"LENSLATE_OCR_READER": "meiki"})
        # self.cache: translation cache + the model that fills it (llm or mt; `lenslate translator`)
        kind, llm = wanted_translator()
        self.cache = tf.Translator(HERE, CACHE_PATH, LANG, llm, OLLAMA, kind, DEBUG)
        if kind == "llm" and self.cache.kind != "llm":
            notify("The language model is not downloaded, so lenslate translates with the fast processor translator "
                   "(machine-like wording). Download it in lenslate's Models page for better translations.")
        elif self.cache.notice:   # e.g. a processor model of the chosen translator is missing (it is not replaced)
            notify(self.cache.notice)
        self.cache.on_names = lambda game, found: found and notify(
            "New names to check: %s\nlenslate names %s" % (", ".join("%s = %s" % p for p in found.items()), game))
        if self.engine_name == "ocr" and not self.ocr.available():
            notify("OCR helper not installed (ocr-venv); using the vision model")
            self.engine_name = "vlm"
        if self.engine_name == "ocr":
            threading.Thread(target=self._warm_ocr, daemon=True).start()
        self.gen = 0               # bumped by new region / clear: results of older runs are dropped
        if PORTAL:                 # the desktop asks which window or screen to share (once; then remembered)
            Shared.start(lambda e: notify("Screen sharing: " + e))
        if notif.enabled(cfgmod.get) and not notif.WATCH.start():   # desktop notifications inside the area
            dbg("dbus-monitor not found: notifications are only left out where the desktop says where they are")
        self.pending = None        # run requested while busy: None, False (auto) or True (forced)
        self._sel_token = 0
        self._badge_token = 0
        self.auto = QTimer(self)
        self.auto.setInterval(int(cfgmod.get("refresh.interval") * 1000))
        self.auto.timeout.connect(lambda: self.run(force=False))
        self.server = QLocalServer(self)
        QLocalServer.removeServer(SOCK)
        self.server.listen(SOCK)
        self.server.newConnection.connect(self.on_conn)

    def _warm_ocr(self):
        try:
            self.ocr.warm()
            self.cache.warm()
            dbg("OCR helper ready; translator=%s cache entries: %d" % (self.cache.kind, len(self.cache)))
        except Exception as e:  # noqa: BLE001
            dbg("OCR warm-up failed:", e)

    # -- IPC
    def on_conn(self):
        s = self.server.nextPendingConnection()
        s.waitForReadyRead(500)
        cmd = bytes(s.readAll()).decode().strip()
        try:
            reply = self.handle(cmd)
        except Exception as e:  # noqa: BLE001
            reply = "error: %s" % e
        s.write(reply.encode()); s.flush(); s.disconnectFromServer()

    def handle(self, cmd):
        dbg("command:", cmd)
        if cmd == "select":
            self.select(); return "ok"
        if cmd in ("toggle", "clear"):   # "clear" too: KDE may keep running the hotkey's old command
            if self.region.isEmpty():
                self.select(); return "select"
            if not self.hidden:
                self.hide_overlay(); return "hidden"
            self.show_overlay(); return "shown"
        if cmd.startswith("region "):
            parts = cmd.split()
            if len(parts) < 5:
                return "usage: region X Y W H [SCREEN]"
            x, y, w, h = [int(v) for v in parts[1:5]]
            if w < 8 or h < 8:
                return "region too small"
            named = [sc for sc in QGuiApplication.screens() if len(parts) > 5 and sc.name() == parts[5]]
            self.screen = named[0] if named else mouse_screen()
            dbg("screens", [(sc.name(), sc.geometry().getRect()) for sc in QGuiApplication.screens()], "using", self.screen.name())
            self.on_chosen(QRect(x, y, w, h)); return "ok"
        if cmd == "now":
            if self.region.isEmpty():
                self.select()
            else:
                if self.hidden:
                    self.show_overlay(refresh=False)
                self.run(force=True)
            return "ok"
        if cmd == "auto":
            if self.region.isEmpty():
                self.select(); self.auto.start(); return "auto on"
            if self.hidden:   # showing it again is what the user wants; keep auto as requested below
                self.show_overlay(refresh=False)
            on = not self.auto.isActive()
            self.auto.start() if on else self.auto.stop()
            self.badge("auto on" if on else "auto off", 1500)
            if on:
                self.run(force=False)   # only what changed; Translate now (Ctrl+Alt+X) is the full re-read
            return "auto on" if on else "auto off"
        if cmd.startswith("opacity"):
            parts = cmd.split()
            if len(parts) == 1:
                return "opacity %.2f" % self.opacity
            self.opacity = clamp_opacity(parts[1])
            cfgmod.set("overlay.opacity", round(self.opacity, 2))
            self._cfg_mtime = self._config_mtime()
            self.show_cards(self.raw_cards)
            return "opacity %.2f" % self.opacity
        if cmd.startswith("translator"):
            parts = cmd.split()
            if len(parts) == 1:
                return "translator %s" % self.cache.label()
            if self.worker is not None:
                # lines of the running refresh are still being translated: switching now would file the old
                # model's translations under the new one. The config is written; reload_config() applies it when
                # the refresh ends.
                if parts[1] not in tf.TRANSLATORS:
                    return "translator must be one of: " + ", ".join(tf.TRANSLATORS)
                vals = {"translator.kind": parts[1]}
                if len(parts) > 2:
                    vals["translator.llm_model"] = parts[2]
                cfgmod.set_many(vals)
                return "translator %s after this refresh" % parts[1]
            # typed on the command line: a translator with a missing model is refused and the answer says why at
            # once (a choice made in the settings / config.toml is applied anyway, with a notice: reload_config)
            note = self.cache.set_kind(parts[1], parts[2] if len(parts) > 2 else None)
            if self.cache.kind == parts[1] and (len(parts) < 3 or self.cache.model == parts[2]):
                vals = {"translator.kind": self.cache.kind}
                if self.cache.kind == "llm":
                    vals["translator.llm_model"] = self.cache.model
                cfgmod.set_many(vals)
                self._cfg_mtime = self._config_mtime()
                threading.Thread(target=self.cache.warm, daemon=True).start()
                self.badge("translator: " + self.cache.label(), 1500)
            return note or "translator %s" % self.cache.label()
        if cmd == "reset":
            self.close_picker()
            self.gen += 1; self.pending = None
            self.cancel_worker()
            self.overlay.set("badge", "")
            self.auto.stop(); self.cards = []; self.history = []; self.junk = []; self.mem = {}; self.last_sig = None
            self.hidden, self.auto_was = True, False
            self.overlay.set("cards", []); self.overlay.set("visible", False); return "reset"
        if cmd == "share":    # portal capture: forget the remembered window/screen and ask the desktop again
            if not PORTAL:
                return "this desktop does not use the screen-sharing portal ([capture] backend = \"portal\" turns it on)"
            import portalcap
            Shared.stop()
            portalcap.forget()
            Shared.told = False
            Shared.start(lambda e: notify("Screen sharing: " + e))
            return "asking your desktop what to share"
        if cmd == "status":   # for the GUI: one line of JSON
            return json.dumps({"auto": self.auto.isActive(), "hidden": self.hidden,
                               "region": None if self.region.isEmpty() else list(self.region.getRect()),
                               "screen": self.screen.name() if self.screen else None,
                               "translator": self.cache.label(), "busy": self.worker is not None,
                               "capture": CAPTURE, "shared": (None if not PORTAL or Shared.stream is None else
                                                              "window" if Shared.is_window() else "screen"),
                               "stale": code_changed_since(STARTED)})
        if cmd == "quit":
            self.close_picker()
            QTimer.singleShot(50, QGuiApplication.quit); return "bye"
        return "unknown command"

    def hide_overlay(self):
        self.hidden = True
        self.auto_was = self.auto.isActive() or self.auto_was
        self.auto.stop()
        self.gen += 1; self.pending = None   # drop anything in flight
        self.cancel_worker()
        self.overlay.set("badge", "")
        self.overlay.set("visible", False)

    def show_overlay(self, refresh=True):
        self.hidden = False
        self.overlay.set("showCards", True)
        self.overlay.place(self.screen)
        if self.auto_was:
            self.auto.start()
        self.auto_was = False
        if refresh:
            self.run(force=False)   # cheap: unchanged screen = no work, otherwise only what changed

    def badge(self, text, clear_after=0):
        self._badge_token += 1
        tok = self._badge_token
        self.overlay.set("badge", text)
        self._badge_until = time.time() + clear_after / 1000.0 if clear_after else 0.0
        if clear_after:
            QTimer.singleShot(clear_after, lambda: self.overlay.set("badge", "") if tok == self._badge_token else None)

    def clear_badge(self):
        """Clear a progress badge ("translating…"), but leave a timed message ("auto on") up until its time ends
        (the refresh that "auto on" starts used to wipe it at once)."""
        if time.time() < getattr(self, "_badge_until", 0.0):
            return
        self.overlay.set("badge", "")

    # -- region selection: frozen screenshot of the screen under the mouse
    def select(self):
        if self.selecting:
            return
        self.selecting = True
        self.overlay.set("showCards", False)
        QTimer.singleShot(200, self._select_capture)

    def _select_capture(self):
        try:
            img, bounds = capture_all()
        except Exception as e:  # noqa: BLE001
            notify("capture failed: %s" % e)
            self.selecting = False; self.overlay.set("showCards", True); return
        self._shot = (img, bounds)
        self.selwin.set("frame", "")
        self.selwin.place(mouse_screen())
        self._sel_token += 1
        tok = self._sel_token
        QTimer.singleShot(45000, lambda: self.close_picker() if self.selecting and tok == self._sel_token else None)
        # wait until the picker is mapped (incl. a possible re-map), then show the frozen frame of the monitor it is on
        QTimer.singleShot(600, self._select_frame)

    def _select_frame(self):
        name = self.selwin.output()
        sc = next((s for s in QGuiApplication.screens() if s.name() == name), QGuiApplication.primaryScreen())
        dbg("picker landed on", name)
        self._pick_screen = sc   # committed only when a box is actually chosen
        img, bounds = self._shot
        g = sc.geometry()
        frame = crop_screen_region(img, bounds, g, QRect(0, 0, g.width(), g.height()))
        self._frame_path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "lenslate-frame-%d.png" % os.getpid())
        frame.save(self._frame_path, "PNG")
        self.selwin.set("frame", QUrl.fromLocalFile(self._frame_path))

    def close_picker(self):
        """Always-available escape hatch: hide the picker, whatever state it is in."""
        self.selecting = False
        self.selwin.set("visible", False)
        self.drop_frame()
        self.overlay.set("showCards", True)

    def drop_frame(self):
        try:
            os.unlink(self._frame_path)
        except (AttributeError, OSError):
            pass

    def on_cancel(self):
        self.selecting = False
        self.drop_frame()
        self.overlay.set("showCards", True)
        if self.region.isEmpty():   # "auto" without an area opened the picker; cancelled: nothing to watch
            self.auto.stop()
            self.auto_was = False

    def on_chosen_xywh(self, x, y, w, h):
        self.selecting = False
        self.drop_frame()
        self.screen = getattr(self, "_pick_screen", None) or QGuiApplication.primaryScreen()
        self.on_chosen(QRect(x, y, w, h))

    def cancel_worker(self):
        if self.worker is not None:
            self.worker.cancelled = True

    def on_chosen(self, rect):
        self.region = rect
        self.gen += 1
        self.cancel_worker()
        self.last_sig = None
        self.history = []
        self.junk = []
        self.mem = {}
        self.text_scale = None
        self.target = None
        self.hidden = False
        self.cards = []
        self.overlay.set("cards", [])
        self.overlay.set("regionX", rect.x()); self.overlay.set("regionY", rect.y())
        self.overlay.set("showCards", True)
        self.overlay.place(self.screen)
        QTimer.singleShot(400, lambda: self.run(force=True))

    # -- translate the chosen region
    def run(self, force):
        dbg("run force=%s busy=%s region=%s selecting=%s" % (force, self.worker is not None, self.region, self.selecting))
        if self.region.isEmpty() or self.selecting or self.hidden:
            return
        if self.worker is not None:
            # remember it; it runs as soon as the current one finishes (a forced request wins)
            self.pending = bool(force or self.pending)
            if force:
                self.badge("translating…")
            return
        self.overlay.place(self.screen)
        if force:
            self.badge("translating…")
        self._fresh = True
        # Capture just the window that contains the region (the overlay is never part of it, so the cards stay up).
        # The focused window becomes the target; with KWin direct capture the target keeps being captured when it is
        # not focused (you clicked the other monitor). Without it, only the focused window can be captured.
        act = active_window()
        cur = None                 # the target window as it is now
        if self.target is not None:
            if act is not None and act.uuid == self.target.uuid:
                cur = act
            elif KWIN_DIRECT[0]:
                cur = window_target(self.target.uuid)
            if cur is not None and not PORTAL and cur.rect != self.target.rect:
                self.follow(cur)   # the game window was moved or resized: the area goes with it
        glob = self.region.translated(self.screen.geometry().topLeft())
        if X11 and not PORTAL:
            top = x_top_window(glob)
            if top is not None and (act is None or top.uuid != act.uuid):
                act = top
        win = None
        if act is not None and covers(act.rect, glob):
            win = self.target = act
        elif cur is not None and covers(cur.rect, glob):
            win = self.target = cur
        gen = self.gen
        if win is not None:
            self._told_focus = False
            game = window_game(win.uuid)
            if game != self.cache.names.game:
                dbg("game for names: %s" % game)
                self.cache.set_game(game)
            self._start_worker(force, win, gen)
        elif not force:
            # No capturable window for the region. A full-screen capture would have to hide the cards around every
            # shot (they flashed on and off each interval), so auto-refresh waits instead.
            dbg("target window not capturable/focused: auto refresh skipped")
            if not getattr(self, "_told_focus", False):
                # say it once per area: otherwise auto mode looks broken while it waits for the game window
                self._told_focus = True
                self.badge("auto needs a shared window, not a whole screen (lenslate share)" if PORTAL
                           else "auto waits: click the game window", 3000)
            else:
                self.clear_badge()
            return
        else:
            self.overlay.set("showCards", False)
            QTimer.singleShot(160, lambda: self._start_worker(force, None, gen))

    def follow(self, cur):
        """The target window moved or changed size since the last refresh: carry the chosen area (and its cards)
        along. A move keeps everything (the picture inside the window is the same); a resize starts the reading
        over, as the text is drawn at another size."""
        old = self.target.rect
        glob = moved_region(self.region.translated(self.screen.geometry().topLeft()), old, cur.rect)
        resized = cur.rect.size() != old.size()
        self.target = cur
        screen = QGuiApplication.screenAt(glob.center()) or self.screen
        dbg("window %s -> %s: area follows to %s%s" % (old.getRect(), cur.rect.getRect(), glob.getRect(),
                                                      " (resized: read again)" if resized else ""))
        self.screen = screen
        self.region = glob.translated(-screen.geometry().topLeft())
        self.overlay.set("regionX", self.region.x()); self.overlay.set("regionY", self.region.y())
        if resized:
            self.gen += 1
            self.last_sig, self.history, self.junk[:], self.text_scale = None, [], [], None
            self.mem.clear()
            self.cards, self.raw_cards = [], []
            self.overlay.set("cards", [])

    def _start_worker(self, force, win, gen):
        if self.worker is not None or self.region.isEmpty():
            return
        if gen != self.gen or self.selecting:   # cleared / new region / picker opened during the 160 ms wait
            if not self.selecting:
                self.overlay.set("showCards", True)
            return
        if self.engine_name == "ocr":
            w = OcrPipeline(self.screen.geometry(), self.region, list(self.history), force, win, self.ocr, self.cache,
                            self.text_scale, self.junk, self.mem, self.ocr_ultra)
        else:
            w = Pipeline(self.screen.geometry(), self.region, self.last_sig, force, win)
        w.hide_cards.connect(lambda: self.overlay.set("showCards", False))
        w.captured.connect(self.on_captured)
        w.partial.connect(lambda c, g=gen: self.on_partial(c, g))
        w.done.connect(lambda c, sig, g=gen: self.on_done(c, sig, g))
        w.failed.connect(lambda m, g=gen: self.on_failed(m, g))
        w.finished.connect(self.on_finished)
        self.worker = w
        w.start()

    def on_captured(self):
        dbg("captured")
        if not self.selecting:
            self.overlay.set("showCards", True)

    def show_cards(self, cards):
        self.raw_cards = list(cards)
        out = []
        for c in layout_cards(cards, self.region):
            card, px, align, mx, my = c["layout"]
            out.append({"x": card.x(), "y": card.y(), "w": card.width(), "h": card.height(),
                        "text": c["tr"], "bg": self.card_bg(c["bg"]), "bgs": c["bg"].name(), "fg": c["fg"].name(),
                        "outline": self.opacity < 0.95, "px": px,
                        "align": align, "mx": mx, "my": my})
        self.cards = out
        self.overlay.set("cards", out)

    @staticmethod
    def _config_mtime():
        return cfgmod.mtime()

    def reload_config(self):
        """Apply hand edits of config.toml (or GUI changes) while running. Translator, OCR helper and language
        changes wait while a refresh runs (its lines are still being read and translated): the file's time is then
        not taken as seen, so the next check (every 2 s, and right after the refresh ends) applies them."""
        m = self._config_mtime()
        if m == self._cfg_mtime:
            return
        busy = self.worker is not None
        applied = not busy
        kind, llm = wanted_translator()
        if (kind != self.cache.kind or (kind == "llm" and llm != self.cache.model)) and not busy:
            note = self.cache.set_kind(kind, llm, force=True)   # the user's choice, even with a model missing
            dbg("config changed: translator -> %s %s" % (self.cache.label(), note))
            if note:
                notify(note)
            threading.Thread(target=self.cache.warm, daemon=True).start()
        if not busy:
            if getattr(self, "ocr_ultra", None) is not None:
                self.ocr_ultra.follow_config()
            restarted = self.ocr.follow_config()     # GPU mode / threads: restart the OCR helper
            if restarted is None:                    # the helper is busy (warming up): try again on the next check
                applied = False
            elif restarted:
                dbg("config changed: OCR helper restarts (gpu %s)" % cfgmod.get("ocr.gpu"))
                threading.Thread(target=self.ocr.warm, daemon=True).start()
        lang = cfgmod.get("translator.language")
        if lang != self.cache.lang and not busy:   # target language changed in the settings
            dbg("config changed: target language %s -> %s" % (self.cache.lang, lang))
            note = self.cache.set_language(lang)
            if note:
                notify(note)
            self.overlay.set("family", card_family(lang))
            self.cards, self.raw_cards = [], []   # cards in the old language would stay up otherwise
            self.history = []
            self.overlay.set("cards", [])
            threading.Thread(target=self.cache.warm, daemon=True).start()
        iv = int(cfgmod.get("refresh.interval") * 1000)
        if iv != self.auto.interval():   # setInterval restarts the timer: only when it really changed
            self.auto.setInterval(iv)
        new = cfgmod.get("overlay.opacity")
        if abs(new - self.opacity) > 1e-6:
            dbg("config changed: opacity %.2f -> %.2f" % (self.opacity, new))
            self.opacity = new
            self.show_cards(self.raw_cards)
        if applied:
            self._cfg_mtime = m

    def card_bg(self, color):
        """Card background with the configured opacity (the text itself stays fully opaque)."""
        col = QColor(color)
        col.setAlphaF(self.opacity if see_through() else 1.0)
        return col.name(QColor.NameFormat.HexArgb)

    def on_partial(self, cards, gen):
        if gen != self.gen:
            return
        # new picture: the old cards are stale, replace them as the new ones stream in
        if self._fresh:
            self.clear_badge()
            self._fresh = False
        self.show_cards(cards)

    def on_done(self, cards, state, gen):
        dbg("done", None if cards is None else len(cards))
        if gen != self.gen:
            dbg("dropped stale result")
            return
        if self.engine_name == "ocr":
            self.text_scale = state.get("scale")
            rep_i = state["replace"]
            if rep_i is not None and rep_i < len(self.history):
                hg, hcards = self.history.pop(rep_i)
                self.history.insert(0, (state["grid"], hcards))
            else:
                self.history.insert(0, (state["grid"], cards))
            del self.history[tf.HISTORY:]
        else:
            self.last_sig = state
        if cards is not None:
            self.show_cards(cards)
        self.clear_badge()

    def on_failed(self, msg, gen):
        dbg("failed", msg)
        if not self.selecting:
            self.overlay.set("showCards", True)
        if gen == self.gen:
            self.badge("error: " + msg, 4000)

    def on_finished(self):
        self.worker = None
        self.reload_config()   # settings changed during the refresh (they waited for it)
        nxt, self.pending = self.pending, None
        if nxt is not None:
            self.run(force=nxt)


def names_cli(args):
    os.makedirs(nm.NAMES_DIR, exist_ok=True)
    if not args:
        files = sorted(f[:-4] for f in os.listdir(nm.NAMES_DIR) if f.endswith(".tsv"))
        print("name lists in %s:" % nm.NAMES_DIR)
        for g in files:
            e = nm.read_file(os.path.join(nm.NAMES_DIR, g + ".tsv"))
            print("  %-28s %3d confirmed, %3d to check" % (g, sum(v[0] == "ok" for v in e.values()),
                                                         sum(v[0] == "?" for v in e.values())))
        print("usage: lenslate names GAME | names scan GAME_FOLDER [OLLAMA_MODEL] | names ok GAME all|NAME...")
        return 0
    if args[0] == "scan" and len(args) >= 2:
        folder = os.path.abspath(os.path.expanduser(args[1]))
        model = args[2] if len(args) > 2 else wanted_translator()[1]
        print("scanning %s (names spelled by %s) ..." % (folder, model))
        game, found, _ids = nm.scan(folder, model, OLLAMA)
        added = nm.append_entries(game, found, " from game files")
        for jp, en in added:
            print("  %s  %s" % (jp, en if en != "-" else "(not a name)"))
        print("%d new entries -> %s" % (len(added), os.path.join(nm.NAMES_DIR, game + ".tsv")))
        if any(en != "-" for _jp, en in added):
            print("check them, then: lenslate names ok %s all   (or edit the file: remove the ?)" % game)
        return 0
    if args[0] == "ok" and len(args) >= 3:
        n = nm.confirm(args[1], args[2:])
        print("%d confirmed in %s" % (n, os.path.join(nm.NAMES_DIR, args[1] + ".tsv")))
        return 0
    path = os.path.join(nm.NAMES_DIR, nm.game_id(args[0]) + ".tsv")
    print(path)
    try:
        print(open(path, encoding="utf-8").read().rstrip())
    except OSError:
        print("(no list yet)")
    return 0


def send(cmd):
    s = QLocalSocket()
    s.connectToServer(SOCK)
    if not s.waitForConnected(300):
        return None
    s.write(cmd.encode()); s.flush(); s.waitForReadyRead(3000)
    reply = bytes(s.readAll()).decode()
    s.disconnectFromServer()
    return reply


def main():
    cmd = " ".join(sys.argv[1:]).strip() or "select"
    if cmd in ("-h", "--help", "help"):
        print(__doc__); return 0
    if sys.argv[1:2] == ["gui"]:   # settings window + tray icon (a normal window, not an overlay surface)
        os.environ.pop("QT_WAYLAND_SHELL_INTEGRATION", None)
        import gui
        return gui.main(sys.argv[2:])
    if sys.argv[1:2] == ["setup"]:   # first-launch setup window again (languages, preset + hardware check, downloads)
        if "--done" in sys.argv[2:]:   # the installer asked its questions in the terminal: no setup window
            cfgmod.set("general.setup_done", True)
            return 0
        os.environ.pop("QT_WAYLAND_SHELL_INTEGRATION", None)
        import gui
        return gui.main(["--setup"] + sys.argv[2:])
    if sys.argv[1:2] == ["testbench"]:   # test screens through every preset: step times + translation previews
        import testbench
        return testbench.cli(sys.argv[2:])
    if cmd in ("version", "--version", "-V"):
        print("lenslate %s" % version.describe()); return 0
    if sys.argv[1:2] == ["hotkeys"]:   # the four commands on keys, per desktop
        import hotkeys
        return hotkeys.cli(sys.argv[2:])
    if sys.argv[1:2] == ["capture"]:   # which capture method this desktop gets, with its advice
        print(captureinfo.text()); return 0
    if sys.argv[1:2] == ["hwcheck"]:   # what lenslate found in this PC, and which presets fit
        import hwcheck
        s = hwcheck.summary()
        g = hwcheck.best_gpu(s)
        print("processor: %s (%d threads), memory %.0f GB" % (s["cpu"], s["threads"], s["ram_gb"]))
        print("graphics:  %s" % (("%s, %.1f GB" % (g["name"] if g["name"].startswith(g["vendor"]) else g["vendor"] + " " + g["name"], g["vram_mb"] / 1024)) if g else "none found"))
        rec, why = hwcheck.recommend(s)
        print("recommended preset: %s (%s)" % (rec, why))
        for n in cfgmod.PRESET_ORDER:
            probs = hwcheck.check(n, s)
            print("  %-10s %s" % (n, "fits" if not probs else probs[0] + (" (+%d more)" % (len(probs) - 1) if len(probs) > 1 else "")))
        return 0
    if sys.argv[1:2] == ["models"]:   # model catalog / downloads: no daemon needed
        import models
        models.adopt_existing()
        return models.cli(sys.argv[2:])
    if sys.argv[1:2] == ["preset"]:   # pick a preset (no daemon needed: the running one follows config.toml)
        names = cfgmod.PRESET_ORDER
        if len(sys.argv) > 2:      # old names still work (light -> nogpu, fast -> balanced)
            sys.argv[2] = cfgmod.BY_KEY["general.preset"].aliases.get(sys.argv[2], sys.argv[2])
        if len(sys.argv) < 3 or sys.argv[2] not in names:
            print("preset: %s" % cfgmod.current_preset())
            for n in names:
                p = cfgmod.PRESETS[n]
                print("  %-9s %s Trade-off: %s" % (n, p["summary"], p["tradeoff"]))
            print("usage: lenslate preset %s" % "|".join(names))
            return 0
        cfgmod.apply_preset(sys.argv[2])
        p = cfgmod.PRESETS[sys.argv[2]]
        print("preset %s: %s\nTrade-off: %s" % (p["label"], p["summary"], p["tradeoff"]))
        return 0
    if sys.argv[1:2] == ["ocr-gpu"]:   # read text on the graphics card (optional CUDA runtime)
        import ocrgpu
        return ocrgpu.cli(sys.argv[2:])
    if sys.argv[1:2] == ["hook"]:   # game hooks (RPG Maker MV/MZ plugin, Unity XUnity): no daemon needed
        import hooks
        return hooks.cli(sys.argv[2:])
    if sys.argv[1:2] == ["names"]:   # name lists: plain files, no daemon needed (it reloads them by itself)
        return names_cli(sys.argv[2:])
    if cmd == "serve":   # hook mode: plain HTTP server, no overlay / Qt
        import hookserve
        return hookserve.serve(HERE, CACHE_PATH, LANG, OLLAMA)
    app = QGuiApplication(sys.argv[:1])
    QGuiApplication.setDesktopFileName(APP_ID)
    reply = send(cmd)
    if reply is not None:
        print(reply); return 0
    if cmd in ("reset", "quit", "status"):   # these never start lenslate
        print("lenslate is not running" if cmd != "status" else "not running"); return 0
    # two hotkey presses before the daemon is up must not start two daemons
    lock = QLockFile(os.path.join(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()), SOCK + ".lock"))
    if not lock.tryLock(0):
        for _ in range(30):
            QThread.msleep(100)
            reply = send(cmd)
            if reply is not None:
                print(reply); return 0
        print("lenslate is starting, try again"); return 1
    app.setQuitOnLastWindowClosed(False)
    global LOG
    LOG = SessionLog()
    if LOG.on:
        dbg("session start; lenslate %s; engine=%s model=%s debug dir=%s" % (version.describe(), ENGINE, MODEL, LOG.dir))
        LOG.record({"kind": "session", "lenslate": version.describe(), "platform": captureinfo.platform(),
                    "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""), "preset": cfgmod.current_preset(),
                    "translator": "%s %s" % wanted_translator()})
    d = Daemon()
    d.handle(cmd)
    rc = app.exec()
    lock.unlock()
    d.ocr.stop()
    d.ocr_ultra.stop()
    Shared.stop()
    d.cache.save()
    d.cache.stop()
    import llm
    llm.RUNNER.stop()   # the built-in model runner: give its GPU memory back (os._exit skips atexit)
    # a translation may still be blocked on the HTTP request; don't let Qt abort on a running QThread
    os._exit(rc)


if __name__ == "__main__":
    sys.exit(main())
