"""`lenslate hook ...`: put lenslate inside a game so it translates the game's own text (no screen reading).

    lenslate hook status GAME_FOLDER        which engine, is the hook installed
    lenslate hook install GAME_FOLDER       install the hook (backs up every file it changes)
    lenslate hook remove GAME_FOLDER        undo it
    lenslate hook pretranslate GAME_FOLDER  translate all the game's text now, so it shows instantly while playing

Engines:
    rpgm-mv / rpgm-mz  plugin js/plugins/Lenslate.js + one line in js/plugins.js; pre-translation reads data/*.json
    unity              XUnity.AutoTranslator pointed at lenslate's server; BepInEx + XUnity are downloaded and
                       installed first when missing (unityloader.py: Mono and IL2CPP games)
While playing, the hook talks to `lenslate serve` (started by hand, or by a game launcher that supports it).
"""
import json
import os
import re
import shutil
import time

import config as cfgmod
import names as nm
import rpgm

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = ".lenslate-hook"     # in the game folder: which hook is installed (a launcher can start the server for it)
GENERIC_EXE = {"game", "nw", "launcher", "start", "play", "config", "setup", "settings", "editor"}


def game_id(folder):
    """Name-list / cache id of a game: its exe name, or the folder name when the exe is generic (Game.exe)."""
    folder = os.path.abspath(folder)
    exes = [f for f in os.listdir(folder) if f.lower().endswith(".exe") and "crash" not in f.lower()
            and not f.lower().startswith(("unins", "notification_helper")) and "mtool" not in f.lower()]
    for e in exes:
        if nm.game_id(e) not in GENERIC_EXE:
            return nm.game_id(e)
    return nm.game_id(os.path.basename(folder.rstrip("/")))


def detect(folder):
    eng = rpgm.engine(folder)
    if eng:
        return "rpgm-" + eng
    if os.path.isdir(os.path.join(folder, "BepInEx")) or any(n.endswith("_Data") for n in os.listdir(folder)):
        return "unity"
    if os.path.isdir(os.path.join(folder, "renpy")) or os.path.isdir(os.path.join(folder, "game")) and \
            any(f.endswith((".rpa", ".rpyc", ".rpy")) for f in os.listdir(os.path.join(folder, "game"))):
        return "renpy"
    if os.path.exists(os.path.join(folder, "Data.wolf")) or os.path.isdir(os.path.join(folder, "Data")) and \
            os.path.exists(os.path.join(folder, "Game.ini")) and not os.path.exists(os.path.join(folder, "Game.rgss3a")):
        return "wolf"
    if any(os.path.exists(os.path.join(folder, f)) for f in ("Game.rgss3a", "Game.rgss2a", "Game.rgssad")):
        return "rpgm-vxace"
    return None


SUPPORTED = ("rpgm-mv", "rpgm-mz", "unity", "renpy")


def _backup(path):
    b = path + ".lenslate-backup"
    if os.path.exists(path) and not os.path.exists(b):
        shutil.copy2(path, b)


def _restore(path):
    b = path + ".lenslate-backup"
    if os.path.exists(b):
        os.replace(b, path)
        return True
    return False


def _mark(folder, data):
    with open(os.path.join(folder, MARK), "w") as f:
        json.dump(data, f)


def status(folder):
    eng = detect(folder)
    try:
        mark = json.load(open(os.path.join(folder, MARK)))
    except (OSError, ValueError):
        mark = None
    return {"engine": eng, "game": game_id(folder), "installed": bool(mark), "mark": mark,
            "supported": eng in SUPPORTED, "loader_off": eng == "unity" and loader_disabled(folder),
            "unity": _unity_state(folder) if eng == "unity" else None}


def _unity_state(folder):
    import unityloader
    st = unityloader.state(folder)
    try:
        st["missing"] = unityloader.needed(folder)
    except RuntimeError as e:
        st["missing"], st["problem"] = [], str(e)
    return st


# ------------------------------------------------------------------------------------------- RPG Maker MV/MZ
PLUGIN_LINE = '{"name":"Lenslate","status":true,"description":"Translates the game\'s text with lenslate (local)","parameters":{}}'


def _install_rpgm(folder, game):
    jd = rpgm.js_dir(folder)
    os.makedirs(os.path.join(jd, "plugins"), exist_ok=True)
    src = open(os.path.join(HERE, "hooks", "rpgm", "Lenslate.js"), encoding="utf-8").read()
    src = src.replace("__LENSLATE_GAME__", game).replace("__LENSLATE_PORT__", str(cfgmod.get("hook.port")))
    import langs
    src = src.replace("__LENSLATE_SRC__", langs.client_regex(langs.sources(cfgmod.get("translator.sources"))))
    with open(os.path.join(jd, "plugins", "Lenslate.js"), "w", encoding="utf-8") as f:
        f.write(src)
    pj = os.path.join(jd, "plugins.js")
    text = open(pj, encoding="utf-8-sig").read()
    if '"name":"Lenslate"' not in text:
        _backup(pj)
        # last entry of the $plugins array: add ours after it (it must load last, after every other plugin)
        i = text.rstrip().rfind("];")
        if i < 0:
            raise RuntimeError("js/plugins.js has an unexpected format; not changed")
        head = text[:i].rstrip()
        sep = "," if head.rstrip().endswith("}") else ""
        text = head + sep + "\n" + PLUGIN_LINE + "\n" + text[i:]
        with open(pj, "w", encoding="utf-8") as f:
            f.write(text)


def _remove_rpgm(folder):
    jd = rpgm.js_dir(folder)
    pj = os.path.join(jd, "plugins.js")
    if not _restore(pj) and os.path.exists(pj):
        text = open(pj, encoding="utf-8-sig").read()
        text = re.sub(r",?\s*\{\"name\":\"Lenslate\"[^\n]*\}\s*(?=\n)", "", text)
        open(pj, "w", encoding="utf-8").write(text)
    p = os.path.join(jd, "plugins", "Lenslate.js")
    if os.path.exists(p):
        os.remove(p)


# ------------------------------------------------------------------------------------------------- Unity
def _xunity_ini(folder):
    for p in (os.path.join(folder, "BepInEx", "config", "AutoTranslatorConfig.ini"),
              os.path.join(folder, "AutoTranslator", "Config.ini")):
        if os.path.exists(os.path.dirname(p)):
            return p
    return None


def _doorstop(folder):
    """BepInEx's loader settings file, or None."""
    p = os.path.join(folder, "doorstop_config.ini")
    return p if os.path.exists(p) else None


def loader_disabled(folder):
    """BepInEx is installed but switched off (doorstop enabled = false): no plugin, so no hook, loads."""
    p = _doorstop(folder)
    if not p:
        return False
    return bool(re.search(r"^\s*enabled\s*=\s*false\s*$", open(p, encoding="utf-8-sig", errors="ignore").read(), re.M | re.I))


def _install_unity(folder, game, progress=print):
    import unityloader
    got = unityloader.install(folder, progress)
    if got:
        progress("installed: %s" % ", ".join(got))
    if loader_disabled(folder):        # switched off earlier (e.g. for screen-reading tests): switch it back on
        p = _doorstop(folder)
        text = open(p, encoding="utf-8-sig", errors="ignore").read()
        with open(p, "w", encoding="utf-8") as f:
            f.write(re.sub(r"^(\s*enabled\s*=\s*)false(\s*)$", r"\1true\2", text, flags=re.M | re.I))
    ini = _xunity_ini(folder) or os.path.join(folder, "BepInEx", "config", "AutoTranslatorConfig.ini")
    os.makedirs(os.path.dirname(ini), exist_ok=True)
    _backup(ini)
    text = open(ini, encoding="utf-8-sig").read() if os.path.exists(ini) else ""
    url = "http://127.0.0.1:%d/g/%s/translate" % (cfgmod.get("hook.port"), game)
    nl = "\r\n" if "\r\n" in text else "\n"

    def setval(text, section, key, value):
        sec = re.search(r"^\[%s\]\s*$" % re.escape(section), text, re.M)
        if not sec:
            return text.rstrip() + "%s%s[%s]%s%s=%s%s" % (nl, nl, section, nl, key, value, nl)
        end = re.search(r"^\[", text[sec.end():], re.M)
        body_end = sec.end() + (end.start() if end else len(text) - sec.end())
        body = text[sec.end():body_end]
        if re.search(r"^%s=" % re.escape(key), body, re.M):
            body = re.sub(r"^%s=.*$" % re.escape(key), "%s=%s" % (key, value), body, flags=re.M)
        else:
            body = nl + "%s=%s" % (key, value) + body
        return text[:sec.end()] + body + text[body_end:]
    for sec, key, val in (("Service", "Endpoint", "CustomTranslate"), ("Service", "FallbackEndpoint", ""),
                          ("General", "Language", "en"), ("General", "FromLanguage", "ja"), ("Custom", "Url", url)):
        text = setval(text, sec, key, val)
    with open(ini, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _remove_unity(folder):
    ini = _xunity_ini(folder)
    if ini:
        if not _restore(ini) and os.path.exists(os.path.join(folder, ".lenslate-loader")):
            os.remove(ini)       # we created it (fresh XUnity install): the loader files go below
    import unityloader
    unityloader.remove(folder)


# ------------------------------------------------------------------------------------------------- Ren'Py
def _renpy_game_dir(folder):
    d = os.path.join(folder, "game")
    if not os.path.isdir(d):
        raise RuntimeError("no game/ folder in this Ren'Py game")
    return d


def _install_renpy(folder, game):
    src = open(os.path.join(HERE, "hooks", "renpy", "zz_lenslate.rpy"), encoding="utf-8").read()
    src = src.replace("__LENSLATE_GAME__", game).replace("__LENSLATE_PORT__", str(cfgmod.get("hook.port")))
    import langs
    src = src.replace("__LENSLATE_SRC__", langs.client_regex(langs.sources(cfgmod.get("translator.sources"))))
    with open(os.path.join(_renpy_game_dir(folder), "zz_lenslate.rpy"), "w", encoding="utf-8") as f:
        f.write(src)


def _remove_renpy(folder):
    d = os.path.join(folder, "game")
    for f in ("zz_lenslate.rpy", "zz_lenslate.rpyc"):
        p = os.path.join(d, f)
        if os.path.exists(p):
            os.remove(p)


# ------------------------------------------------------------------------------------------------ commands
def install(folder):
    folder = os.path.abspath(os.path.expanduser(folder))
    eng, game = detect(folder), game_id(folder)
    if eng in ("rpgm-mv", "rpgm-mz"):
        _install_rpgm(folder, game)
    elif eng == "unity":
        _install_unity(folder, game)
    elif eng == "renpy":
        _install_renpy(folder, game)
    else:
        raise RuntimeError("no hook for this game yet (engine: %s). Use the screen overlay (lenslate select)." % (eng or "unknown"))
    _mark(folder, {"engine": eng, "game": game, "installed": time.strftime("%Y-%m-%d %H:%M")})
    return eng, game


def remove(folder):
    folder = os.path.abspath(os.path.expanduser(folder))
    eng = detect(folder)
    if eng in ("rpgm-mv", "rpgm-mz"):
        _remove_rpgm(folder)
    elif eng == "unity":
        _remove_unity(folder)
    elif eng == "renpy":
        _remove_renpy(folder)
    m = os.path.join(folder, MARK)
    if os.path.exists(m):
        os.remove(m)
    return eng


def pretranslate(folder, progress=print):
    """Translate every text of the game into lenslate's cache (same keys the hook will ask for)."""
    import textflow as tf
    folder = os.path.abspath(os.path.expanduser(folder))
    eng, game = detect(folder), game_id(folder)
    if eng not in ("rpgm-mv", "rpgm-mz"):
        raise RuntimeError("pre-translation is available for RPG Maker MV/MZ games (this one: %s)" % (eng or "unknown"))
    items = rpgm.extract(folder)
    keys, seen = [], set()
    for kind, raw in items:
        for k in rpgm.keys(raw, "message" if kind == "message" else kind):
            if k not in seen:
                seen.add(k)
                keys.append(k)
    t = tf.Translator(HERE, cfgmod.cache_path(), cfgmod.get("translator.language"), cfgmod.get("translator.llm_model"),
                      cfgmod.get("translator.ollama_url"), cfgmod.get("translator.kind"))
    t.set_game(game)
    if t.notice and t.missing_models(t.kind)[0]:   # the chosen translator's model is not downloaded
        progress("%s: %s" % (game, t.notice))
        t.stop()
        return 0, 0
    todo = [k for k in keys if t.get(k) is None]
    progress("%s (%s): %d texts, %d already translated, %d to do with %s"
             % (game, eng, len(keys), len(keys) - len(todo), len(todo), t.label()))
    t0, done, failed, last_save = time.time(), 0, 0, time.time()
    batch = 16 if t.kind in ("mt", "sugoi") else 1
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        res = t.translate_batch(part)
        for j, k in enumerate(part):
            if j in res:
                t.put(k, res[j])
                done += 1
            else:
                failed += 1
        if time.time() - last_save > 10:
            t.save()
            last_save = time.time()
        el = time.time() - t0
        left = (len(todo) - i - len(part)) * el / max(1, i + len(part))
        progress("\r  %d / %d  (%d failed)  %.0f s, about %.0f s left   " % (i + len(part), len(todo), failed, el, left), end="")
    t.save()
    t.stop()
    import llm
    llm.RUNNER.stop()
    progress("\ndone: %d translated, %d failed, %.0f s" % (done, failed, time.time() - t0))
    return done, failed


def cli(args):
    if len(args) < 2 or args[0] not in ("status", "install", "remove", "pretranslate"):
        print(__doc__.strip())
        return 1
    folder = os.path.abspath(os.path.expanduser(" ".join(args[1:])))
    if not os.path.isdir(folder):
        print("not a folder: %s" % folder)
        return 1
    try:
        if args[0] == "status":
            st = status(folder)
            print("engine: %s%s\ngame id: %s\nhook installed: %s" % (
                st["engine"] or "unknown", "" if st["supported"] else " (no hook yet: use the screen overlay)",
                st["game"], "yes (%s)" % st["mark"].get("installed") if st["installed"] else "no"))
            u = st.get("unity")
            if u:
                print("unity: %s %s, BepInEx %s, XUnity.AutoTranslator %s%s" % (
                    u["flavor"] or "?", u["arch"] or "?", u["bepinex"] or "not installed",
                    "installed" if u["xunity"] else "not installed",
                    ("; `lenslate hook install` downloads: " + ", ".join(u["missing"])) if u["missing"] else ""))
                if u.get("problem"):
                    print("problem: " + u["problem"])
            if st.get("loader_off"):
                print("warning: BepInEx is switched off in doorstop_config.ini (enabled = false), so the hook does "
                      "not load. `lenslate hook install` switches it back on.")
        elif args[0] == "install":
            eng, game = install(folder)
            print("hook installed (%s, game id %s). While playing, run `lenslate serve`." % (eng, game))
            if eng == "unity":
                print("Wine/Proton must load the game's winhttp.dll: set WINEDLLOVERRIDES=\"winhttp=n,b\" (in Steam's "
                      "launch options:  WINEDLLOVERRIDES=\"winhttp=n,b\" %command%)")
                import unityloader
                if unityloader.flavor(folder) == "il2cpp":
                    print("IL2CPP game: the first start takes a few minutes (BepInEx prepares the game once).")
            if eng.startswith("rpgm"):
                print("tip: `lenslate hook pretranslate \"%s\"` translates all text now, so it appears instantly." % folder)
        elif args[0] == "remove":
            print("hook removed (%s); changed files restored from their backups." % remove(folder))
        elif args[0] == "pretranslate":
            pretranslate(folder, progress=lambda *a, **k: print(*a, flush=True, **k))
    except RuntimeError as e:
        print("lenslate: %s" % e)
        return 1
    return 0
