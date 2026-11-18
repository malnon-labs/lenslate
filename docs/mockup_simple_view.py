"""THROWAWAY MOCKUP of lenslate's Simple / Advanced view, preset cards and comparison (roadmap step 1).
Placeholder data from docs/ROADMAP.md's measured numbers; the 'Your PC' panel reads the real CPU/GPU live.
Run: python3 mockup.py [simple|advanced|compare]"""
import subprocess
import sys

import psutil
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QListWidget, QPushButton, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

PRESETS = [
    # name, good for, runs, mem, download, small text, dialogue, menus, speed (0-5), sec/line on THIS pc (est.)
    ("Light", "Heavy games that need the whole graphics card", "CPU", "0.5 GB RAM", "included", False, 1, 3, 5, 0.25),
    ("Light+", "Visual novels without a spare graphics card", "CPU", "1.6 GB RAM", "1.1 GB", False, 3, 3, 5, 0.27),
    ("Fast", "Most games: natural translations, quick", "GPU", "1.7 GB GPU", "3.1 GB", False, 5, 4, 4, 0.40),
    ("Balanced", "Games with small text (hints, UI, versions)", "GPU", "1.7 GB GPU", "3.1 GB", True, 5, 5, 3, 0.65),
    ("Quality", "Visual novels with typed-out text", "GPU", "1.7 GB GPU", "3.1 GB", True, 5, 5, 2, 1.20),
]


def dots(n):
    return "●" * n + "○" * (5 - n)


class Spark(QWidget):
    """Tiny live line graph."""
    def __init__(self, color):
        super().__init__()
        self.vals, self.color = [], QColor(color)
        self.setMinimumHeight(46)

    def push(self, v):
        self.vals = (self.vals + [v])[-60:]
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QPen(self.palette().mid().color(), 1))
        p.drawRoundedRect(r, 4, 4)
        if len(self.vals) < 2:
            return
        path = QPainterPath()
        for i, v in enumerate(self.vals):
            x = r.left() + r.width() * i / 59
            y = r.bottom() - r.height() * min(1.0, v / 100.0)
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        p.setPen(QPen(self.color, 2))
        p.drawPath(path)


class Card(QFrame):
    def __init__(self, preset, on_pick):
        super().__init__()
        name, good, runs, mem, dl, small, dlg, menu, speed, _sec = preset
        self.name = name
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setSpacing(4)
        top = QHBoxLayout()
        t = QLabel("<b style='font-size:15px'>%s</b>" % name)
        badge = QLabel(" %s " % runs)
        badge.setStyleSheet("background:%s;color:white;border-radius:4px;font-size:11px;" %
                            ("#3daee9" if runs == "GPU" else "#7f8c8d"))
        top.addWidget(t); top.addStretch(1); top.addWidget(badge)
        lay.addLayout(top)
        g = QLabel(good); g.setWordWrap(True); g.setStyleSheet("font-size:11px;")
        lay.addWidget(g)
        grid = QGridLayout(); grid.setVerticalSpacing(0)
        for i, (k, v) in enumerate((("Dialogue", dots(dlg)), ("Menus", dots(menu)), ("Speed", dots(speed)))):
            a = QLabel(k); a.setStyleSheet("font-size:11px;")
            b = QLabel(v); b.setStyleSheet("font-size:11px;color:#f67400;letter-spacing:1px;")
            grid.addWidget(a, i, 0); grid.addWidget(b, i, 1)
        lay.addLayout(grid)
        info = QLabel("%s · download: %s<br>small text: %s" % (mem, dl, "found" if small else "may be missed"))
        info.setStyleSheet("font-size:11px;")
        lay.addWidget(info)
        self.btn = QPushButton("Use" if dl in ("included",) or name in ("Fast", "Balanced", "Quality") else "Download 1.1 GB")
        self.btn.clicked.connect(lambda: on_pick(self))
        lay.addWidget(self.btn)
        self.mousePressEvent = lambda _e: on_pick(self)
        self.set_selected(False)

    def set_selected(self, on):
        self.setStyleSheet("#card{border:%s;border-radius:8px;}" %
                           ("2px solid palette(highlight)" if on else "1px solid palette(mid)"))
        self.btn.setText("In use" if on else self.btn.text().replace("In use", "Use"))
        self.btn.setEnabled(not on)


class Window(QWidget):
    def __init__(self, view):
        super().__init__()
        self.setWindowTitle("lenslate")
        self.resize(1100, 680)
        root = QVBoxLayout(self)
        # ---- top bar: status + Simple/Advanced switch (OBS-like)
        bar = QHBoxLayout()
        dot = QLabel("●"); dot.setStyleSheet("color:#27ae60;font-size:18px;")
        bar.addWidget(dot); bar.addWidget(QLabel("Running · area 1280×300 on DP-2 · cards shown"))
        bar.addWidget(QPushButton("Stop lenslate"))
        bar.addStretch(1)
        self.sw = QButtonGroup(self)
        for i, t in enumerate(("Simple", "Advanced")):
            b = QPushButton(t); b.setCheckable(True); b.setMinimumWidth(90)
            b.setStyleSheet("QPushButton{border:1px solid palette(mid);border-radius:0;%spadding:5px 10px;}"
                            "QPushButton:checked{background:palette(highlight);color:palette(highlighted-text);}" %
                            ("border-top-left-radius:6px;border-bottom-left-radius:6px;" if i == 0 else
                             "border-top-right-radius:6px;border-bottom-right-radius:6px;"))
            self.sw.addButton(b, i); bar.addWidget(b)
        root.addLayout(bar)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.simple())
        self.stack.addWidget(self.advanced())
        root.addWidget(self.stack, 1)
        self.sw.idToggled.connect(lambda i, on: on and self.stack.setCurrentIndex(i))
        self.sw.button(1 if view == "advanced" else 0).setChecked(True)
        help_ = QLabel("Hover over anything to see what it does.")
        help_.setStyleSheet("padding:8px;border-top:1px solid palette(mid);")
        root.addWidget(help_)
        self.timer = QTimer(self); self.timer.timeout.connect(self.sample); self.timer.start(500)
        psutil.cpu_percent()

    # ---------------------------------------------------------------------------------------------- simple
    def simple(self):
        w = QWidget(); h = QHBoxLayout(w)
        left = QVBoxLayout()
        row = QHBoxLayout()
        for t in ("Pick area…", "Translate now", "Show / hide"):
            row.addWidget(QPushButton(t))
        row.addWidget(QCheckBox("Keep translating automatically")); row.addStretch(1)
        left.addLayout(row)
        lang = QHBoxLayout()
        a = QComboBox(); a.addItems(["Auto (Japanese, Chinese, English)", "Japanese only", "Chinese only", "English only"])
        b = QComboBox(); b.addItems(["English", "Spanish", "Portuguese (Brazil)"])
        lang.addWidget(QLabel("Translate")); lang.addWidget(a); lang.addWidget(QLabel("→")); lang.addWidget(b); lang.addStretch(1)
        left.addLayout(lang)
        ph = QHBoxLayout()
        ph.addWidget(QLabel("<b>Pick how lenslate works</b>")); ph.addStretch(1)
        cmp_ = QPushButton("Compare all…"); cmp_.clicked.connect(lambda: Compare(self).exec())
        ph.addWidget(cmp_)
        left.addLayout(ph)
        grid = QGridLayout(); grid.setSpacing(10)
        self.cards = []
        for i, p in enumerate(PRESETS):
            c = Card(p, self.pick); self.cards.append(c); grid.addWidget(c, i // 3, i % 3)
        left.addLayout(grid)
        left.addStretch(1)
        h.addLayout(left, 3)
        # right: Your PC
        right = QFrame(); right.setObjectName("pc"); right.setStyleSheet("#pc{border:1px solid palette(mid);border-radius:8px;}")
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("<b>Your PC</b>"))
        rl.addWidget(QLabel("AMD Ryzen 5 5500 · RTX 4060 8 GB"))
        self.cpu_lab = QLabel("CPU"); rl.addWidget(self.cpu_lab)
        self.cpu = Spark("#3daee9"); rl.addWidget(self.cpu)
        self.gpu_lab = QLabel("GPU"); rl.addWidget(self.gpu_lab)
        self.gpu = Spark("#27ae60"); rl.addWidget(self.gpu)
        self.vram_lab = QLabel("GPU memory"); rl.addWidget(self.vram_lab)
        self.vram = Spark("#f67400"); rl.addWidget(self.vram)
        rl.addSpacing(8)
        rl.addWidget(QLabel("<b>With the selected preset</b>"))
        self.est = QLabel(); self.est.setWordWrap(True); rl.addWidget(self.est)
        rl.addStretch(1)
        right.setMinimumWidth(270)
        h.addWidget(right, 1)
        self.pick(self.cards[2])
        return w

    def pick(self, card):
        for c in self.cards:
            c.set_selected(c is card)
        p = next(x for x in PRESETS if x[0] == card.name)
        free = 8188 - self.used_vram()
        need = 1700 if p[2] == "GPU" else 0
        self.est.setText(
            "≈ %.2f s per new line on this PC (measured once with a short test)<br>"
            "+%s<br>%s" % (p[9], p[3],
                           ("GPU memory: needs ~1.7 GB, %.1f GB free now ✓" % (free / 1024)) if need and free > need + 500 else
                           ("<span style='color:#da4453'>GPU memory: needs ~1.7 GB, only %.1f GB free</span>" % (free / 1024)) if need else
                           "no graphics-card memory used"))

    def used_vram(self):
        try:
            return int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                      capture_output=True, text=True, timeout=2).stdout)
        except Exception:
            return 0

    def sample(self):
        if not hasattr(self, "cpu"):
            return
        c = psutil.cpu_percent()
        self.cpu.push(c); self.cpu_lab.setText("CPU %d%%" % c)
        try:
            u, m = [int(x) for x in subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=2).stdout.split(",")]
        except Exception:
            u, m = 0, 0
        self.gpu.push(u); self.gpu_lab.setText("GPU %d%%" % u)
        self.vram.push(100 * m / 8188); self.vram_lab.setText("GPU memory %.1f / 8.0 GB" % (m / 1024))

    # -------------------------------------------------------------------------------------------- advanced
    def advanced(self):
        w = QWidget(); h = QHBoxLayout(w)
        nav = QListWidget(); nav.setFixedWidth(160)
        nav.addItems(["Overlay", "Translation", "Models", "Games", "Names", "Advanced"]); nav.setCurrentRow(1)
        h.addWidget(nav)
        v = QVBoxLayout()
        v.addWidget(QLabel("<i>(today's settings pages, unchanged; the preset row stays on top of Translation)</i>"))
        row = QHBoxLayout(); row.setSpacing(0)
        for t in ("Light", "Light+", "Fast", "Balanced", "Quality"):
            b = QPushButton(t); b.setCheckable(True); b.setChecked(t == "Fast"); row.addWidget(b)
        row.addWidget(QLabel("  Custom")); row.addStretch(1)
        v.addLayout(row)
        v.addWidget(QLabel("Who translates:  [Language model | Processor | Visual novel | Online]"))
        v.addWidget(QLabel("Language model: Gemma 4 E2B · Model runner: auto · Show translation as it is written"))
        v.addWidget(QLabel("Reading: accurate / fast · Typewriter wait (experimental) · OCR on graphics card"))
        v.addStretch(1)
        h.addLayout(v, 1)
        return w


class Compare(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Compare translation methods")
        self.resize(900, 360)
        rows = [("Runs on", "Processor", "Processor", "Graphics card", "Internet"),
                ("Memory", "0.5 GB RAM", "1.1 GB RAM", "1.7 GB GPU", "none"),
                ("Download", "included", "1.1 GB", "3.1 GB", "none"),
                ("Per new line", "~0.03 s", "~0.05 s", "~0.15 s", "~0.2-0.5 s"),
                ("Menus / UI", "good, literal", "poor", "good", "good"),
                ("Dialogue", "weakest", "good (also adult)", "best", "good"),
                ("Names, context, OCR typos", "no", "no", "yes", "no"),
                ("Languages", "one model per pair", "Japanese → English", "any pair", "any pair"),
                ("Privacy", "local", "local", "local", "text sent to the company"),
                ("Licence", "CC-BY 4.0", "NTT non-commercial", "Gemma terms", "service terms")]
        t = QTableWidget(len(rows), 4)
        t.setHorizontalHeaderLabels(["quickmt", "Sugoi", "Gemma 4 E2B", "Online (Google…)"])
        t.setVerticalHeaderLabels([r[0] for r in rows])
        for i, r in enumerate(rows):
            for j, v in enumerate(r[1:]):
                t.setItem(i, j, QTableWidgetItem(v))
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay = QVBoxLayout(self); lay.addWidget(t)


if __name__ == "__main__":
    app = QApplication(sys.argv[:1])
    view = sys.argv[1] if len(sys.argv) > 1 else "simple"
    w = Window(view); w.show()
    if view == "compare":
        QTimer.singleShot(300, lambda: Compare(w).show())
    sys.exit(app.exec())
