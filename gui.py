"""lenslate settings window and tray icon (`lenslate gui`).

Everything here is also a command or a line in ~/.config/lenslate/config.toml; the window only makes it easier.
Every control explains itself: hover it and the explanation appears in the help bar at the bottom (and as a
tooltip). The explanations come from config.py's SCHEMA, the same text that is written into config.toml.

The window talks to the running overlay through the same local socket as the hotkeys (it never starts it by
accident), and runs slow jobs (downloads, pre-translation, name scans) in background threads.
"""
import json
import os
import subprocess
import sys

from PySide6.QtCore import QPoint, QRect, QSize, QEvent, QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import (QToolButton, QLayout, QBoxLayout, QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit,
                               QListWidget, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QScrollArea, QSlider, QSpinBox, QStackedWidget, QSystemTrayIcon, QTabWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import config as cfgmod
from i18n import _
import langs
import re
import time
import theme
import version
from theme import set_role

HERE = os.path.dirname(os.path.abspath(__file__))


def app_icon():
    """lenslate's own icon (packaging/lenslate.svg next to the code; the installed icon theme copy otherwise)."""
    path = os.path.join(HERE, "packaging", "lenslate.svg")
    return QIcon(path) if os.path.exists(path) else QIcon.fromTheme("lenslate", QIcon.fromTheme("preferences-desktop-locale"))


def emoji_icon(ch):
    """An icon drawn from an emoji, for sidebar pages whose icon the desktop's icon theme does not have."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    f = QFont("Noto Color Emoji")
    f.setPixelSize(52)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, ch)
    p.end()
    return QIcon(pm)


def page_icons(spec):
    """{page: emoji} -> {page: QIcon}. Colour emojis on every desktop: icon themes mix flat monochrome icons with
    coloured ones (Breeze), and some setups have no icon theme at all."""
    return {page: emoji_icon(ch) for page, ch in spec.items()}
SOCK = "lenslate-%d" % os.getuid()
LENSLATE = os.path.expanduser("~/.local/bin/lenslate")


# ------------------------------------------------------------------------------------------- talking to lenslate
def send(cmd, timeout=1500):
    """Send a command to the running overlay; None if it is not running (never starts it)."""
    s = QLocalSocket()
    s.connectToServer(SOCK)
    if not s.waitForConnected(200):
        return None
    s.write(cmd.encode())
    s.flush()
    s.waitForReadyRead(timeout)
    reply = bytes(s.readAll()).decode()
    s.disconnectFromServer()
    return reply


def run_lenslate(*args):
    """Start a lenslate command in the background (e.g. start the overlay)."""
    exe = LENSLATE if os.path.exists(LENSLATE) else sys.executable
    cmd = [exe] + list(args) if exe == LENSLATE else [exe, os.path.join(HERE, "lenslate.py")] + list(args)
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


class Job(QThread):
    """A slow task in the background: fn(progress) where progress(done, total, text)."""
    progress = Signal(float, float, str)    # bytes can pass 2^31 (a 3 GB model): not int
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.finished_ok.emit(self.fn(lambda d, t, s="": self.progress.emit(float(d), float(t), str(s))))
        except Exception as e:  # noqa: BLE001 - shown to the user
            self.failed.emit(str(e))


# ------------------------------------------------------------------------------------------------- help bar
class HelpFilter(QObject):
    """Shows a widget's explanation (property "help") in the help bar while the mouse is over it."""

    def __init__(self, bar):
        super().__init__()
        self.bar = bar
        self.pending = None     # an error message: shown again after the hover help, until the next click

    def show(self, text, state="help"):
        """state: idle (the default hint), help (hover text), error (red, stays until the next click)."""
        if state == "error":
            self.pending = text
            text = "⚠ " + _(text)
        self.bar.setText(_(text))
        set_role(self.bar, "helpbar", state=state)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Enter:
            text = obj.property("help")
            if text:
                self.show(text)
        elif ev.type() == QEvent.Leave and obj.property("help"):
            if self.pending:
                self.show(self.pending, "error")
            else:
                self.show(DEFAULT_HELP, "idle")
        elif ev.type() == QEvent.MouseButtonPress:
            self.pending = None
        return False


DEFAULT_HELP = "Hover over anything to see what it does."

# Game settings that help OCR (shown on the Overlay page). Measured reasons: the reader is trained on plain printed
# fonts; busy art behind text adds false "text" the reader must check; small text is read at 2x (slower).
READING_TIPS = (   # (title, one-line version shown on the page, full text on hover)
    ("Solid text-box background", "Raise the text box's opacity", "if the game lets you raise the text window's opacity, do it: text over busy "
     "art or a see-through box is found and read worse, and the art itself can be mistaken for text."),
    ("Bigger text", "Larger text or UI scale", "a larger text size or UI scale reads more reliably; text under about 22 pixels tall has to be "
     "read enlarged, which is slower."),
    ("Plain font", "The game's standard font", "pick the game's standard font over decorative, handwritten or pixel fonts. Fonts made for "
     "readers with dyslexia are not a good choice here: their unusual letter shapes are harder for the text "
     "reader."),
)


def explain(widget, text, flt):
    text = _(text)
    widget.setProperty("help", text)
    widget.setToolTip("<p style='max-width:420px'>%s</p>" % text)
    widget.installEventFilter(flt)
    return widget


# ------------------------------------------------------------------------------------- widgets bound to config
def setting_widget(key, flt, on_error):
    """A control for one setting from config.SCHEMA; changes are saved to config.toml at once."""
    s = cfgmod.BY_KEY[key]
    val = cfgmod.get(key)
    if s.choices:
        w = QComboBox()
        w.addItems([str(c) for c in s.choices])
        w.setCurrentText(str(val))
        w.currentTextChanged.connect(lambda v: save(key, v, on_error))
    elif s.type is bool:
        w = QCheckBox()
        w.setChecked(bool(val))
        w.toggled.connect(lambda v: save(key, v, on_error))
    elif s.type is int:
        w = QSpinBox()
        w.setRange(int(s.lo if s.lo is not None else -10 ** 9), int(s.hi if s.hi is not None else 10 ** 9))
        w.setValue(int(val))
        w.valueChanged.connect(lambda v: save(key, v, on_error))
    elif s.type is float:
        w = QDoubleSpinBox()
        w.setDecimals(2)
        w.setSingleStep(0.1)
        w.setRange(float(s.lo if s.lo is not None else -1e9), float(s.hi if s.hi is not None else 1e9))
        w.setValue(float(val))
        w.valueChanged.connect(lambda v: save(key, round(v, 2), on_error))
    else:
        w = QLineEdit(str(val))
        if "key" in key:
            w.setEchoMode(QLineEdit.Password)
        w.editingFinished.connect(lambda: save(key, w.text(), on_error))
    help_text = "%s: %s" % (_(s.label), _(s.help))
    if cfgmod.overridden(key):
        w.setEnabled(False)
        help_text += " (Locked: set by the environment variable %s.)" % s.env
    return explain(w, help_text, flt)


def save(key, value, on_error):
    try:
        cfgmod.set(key, value)
    except Exception as e:  # noqa: BLE001
        on_error("Could not save %s: %s" % (key, e))
        try:
            with open(os.path.join(cfgmod.CACHE_DIR, "gui-clicks.log"), "a", encoding="utf-8") as fh:
                fh.write("  SAVE FAILED %s=%r: %s\n" % (key, value, e))
        except OSError:
            pass


GAP = 24          # space before a section header (docs/UX-GUIDE.md spacing scale)
LABEL_W = 230     # one label column for every form, so fields start at the same x on a page
TEXT_W = 640      # explanations: at most ~85 characters a line
CONTENT_W = 880   # pages with forms keep a readable column instead of stretching across the window


class Section(QLabel):
    """A section header (bigger, bold, space above)."""

    def __init__(self, text):
        super().__init__(_(text))
        set_role(self, "section")
        self.setContentsMargins(0, GAP - 8, 0, 2)


def section_label(text):
    return Section(text)


def note(text, width=TEXT_W):
    """A quieter explanation line (muted text colour that passes contrast in light and dark)."""
    lab = QLabel(_(text))
    lab.setWordWrap(True)
    if width:
        lab.setMaximumWidth(width)
    return set_role(lab, "muted")


def hint(text):
    lab = note(text)
    return set_role(lab, "hint")


def chip(text, kind=None):
    lab = QLabel(_(text))
    return set_role(lab, "chip", kind=kind or "")


def message(text, kind="info"):
    """An inline message box (info / warning / error) with a coloured side bar; the text says what it is."""
    lab = QLabel(_(text))
    lab.setWordWrap(True)
    lab.setMaximumWidth(CONTENT_W)
    return set_role(lab, "message", kind=kind)


def card_frame(role="card"):
    w = QFrame()
    return set_role(w, role)


def page(*widgets, wide=False):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 8, 16, 16)
    lay.setSpacing(8)
    for x in widgets:
        if isinstance(x, QWidget):
            lay.addWidget(x)
        else:
            lay.addLayout(x)
    lay.addStretch(1)
    if not wide:
        w.setMaximumWidth(CONTENT_W + 32)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setWidget(w)
    area.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    return area


def _limit(widget):
    """Free-text fields stop at 480 px; spin boxes and short lists keep their natural width."""
    if isinstance(widget, QLineEdit):
        widget.setMaximumWidth(480)
    return widget


def form(rows):
    f = QFormLayout()
    f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    f.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    f.setRowWrapPolicy(QFormLayout.WrapLongRows)    # narrow window: the label goes above its field
    f.setHorizontalSpacing(12)
    f.setVerticalSpacing(8)
    for label, widget in rows:
        lab = QLabel(_(label))
        lab.setMinimumWidth(LABEL_W)
        lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lab.setWordWrap(True)
        f.addRow(lab, _limit(widget) if isinstance(widget, QWidget) else widget)
    return f


class FitHeight(QObject):
    """Keeps a box at least as tall as its wrapped text needs at the width it really got (a horizontal layout asks
    for the height before it knows the width, and wrapped labels were cut off)."""

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Resize, QEvent.LayoutRequest) and obj.layout() is not None:
            need = obj.layout().totalHeightForWidth(obj.width())
            if need > 0 and obj.minimumHeight() != need:
                obj.setMinimumHeight(need)
        return False


_FIT = None


def fit_height(widget):
    global _FIT
    if _FIT is None:
        _FIT = FitHeight()
    widget.installEventFilter(_FIT)
    return widget


class Reflow(QWidget):
    """Two widgets side by side when the page is wide enough, one under the other when it is not."""

    def __init__(self, main, side, main_min=480):
        super().__init__()
        self.main, self.side, self.main_min = main, side, main_min
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(16)
        self.box.setSizeConstraint(QLayout.SetNoConstraint)   # never forces the page wider (see minimumSizeHint)
        self.box.addWidget(main, 3)     # (no alignment flag: an aligned widget gets its plain size hint, and
        self.box.addWidget(side, 1)     #  wrapped text inside it is then cut off)

    def minimumSizeHint(self):
        """Only as wide as the stacked layout needs: side by side is chosen when there is room, never forced."""
        return QSize(max(self.main.minimumSizeHint().width(), self.side.minimumWidth()), 0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self.box.totalHeightForWidth(w) if self.box.hasHeightForWidth() else self.box.sizeHint().height()

    def resizeEvent(self, ev):
        need = max(self.main_min, self.main.minimumSizeHint().width()) + self.side.minimumWidth() + 16
        wide = ev.size().width() >= need
        d = QBoxLayout.LeftToRight if wide else QBoxLayout.TopToBottom
        if self.box.direction() != d:
            self.box.setDirection(d)
            self.side.setMaximumWidth(300 if wide else CONTENT_W)
        super().resizeEvent(ev)


def small_form(rows):
    """A form inside a step: labels only as wide as they need."""
    f = QFormLayout()
    f.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    f.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    f.setRowWrapPolicy(QFormLayout.WrapLongRows)
    f.setHorizontalSpacing(12)
    f.setVerticalSpacing(6)
    f.setContentsMargins(0, 0, 0, 0)
    for label, widget in rows:
        f.addRow(QLabel(label), _limit(widget))
    return f


def framed(title, about, body):
    """Page title + muted subtitle over a page body."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    head = QVBoxLayout()
    head.setContentsMargins(16, 16, 16, 8)
    head.setSpacing(4)
    head.addWidget(set_role(QLabel(title), "title"))
    head.addWidget(note(about, CONTENT_W))
    lay.addLayout(head)
    lay.addWidget(body, 1)
    return w


# ------------------------------------------------------------------------------------------ presets page parts


OCR_GPU_GB = 3.4    # CUDA build of the OCR runtime + NVIDIA libraries (lenslate ocr-gpu install)

# The steps on the Translation page. Each text says HOW the option works, with costs measured on my PC
# (Ryzen 5 5500, RTX 4060; `Measure again` on whole 1080p screens, 2026-11-10).
STEPS = (
    ("Reading", "ocr.reading", (
        ("ultrafast", "Ultrafast", "meikiocr, a small model trained on Japanese game text, finds the lines and reads "
         "them (long lines in pieces). Whole 1080p screens in ~0.3-0.9 s on the processor, ~0.1-0.5 s on the "
         "graphics card. Japanese only: English lines are read again by the normal reader, Chinese comes out "
         "wrong; tiny text and version numbers are missed."),
        ("fast", "Quick", "The finder model looks at the area once, shrunk to at most 1920 px, and draws a box "
         "around each line. The reader reads only those boxes, line by line, and keeps its best guess (no second "
         "look). Whole 1080p screens in ~0.4-1.2 s on the processor, ~0.2-0.6 s on the graphics card. Lone "
         "characters and tiny or faint text the finder overlooks are never read. Japanese, Chinese and English."),
        ("accurate", "Careful", "The finder model looks at the whole area at full size, then the reader reads "
         "every line it found; small text is read again enlarged. Finds small, faint and single-character text. "
         "Whole 1080p screens in ~1-3.6 s, and its cards appear only when the whole area is done."))),
    ("Reading runs on", "ocr.gpu", (
        ("off", "Processor", "The finder and the reader run on the processor (6 threads). No graphics memory; the "
         "game shares the processor while text is read."),
        ("all", "Graphics card", "The finder and the reader run on the NVIDIA card (CUDA): whole screens 2-3x faster "
         "with Quick and Ultrafast reading, and the processor stays almost idle. Careful reading of a big, busy "
         "screen gains little (its full-size finder falls back to the processor). Needs ~0.7-1.2 GB of free "
         "graphics memory (checked when lenslate starts reading; if it is not free the processor reads and you "
         "get a notice) and a one-time 3.4 GB download."))),
    ("Translator", "translator.kind", (
        ("mt", "Cheapest (quickmt)", "A small translation model per language pair, on the processor: ~0.03 s a "
         "line, 0.5 GB of memory. Word-for-word style: fine for menus, stiff on dialogue, no names or context."),
        ("sugoi", "Visual novel (quickmt + Sugoi)", "Each line is sorted first: short labels (up to 12 characters, "
         "no sentence ending) go to quickmt, sentences to Sugoi, a model trained on visual-novel dialogue. Better "
         "dialogue on the processor (~0.3 s a line, 1.6 GB memory), still no context. Sugoi: Japanese to English "
         "only, 1.1 GB download, non-commercial licence."),
        ("llm", "Language model", "(described for the chosen model: llm_description)"),
        ("online", "Online", "Each line is sent to Google, Bing, Yandex or DeepL. Nothing runs on this computer, "
         "but the text leaves it."))),
)
# The one thing to know about each option, in plain words: shown first and in bold in its tooltip and under "?".
PLAIN = {
    ("ocr.reading", "ultrafast"): "Fastest and lightest reading, but only for Japanese, and it misses tiny text.",
    ("ocr.reading", "fast"): "Fast and light. Can miss single characters and tiny or faint text.",
    ("ocr.reading", "accurate"): "Finds the most text, tiny print too. Slower, and heavier on the processor.",
    ("ocr.gpu", "off"): "Uses the processor: no graphics memory, but the game has to share the processor.",
    ("ocr.gpu", "all"): "Faster, and leaves the processor to the game. Needs an NVIDIA card with some free memory.",
    ("translator.kind", "mt"): "Cheapest and fastest. Translates word for word: fine for menus, stiff dialogue.",
    ("translator.kind", "sugoi"): "Better dialogue without a graphics card. Japanese to English only.",
    ("translator.kind", "llm"): "Best translations: natural wording, names kept right. Uses graphics memory.",
    ("translator.kind", "online"): "Good translations with nothing running here, but the text is SENT to that company.",
}


def rich(key, val, text, why=None):
    """Tooltip / '?' text: the plain sentence in bold, the details in italics, a blocking reason first."""
    plain = PLAIN.get((key, val), "")
    parts = []
    if why:
        parts.append("<b>⚠ %s</b>" % why)
    if plain:
        parts.append("<b>%s</b>" % plain)
    parts.append("<i>%s</i>" % text)
    return "<br>".join(parts)


# Step options that only work for some languages or hardware: (key, value) -> function(sources, target, nvidia)
# returning the reason it does not fit, or None. When the current choice stops fitting (for example the languages
# changed), the step switches to the first option of STEP_FALLBACK[key] that fits. Add new limited options here.
OPTION_LIMITS = {
    ("ocr.reading", "ultrafast"): lambda src, tgt, nv: None if ("ja" in src and not src & set(langs.OWN_READER)) else
        "Only for Japanese text (Translate from includes no Japanese).",
    ("translator.kind", "sugoi"): lambda src, tgt, nv: None if ("ja" in src and tgt == "en") else
        "Only Japanese to English (pick Japanese and English above).",
    ("ocr.gpu", "all"): lambda src, tgt, nv: None if nv else "Needs an NVIDIA graphics card; none was found.",
    # retired from the window 2026-11-10: on 18 test screens Careful found nothing Quick missed and was 2-3x slower.
    # The code stays (config.toml `[ocr] reading = "accurate"` is switched to Quick when the window opens).
    ("ocr.reading", "accurate"): lambda src, tgt, nv: "Careful reading is no longer offered (it found nothing Quick "
        "missed in tests, and was 2-3x slower).",
}
RETIRED = {("ocr.reading", "accurate")}     # not shown at all (other blocked options are shown greyed out)
STEP_FALLBACK = {"ocr.reading": ("fast", "accurate"), "translator.kind": ("mt", "llm", "online"),   # first that fits
                 "ocr.gpu": ("off",)}


def option_blocks():
    """{(key, value): reason} for every step option that does not fit the current languages / this PC."""
    import hwcheck
    g = hwcheck.best_gpu()
    nv = bool(g and g["vendor"] == "NVIDIA")
    src = langs.sources(cfgmod.get("translator.sources"))
    tgt = langs.target_code(cfgmod.get("translator.language"))
    out = {}
    for kv, rule in OPTION_LIMITS.items():
        why = rule(src, tgt, nv)
        if why:
            out[kv] = why
    return out


def enforce_steps():
    """Switch any step whose current choice no longer fits to its fallback. Returns what changed, as text."""
    blocked = option_blocks()
    changed = []
    labels = {key: {v: lab for v, lab, _t in opts} for _title, key, opts in STEPS}
    for (key, val), why in blocked.items():
        if cfgmod.get(key) != val:
            continue
        new = next((v for v in STEP_FALLBACK.get(key, ()) if (key, v) not in blocked), None)
        if new is None:
            continue
        cfgmod.set(key, new)
        changed.append("%s → %s: %s" % (labels[key].get(val, val), labels[key].get(new, new),
                                         why.split(" (")[0].rstrip(".").lower()))
    return changed


class FlowLayout(QLayout):
    """Lays widgets out left to right and wraps onto the next line when the width runs out."""

    def __init__(self, parent=None, hspacing=0, vspacing=6):
        super().__init__(parent)
        self.items, self.hs, self.vs = [], hspacing, vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):
        super().setGeometry(r)
        self._do(r, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self.items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _do(self, r, test):
        x, y, line = r.x(), r.y(), 0
        for it in self.items:
            hint = it.sizeHint().expandedTo(it.minimumSize())
            if x + hint.width() > r.right() + 1 and line > 0:
                x, y, line = r.x(), y + line + self.vs, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.hs
            line = max(line, hint.height())
        return y + line - r.y()


def short_title(title):
    """'Gemma 4 E2B (language model)' -> 'Gemma 4 E2B' (the list it is in already says what it is)."""
    return re.sub(r" \(language model\)$", "", title)


def llm_description():
    """Step 2's text for the language model that is chosen now (never a guess: a model lenslate does not know is
    described as such)."""
    import models
    name = cfgmod.get("translator.llm_model")
    m = models.find(name)
    what = ("gets each line with a short instruction and writes a natural translation; it keeps names right and "
            "fixes small reading mistakes.")
    if m is None:
        return ("Your Ollama model %s %s Its speed and graphics memory depend on the model (Measure again shows "
                "the speed)." % (name, what))
    cost = "%.1f GB of graphics memory" % m.vram_gb if m.vram_gb else "its own memory"
    speed = " ~0.15 s a line." if m.name == "gemma-4-e2b" else ""
    return "%s on the graphics card %s%s %s." % (short_title(m.title), what, speed, cost[0].upper() + cost[1:])


def dots(n):
    return "●" * n + "○" * (5 - n)


class Spark(QWidget):
    """A small live line graph (last 60 samples, 0-100)."""
    def __init__(self, color):
        super().__init__()
        self.vals, self.color = [], QColor(color)
        self.setMinimumHeight(42)

    def push(self, v):
        self.vals = (self.vals + [max(0.0, min(100.0, v))])[-60:]
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        t = theme.tokens()
        # a filled strip with a faint outline and a baseline: a graph, not an empty text field
        p.setPen(QPen(QColor(t["border_subtle"]), 1))
        p.setBrush(QColor(t["surface_card"]))
        p.drawRoundedRect(r, 4, 4)
        p.setPen(QPen(QColor(t["border_subtle"]), 1, Qt.DashLine))
        p.drawLine(r.left() + 4, r.bottom() - 2, r.right() - 4, r.bottom() - 2)
        if len(self.vals) < 2:
            return
        path = QPainterPath()
        n = len(self.vals)
        for i, v in enumerate(self.vals):
            x = r.right() - r.width() * (n - 1 - i) / 59
            y = r.bottom() - r.height() * v / 100.0
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        p.setPen(QPen(self.color, 2))
        p.drawPath(path)


class CpuMeter:
    """CPU usage from /proc/stat (no extra packages)."""
    def __init__(self):
        self.last = self._read()

    @staticmethod
    def _read():
        with open("/proc/stat") as f:
            v = [int(x) for x in f.readline().split()[1:]]
        return v[3] + v[4], sum(v)

    def percent(self):
        idle, total = self._read()
        di, dt = idle - self.last[0], total - self.last[1]
        self.last = (idle, total)
        return 0.0 if dt <= 0 else 100.0 * (1 - di / dt)


class Compare(QDialog):
    """Every translation method side by side (measured numbers, docs/ROADMAP.md)."""
    ROWS = [("Runs on", "Processor", "Processor", "Graphics card", "Internet"),
            ("Memory", "0.5 GB RAM", "1.1 GB RAM", "1.7 GB GPU", "none"),
            ("Download", "included", "1.1 GB", "3.1 GB", "none"),
            ("Per new line", "~0.03 s", "~0.05-0.3 s", "~0.12-0.15 s", "~0.2-0.5 s"),
            ("Menus / UI", "good, literal", "poor (lenslate sends menus to quickmt)", "good", "good"),
            ("Dialogue", "weakest", "good (also adult)", "best", "good"),
            ("Names, context, OCR typos", "no", "no", "yes", "no"),
            ("Languages", "one model per pair", "Japanese → English", "any pair", "any pair"),
            ("Privacy", "local", "local", "local", "text sent to the company"),
            ("Licence", "CC-BY 4.0", "NTT non-commercial", "Gemma terms", "service terms")]

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(_("Compare translation methods"))
        self.resize(940, 380)
        t = QTableWidget(len(self.ROWS), 4)
        t.setHorizontalHeaderLabels(["quickmt", "Sugoi", "Gemma 4 E2B", "Online (Google…)"])
        t.setVerticalHeaderLabels([r[0] for r in self.ROWS])
        for i, r in enumerate(self.ROWS):
            for j, v in enumerate(r[1:]):
                t.setItem(i, j, QTableWidgetItem(v))
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        QVBoxLayout(self).addWidget(t)


# ----------------------------------------------------------------------------------------------- the window
class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(_("lenslate"))
        self.setWindowIcon(app_icon())
        self.resize(1120, 700)
        self.jobs = []
        self.tasks = {}     # running background work by key: {"value": 0-1000 or None (busy), "text": str}
        self.helpbar = QLabel(DEFAULT_HELP)
        self.helpbar.setWordWrap(True)
        self.helpbar.setFixedHeight(58)       # two lines; no layout jumps when the text changes
        self.helpbar.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        set_role(self.helpbar, "helpbar", state="idle")
        self.flt = HelpFilter(self.helpbar)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFrameShape(QFrame.NoFrame)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.installEventFilter(self)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.nav_side = QFrame()
        self.nav_side.setMinimumWidth(52)
        self.nav_side.setMaximumWidth(300)
        self.nav_side.setObjectName("navside")
        nv = QVBoxLayout(self.nav_side)
        nv.setContentsMargins(0, 0, 0, 0)
        nv.setSpacing(0)
        self.nav_toggle = QToolButton()
        self.nav_toggle.setObjectName("navtoggle")
        self.nav_toggle.setIcon(QIcon.fromTheme("sidebar-collapse-left", QIcon.fromTheme("application-menu")))
        if self.nav_toggle.icon().isNull():
            self.nav_toggle.setText("☰")
        self.nav_toggle.clicked.connect(lambda: self.set_nav_collapsed(not self.nav_collapsed, by_user=True))
        nv.addWidget(self.nav_toggle, 0, Qt.AlignLeft)
        nv.addWidget(self.nav, 1)
        from PySide6.QtCore import QSettings
        self.gui_state = QSettings("lenslate", "gui")      # ~/.config/lenslate/gui.conf (window-only state)
        self.nav_user_collapsed = self.gui_state.value("sidebar_collapsed", False, type=bool)
        self.nav_width = self.gui_state.value("sidebar_width", 180, type=int)
        self.nav_collapsed = False
        self.pages = QStackedWidget()
        # options that no longer fit (or were retired, like Careful reading) switch to their fallback before the
        # pages are built, and the help bar says what changed
        startup_changes = enforce_steps()
        if startup_changes:
            QTimer.singleShot(500, lambda: self.say("Changed: " + "; ".join(startup_changes) + "."))
        self.page_specs = (
                ("Overlay", self.page_overlay, "Translate text anywhere on screen: games, browsers, videos, documents."),
                ("Translation", self.page_presets, "Which languages, and how lenslate reads and translates them. The "
                 "panel shows what your choices cost on this PC."),
                ("Models", self.page_models, "Download or remove translation models."),
                ("Games", self.page_games, "Translate inside a game (hooks) and prepare its text in advance."),
                ("Names & fixes", self.page_names, "Character names and game terms, so they are translated the same "
                 "way every time; and translations that came out wrong, to correct or delete."),
                ("Advanced", self.page_advanced, "Everything else, for fine-tuning and troubleshooting."))
        icons = {"Overlay": "\U0001F50D", "Translation": "\U0001F310", "Models": "\U0001F4E6", "Games": "\U0001F3AE",
                 "Names & fixes": "\U0001F3F7\uFE0F", "Advanced": "\u2699\uFE0F"}
        icons = page_icons(icons)
        for name, builder, about in self.page_specs:
            self.nav.addItem(_(name))
            item = self.nav.item(self.nav.count() - 1)
            item.setToolTip(_(about))
            item.setIcon(icons[name])
            self.pages.addWidget(framed(_(name), _(about), builder()))
        for i in range(self.nav.count()):
            self.nav.item(i).setData(Qt.UserRole, self.nav.item(i).text())
        self.set_nav_collapsed(self.nav_user_collapsed)
        self.nav.currentRowChanged.connect(self._page_shown)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.currentRowChanged.connect(lambda i: self.flt.show(self.nav.item(i).toolTip(), "idle"))
        self.nav.setCurrentRow(0)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)
        from PySide6.QtWidgets import QSplitter
        self.split = QSplitter(Qt.Horizontal)      # drag the sidebar's edge: narrower than ~110 px = icons only
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(4)
        self.split.addWidget(self.nav_side)
        self.split.addWidget(self.pages)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.splitterMoved.connect(self._nav_dragged)
        top.addWidget(self.split, 1)
        self.set_nav_collapsed(self.nav_collapsed)     # now that the splitter exists: its first sizes
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top, 1)
        lay.addWidget(self.helpbar)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(2000)
        self.refresh_status()

    NAV_AUTO = 820   # window narrower than this: the sidebar shows icons only (unless you opened it)

    def set_nav_collapsed(self, collapsed, by_user=False):
        """Sidebar with names (180 px) or icons only (52 px). The button's choice is remembered; a narrow window
        also folds it by itself."""
        if by_user:
            self.nav_user_collapsed = collapsed
            self.gui_state.setValue("sidebar_collapsed", collapsed)
        self.nav_collapsed = collapsed
        for i in range(self.nav.count()):
            it = self.nav.item(i)
            name = it.data(Qt.UserRole) or it.text()
            it.setText(("" if not it.icon().isNull() else name[:1]) if collapsed else name)   # no icon: 1 letter
            it.setToolTip(("%s: %s" % (name, self.page_specs[i][2])) if collapsed else self.page_specs[i][2])
        self.nav.setIconSize(QSize(26, 26) if collapsed else QSize(18, 18))
        self.nav.setStyleSheet("")
        if collapsed:      # centred once the strip has its final width (and again on every resize)
            QTimer.singleShot(0, self._centre_nav_icons)
        self.nav_toggle.parentWidget().layout().setAlignment(self.nav_toggle,
                                                              Qt.AlignHCenter if collapsed else Qt.AlignLeft)
        if hasattr(self, "split"):
            total = sum(self.split.sizes()) or self.width()
            side = 58 if collapsed else self.nav_width
            self.split.setSizes([side, max(100, total - side)])
        self.nav_toggle.setToolTip("Show the page names" if collapsed else "Icons only (more room for the page)")

    def _centre_nav_icons(self):
        """Folded sidebar: left padding = half of the free room, measured on the strip as it really is."""
        if not self.nav_collapsed:
            return
        icon = self.nav.iconSize().width()
        pad = max(0, (self.nav.viewport().width() - icon) // 2 - 3)   # the style adds ~3 px inside each item
        css = "QListWidget#nav::item { padding: 0 0 0 %dpx; border-left: none; }" % pad
        if self.nav.styleSheet() != css:
            self.nav.setStyleSheet(css)

    def _nav_dragged(self, _pos, _index):
        w = self.split.sizes()[0]
        if w < 110:
            if not self.nav_collapsed:
                self.set_nav_collapsed(True, by_user=True)
        else:
            self.nav_width = w
            self.gui_state.setValue("sidebar_width", w)
            if self.nav_collapsed:
                self.set_nav_collapsed(False, by_user=True)

    def eventFilter(self, obj, ev):
        if obj is getattr(self, "nav", None) and ev.type() == QEvent.Resize:
            QTimer.singleShot(0, self._centre_nav_icons)
        return super().eventFilter(obj, ev)

    def resizeEvent(self, ev):
        auto = ev.size().width() < self.NAV_AUTO
        want = self.nav_user_collapsed or auto
        if hasattr(self, "nav_toggle") and want != self.nav_collapsed:
            self.set_nav_collapsed(want)
        super().resizeEvent(ev)

    def rebuild_pages(self):
        """After a setting changed: build the shown page again now (keeping its scroll position); the other pages
        are built again when they are opened (building all of them made every click freeze for ~0.5 s)."""
        self.stale = set(range(self.pages.count()))
        self._rebuild_page(self.pages.currentIndex())
        self.refresh_status()

    def _page_shown(self, i):
        if i in getattr(self, "stale", set()):
            self._rebuild_page(i)
            self.refresh_status()      # the Overlay page's status widgets are new: fill them now

    def _rebuild_page(self, i):
        if i < 0:
            return
        self.stale.discard(i)
        old = self.pages.widget(i)
        a = old.findChild(QScrollArea)
        pos = a.verticalScrollBar().value() if a is not None else 0
        name, builder, about = self.page_specs[i]
        new = framed(name, about, builder())
        self.pages.blockSignals(True)
        self.pages.insertWidget(i, new)
        self.pages.removeWidget(old)
        self.pages.setCurrentIndex(self.nav.currentRow())
        self.pages.blockSignals(False)
        old.deleteLater()

        def restore():
            b = new.findChild(QScrollArea)
            if b is not None:
                b.verticalScrollBar().setValue(pos)
        QTimer.singleShot(0, restore)
        QTimer.singleShot(60, restore)     # again once the page has its final height

    def rebuild_all_pages(self):
        """After a preset: build the pages again so every control shows the new settings."""
        cur = self.pages.currentIndex()
        pos = []
        for i in range(self.pages.count()):
            a = self.pages.widget(i).findChild(QScrollArea)
            pos.append(a.verticalScrollBar().value() if a is not None else 0)
        while self.pages.count():
            w = self.pages.widget(0)
            self.pages.removeWidget(w)
            w.deleteLater()
        for name, builder, about in self.page_specs:
            self.pages.addWidget(framed(name, about, builder()))
        self.pages.setCurrentIndex(cur)

        def restore():
            for i, v in enumerate(pos):
                if i < self.pages.count():
                    a = self.pages.widget(i).findChild(QScrollArea)
                    if a is not None:
                        a.verticalScrollBar().setValue(v)
        QTimer.singleShot(0, restore)
        QTimer.singleShot(60, restore)     # again once the new page has its final height
        self.refresh_status()

    def pick_preset(self, name, check=True):
        self._click_log("preset %s" % name)
        if self.measuring():
            self.rebuild_pages()
            return
        if check and not self.preset_fits(name):
            self.rebuild_pages()   # the clicked button/card goes back to the current preset
            return
        cfgmod.apply_preset(name)
        p = cfgmod.PRESETS[name]
        # (no command to the running overlay: it follows config.toml within 2 s, and only one program writes the file)
        self.rebuild_pages()
        self.say(_("%s preset. %s Trade-off: %s") % (p["label"], p["summary"], p["tradeoff"]))
        QTimer.singleShot(0, self.offer_model)

    def preset_fits(self, name):
        """Hardware check (roadmap step 5): warn and ask; never switch by itself. True = go ahead with this preset."""
        import hwcheck
        problems = hwcheck.check(name, downloads=False)
        if not problems:
            return True
        rec, _why = hwcheck.recommend()
        label = cfgmod.PRESETS[name]["label"]
        box = QMessageBox(QMessageBox.Warning, "Check this preset", "%s may not suit this PC:\n\n%s" % (
            label, "\n\n".join("• " + t for t in problems)), parent=self)
        keep = set_role(box.addButton("Use %s anyway" % label, QMessageBox.AcceptRole), "secondary")
        alt = set_role(box.addButton("Use %s instead" % cfgmod.PRESETS[rec]["label"], QMessageBox.ActionRole),
                       "primary") if rec != name else None
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is keep:
            return True
        if alt is not None and box.clickedButton() is alt:
            QTimer.singleShot(0, lambda: self.pick_preset(rec, check=False))
        return False

    def run_setup(self):
        import setup
        ok, measure = setup.run(self)
        enforce_steps()     # the setup may have changed the languages
        self.rebuild_pages()
        if ok:
            p = cfgmod.PRESETS.get(cfgmod.current_preset())
            self.say(_("Setup done%s.") % (": %s preset" % p["label"] if p else ""))
            if measure:
                self.nav.setCurrentItem(self.nav.findItems("Translation", Qt.MatchFixedString)[0])
                self.run_benchmark()
        else:
            self.say(_("Setup closed; nothing changed. Translation page > Run setup again brings it back."))

    def first_launch(self):
        """Setup window the first time; afterwards the older one-question checks."""
        if not cfgmod.get("general.setup_done"):
            self.run_setup()
            return
        self.offer_model()     # the preset needs the language model but it is not downloaded
        self.maybe_benchmark()   # new hardware: ask, then measure this PC

    def offer_model(self):
        """The preset needs the language model but it is not downloaded: offer it, or use Light."""
        import models
        if cfgmod.get("translator.kind") != "llm":
            return
        m = models.find(cfgmod.get("translator.llm_model"))
        if m is None or m.installed():
            return
        r = QMessageBox.question(self, "Download the language model?",
                                 "This preset translates with %s (%.1f GB download, about %.1f GB of GPU memory).\n\n"
                                 "Download it now? If not, lenslate uses the No GPU preset: the cheapest translator "
                                 "on the processor, with word-for-word translations." % (m.title, m.size_gb, m.vram_gb or 0))
        if r == QMessageBox.Yes:
            self.nav.setCurrentItem(self.nav.findItems("Models", Qt.MatchFixedString)[0])   # download runs there
            self._model_action(m)
        else:
            self.pick_preset("nogpu")

    def error(self, text):
        self.flt.show(text, "error")

    def say(self, text):
        """A status message in the help bar (normal text)."""
        self.flt.pending = None
        self.flt.show(text, "help")

    # ------------------------------------------------------------------------------------------- overlay page
    def page_overlay(self):
        f = self.flt
        import shortcutsdialog
        keys = shortcutsdialog.keys_now()
        hot = lambda a: "Hotkey: %s." % shortcutsdialog.key_text(a, keys)   # noqa: E731
        # one indicator + one button: the button always says what it will do
        self.run_dot = QLabel()
        self.run_text = QLabel()
        explain(self.run_dot, "Green = lenslate is running (it can translate the moment you pick an area). "
                "Grey = stopped: it uses no memory, and the hotkeys or Pick area start it again.", f)
        explain(self.run_text, "What the overlay is doing right now. It updates every 2 seconds.", f)
        self.run_text.setWordWrap(True)
        self.run_btn = QPushButton()
        self.run_btn.setMinimumWidth(140)
        self.run_btn.clicked.connect(self.toggle_running)
        self.status_card = card_frame()
        srow = QHBoxLayout(self.status_card)
        srow.setContentsMargins(12, 10, 12, 10)
        srow.addWidget(self.run_dot)
        srow.addWidget(self.run_text, 1)
        srow.addWidget(self.run_btn)

        b_select = explain(QPushButton(_("Pick area…")), "Drag a box around the text you want translated: a game's "
                           "dialogue box, a video's subtitles, part of a web page, a PDF, or the whole screen. "
                           "Smaller areas are read faster. " + hot("select"), f)
        b_select.clicked.connect(lambda: send("select") or run_lenslate("select"))
        self.b_now = explain(QPushButton(_("Translate now")), "Read the whole chosen area again and translate it. "
                             "Lines translated before come from the cache instantly. " + hot("now"), f)
        self.b_now.clicked.connect(lambda: (send("now"), self.refresh_status()))
        self.b_toggle = explain(QPushButton(_("Show / hide")), "Hide the translation cards (automatic translation "
                                "pauses while hidden), or show them again. " + hot("toggle"), f)
        self.b_toggle.clicked.connect(lambda: (send("toggle"), self.refresh_status()))
        self.b_reset = explain(QPushButton(_("Forget area")), "Remove the cards and forget the chosen area.", f)
        self.b_reset.clicked.connect(lambda: (send("reset"), self.refresh_status()))
        self.auto_box = explain(QCheckBox(_("Keep translating automatically")),
                                "Check the area again and again (every 'Auto-refresh interval' seconds) and translate "
                                "new text as it appears. Only the parts that changed are read again, so it costs "
                                "little while nothing changes. Pick an area first. " + hot("auto"), f)
        self.auto_box.clicked.connect(self.toggle_auto)
        self.b_select = b_select
        row2 = FlowLayout(hspacing=8, vspacing=8)
        for b in (b_select, self.b_now, self.b_toggle, self.b_reset):
            row2.addWidget(set_role(b, "secondary"))
            b.setMinimumWidth(120)
        self.area_hint = hint(_("Pick an area to use the other buttons."))

        op = cfgmod.BY_KEY["overlay.opacity"]
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(10, 100)
        self.opacity.setValue(int(round(cfgmod.get("overlay.opacity") * 100)))
        self.opacity_label = QLabel(_("%d%%") % self.opacity.value())
        self.opacity.valueChanged.connect(lambda v: (self.opacity_label.setText(_("%d%%") % v),
                                                     save("overlay.opacity", v / 100, self.error)))
        explain(self.opacity, "%s: %s" % (op.label, op.help), f)
        self.opacity.setFixedWidth(320)
        orow = QHBoxLayout()
        orow.setContentsMargins(0, 0, 0, 0)
        orow.addWidget(self.opacity)
        orow.addWidget(self.opacity_label)
        orow.addStretch(1)

        refresh = form([(cfgmod.BY_KEY[k].label, setting_widget(k, f, self.error))
                        for k in ("refresh.interval", "refresh.settle_step", "refresh.settle_max")])
        sec = section_label("Translate what is on screen")
        explain(sec, "Works on anything on screen: games, browsers, video players, PDF and image viewers, the "
                "desktop. The buttons below have hotkeys for use inside a game: Keyboard shortcuts changes them.", f)
        b_keys = explain(set_role(QPushButton(_("Keyboard shortcuts…")), "quiet"),
                         "See and change the hotkeys of Pick area, Translate now, Keep translating and Show / hide. "
                         "lenslate checks that a key is free before it uses it.", f)
        b_keys.clicked.connect(self.edit_shortcuts)
        sec_row = QWidget()
        sl = QHBoxLayout(sec_row)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(sec)
        sl.addStretch(1)
        sl.addWidget(b_keys, 0, Qt.AlignBottom)
        sec_row.setMaximumWidth(CONTENT_W)
        # shown under the status bar while lenslate runs (the moment the player is about to use it), until "Got it"
        self.read_tip = QFrame()
        set_role(self.read_tip, "tip")
        self.read_tip.setMaximumWidth(CONTENT_W)
        tl = QHBoxLayout(self.read_tip)
        tl.setContentsMargins(12, 8, 8, 8)
        tip_text = QLabel(_("<b>Tip:</b> in the game's settings, a solid text-box background, bigger text and the "
                          "standard font make lenslate read faster and make fewer mistakes."))
        tip_text.setWordWrap(True)
        explain(tip_text, " ".join("%s: %s" % (t, full) for t, _short, full in READING_TIPS), f)
        tip_ok = set_role(QPushButton(_("Got it")), "quiet")
        explain(tip_ok, "Hide this tip for good (Advanced > Overlay brings it back).", f)
        tip_ok.clicked.connect(lambda: (save("overlay.reading_tip", False, self.error), self.read_tip.hide()))
        tl.addWidget(tip_text, 1)
        tl.addWidget(tip_ok, 0, Qt.AlignVCenter)
        self.read_tip.setVisible(False)
        look = form([("Card opacity", self._wrap(orow)),
                     ("Placeholder cards", setting_widget("overlay.placeholder", f, self.error))])
        return page(self.status_card, self.read_tip, sec_row, row2, self.area_hint, self.auto_box,
                    section_label("Cards"), look,
                    section_label("When to look again"), refresh,
                    *self._capture_section())

    def _capture_section(self):
        """How lenslate sees the screen on this desktop, with the advice that goes with it (captureinfo.py)."""
        import captureinfo
        method = captureinfo.platform()
        g = captureinfo.guide(method)
        sec = section_label("How lenslate sees the screen")
        explain(sec, "The capture method depends on your desktop (Advanced > Screen capture method can force the "
                "screen-sharing portal). Full guide: docs/CAPTURE.md.", self.flt)
        body = note(_("<b>%s.</b> %s<ul style='margin-left:-18px'>%s</ul>") % (
            g["title"], g["summary"], "".join("<li>%s</li>" % t for t in g["tips"])), CONTENT_W)
        out = [sec, body]
        if method == "portal":
            b = set_role(QPushButton(_("Choose what to share…")), "secondary")
            explain(b, "Ask your desktop again which window or screen lenslate may see (same as `lenslate "
                    "share`). lenslate must be running.", self.flt)
            b.clicked.connect(lambda: self.say(send("share") or "lenslate is not running: start it first."))
            b.setMaximumWidth(220)
            out.append(b)
        return out

    def toggle_running(self):
        if self.run_btn.text() == "Restart lenslate":
            send("quit")
            QTimer.singleShot(1200, lambda: run_lenslate("translator"))
            self.run_text.setText(_("Restarting…"))
            QTimer.singleShot(3500, self.refresh_status)
            return
        if send("status", 400) is None:
            run_lenslate("translator")    # starts the overlay without asking for an area
            self.run_text.setText(_("Starting…"))
        else:
            send("quit")
            self.run_text.setText(_("Stopping…"))
        QTimer.singleShot(1500, self.refresh_status)

    def edit_shortcuts(self):
        import shortcutsdialog
        shortcutsdialog.ShortcutsDialog(self, on_saved=lambda keys: self.say(
            "Hotkeys saved: " + ", ".join("%s %s" % (k, a) for a, k in keys.items() if k))).exec()

    def toggle_auto(self):
        send("auto")
        self.refresh_status()

    def refresh_status(self):
        r = send("status", 600)
        st = None
        if r is not None:
            try:
                st = json.loads(r)
            except ValueError:
                st = {}
        running = st is not None
        self.read_tip.setVisible(running and bool(cfgmod.get("overlay.reading_tip")))
        self.run_dot.setText("●")   # green = running, grey = stopped (the text next to it says it too)
        self.run_dot.setStyleSheet("color: %s; font-size: 16pt;" % theme.color("success_text" if running else "text_muted"))
        self.run_btn.setText(_("Stop lenslate") if running else _("Start lenslate"))
        set_role(self.run_btn, "secondary" if running else "primary")
        tip = ("Stop the overlay completely and free its memory, including the language model's GPU memory."
               if running else "Start the overlay in the background. Nothing is read until you pick an area.")
        if self.run_btn.property("help") != tip:   # (installing the hover filter again every 2 s piled them up)
            explain(self.run_btn, tip, self.flt)
        has_area = bool(st and st.get("region"))
        for w in (self.b_now, self.b_toggle, self.b_reset):
            w.setEnabled(has_area)
        self.auto_box.setEnabled(has_area)
        self.area_hint.setVisible(not has_area)
        # one main action: Pick area while nothing is picked and lenslate runs
        set_role(self.b_select, "primary" if running and not has_area else "secondary")
        set_role(self.status_card, state="warning" if (running and st and st.get("stale")) else "")
        self.auto_box.setChecked(bool(st and st.get("auto")) and has_area)
        if running and st and st.get("stale"):
            self.run_text.setText(_("⚠ Running an older version of lenslate: restart it to use the new one"))
            self.run_btn.setText(_("Restart lenslate"))
            set_role(self.run_btn, "primary")
            explain(self.run_btn, "lenslate was updated while it was running. Restart it so it uses the new version "
                    "(an older running version can overwrite newer settings).", self.flt)
            return
        if not running:
            self.run_text.setText(_("Stopped"))
        elif not st:
            self.run_text.setText(_("Running (an older version: restart it to see its state)"))
        else:
            area = "no area picked" if not has_area else "area %d×%d on %s" % (
                st["region"][2], st["region"][3], st.get("screen") or "screen")
            self.run_text.setText(_("Running · %s · %s · %s%s") % (
                area, "cards hidden" if st.get("hidden") else "cards shown", st.get("translator"),
                " · working…" if st.get("busy") else ""))

    # ------------------------------------------------------------------------------------------- presets page
    def _preset_row(self):
        """Three presets by how much of the PC lenslate may use; 'Custom' when the steps below match none."""
        f = self.flt
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        head = QHBoxLayout()
        sec = section_label("Preset")
        explain(sec, "<b>A quick start: how much of your PC lenslate may use.</b><br><i>Each preset sets the steps "
                "below; change any step to make your own combination (Custom). Your language model choice is "
                "kept.</i>", f)
        head.addWidget(sec)
        head.addStretch(1)
        v.addLayout(head)
        row = FlowLayout(hspacing=0, vspacing=6)
        cur = cfgmod.current_preset()
        blocked = option_blocks()
        group = QButtonGroup(w)
        group.setExclusive(True)
        buttons = []
        for name in cfgmod.PRESET_ORDER:
            p = cfgmod.PRESETS[name]
            b = QPushButton(p["label"] + (" (recommended)" if name == "balanced" else ""))
            b.setCheckable(True)
            b.setChecked(name == cur)
            why = blocked.get(("ocr.gpu", "all")) if p["values"].get("ocr.gpu") == "all" else None
            if why:
                b.setEnabled(False)
            explain(b, "%s<b>%s</b><br><i>Trade-off: %s</i>" % ("<b>⚠ %s</b><br>" % why if why else "",
                                                                 p["summary"], p["tradeoff"]), f)
            group.addButton(b)
            if name != cur:
                b.clicked.connect(lambda _c=False, n=name: self.pick_preset(n))
            buttons.append(b)
            row.addWidget(b)
        mine = self._custom_steps()
        if cur == "custom":     # remember the user's own combination, so the Custom button can bring it back
            now = cfgmod.values_of("current")
            self.gui_state.setValue("custom_steps", json.dumps({k: now[k] for k in ("ocr.reading", "ocr.gpu",
                                                                                     "translator.kind")}))
            mine = self._custom_steps()
        c = QPushButton(_("Custom"))
        c.setCheckable(True)
        c.setChecked(cur == "custom")
        c.setEnabled(cur == "custom" or mine is not None)
        explain(c, "<b>Your own combination of the steps below.</b><br><i>Ticked by itself whenever the steps "
                "match no preset. Click it to go back to the combination you made last%s.</i>" % (
                    " (%s)" % self._describe_steps(mine) if mine else ": none yet"), f)
        group.addButton(c)
        if cur != "custom" and mine is not None:
            c.clicked.connect(self.restore_custom)
        buttons.append(c)
        row.addWidget(c)
        theme.segment_row(buttons)
        holder = QWidget()
        holder.setLayout(row)
        v.addWidget(holder)
        return w

    def _custom_steps(self):
        try:
            d = json.loads(self.gui_state.value("custom_steps", "") or "null")
        except ValueError:
            return None
        return d if isinstance(d, dict) and d else None

    @staticmethod
    def _describe_steps(d):
        names = {k: {v: lab for v, lab, _t in opts} for _title, k, opts in STEPS}
        return ", ".join(names[k].get(v, v) for k, v in d.items() if k in names)

    def restore_custom(self):
        d = self._custom_steps()
        if not d:
            return
        self._click_log("custom -> %s" % d)
        cfgmod.set_many(d)
        changed = enforce_steps()     # e.g. the languages changed since: an option that no longer fits
        self.rebuild_pages()
        self.say(_("Custom: %s.%s") % (self._describe_steps(d), (" Switched: " + "; ".join(changed)) if changed else ""))

    def languages_changed(self):
        changed = enforce_steps()
        self.rebuild_pages()
        if changed:
            self.say("Switched because of the languages: " + "; ".join(changed) + ".")

    def _steps_box(self, extra=None):
        """The three steps. Each title has a "?" that shows how the chosen option works (hovering any option
        shows its text in the help bar too); option buttons wrap when the box is narrow. Options the languages or
        this PC cannot use are greyed out with the reason."""
        f = self.flt
        if not hasattr(self, "_help_open"):
            self._help_open = set()
        box = card_frame()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(14)
        head = set_role(QLabel(_("How it reads and translates")), "section")
        explain(head, "Two choices: how text is read (and on which chip: CPU or GPU), and who translates. Hover an "
                "option, or press ?, to see how it works and what it costs; the panel estimates the speed of the "
                "whole combination on this PC.", f)
        lay.addWidget(head)
        blocked = option_blocks()

        def segment(key, options, cur, short=None):
            """Buttons of one choice; returns (buttons, text of the current option). One exclusive group: a click
            on the option already chosen does nothing (it used to untick it until the page was rebuilt)."""
            group = QButtonGroup(box)
            group.setExclusive(True)
            buttons, now, now_label = [], "", ""
            for val, label, text in options:
                if (key, val) == ("translator.kind", "llm"):
                    text = llm_description()
                b = QPushButton((short or {}).get(val, label))
                b.setCheckable(True)
                b.setChecked(val == cur)
                why = blocked.get((key, val))
                if why:
                    b.setEnabled(False)
                text = rich(key, val, text, why)
                buttons.append(b)
                explain(b, ("<b>%s</b><br>%s" % (label, text)) if short else text, f)
                if val == cur:
                    now = text
                    now_label = label
                group.addButton(b)
                if val != cur:
                    b.clicked.connect(lambda _c=False, k=key, v=val: self.set_step(k, v))
            theme.segment_row(buttons)
            return buttons, now, now_label

        def titled(what, label, text):
            """One '?' paragraph, headed by the button it explains."""
            return "<span style='color:%s'><b>%s: %s</b></span><br>%s" % (theme.color("accent_text"), what, label, text)

        where = next(s for s in STEPS if s[1] == "ocr.gpu")
        shown = [s for s in STEPS if s[1] != "ocr.gpu"]   # where reading runs = the CPU | GPU switch on Reading
        for row, (title, key, options) in enumerate(shown):
            cur = cfgmod.get(key)
            options = [o for o in options if (key, o[0]) not in RETIRED]
            right = QVBoxLayout()
            right.setSpacing(6)
            trow = QHBoxLayout()
            trow.setSpacing(6)
            trow.addWidget(QLabel(_("<span style='color:%s'><b>%d</b></span>&nbsp;&nbsp;<b>%s</b>") % (
                theme.color("accent"), row + 1, title)))
            q = QToolButton()
            q.setText("?")
            q.setCheckable(True)
            q.setChecked(key in self._help_open)
            q.setAutoRaise(True)
            explain(q, "Show or hide how the chosen option works.", f)
            trow.addWidget(q)
            trow.addStretch(1)
            right.addLayout(trow)
            buttons, now, now_label = segment(key, options, cur)
            seg = FlowLayout(hspacing=0, vspacing=6)
            for b in buttons:
                seg.addWidget(b)
            texts = [titled("Reading mode" if key == "ocr.reading" else title, now_label, now)]
            if key == "ocr.reading":
                g = cfgmod.get("ocr.gpu")
                g = "off" if g == "reader" else g      # (reader-only is an Advanced setting: reads like CPU here)
                sw, gtext, glabel = segment("ocr.gpu", where[2], g, short={"off": "CPU", "all": "GPU"})
                texts.append(titled("Runs on", "%s (%s)" % (glabel, "GPU" if g == "all" else "CPU"), gtext))
                line = QHBoxLayout()
                line.setSpacing(16)
                holder = QWidget()
                holder.setLayout(seg)
                line.addWidget(holder, 1)
                swl = QHBoxLayout()
                swl.setSpacing(0)
                for b in sw:
                    b.setMinimumWidth(56)
                    swl.addWidget(b)
                line.addLayout(swl)
                line.setAlignment(swl, Qt.AlignTop)
                right.addLayout(line)
            else:
                right.addLayout(seg)
            how = hint("<br><br>".join(texts))
            how.setMaximumWidth(16777215)   # a width cap made the layout plan too few lines (text cut off)
            how.setVisible(key in self._help_open)
            q.toggled.connect(lambda on, k=key, how=how: (how.setVisible(on), self._help_open.add(k) if on
                                                          else self._help_open.discard(k)))
            right.addWidget(how)
            if key == "translator.kind" and extra is not None:
                right.addWidget(extra)
            lay.addLayout(right)
        lay.addStretch(1)     # beside a taller panel: the extra room goes below the steps, not between them
        return box

    def _click_log(self, text):
        """~/.cache/lenslate/gui-clicks.log: each step / preset click and what was saved (kept small)."""
        try:
            os.makedirs(cfgmod.CACHE_DIR, exist_ok=True)
            path = os.path.join(cfgmod.CACHE_DIR, "gui-clicks.log")
            if os.path.exists(path) and os.path.getsize(path) > 200 * 1024:
                os.replace(path, path + ".old")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("%s %s\n" % (time.strftime("%H:%M:%S"), text))
        except OSError:
            pass

    def set_step(self, key, value):
        """One step changed by hand: check what it needs (download, hardware), then save it."""
        if self.measuring():
            self._click_log("click %s=%s ignored: measuring" % (key, value))
            self.rebuild_pages()
            return
        self._click_log("click %s=%s (was %s)" % (key, value, cfgmod.get(key)))
        QTimer.singleShot(0, lambda: self._click_log("  saved %s=%s" % (key, cfgmod.get(key))))
        import models
        if key == "ocr.gpu" and value == "all":
            import ocrgpu
            ok = ocrgpu.installed()
            self._click_log("  graphics-card reader installed: %s" % ok)
            if not ok:
                if QMessageBox.question(self, "Download the graphics-card reader?", "Reading on the graphics card "
                                        "needs the CUDA build of the text reader: a one-time 3.4 GB download.\n\n"
                                        "Download it now?") != QMessageBox.Yes:
                    self._click_log("  download declined: GPU not switched on")
                    self.rebuild_pages()
                    return
                if "ocrgpu" in self.tasks:
                    self.say(_("The graphics-card reader is still downloading…"))
                    return
                self.say(_("Downloading the graphics-card reader (3.4 GB; no progress is shown, it can "
                                     "take a few minutes)…"))
                job = self.start_job(Job(lambda progress: ocrgpu.install()), "ocrgpu")
                job.finished_ok.connect(lambda _r: (cfgmod.set("ocr.gpu", "all"), self.rebuild_pages(),
                                                    self.say(_("The graphics-card reader is installed."))))
                job.failed.connect(lambda e: (self.error("Graphics-card reader: " + e), self.rebuild_pages()))
                job.start()
                return
        if key == "translator.kind" and value == "sugoi":
            m = models.BY_NAME["sugoi-v4-ja-en"]
            if not m.installed():
                if QMessageBox.question(self, "Download Sugoi?", "Visual novel (quickmt + Sugoi) needs Sugoi (1.1 GB, NTT "
                                        "non-commercial licence).\n\nDownload it now?") != QMessageBox.Yes:
                    self.rebuild_pages()
                    return
                self.nav.setCurrentItem(self.nav.findItems("Models", Qt.MatchFixedString)[0])
                self._model_action(m)
        save(key, value, self.error)
        self.rebuild_pages()
        if key == "translator.kind":
            QTimer.singleShot(0, self.offer_model)   # the language model is not downloaded yet: offer it
        p = cfgmod.PRESETS.get(cfgmod.current_preset())
        self.say(_("Now: %s.") % (p["label"] + " preset" if p else "Custom (your own combination)"))

    def page_presets(self):
        """The Translation page: languages first (everything else depends on them), then the three steps with
        this PC's live usage and an estimate for exactly those steps, then the language model and online options."""
        import bench
        import hwcheck
        f = self.flt
        self.bench = bench.load()
        b_cmp = explain(QPushButton(_("Compare all…")), "Every translation method side by side: where it runs, memory, "
                        "download, speed, menus, dialogue, names, languages, privacy and licence.", f)
        b_cmp.clicked.connect(lambda: Compare(self).exec())
        b_setup = explain(QPushButton(_("Run setup again…")), "The first-launch setup: languages, settings that fit "
                          "this PC (with a hardware check), and the downloads they need.", f)
        b_setup.clicked.connect(self.run_setup)
        self._head_buttons = [set_role(b_cmp, "quiet"), set_role(b_setup, "quiet")]

        pc = card_frame("panel")
        pc.setMinimumWidth(250)
        pc.setMaximumWidth(300)
        rl = QVBoxLayout(pc)
        rl.setContentsMargins(14, 12, 14, 14)
        rl.setSpacing(4)
        hw = bench.hardware()
        g = hwcheck.best_gpu()
        rl.addWidget(set_role(QLabel(_("Your PC")), "section"))
        rl.addWidget(explain(hint(_("%s<br>%s") % (hw["cpu"], ("%s, %.0f GB" % (g["name"], g["vram_mb"] / 1024))
                                                 if g and g["dedicated"] else ("integrated %s graphics" % g["vendor"])
                                                 if g else "no graphics card found")),
                             "The processor and graphics card lenslate found. Live graphics-card usage below needs "
                             "an NVIDIA card (nvidia-smi).", f))
        self.bench_label = QLabel()
        self.bench_label.setWordWrap(True)
        self.bench_label.setVisible(False)
        self.bench_bar = set_role(QProgressBar(), "thin")
        self.bench_bar.setRange(0, 100)
        self.bench_bar.setTextVisible(False)
        self.bench_bar.setVisible(False)
        rl.addSpacing(8)   # at the top: the panel bottom is often below the fold
        rl.addWidget(self.bench_label)
        rl.addWidget(self.bench_bar)
        self.cpu_lab, self.gpu_lab, self.vram_lab = QLabel(_("Processor")), QLabel(_("Graphics card")), QLabel(_("GPU memory"))
        rl.addSpacing(6)
        for lab, tip in ((self.cpu_lab, "How busy the processor is right now (all programs)."),
                         (self.gpu_lab, "How busy the graphics card is right now (all programs)."),
                         (self.vram_lab, "Graphics-card memory in use right now (all programs).")):
            rl.addWidget(explain(lab, tip, f))
        rl.addSpacing(14)
        self.est_label = QLabel()
        self.est_label.setWordWrap(True)
        rl.addWidget(explain(self.est_label, "<b>How long until the translation shows, with the choices on the left, "
                             "measured on this PC.</b><br><i>Per new dialogue line: a small text box, where the reading "
                             "mode hardly matters; the translator does. Whole screen: a menu (8 lines), a settings "
                             "screen (28) and a wall of text (40), read whole. Best = every line was translated "
                             "before (only reading); typical = half the lines are new; worst = every line is new. A "
                             "busy game or other programs make it slower.</i>", f))
        measuring = self.measuring()
        b_measure = explain(QPushButton("Measuring…" if measuring else "Measure again"), "Measure again how fast "
                            "this PC reads and translates (about 1-2 minutes): a dialogue box and three whole screens, read in every "
                            "reading mode on the processor and the graphics card, then four lines with every installed "
                            "translator. The steps on the left are locked until it is done.", f)
        b_measure.setEnabled(not measuring)
        b_measure.clicked.connect(self.run_benchmark)
        rl.addSpacing(8)
        rl.addWidget(set_role(b_measure, "secondary"))
        rl.addStretch(1)

        langs_w, extra_w = self._translation_settings()
        presets_w = self._preset_row()
        steps_w = fit_height(self._steps_box(extra_w))
        mid = Reflow(steps_w, pc)
        outer = QWidget()
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(16)
        ov.addWidget(langs_w)
        ov.addWidget(presets_w)
        ov.addWidget(mid)
        self.cpu_meter = CpuMeter()
        if not hasattr(self, "usage_timer"):
            self.usage_timer = QTimer(self)
            self.usage_timer.timeout.connect(self.sample_usage)
            self.usage_timer.start(1000)
        self.presets_widget = outer
        if measuring:       # a click now would change what is being measured (and the numbers it shows)
            for w in (langs_w, presets_w, steps_w, *self._head_buttons[1:]):
                w.setEnabled(False)
        self._show_bench_state()
        self.show_estimate()
        area = page(outer, wide=True)
        return area

    def show_estimate(self):
        """What the steps chosen now cost on this PC."""
        import bench
        import hwcheck
        if not hasattr(self, "est_label"):
            return
        v = cfgmod.values_of("current")
        name = cfgmod.current_preset()
        title = ("Same as the %s preset" % cfgmod.PRESETS[name]["label"]) if name in cfgmod.PRESETS else "These settings"
        fs = theme.tokens()["fs_section"]
        lines = ["<b>%s</b>" % title]
        est = bench.estimate("current", self.bench)
        if v["translator.kind"] == "online":
            lines.append("speed: depends on the online service and your connection")
        elif est is not None:
            lines.append("<span style='font-size:%spt'><b>≈ %.2f s</b></span> per new dialogue line" % (fs, est))
        work = bench.cpu_work("current", self.bench)
        if work is not None:
            lines.append("processor work per read: %.2f s" % work)
        elif self.bench is None:
            lines.append("speed: not measured yet (Measure again)")
        elif bench._ocr_key(v, "ocr") not in self.bench:
            lines.append("speed: not measured yet for this reading (Measure again)")
        needs = hwcheck.preset_needs("current")
        need = needs["vram_gb"]
        gnow = bench.gpu_now()
        if needs.get("custom_model"):
            lines.append("GPU memory: depends on %s%s" % (needs["custom_model"], (
                " (+ ~%.1f GB for reading)" % need) if need else ""))
        elif need:
            if gnow:
                free = (gnow[2] - gnow[1]) / 1024
                ok = free >= need + 0.5
                lines.append(("<span style='color:%s'>✓ GPU memory: needs ~%%.1f GB, %%.1f GB free now</span>"
                              % theme.color("success_text") if ok else
                              "<span style='color:%s'>⚠ GPU memory: needs ~%%.1f GB, only %%.1f GB free now</span>"
                              % theme.color("warning_text")) % (need, free))
            else:
                lines += ["<span style='color:%s'>⚠ %s</span>" % (theme.color("warning_text"), t)
                          for t in hwcheck.check("current", downloads=False)]
        else:
            lines.append("no graphics-card memory used")
        sc = bench.scene_estimates(v, self.bench)
        if sc:
            def cell(x):
                return "–" if x is None else ("%.1f" % x)
            rows = "".join("<tr><td>%s</td><td align='right'>%s</td><td align='right'>%s</td>"
                           "<td align='right'>%s</td></tr>" % (t, cell(b), cell(m), cell(w)) for t, _n, b, m, w in sc)
            lines.append("<br><b>Whole screen, seconds</b><table cellspacing='0' cellpadding='2'>"
                         "<tr><td></td><td><i>best</i></td><td><i>typical</i></td><td><i>worst</i></td></tr>%s</table>"
                         % rows)
        elif self.bench is not None:
            lines.append("<br>whole screens: not measured yet (Measure again)")
        dl = hwcheck.missing_downloads("current")
        if dl:
            lines.append("<span style='color:%s'>needs a download: %s</span>" % (
                theme.color("warning_text"), ", ".join("%s (%.1f GB)" % x for x in dl)))
        self.est_label.setText("<br>".join(lines))

    def sample_usage(self):
        import bench
        if not hasattr(self, "cpu_lab") or self.pages.currentWidget() is None:
            return
        try:   # only while the Translation page is shown
            if not self.pages.currentWidget().isAncestorOf(self.presets_widget):
                self.cpu_meter.percent()
                return
        except RuntimeError:   # page rebuilt
            return
        c = self.cpu_meter.percent()
        self.cpu_lab.setText(_("Processor %d%%") % c)
        g = bench.gpu_now()
        if g:
            self.gpu_lab.setText(_("Graphics card %d%%") % g[0])
            self.vram_lab.setText(_("GPU memory %.1f / %.1f GB") % (g[1] / 1024, g[2] / 1024))

    def maybe_benchmark(self):
        """First launch (or new hardware): say what will happen, then measure - or later."""
        import bench
        if bench.load() is not None or getattr(self, "bench_asked", False):
            return
        self.bench_asked = True
        r = QMessageBox.question(
            self, "Measure this PC?",
            "lenslate will now measure how fast this PC reads and translates text, so the Translation page can show real "
            "numbers for your processor and graphics card.\n\nIt takes about 1-2 minutes. The processor is busy "
            "for a moment, and the language model (if downloaded) is loaded onto the graphics card briefly.\n\n"
            "Measure now? (You can also do it later on the Translation page.)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if r == QMessageBox.Yes:
            self.nav.setCurrentItem(self.nav.findItems("Translation", Qt.MatchFixedString)[0])
            self.run_benchmark()

    def start_job(self, job, key=None):
        """Run a Job. With a key it is listed in self.tasks until it ends, so a page built meanwhile can show its
        progress bar and keep its button locked (the widgets a job started with may be gone by then)."""
        if key is not None:
            self.tasks[key] = {"value": None, "text": ""}

        def gone(*_a):
            if key is not None:
                self.tasks.pop(key, None)
            if job in self.jobs:
                self.jobs.remove(job)
        job.finished_ok.connect(gone)      # connected first: the task is over before the caller's handlers run
        job.failed.connect(gone)
        self.jobs.append(job)
        return job

    @staticmethod
    def show_task(st, bar, buttons=()):
        """Draw one task's state (an entry of self.tasks, or None = not running) on a page's widgets."""
        try:
            for b in buttons:
                b.setEnabled(st is None)
            bar.setVisible(st is not None)
            if st is None:
                return
            if st["value"] is None:
                bar.setRange(0, 0)
            else:
                bar.setRange(0, 1000)
                bar.setValue(int(st["value"]))
            bar.setFormat(st["text"] or "%p%")
        except RuntimeError:      # the page (and its widgets) was just replaced
            pass

    def measuring(self):
        return getattr(self, "bench_state", None) is not None and self.bench_state["phase"] == "running"

    def _show_bench_state(self):
        """Fill the current page's progress bar from self.bench_state (a page rebuild makes a new bar)."""
        st = getattr(self, "bench_state", None)
        bar, lab = getattr(self, "bench_bar", None), getattr(self, "bench_label", None)
        if bar is None or lab is None:
            return
        try:
            bar.setVisible(st is not None)
            lab.setVisible(st is not None)
            if st is None:
                return
            bar.setValue(int(st["value"]))
            if st["phase"] == "done":
                lab.setText(_("<span style='color:%s'><b>✓ Done</b></span> at %s. The numbers below are new.") % (
                    theme.color("success_text"), st["text"]))
            else:
                lab.setText(_("<b>Measuring %d%%</b><br>%s") % (st["value"], st["text"]))
        except RuntimeError:      # the page (and its bar) was just replaced
            pass

    def run_benchmark(self):
        import bench
        if self.measuring():
            return
        self._click_log("measure start")
        self.bench_state = {"phase": "running", "value": 0, "text": "Starting…"}
        self.rebuild_pages()      # locks the steps and the Measure button

        def progress(d, t, s):
            self.bench_state.update(value=100.0 * d / max(1.0, t), text=s)
            self._show_bench_state()
            self.say("Measuring this PC: " + s)
        job = self.start_job(Job(lambda p: bench.run(HERE, p)))
        job.progress.connect(progress)

        def done(res):
            self.bench = res
            self.bench_state = {"phase": "done", "value": 100, "text": time.strftime("%H:%M")}
            self._click_log("measure done")
            self.rebuild_pages()
            self.say(_("Measured: reading %.2f s (fast %.2f s), translating per line: quickmt %.2f s%s%s.") % (
                res["ocr_accurate"], res["ocr_fast"], res["mt"],
                ", Sugoi %.2f s" % res["sugoi"] if res.get("sugoi") else "",
                ", language model %.2f s" % res["llm"] if res.get("llm") else ""))

        def failed(e):
            self.bench_state = None
            self._click_log("measure failed: %s" % e)
            self.rebuild_pages()
            self.error("Measuring failed: " + e)
        job.finished_ok.connect(done)
        job.failed.connect(failed)
        job.start()

    # --------------------------------------------------------------------------------------- translation page
    def _translation_settings(self):
        """Below the preset steps: the language model's own options (when it translates), languages, online."""
        f = self.flt
        current = cfgmod.get("translator.kind")
        self.online_warn = message(_("⚠ Online: the text on screen is sent to the online service."), "warning")
        self.online_warn.setVisible(current == "online")

        import models
        self.llm_combo = QComboBox()
        names = [m.name for m in models.CATALOG if m.kind == "llm"]
        for m in models.CATALOG:
            if m.kind == "llm":
                self.llm_combo.addItem("%s%s" % (short_title(m.title), "" if m.installed() else "  (not downloaded)"),
                                       m.name)
        cur = cfgmod.get("translator.llm_model")
        known = models.find(cur)
        if known is None:
            self.llm_combo.addItem("%s (your Ollama model)" % cur, cur)
        self.llm_combo.addItem("Other Ollama model…", "__other__")
        self.llm_combo.setCurrentIndex(max(0, self.llm_combo.findData(known.name if known else cur)))

        def pick_model(i):
            name = self.llm_combo.itemData(i)
            if name == "__other__":
                from PySide6.QtWidgets import QInputDialog
                text, ok = QInputDialog.getText(self, "Ollama model", "Name of a model in your Ollama (as `ollama "
                                                "list` shows it), for example qwen3:8b:")
                if ok and text.strip():
                    save("translator.llm_model", text.strip(), self.error)
                QTimer.singleShot(0, self.rebuild_pages)
                return
            save("translator.llm_model", name, self.error)
            QTimer.singleShot(0, self.rebuild_pages)    # the step's description and the estimate name the model
        self.llm_combo.currentIndexChanged.connect(pick_model)
        explain(self.llm_combo, "%s: %s" % (cfgmod.BY_KEY["translator.llm_model"].label,
                                            cfgmod.BY_KEY["translator.llm_model"].help), f)
        self.llm_rows = QWidget()
        self.llm_rows.setLayout(form([("Language model", self.llm_combo),
                                      ("Model runner", setting_widget("translator.llm_backend", f, self.error)),
                                      ("Show translation as it is written",
                                       setting_widget("translator.stream", f, self.error))]))

        # Translate from: Auto (every supported language, recognised per line) or one language only
        self.src_combo = QComboBox()
        self.src_combo.addItem("Auto (Japanese, Chinese, English)", ",".join(langs.SOURCES))
        for code, name in langs.SOURCES.items():
            self.src_combo.addItem(name + " only", code)
        for code, name in langs.OWN_READER.items():     # their own reader model: never part of Auto
            self.src_combo.addItem(name + " (and English)", code + ",en")
        enabled = sorted(langs.sources(cfgmod.get("translator.sources")))
        own = next((c for c in langs.OWN_READER if c in enabled), None)
        idx = (max(0, self.src_combo.findData(own + ",en")) if own else
               0 if len(enabled) != 1 else max(0, self.src_combo.findData(enabled[0])))
        self.src_combo.setCurrentIndex(idx)
        self.src_combo.currentIndexChanged.connect(
            lambda i: save("translator.sources", self.src_combo.itemData(i), self.error))
        explain(self.src_combo, "Which languages lenslate translates. Auto: Japanese, Chinese (Simplified and "
                "Traditional) and English, each line's language recognised automatically; text already in the "
                "'Translate into' language is left alone. Pick one language to translate only that one (for example "
                "English only, to leave Japanese signs in an English game alone).", f)
        target = setting_widget("translator.language", f, self.error)
        # the step options depend on the languages (Ultrafast / Visual novel are Japanese only): show them again
        self.src_combo.currentIndexChanged.connect(lambda _i: QTimer.singleShot(0, self.languages_changed))
        if isinstance(target, QComboBox):
            target.currentIndexChanged.connect(lambda _i: QTimer.singleShot(0, self.languages_changed))
        explain(target, "The language the translations are written in. Portuguese (Brazil) on the processor uses "
                "the OPUS model (Brazilian Portuguese); the language model and online services write it too.", f)

        provider = setting_widget("translator.online_provider", f, self.error)
        self.deepl_row = self._wrap(small_form([("DeepL API key", setting_widget("translator.deepl_key", f, self.error))]))
        provider.currentTextChanged.connect(lambda t: self.deepl_row.setVisible(t == "deepl"))
        self.deepl_row.setVisible(cfgmod.get("translator.online_provider") == "deepl")
        service = self._wrap(small_form([("Online service", provider)]))
        explain(service, "Google, Bing and Yandex need no account but can stop working or limit you at any time; "
                "DeepL needs a free API key. The text on screen is SENT TO THAT COMPANY.", f)

        # step 2's own options, under its buttons. Fixed order so nothing jumps when the translator changes:
        # the online checkbox first (always there; greyed out for Online), then that translator's options.
        extra = QWidget()
        el = QVBoxLayout(extra)
        el.setContentsMargins(0, 6, 0, 0)
        el.setSpacing(8)
        fb = QCheckBox()
        fb.setObjectName("online_fallback")
        fb_text = QLabel(_("If the local translator fails on a line, send that line to an online service"))
        fb_text.setWordWrap(True)     # (a checkbox's own text cannot wrap and kept the page wide)
        for w_ in (fb, fb_text):
            explain(w_, cfgmod.BY_KEY["translator.online_fallback"].help if current != "online" else
                    "Online already translates every line.", f)
        fb_text.mousePressEvent = lambda _e: fb.isEnabled() and fb.toggle()
        fbr = QHBoxLayout()
        fbr.setSpacing(8)
        fbr.addWidget(fb, 0, Qt.AlignTop)
        fbr.addWidget(fb_text, 1)
        el.addLayout(fbr)
        warn = message(_("⚠ With this on, lines the local translator cannot do leave this computer."), "warning")
        if current == "online":
            fb.setChecked(True)
            fb.setEnabled(False)
            fb_text.setEnabled(False)
            warn = self.online_warn
            on = True
        else:
            fb.setChecked(bool(cfgmod.get("translator.online_fallback")))
            on = fb.isChecked()

            def toggled(v):
                save("translator.online_fallback", bool(v), self.error)
                for x in (service, warn):
                    x.setVisible(bool(v))
                self.deepl_row.setVisible(bool(v) and cfgmod.get("translator.online_provider") == "deepl")
            fb.toggled.connect(toggled)
        warn.setVisible(on)
        service.setVisible(on)
        self.deepl_row.setVisible(on and cfgmod.get("translator.online_provider") == "deepl")
        el.addWidget(warn)
        el.addWidget(service)
        el.addWidget(self.deepl_row)
        if current == "llm":
            self.llm_rows = self._wrap(small_form([("Model", self.llm_combo),
                                                   ("Runner", setting_widget("translator.llm_backend", f, self.error)),
                                                   ("Show translation as it is written",
                                                    setting_widget("translator.stream", f, self.error))]))
            el.addWidget(self.llm_rows)
        else:
            self.llm_rows = QWidget()     # (kept for code that toggles it)

        langs_box = QWidget()
        ll = QVBoxLayout(langs_box)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(section_label("Languages"))
        top.addStretch(1)
        for b in getattr(self, "_head_buttons", []):
            top.addWidget(b)
        ll.addLayout(top)
        ll.addWidget(self._wrap(form([("Translate from", self.src_combo), ("Translate into", target),
                                      ("Ready-made menu translations",
                                       setting_widget("translator.seed_packs", f, self.error))])))
        return langs_box, extra

    @staticmethod
    def _wrap(layout):
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    # -------------------------------------------------------------------------------------------- models page
    def page_models(self):
        import llm
        import models
        f = self.flt
        rows = []
        info = llm.runtime_info()
        self.runtime_label = hint("Built-in model runner: " + (
            "llama.cpp %s (%s)" % (info["build"], info["flavor"]) if info else "not installed yet (it comes with the "
            "first language model you download)"))
        explain(self.runtime_label, "lenslate runs language models itself with llama.cpp (Vulkan: NVIDIA, AMD and "
                "Intel graphics). Nothing else needs to be installed. Ollama is used only if you choose it.", f)
        rows.append(self.runtime_label)
        pack = explain(set_role(QPushButton(_("Load offline pack…")), "quiet"),
                       "Install processor translators from an offline pack file (lenslate-pack-*.tar from the "
                       "release page, or one made with `lenslate models pack`) - for a PC without internet. Every "
                       "file is checked before it is used.", f)
        pack.setMaximumWidth(220)
        pack.clicked.connect(self._load_pack)
        self.pack_bar = QProgressBar()
        self.pack_bar.setVisible(False)
        self.model_rows = {}
        groups = (("mt", "Processor translators (quickmt)"), ("llm", "Language models (graphics card)"),
                  ("sugoi", "Visual novel translator (Sugoi, processor)"))
        for kind, title in groups:
            if kind == "mt":        # the offline pack holds processor translators: its button sits with them
                head = QWidget()
                hl = QHBoxLayout(head)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.addWidget(section_label(title))
                hl.addStretch(1)
                hl.addWidget(pack, 0, Qt.AlignBottom)
                rows += [head, self.pack_bar]
                continue_rows = True
            else:
                rows.append(section_label(title))
            for m in models.CATALOG:
                if m.kind != kind:
                    continue
                rows.append(self._model_row(m))
        return page(*rows)

    def _model_row(self, m):
        f = self.flt
        w = card_frame()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        # the section header already says what kind of model it is
        short = re.sub(r"\s*\((?:language|translation|language \+ image) model\)$", "", m.title)
        title = QLabel("<b>%s</b>" % short)
        title.setWordWrap(False)
        btn = QPushButton()
        btn.setMinimumWidth(150)
        tags = FlowLayout(hspacing=8, vspacing=4)     # title and chips wrap; the button stays on the right
        tags.addWidget(title)
        inst = chip("✓ Installed", "success")
        tags.addWidget(inst)
        if m.experimental:
            tags.addWidget(chip("Experimental", "warning"))
        if "non-commercial" in m.license.lower():
            nc = chip("Non-commercial", "warning")
            nc.setToolTip("Licence: %s. Fine for playing games; not for paid or business use." % m.license)
            tags.addWidget(nc)
        head.addLayout(tags, 1)
        head.addWidget(btn, 0, Qt.AlignTop)
        mem = ("%.1f GB GPU memory" % m.vram_gb) if m.vram_gb else ("%.1f GB memory" % (m.ram_gb or 0))
        size = hint(_("%.1f GB download · %s · licence: %s") % (m.size_gb, mem, m.license.split(" (")[0]))
        if " (" in m.license:   # the licence's note ("free for personal and non-commercial use") in its hover text
            size.setToolTip(m.license)
        can = QLabel(_("<b>Translates:</b> %s") % m.can) if getattr(m, "can", "") else None
        about = QLabel(m.about)
        about.setWordWrap(True)
        bar = QProgressBar()
        bar.setVisible(False)
        lay.addLayout(head)
        lay.addWidget(size)
        if can is not None:
            can.setWordWrap(True)
            lay.addWidget(can)
        lay.addWidget(about)
        lay.addWidget(bar)
        explain(w, m.about, f)
        self.model_rows[m.name] = (btn, bar)
        self.model_chips = getattr(self, "model_chips", {})
        self.model_chips[m.name] = inst
        self._update_model_row(m)
        btn.clicked.connect(lambda: self._model_action(m))
        return w

    def _update_model_row(self, m):
        btn, bar = self.model_rows[m.name]
        own = os.path.exists(os.path.join(m.path, ".complete"))
        self.show_task(self.tasks.get("model:" + m.name), bar, (btn,))
        btn.setText("Remove" if own else "↓ Download %.1f GB" % m.size_gb)
        set_role(btn, "danger" if own else "download")
        if m.name in getattr(self, "model_chips", {}):
            self.model_chips[m.name].setVisible(own)
        explain(btn, ("Delete this model from lenslate's folder (%s)." % m.path) if own else
                "Download this model (%.1f GB) from Hugging Face%s." % (
                    m.size_gb, ", plus lenslate's model runner the first time" if m.kind == "llm" else ""), self.flt)

    def _model_action(self, m):
        import models
        key = "model:" + m.name
        if key in self.tasks:          # already downloading (started from another page or before a rebuild)
            return
        if os.path.exists(os.path.join(m.path, ".complete")):
            box = QMessageBox(QMessageBox.Question, "Remove model", "Delete %s from this computer?" % m.title, parent=self)
            yes = set_role(box.addButton("Remove", QMessageBox.DestructiveRole), "danger")
            box.addButton("Cancel", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is yes:
                try:
                    models.remove(m.name)
                except Exception as e:  # noqa: BLE001
                    self.error(str(e))
                self._update_model_row(m)
            return
        job = self.start_job(Job(lambda progress: models.download(m.name, progress)), key)

        def row():
            """The row's widgets on the page as it is now (a rebuild replaces them)."""
            if m.name in getattr(self, "model_rows", {}):
                try:
                    self._update_model_row(m)
                except RuntimeError:       # that page is waiting to be built again
                    pass

        def prog(done, total, text):
            st = self.tasks.get(key)
            if st is not None:
                st.update(value=1000 * done / total if total > 0 else None, text=text[:30])
                row()

        def end(ok_or_err, failed=False):
            row()
            if failed:
                self.error(_("%s: %s") % (m.title, ok_or_err))
            else:
                self.say(_("%s is installed.") % m.title)
        job.progress.connect(prog)
        job.finished_ok.connect(lambda _r: end(None))
        job.failed.connect(lambda e: end(e, True))
        row()
        job.start()

    def _load_pack(self):
        import models
        path, _f = QFileDialog.getOpenFileName(self, "Load offline pack", os.path.expanduser("~/Downloads"),
                                               "lenslate offline pack (*.tar);;All files (*)")
        if not path:
            return
        try:
            names = sorted(models.read_pack(path)["models"])
        except RuntimeError as e:
            self.error(str(e))
            return
        job = self.start_job(Job(lambda progress: models.import_pack(path, progress)), "pack")
        bar = self.pack_bar

        def prog(done, total, text):
            try:
                bar.setVisible(True)
                bar.setRange(0, 1000)
                bar.setValue(int(1000 * done / total) if total else 0)
                bar.setFormat(text[:40])
            except RuntimeError:
                pass

        def end(result, failed=False):
            try:
                bar.setVisible(False)
            except RuntimeError:
                pass
            if failed:
                self.error(_("Offline pack: %s") % result)
                return
            done, skipped = result
            for m in models.CATALOG:
                if m.name in getattr(self, "model_rows", {}):
                    try:
                        self._update_model_row(m)
                    except RuntimeError:
                        pass
            self.say(_("Offline pack: installed %s%s.") % (", ".join(done) or "nothing new",
                                                      ("; already installed: " + ", ".join(skipped)) if skipped else ""))
        job.progress.connect(prog)
        job.finished_ok.connect(lambda r: end(r))
        job.failed.connect(lambda e: end(e, True))
        self.say(_("Loading %s (%s)…") % (os.path.basename(path), ", ".join(names)))
        job.start()

    # --------------------------------------------------------------------------------------------- games page
    def page_games(self):
        f = self.flt
        self.game_path = explain(QLineEdit(), "The game's folder (the one with its .exe, or with game/ for Ren'Py "
                                 "games).", f)
        browse = set_role(explain(QPushButton(_("Choose folder…")), "Pick the game's folder.", f), "secondary")
        self.game_path.setPlaceholderText(_("Game folder"))
        browse.clicked.connect(self.choose_game)
        self.game_path.editingFinished.connect(self.game_changed)
        prow = QHBoxLayout()
        prow.addWidget(self.game_path, 1)
        prow.addWidget(browse)
        self.game_info = note(_("Choose a game folder to enable these actions."), CONTENT_W)
        self.b_install = explain(QPushButton(_("Install hook")), "Put lenslate inside the game, so it translates "
                                 "the game's own text: no screen reading, no misread characters. Every file it "
                                 "changes is backed up. Works for RPG Maker MV/MZ, Ren'Py and Unity (with XUnity).",
                                 f)
        self.b_remove = explain(QPushButton(_("Remove hook")), "Take lenslate out of the game and restore the "
                                "backed-up files.", f)
        self.b_pre = explain(QPushButton(_("Translate all text now")), "Read every line of the game from its files "
                             "and translate it ahead of time, so everything appears instantly while you play "
                             "(RPG Maker MV/MZ; Ren'Py games do this by themselves when they start).", f)
        self.b_names = explain(QPushButton(_("Find character names")), "Look for character names in the game's "
                               "files and suggest their spelling. You confirm them on the Names & fixes page.", f)
        self.b_install.clicked.connect(lambda: self.game_job("install"))
        self.b_remove.clicked.connect(lambda: self.game_job("remove"))
        self.b_pre.clicked.connect(lambda: self.game_job("pretranslate"))
        self.b_names.clicked.connect(lambda: self.game_job("names"))
        set_role(self.b_install, "primary")
        set_role(self.b_pre, "secondary")
        set_role(self.b_names, "secondary")
        set_role(self.b_remove, "danger")
        brow = FlowLayout(hspacing=8, vspacing=8)
        for b in (self.b_install, self.b_pre, self.b_names, self.b_remove):   # Remove last, away from Install
            brow.addWidget(b)
        for b in (self.b_install, self.b_remove, self.b_pre, self.b_names):
            b.setEnabled(False)
        self.game_bar = QProgressBar()
        self.game_bar.setVisible(False)
        self.game_log = QPlainTextEdit()
        self.game_log.setReadOnly(True)
        self.game_log.setMaximumHeight(160)
        set_role(self.game_log, "log")
        from PySide6.QtGui import QFontDatabase
        self.game_log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.game_log.setVisible(False)
        explain(self.game_log, "What the last game action did.", f)
        gsec = section_label("Game")
        explain(gsec, "While you play a hooked game, lenslate's translation server must run: start "
                "it with `lenslate serve` (some game launchers do it for you). Games without a hook (Wolf RPG, RPG Maker VX Ace, KiriKiri …) use the "
                "screen overlay.", f)
        gs = getattr(self, "game_state", None)
        if gs:                              # the page was built again: same folder, log and running job
            self.game_path.setText(gs["path"])
            if os.path.isdir(gs["path"]):
                self.game_changed()
            if gs["log"]:
                self.game_log.setVisible(True)
                self.game_log.setPlainText(gs["log"])
            self._show_game_task()
        return page(gsec, prow, self.game_info, brow, self.game_bar, self.game_log)

    def _show_game_task(self):
        st = self.tasks.get("game")
        if st is None:
            try:
                self.game_bar.setVisible(False)
            except RuntimeError:
                pass
            return
        self.show_task(st if st.get("bar") else None, self.game_bar)
        try:
            for b in (self.b_install, self.b_remove, self.b_pre, self.b_names):
                b.setEnabled(False)
        except RuntimeError:
            pass

    def choose_game(self):
        d = QFileDialog.getExistingDirectory(self, "Game folder", self.game_path.text() or os.path.expanduser("~/Games"))
        if d:
            self.game_path.setText(d)
            self.game_changed()

    def game_changed(self):
        import hooks
        d = self.game_path.text().strip()
        gs = self.__dict__.setdefault("game_state", {"path": "", "log": ""})
        if d != gs["path"]:
            gs.update(path=d, log="")
        if not os.path.isdir(d):
            self.game_info.setText(_("Not a folder."))
            return
        st = hooks.status(d)
        names = {"rpgm-mv": "RPG Maker MV", "rpgm-mz": "RPG Maker MZ", "unity": "Unity", "renpy": "Ren'Py",
                 "wolf": "Wolf RPG", "rpgm-vxace": "RPG Maker VX Ace"}
        eng = names.get(st["engine"], st["engine"] or "unknown engine")
        import unityloader
        extra = ""
        u = st.get("unity")
        if u and u.get("problem"):
            extra = " · " + u["problem"]
        elif u and u["missing"] and not st["installed"]:
            extra = " · Install also downloads %s (%s, about %.0f MB)" % (
                " and ".join("BepInEx" if m.startswith("bepinex") else "XUnity.AutoTranslator" for m in u["missing"]),
                "IL2CPP" if u["flavor"] == "il2cpp" else "Mono", max(1, sum(unityloader.SIZES_MB[m] for m in u["missing"])))
        if st.get("loader_off"):
            extra += " · BepInEx is switched off: Install switches it back on"
        ok_c, warn_c = theme.color("success_text"), theme.color("warning_text")
        self.game_info.setText(_("<b>%s</b> · game id %s · %s%s%s") % (
            eng, st["game"], "<span style='color:%s'>✓ hook installed</span>" % ok_c if st["installed"] else "no hook",
            "" if st["supported"] else " · <span style='color:%s'>⚠ no hook for this engine yet: use the screen "
            "overlay</span>" % warn_c, extra))
        self.b_install.setEnabled(st["supported"] and (not st["installed"] or st.get("loader_off")
                                                        or bool(u and u["missing"])))
        self.b_remove.setEnabled(st["installed"])
        self.b_pre.setEnabled(st["engine"] in ("rpgm-mv", "rpgm-mz"))
        self.b_names.setEnabled(True)
        if "game" in self.tasks:
            self._show_game_task()

    def game_job(self, what):
        import hooks
        import names as nm
        d = self.game_path.text().strip()
        if "game" in self.tasks:
            return
        gs = self.__dict__.setdefault("game_state", {"path": d, "log": ""})
        log = []

        def work(progress):
            if what == "install":
                eng, game = hooks.install(d)
                msg = "Hook installed (%s, game id %s)." % (eng, game)
                if eng == "unity":
                    msg += (" Wine/Proton must load BepInEx's winhttp.dll: set WINEDLLOVERRIDES=\"winhttp=n,b\" "
                            "(in Steam's launch options: WINEDLLOVERRIDES=\"winhttp=n,b\" %command%).")
                return msg
            if what == "remove":
                return "Hook removed (%s); backed-up files restored." % hooks.remove(d)
            if what == "pretranslate":
                def p(*a, **k):
                    text = " ".join(str(x) for x in a).strip()
                    import re
                    m = re.search(r"(\d+) / (\d+)", text)
                    if m:
                        progress(int(m.group(1)), int(m.group(2)), text)
                    else:
                        log.append(text)
                done, failed = hooks.pretranslate(d, p)
                return "\n".join(log + ["Done: %d translated, %d failed." % (done, failed)])
            if what == "names":
                game, found, _ids = nm.scan(d, cfgmod.get("translator.llm_model"), cfgmod.get("translator.ollama_url"),
                                            log=lambda s: log.append(s))
                added = nm.append_entries(game, found, " from game files")
                good = ["%s = %s" % (jp, en) for jp, en in added if en != "-"]
                return "\n".join(log + ["%d names suggested: %s" % (len(good), ", ".join(good) or "none"),
                                        "Check them on the Names & fixes page."])
        job = self.start_job(Job(work), "game")
        self.tasks["game"]["bar"] = what == "pretranslate"
        gs["log"] = "Working…"
        self.game_log.setVisible(True)
        self.game_log.setPlainText(gs["log"])
        self._show_game_task()

        def prog(dn, tot, _t):
            st = self.tasks.get("game")
            if st is not None:
                st.update(value=1000 * dn / max(1.0, tot), text="%d / %d" % (dn, tot))
                self._show_game_task()

        def end(text):
            gs["log"] = text
            try:
                self.game_bar.setVisible(False)
                self.game_log.setVisible(True)
                self.game_log.setPlainText(text)
                self.game_changed()
            except RuntimeError:       # the Games page is waiting to be built again: it reads game_state then
                pass
            try:
                self.reload_name_games()
            except RuntimeError:
                pass
        job.progress.connect(prog)
        job.finished_ok.connect(end)
        job.failed.connect(lambda e: end("⚠ " + e))
        job.start()

    # --------------------------------------------------------------------------------------------- names page
    def page_names(self):
        """Two kinds of per-game corrections on one page: names/terms (before translating) and fixed translations
        (after)."""
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self.section_names(), "Names && terms")
        tabs.addTab(self.section_fixes(), "Fix translations")
        tabs.setTabToolTip(0, "Character names and game terms, so they are translated the same way every time.")
        tabs.setTabToolTip(1, "Find a translation that came out wrong and correct it (or delete it so it is "
                              "translated again).")
        tabs.currentChanged.connect(lambda i: self.say(tabs.tabToolTip(i)))
        return tabs

    def section_names(self):
        f = self.flt
        self.name_game = explain(QComboBox(), "Which game's list to show. 'global' applies to every game. Names are "
                                 "found automatically in Japanese and Chinese text while you play, or with 'Find "
                                 "character names' on the Games page.", f)
        self.name_game.currentTextChanged.connect(self.load_names)
        self.name_table = QTableWidget(0, 3)
        self.name_table.setHorizontalHeaderLabels(["Original", "Translation", "State"])
        self.name_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.name_table.setMinimumHeight(330)
        explain(self.name_table, "Original = the name or term as the game writes it; Translation = how it must "
                "always be translated. State: used = applied to every translation; suggestion = found by lenslate, "
                "not used until you set it to used; rejected = not a name, never suggested again.", f)
        b_add = explain(QPushButton(_("Add row")), "Add a name or term by hand (for example 淫紋 → lewd crest).", f)
        b_add.clicked.connect(lambda: self._name_row("", "", "used"))
        b_ok = explain(QPushButton(_("Use all suggestions")), "Mark every suggestion as used.", f)
        b_ok.clicked.connect(self.confirm_all_names)
        b_save = explain(QPushButton(_("Save")), "Write the list. The overlay and hook server pick it up within "
                         "a few seconds.", f)
        b_save.clicked.connect(self.save_names)
        self.name_table.setAlternatingRowColors(True)
        row = QHBoxLayout()
        for b in (b_add, b_ok):
            row.addWidget(set_role(b, "secondary"))
        row.addStretch(1)
        row.addWidget(set_role(b_save, "primary"))
        self.reload_name_games()
        self.names_empty = note(_("No names for this game yet. Add one, or use Find character names on the Games page."))
        return page(form([("Game", self.name_game)]), self.names_empty, self.name_table, row, wide=True)

    # ------------------------------------------------------------------------------------ fix translations
    def section_fixes(self):
        f = self.flt
        self.fix_file = explain(QComboBox(), "Which translator's saved translations to search. Every translator keeps "
                                "its own, so you always see that model's wording.", f)
        self.fix_search = explain(QLineEdit(), "Type part of the original or of the translation (for example a word "
                                  "that was translated wrong).", f)
        self.fix_search.setPlaceholderText(_("Search…"))
        self.fix_search.textChanged.connect(lambda _t: self.fix_timer.start(250))
        self.fix_timer = QTimer(self)
        self.fix_timer.setSingleShot(True)
        self.fix_timer.timeout.connect(self.load_fixes)
        self.fix_file.currentIndexChanged.connect(lambda _i: self.load_fixes())
        self.fix_table = QTableWidget(0, 2)
        self.fix_table.setHorizontalHeaderLabels(["Original", "Translation"])
        self.fix_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.fix_table.setMinimumHeight(330)
        self.fix_table.setWordWrap(True)
        explain(self.fix_table, "Double-click a translation to correct it, then Save. Only the translation can be "
                "edited: the original is what the game showed.", f)
        b_del = explain(QPushButton(_("Delete selected")), "Forget the selected translations: they are translated "
                        "again the next time they appear (useful after changing a name or the model).", f)
        b_del.clicked.connect(self.delete_fixes)
        b_save = explain(QPushButton(_("Save")), "Keep your corrections. A running overlay or hook server uses them "
                         "within a few seconds.", f)
        b_save.clicked.connect(self.save_fixes)
        self.fix_table.setAlternatingRowColors(True)
        row = QHBoxLayout()
        row.addWidget(set_role(b_del, "danger"))
        row.addStretch(1)
        row.addWidget(set_role(b_save, "primary"))
        self.reload_fix_files()
        return page(form([("Translator", self.fix_file), ("Find", self.fix_search)]), self.fix_table, row, wide=True)

    def reload_fix_files(self):
        import re
        import textflow as tf
        base = cfgmod.cache_path()
        folder, stem = os.path.dirname(base), os.path.splitext(os.path.basename(base))[0]
        current = tf.cache_file(base, cfgmod.get("translator.kind"), cfgmod.get("translator.llm_model"))
        self.fix_file.blockSignals(True)
        self.fix_file.clear()
        try:
            files = sorted(fn for fn in os.listdir(folder) if fn.startswith(stem) and fn.endswith(".json"))
        except OSError:
            files = []
        for fn in files:
            tag = fn[len(stem):-5].lstrip("-") or "qwen3-vl 4B (first default)"
            tag = {"mt": "Cheapest (quickmt)", "sugoi": "Visual novel (quickmt + Sugoi)"}.get(tag, re.sub(r"_", "-", tag))
            self.fix_file.addItem(tag, os.path.join(folder, fn))
        i = self.fix_file.findData(current)
        self.fix_file.setCurrentIndex(max(0, i))
        self.fix_file.blockSignals(False)
        self.load_fixes()

    def load_fixes(self):
        import textflow as tf
        path = self.fix_file.currentData()
        self.fix_table.setRowCount(0)
        self.fix_cache = tf.TextCache(path) if path else None
        if not self.fix_cache:
            return
        q = self.fix_search.text().strip().lower()
        rows = [(k, v) for k, v in self.fix_cache.data.items() if not q or q in k.lower() or q in v.lower()]
        for k, v in rows[-500:][::-1]:   # newest first
            r = self.fix_table.rowCount()
            self.fix_table.insertRow(r)
            orig = QTableWidgetItem(k.split("\x1f")[0])
            orig.setFlags(orig.flags() & ~Qt.ItemIsEditable)
            orig.setData(Qt.UserRole, k)
            self.fix_table.setItem(r, 0, orig)
            self.fix_table.setItem(r, 1, QTableWidgetItem(v))
        self.fix_table.resizeRowsToContents()

    def delete_fixes(self):
        rows = sorted({i.row() for i in self.fix_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.fix_cache.delete(self.fix_table.item(r, 0).data(Qt.UserRole))
            self.fix_table.removeRow(r)
        self.fix_cache.save()
        self.say(_("Deleted %d translations; they are translated again when they next appear.") % len(rows))

    def save_fixes(self):
        n = 0
        for r in range(self.fix_table.rowCount()):
            key, new = self.fix_table.item(r, 0).data(Qt.UserRole), self.fix_table.item(r, 1).text().strip()
            if new and self.fix_cache.data.get(key) != new:
                self.fix_cache.put(key, new)
                self.fix_cache.mark_fixed(key)   # a hand correction: kept over ready-made menu translations
                n += 1
        self.fix_cache.save()
        self.say(_("Saved %d corrections.") % n)

    def reload_name_games(self):
        import names as nm
        if not hasattr(self, "name_game"):
            return
        cur = self.name_game.currentText()
        os.makedirs(nm.NAMES_DIR, exist_ok=True)
        games = sorted(f[:-4] for f in os.listdir(nm.NAMES_DIR) if f.endswith(".tsv"))
        if "global" not in games:
            games.insert(0, "global")
        self.name_game.blockSignals(True)
        self.name_game.clear()
        self.name_game.addItems(games)
        self.name_game.blockSignals(False)
        if cur not in games:   # first time: the list changed most recently
            recent = sorted((f for f in games if f != "global"), reverse=True,
                            key=lambda g: os.path.getmtime(os.path.join(nm.NAMES_DIR, g + ".tsv")))
            cur = recent[0] if recent else games[0]
        self.name_game.setCurrentText(cur)
        self.load_names(self.name_game.currentText())

    def _name_row(self, jp, en, state):
        r = self.name_table.rowCount()
        self.name_table.insertRow(r)
        self.name_table.setItem(r, 0, QTableWidgetItem(jp))
        self.name_table.setItem(r, 1, QTableWidgetItem(en))
        c = QComboBox()
        c.addItems(["used", "suggestion", "rejected"])
        c.setCurrentText(state)
        explain(c, "used = applied to every translation of this game; suggestion = found by lenslate, waiting for "
                "you (not used yet); rejected = not a name, never suggested again.", self.flt)
        self.name_table.setCellWidget(r, 2, c)

    def load_names(self, game):
        import names as nm
        self.name_table.setRowCount(0)
        if not game:
            return
        for jp, (state, en) in nm.read_file(os.path.join(nm.NAMES_DIR, game + ".tsv")).items():
            self._name_row(jp, en, {"ok": "used", "?": "suggestion", "-": "rejected"}[state])
        if hasattr(self, "names_empty"):
            self.names_empty.setVisible(self.name_table.rowCount() == 0)

    def confirm_all_names(self):
        for r in range(self.name_table.rowCount()):
            c = self.name_table.cellWidget(r, 2)
            if c.currentText() == "suggestion":
                c.setCurrentText("used")

    def save_names(self):
        import names as nm
        game = self.name_game.currentText()
        lines = [nm.HEADER.format(game=game).rstrip("\n")]
        for r in range(self.name_table.rowCount()):
            jp = (self.name_table.item(r, 0).text() if self.name_table.item(r, 0) else "").strip()
            en = (self.name_table.item(r, 1).text() if self.name_table.item(r, 1) else "").strip()
            state = self.name_table.cellWidget(r, 2).currentText()
            if not jp:
                continue
            prefix = {"used": "", "suggestion": "?", "rejected": "-"}[state]
            lines.append("%s%s\t%s" % (prefix, jp, en))
        os.makedirs(nm.NAMES_DIR, exist_ok=True)
        with open(os.path.join(nm.NAMES_DIR, game + ".tsv"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        self.say(_("Saved %s (%d entries).") % (game, len(lines) - 1))

    # ------------------------------------------------------------------------------------------ advanced page
    def page_advanced(self):
        f = self.flt
        shown = {"overlay.opacity", "overlay.placeholder", "translator.stream", "ocr.reading", "refresh.interval", "refresh.settle_step", "refresh.settle_max",
                 "translator.kind", "translator.llm_model", "translator.llm_backend", "translator.language",
                 "translator.sources", "translator.online_provider", "translator.online_fallback", "translator.seed_packs",
                 "translator.deepl_key"}
        cfg = explain(QPushButton(_("Open config.toml")), "Open the settings file in your text editor. Every "
                      "setting is explained in it; changes apply while lenslate runs.", f)
        cfg.clicked.connect(lambda: subprocess.Popen(["xdg-open", cfgmod.CONFIG_PATH]))
        top = QHBoxLayout()
        ver = explain(QLabel(_("lenslate %s") % version.describe()), "The version of lenslate that is installed (and "
                      "the commit it was made from). Give it when you report a problem.", f)
        ver.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top.addWidget(set_role(ver, "hint"))
        top.addStretch(1)
        top.addWidget(set_role(cfg, "quiet"))
        out = [top]
        for sec, about in cfgmod.SECTIONS.items():
            keys = [s.key for s in cfgmod.SCHEMA if s.key.startswith(sec + ".") and s.key not in shown]
            if not keys:
                continue
            g = QGroupBox(_({"general": "General", "translator": "Translator", "ocr": "Screen reading (OCR)",
                           "hook": "Hook mode", "paths": "Files and folders", "debug": "Troubleshooting",
                           "overlay": "Overlay", "refresh": "Refreshing"}.get(sec, sec.capitalize())))
            g.setLayout(form([(_(cfgmod.BY_KEY[k].label), setting_widget(k, f, self.error)) for k in keys]))
            explain(g, about, f)
            out.append(g)
        return page(*out)


# ------------------------------------------------------------------------------------------------- tray icon
def make_tray(app, win):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    tray = QSystemTrayIcon(win.windowIcon(), app)
    tray.setToolTip("lenslate %s" % version.VERSION)
    menu = QMenu()
    acts = [("Settings…", lambda: (win.showNormal(), win.raise_(), win.activateWindow())),
            (None, None),
            ("Pick area…", lambda: send("select") or run_lenslate("select")),
            ("Translate now", lambda: send("now")),
            ("Automatic on / off", lambda: send("auto")),
            ("Show / hide", lambda: send("toggle")),
            (None, None)]
    for text, fn in acts:
        if text is None:
            menu.addSeparator()
            continue
        a = QAction(text, menu)
        a.triggered.connect(fn)
        menu.addAction(a)
    sub = menu.addMenu("Translator")
    grp = QActionGroup(sub)
    for k, t in (("llm", "Language model"), ("mt", "Processor"), ("sugoi", "Visual novel (processor)"),
                 ("online", "Online service")):
        a = QAction(t, sub, checkable=True)
        a.setChecked(cfgmod.get("translator.kind") == k)
        a.triggered.connect(lambda _c=False, k=k: save("translator.kind", k, win.error))
        grp.addAction(a)
        sub.addAction(a)
    menu.addSeparator()
    a = QAction(_("Stop lenslate"), menu)
    a.triggered.connect(lambda: send("quit"))
    menu.addAction(a)
    a = QAction(_("Close this window and tray icon"), menu)
    a.triggered.connect(app.quit)
    menu.addAction(a)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: r == QSystemTrayIcon.Trigger and (win.showNormal(), win.activateWindow()))
    tray.show()
    return tray


class MainWindow(Window):
    def closeEvent(self, ev):
        if getattr(self, "tray", None) is not None:   # closing the window keeps the tray icon
            ev.ignore()
            self.hide()
        else:
            super().closeEvent(ev)


def main(args=()):
    os.environ.pop("QT_WAYLAND_SHELL_INTEGRATION", None)   # normal windows, not overlay-layer surfaces
    app = QApplication.instance() or QApplication(sys.argv[:1])
    import i18n
    i18n.install_qt(app)
    app.setApplicationName("lenslate")
    app.setDesktopFileName("lenslate")
    app.setWindowIcon(app_icon())
    theme.install(app)        # colours and button roles (docs/UX-GUIDE.md), light and dark
    app.setQuitOnLastWindowClosed(False)
    win = MainWindow()
    for a in args:   # --page NAME: open on that page (Overlay, Translation, Models, Games, Names, Advanced)
        if a.startswith("--page="):
            want = a.split("=", 1)[1]
            want = {"presets": "Translation", "fixes": "Names & fixes", "names": "Names & fixes"}.get(want.lower(), want)
            items = win.nav.findItems(want, Qt.MatchFixedString)
            if items:
                win.nav.setCurrentItem(items[0])
    win.tray = make_tray(app, win)
    if "--setup" in args:
        cfgmod.set("general.setup_done", False)
    QTimer.singleShot(800, win.first_launch)   # setup window the first time; later: missing model, new hardware
    if "--tray" not in args or win.tray is None:
        win.show()
    if win.tray is None:
        app.setQuitOnLastWindowClosed(True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
