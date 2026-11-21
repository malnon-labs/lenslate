"""lenslate's windows opened in each language: no English text may be left over.

The windows are opened in English and in every other window language (tests/window_texts.py, one process each).
A text with words in it that is shown exactly the same in both was not translated - unless it is a name (a model,
a program, a company) or a technical word every language writes the same way (ALLOWED).
"""
import json
import os
import re
import subprocess
import sys
import unittest

from tests import ROOT

try:
    import PySide6  # noqa: F401
except ImportError:      # the GUI toolkit is a system package: skip where it is missing
    PySide6 = None

import i18n

# names and words that stay as they are in every language (checked word by word, case-sensitive)
NAMES = {
    "lenslate", "Gemma", "PLaMo", "Translate", "quickmt", "OPUS", "Sugoi", "Qwen", "LFM", "Hunyuan", "MT",
    "Hy", "VL", "EN", "JP", "uncensored", "Google", "DeepL", "Bing", "Yandex", "Ollama", "NVIDIA", "AMD", "Intel",
    "Ryzen", "GeForce", "RTX", "Radeon", "Arc", "Vulkan", "CUDA", "llama", "cpp", "server", "Hugging", "Face", "GPU",
    "CPU", "OCR", "RAM", "VRAM", "GB", "MB", "ms", "KDE", "Plasma", "X11", "Wayland", "GNOME", "Cinnamon", "Xfce",
    "MATE", "Hyprland", "Sway", "niri", "i3", "KWin", "Ctrl", "Alt", "Shift", "Super", "Meta", "Esc", "Unity",
    "RPG", "Maker", "MV", "MZ", "VX", "Ace", "Ren", "Py", "XUnity", "AutoTranslator", "BepInEx", "PP", "OCRv5",
    "OCRv6", "Ultrafast", "meikiocr", "PaddleOCR", "RapidOCR", "Steam", "Proton", "Wine", "JSON", "TOML", "API",
    "URL", "PDF", "Preferred", "Networks", "Tencent", "Helsinki", "NLP", "opus", "tc", "big", "en", "pt", "NTT",
    "Liquid", "Apache", "MIT", "CC", "BY", "NC", "SA", "Community", "License", "LibreTranslate", "DeepLX",
    "ONNX", "onnxruntime", "PipeWire", "Spectacle", "Flameshot", "XWayland", "Mutter", "Xcomposite", "kdotool",
    "PySide6", "Qt", "numpy", "uv", "pip", "Python", "AppImage", "Flatpak", "Linux", "Windows", "macOS",
    "Portuguese", "Brazil", "English", "Japanese", "Chinese", "Korean", "Russian", "Spanish",
    "Ollama's", "Google's", "Tencent's", "KDE's", "lenslate's", "PP-OCRv5", "PP-OCRv6",
}
# language names in their own language (the window language picker shows them so on purpose)
OWN_NAMES = set(i18n.LANGS.values())


def leftover(text):
    """The English words of a text that a translation should have changed (empty: nothing to translate)."""
    if text in OWN_NAMES:
        return []
    t = re.sub(r"\b\w*\d\w*\b|https?://\S+|~?/[\w./*-]+|\[[\w.]+\]|\b[\w-]+\.(json|toml|py|log|gguf|sh|desktop)\b|`[^`]*`|"
               r"\b[\w.]+=\S*|\b[a-z_]+\.[a-z_.]+\b|%[-.0-9]*[sdfr]", " ", text)
    words = re.findall(r"[A-Za-z][A-Za-z']+", t)
    return [w for w in words if w not in NAMES and len(w) > 1 and not re.fullmatch(r"[A-Z0-9]+", w)]


def texts(lang):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    out = subprocess.run([sys.executable, "-m", "tests.window_texts", lang], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=300)
    if out.returncode:
        raise AssertionError("tests.window_texts %s failed:\n%s" % (lang, out.stderr[-3000:]))
    return {d["text"]: d["where"] for d in json.loads(out.stdout.strip().splitlines()[-1])}


@unittest.skipIf(PySide6 is None, "PySide6 is not installed")
class NoEnglishLeft(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.english = texts("en")

    def check(self, lang):
        shown = texts(lang)
        same = {re.sub(r"<[^>]+>", " ", k).replace("&&", "&").strip() for k, v in i18n.catalog(lang).items() if k == v}
        left = sorted("%s: %s" % (where, t[:100]) for t, where in shown.items()
                      if t in self.english and leftover(t) and t.lstrip("✓ ") not in same)   # (same: the word is the same there)
        self.assertEqual(left, [], "%d texts still in English in the %s windows" % (len(left), lang))

    def test_portuguese(self):
        self.check("pt")

    def test_chinese(self):
        self.check("zh")

    def test_japanese(self):
        self.check("ja")

    def test_korean(self):
        self.check("ko")

    def test_russian(self):
        self.check("ru")

    def test_the_check_finds_english(self):
        self.assertEqual(leftover("Pick area…"), ["Pick", "area"])
        self.assertEqual(leftover("quickmt Japanese → English"), [])
        self.assertEqual(leftover("Gemma 4 E2B · 3.1 GB"), [])
        self.assertEqual(leftover("Português (Brasil)"), [])


if __name__ == "__main__":
    unittest.main()
