"""The "Keyboard shortcuts" dialog (settings window, Overlay page, and the setup window's last page).

Shows lenslate's four hotkeys as the desktop has them now, lets the user press new ones, checks them for clashes
(with the desktop's own shortcuts and other programs', and with each other) and writes them to the desktop
(hotkeys.apply: KDE through KGlobalAccel, Cinnamon / GNOME through gsettings). Where lenslate cannot write them
(Hyprland, Sway, niri, i3, Xfce, MATE ...) it shows the lines to paste, made from the keys chosen here.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QApplication, QDialog, QGridLayout, QHBoxLayout, QKeySequenceEdit, QLabel,
                               QPlainTextEdit, QPushButton, QVBoxLayout)

import hotkeys as hk
from i18n import N_, _


def _role(w, role):
    w.setProperty("role", role)   # styled by the window's stylesheet when it knows the role (theme.py)
    return w


def keys_now(desk=None):
    """{action: combo} as the desktop has them, with the defaults where nothing could be read."""
    desk = desk or hk.desktop()
    try:
        cur = hk.current(desk)
    except Exception:  # noqa: BLE001 - reading must never break the window
        cur = None
    return {a: (cur or {}).get(a) or (None if cur is not None else hk.DEFAULTS[a]) for a, _w in hk.ACTIONS}


def key_text(action, keys=None):
    """'Ctrl+Alt+Z' for a hint, or 'none'."""
    k = (keys or keys_now()).get(action)
    return k or "none"


# each command as the dialog names it (hotkeys.ACTIONS keeps the lower-case English the desktops' lists show)
LABELS = {"select": N_("Pick the area to translate"), "now": N_("Translate the area again"),
          "auto": N_("Auto refresh on / off"), "toggle": N_("Hide / show the translations")}


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None, desk=None, on_saved=None):
        super().__init__(parent)
        self.desk = desk or hk.desktop()
        self.on_saved = on_saved
        self.can_write = hk.writable(self.desk)
        self.setWindowTitle(_("Keyboard shortcuts"))
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        intro = QLabel((_("Press a new key combination for a command, then Save. lenslate checks first that "
                          "nothing else on %s uses it.") if self.can_write else
                        _("lenslate cannot change shortcuts on %s itself. Choose keys here, then add the lines "
                          "below to your desktop's settings.")) % hk.NAMES.get(self.desk, self.desk))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        grid = QGridLayout()
        grid.setColumnStretch(3, 1)
        self.edits, self.notes = {}, {}
        start = keys_now(self.desk)
        for row, (action, what) in enumerate(hk.ACTIONS):
            grid.addWidget(QLabel(_(LABELS.get(action, what))), row, 0)
            e = QKeySequenceEdit()
            if hasattr(e, "setMaximumSequenceLength"):
                e.setMaximumSequenceLength(1)
            if start.get(action):
                e.setKeySequence(QKeySequence(start[action]))
            e.setMinimumWidth(170)
            e.keySequenceChanged.connect(lambda _s: self.check())
            clear = _role(QPushButton(_("No key")), "quiet")
            clear.setToolTip(_("Take the key away from this command"))
            clear.clicked.connect(lambda _c=False, e=e: e.clear())
            note = QLabel()
            note.setWordWrap(True)
            _role(note, "muted")
            grid.addWidget(e, row, 1)
            grid.addWidget(clear, row, 2)
            grid.addWidget(note, row, 3)
            self.edits[action], self.notes[action] = e, note
        lay.addLayout(grid)
        self.paste = QPlainTextEdit()
        self.paste.setReadOnly(True)
        self.paste.setVisible(not self.can_write)
        self.paste.setMinimumHeight(120)
        lay.addWidget(self.paste)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        buttons = QHBoxLayout()
        defaults = _role(QPushButton(_("Defaults")), "secondary")
        defaults.setToolTip(_("Ctrl+Alt+Z, X, C and V: free in the default shortcuts of every desktop lenslate "
                              "knows"))
        defaults.clicked.connect(self.defaults)
        buttons.addWidget(defaults)
        buttons.addStretch(1)
        close = _role(QPushButton(_("Close")), "secondary")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        self.save_btn = _role(QPushButton(_("Save")), "primary")
        self.save_btn.clicked.connect(self.save)
        self.save_btn.setVisible(self.can_write)
        buttons.addWidget(self.save_btn)
        lay.addLayout(buttons)
        self.check()

    def chosen(self):
        out = {}
        for a, e in self.edits.items():
            t = e.keySequence().toString(QKeySequence.PortableText)
            try:
                out[a] = hk.normal(t) if t else ""
            except ValueError:
                out[a] = t
        return out

    def defaults(self):
        for a, e in self.edits.items():
            e.setKeySequence(QKeySequence(hk.DEFAULTS[a]))

    def check(self):
        keys = self.chosen()
        try:
            bad = hk.conflicts(self.desk, keys) if self.can_write else \
                {a: w for a, w in hk.conflicts("other", keys).items()}
        except Exception as e:  # noqa: BLE001
            bad = {}
            self.status.setText(_("Could not check the keys: %s") % e)
        for a, note in self.notes.items():
            w = bad.get(a)
            if w:
                note.setText(w if w.startswith(("needs", "also", "unknown", "empty")) else "taken by " + w)
                note.setProperty("state", "error")
            else:
                note.setText("" if keys[a] else _("no key"))
                note.setProperty("state", "")
            note.style().unpolish(note)
            note.style().polish(note)
        self.save_btn.setEnabled(not bad)
        if not self.can_write:
            text = []
            for head, body in hk.lines(self.desk, keys={a: k for a, k in keys.items() if k and a not in bad}):
                text.append(head)
                text += ["  " + ln for ln in body]
            self.paste.setPlainText("\n".join(text))
        return bad

    def save(self):
        if self.check():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            msg = hk.apply(self.desk, self.chosen())
        except (RuntimeError, ValueError) as e:
            self.status.setText(_("Nothing was changed: %s") % e)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.status.setText(_("Saved: %s.") % msg)
        if self.on_saved:
            self.on_saved(self.chosen())
