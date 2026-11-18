"""Screen capture through the desktop portal (org.freedesktop.portal.ScreenCast) and PipeWire.

This is the capture path every Wayland desktop offers (GNOME, Hyprland, Sway, KDE): the desktop shows its own
"share a window or a screen" dialog once, lenslate keeps the answer (a restore token) so the dialog does not come
back, and the frames arrive over PipeWire (read here with GStreamer's pipewiresrc). On KDE lenslate normally uses
KWin's own window capture instead (lenslate.py); this module is for the other desktops, or `[capture] backend =
"portal"`.

What the portal does NOT tell an application: where the shared window is on the screen. lenslate therefore treats
a shared *window* as filling its monitor (a fullscreen or borderless game). A shared *monitor* lines up always, but
its picture includes lenslate's own cards, so they are hidden for a moment around every read.

Needs: python3-gobject, GStreamer with the PipeWire plugin (pipewiresrc), xdg-desktop-portal with a backend.
"""
import os
import threading
import time

import config as cfgmod

TOKEN_PATH = os.path.join(cfgmod.CONFIG_DIR, "portal-token")
MONITOR, WINDOW = 1, 2
MAX_FPS = 10          # asked of the desktop: lenslate reads about once a second


class PortalError(RuntimeError):
    pass


def missing():
    """What this PC lacks for portal capture, as text ("" = nothing)."""
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        if Gst.ElementFactory.find("pipewiresrc") is None:
            return "GStreamer's PipeWire plugin (package gstreamer1-plugin-pipewire / gst-plugin-pipewire / gstreamer1.0-pipewire)"
    except (ImportError, ValueError):
        return "python3-gobject with GStreamer (packages python3-gobject, gstreamer1)"
    return ""


def _load_token():
    try:
        with open(TOKEN_PATH) as f:
            return f.read().strip()
    except OSError:
        return ""


def _save_token(tok):
    try:
        os.makedirs(cfgmod.CONFIG_DIR, exist_ok=True)
        fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(tok)
    except OSError:
        pass


class Stream:
    """One shared window or monitor. start() asks the desktop (blocks while its dialog is open); frame() gives the
    newest picture as (bytes, width, height, stride) in BGRx, or None."""

    def __init__(self, ask_timeout=120.0):
        self.ask_timeout = ask_timeout
        self.kind = None            # MONITOR or WINDOW
        self.size = None            # (w, h) the desktop reported (logical), may be None
        self.position = None        # monitors: (x, y) in the desktop's coordinates, may be None
        self.pipeline = None
        self.sink = None
        self.lock = threading.Lock()
        self.sample = None          # newest Gst.Sample
        self.sample_at = 0.0
        self.error = None
        self._conn = None
        self._session = None

    # ------------------------------------------------------------------------------------------ portal
    def start(self):
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gio, GLib, Gst
        Gst.init(None)
        ctx = GLib.MainContext.new()
        ctx.push_thread_default()
        try:
            addr = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
            conn = Gio.DBusConnection.new_for_address_sync(
                addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                None, None)
            self._conn = conn
            sender = conn.get_unique_name()[1:].replace(".", "_")
            n = [0]

            def request(method, args_fmt, args, options):
                """Call a portal method that answers through a Request object; returns its results dict."""
                n[0] += 1
                token = "lenslate%d_%d" % (os.getpid(), n[0])
                options = dict(options, handle_token=GLib.Variant("s", token))
                path = "/org/freedesktop/portal/desktop/request/%s/%s" % (sender, token)
                got = []
                sub = conn.signal_subscribe("org.freedesktop.portal.Desktop", "org.freedesktop.portal.Request",
                                            "Response", path, None, Gio.DBusSignalFlags.NONE,
                                            lambda *a: got.append(a[5].unpack()))
                try:
                    conn.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                                   "org.freedesktop.portal.ScreenCast", method,
                                   GLib.Variant(args_fmt, tuple(args) + (options,)), None,
                                   Gio.DBusCallFlags.NONE, 5000, None)
                    end = time.time() + self.ask_timeout
                    while not got and time.time() < end:
                        ctx.iteration(False)
                        time.sleep(0.02)
                finally:
                    conn.signal_unsubscribe(sub)
                if not got:
                    # also what a failed share looks like: niri nested in another desktop (no GBM device) stops the
                    # cast after the user picked a window, and the portal then sends no answer at all (2026-11-13)
                    raise PortalError("screen sharing did not start: no answer from the desktop. If you did pick "
                                      "something, the desktop's screen sharing failed - try `lenslate share` again, "
                                      "or log out and back in")
                code, results = got[0]
                if code != 0:
                    raise PortalError("screen sharing was not allowed" if code == 1 else "screen sharing ended")
                return results

            res = request("CreateSession", "(a{sv})", (),
                          {"session_handle_token": GLib.Variant("s", "lenslate%d" % os.getpid())})
            session = res["session_handle"]
            self._session = session
            opts = {"types": GLib.Variant("u", MONITOR | WINDOW), "multiple": GLib.Variant("b", False),
                    "cursor_mode": GLib.Variant("u", 1),          # no mouse pointer in the picture
                    "persist_mode": GLib.Variant("u", 2)}         # remember the choice until revoked
            tok = _load_token()
            if tok:
                opts["restore_token"] = GLib.Variant("s", tok)
            request("SelectSources", "(oa{sv})", (session,), opts)
            res = request("Start", "(osa{sv})", (session, ""), {})
            if res.get("restore_token"):
                _save_token(res["restore_token"])       # single use: the new one replaces the old
            streams = res.get("streams") or []
            if not streams:
                raise PortalError("the desktop shared nothing")
            node, props = streams[0]
            self.kind = int(props.get("source_type", MONITOR))
            self.size = tuple(props["size"]) if props.get("size") else None
            self.position = tuple(props["position"]) if props.get("position") else None
            ret, fds = conn.call_with_unix_fd_list_sync(
                "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.ScreenCast", "OpenPipeWireRemote",
                GLib.Variant("(oa{sv})", (session, {})), None, Gio.DBusCallFlags.NONE, 5000, None, None)
            fd = fds.get(ret.unpack()[0])
        except GLib.Error as e:
            self.stop()
            raise PortalError("screen-sharing portal: %s" % e.message) from None
        except PortalError:
            self.stop()         # also takes the desktop's dialog away when nobody answered it
            raise
        finally:
            ctx.pop_thread_default()
        self._play(Gst, "pipewiresrc fd=%d path=%d do-timestamp=true keepalive-time=1000 ! "
                   "video/x-raw,max-framerate=%d/1" % (fd, node, MAX_FPS))
        return self

    # ---------------------------------------------------------------------------------------- pipewire
    def _play(self, Gst, source):
        """source: the GStreamer elements that deliver the video (the tests use a test picture instead)."""
        desc = (source + " ! videoconvert ! video/x-raw,format=BGRx ! "
                "appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false")
        try:
            self.pipeline = Gst.parse_launch(desc)
        except Exception as e:  # noqa: BLE001 - GLib.Error
            raise PortalError("PipeWire stream: %s" % e) from None
        self.sink = self.pipeline.get_by_name("sink")
        self.sink.connect("new-sample", self._on_sample)
        self.pipeline.set_state(Gst.State.PLAYING)
        self._Gst = Gst

    def _on_sample(self, sink):
        s = sink.emit("pull-sample")
        if s is not None:
            with self.lock:
                self.sample, self.sample_at = s, time.time()
        return 0     # Gst.FlowReturn.OK

    def frame(self, newer_than=0.0, wait=2.0):
        """The newest picture; with newer_than, one that arrived after that time (waits up to `wait` seconds, then
        gives the newest anyway: a still screen sends no new frames)."""
        end = time.time() + wait
        while True:
            with self.lock:
                s, at = self.sample, self.sample_at
            if s is not None and (at > newer_than or time.time() >= end):
                break
            if time.time() >= end:
                return None
            time.sleep(0.02)
        caps = s.get_caps().get_structure(0)
        w, h = caps.get_value("width"), caps.get_value("height")
        buf = s.get_buffer()
        ok, info = buf.map(self._Gst.MapFlags.READ)
        if not ok:
            return None
        try:
            data = bytes(info.data)
        finally:
            buf.unmap(info)
        return data, w, h, len(data) // max(1, h)

    def stop(self):
        if self.pipeline is not None:
            self.pipeline.set_state(self._Gst.State.NULL)
            self.pipeline = None
            with self.lock:
                self.sample = None
        if self._conn is not None and self._session:
            try:
                self._conn.call_sync("org.freedesktop.portal.Desktop", self._session,
                                     "org.freedesktop.portal.Session", "Close", None, None, 0, 2000, None)
            except Exception:  # noqa: BLE001 - already closed
                pass
            self._conn = None


def forget():
    """Drop the remembered choice: the desktop asks again next time."""
    try:
        os.unlink(TOKEN_PATH)
    except OSError:
        pass


if __name__ == "__main__":      # quick look: python3 portalcap.py out.png
    import sys
    from PySide6.QtGui import QImage
    st = Stream(ask_timeout=float(os.environ.get("ASK", "60"))).start()
    print("shared:", "monitor" if st.kind == MONITOR else "window", "size", st.size, "position", st.position)
    f = st.frame(wait=5)
    if f is None:
        print("no frame")
    else:
        QImage(f[0], f[1], f[2], f[3], QImage.Format_RGB32).save(sys.argv[1] if len(sys.argv) > 1 else "/dev/null")
        print("frame", f[1:])
        t = time.time(); n0 = st.sample_at; time.sleep(3)
        print("still receiving:", st.sample_at > n0)
    st.stop()
