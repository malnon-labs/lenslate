"""`lenslate serve`: translation endpoint for in-game text hooks (hook mode).

XUnity.AutoTranslator (Unity games, via BepInEx) reads the game's own text objects and asks a translator; its
CustomTranslate endpoint sends   GET <Url>?from=ja&to=en&text=<text>   and shows the plain-text reply in the
game's own UI. No screenshots, no OCR, no overlay - and no OCR misreads. lenslate answers from the same
translation cache as the overlay, and cache misses go to the current translator (llm or mt, see
`lenslate translator`).

Game side, BepInEx/config/AutoTranslatorConfig.ini:
    [Service]
    Endpoint=CustomTranslate
    [General]
    Language=en
    FromLanguage=ja
    [Custom]
    Url=http://127.0.0.1:14366/g/<game>/translate     (<game> = exe name, e.g. mygame; selects the
                                                      game's name list, see names.py; /translate = global list)
"""
import json
import os
import re
import signal
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rpgm
import textflow as tf

import config as cfgmod


class Service:
    def __init__(self, here, cache_path, lang, url, log):
        self.log = log
        self.mtime = cfgmod.mtime()
        kind, llm = cfgmod.get("translator.kind"), cfgmod.get("translator.llm_model")
        self.tr = tf.Translator(here, cache_path, lang, llm, url, kind)
        self.lock = threading.Lock()          # one translation at a time (one GPU / a few CPU threads)
        self.stats = {"hits": 0, "new": 0, "failed": 0}
        self.qlock = threading.Lock()
        self.qevent = threading.Event()
        self.pending, self.queued = [], set()
        threading.Thread(target=self._worker, daemon=True).start()

    def _follow_config(self):
        """config.toml changed (GUI, hand edit, `lenslate translator`): switch translator and target language."""
        m = cfgmod.mtime()
        if m != self.mtime:
            self.mtime = m
            kind, llm = cfgmod.get("translator.kind"), cfgmod.get("translator.llm_model")
            lang = cfgmod.get("translator.language")
            if lang != self.tr.lang:   # "Translate into" changed: the new language's cache files and models
                note = self.tr.set_language(lang)
                self.log("language -> %s %s" % (lang, note))
            if kind != self.tr.kind or (kind == "llm" and llm != self.tr.model):
                note = self.tr.set_kind(kind, llm, force=True)   # the user's choice, even with a model missing
                self.log("translator -> %s %s" % (self.tr.label(), note))

    def _key(self, text):
        # one block: wrapped lines are joined (the game re-wraps the reply in its text box)
        return " ".join(l.strip() for l in text.split("\n") if l.strip())

    def lookup(self, key, game):
        """Cached translation. It does not wait for a translation in progress (the game hooks wait for this answer
        synchronously: a cached line must not freeze the game while the model works on another one, e.g. during the
        ~30 s very first start of the language model). The caches and name lists have their own locks; only a
        different game's name list needs the translation lock (switching it under a running translation would
        change that translation's key)."""
        if self.tr.names.game == (game or "unknown"):
            return self.tr.get(key)
        with self.lock:
            self.tr.set_game(game)
            return self.tr.get(key)

    def translate_key(self, key, game):
        """Cache hit or translate now (blocks while the model works)."""
        with self.lock:
            self._follow_config()
            self.tr.set_game(game)
            tr = self.tr.get(key)
            if tr is not None:
                self.stats["hits"] += 1
                return tr
            t0 = time.time()
            tr = self.tr.translate_text(key)
            if tr is None:
                self.stats["failed"] += 1
                self.log("FAILED (%.2fs) %s" % (time.time() - t0, _shown(key, 80)))
                return None
            self.stats["new"] += 1
            self.log("%s %.2fs  %s  ->  %s" % (self.tr.label(), time.time() - t0, _shown(key, 60), _shown(tr, 80)))
            return tr

    def queue(self, keys, game):
        """Translate in the background (the game asked without waiting); later requests find them cached."""
        with self.qlock:
            for k in keys:
                if (game, k) not in self.queued:
                    self.queued.add((game, k))
                    self.pending.append((game, k))
        self.qevent.set()

    def _worker(self):
        while True:
            self.qevent.wait()
            with self.qlock:
                if not self.pending:
                    self.qevent.clear()
                    continue
                game, key = self.pending.pop(0)
            try:
                self.translate_key(key, game)
            except Exception as e:  # noqa: BLE001
                self.log("background error: %r" % e)
            with self.qlock:
                self.queued.discard((game, key))

    def translate(self, text, game="unknown", engine=None, kind="message", wait=True):
        """Raw game text -> translated text, or None (not translated / not ready when wait=False)."""
        if not tf.wants_translation(text):
            return text
        if engine in ("rpgm", "renpy"):
            segs = rpgm.split(text, kind, engine)
            keys = [sg[1] for sg in segs if sg[0] == "tr"]
        else:
            segs, keys = None, [self._key(text)]
        found = {}
        for k in keys:
            tr = self.lookup(k, game)
            if tr is None and wait:
                tr = self.translate_key(k, game)
            if tr is not None:
                found[k] = tr
        missing = [k for k in keys if k not in found]
        if missing:
            if not wait:
                self.queue(missing, game)
            return None
        return rpgm.assemble(segs, found) if segs is not None else found[keys[0]]

    def close(self):
        self.tr.save()
        self.tr.stop()
        import llm
        llm.RUNNER.stop()


def _shown(text, n):
    """Game text in the log only with the debug log on ([debug] enabled): the server's log (wherever `lenslate serve`
    is redirected) otherwise kept every line of every game played, and its translation."""
    if cfgmod.get("debug.enabled"):
        return text[:n]
    return "<%d chars>" % len(text)


LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")
# Pages that may use the endpoint: games (RPG Maker MV/MZ in NW.js: chrome-extension:// or file://; a browser game
# from a local server) send these. XUnity and Ren'Py send no Origin at all. Not "null": any web page can send that
# (a sandboxed iframe), so it would open the door again.
LOCAL_ORIGIN = re.compile(r"^(file://.*|chrome-extension://.*|app://.*|nw://.*|"
                          r"https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?)$", re.I)


def allowed(headers):
    """The request comes from a game or a local tool, not from a web page in the user's browser. Without this, any
    site could drive the translator and fill the cache with its own lines while `lenslate serve` runs: the server
    answered every origin (Access-Control-Allow-Origin: *) and took text/plain POSTs. The Host check stops DNS
    rebinding (a site's own name pointed at 127.0.0.1)."""
    host = (headers.get("Host") or "").strip().lower()
    if host and host.rsplit(":", 1)[0] not in LOCAL_HOSTS and not host.startswith("[::1]"):
        return False
    origin = headers.get("Origin")
    if origin is not None:
        return bool(LOCAL_ORIGIN.match(origin.strip()))
    # no Origin: games and tools, but also a page's <img>/<script>/link to this address (browsers mark those)
    dest = headers.get("Sec-Fetch-Dest")
    site = headers.get("Sec-Fetch-Site")
    return not (dest and dest != "empty") and site in (None, "none", "same-origin")


def make_handler(svc):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _refuse(self):
            svc.log("refused a request from %s" % (self.headers.get("Origin") or self.headers.get("Host") or "?"))
            data = b"forbidden"
            self.send_response(403)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _reply(self, code, body, ctype="text/plain; charset=utf-8"):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            # games run as local web pages (RPG Maker MV/MZ: NW.js) and may only read answers that allow it
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            if not allowed(self.headers):
                return self._refuse()
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def _game(self, path):
            # /g/<game>/...: the game's name list (XUnity's Url carries it; plain /translate = global only)
            parts = [p for p in path.split("/") if p]
            return tf.nm.game_id(parts[1]) if len(parts) >= 3 and parts[0] == "g" else "unknown"

        def do_GET(self):
            if not allowed(self.headers):
                return self._refuse()
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
            if u.path in ("/", "/status"):
                return self._reply(200, json.dumps({"translator": svc.tr.label(), "queued": len(svc.pending),
                                                    **svc.stats}), "application/json")
            text = q.get("text", [""])[0]
            if not text:
                return self._reply(400, "missing text")
            try:
                tr = svc.translate(text, self._game(u.path), q.get("engine", [None])[0],
                                   q.get("kind", ["message"])[0], True)
            except Exception as e:  # noqa: BLE001 - one bad request must not stop the server
                svc.log("error: %r" % e)
                return self._reply(500, "translation failed")
            if tr is None:
                # an error status makes XUnity retry later instead of caching an untranslated line
                return self._reply(500, "no translation")
            self._reply(200, tr)

        def do_POST(self):
            """POST /g/<game>/batch  {"items": [{"text": .., "kind": ..}], "engine": "rpgm", "wait": false}
            -> {"out": [translation or null]}. Without wait, missing ones are translated in the background."""
            if not allowed(self.headers):
                return self._refuse()
            u = urllib.parse.urlparse(self.path)
            if not u.path.endswith("/batch"):
                return self._reply(404, "unknown")
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                game, engine, wait = self._game(u.path), req.get("engine"), bool(req.get("wait"))
                out = [svc.translate(it.get("text", ""), game, engine, it.get("kind", "text"), wait)
                       for it in req.get("items", [])]
            except Exception as e:  # noqa: BLE001
                svc.log("batch error: %r" % e)
                return self._reply(500, json.dumps({"error": str(e)}), "application/json")
            self._reply(200, json.dumps({"out": out}, ensure_ascii=False), "application/json; charset=utf-8")
    return H


def serve(here, cache_path, lang, url):
    port = cfgmod.get("hook.port")
    def log(msg):
        print(time.strftime("%H:%M:%S"), msg, flush=True)

    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), None)
    except OSError:
        print("lenslate serve: port %d already in use (already running?)" % port)
        return 0
    svc = Service(here, cache_path, lang, url, log)
    httpd.RequestHandlerClass = make_handler(svc)
    if svc.tr.mt is not None:
        svc.tr.warm()
    log("hook endpoint http://127.0.0.1:%d/translate  translator=%s  cached=%d" % (port, svc.tr.label(), len(svc.tr)))
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)

    def autosave():   # new translations reach the file within a few seconds even if nothing else arrives
        while True:
            time.sleep(5)
            with svc.lock:
                svc.tr.save()
    threading.Thread(target=autosave, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        svc.close()
    return 0


if __name__ == "__main__":
    sys.exit("run it as: lenslate serve")
