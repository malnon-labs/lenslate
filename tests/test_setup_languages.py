"""First-launch setup by language: the ticked languages decide the downloads and the language model."""
import unittest

from tests import SCRATCH  # noqa: F401 - sets the private config and cache folders

try:
    from PySide6.QtWidgets import QApplication
except ImportError:      # the GUI toolkit is a system package: skip where it is missing
    QApplication = None

import config as cfgmod
import hwcheck


class PickModel(unittest.TestCase):
    def test_plamo_only_for_japanese_into_english(self):
        self.assertEqual(hwcheck.pick_llm("ja", "English")[0], "plamo-3-translate-0.8b")
        self.assertEqual(hwcheck.pick_llm("ja,en", "English")[0], "plamo-3-translate-0.8b")   # English: nothing to do
        for src, tgt in (("ja", "Portuguese (Brazil)"), ("ja,zh", "English"), ("ko,en", "English"),
                         ("en", "Spanish"), ("ja,zh,en", "English")):
            self.assertEqual(hwcheck.pick_llm(src, tgt)[0], "gemma-4-e2b", (src, tgt))

    def test_processor_base_is_only_what_the_languages_need(self):
        self.assertEqual(hwcheck.language_models("zh", "English"), ["quickmt-zh-en"])
        self.assertEqual(sorted(hwcheck.language_models("ja", "Portuguese (Brazil)")),
                         ["opus-en-ptbr", "quickmt-ja-en"])
        self.assertEqual(hwcheck.language_models("ko,en", "English"), ["quickmt-ko-en"])
        self.assertEqual(sorted(hwcheck.language_models("ru", "Portuguese (Brazil)")), ["opus-en-ptbr", "quickmt-ru-en"])

    def test_the_picked_model_is_what_the_preset_needs(self):
        need = hwcheck.preset_needs("balanced", "ja", "English", llm="plamo-3-translate-0.8b")
        self.assertEqual(need["models"], ["plamo-3-translate-0.8b"])
        self.assertLess(need["vram_gb"], 1.0)


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class LanguagesPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import setup
        cfgmod.set("translator.llm_model", "gemma-4-e2b")
        self.w = setup.Setup()
        self.p = self.w.page(0)

    def tearDown(self):
        self.w.close()

    def tick(self, *codes):
        for c, b in self.p.boxes.items():
            b.setChecked(c in codes)

    def test_korean_and_russian_go_with_english_only(self):
        self.tick("ja", "zh")
        self.p.boxes["ko"].setChecked(True)
        self.assertEqual({c for c, b in self.p.boxes.items() if b.isChecked()}, {"ko"})
        self.p.boxes["ja"].setChecked(True)
        self.assertFalse(self.p.boxes["ko"].isChecked())

    def test_choices_reach_the_wizard_and_config(self):
        self.p.tgt.setCurrentText("English")
        self.tick("ja", "en")
        self.assertEqual(self.w.sources(), "ja")          # English into English is left out
        self.assertEqual(self.w.llm(), "plamo-3-translate-0.8b")
        self.assertTrue(self.p.isComplete())
        self.tick("en")
        self.assertFalse(self.p.isComplete())             # nothing to translate
        self.p.tgt.setCurrentText("Spanish")
        self.assertTrue(self.p.isComplete())
        self.assertEqual(self.w.llm(), "gemma-4-e2b")

    def test_a_model_the_user_chose_is_kept(self):
        cfgmod.set("translator.llm_model", "qwen3.5-4b-uncensored")
        self.p.tgt.setCurrentText("English")
        self.tick("ja")
        self.assertEqual(self.w.llm(), "qwen3.5-4b-uncensored")


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class DownloadsNext(unittest.TestCase):
    """Next on the Downloads page downloads what is ticked and goes on; with nothing that can translate it warns on
    the page first (Next without downloading left people with no translator, 2026-11-20 review)."""
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import models
        import setup
        cfgmod.set_many({"translator.sources": "ja", "translator.language": "English",
                         "translator.llm_model": "gemma-4-e2b"})
        self.w = setup.Setup()
        self.p = self.w.page(2)
        self.w.page(1).chosen = "nogpu"
        self.p.initializePage()
        self.models = models
        self.old = models.download

    def tearDown(self):
        self.models.download = self.old
        self.w.close()

    def pump(self, until, limit=5.0):
        import time
        end = time.time() + limit
        while not until() and time.time() < end:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(until())

    def test_next_downloads_the_ticked_items_then_goes_on(self):
        import os
        got = []

        def fake(name, progress=None):      # what a finished download leaves: the model folder with .complete
            got.append(name)
            path = self.models.BY_NAME[name].path
            os.makedirs(path, exist_ok=True)
            open(os.path.join(path, ".complete"), "w").close()
        self.models.download = fake
        self.addCleanup(lambda: [os.remove(os.path.join(self.models.BY_NAME[n].path, ".complete")) for n in got])
        self.w.setStartId(2)                          # the wizard on the Downloads page
        self.w.restart()
        self.assertIs(self.w.currentPage(), self.p)
        self.assertTrue(self.p.selected())            # quickmt ja-en is ticked for Japanese
        self.assertNotEqual(self.p.buttonText(setup_wizard().NextButton), self.p.next_text)
        self.w.next()                                 # Next starts the downloads instead of leaving the page
        self.assertEqual(self.w.currentId(), 2)
        self.pump(lambda: self.w.currentId() == 3)    # ... and goes on by itself when they are done
        self.assertIn("quickmt-ja-en", got)

    def test_nothing_to_translate_with_warns_once(self):
        for it in self.p.items:
            it["cb"].setChecked(False)
        self.assertEqual(self.p.buttonText(setup_wizard().NextButton), self.p.next_text)
        self.assertFalse(self.p.has_translator())
        self.assertFalse(self.p.validatePage())       # first Next: the warning on the page
        self.assertIn("Nothing is ticked", self.p.status.text())
        self.assertTrue(self.p.validatePage())        # second Next: the user's choice


def setup_wizard():
    from PySide6.QtWidgets import QWizard
    return QWizard


if __name__ == "__main__":
    unittest.main()
