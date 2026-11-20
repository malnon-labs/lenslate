"""Desktop notifications that pop up inside the area lenslate reads.

A whole-screen picture (an area that belongs to no window, X11's root window, a shared screen through the portal)
also holds the notifications the desktop shows on top: a chat message relayed from a phone was read, translated and
kept in the debug recording. Window captures never have them (KWin's and X11's window pictures hold only the game).

Two ways to keep them out, both used when they can be:
- where the desktop says where its notifications are, those rectangles are covered before anything is read or
  recorded (KDE: KWin window types Notification / OSD / Critical notification; X11: _NET_WM_WINDOW_TYPE_NOTIFICATION
  windows, e.g. xfce4-notifyd, MATE, dunst);
- everywhere else (Cinnamon and GNOME draw notifications inside the shell, Hyprland/niri/Sway daemons have no
  positions to ask for): every notification sent on the session bus is watched with dbus-monitor, and for as long as
  it is on screen a line read from the picture that is part of its text is dropped. Those pictures can still hold
  the notification in a debug recording; the dropped lines are blacked out in the recorded picture.
"""
import atexit
import difflib
import os
import re
import shutil
import subprocess
import threading
import time

KDE_TYPES = {13, 16, 17}    # NET::Notification, NET::OnScreenDisplay, NET::CriticalNotification (KWin getWindowInfo)
SHOWN_S = 8.0               # how long a notification stays when its sender leaves it to the desktop (-1): Plasma 5 s,
                            # GNOME / Cinnamon a few seconds more for long texts
STICKY_S = 30.0             # critical or never-expiring ones: watched this long (no way to see them go on most desktops)
GRACE_S = 1.5               # fade-in / fade-out and the time between the picture and the read
MIN_CHARS = 4               # shorter Latin lines ("OK", "now") are left alone: too likely to be the game's own
MIN_CHARS_CJK = 2

_HEADER = re.compile(r"^(method call|method return|signal|error) time=")
_WIDE = re.compile(r"[぀-ヿ㐀-鿿가-힯豈-﫿]")


def _norm(t):
    return re.sub(r"[\W_]+", "", t or "").casefold()


# ----------------------------------------------------------------------------------------- what dbus-monitor prints
def parse_monitor(lines):
    """Notify calls from `dbus-monitor --session` output lines: yields dicts with app, summary, body, expire (ms,
    -1 = the desktop decides, 0 = never) and urgency (0 low, 1 normal, 2 critical). The arguments are printed one
    per line with a three-space indent; a string goes on until the next argument (bodies have line breaks)."""
    msg, cur, last_key = None, None, None

    def finish_string():
        nonlocal cur
        if cur is not None:
            s = "\n".join(cur)
            msg["args"].append(s[:-1] if s.endswith('"') else s)
            cur = None

    for raw in lines:
        line = raw.rstrip("\n")
        if _HEADER.match(line):               # a new message (string continuation lines start at column 0 too)
            if msg is not None:
                finish_string()
            msg = {"args": [], "urgency": 1} if ("member=Notify" in line and line.startswith("method call")) else None
            cur, last_key = None, None
            continue
        if msg is None:
            continue
        top = line.startswith("   ") and not line.startswith("    ")
        if not top and cur is None and not line.startswith(" "):
            continue
        if not top:
            if cur is not None and len(msg["args"]) < 5:      # a line of a multi-line string
                cur.append(line)
                continue
            s = line.strip()                                  # inside the actions / hints arrays
            if s.startswith('string "'):
                last_key = s[8:-1]
            elif last_key == "urgency" and "byte" in s:
                try:
                    msg["urgency"] = int(s.split("byte")[-1])
                except ValueError:
                    pass
                last_key = None
            continue
        finish_string()
        s = line[3:]
        if s.startswith('string "'):
            cur = [s[8:]]
        elif s.startswith(("uint32 ", "int32 ")):
            msg["args"].append(s.split()[-1])
            if s.startswith("int32 ") and len(msg["args"]) >= 6:   # the last argument: expire_timeout
                a = msg["args"]
                try:
                    expire = int(a[-1])
                except ValueError:
                    expire = -1
                if len(a) >= 5:
                    yield {"app": a[0], "summary": a[3], "body": a[4], "expire": expire, "urgency": msg["urgency"]}
                msg = None
        elif s.startswith("array"):
            msg["args"].append("")            # actions / hints: placeholders so the int32 count stays right
    if msg is not None:
        finish_string()


def _strip_markup(t):
    return re.sub(r"<[^>]+>", " ", t or "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


# --------------------------------------------------------------------------------------------------- the watcher
class Watcher:
    """Notifications shown lately, from the session bus (dbus-monitor in the background)."""

    def __init__(self):
        self.items = []           # [(until, normalised text, words)]
        self.lock = threading.Lock()
        self.proc = None
        self.running = False

    def start(self):
        if self.running:
            return True
        exe = shutil.which("dbus-monitor")
        if exe is None:
            return False
        try:
            self.proc = subprocess.Popen(
                [exe, "--session", "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True,
                errors="replace", bufsize=1)
        except OSError:
            return False
        self.running = True
        atexit.register(self.stop)
        threading.Thread(target=self._read, daemon=True).start()
        return True

    def _read(self):
        try:
            for n in parse_monitor(self.proc.stdout):
                self.add(n)
        finally:
            self.running = False

    def stop(self):
        p, self.proc = self.proc, None
        if p is not None:
            try:
                p.terminate()
                p.wait(1)
            except (OSError, subprocess.SubprocessError):
                pass
        self.running = False

    def add(self, n, now=None):
        now = time.time() if now is None else now
        if n.get("urgency") == 2 or n.get("expire") == 0:
            stay = STICKY_S
        elif n.get("expire", -1) > 0:
            stay = min(n["expire"] / 1000.0, STICKY_S)
        else:
            stay = SHOWN_S
        texts = [n.get("app", ""), n.get("summary", ""), _strip_markup(n.get("body", ""))]
        with self.lock:
            self.items = [it for it in self.items if it[0] > now]
            self.items.append((now + stay + GRACE_S, _norm(" ".join(texts)), [_norm(t) for t in texts if _norm(t)]))

    def active(self, now=None):
        """True while a notification may be on screen."""
        now = time.time() if now is None else now
        with self.lock:
            return any(it[0] > now for it in self.items)

    def matches(self, text, now=None):
        """The read line is (part of) a notification on screen now."""
        now = time.time() if now is None else now
        with self.lock:
            blobs = [it for it in self.items if it[0] > now]
        if not blobs:
            return False
        return any(text_in(text, blob) for _until, blob, _words in blobs)


def text_in(text, blob):
    """A read line is part of a notification's text: whole, or with a few misread letters (a line of the body read
    with an OCR slip, or cut at the notification's edge)."""
    n = _norm(text)
    if len(n) < (MIN_CHARS_CJK if _WIDE.search(n) else MIN_CHARS) or not blob:
        return False
    if n in blob:
        return True
    if len(n) < 6:
        return False
    m = difflib.SequenceMatcher(None, n, blob, autojunk=False)
    blocks = [b for b in m.get_matching_blocks() if b.size >= 2]
    if not blocks:
        return False
    hit = sum(b.size for b in blocks)
    span = blocks[-1].b + blocks[-1].size - blocks[0].b
    return hit >= 0.8 * len(n) and span <= 1.5 * len(n)


WATCH = Watcher()


# ------------------------------------------------------------------------------------- where they are on screen
def kde_rects():
    """Global logical rectangles (x, y, w, h) of KWin's notification and on-screen-display windows, or []."""
    if shutil.which("kdotool") is None:
        return []
    try:
        ids = subprocess.run(["kdotool", "search", "."], capture_output=True, text=True, timeout=2).stdout.split()
        ids += subprocess.run(["kdotool", "search", "--class", "plasmashell"], capture_output=True, text=True,
                              timeout=2).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return []
    try:
        import dbus
        bus = dbus.SessionBus()
        kw = dbus.Interface(bus.get_object("org.kde.KWin", "/KWin"), "org.kde.KWin")
    except Exception:  # noqa: BLE001 - no KWin on this bus
        return []
    out = []
    for wid in dict.fromkeys(i for i in ids if i.startswith("{")):
        try:
            info = kw.getWindowInfo(wid)
            if int(info.get("type", -1)) in KDE_TYPES:
                out.append(tuple(int(round(float(info[k]))) for k in ("x", "y", "width", "height")))
        except Exception:  # noqa: BLE001 - the window just went away
            continue
    return out


def x11_rects():
    """X pixel rectangles of mapped notification windows on an X11 desktop, or []."""
    try:
        import x11 as xb
        return xb.notification_rects()
    except Exception:  # noqa: BLE001
        return []


def enabled(cfg_get):
    return bool(cfg_get("capture.ignore_notifications")) and not os.environ.get("LENSLATE_NO_NOTIFY_WATCH")
