"""Offline tests for lenslate: no models, no network, no GPU, no running overlay.

Run from the project folder:  python3 -m unittest discover -s tests -t .

Every test run gets its own empty config, cache and data folders (set here, before any lenslate module reads them),
so the user's settings, caches and downloaded models are never touched. Qt runs offscreen.
"""
import atexit
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SCRATCH = tempfile.mkdtemp(prefix="lenslate-tests-")
atexit.register(shutil.rmtree, SCRATCH, True)
for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
    os.environ[var] = os.path.join(SCRATCH, var.lower())
    os.makedirs(os.environ[var], exist_ok=True)
os.environ["LENSLATE_MODELS"] = os.path.join(SCRATCH, "models")   # empty: no model is "downloaded"
os.makedirs(os.environ["LENSLATE_MODELS"], exist_ok=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for var in [v for v in os.environ if v.startswith("LENSLATE_") and v != "LENSLATE_MODELS"]:
    os.environ.pop(var, None)   # the user's own overrides must not change what the tests see

# One Qt application for the whole run, made first: the window tests need a QApplication, and whichever test asks
# first would otherwise make a plain QGuiApplication that cannot be replaced.
try:
    from PySide6.QtWidgets import QApplication
    APP = QApplication.instance() or QApplication(["lenslate-tests"])
except ImportError:
    APP = None
