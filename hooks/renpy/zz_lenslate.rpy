# lenslate - live translation for Ren'Py games (installed by `lenslate hook install`; remove with
# `lenslate hook remove`). Dialogue and menu choices are sent to lenslate's local translation server
# (`lenslate serve`, 127.0.0.1, nothing leaves the computer) and shown translated. Other on-screen text (names,
# buttons) uses translations lenslate already has. In the background the whole script is queued for
# translation, so later lines appear instantly. If lenslate is not running the game stays in its language.
# Works with Ren'Py 7 (Python 2) and Ren'Py 8 (Python 3).

init -999 python:
    import json as _ls_json
    import threading as _ls_threading
    import time as _ls_time
    import re as _ls_re
    try:
        from urllib.request import urlopen as _ls_urlopen, Request as _ls_Request
        from urllib.parse import quote as _ls_quote
    except ImportError:
        from urllib2 import urlopen as _ls_urlopen, Request as _ls_Request
        from urllib import quote as _ls_quote

    _ls_base = "http://127.0.0.1:__LENSLATE_PORT__/g/__LENSLATE_GAME__"
    _ls_jp = _ls_re.compile(u"__LENSLATE_SRC__")   # scripts of the languages lenslate translates (config sources)
    _ls_memo = {}
    _ls_state = {"down": 0.0}

    def _ls_text(s):
        try:
            return s if isinstance(s, unicode) else s.decode("utf-8")   # Python 2
        except NameError:
            return s

    def _ls_get(text, kind):
        if _ls_time.time() < _ls_state["down"]:
            return None
        url = _ls_base + "/translate?engine=renpy&kind=" + kind + "&text=" + _ls_quote(text.encode("utf-8"))
        try:
            return _ls_text(_ls_urlopen(url, timeout=120).read().decode("utf-8"))
        except Exception as e:
            if "Connection refused" in str(e) or "urlopen error" in str(e):
                _ls_state["down"] = _ls_time.time() + 30      # lenslate not running: stop asking for 30 s
            return None

    def _ls_batch(texts, kind, wait=False):
        if not texts or _ls_time.time() < _ls_state["down"]:
            return [None] * len(texts)
        body = _ls_json.dumps({"items": [{"text": t, "kind": kind} for t in texts], "engine": "renpy", "wait": wait})
        try:
            req = _ls_Request(_ls_base + "/batch", body.encode("utf-8"), {"Content-Type": "text/plain"})
            return _ls_json.loads(_ls_urlopen(req, timeout=30).read().decode("utf-8"))["out"]
        except Exception:
            _ls_state["down"] = _ls_time.time() + 30
            return [None] * len(texts)

    def _ls_translate(s, kind="message"):
        s = _ls_text(s)
        if not s or not _ls_jp.search(s):
            return s
        key = (kind, s)
        if key not in _ls_memo:
            out = _ls_get(s, kind)
            if out is None:
                return s
            _ls_memo[key] = out
        return _ls_memo[key]

    # dialogue and menu choices: translated before they are shown (waits for the model on a new line)
    _ls_prev_filter = config.say_menu_text_filter
    def _ls_say_filter(s):
        if _ls_prev_filter:
            s = _ls_prev_filter(s)
        return _ls_translate(s, "message")
    config.say_menu_text_filter = _ls_say_filter

    # everything else on screen (character names, buttons, screens): only translations lenslate already has
    _ls_ui = {}
    _ls_prev_replace = config.replace_text
    def _ls_replace(s):
        if _ls_prev_replace:
            s = _ls_prev_replace(s)
        if not _ls_jp.search(s):
            return s
        hit = _ls_ui.get(s)
        if hit is None or (hit[0] is None and _ls_time.time() - hit[1] > 10):
            out = _ls_batch([s], "text")[0]
            hit = (out, _ls_time.time())
            _ls_ui[s] = hit
        return hit[0] if hit[0] is not None else s
    config.replace_text = _ls_replace

    # background: queue every line the player can see in the current language, so lenslate translates ahead

    def _ls_walk(block, out):
        import renpy.ast as _ast
        for node in block or []:
            if isinstance(node, _ast.Say) and node.what:
                out.append(node.what)
            elif isinstance(node, _ast.Menu):
                for item in node.items:
                    if item[0]:
                        out.append(item[0])
                    if len(item) > 2 and isinstance(item[2], list):
                        _ls_walk(item[2], out)
            elif isinstance(node, _ast.If):
                for entry in node.entries:
                    _ls_walk(entry[1], out)
            elif isinstance(getattr(node, "block", None), list):
                _ls_walk(node.block, out)

    def _ls_prefetch():
        try:
            lang = renpy.game.preferences.language or config.language
            tr = renpy.game.script.translator
            dialogue, strings = [], []
            if lang:
                for (ident, l), t in list(tr.language_translates.items()):
                    if l == lang:
                        _ls_walk(t.block, dialogue)
                st = tr.strings.get(lang)
                if st is not None:
                    strings = list(st.translations.values())
            if not dialogue:   # untranslated game (the usual case): the script itself
                for node in list(renpy.game.script.namemap.values()):
                    _ls_walk([node], dialogue)
            seen, uniq = set(), []
            for t in dialogue + strings:
                if t and t not in seen and _ls_jp.search(t):
                    seen.add(t)
                    uniq.append(t)
            for i in range(0, len(uniq), 200):
                _ls_batch(uniq[i:i + 200], "message")
                _ls_time.sleep(0.2)
        except Exception as e:
            print("lenslate prefetch: %r" % (e,))

    def _ls_start_prefetch():
        t = _ls_threading.Thread(target=_ls_prefetch)
        t.daemon = True
        t.start()
    config.start_callbacks.append(_ls_start_prefetch)
