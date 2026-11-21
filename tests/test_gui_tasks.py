"""Background work in the settings window survives a page rebuild: the bar is drawn again and the button stays
locked (a second download could be started before)."""
import os
import threading
import unittest

from tests import SCRATCH  # noqa: F401 - sets the private config and cache folders

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
except ImportError:      # the GUI toolkit is a system package: skip where it is missing
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class TaskBars(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gui
        import theme
        cls.app = QApplication.instance() or QApplication(["test"])
        theme.install(cls.app)
        cls.gui = gui
        cls.win = gui.MainWindow()

    def pump(self, until, limit=5.0):
        import time
        end = time.time() + limit
        while not until() and time.time() < end:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(until())

    def test_download_survives_a_page_rebuild(self):
        import models
        win = self.win
        win.show_page("Models")
        self.app.processEvents()
        m = next(x for x in models.CATALOG if not os.path.exists(os.path.join(x.path, ".complete")))
        gate, calls = threading.Event(), []

        def fake(name, progress):
            calls.append(name)
            progress(500, 1000, "half")
            gate.wait(5)
        old, models.download = models.download, fake
        try:
            win._model_action(m)
            key = "model:" + m.name
            self.pump(lambda: (win.tasks.get(key) or {}).get("value") == 500)
            win.rebuild_pages()                      # what a settings click does
            self.app.processEvents()
            btn, bar = win.model_rows[m.name]
            self.assertFalse(btn.isEnabled())
            self.assertFalse(bar.isHidden())
            self.assertEqual(bar.value(), 500)
            win._model_action(m)                     # a second click must not start a second download
            self.assertEqual(calls, [m.name])
            gate.set()
            self.pump(lambda: key not in win.tasks)
            self.app.processEvents()
            btn, bar = win.model_rows[m.name]
            self.assertTrue(btn.isEnabled())
            self.assertTrue(bar.isHidden())
            self.assertEqual(win.jobs, [])
        finally:
            gate.set()
            models.download = old


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gui
        import theme
        cls.app = QApplication.instance() or QApplication(["test"])
        theme.install(cls.app)
        cls.gui = gui

    def test_a_page_opens_by_name_with_the_sidebar_folded(self):
        # the sidebar's texts are translated, or empty when folded: pages were looked up by their English text
        win = self.gui.MainWindow()
        win.set_nav_collapsed(True)
        win.show_page("Translation")
        self.assertEqual(win.nav.currentRow(), 1)
        win.show_page("names & fixes")
        self.assertEqual(win.nav.currentRow(), 4)
        win.close()

    def test_no_names_note_only_for_an_empty_list(self):
        import names as nm
        os.makedirs(nm.NAMES_DIR, exist_ok=True)
        path = os.path.join(nm.NAMES_DIR, "zz-test-game.tsv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(nm.HEADER.format(game="zz-test-game") + "リゲル\tRigel\n")
        try:
            win = self.gui.MainWindow()
            win.show_page("Names & fixes")
            self.app.processEvents()
            win.name_game.setCurrentIndex(win.name_game.findData("zz-test-game"))
            self.assertEqual(win.name_table.rowCount(), 1)
            self.assertTrue(win.names_empty.isHidden())        # it stood above a filled table before
            win.name_game.setCurrentIndex(win.name_game.findData("global"))
            self.assertEqual(win.name_table.rowCount(), 0)
            self.assertFalse(win.names_empty.isHidden())
            self.assertEqual(win.name_game.currentText(), "All games")
            win.close()
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
