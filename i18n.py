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
SHOWN = {"_", "QAction", "explain", "section_label", "note", "hint", "chip", "message", "QPushButton", "QLabel", "QCheckBox",
         "QRadioButton", "setTitle", "setSubTitle", "setWindowTitle", "setText", "setPlaceholderText", "say",
         "_label", "addItem"}
FILES = ("gui.py", "setup.py", "shortcutsdialog.py")
# shown, but kept in tuples and dicts the extractor does not follow: page names and their lines, Advanced's groups
EXTRA = ["Japanese", "Chinese (Simplified and Traditional)", "English", "Korean", "Russian",
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
    for t in EXTRA:
        if t not in out:
            out.append(t)
    import config as cfgmod
    for s in cfgmod.SCHEMA:
        for t in (s.label, s.help):
            if t and t not in out:
                out.append(t)
    return out


def main(args):
    if args[:1] == ["extract"]:
        print(json.dumps({t: "" for t in extract()}, ensure_ascii=False, indent=1))
        return 0
    if args[:1] == ["missing"] and len(args) > 1:
        have = catalog(args[1])
        miss = [t for t in extract() if t not in have]
        print(json.dumps({t: "" for t in miss}, ensure_ascii=False, indent=1))
        print("%d of %d texts missing" % (len(miss), len(extract())), file=sys.stderr)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
