"""What this PC has, and whether a preset fits it (roadmap step 5: hardware check).

Used by the first-launch setup window and when a preset is picked. It only *warns*: the rule is that
nothing switches behind the user's back, so the GUI shows the problems and asks yes/no.

Graphics cards: NVIDIA through nvidia-smi; AMD through the amdgpu files in /sys (total and used VRAM);
Intel and other integrated graphics are found in /sys but have no memory of their own (they share RAM).
The language model runs through llama.cpp's Vulkan build, so AMD and Intel can run it; reading text on the
graphics card (Fastest preset, `ocr.gpu`) needs CUDA = NVIDIA only.
Pure standard library: no Qt, no numpy.
"""
import glob
import os
import shutil
import subprocess

import config as cfgmod

VENDORS = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}
GAME_ROOM_GB = 2.5      # GPU memory a typical game keeps for itself next to lenslate (rule of thumb, not measured)
OCR_GPU_ALL_GB = 1.6    # measured: finders + reader on the GPU (Fastest preset)
OCR_GPU_DL_GB = 3.4     # one-time CUDA runtime download for reading on the GPU
OCR_RAM_GB = 1.0        # OCR helper on the processor (models + buffers), rough


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _lspci_name(slot):
    if not slot or not shutil.which("lspci"):
        return None
    try:
        out = subprocess.run(["lspci", "-mm", "-s", slot], capture_output=True, text=True, timeout=3).stdout
        parts = out.split('"')
        return parts[5] if len(parts) > 5 else None   # "slot" "class" "vendor" "device" ...
    except (OSError, subprocess.SubprocessError):
        return None


def gpus():
    """Graphics cards: [{vendor, name, vram_mb, used_mb (None if unknown), dedicated}], biggest memory first."""
    found = []
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout
            for line in out.strip().splitlines():
                name, total, used = [x.strip() for x in line.split(",")]
                found.append({"vendor": "NVIDIA", "name": name, "vram_mb": int(total), "used_mb": int(used),
                              "dedicated": True})
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    seen_nvidia = any(g["vendor"] == "NVIDIA" for g in found)
    for dev in sorted(glob.glob("/sys/class/drm/card[0-9]*/device")):
        if "-" in os.path.basename(os.path.dirname(dev)):   # card1-DP-1 = a connector, not a card
            continue
        vendor = VENDORS.get(_read(os.path.join(dev, "vendor")) or "", "other")
        if vendor == "NVIDIA" and seen_nvidia:
            continue
        slot = None
        for line in (_read(os.path.join(dev, "uevent")) or "").splitlines():
            if line.startswith("PCI_SLOT_NAME="):
                slot = line.split("=", 1)[1]
        name = _lspci_name(slot) or "%s graphics" % vendor
        total = _read(os.path.join(dev, "mem_info_vram_total"))   # amdgpu only
        used = _read(os.path.join(dev, "mem_info_vram_used"))
        vram = int(total) // 2 ** 20 if total and total.isdigit() else 0
        # an AMD APU reports a small carve-out (e.g. 512 MB) as VRAM: count it as integrated
        found.append({"vendor": vendor, "name": name, "vram_mb": vram,
                      "used_mb": int(used) // 2 ** 20 if used and used.isdigit() else None,
                      "dedicated": vram >= 2048 or (vendor == "NVIDIA")})
    return sorted(found, key=lambda g: (g["dedicated"], g["vram_mb"]), reverse=True)


def ram_gb():
    """(total, available) in GB."""
    vals = {}
    for line in (_read("/proc/meminfo") or "").splitlines():
        k, _, v = line.partition(":")
        if v.strip().endswith("kB"):
            vals[k] = int(v.split()[0]) / 2 ** 20
    return vals.get("MemTotal", 0.0), vals.get("MemAvailable", 0.0)


def disk_free_gb(path=None):
    path = path or cfgmod.models_dir()
    while path and not os.path.exists(path):
        path = os.path.dirname(path)
    try:
        return shutil.disk_usage(path or "/").free / 2 ** 30
    except OSError:
        return None


def cpu_threads():
    return os.cpu_count() or 1


_SUMMARY = [0.0, None]   # (time, result): the settings window builds several things from it in one go


def summary(max_age=5.0):
    """Everything the setup window shows under "Your PC" (kept for a few seconds: each call runs nvidia-smi and
    reads /proc, ~25 ms, and one page build used to ask about ten times)."""
    import time
    if _SUMMARY[1] is not None and time.time() - _SUMMARY[0] < max_age:
        return _SUMMARY[1]
    _SUMMARY[1] = _summary()
    _SUMMARY[0] = time.time()
    return _SUMMARY[1]


def _summary():
    total, avail = ram_gb()
    cpu = "unknown processor"
    for line in (_read("/proc/cpuinfo") or "").splitlines():
        if line.startswith("model name"):
            cpu = line.split(":", 1)[1].strip()
            break
    return {"cpu": cpu, "threads": cpu_threads(), "ram_gb": total, "ram_free_gb": avail, "gpus": gpus(),
            "disk_free_gb": disk_free_gb()}


def best_gpu(info=None):
    g = (info or summary())["gpus"]
    return g[0] if g else None


# ------------------------------------------------------------------------------------------- what a preset needs
def language_models(sources=None, target=None, kind="mt"):
    """Processor models the chosen languages need (quickmt pairs, OPUS for Brazilian Portuguese, Sugoi)."""
    import langs
    from textflow import mt_route
    sources = langs.sources(sources if sources is not None else cfgmod.get("translator.sources"))
    target = langs.TARGET_CODES.get((target or cfgmod.get("translator.language")).lower(), "en")
    need = []
    for src in sorted(sources):
        for m in mt_route(kind, src, target):
            if m and m not in need:
                need.append(m)
    return need


AUTO_LLMS = ("gemma-4-e2b", "plamo-3-translate-0.8b")   # the language models the setup picks by itself


def pick_llm(sources=None, target=None):
    """(catalog name, reason): the language model for these languages. PLaMo 3 Translate 0.8B when Japanese is the
    only language to translate and the target is English (most natural dialogue in tests, 0.5 GB of GPU memory);
    Gemma 4 E2B for everything else (PLaMo has no Portuguese, is weaker into Spanish / Chinese, and knows no Korean
    or Russian). Rule since 2026-11-13."""
    import langs
    src = langs.sources(sources if sources is not None else cfgmod.get("translator.sources"))
    tgt = langs.TARGET_CODES.get((target or cfgmod.get("translator.language")).lower(), "en")
    if tgt == "en" and src - {"en"} == {"ja"}:
        return "plamo-3-translate-0.8b", "Japanese into English: the most natural dialogue, little GPU memory"
    return "gemma-4-e2b", "handles every language you chose"


def preset_needs(name, sources=None, target=None, llm=None):
    """{"vram_gb", "ram_gb", "models": [catalog names], "ocr_gpu": bool, "nvidia": bool}. llm = the language model
    to count instead of the configured one (the setup window's pick)."""
    import models
    v = cfgmod.values_of(name)
    kind = v["translator.kind"]
    need = {"vram_gb": 0.0, "ram_gb": OCR_RAM_GB, "models": [], "ocr_gpu": False, "nvidia": False}
    if kind == "llm":
        m = models.find(llm or v.get("translator.llm_model") or cfgmod.get("translator.llm_model"))
        if m is not None:            # a model of the user's own (Ollama): its size is not known here
            need["models"].append(m.name)
            need["vram_gb"] += m.vram_gb or 0
        else:
            need["custom_model"] = v.get("translator.llm_model")
    elif kind != "online":
        need["models"] += language_models(sources, target, kind)
        if kind == "sugoi":   # Visual novel mode: menus still go to quickmt
            for extra in language_models(sources, target, "mt"):
                if extra not in need["models"]:
                    need["models"].append(extra)
        need["ram_gb"] += sum(models.BY_NAME[m].ram_gb or 0.5 for m in need["models"])
    if v.get("ocr.gpu") == "all":
        need["vram_gb"] += OCR_GPU_ALL_GB
        need["ocr_gpu"] = need["nvidia"] = True
        need["ram_gb"] -= OCR_RAM_GB * 0.5
    return need


def missing_downloads(name, sources=None, target=None, llm=None):
    """[(label, GB)] still to download for this preset."""
    import models
    import ocrgpu
    need = preset_needs(name, sources, target, llm)
    out = [(models.BY_NAME[m].title, models.BY_NAME[m].size_gb) for m in need["models"]
           if not models.BY_NAME[m].installed()]
    if need["ocr_gpu"] and not ocrgpu.installed():
        out.append(("Reading on the graphics card (CUDA runtime)", OCR_GPU_DL_GB))
    return out


def check(name, info=None, sources=None, target=None, downloads=True, llm=None):
    """Problems with this preset on this PC: [text]. Empty = fits. Never changes anything."""
    import langs
    info = info or summary()
    need = preset_needs(name, sources, target, llm)
    g = best_gpu(info)
    out = []
    src = langs.sources(sources if sources is not None else cfgmod.get("translator.sources"))
    if cfgmod.PRESETS.get(name, {}).get("values", {}).get("translator.kind") == "mt" and src & set(langs.OWN_READER):
        out.append("It translates on the processor: for Korean and Russian that translator is literal and weak on "
                   "lone words (menus come from the ready-made lists); the language model reads more naturally.")
    if need["nvidia"] and not (g and g["vendor"] == "NVIDIA"):
        out.append("It reads text on the graphics card, which needs an NVIDIA card; none was found (the processor would read instead).")
    if need["vram_gb"]:
        if not g or not g["dedicated"]:
            out.append("It needs a graphics card with its own memory (about %.1f GB). This PC has %s: the language "
                       "model would run on the processor instead, about 1-3 s per line."
                       % (need["vram_gb"], ("only integrated %s graphics" % g["vendor"]) if g else "no graphics card"))
        else:
            total = g["vram_mb"] / 1024
            if total < need["vram_gb"] + GAME_ROOM_GB:
                out.append("It needs about %.1f GB of GPU memory; your %s has %.1f GB in total, which leaves little "
                           "for a game (games often need %.1f GB or more). A game may stutter, or lenslate may be "
                           "pushed onto the processor (slow)." % (need["vram_gb"], g["name"], total, GAME_ROOM_GB))
            elif g["used_mb"] is not None and (g["vram_mb"] - g["used_mb"]) / 1024 < need["vram_gb"] + 0.3:
                out.append("Right now only %.1f GB of GPU memory is free (another program, maybe a game, is using "
                           "it); this preset needs about %.1f GB. It will work once that program is closed."
                           % ((g["vram_mb"] - g["used_mb"]) / 1024, need["vram_gb"]))
    if info["ram_gb"] and info["ram_gb"] < need["ram_gb"] + 4:
        out.append("It uses about %.1f GB of memory (RAM); this PC has %.0f GB in total, so a game and lenslate "
                   "together may run short." % (need["ram_gb"], info["ram_gb"]))
    if downloads:
        dl = sum(gb for _t, gb in missing_downloads(name, sources, target, llm))
        free = info.get("disk_free_gb")
        if dl and free is not None and free < dl + 1:
            out.append("It needs %.1f GB of downloads, but only %.1f GB of disk space is free." % (dl, free))
    if cfgmod.values_of(name).get("ocr.reading") == "ultrafast":
        src = langs.sources(sources if sources is not None else cfgmod.get("translator.sources"))
        if "ja" not in src:
            out.append("Its reader (meikiocr) only reads Japanese; your source languages would be read badly. "
                       "Light reads every language.")
        elif "zh" in src:
            out.append("Its reader (meikiocr) only reads Japanese: Chinese text is read wrong (English is read by "
                       "the normal reader). Light reads every language.")
    if cfgmod.values_of(name)["translator.kind"] == "sugoi":
        src = langs.sources(sources if sources is not None else cfgmod.get("translator.sources"))
        tgt = (target or cfgmod.get("translator.language"))
        if "ja" not in src:
            out.append("Its dialogue translator (Sugoi) only knows Japanese; your languages would all use the "
                       "plain processor translator, the same as Light.")
        elif tgt != "English":
            out.append("Sugoi translates Japanese into English only; for %s each line is then translated again "
                       "on the processor (a little slower, wording a bit stiffer)." % tgt)
    return out


def recommend(info=None, sources=None, target=None, llm=None):
    """(preset, reason). A suggestion only: the user picks. llm = the language model that would be used (its GPU
    memory decides whether it fits next to a game; Gemma's 1.7 GB when not given)."""
    import models
    info = info or summary()
    g = best_gpu(info)
    m = models.find(llm) if llm else None
    vram = (m.vram_gb if m is not None and m.vram_gb else 1.7)
    if g and g["dedicated"] and g["vram_mb"] / 1024 >= vram + GAME_ROOM_GB + 1.5:
        return "balanced", ("your %s has %.0f GB of memory: enough for the language model next to a game"
                            % (g["name"], g["vram_mb"] / 1024))
    why = ("your %s has only %.0f GB of memory, which a game needs" % (g["name"], g["vram_mb"] / 1024)
           if g and g["dedicated"] else "no graphics card with its own memory was found")
    return "nogpu", why + "; No GPU runs everything on the processor"


if __name__ == "__main__":   # quick look: python3 hwcheck.py
    import json
    s = summary()
    print(json.dumps(s, indent=1))
    print("recommend:", recommend(s))
    for n in cfgmod.PRESET_ORDER:
        print(n, preset_needs(n), check(n, s) or "fits")
