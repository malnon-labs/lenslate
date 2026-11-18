"""Install the Unity mod loader (BepInEx) and XUnity.AutoTranslator into a game, so its text can be hooked.

Unity games need two things for lenslate's hook: BepInEx (loads plugins into the game) and XUnity.AutoTranslator
(the plugin that catches the game's text and asks lenslate's server for translations). This downloads the right
pair for the game and copies it into the game folder:

    Mono games  (<Game>_Data/Managed)            BepInEx 5.4.23.6 (x64 or x86) + XUnity.AutoTranslator 5.6.3.1
    IL2CPP games (GameAssembly.dll, il2cpp_data) BepInEx 6 build 791 (x64)    + XUnity.AutoTranslator IL2CPP 5.6.3.1

Every download is pinned to a version and checked against its SHA-256. Files that were already in the game folder
are never overwritten (an existing BepInEx is reused). The list of added files is kept in .lenslate-loader so
`lenslate hook remove` can delete exactly those again.

On Linux the game runs under Wine/Proton, which must load the game's winhttp.dll (BepInEx's starter):
WINEDLLOVERRIDES="winhttp=n,b" (for Steam, put it in the launch options).
"""
import hashlib
import json
import os
import struct
import urllib.request
import zipfile

import config as cfgmod

GH = "https://github.com/"
PACKAGES = {
    "bepinex5-x64": (GH + "BepInEx/BepInEx/releases/download/v5.4.23.6/BepInEx_win_x64_5.4.23.6.zip",
                     "6c57a714a892efb4e9e1fef63d608a3391f30ec984031c465404e4ee381a0755"),
    "bepinex5-x86": (GH + "BepInEx/BepInEx/releases/download/v5.4.23.6/BepInEx_win_x86_5.4.23.6.zip",
                     "a4024dafaca5d3784097e34b3c2921415030c0b461e52f30053ed8914be9622d"),
    "bepinex6-il2cpp-x64": ("https://builds.bepinex.dev/projects/bepinex_be/791/"
                            "BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.791%2Bb782da4.zip",
                            "bb1c510909b69522733791f3a0817a487379a52da6468a492f1c9c19b3ec6f9a"),
    "xunity-mono": (GH + "bbepis/XUnity.AutoTranslator/releases/download/v5.6.3.1/"
                    "XUnity.AutoTranslator-BepInEx-5.6.3.1.zip",
                    "6c3ff03aafe9708f25c2115c0c04c255b6a9d88e716896ae7bacb590a8777609"),
    "xunity-il2cpp": (GH + "bbepis/XUnity.AutoTranslator/releases/download/v5.6.3.1/"
                      "XUnity.AutoTranslator-BepInEx-IL2CPP-5.6.3.1.zip",
                      "f1d4d3151a061edfcda815e4472fe1f1de8756bdc23708c9b5ebb9bfe736fb1f"),
}
SIZES_MB = {"bepinex5-x64": 0.6, "bepinex5-x86": 0.6, "bepinex6-il2cpp-x64": 34.3, "xunity-mono": 0.8,
            "xunity-il2cpp": 0.8}
CACHE = os.path.join(cfgmod.CACHE_DIR, "unity-loader")
LOADER_MARK = ".lenslate-loader"


def flavor(folder):
    """'il2cpp', 'mono' or None (not a Unity game)."""
    if os.path.exists(os.path.join(folder, "GameAssembly.dll")):
        return "il2cpp"
    for n in os.listdir(folder):
        if n.endswith("_Data") and os.path.isdir(os.path.join(folder, n)):
            if os.path.isdir(os.path.join(folder, n, "il2cpp_data")):
                return "il2cpp"
            if os.path.isdir(os.path.join(folder, n, "Managed")):
                return "mono"
    return None


def arch(folder):
    """'x64' or 'x86' from the game exe's header (the exe next to <Name>_Data)."""
    exes = [n[:-5] + ".exe" for n in os.listdir(folder) if n.endswith("_Data")]
    exes = [e for e in exes if os.path.exists(os.path.join(folder, e))] or \
        [n for n in os.listdir(folder) if n.lower().endswith(".exe") and "crash" not in n.lower()]
    for e in exes:
        try:
            with open(os.path.join(folder, e), "rb") as f:
                f.seek(0x3C)
                pe = struct.unpack("<I", f.read(4))[0]
                f.seek(pe + 4)
                machine = struct.unpack("<H", f.read(2))[0]
            return {0x8664: "x64", 0x14C: "x86"}.get(machine)
        except (OSError, struct.error):
            continue
    return None


def state(folder):
    """What is there: {'flavor', 'arch', 'bepinex': None|5|6, 'xunity': bool}."""
    core = os.path.join(folder, "BepInEx", "core")
    bep = None
    if os.path.isdir(core):
        bep = 6 if any(n.startswith("BepInEx.Unity.") or n == "BepInEx.Core.dll" for n in os.listdir(core)) else 5
    xu = os.path.isdir(os.path.join(folder, "BepInEx", "plugins", "XUnity.AutoTranslator")) or \
        os.path.isdir(os.path.join(folder, "AutoTranslator"))
    return {"flavor": flavor(folder), "arch": arch(folder), "bepinex": bep, "xunity": xu}


def needed(folder):
    """Package names to install (empty: nothing missing). Raises RuntimeError when it cannot be done."""
    st = state(folder)
    if st["flavor"] is None:
        raise RuntimeError("this does not look like a Unity game (no <Game>_Data folder)")
    out = []
    if st["bepinex"] is None:
        if st["flavor"] == "il2cpp":
            if st["arch"] != "x64":
                raise RuntimeError("32-bit IL2CPP Unity games are not supported by BepInEx 6 builds yet")
            out.append("bepinex6-il2cpp-x64")
        else:
            out.append("bepinex5-%s" % (st["arch"] or "x64"))
    if not st["xunity"]:
        il2cpp = st["bepinex"] == 6 or (st["bepinex"] is None and st["flavor"] == "il2cpp")
        out.append("xunity-il2cpp" if il2cpp else "xunity-mono")
    return out


def _fetch(name, progress):
    url, sha = PACKAGES[name]
    os.makedirs(CACHE, exist_ok=True)
    dest = os.path.join(CACHE, name + ".zip")
    if os.path.exists(dest) and _sha(dest) == sha:
        return dest
    progress("downloading %s" % url.rsplit("/", 1)[1].replace("%2B", "+"))
    req = urllib.request.Request(url, headers={"User-Agent": "lenslate"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest + ".part", "wb") as f:
        while True:
            b = r.read(1 << 16)
            if not b:
                break
            f.write(b)
    if _sha(dest + ".part") != sha:
        os.remove(dest + ".part")
        raise RuntimeError("download of %s did not match its checksum; nothing was installed" % name)
    os.replace(dest + ".part", dest)
    return dest


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _extract(zpath, folder, added):
    """Unpack into the game folder without overwriting anything that is already there."""
    root = os.path.realpath(folder)
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            target = os.path.realpath(os.path.join(root, info.filename))
            if not target.startswith(root + os.sep):
                continue                      # never write outside the game folder
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            if os.path.exists(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            added.append(os.path.relpath(target, root))


def install(folder, progress=print):
    """Install what is missing. Returns the package names installed (empty: already there)."""
    folder = os.path.abspath(folder)
    names = needed(folder)
    if not names:
        return []
    zips = [_fetch(n, progress) for n in names]       # all downloaded and checked before anything is copied
    mark = os.path.join(folder, LOADER_MARK)
    try:
        data = json.load(open(mark))
    except (OSError, ValueError):
        data = {"packages": [], "files": []}
    for n, z in zip(names, zips):
        progress("installing %s" % n)
        _extract(z, folder, data["files"])
        data["packages"].append(n)
    with open(mark, "w") as f:
        json.dump(data, f, indent=1)
    return names


def _inside(folder, p):
    """p (after following symlinks) is inside the game folder. The list of files to remove comes from the
    .lenslate-loader file in the game folder, which anything could have written: an entry like "../../x" or an
    absolute path, or a symlinked folder, must never make remove() delete the user's files elsewhere."""
    real, root = os.path.realpath(p), os.path.realpath(folder)
    return real != root and os.path.commonpath([real, root]) == root


def remove(folder):
    """Delete the files install() added (and folders left empty). Returns how many files were removed."""
    folder = os.path.abspath(folder)
    mark = os.path.join(folder, LOADER_MARK)
    try:
        data = json.load(open(mark))
    except (OSError, ValueError):
        return 0
    n = 0
    if any(p.startswith("bepinex") for p in data.get("packages", [])):
        import shutil       # what BepInEx itself generated after we installed it (only then: never the user's)
        for gen in ("cache", "interop", "unity-libs", "LogOutput.log", "ErrorLog.log", "config/BepInEx.cfg"):
            p = os.path.join(folder, "BepInEx", gen)
            if not _inside(folder, p):
                continue
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.isfile(p):
                os.remove(p)
    files = [rel for rel in data.get("files", []) if isinstance(rel, str) and not os.path.isabs(rel)
             and _inside(folder, os.path.join(folder, rel))]
    for rel in files:
        p = os.path.join(folder, rel)
        if os.path.isfile(p) or os.path.islink(p):
            os.remove(p)
            n += 1
    # folders the loader made (and its generated config/cache/logs) - only if nothing of the user's is left in them
    for d in sorted({os.path.dirname(r) for r in files if os.path.dirname(r)}, key=len, reverse=True):
        p = os.path.join(folder, d)
        while p != folder and _inside(folder, p) and os.path.isdir(p) and not os.listdir(p):
            os.rmdir(p)
            p = os.path.dirname(p)
    if any(p.startswith("bepinex") for p in data.get("packages", [])):
        for top in ("BepInEx", "dotnet"):        # empty folders left of the loader we installed
            if not _inside(folder, os.path.join(folder, top)) or os.path.islink(os.path.join(folder, top)):
                continue
            for dirpath, _dirs, _files in sorted(os.walk(os.path.join(folder, top)), key=lambda w: -len(w[0])):
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
    os.remove(mark)
    return n
