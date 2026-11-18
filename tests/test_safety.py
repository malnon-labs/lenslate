"""Hook server request filter, loader removal limits, config robustness, verified downloads, config reload timing."""
import functools
import hashlib
import http.server
import json
import os
import shutil
import tempfile
import threading
import time
import unittest

from tests import SCRATCH
import config as cfgmod


class HookServerFilter(unittest.TestCase):
    def test_allowed(self):
        import hookserve as h
        cases = [({"Host": "127.0.0.1:14366"}, True),                                     # XUnity, Ren'Py
                 ({"Host": "127.0.0.1:14366", "Origin": "chrome-extension://abc"}, True),  # RPG Maker (NW.js)
                 ({"Host": "127.0.0.1:14366", "Origin": "file://"}, True),
                 ({"Host": "localhost:14366", "Origin": "http://localhost:8000"}, True),
                 ({"Host": "127.0.0.1:14366", "Origin": "https://evil.example"}, False),   # a web page
                 ({"Host": "127.0.0.1:14366", "Origin": "null"}, False),                   # a sandboxed iframe
                 ({"Host": "evil.example:14366"}, False),                                  # DNS rebinding
                 ({"Host": "127.0.0.1:14366", "Sec-Fetch-Dest": "image", "Sec-Fetch-Site": "cross-site"}, False)]
        for headers, want in cases:
            self.assertEqual(h.allowed(headers), want, headers)


class LoaderRemoval(unittest.TestCase):
    def test_manifest_cannot_reach_outside_the_game(self):
        import unityloader
        base = tempfile.mkdtemp(dir=SCRATCH)
        game, victim = os.path.join(base, "game"), os.path.join(base, "victim")
        os.makedirs(os.path.join(game, "BepInEx", "plugins"))
        os.makedirs(victim)
        open(os.path.join(victim, "precious.txt"), "w").write("keep")
        open(os.path.join(game, "BepInEx", "plugins", "a.dll"), "w").write("x")
        os.symlink(victim, os.path.join(game, "link"))
        json.dump({"packages": ["bepinex5"], "files": ["BepInEx/plugins/a.dll", "../victim/precious.txt",
                                                       os.path.join(victim, "precious.txt"), "link/precious.txt"]},
                  open(os.path.join(game, unityloader.LOADER_MARK), "w"))
        self.assertEqual(unityloader.remove(game), 1)
        self.assertTrue(os.path.exists(os.path.join(victim, "precious.txt")))
        shutil.rmtree(base)


class ConfigRobustness(unittest.TestCase):
    def test_value_where_a_section_belongs(self):
        with open(cfgmod.CONFIG_PATH, "w") as f:
            f.write("translator = 5\n")
        cfgmod._cache["mtime"] = object()
        self.assertEqual(cfgmod.get("translator.kind"), cfgmod.BY_KEY["translator.kind"].default)
        os.remove(cfgmod.CONFIG_PATH)

    def test_config_is_private(self):
        cfgmod.set("overlay.opacity", 0.9)
        self.assertEqual(os.stat(cfgmod.CONFIG_PATH).st_mode & 0o777, 0o600)

    def test_custom_cache_path_is_per_language(self):
        os.environ["LENSLATE_CACHE"] = os.path.join(SCRATCH, "my-cache.json")
        try:
            cfgmod.set("translator.language", "Spanish")
            self.assertTrue(cfgmod.cache_path().endswith("my-cache-spanish.json"))
            cfgmod.set("translator.language", "English")
            self.assertTrue(cfgmod.cache_path().endswith("my-cache.json"))
        finally:
            del os.environ["LENSLATE_CACHE"]


class Downloads(unittest.TestCase):
    def test_size_checksum_and_one_at_a_time(self):
        import fcntl
        import models
        srv_dir = tempfile.mkdtemp(dir=SCRATCH)
        data = os.urandom(300000)
        open(os.path.join(srv_dir, "m.bin"), "wb").write(data)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=srv_dir)
        handler.log_message = lambda *a: None
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d/m.bin" % srv.server_port
        dest = os.path.join(srv_dir, "out", "m.bin")
        quiet = lambda *a: None   # noqa: E731
        try:
            with self.assertRaises(RuntimeError):
                models._download(url, dest, quiet, 0, 0, len(data), "0" * 64)       # damaged
            self.assertFalse(os.path.exists(dest))
            with self.assertRaises(RuntimeError):
                models._download(url, dest, quiet, 0, 0, len(data) + 1)           # incomplete
            self.assertFalse(os.path.exists(dest))
            models._download(url, dest, quiet, 0, 0, len(data), hashlib.sha256(data).hexdigest())
            self.assertEqual(open(dest, "rb").read(), data)
            lock = open(dest + ".lock", "w")
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaises(RuntimeError):
                models._download(url, dest, quiet, 0, 0)                          # already running elsewhere
            lock.close()
        finally:
            srv.shutdown()


class PinnedDownloads(unittest.TestCase):
    def test_every_catalog_download_names_one_commit(self):
        import models
        for m in models.CATALOG:
            for repo in filter(None, [m.repo, m.gguf and m.gguf[0]]):
                self.assertRegex(models.revision(repo), r"^[0-9a-f]{40}$", "%s is not pinned (models.REVISIONS)" % repo)
                self.assertIn("/resolve/%s/" % models.revision(repo), models.file_url(repo, "x.bin"))



    def test_changes_during_a_refresh_are_applied_after_it(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        import lenslate as ls

        class Stub:
            _config_mtime = staticmethod(cfgmod.mtime)

            def __init__(s):
                s.worker, s.raw_cards, s.cards, s.history = object(), [], [], []
                s._cfg_mtime, s.opacity = cfgmod.mtime(), cfgmod.get("overlay.opacity")

                class C:
                    kind, model, lang = "mt", "gemma-4-e2b", "English"

                    def set_kind(c, k, m=None, force=False):
                        c.kind = k
                        return ""

                    def set_language(c, lang):
                        c.lang = lang
                        return ""

                    def label(c):
                        return c.kind

                    def warm(c):
                        pass

                class O:
                    def follow_config(o):
                        return False

                class Ov:
                    def set(o, *a):
                        pass

                class T:
                    def interval(t):
                        return 1000

                    def setInterval(t, v):
                        pass
                s.cache, s.ocr, s.overlay, s.auto = C(), O(), Ov(), T()

            def show_cards(s, c):
                pass

        cfgmod.set_many({"translator.kind": "mt", "translator.language": "English"})
        d = Stub()
        time.sleep(0.05)
        cfgmod.set_many({"translator.kind": "sugoi", "translator.language": "Spanish"})
        ls.Daemon.reload_config(d)                 # a refresh is running: wait
        self.assertEqual((d.cache.kind, d.cache.lang), ("mt", "English"))
        d.worker = None
        ls.Daemon.reload_config(d)                 # it ended: now
        self.assertEqual((d.cache.kind, d.cache.lang), ("sugoi", "Spanish"))


if __name__ == "__main__":
    unittest.main()


class ReleaseFiles(unittest.TestCase):
    def test_notice_lists_every_catalog_model_with_its_licence(self):
        import models
        from tests import ROOT
        text = open(os.path.join(ROOT, "NOTICE.md"), encoding="utf-8").read()
        for m in models.CATALOG:
            row = next((ln for ln in text.splitlines() if ln.startswith("| %s |" % m.name)), None)
            self.assertIsNotNone(row, "%s is missing from NOTICE.md" % m.name)
            self.assertIn(m.license, row)

    def test_changelog_has_the_current_version(self):
        import version
        from tests import ROOT
        self.assertIn("## %s" % version.VERSION, open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read())
        self.assertRegex(version.VERSION, r"^\d+\.\d+\.\d+$")



    def test_fresh_install_has_no_model_folder(self):
        """A language model without a file list (PLaMo: GGUF only) crashed every `lenslate models` call on a PC
        with no models yet, and counted as installed where the folder existed."""
        import models
        models.adopt_existing()
        for m in models.CATALOG:
            if not m.files:
                self.assertFalse(os.path.exists(os.path.join(m.path, ".complete")), m.name)


class CaptureGuide(unittest.TestCase):
    def test_method_per_desktop_and_texts(self):
        import captureinfo
        keep = {k: os.environ.get(k) for k in ("LENSLATE_PLATFORM", "WAYLAND_DISPLAY", "DISPLAY", "XDG_CURRENT_DESKTOP",
                                               "LENSLATE_CAPTURE")}
        try:
            os.environ.pop("LENSLATE_PLATFORM", None)
            os.environ.pop("LENSLATE_CAPTURE", None)
            os.environ.update(WAYLAND_DISPLAY="wayland-0", XDG_CURRENT_DESKTOP="KDE")
            self.assertEqual(captureinfo.platform(), "kwin")
            os.environ["XDG_CURRENT_DESKTOP"] = "Hyprland"
            self.assertEqual(captureinfo.platform(), "portal")
            os.environ.update(XDG_CURRENT_DESKTOP="KDE", LENSLATE_CAPTURE="portal")
            self.assertEqual(captureinfo.platform(), "portal")
            os.environ.pop("WAYLAND_DISPLAY")
            os.environ["DISPLAY"] = ":0"
            self.assertEqual(captureinfo.platform(), "x11")
        finally:
            for k, v in keep.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        for m in ("kwin", "x11", "portal"):
            self.assertIn(captureinfo.guide(m)["title"], captureinfo.text(m))
        self.assertIn("whole SCREEN", captureinfo.text("portal"))
