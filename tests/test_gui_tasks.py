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


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class SelfChangedSettings(unittest.TestCase):
    """When lenslate switches a setting by itself, a notice above the page says so and stays (it was a help-bar
    line that the next mouse move erased); after a language change, Undo puts the languages and steps back."""
    @classmethod
    def setUpClass(cls):
        import gui
        import theme
        cls.app = QApplication.instance() or QApplication(["test"])
        theme.install(cls.app)
        cls.gui = gui

    def setUp(self):
        import config as cfgmod
        self.cfg = cfgmod
        self.keep = {k: cfgmod.get(k) for k in self.gui.STEP_KEYS}

    def tearDown(self):
        self.cfg.set_many(self.keep)

    def test_a_new_config_is_not_switched(self):
        self.assertEqual(self.cfg.BY_KEY["ocr.reading"].default, "fast")   # Careful is retired: never the default
        win = self.gui.MainWindow()
        self.assertTrue(win.notice_bar.isHidden())
        win.close()

    def test_a_retired_choice_is_switched_with_a_notice_that_stays(self):
        self.cfg.set("ocr.reading", "accurate")
        win = self.gui.MainWindow()
        self.assertEqual(self.cfg.get("ocr.reading"), "fast")
        self.assertFalse(win.notice_bar.isHidden())
        self.assertIn("Careful", win.notice_text.text())
        self.assertTrue(win.notice_undo.isHidden())      # nothing to go back to: Careful is not offered
        win.say("something else")                        # a help-bar message does not remove it
        self.assertFalse(win.notice_bar.isHidden())
        win.close()

    def test_undo_after_a_language_change(self):
        self.cfg.set_many({"translator.sources": "ja", "translator.language": "English", "ocr.reading": "ultrafast"})
        win = self.gui.MainWindow()
        win.show_page("Translation")
        self.app.processEvents()
        self.assertTrue(win.notice_bar.isHidden())
        self.cfg.set("translator.sources", "zh")         # what the Translate from list does, then:
        win.languages_changed()
        self.assertEqual(self.cfg.get("ocr.reading"), "fast")     # Ultrafast reads Japanese only
        self.assertFalse(win.notice_bar.isHidden())
        self.assertFalse(win.notice_undo.isHidden())
        win.notice_undo.click()
        self.assertEqual(self.cfg.get("translator.sources"), "ja")
        self.assertEqual(self.cfg.get("ocr.reading"), "ultrafast")
        self.assertTrue(win.notice_bar.isHidden())
        win.close()


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class LanguagePicker(unittest.TestCase):
    def test_another_language_says_in_red_that_lenslate_must_restart(self):
        import gui
        import i18n
        app = QApplication.instance() or QApplication(["test"])
        win = gui.MainWindow()
        win.show_page("Advanced")
        app.processEvents()
        box = next(w for w in win.findChildren(gui.QWidget) if hasattr(w, "note") and hasattr(w, "combo"))
        self.assertTrue(box.note.isHidden())                 # the language in use: nothing to say
        box.combo.setCurrentIndex(box.combo.findData("pt"))
        self.assertFalse(box.note.isHidden())
        self.assertIn("Restart lenslate", box.note.text())
        self.assertIn(i18n.catalog("pt")[gui.RESTART_TEXT], box.note.text())   # also in the picked language
        box.combo.setCurrentIndex(box.combo.findData("en"))
        self.assertTrue(box.note.isHidden())
        win.close()


if __name__ == "__main__":
    unittest.main()
