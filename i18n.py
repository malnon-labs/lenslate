"""lenslate's own windows in other languages.

    _("Pick area…")  ->  "Selecionar área…" when the window language is Portuguese (Brazil)

Catalogs: i18n/<code>.json, {"English text": "translation"}; a text missing from a catalog stays English, so a
partial catalog is fine (the long hover explanations are translated step by step). The key is the English text
exactly as written in the code (a template like "Hotkey: %s." is translated before it is filled in).

Language: [general] ui_language (auto = from the system: LANGUAGE / LC_ALL / LC_MESSAGES / LANG).

    python3 i18n.py extract          every text the windows show, as JSON (for translators: the keys to fill in)
    python3 i18n.py missing pt       the texts the Portuguese catalog does not have yet
"""
import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "i18n")
LANGS = {"en": "English", "pt": "Português (Brasil)", "zh": "简体中文", "ja": "日本語", "ko": "한국어",
         "ru": "Русский"}
_cat = {}
_lang = [None]


def system_language(env=None):
    env = os.environ if env is None else env
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        for part in (env.get(var) or "").split(":"):
            code = part.split(".")[0].split("_")[0].split("-")[0].lower()
            if code in LANGS:
                return code
            if code and code not in ("c", "posix"):
                return "en"
    return "en"


def language():
    """The window language code ('en', 'pt', ...)."""
    if _lang[0] is None:
        want = "auto"
        try:
            import config as cfgmod
            want = cfgmod.get("general.ui_language")
        except Exception:  # noqa: BLE001 - no config yet: follow the system
            pass
        _lang[0] = want if want in LANGS else system_language()
    return _lang[0]


def set_language(code):
    """Use another catalog from now on (windows built after this show it)."""
    _lang[0] = code if code in LANGS else system_language()
    _cat.clear()


def catalog(code=None):
    code = code or language()
    if code not in _cat:
        data = {}
        if code != "en":
            try:
                with open(os.path.join(DIR, code + ".json"), encoding="utf-8") as f:
                    data = {k: v for k, v in json.load(f).items() if isinstance(v, str) and v}
            except (OSError, ValueError):
                data = {}
        _cat[code] = data
    return _cat[code]


def _(text):
    """The text in the window language (English when the catalog has no entry)."""
    if not isinstance(text, str) or not text:
        return text
    return catalog().get(text, text)


def N_(text):
    """Marks a text that is translated later, where it is shown (kept in a table: page names, tray entries)."""
    return text


def install_qt(app):
    """Load Qt's own translations (wizard and dialog buttons: Back, Next, Cancel ...) for the window language."""
    code = language()
    if code == "en":
        return
    try:
        from PySide6.QtCore import QLibraryInfo, QTranslator
        qt_code = {"pt": "pt_BR", "zh": "zh_CN"}.get(code, code)
        tr = QTranslator(app)
        if tr.load("qtbase_" + qt_code, QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            app.installTranslator(tr)
            app._lenslate_qt_tr = tr      # keep it alive
    except Exception:  # noqa: BLE001 - only the standard buttons stay English
        pass


# ------------------------------------------------------------------------------------------------- tools
# functions whose first text argument is shown in a window (besides _ itself)
SHOWN = {"_", "N_", "QAction", "explain", "section_label", "note", "hint", "chip", "message", "QPushButton", "QLabel", "QCheckBox",
         "QRadioButton", "setTitle", "setSubTitle", "setWindowTitle", "setText", "setPlaceholderText", "say",
         "_label", "addItem"}
FILES = ("gui.py", "setup.py", "shortcutsdialog.py", "hwcheck.py")
TABLES = {"STEPS", "PLAIN"}
# shown, but kept in tuples and dicts the extractor does not follow: page names and their lines, Advanced's groups
EXTRA = ["Spanish", "Portuguese (Brazil)", "Chinese (Simplified)", "%s only", "%s (and English)", "Japanese", "Chinese (Simplified and Traditional)", "English", "Korean", "Russian",
         "Hover over anything to see what it does.", " (your own choice)", "Overlay", "Translation", "Models", "Games", "Names & fixes", "Advanced",
         "Translate text anywhere on screen: games, browsers, videos, documents.",
         "Which languages, and how lenslate reads and translates them. The panel shows what your choices cost on this PC.",
         "Download or remove translation models.",
         "Translate inside a game (hooks) and prepare its text in advance.",
         "Character names and game terms, so they are translated the same way every time; and translations that came "
         "out wrong, to correct or delete.",
         "Everything else, for fine-tuning and troubleshooting.",
         "General", "Screen reading (OCR)", "Hook mode", "Files and folders", "Troubleshooting", "Refreshing"]


def _const(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):    # "text %s" % x: the template
        return _const(node.left)
    return None


def extract():
    """Every text the windows show: the literal texts passed to SHOWN functions, and the settings' labels/help."""
    out = []
    for fn in FILES:
        tree = ast.parse(open(os.path.join(HERE, fn), encoding="utf-8").read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name not in SHOWN:
                continue
            for arg in node.args[:2]:
                t = _const(arg)
                if t and any(c.isalpha() for c in t) and t not in out:
                    out.append(t)
        for node in ast.walk(tree):     # option tables shown in the window (gui.STEPS, gui.PLAIN)
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") in TABLES for t in node.targets) \
                    and not isinstance(node.value, (ast.Call, ast.GeneratorExp, ast.DictComp)):
                for c in ast.walk(node.value):
                    t = _const(c)
                    if t and " " in t.strip() or (t and t[:1].isupper()):
                        if t not in out:
                            out.append(t)
    for t in EXTRA:
        if t not in out:
            out.append(t)
    for t in data_texts():
        if t and t not in out:
            out.append(t)
    return out


def data_texts():
    """Texts the windows take from lenslate's tables: settings, presets, models, capture guides."""
    import re
    import captureinfo
    import config as cfgmod
    import models
    out = list(cfgmod.SECTIONS.values())
    for p in cfgmod.PRESETS.values():
        out += [p.get("label"), p.get("summary"), p.get("tradeoff")]
    for s in cfgmod.SCHEMA:
        out += [s.label, s.help]
    for m in models.CATALOG:
        out += [m.title, re.sub(r" \(language model\)$", "", m.title),
                re.sub(r"\s*\((?:language|translation|language \+ image) model\)$", "", m.title),
                m.about, m.license, m.license.split(" (")[0], getattr(m, "can", "")]
    for g in captureinfo.GUIDES.values():
        out += [g["title"], g["summary"]] + list(g["tips"])
    return [t for t in out if t and needs_words(t)]


NOT_TEXT = {"warning", "success", "__other__", "lenslate", "lenslate %s",
            "(described for the chosen model: llm_description)",    # markers and names, not words to translate
            # model and licence names: the same in every language
            "CC-BY-4.0", "Apache-2.0", "Gemma 4 E2B", "Qwen3.5 4B uncensored", "PLaMo 3 Translate 0.8B",
            "PLaMo 3 Translate 2B", "Hy-MT2 1.8B", "LFM2 350M EN-JP", "Qwen3-VL 4B", "PLaMo Community License",
            "LFM Open License"}


def needs_words(t):
    """A text with words in it (not only placeholders, markup, or an internal marker)."""
    import re
    return t not in NOT_TEXT and bool(re.search(r"[A-Za-z]{2}", re.sub(r"<[^>]+>|%[-.0-9]*[sdfr%]|&nbsp;", "", t)))


def main(args):
    if args[:1] == ["extract"]:
        print(json.dumps({t: "" for t in extract()}, ensure_ascii=False, indent=1))
        return 0
    if args[:1] == ["missing"] and len(args) > 1:
        have = catalog(args[1])
        miss = [t for t in extract() if t not in have and needs_words(t)]
        print(json.dumps({t: "" for t in miss}, ensure_ascii=False, indent=1))
        print("%d of %d texts missing" % (len(miss), len([t for t in extract() if needs_words(t)])), file=sys.stderr)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
