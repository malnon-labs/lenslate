"""Model catalog and downloader for lenslate (`lenslate models ...`, and the GUI's download buttons).

CPU translation models (quickmt, Sugoi) are downloaded file by file straight from Hugging Face into the model
folder (config [paths] models): no account, no extra programs. Downloads resume after an interruption and are
only marked installed once every file is complete.

Language models (LLMs) are pulled through Ollama when it is installed. (A built-in runner that needs no Ollama
is the next step; see README.)
"""
import fcntl
import hashlib
import json
import os
import shutil
import time
import urllib.request

import config as cfgmod

HF = "https://huggingface.co"
UA = {"User-Agent": "lenslate-model-downloader"}

# Every download is pinned to one commit of its Hugging Face repository: a repository that is changed later (new
# weights under the same file name, or something worse) cannot change what lenslate installs. To move a model to a
# newer commit: put the new id here (https://huggingface.co/api/models/<repo> -> "sha"), test it, and add a line to
# CHANGELOG.md. A repository that is not listed falls back to "main" (unpinned) - tests/test_safety.py fails then.
REVISIONS = {
    "quickmt/quickmt-ja-en": "e9ae594ff322d95254d730867c6166b25fd2c704",
    "quickmt/quickmt-zh-en": "c27cc8024e01a047733a1e34796e2ab19d74b237",
    "quickmt/quickmt-en-es": "430b78899a30bf5a867dffd407c64b028bbaebf4",
    "quickmt/quickmt-en-zh": "f48b69e53866b717607b59f94350e9aae3ed021c",
    "quickmt/quickmt-en-pt": "3b4cf7a68fa57a195486da65e112b431b54360de",
    "ooeoeo/opus-mt-tc-big-en-pt-ct2-float16": "1b42ae200c9d9149b316a043b0b56874abcd62f8",
    "entai2965/sugoi-v4-ja-en-ctranslate2": "71d67eb8e73ec2f5aaefc0689e03a4eb843d3a2b",
    "unsloth/gemma-4-E2B-it-GGUF": "0314792d7f1f7e229411f620751375812bb9faf2",
    "HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive": "c09cdbcdb1fefad6d335809d445621b5f5ba0c6e",
    "pfnet/plamo-3-translate-0.8b-GGUF": "1cf96ae02133958a20074bfdfab76517bb737d00",
    "pfnet/plamo-3-translate-2b-GGUF": "4f672106b847200bfdc0f6af6c321cd94eba1aed",
    "tencent/Hy-MT2-1.8B-GGUF": "a0c709d9fac510f2c807aa3af52872340dc37a4a",
    "LiquidAI/LFM2-350M-ENJP-MT-GGUF": "889c88c3d3681b4f342ae210a1d2a1369aba0e10",
}


def revision(repo):
    return REVISIONS.get(repo, "main")


def file_url(repo, path):
    return "%s/%s/resolve/%s/%s" % (HF, repo, revision(repo), path)


class Model:
    def __init__(self, name, kind, title, about, size_gb, license, repo=None, files=(), ollama=None, ram_gb=None,
                 vram_gb=None, gguf=None, style=None, experimental=False):
        self.name, self.kind, self.title, self.about = name, kind, title, about
        self.size_gb, self.license, self.repo, self.files = size_gb, license, repo, list(files)
        self.ollama, self.ram_gb, self.vram_gb = ollama, ram_gb, vram_gb
        self.gguf = gguf                  # (Hugging Face repo, file) for the built-in runner
        self.style = style                # prompt format the model needs (None = lenslate's own prompt)
        self.experimental = experimental

    @property
    def gguf_path(self):
        return os.path.join(cfgmod.models_dir(), self.name, self.gguf[1]) if self.gguf else None

    def gguf_installed(self):
        return bool(self.gguf) and os.path.exists(os.path.join(cfgmod.models_dir(), self.name, ".complete"))

    @property
    def path(self):
        return os.path.join(cfgmod.models_dir(), self.name)

    def installed(self):
        if os.path.exists(os.path.join(self.path, ".complete")):
            return True
        return bool(self.ollama) and self.ollama in ollama_models()


CATALOG = [
    Model("quickmt-ja-en", "mt", "quickmt Japanese → English",
          "Small translation model on the processor. Fast (~25 ms a line), literal, no GPU memory. Good for menus, "
          "weaker on casual dialogue. Installed when Japanese is one of your languages.",
          0.41, "CC-BY-4.0", repo="quickmt/quickmt-ja-en",
          files=["config.json", "model.bin", "source_vocabulary.json", "target_vocabulary.json", "src.spm.model",
                 "tgt.spm.model"], ram_gb=0.5),
    Model("quickmt-zh-en", "mt", "quickmt Chinese → English",
          "Small translation model on the processor for Chinese (Simplified and Traditional) games. Fast, no GPU "
          "memory. Also the first step for Chinese → Spanish/Portuguese on the processor.",
          0.41, "CC-BY-4.0", repo="quickmt/quickmt-zh-en", files=["config.json", "model.bin", "source_vocabulary.json", "target_vocabulary.json", "src.spm.model", "tgt.spm.model"], ram_gb=0.5),
    Model("quickmt-en-es", "mt", "quickmt English → Spanish",
          "Small translation model on the processor: English games into Spanish, and the second step for "
          "Japanese/Chinese → Spanish (through English).",
          0.41, "CC-BY-4.0", repo="quickmt/quickmt-en-es", files=["config.json", "model.bin", "source_vocabulary.json", "target_vocabulary.json", "src.spm.model", "tgt.spm.model"], ram_gb=0.5),
    Model("quickmt-en-zh", "mt", "quickmt English → Chinese (Simplified)",
          "Small translation model on the processor: English games into Simplified Chinese, and the second step for "
          "Japanese → Chinese (through English).",
          0.41, "CC-BY-4.0", repo="quickmt/quickmt-en-zh", files=["config.json", "model.bin", "source_vocabulary.json", "target_vocabulary.json", "src.spm.model", "tgt.spm.model"], ram_gb=0.5),
    Model("quickmt-en-pt", "mt", "quickmt English → Portuguese",
          "Small translation model on the processor: English games into Portuguese, and the second step for "
          "Japanese/Chinese → Portuguese (through English). Writes European Portuguese (tu/tens); lenslate uses "
          "OPUS English → Portuguese (Brazil) instead for the Portuguese (Brazil) target.",
          0.41, "CC-BY-4.0", repo="quickmt/quickmt-en-pt", files=["config.json", "model.bin", "source_vocabulary.json", "target_vocabulary.json", "src.spm.model", "tgt.spm.model"], ram_gb=0.5),
    Model("opus-en-ptbr", "mt", "OPUS English → Portuguese (Brazil)",
          "Translation model on the processor (Helsinki-NLP opus-mt-tc-big-en-pt) set to write Brazilian Portuguese "
          "(você, configurações). English games into Portuguese, and the second step for Japanese/Chinese → "
          "Portuguese (through English). ~0.5 GB RAM, no GPU memory.",
          0.47, "CC-BY-4.0", repo="ooeoeo/opus-mt-tc-big-en-pt-ct2-float16",
          files=["config.json", "model.bin", "shared_vocabulary.json", "source.spm", "target.spm"], ram_gb=0.6),
    Model("sugoi-v4-ja-en", "sugoi", "Sugoi v4 Japanese → English",
          "Translation model trained on visual novels, on the processor (~50 ms a line), no GPU memory. Best "
          "CPU choice for dialogue, including adult content; poor on menus (turns labels into sentences).",
          1.10, "NTT non-commercial", repo="entai2965/sugoi-v4-ja-en-ctranslate2",
          files=["config.json", "model.bin", "source_vocabulary.json", "target_vocabulary.json",
                 "spm/spm.ja.nopretok.model", "spm/spm.en.nopretok.model"], ram_gb=1.1),
    Model("gemma-4-e2b", "llm", "Gemma 4 E2B (language model)",
          "Small general-purpose language model from Google. Best game translations in tests: natural wording, "
          "keeps names right, handles adult text, fixes OCR typos. ~0.15 s a line on the graphics card.",
          3.1, "Gemma terms of use", ollama="hf.co/unsloth/gemma-4-E2B-it-GGUF:Q4_K_M", vram_gb=1.7,
          gguf=("unsloth/gemma-4-E2B-it-GGUF", "gemma-4-E2B-it-Q4_K_M.gguf")),
    Model("qwen3.5-4b-uncensored", "llm", "Qwen3.5 4B uncensored (language model)",
          "Language model without the usual content filters: never softens adult lines. Fluent, sometimes "
          "misreads meaning. ~0.3 s a line on the graphics card.",
          2.7, "Apache-2.0", ollama="hf.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive:Q4_K_M", vram_gb=3.1,
          gguf=("HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive", "Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf")),
    Model("plamo-3-translate-0.8b", "llm", "PLaMo 3 Translate 0.8B (translation model)",
          "Small translation-only model from Preferred Networks, strongest between Japanese and English: the most "
          "natural dialogue in tests (2026-11-11), names right, adult text kept, ~0.05 s a line and only 0.5 GB of "
          "graphics-card memory (~0.35 s a line on the processor). Uses the name lists as its glossary. Weak "
          "points: does not correct misread characters the way Gemma does, lone English menu words into Spanish "
          "or Chinese are hit and miss, and it has no Portuguese.",
          0.57, "PLaMo Community License (free for personal and non-commercial use)", vram_gb=0.6,
          gguf=("pfnet/plamo-3-translate-0.8b-GGUF", "plamo-3-translate-0.8b-Q4_K_M.gguf"), style="plamo"),
    Model("plamo-3-translate-2b", "llm", "PLaMo 3 Translate 2B (translation model)",
          "The larger PLaMo 3 Translate: a little more natural than the 0.8B on Japanese dialogue, better on "
          "Spanish and Chinese, ~0.13 s a line, 1.8 GB of graphics-card memory. Same weak points (misread "
          "characters, no Portuguese).",
          1.81, "PLaMo Community License (free for personal and non-commercial use)", vram_gb=1.8,
          gguf=("pfnet/plamo-3-translate-2b-GGUF", "plamo-3-translate-2b-Q4_K_M.gguf"), style="plamo"),
    Model("hy-mt2-1.8b", "llm", "Hy-MT2 1.8B (translation model)",
          "Tencent's language model trained only for translation, 33 languages. ~0.12 s a line on the graphics "
          "card, ~1.2 s on the processor. Decent; garbles names more than Gemma. (Experimental: still being tested.)",
          1.1, "Apache-2.0", ollama="hf.co/tencent/Hy-MT2-1.8B-GGUF:Q4_K_M", vram_gb=1.3,
          gguf=("tencent/Hy-MT2-1.8B-GGUF", "Hy-MT2-1.8B-Q4_K_M.gguf"), style="hy-mt", experimental=True),
    Model("lfm2-350m-enjp", "llm", "LFM2 350M EN-JP (translation model)",
          "Tiny English/Japanese translation model (~0.3 s a line on the processor). Made things up in tests. "
          "(Experimental: still being tested.)",
          0.23, "LFM Open License", ollama="hf.co/LiquidAI/LFM2-350M-ENJP-MT-GGUF:Q4_K_M", vram_gb=0.3,
          gguf=("LiquidAI/LFM2-350M-ENJP-MT-GGUF", "LFM2-350M-ENJP-MT-Q4_K_M.gguf"), style="lfm2-mt", experimental=True),
    Model("qwen3-vl-4b", "llm", "Qwen3-VL 4B (language + image model)",
          "lenslate's first default. Can also read screenshots (the vlm screen-reading method). Softens adult "
          "lines and gets names wrong more often than Gemma.",
          3.3, "Apache-2.0", ollama="qwen3-vl:4b-instruct", vram_gb=3.3),
]
BY_NAME = {m.name: m for m in CATALOG}

# What each model translates, in one line: shown next to it in the setup window, on the Models page and in
# `lenslate models` (processor models do one language pair each; pairs not covered go through English).
_GENERAL = "Japanese, Chinese, Korean, Russian, English → English, Spanish, Portuguese (Brazil), Chinese"
CAN = {
    "quickmt-ja-en": "Japanese → English", "quickmt-zh-en": "Chinese → English",
    "quickmt-en-es": "English → Spanish", "quickmt-en-zh": "English → Chinese (Simplified)",
    "quickmt-en-pt": "English → Portuguese (Portugal)", "opus-en-ptbr": "English → Portuguese (Brazil)",
    "sugoi-v4-ja-en": "Japanese → English (dialogue)",
    "gemma-4-e2b": _GENERAL, "qwen3.5-4b-uncensored": _GENERAL, "qwen3-vl-4b": _GENERAL,
    "plamo-3-translate-0.8b": "Japanese ↔ English (its strength); English → Spanish, Chinese (weaker); no Portuguese",
    "plamo-3-translate-2b": "Japanese ↔ English; English → Spanish, Chinese; no Portuguese",
    "hy-mt2-1.8b": "33 languages, every source and target lenslate offers",
    "lfm2-350m-enjp": "English ↔ Japanese",
}
for _m in CATALOG:
    _m.can = CAN.get(_m.name, "")


def find(name):
    """Catalog entry by lenslate name or by its Ollama name (older configs store the Ollama name)."""
    return BY_NAME.get(name) or next((m for m in CATALOG if m.ollama and m.ollama == name), None)


# ------------------------------------------------------------------------------------------------- ollama
def _ollama_base():
    return cfgmod.get("translator.ollama_url").rsplit("/api/", 1)[0]


def ollama_running():
    try:
        urllib.request.urlopen(_ollama_base() + "/api/version", timeout=2).read()
        return True
    except (OSError, ValueError):
        return False


def ollama_models():
    try:
        with urllib.request.urlopen(_ollama_base() + "/api/tags", timeout=3) as r:
            return {m["name"] for m in json.load(r).get("models", [])}
    except (OSError, ValueError):
        return set()


def ollama_pull(name, progress):
    req = urllib.request.Request(_ollama_base() + "/api/pull", json.dumps({"model": name, "stream": True}).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        for line in r:
            msg = json.loads(line)
            if "error" in msg:
                raise RuntimeError(msg["error"])
            progress(msg.get("completed", 0), msg.get("total", 0), msg.get("status", ""))


# ------------------------------------------------------------------------------------------- hugging face
def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url, dest, progress, done_before, total, size=0, sha=None):
    """One file with resume (Range) into dest; progress(bytes_done_overall, total, status).
    size / sha (from the Hugging Face file list): the finished file must match them, or it is not kept. Only one
    download of a file runs at a time (two at once, e.g. the settings window and the setup window, appended to the
    same .part file and could leave a corrupt model marked as installed)."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    lock = open(dest + ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise RuntimeError("%s is already being downloaded (by another lenslate window)" % os.path.basename(dest))
    try:
        return _download_locked(url, dest, progress, done_before, total, size, sha)
    finally:
        lock.close()
        try:
            os.unlink(dest + ".lock")
        except OSError:
            pass


def _download_locked(url, dest, progress, done_before, total, size, sha):
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    headers = dict(UA)
    if have:
        headers["Range"] = "bytes=%d-" % have
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:   # server ignored the range: start over
            have = 0
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(part, "ab" if have else "wb") as f:
            last = 0.0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)
                now = time.time()
                if now - last > 0.2:
                    progress(done_before + have, total, os.path.basename(dest))
                    last = now
    if size and have != size:
        if have > size:   # not resumable: start over next time
            os.remove(part)
        raise RuntimeError("%s: download incomplete (%d of %d bytes); try again to resume"
                           % (os.path.basename(dest), have, size))
    if sha:
        progress(done_before + have, total, "checking " + os.path.basename(dest))
        if _sha256(part) != sha:
            os.remove(part)
            raise RuntimeError("%s: the downloaded file is damaged (checksum differs); try again"
                               % os.path.basename(dest))
    os.replace(part, dest)
    return have


def _tree(repo):
    """{path: (size, sha256 or None)} of a Hugging Face repo's files (large files carry their SHA-256)."""
    url = "%s/api/models/%s/tree/%s?recursive=true" % (HF, repo, revision(repo))
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return {f["path"]: (f.get("size", 0), (f.get("lfs") or {}).get("oid"))
                for f in json.load(r) if f.get("type") == "file"}


def _sizes_of(tree):
    return {p: v[0] for p, v in tree.items()}


def download(name, progress=None):
    """Install a model from the catalog. progress(done_bytes, total_bytes, status) is called as it goes."""
    m = BY_NAME[name]
    progress = progress or (lambda *a: None)
    builtin = m.kind == "llm" and m.gguf and cfgmod.get("translator.llm_backend") != "ollama"
    if (m.gguf_installed() if builtin else m.installed()):
        progress(1, 1, "already installed")
        return m
    if m.kind == "llm":
        if cfgmod.get("translator.llm_backend") == "ollama" or not m.gguf:
            if not ollama_running():
                raise RuntimeError("Ollama is not running (needed for %s)." % m.title)
            ollama_pull(m.ollama, progress)
            return m
        return _download_gguf(m, progress)
    tree = _tree(m.repo)
    sizes = _sizes_of(tree)
    total = sum(sizes.get(f, 0) for f in m.files)
    done = 0
    for f in m.files:
        dest = os.path.join(m.path, f)
        if os.path.exists(dest) and os.path.getsize(dest) == sizes.get(f, -1):
            done += sizes[f]
            continue
        url = file_url(m.repo, f)
        size, sha = tree.get(f, (0, None))
        _download(url, dest, progress, done, total, size=size, sha=sha)
        done += sizes.get(f, 0)
    open(os.path.join(m.path, ".complete"), "w").write(json.dumps({"repo": m.repo, "revision": revision(m.repo), "files": m.files}))
    progress(total, total, "done")
    return m


def _ollama_blob(name):
    """Path of the GGUF file Ollama already has for this model, or None."""
    if not name or not shutil.which("ollama") or name not in ollama_models():
        return None
    try:
        import subprocess
        out = subprocess.run(["ollama", "show", "--modelfile", name], capture_output=True, text=True, timeout=20).stdout
    except (OSError, ValueError):
        return None
    for line in out.splitlines():   # first FROM is the model, later ones are projectors (images)
        if line.startswith("FROM /") and os.path.isfile(line[5:].strip()):
            return line[5:].strip()
    return None


def _download_gguf(m, progress):
    import llm
    if not llm.server_binary():
        llm.install_runtime(progress)
    repo, fname = m.gguf
    dest = m.gguf_path
    os.makedirs(m.path, exist_ok=True)
    blob = _ollama_blob(m.ollama)
    tree = {}
    try:
        tree = _tree(repo)
    except (OSError, ValueError):
        pass
    sizes = _sizes_of(tree)
    size, sha = tree.get(fname, (0, None))
    same = (os.path.basename(blob).replace("sha256-", "").replace("sha256:", "") == sha) if (blob and sha) else \
        (blob and (not sizes.get(fname) or os.path.getsize(blob) == sizes[fname]))
    if blob and same:
        # Ollama already has this exact file: link to it instead of downloading it again
        if os.path.lexists(dest):
            os.remove(dest)
        os.symlink(blob, dest)
        progress(1, 1, "reused Ollama's copy")
    else:
        url = file_url(repo, fname)
        _download(url, dest, progress, 0, size, size=size, sha=sha)
    with open(os.path.join(m.path, ".complete"), "w") as f:
        json.dump({"repo": repo, "revision": revision(repo), "file": fname, "linked": bool(blob)}, f)
    return m


def remove(name):
    m = BY_NAME[name]
    if os.path.isdir(m.path):            # lenslate's own copy (or link)
        shutil.rmtree(m.path)
    elif m.ollama:
        req = urllib.request.Request(_ollama_base() + "/api/delete", json.dumps({"model": m.ollama}).encode(),
                                     {"Content-Type": "application/json"}, method="DELETE")
        urllib.request.urlopen(req, timeout=30).read()


def cli(args):
    if not args or args[0] == "list":
        ol = ollama_running()
        print("models (folder %s; Ollama %s):" % (cfgmod.models_dir(), "running" if ol else "not running"))
        for m in CATALOG:
            if os.path.exists(os.path.join(m.path, ".complete")):
                state = "installed"
            elif m.ollama and ol and m.ollama in ollama_models():
                state = "in Ollama"
            else:
                state = "-"
            mem = ("%.1f GB GPU" % m.vram_gb) if m.vram_gb else ("%.1f GB RAM" % m.ram_gb)
            print("  %-24s %-5s %5.1f GB download, %-11s %-12s %s" % (m.name, m.kind, m.size_gb, mem, state, m.title))
            if m.can:
                print("  %-24s can translate: %s" % ("", m.can))
        import llm
        info = llm.runtime_info()
        print("built-in runner: %s" % ("llama.cpp %s (%s)" % (info["build"], info["flavor"]) if info else
                                       "not installed (installed with the first language model, or: lenslate models runtime)"))
        print("usage: lenslate models get NAME | models get --needed | models pick | models use NAME | models remove NAME | models runtime")
        return 0
    if args[0] in ("get", "download") and args[1:] == ["--needed"]:
        # the processor translators the chosen languages need (the installer's base when no setup window opens)
        import hwcheck
        need = [n for n in hwcheck.language_models() if n and not BY_NAME[n].installed()]
        if not need:
            print("the processor translators for your languages are installed")
        for n in need:
            if cli(["get", n]):
                return 1
        return 0
    if args[0] == "pick":   # the language model for the configured languages (PLaMo for Japanese -> English)
        import hwcheck
        print(hwcheck.pick_llm()[0])
        return 0
    if args[0] == "use" and len(args) > 1:   # the language model to use (config.toml; no daemon needed)
        if args[1] not in BY_NAME or BY_NAME[args[1]].kind != "llm":
            print("not a language model: %r; see: lenslate models" % args[1])
            return 1
        cfgmod.set("translator.llm_model", args[1])
        print("language model: %s" % args[1])
        return 0
    if args[0] in ("get", "download") and len(args) > 1:
        if args[1] not in BY_NAME:
            print("unknown model %r; see: lenslate models" % args[1])
            return 1
        t0 = [time.time()]

        def show(done, total, status):
            if total:
                print("\r  %5.1f%%  %6.0f / %.0f MB  %-30s" % (100 * done / total, done / 1e6, total / 1e6, status[:30]),
                      end="", flush=True)
        download(args[1], show)
        print("\n%s installed (%.0f s)" % (args[1], time.time() - t0[0]))
        return 0
    if args[0] == "runtime":
        import llm
        info = llm.runtime_info()
        if info and "--reinstall" not in args:
            print("built-in runner installed: llama.cpp %s (%s) in %s" % (info["build"], info["flavor"], llm.RUNTIME_DIR))
            return 0
        flavor = llm.install_runtime(lambda d, t, s: t and print("\r  %5.1f%%  %s" % (100 * d / t, s), end="", flush=True))
        print("\nbuilt-in runner installed (%s)" % flavor)
        return 0
    if args[0] == "remove" and len(args) > 1:
        remove(args[1])
        print("%s removed" % args[1])
        return 0
    print("usage: lenslate models [list] | models get NAME | models remove NAME")
    return 1


def adopt_existing():
    """Models downloaded before the catalog existed (same folder names) count as installed."""
    for m in CATALOG:
        if m.ollama or m.installed() or not m.files:     # no file list (a GGUF-only model): nothing to recognise
            continue
        if all(os.path.exists(os.path.join(m.path, f)) for f in m.files):
            open(os.path.join(m.path, ".complete"), "w").write(json.dumps({"repo": m.repo, "adopted": True}))
