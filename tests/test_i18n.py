"""lenslate's own windows in other languages: the catalogs stay in step with the code."""
import json
import os
import re
import unittest

from tests import ROOT
import i18n

SPEC = re.compile(r"%[-.0-9]*[sdfr%]")


class Catalogs(unittest.TestCase):
    def test_every_entry_is_a_text_the_windows_show_with_the_same_placeholders(self):
        shown = set(i18n.extract())
        for code in i18n.LANGS:
            if code == "en":
                continue
            path = os.path.join(ROOT, "i18n", code + ".json")
            with open(path, encoding="utf-8") as f:
                cat = json.load(f)
            self.assertGreater(len(cat), 150, code)
            for en, tr in cat.items():
                self.assertIn(en, shown, "%s: %r is no longer in the code" % (code, en[:60]))
                self.assertEqual(SPEC.findall(en), SPEC.findall(tr), "%s: %r" % (code, en[:60]))

    def test_every_text_is_translated(self):
        shown = [t for t in i18n.extract() if i18n.needs_words(t)]
        for code in i18n.LANGS:
            if code != "en":
                missing = [t[:50] for t in shown if t not in i18n.catalog(code)]
                self.assertEqual(missing, [], code)

    def test_lookup_and_fallback(self):
        i18n.set_language("pt")
        try:
            self.assertEqual(i18n._("Pick area…"), "Selecionar área…")
            self.assertEqual(i18n._("not in any catalog"), "not in any catalog")
        finally:
            i18n.set_language("en")
        self.assertEqual(i18n._("Pick area…"), "Pick area…")

    def test_system_language(self):
        self.assertEqual(i18n.system_language({"LANG": "pt_BR.UTF-8"}), "pt")
        self.assertEqual(i18n.system_language({"LANGUAGE": "zh_CN:en", "LANG": "en_US.UTF-8"}), "zh")
        self.assertEqual(i18n.system_language({"LANG": "de_DE.UTF-8"}), "en")
        self.assertEqual(i18n.system_language({}), "en")


if __name__ == "__main__":
    unittest.main()
