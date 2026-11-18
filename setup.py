"""First-launch setup window (roadmap step 4): languages -> preset (with the hardware check) -> downloads -> done.

Opens by itself the first time the settings window starts ([general] setup_done = false), or with
`lenslate setup` / the "Run setup again" button on the Translation page. Nothing heavy is downloaded without the
user ticking it and pressing Download; nothing is written to config.toml until Finish (except a model that was
downloaded). Cancel keeps the current settings.
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QProgressBar, QPushButton, QRadioButton, QVBoxLayout, QWizard, QWizardPage)

import config as cfgmod
from i18n import _
import hwcheck
import langs
import shortcutsdialog
import theme
from theme import set_role


def _c(token):
    return "color:%s;" % theme.color(token)
HELP = "Hover over anything to see what it does."
_JOBS = []   # running download threads outlive a closed window (a QThread must not be destroyed while running)


class PageHelp(QObject):
    """Hover help: shows a widget's "help" text in the help bar of the page that is shown."""

    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Enter, QEvent.Leave) and obj.property("help"):
            page = self.wiz.currentPage()
            if page is not None and hasattr(page, "bar"):
                enter = ev.type() == QEvent.Enter
                page.bar.setText(obj.property("help") if enter else _(HELP))
                set_role(page.bar, state="help" if enter else "idle")
        return False


def help_bar(page):
    page.bar = QLabel(_(HELP))
    page.bar.setWordWrap(True)
    page.bar.setFixedHeight(54)
    page.bar.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    return set_role(page.bar, "helpbar", state="idle")


def _label(text, wrap=True, style=""):
    text = _(text)
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    lab.setTextFormat(Qt.RichText)
    if style:
        lab.setStyleSheet(style)
    return lab


class Setup(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("lenslate setup"))
        self.setWizardStyle(QWizard.ClassicStyle)
        self.resize(860, 680)
        self.flt = PageHelp(self)
        self.info = hwcheck.summary()
        self.measure = False
        self.addPage(LanguagesPage(self))
        self.addPage(PresetPage(self))
        self.addPage(DownloadsPage(self))
        self.addPage(DonePage(self))
        self.setButtonText(QWizard.FinishButton, "Finish")
        for b in (QWizard.NextButton, QWizard.FinishButton):
            set_role(self.button(b), "primary")

    def explain(self, w, text):
        text = _(text)
        w.setProperty("help", text)
        w.setToolTip("<p style='max-width:420px'>%s</p>" % text)
        w.installEventFilter(self.flt)
        return w

    # the current choices (written to config.toml only on Finish)
    def sources(self):
        return ",".join(self.page(0).codes())

    def target(self):
        return self.page(0).tgt.currentData()

    def llm_for(self, sources, target):
        """The language model for these languages: the automatic pick (PLaMo for Japanese -> English, Gemma
        otherwise), unless the user chose another model of their own before (that choice is kept)."""
        cur = cfgmod.get("translator.llm_model")
        if cur and cur not in hwcheck.AUTO_LLMS and cfgmod.BY_KEY["translator.llm_model"].default != cur:
            import models
            if models.find(cur) is not None:
                return models.find(cur).name
        return hwcheck.pick_llm(sources, target)[0]

    def llm(self):
        return self.llm_for(self.sources(), self.target())

    def preset(self):
        return self.page(1).chosen

    def accept(self):
        if self.page(2).running():
            QMessageBox.information(self, "Downloading", "Wait for the downloads to finish (or press Cancel on them).")
            return
        cfgmod.set_many({"translator.sources": self.sources(), "translator.language": self.target(),
                         "translator.llm_model": self.llm()})
        cfgmod.apply_preset(self.preset())
        cfgmod.set("general.setup_done", True)
        self.measure = self.page(3).measure.isChecked()
        super().accept()

    def reject(self):
        if self.page(2).running():
            if QMessageBox.question(self, "Stop downloading?", "A download is still running. Close setup anyway? "
                                    "(The download stops; it continues where it left off next time.)") != QMessageBox.Yes:
                return
            self.page(2).cancel()
            if self.page(2).job is not None:
                self.page(2).job.wait(5000)
        cfgmod.set("general.setup_done", True)   # do not ask again on every start; "Run setup again" brings it back
        super().reject()


# ------------------------------------------------------------------------------------------------ 1. languages
LANG_HELP = {
    "ja": "Japanese games, visual novels, manga, video subtitles.",
    "zh": "Chinese games and text, Simplified and Traditional characters.",
    "en": "English games and text (useful when you translate into Spanish, Portuguese or Chinese).",
    "ko": "Korean. Read by its own reader model, so it goes together with English only (not with Japanese, "
          "Chinese or Russian). Its processor translator is literal and weak on lone words (menus come from a "
          "ready-made list); the language model translates it better.",
    "ru": "Russian. Read by its own reader model, so it goes together with English only (not with Japanese, "
          "Chinese or Korean). Its processor translator is literal and weak on lone words (menus come from a "
          "ready-made list); the language model translates it better.",
}


class LanguagesPage(QWizardPage):
    """Tick the languages to translate: they decide what is downloaded (only the translators these languages
    need) and which language model is suggested."""

    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(_("Welcome to lenslate"))
        self.setSubTitle(_("lenslate paints translations over text anywhere on your screen, on this computer. "
                         "Which languages do you need? Only what they need is downloaded."))
        cur = langs.sources(cfgmod.get("translator.sources"))
        self.boxes = {}
        col = QVBoxLayout()
        col.addWidget(QLabel(_("<b>Translate from</b> (tick every language you read in games or on screen)")))
        names = dict(langs.ALL_SOURCES, zh="Chinese (Simplified and Traditional)")
        for code in langs.ALL_SOURCES:
            cb = QCheckBox(_(names[code]))
            cb.setChecked(code in cur)
            wiz.explain(cb, LANG_HELP[code])
            cb.toggled.connect(lambda on, c=code: self.toggled(c, on))
            self.boxes[code] = cb
            col.addWidget(cb)
        col.addWidget(set_role(_label(_("Korean and Russian each have their own reader: one of them at a time, with "
                                      "English.")), "muted"))
        self.tgt = QComboBox()
        for c in cfgmod.BY_KEY["translator.language"].choices:   # shown translated, the value is kept as data
            self.tgt.addItem(_(c), c)
        self.tgt.setCurrentIndex(max(0, self.tgt.findData(cfgmod.get("translator.language"))))
        wiz.explain(self.tgt, "The language the translations are written in.")
        self.tgt.currentIndexChanged.connect(lambda _i: self.refresh())
        row = QHBoxLayout()
        row.addWidget(QLabel(_("<b>Translate into</b>")))
        row.addWidget(self.tgt)
        row.addStretch(1)
        self.plan = _label(_(""))
        wiz.explain(self.plan, "What these languages need. The processor translators are always installed for "
                    "them (small, no graphics-card memory, also the backup when the language model is busy or "
                    "missing). The language model is only downloaded with a preset that uses the graphics card "
                    "(next page).")
        plan = set_role(QFrame(), "card")
        pl = QVBoxLayout(plan)
        pl.setContentsMargins(12, 10, 12, 10)
        pl.addWidget(self.plan)
        lay = QVBoxLayout(self)
        lay.addLayout(col)
        lay.addSpacing(8)
        lay.addLayout(row)
        lay.addSpacing(8)
        lay.addWidget(plan)
        lay.addWidget(set_role(_label(_("You can change these later on the Translation page.")), "muted"))
        lay.addStretch(1)
        lay.addWidget(help_bar(self))
        self.refresh()

    def toggled(self, code, on):
        if on:   # Korean / Russian have their own reader: with English only
            own = set(langs.OWN_READER)
            clash = (set(langs.ALL_SOURCES) - {"en", code}) if code in own else own
            for c in clash:
                self.boxes[c].blockSignals(True)
                self.boxes[c].setChecked(False)
                self.boxes[c].blockSignals(False)
        self.refresh()

    def codes(self):
        """The ticked languages that will be translated ("English" into English is nothing to do)."""
        tgt = langs.TARGET_CODES.get(self.tgt.currentData().lower(), "en")
        return [c for c in langs.ALL_SOURCES if self.boxes[c].isChecked() and not (c == "en" and tgt == "en")]

    def refresh(self):
        import hwcheck
        import models
        tgt = self.tgt.currentData()
        en = self.boxes["en"]
        en.setEnabled(tgt != "English")
        en.setToolTip("" if tgt != "English" else "Text already in English is left as it is.")
        codes = self.codes()
        if not codes:
            self.plan.setText(_("<span style='%s'>Tick at least one language%s.</span>") % (
                _c("warning_text"), " other than English" if tgt == "English" else ""))
        else:
            src = ",".join(codes)
            base = sorted((models.BY_NAME[m] for m in hwcheck.language_models(src, tgt) if m),
                          key=lambda m: m.can.startswith("English"))   # route order: X -> English -> target
            name, why = hwcheck.pick_llm(src, tgt)
            llm = models.BY_NAME[self.wiz.llm_for(src, tgt)]
            lines = []
            if base:
                lines.append(_("<b>Always installed</b> (processor, %.1f GB): %s") % (
                    sum(m.size_gb for m in base), ", ".join(m.can for m in base)))
            else:
                lines.append(_("<b>No processor translator</b> is needed for these languages: only the language "
                             "model below or an online service."))
            lines.append(_("<b>Language model</b> (%.1f GB download, %.1f GB of graphics-card memory; only with a "
                         "preset that uses the graphics card): %s%s") % (llm.size_gb, llm.vram_gb or 0, llm.title,
                                                                         " - %s" % why if llm.name == name else _(" (your own choice)")))
            if llm.name.startswith("plamo"):
                lines.append("<span style='%s'>PLaMo's licence allows personal and non-commercial use only.</span>"
                             % _c("text_muted"))
            self.plan.setText("<br>".join(lines))
        self.completeChanged.emit()

    def isComplete(self):
        return bool(self.codes())


# --------------------------------------------------------------------------------------------------- 2. preset
class PresetPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(_("How should lenslate work on this PC?"))
        self.setSubTitle(_("A preset picks several settings at once. The recommended one fits the hardware lenslate "
                         "found; you can pick any other, and change it any time on the Translation page."))
        self.chosen = None
        self.lay = QVBoxLayout(self)
        self.pc = _label(_(""))
        self.wiz.explain(self.pc, "What lenslate found in this PC. The graphics card's own memory decides whether the "
                         "language model (best translations) fits next to a game.")
        self.rec = _label(_(""))
        self.group = QButtonGroup(self)
        self.radios = {}
        box = QGridLayout()
        box.setColumnMinimumWidth(0, 140)
        box.setColumnStretch(1, 1)
        box.setHorizontalSpacing(12)
        box.setVerticalSpacing(8)
        self.rec_chips = {}
        for i, name in enumerate(cfgmod.PRESET_ORDER):
            p = cfgmod.PRESETS[name]
            r = QRadioButton(p["label"])
            wiz.explain(r, "%s Trade-off: %s" % (p["summary"], p["tradeoff"]))
            r.toggled.connect(lambda on, n=name: on and self.pick(n))
            self.group.addButton(r)
            self.radios[name] = r
            desc = set_role(_label(p["summary"]), "muted")
            wiz.explain(desc, "%s Trade-off: %s" % (p["summary"], p["tradeoff"]))
            chip = set_role(QLabel(_("★ Recommended")), "chip", kind="accent")
            chip.setVisible(False)
            self.rec_chips[name] = chip
            box.addWidget(r, i, 0, Qt.AlignTop)
            box.addWidget(desc, i, 1)
            box.addWidget(chip, i, 2, Qt.AlignTop)
        frame = set_role(QFrame(), "panel")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.addWidget(self.pc)
        self.lay.addWidget(frame)
        self.lay.addWidget(self.rec)
        self.lay.addLayout(box)
        self.trade = _label(_(""))
        tcard = set_role(QFrame(), "card")
        tl = QVBoxLayout(tcard)
        tl.setContentsMargins(12, 10, 12, 10)
        tl.addWidget(self.trade)
        self.warn = set_role(_label(_("")), "message", kind="warning")
        self.lay.addSpacing(8)
        self.lay.addWidget(tcard)
        self.lay.addWidget(self.warn)
        self.use_rec = set_role(QPushButton(), "secondary")
        self.use_rec.setVisible(False)
        self.use_rec.clicked.connect(lambda: self.radios[self.recommended].setChecked(True))
        self.lay.addWidget(self.use_rec, 0, Qt.AlignLeft)
        self.lay.addStretch(1)
        self.lay.addWidget(help_bar(self))

    def initializePage(self):
        i = self.wiz.info
        g = hwcheck.best_gpu(i)
        gpu = ("%s, %.0f GB of its own memory%s" % (g["name"], g["vram_mb"] / 1024,
                                                   (", %.1f GB free now" % ((g["vram_mb"] - g["used_mb"]) / 1024))
                                                   if g["used_mb"] is not None else "")
               if g and g["dedicated"] else ("integrated %s graphics (no memory of its own)" % g["vendor"]) if g
               else "no graphics card found")
        self.pc.setText(_("<b>Your PC</b><br>Processor: %s (%d threads)<br>Graphics: %s<br>Memory: %.0f GB · "
                        "Free disk space: %s") % (i["cpu"], i["threads"], gpu, i["ram_gb"],
                                                 "%.0f GB" % i["disk_free_gb"] if i["disk_free_gb"] is not None else "?"))
        self.recommended, why = hwcheck.recommend(i, self.wiz.sources(), self.wiz.target(), llm=self.wiz.llm())
        self.rec.setText(_("Recommended: <b>%s</b> (%s).") % (cfgmod.PRESETS[self.recommended]["label"], why))
        for n, r in self.radios.items():
            self.rec_chips[n].setVisible(n == self.recommended)
        start = self.chosen or self.recommended
        self.radios[start].setChecked(True)
        self.pick(start)

    def pick(self, name):
        self.chosen = name
        import models
        p = cfgmod.PRESETS[name]
        uses = ""
        if p["values"].get("translator.kind") == "llm":
            m = models.BY_NAME[self.wiz.llm()]
            uses = "<br>Language model for your languages: <b>%s</b> (%.1f GB of graphics-card memory)." % (
                m.title, m.vram_gb or 0)
        self.trade.setText(_("<b>%s</b>: %s<br>Trade-off: %s%s") % (p["label"], p["summary"], p["tradeoff"], uses))
        self.problems = hwcheck.check(name, self.wiz.info, self.wiz.sources(), self.wiz.target(), llm=self.wiz.llm())
        self.warn.setText("<br>".join("⚠ " + t for t in self.problems))
        self.warn.setVisible(bool(self.problems))
        other = name != self.recommended
        self.use_rec.setVisible(bool(self.problems) and other)
        self.use_rec.setText(_("Use %s instead") % cfgmod.PRESETS[self.recommended]["label"])

    def validatePage(self):
        if not self.problems:
            return True
        alt = cfgmod.PRESETS[self.recommended]["label"]
        text = "%s may not suit this PC:\n\n%s" % (cfgmod.PRESETS[self.chosen]["label"],
                                                   "\n\n".join("• " + t for t in self.problems))
        box = QMessageBox(QMessageBox.Warning, "Check this preset", text, parent=self)
        keep = set_role(box.addButton("Use %s anyway" % cfgmod.PRESETS[self.chosen]["label"], QMessageBox.AcceptRole),
                        "secondary")
        switch = None
        if self.chosen != self.recommended:
            switch = set_role(box.addButton("Use %s instead" % alt, QMessageBox.ActionRole), "primary")
        box.addButton("Go back", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is keep:
            return True
        if switch is not None and box.clickedButton() is switch:
            self.radios[self.recommended].setChecked(True)
            return True
        return False


# ------------------------------------------------------------------------------------------------ 3. downloads
class DownloadsPage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(_("Downloads"))
        self.setSubTitle(_("What the chosen preset and languages need. Nothing is downloaded until you press "
                         "Download. Everything can also be added or removed later on the Models page."))
        self.lay = QVBoxLayout(self)
        self.grid = QGridLayout()
        self.lay.addLayout(self.grid)
        self.total = _label(_(""))
        self.lay.addWidget(self.total)
        row = QHBoxLayout()
        self.go = set_role(QPushButton(_("↓ Download selected")), "download")
        self.go.clicked.connect(self.start)
        wiz.explain(self.go, "Download the ticked items one after another. You can keep reading while it runs; "
                    "an interrupted download continues where it stopped next time.")
        self.stop_btn = set_role(QPushButton(_("Cancel downloads")), "danger")
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self.cancel)
        row.addWidget(self.go)
        row.addWidget(self.stop_btn)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.status = _label(_(""))
        self.lay.addWidget(self.status)
        self.lay.addStretch(1)
        self.lay.addWidget(help_bar(self))
        self.items = []
        self.job = None
        self.queue = []
        self.cancelled = False

    def running(self):
        return self.job is not None and self.job.isRunning()

    def initializePage(self):
        import models
        import ocrgpu
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.items = []
        preset, src, tgt = self.wiz.preset(), self.wiz.sources(), self.wiz.target()
        plabel = cfgmod.PRESETS[preset]["label"]
        need = hwcheck.preset_needs(preset, src, tgt, llm=self.wiz.llm())
        rows = []   # (key, title, GB, licence, why, checked, installed)
        for m in need["models"]:
            mm = models.BY_NAME[m]
            rows.append((m, mm.title, mm.size_gb, mm.license, "needed by %s" % plabel, True, mm.installed()))
        if need["ocr_gpu"]:
            rows.append(("ocr-gpu", "Reading on the graphics card (CUDA runtime)", hwcheck.OCR_GPU_DL_GB,
                         "NVIDIA CUDA EULA", "needed by %s" % plabel, True, ocrgpu.installed()))
        for m in hwcheck.language_models(src, tgt, "mt"):   # processor models: menus, and the fallback
            if m not in need["models"]:
                mm = models.BY_NAME[m]
                rows.append((m, mm.title, mm.size_gb, mm.license, "always installed for your languages: small, on "
                             "the processor, and the backup when the language model is missing or busy", True,
                             mm.installed()))
        if "ja" in langs.sources(src) and "sugoi-v4-ja-en" not in need["models"]:
            mm = models.BY_NAME["sugoi-v4-ja-en"]
            rows.append((mm.name, mm.title, mm.size_gb, mm.license, "optional: the Visual novel translator on the "
                         "processor (Visual novel translator)", False, mm.installed()))
        for i, (key, title, gb, lic, why, checked, installed) in enumerate(rows):
            cb = QCheckBox(title)
            cb.setChecked(checked and not installed)
            cb.setEnabled(not installed)
            cb.toggled.connect(self.update_total)
            can = getattr(models.BY_NAME.get(key), "can", "")
            self.wiz.explain(cb, "%s. %s%.1f GB download, licence: %s." % (
                why[0].upper() + why[1:], ("Translates: %s. " % can) if can else "", gb, lic))
            info = _label(_("%.1f GB · %s%s · %s") % (gb, ("<b>%s</b> · " % can) if can else "", lic,
                                                  "<span style='%s'>✓ installed</span>" % _c("success_text")
                                                  if installed else why))
            bar = QProgressBar()
            bar.setVisible(False)
            bar.setMaximumWidth(220)
            self.grid.addWidget(cb, i, 0)
            self.grid.addWidget(info, i, 1)
            self.grid.addWidget(bar, i, 2)
            self.items.append({"key": key, "title": title, "gb": gb, "cb": cb, "bar": bar, "info": info,
                               "installed": installed})
        self.grid.setColumnStretch(1, 1)
        self.status.setText("")
        self.update_total()

    def selected(self):
        return [it for it in self.items if it["cb"].isChecked() and not it["installed"]]

    def update_total(self):
        gb = sum(it["gb"] for it in self.selected())
        free = self.wiz.info.get("disk_free_gb")
        low = free is not None and gb + 1 > free
        self.total.setText(_("<b><span style='%s'>%sSelected: %.1f GB · free disk space: %s</span></b>") % (
            _c("warning_text") if low else "", "⚠ Not enough disk space. " if low else "", gb,
            "%.0f GB" % free if free is not None else "?"))
        self.go.setEnabled(bool(gb) and not self.running())

    def start(self):
        self.queue = self.selected()
        self.cancelled = False
        self.go.setEnabled(False)
        self.stop_btn.setVisible(True)
        for it in self.items:
            it["cb"].setEnabled(False)
        self.next_item()
        self.completeChanged.emit()

    def cancel(self):
        self.cancelled = True
        self.queue = []
        if self.job is not None:
            self.status.setText(_("Stopping…"))

    def next_item(self):
        import gui
        if self.cancelled or not self.queue:
            self.finish_all()
            return
        it = self.queue.pop(0)
        bar = it["bar"]
        bar.setVisible(True)
        bar.setRange(0, 0)
        self.status.setText(_("Downloading %s…") % it["title"])
        if it["key"] == "ocr-gpu":
            import ocrgpu
            fn = lambda progress: ocrgpu.install()   # noqa: E731 - pip shows no byte progress: busy bar
        else:
            import models
            key = it["key"]

            def fn(progress):
                def guarded(*a):   # Cancel: stop inside the file (the .part file resumes next time)
                    if self.cancelled:
                        raise RuntimeError("cancelled")
                    progress(*a)
                return models.download(key, guarded)

        job = gui.Job(fn)

        def prog(done, total, text):
            if total > 0:
                bar.setRange(0, 1000)
                bar.setValue(int(1000 * done / total))
            bar.setFormat((text[:24] + " %p%") if text else "%p%")

        def ok(_r):
            if self.cancelled and not self.isVisible():
                return
            bar.setVisible(False)
            it["installed"] = True
            it["info"].setText(_("%.1f GB · <span style='%s'>✓ installed</span>") % (it["gb"], _c("success_text")))
            self.next_item()

        def bad(e):
            if self.cancelled and not self.isVisible():
                return
            bar.setVisible(False)
            it["info"].setText("stopped (continues where it left off next time)" if e == "cancelled" else
                               "<span style='%s'>⚠ failed: %s</span>" % (_c("danger_text"), e))
            it["cb"].setChecked(True)
            self.next_item()
        job.progress.connect(prog)
        job.finished_ok.connect(ok)
        job.failed.connect(bad)
        self.job = job
        _JOBS[:] = [j for j in _JOBS if j.isRunning()] + [job]
        job.start()

    def finish_all(self):
        self.job = None
        self.stop_btn.setVisible(False)
        for it in self.items:
            it["cb"].setEnabled(not it["installed"])
            if it["installed"]:
                it["cb"].setChecked(False)
        left = self.selected()
        self.status.setText("Stopped." if self.cancelled else
                            "Some downloads failed; press Download selected to try again." if left else
                            "All downloads are done.")
        self.update_total()
        self.completeChanged.emit()

    def isComplete(self):
        return not self.running()

    def validatePage(self):
        missing = [it["title"] for it in self.selected()]
        if not missing:
            return True
        r = QMessageBox.question(self, "Not downloaded yet", "These are ticked but not downloaded:\n\n%s\n\n"
                                 "Continue without them? Until the preset's model is downloaded, lenslate uses the "
                                 "small processor translator instead (machine-like wording). The Models page can "
                                 "download them later." % "\n".join("• " + t for t in missing))
        return r == QMessageBox.Yes


# ------------------------------------------------------------------------------------------------------- 4. done
class DonePage(QWizardPage):
    def __init__(self, wiz):
        super().__init__()
        self.wiz = wiz
        self.setTitle(_("Ready"))
        self.setSubTitle(_("lenslate is set up. Here is how to use it."))
        self.lay = QVBoxLayout(self)
        self.text = _label(_(""))
        self.lay.addWidget(self.text)
        self.measure = QCheckBox(_("Measure this PC's speed now (about 15-40 seconds)"))
        wiz.explain(self.measure, "Reads and translates a sample dialogue box with each installed method, so the "
                    "Translation page can show real numbers for your processor and graphics card. The processor is busy "
                    "for a moment.")
        self.lay.addWidget(self.measure)
        keys = set_role(QPushButton(_("Keyboard shortcuts…")), "secondary")
        wiz.explain(keys, "See and change the four hotkeys. lenslate checks that a key is free before it uses it.")
        keys.clicked.connect(lambda: (shortcutsdialog.ShortcutsDialog(self).exec(), self.initializePage()))
        keys.setMaximumWidth(220)
        self.lay.addWidget(keys)
        self.lay.addStretch(1)
        self.lay.addWidget(help_bar(self))

    def initializePage(self):
        import bench
        p = cfgmod.PRESETS[self.wiz.preset()]
        self.text.setText(
            _("<p>Preset: <b>%s</b> · translating %s into <b>%s</b>.</p>"
            "<p><b>How to use it:</b> open the settings window (or the tray icon's menu) and use its buttons:</p><ul>"
            "<li><b>Pick area…</b>: drag a box around the text to translate (a dialogue box, subtitles, a page)</li>"
            "<li><b>Translate now</b>: translate that area again</li>"
            "<li><b>Keep translating automatically</b>: new text is translated as it appears</li>"
            "<li><b>Show / hide</b>: the translations</li></ul>"
            "<p>The same four have keyboard shortcuts for use inside a game: %s (the Keyboard shortcuts "
            "button below changes them). "
            "Hover over anything in the settings window for an explanation. Run this setup again from the "
            "Translation page.</p>")
            % (p["label"], " / ".join(langs.ALL_SOURCES[c] for c in sorted(langs.sources(self.wiz.sources()))),
               self.wiz.target(), ", ".join(k for k in shortcutsdialog.keys_now().values() if k) or "none set yet"))
        self.measure.setChecked(bench.load() is None)


def run(parent=None):
    """Show the setup window; returns (accepted, measure_now)."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None and not app.styleSheet():    # started on its own (`lenslate setup`), not from the window
        theme.install(app)
        import i18n
        i18n.install_qt(app)
    w = Setup(parent)
    ok = w.exec() == QWizard.Accepted
    return ok, (ok and w.measure)
