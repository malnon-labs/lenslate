"""Every text lenslate's windows show, collected from the real widgets (run in its own process per language).

    python3 -m tests.window_texts LANG      prints a JSON list of {"text", "where"}

Opens the settings window (every page, tab and dropdown), the tray menu, the setup window (every page) and the
Keyboard shortcuts dialog offscreen, with the private test folders from tests/__init__.py. Used by
tests/test_i18n_windows.py: a text shown the same in English and in another language was not translated.
"""
import json
import re
import sys

from tests import SCRATCH  # noqa: F401 - private config, cache and data folders; Qt offscreen


def collect(lang):
    import i18n
    i18n.set_language(lang)
    from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QGroupBox, QLabel, QLineEdit,
                                   QListWidget, QMenu, QSystemTrayIcon, QTableWidget, QTabWidget, QWidget,
                                   QWizard, QWizardPage)
    app = QApplication.instance() or QApplication(["lenslate-test"])
    i18n.install_qt(app)
    import theme
    theme.install(app)
    found = {}

    def add(text, where):
        if isinstance(text, str):
            text = re.sub(r"<[^>]+>", " ", text).replace("&&", "&").replace("&nbsp;", " ")
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                found.setdefault(text, where)

    def menu(m, where):
        for a in m.actions():
            add(a.text(), where)       # (a menu entry's tooltip is its text unless set: not counted)
            if a.menu():
                menu(a.menu(), where)

    def walk(root, where):
        for w in [root] + root.findChildren(QWidget):
            add(w.toolTip(), where)
            add(w.property("help"), where)
            if isinstance(w, QLabel):
                add(w.text(), where)
            if isinstance(w, QAbstractButton):
                add(w.text(), where)
            if isinstance(w, QComboBox):
                for i in range(w.count()):
                    add(w.itemText(i), where)
            if isinstance(w, QGroupBox):
                add(w.title(), where)
            if isinstance(w, QLineEdit):
                add(w.placeholderText(), where)
            if isinstance(w, QTabWidget):
                for i in range(w.count()):
                    add(w.tabText(i), where)
                    add(w.tabToolTip(i), where)
            if isinstance(w, QListWidget):
                for i in range(w.count()):
                    add(w.item(i).text(), where)
                    add(w.item(i).toolTip(), where)
            if isinstance(w, QTableWidget):
                for c in range(w.columnCount()):
                    h = w.horizontalHeaderItem(c)
                    if h:
                        add(h.text(), where)
                        add(h.toolTip(), where)
            if isinstance(w, QWizardPage):
                add(w.title(), where)
                add(w.subTitle(), where)
            if isinstance(w, QMenu):
                menu(w, where)

    import gui
    win = gui.MainWindow()
    for i in range(win.nav.count()):
        win.nav.setCurrentRow(i)
        app.processEvents()
        walk(win, "settings window")
    for folded in (True, False):          # the sidebar's fold button says the other state
        win.set_nav_collapsed(folded)
        walk(win, "settings window")
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
    tray = gui.make_tray(app, win)
    menu(tray.contextMenu(), "tray menu")
    add(tray.toolTip(), "tray menu")
    win.close()

    import setup
    wiz = setup.Setup()
    for pid in wiz.pageIds():
        page = wiz.page(pid)
        try:
            page.initializePage()
        except Exception:  # noqa: BLE001 - a page that needs a real PC: its built texts still count
            pass
        walk(page, "setup window")
    for b in (QWizard.BackButton, QWizard.NextButton, QWizard.FinishButton, QWizard.CancelButton):
        add(wiz.buttonText(b), "setup window")
    wiz.close()

    import shortcutsdialog
    dlg = shortcutsdialog.ShortcutsDialog(None)
    walk(dlg, "shortcuts dialog")
    dlg.close()
    return [{"text": t, "where": w} for t, w in found.items()]


if __name__ == "__main__":
    print(json.dumps(collect(sys.argv[1]), ensure_ascii=False))
