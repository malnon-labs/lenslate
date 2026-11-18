"""All lenslate settings in one place: ~/.config/lenslate/config.toml.

Every setting is declared once in SCHEMA with its default, type, environment-variable override and a plain
description. The description is written into the file as a comment above the value and is what the GUI shows
when the mouse hovers over that setting, so the two never disagree.

Priority: environment variable (for testing) > config.toml > default.
Hand edits are picked up while lenslate runs (the daemon checks the file's time every 2 s).
Pure standard library (tomllib), so helper processes in other environments can use it too.
"""
import os
import tomllib

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "lenslate")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.toml")
DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "lenslate")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "lenslate")


class S:
    def __init__(self, key, default, env, label, help, choices=None, lo=None, hi=None, aliases=None):
        self.key, self.default, self.env, self.label, self.help = key, default, env, label, help
        self.choices, self.lo, self.hi = choices, lo, hi
        self.aliases = aliases or {}     # old values -> current ones (a setting that changed type)
        self.type = type(default)

    def parse(self, v):
        key = str(v).strip().lower() if isinstance(v, (bool, str, int)) else None
        if key in self.aliases:
            v = self.aliases[key]
        if self.type is bool:
            if isinstance(v, str):
                return v.strip().lower() in ("1", "true", "yes", "on")
            return bool(v)
        v = self.type(v)
        if self.lo is not None:
            v = max(self.lo, v)
        if self.hi is not None:
            v = min(self.hi, v)
        if self.choices and v not in self.choices:
            raise ValueError("%s must be one of %s" % (self.key, ", ".join(map(str, self.choices))))
        return v


SECTIONS = {
    "general": "The preset: several settings chosen together.",
    "translator": "Who translates the text, and how.",
    "overlay": "How the translation cards look.",
    "refresh": "When lenslate looks at the screen again.",
    "ocr": "Reading text from the screen.",
    "hook": "Hook mode: games that hand their text to lenslate directly (no screen reading).",
    "paths": "Where lenslate keeps its files.",
    "debug": "Troubleshooting.",
}

SCHEMA = [
    S("general.preset", "balanced", "LENSLATE_PRESET", "Preset",
      "The last preset you picked: nogpu, balanced or fastest (custom when you changed a step by hand). Picking "
      "one sets the reading, where it runs and the translator together; your language model choice is kept.",
      choices=("nogpu", "balanced", "fastest", "custom"),
      # 2026-11-10: seven presets became three. Old names: Light -> No GPU, Fast -> Balanced; the rest (Careful
      # reading, Sugoi, Ultrafast as presets) are steps you can still pick, so they read as custom.
      aliases={"light": "nogpu", "fast": "balanced", "low_cpu": "custom", "ultrafast": "custom",
               "light_plus": "custom", "quality": "custom"}),
    S("general.setup_done", False, "LENSLATE_SETUP_DONE", "Setup done",
      "Set when the first-launch setup window was finished or closed, so it does not open again by itself. Set it to "
      "false (or run `lenslate setup`) to see it again."),
    S("translator.kind", "mt", "LENSLATE_TRANSLATOR", "Translator",
      "Which model translates new text. llm = a language model on the graphics card: best quality, uses GPU "
      "memory. mt = quickmt on the processor: no GPU memory, fast, literal; fine for menus. sugoi = Sugoi on the "
      "processor: no GPU memory, made for visual-novel dialogue, poor on menus. online = an internet service "
      "(see Online translator): nothing runs on this computer, but the game text is sent to that company.",
      choices=("llm", "mt", "sugoi", "online")),
    S("translator.llm_model", "gemma-4-e2b", "LENSLATE_MODEL", "Language model",
      "The language model used when Translator is llm: a name from `lenslate models` (downloaded and run by "
      "lenslate itself), or any Ollama model name. Gemma 4 E2B gave the best game translations in tests and "
      "needs about 1.7 GB of GPU memory."),
    S("translator.llm_backend", "auto", "LENSLATE_LLM_BACKEND", "Model runner",
      "What runs the language model. builtin = lenslate's own runner (llama.cpp, downloaded by lenslate; "
      "nothing else to install). ollama = an Ollama server you installed yourself. auto = the built-in runner "
      "when the model is downloaded in lenslate, otherwise Ollama.", choices=("auto", "builtin", "ollama")),
    S("translator.gpu_layers", 99, "LENSLATE_GPU_LAYERS", "Model layers on the GPU",
      "Built-in runner: how much of the language model goes on the graphics card. 99 = all of it (fastest). "
      "Lower numbers keep part of it in normal memory: slower, but leaves GPU memory for a heavy game. "
      "0 = processor only.", lo=0, hi=999),
    S("translator.runner_port", 14367, "LENSLATE_RUNNER_PORT", "Built-in runner port",
      "The local port lenslate's built-in model runner listens on (only this computer can reach it).",
      lo=1024, hi=65535),
    S("translator.online_provider", "google", "LENSLATE_ONLINE", "Online translator",
      "Internet service used when Translator is online, or as the fallback below. The game text is SENT TO "
      "THAT COMPANY. google, bing and yandex need no account but can stop working or limit you at any time; "
      "deepl needs a free API key (below).", choices=("google", "bing", "yandex", "deepl")),
    S("translator.online_fallback", False, "LENSLATE_ONLINE_FALLBACK", "Use online when local fails",
      "When the local translator cannot translate a line (model missing, crashed, or it gave no usable answer), "
      "send that line to the online translator instead. Off by default: with it on, game text can leave this "
      "computer."),
    S("translator.seed_packs", True, "LENSLATE_SEED_PACKS", "Ready-made menu translations",
      "Use lenslate's lists of common game menu words and short lines (New Game, Inventory, Settings, Save...) "
      "with their usual translation, instead of asking the translator. Small translators often get a lone "
      "word wrong because it has no context (Inventory -> 产品目录). Only whole lines are matched, so dialogue "
      "is not affected. Your own fixes (Fix translations) always win."),
    S("translator.deepl_key", "", "LENSLATE_DEEPL_KEY", "DeepL API key",
      "Your DeepL API key (free plan: 500,000 characters a month, sign up at deepl.com). Only needed for the "
      "deepl online translator."),
    S("translator.stream", False, "LENSLATE_STREAM", "Show translation as it is written",
      "Language model only: the card fills in word by word while the model writes the translation, instead of "
      "appearing when it is finished. The finished translation is the same; it only appears sooner. Off by default."),
    S("translator.context_lines", 0, "LENSLATE_CONTEXT", "Earlier lines as context",
      "Language model only: send this many earlier dialogue lines (with their translations) along with each new "
      "line, so the model knows who is speaking and what 'it' refers to. 0 = off (each line is translated on its "
      "own). Try 3. A little slower per line; a line is still translated only once (the first translation is "
      "kept), and menus and labels never get context.", lo=0, hi=8),
    S("translator.language", "English", "LENSLATE_LANG", "Translate into",
      "The language the translations are written in.",
      choices=("English", "Spanish", "Portuguese (Brazil)", "Chinese (Simplified)")),
    S("translator.sources", "ja,zh,en", "LENSLATE_SOURCES", "Translate from",
      "Which languages lenslate translates when it finds them on screen or in a game, separated by commas: "
      "ja = Japanese, zh = Chinese (Simplified and Traditional), en = English. Each line's language is "
      "recognised automatically; text already in the 'Translate into' language is left alone. Korean (ko) and "
      "Russian (ru) have their own reader model, so choose one of them without Japanese or Chinese (ko,en or "
      "ru,en); they are translated by the language model or an online service."),
    S("translator.ollama_url", "http://127.0.0.1:11434/api/chat", "LENSLATE_URL", "Ollama address",
      "Where the Ollama server listens. Only change this if Ollama runs on another port or machine."),
    S("translator.num_ctx", 4096, "LENSLATE_NUM_CTX", "Model context size",
      "How much text the language model keeps in memory per request. 4096 is plenty for one line and keeps GPU "
      "memory low (Ollama's default would use about 2 GB more).", lo=1024, hi=32768),
    S("translator.mt_threads", 4, "LENSLATE_MT_THREADS", "CPU translator threads",
      "Processor threads used by the mt and sugoi translators. More is faster but leaves less for the game.",
      lo=1, hi=64),
    # (default 0.6 until 2026-11-12, then 0.9; 1.0 since 2026-11-13 by my choice: in a real game the
    #  original showed through and both texts were hard to read; a saved setting is not touched)
    S("overlay.opacity", 1.0, "LENSLATE_OPACITY", "Card opacity",
      "How solid the translation cards are: 1 hides the original text completely, lower values let it show "
      "through (the text gets an outline so it stays readable).", lo=0.1, hi=1.0),
    S("overlay.reading_tip", True, "", "Reading tip",
      "Show the tip about game settings (solid text-box background, bigger text, standard font) on the Overlay "
      "page while lenslate runs. 'Got it' turns it off."),
    S("overlay.placeholder", False, "LENSLATE_PLACEHOLDER", "Placeholder cards",
      "Show a card with … on new text the moment it is read, before its translation is ready, so you see at once "
      "that lenslate is working on it. Off by default."),
    S("refresh.interval", 1.0, "LENSLATE_INTERVAL", "Auto-refresh interval (s)",
      "In auto mode, how often lenslate checks the screen for new text. Only changed areas are read again, so "
      "short intervals cost little while nothing changes.", lo=0.2, hi=30.0),
    S("refresh.settle_step", 0.0, "LENSLATE_SETTLE", "Typewriter wait (optional)",
      "Off by default (0), meant for visual novels and other slow games. Off: text is read while it is still being "
      "typed out, so you can start reading at once; the line's card keeps its last translation (marked …) while "
      "the longer line is translated, and half-typed lines are never kept in the cache. On (e.g. 0.15 = check every "
      "0.15 s): lenslate waits until the text stops being typed before reading it, so each line is read and "
      "translated once, but it appears later. Leave it off for games where dialogue is part of the action or gets "
      "cut off (interruptions, timed choices).",
      lo=0.0, hi=2.0),
    S("refresh.settle_max", 0.8, "LENSLATE_SETTLE_MAX", "Typewriter longest wait",
      "Only used when the typewriter wait is on: the longest lenslate waits for text that is still being typed. "
      "After this it translates whatever is on screen, even half-typed, so very slow text never leaves you "
      "waiting with nothing to read.", lo=0.0, hi=10.0),
    S("ocr.engine", "ocr", "LENSLATE_ENGINE", "Screen reading method",
      "ocr = a text-recognition model on the processor reads the screen, then the translator translates "
      "(recommended). vlm = an image-understanding model reads and translates screenshots in one step (slow, "
      "needs a lot of GPU memory).", choices=("ocr", "vlm")),
    S("ocr.threads", 6, "LENSLATE_OCR_THREADS", "OCR threads",
      "Processor threads used for reading text from the screen. 6 was as fast as 12 in tests.", lo=1, hi=64),
    S("ocr.reading", "accurate", "LENSLATE_READING", "Reading",
      "accurate = the text finder looks at every area at full size and small text is read again enlarged: finds "
      "small and faint text (version numbers, hints, small UI). fast = the finder looks once (shrunk to at most "
      "1920 px) and its lines go straight to the reader: 2-3x faster, but small or faint text can be missed. "
      "ultrafast = like fast, but meikiocr (a reader trained on Japanese game text) finds and reads: ~6x faster "
      "and ~7x less processor work than fast; Japanese only (English lines are read by the normal reader, Chinese "
      "comes out wrong).", choices=("accurate", "fast", "ultrafast")),
    S("ocr.gpu", "off", "LENSLATE_OCR_GPU", "Read text on the graphics card",
      "off = reading runs on the processor. reader = the found lines are read on the graphics card (NVIDIA): about "
      "12x faster line reading for ~0.4 GB of GPU memory; finding text stays on the processor. all = finding and "
      "reading both on the graphics card: the processor is almost idle (lowest CPU use) for ~1-1.3 GB of GPU memory. "
      "Needs a one-time 3.4 GB download (lenslate ocr-gpu install).", choices=("off", "reader", "all"),
      aliases={"true": "reader", "1": "reader", "false": "off", "0": "off"}),
    S("ocr.big_text", "normal", "LENSLATE_BIG_TEXT", "Big text (4K screens)",
      "normal = text is read at its own size. half = areas whose text is taller than about 48 pixels (menus and "
      "dialogue on a 4K screen, or very large game fonts) are read at half size, where the reader still sees it as "
      "large as 1080p text. Helps the careful (accurate) full reads: a whole 4K screen with Balanced measured "
      "11.7 s -> 10.5 s. Fast reading already reads each found line at a fixed size, so it gains nothing. Off by "
      "default.",
      choices=("normal", "half")),
    S("ocr.vlm_model", "qwen3-vl:4b-instruct", "LENSLATE_VLM_MODEL", "Image model (vlm)",
      "The Ollama model used when the screen reading method is vlm. It must be able to read images."),
    S("hook.port", 14366, "LENSLATE_HOOK_PORT", "Hook mode port",
      "The local port games in hook mode send their text to (only this computer can reach it).",
      lo=1024, hi=65535),
    S("paths.cache", "", "LENSLATE_CACHE", "Translation cache file",
      "Where finished translations are kept so the same line is never translated twice. Empty = "
      "~/.cache/lenslate/translations-<language>.json."),
    S("paths.models", os.path.join(DATA_DIR, "models"), "LENSLATE_MODELS", "Model folder",
      "Where downloaded translation models (quickmt, Sugoi) are stored."),
    S("capture.backend", "auto", "LENSLATE_CAPTURE", "Screen capture method",
      "How lenslate takes the picture it reads. auto: the fastest way this desktop offers (KDE: KWin's own window "
      "capture; X11: the X server; other Wayland desktops such as Hyprland, Sway or GNOME: the screen-sharing "
      "portal). portal: always the screen-sharing portal - the desktop asks once which window or screen to share "
      "and remembers it (`lenslate share` asks again). With the portal a shared window must fill its monitor "
      "(fullscreen or borderless), because the desktop does not say where a window is. Needs a restart.",
      choices=("auto", "portal")),
    S("debug.enabled", False, "LENSLATE_DEBUG", "Debug log",
      "Print what lenslate does and record every refresh with its screenshot to ~/.cache/lenslate/debug/. "
      "Uses disk space; turn it off when not troubleshooting."),
]
BY_KEY = {s.key: s for s in SCHEMA}

_cache = {"mtime": object(), "data": {}}


def _read():
    try:
        m = os.stat(CONFIG_PATH).st_mtime
    except OSError:
        m = None
    if m != _cache["mtime"]:
        data = {}
        if m is not None:
            try:
                with open(CONFIG_PATH, "rb") as f:
                    data = tomllib.load(f)
            except (OSError, tomllib.TOMLDecodeError) as e:
                print("lenslate: config.toml is not valid (%s); using defaults" % e, flush=True)
        for sec in list(data):   # a known section written as a value (translator = 5) crashed every process
            if sec in SECTIONS and not isinstance(data[sec], dict):
                print("lenslate: [%s] in config.toml is not a section; using its defaults" % sec, flush=True)
                del data[sec]
        _cache.update(mtime=m, data=data)
    return _cache["data"]


def mtime():
    try:
        return os.stat(CONFIG_PATH).st_mtime
    except OSError:
        return None


def file_value(key):
    sec, name = key.split(".", 1)
    return _read().get(sec, {}).get(name)


def get(key):
    s = BY_KEY[key]
    if s.env and os.environ.get(s.env) not in (None, ""):
        try:
            return s.parse(os.environ[s.env])
        except (TypeError, ValueError):
            pass
    try:
        v = file_value(key)
    except AttributeError:   # (a value where a section should be: _read() drops those, this is a last guard)
        v = None
    if v is not None:
        try:
            return s.parse(v)
        except (TypeError, ValueError):
            print("lenslate: bad value for %s in config.toml: %r; using %r" % (key, v, s.default), flush=True)
    return s.default


def overridden(key):
    """True when an environment variable decides this setting (the GUI shows it as locked)."""
    s = BY_KEY[key]
    return bool(s.env and os.environ.get(s.env))


def set(key, value):   # noqa: A001 - config.set reads naturally
    set_many({key: value})


def set_many(values):
    data = {sec: dict(v) if isinstance(v, dict) else v for sec, v in _read().items()}
    for key, value in values.items():
        value = BY_KEY[key].parse(value)
        sec, name = key.split(".", 1)
        data.setdefault(sec, {})[name] = value
    write(data)


def _toml(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return '"%s"' % v.replace("\\", "\\\\").replace('"', '\\"')
    if isinstance(v, list):
        return "[%s]" % ", ".join(_toml(x) for x in v)
    raise TypeError("cannot write %r to config.toml" % (v,))


def _wrap(text, width=100):
    out, line = [], ""
    for w in text.split():
        if line and len(line) + 1 + len(w) > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    return out + ([line] if line else [])


def write(data):
    """Write config.toml: every known setting with its description as a comment (defaults commented out),
    then any other sections (e.g. per-game ones) as they are."""
    lines = ["# lenslate settings. Lines starting with # are explanations or unchanged defaults:",
             "# remove the # in front of a setting to change it. lenslate picks up changes while running.", ""]
    for sec, about in SECTIONS.items():
        lines.append("[%s]" % sec)
        lines.append("# " + about)
        for s in SCHEMA:
            if not s.key.startswith(sec + "."):
                continue
            name = s.key.split(".", 1)[1]
            lines.append("")
            lines += ["# " + l for l in _wrap("%s: %s" % (s.label, s.help))]
            if s.choices:
                lines.append("# one of: " + ", ".join(map(str, s.choices)))
            v = data.get(sec, {}).get(name)
            if v is None:
                lines.append("#%s = %s" % (name, _toml(s.default)))
            else:
                lines.append("%s = %s" % (name, _toml(v)))
        # settings this version does not know (written by a newer lenslate): keep them. An older running lenslate
        # rewrote the file and silently dropped [ocr] reading, which turned every preset into "Balanced".
        known = {k.split(".", 1)[1] for k in BY_KEY if k.startswith(sec + ".")}
        for name, v in (data.get(sec) or {}).items():
            if name not in known and not isinstance(v, dict):
                try:
                    lines.append("%s = %s" % (name, _toml(v)))
                except TypeError:
                    pass
        lines.append("")
    for sec, vals in data.items():
        if sec in SECTIONS or not isinstance(vals, dict):
            continue
        lines.append("[%s]" % sec)
        for k, v in vals.items():
            if isinstance(v, dict):
                continue
            lines.append("%s = %s" % (k, _toml(v)))
        for k, v in vals.items():   # one level of sub-tables, e.g. [games.yaretakamoment]
            if isinstance(v, dict):
                lines.append("[%s.%s]" % (sec, k))
                lines += ["%s = %s" % (kk, _toml(vv)) for kk, vv in v.items()]
        lines.append("")
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    # only the user may read it: it can hold the DeepL key ([translator] deepl_key)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)
    _cache["mtime"] = object()


def migrate():
    """Old ~/.config/lenslate/config.json (opacity, translator, llm_model) -> config.toml, once."""
    old = os.path.join(CONFIG_DIR, "config.json")
    if os.path.exists(CONFIG_PATH) or not os.path.exists(old):
        if not os.path.exists(CONFIG_PATH):
            write({})
        return
    import json
    try:
        with open(old, encoding="utf-8") as f:
            j = json.load(f)
    except (OSError, ValueError):
        j = {}
    data = {}
    for jk, key in (("opacity", "overlay.opacity"), ("translator", "translator.kind"), ("llm_model", "translator.llm_model")):
        if jk in j:
            sec, name = key.split(".", 1)
            data.setdefault(sec, {})[name] = BY_KEY[key].parse(j[jk])
    write(data)
    os.replace(old, old + ".migrated")


def cache_path():
    import re
    lang = re.sub(r"[^a-z]+", "-", get("translator.language").lower()).strip("-")
    own = get("paths.cache")
    if not own:
        return os.path.join(CACHE_DIR, "translations-%s.json" % lang)
    # a cache file of the user's own choosing: English keeps that exact name (as before); other target languages get
    # their own file next to it (one shared file mixed the languages: a Spanish line could be shown in English)
    own = os.path.expanduser(own)
    if lang == "english":
        return own
    root, ext = os.path.splitext(own)
    return "%s-%s%s" % (root, lang, ext or ".json")


def models_dir():
    return os.path.expanduser(get("paths.models"))


# ------------------------------------------------------------------------------------------------- presets
# A preset sets several settings at once. Changing any of them by hand makes the preset "custom".
# Three, by how much of the PC lenslate may use (decided 2026-11-10). They never set the language model (a model
# you chose stays) or the typewriter wait (Overlay page). Careful reading, Ultrafast and Sugoi are step options.
PRESETS = {
    "nogpu": {
        "label": "No GPU",
        "summary": "Everything on the processor: no graphics-card memory at all. For weaker PCs and games that "
                   "need the whole graphics card.",
        "tradeoff": "Word-for-word translations (quickmt): fine for menus, stiff on dialogue, no names or context.",
        "values": {"ocr.reading": "fast", "ocr.gpu": "off", "translator.kind": "mt"},
    },
    "balanced": {
        "label": "Balanced",
        "summary": "Reading on the processor, the language model on the graphics card: natural translations.",
        "tradeoff": "Uses graphics memory for the language model (0.6-1.7 GB, depending on your languages); the "
                    "game shares the processor while text is read.",
        "values": {"ocr.reading": "fast", "ocr.gpu": "off", "translator.kind": "llm"},
    },
    "fastest": {
        "label": "Fastest",
        "summary": "Reading and translating on the graphics card: whole screens about 2x faster, the processor "
                   "stays almost idle.",
        "tradeoff": "NVIDIA only. More graphics memory (reading ~0.7-1.2 GB + the language model) and a one-time "
                    "3.4 GB download. When that memory is not free, the processor reads instead (you get a notice).",
        "values": {"ocr.reading": "fast", "ocr.gpu": "all", "translator.kind": "llm"},
    },
}
PRESET_ORDER = ("nogpu", "balanced", "fastest")
BY_KEY["general.preset"].choices = tuple(PRESET_ORDER) + ("custom",)   # one list: a new preset is always valid


def _preset_values(name):
    """A preset's settings (every preset says where reading runs)."""
    return dict(PRESETS[name]["values"])


STEP_KEYS = ("ocr.reading", "ocr.gpu", "translator.kind", "translator.llm_model", "refresh.settle_step")


def values_of(preset):
    """A preset's settings; "current" = the steps as set now (the Translation page shows estimates for them);
    a dict is returned as is."""
    if isinstance(preset, dict):
        return preset
    if preset == "current":
        return {k: get(k) for k in STEP_KEYS}
    return PRESETS[preset]["values"]


def apply_preset(name):
    set_many(dict(_preset_values(name), **{"general.preset": name}))


def current_preset():
    """The preset whose settings all match the current ones, or "custom"."""
    hits = [(len(PRESETS[n]["values"]), n) for n in PRESET_ORDER
            if all(get(k) == v for k, v in _preset_values(n).items())]
    return max(hits)[1] if hits else "custom"
