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


if __name__ == "__main__":
    unittest.main()
