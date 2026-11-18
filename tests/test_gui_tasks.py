"""Background work in the settings window survives a page rebuild: the bar is drawn again and the button stays
locked (a second download could be started before)."""
import os
import threading
import unittest

from tests import SCRATCH  # noqa: F401 - sets the private config and cache folders

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt
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
        win.nav.setCurrentItem(win.nav.findItems("Models", Qt.MatchFixedString)[0])
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


if __name__ == "__main__":
    unittest.main()
