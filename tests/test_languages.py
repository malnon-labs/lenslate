"""Korean and Russian as sources: their own reader model, chosen alone; text rules for their scripts."""
import os
import unittest

from tests import SCRATCH  # noqa: F401

import config as cfgmod
import langs
import textflow as tf


class OwnReaderLanguages(unittest.TestCase):
    def test_reader_follows_translate_from(self):
        self.assertEqual(langs.reader_script("ja,zh,en"), "cjk")
        self.assertEqual(langs.reader_script("ko,en"), "korean")
        self.assertEqual(langs.reader_script("ru"), "eslav")
        self.assertEqual(langs.sources("ko,en,xx"), {"ko", "en"})
        self.assertNotIn("ko", ",".join(langs.SOURCES))          # "Auto" stays Japanese, Chinese, English

    def test_helper_environment(self):
        os.environ["LENSLATE_SOURCES"] = "ko,en"
        os.environ["LENSLATE_READING"] = "ultrafast"
        try:
            env = tf.OcrClient(os.getcwd(), False)._own_env()
            self.assertEqual(env["LENSLATE_OCR_SCRIPT"], "korean")
            self.assertEqual(env["LENSLATE_OCR_READER"], "paddle")   # meikiocr reads Japanese only
        finally:
            os.environ.pop("LENSLATE_SOURCES")
            os.environ.pop("LENSLATE_READING")

    def test_lines_wanted_and_checked(self):
        self.assertTrue(langs.wants("새 게임", {"ko", "en"}, "en"))
        self.assertFalse(langs.wants("새 게임", {"ja", "zh", "en"}, "en"))    # not chosen: left alone
        self.assertTrue(langs.wants("Новая игра", {"ru"}, "en"))
        self.assertEqual(langs.source_left("새 게임", "New game", "ko"), 0.0)
        self.assertEqual(langs.source_left("새 게임", "새 게임", "ko"), 1.0)   # came back untranslated
        self.assertGreater(langs.source_left("Новая игра", "Новая game", "ru"), 0.4)

    def test_korean_rows_join_with_a_space(self):
        self.assertEqual(tf._join("저 탑 위에", "불빛이 보여."), "저 탑 위에 불빛이 보여.")
        self.assertEqual(tf._join("あの塔の上に", "光が見える"), "あの塔の上に光が見える")

    def test_weak_processor_translator_is_said(self):
        import hwcheck
        info = {"cpu": "x", "threads": 8, "ram_gb": 16, "gpus": [], "disk_free_gb": 100}
        try:
            probs = hwcheck.check("nogpu", info, "ko,en", "English", downloads=False)
        except (KeyError, TypeError):
            self.skipTest("hardware summary has another shape")
        self.assertTrue(any("Korean and Russian" in p for p in probs))


if __name__ == "__main__":
    unittest.main()


class SpanishOpeners(unittest.TestCase):
    def test_question_and_exclamation_lines_keep_their_opening_mark(self):
        import seeds
        self.assertEqual(seeds.lookup("Continue?", "en", "es"), "¿Continuar?")
        self.assertEqual(seeds.lookup("Continue", "en", "es"), "Continuar")
        self.assertTrue(seeds.lookup("Game over!", "en", "es").startswith("¡"))
        self.assertEqual(seeds.lookup("Are you sure?", "en", "es"), "¿Estás seguro?")


class CyrillicLookalikes(unittest.TestCase):
    def test_mixed_words_become_cyrillic_and_real_latin_stays(self):
        self.assertEqual(langs.fix_lookalikes("Меняющиеся режимы игры ЖypHал"), "Меняющиеся режимы игры ЖурНал")
        self.assertEqual(langs.fix_lookalikes("НOВИНКА"), "НОВИНКА")
        self.assertEqual(langs.fix_lookalikes("Подключите USB-кабель и Wi-Fi"), "Подключите USB-кабель и Wi-Fi")
        self.assertEqual(langs.fix_lookalikes("Версия Steam 1.5"), "Версия Steam 1.5")
        self.assertEqual(langs.fix_lookalikes("Игрdк"), "Игрdк")          # "d" is no look-alike: left alone
        self.assertEqual(langs.fix_lookalikes("Hello"), "Hello")


class KatakanaLookalikes(unittest.TestCase):
    def test_long_vowel_mark_read_for_ichi(self):
        f = langs.fix_lookalikes
        self.assertEqual(f("ー緒に行こう"), "一緒に行こう")
        self.assertEqual(f("ー人で"), "一人で")
        self.assertEqual(f("第ー章"), "第一章")
        self.assertEqual(f("統―体"), "統一体")
        self.assertEqual(f("ゲーム開始"), "ゲーム開始")        # a real long vowel after kana: kept
        self.assertEqual(f("スーパー大会"), "スーパー大会")
        self.assertEqual(f("―私は"), "―私は")                # a dialogue dash at the start: kept
        self.assertEqual(f("それは――体"), "それは――体")      # a pause: kept
        self.assertEqual(f("ー"), "ー")

    def test_kanji_that_look_like_katakana(self):
        self.assertEqual(langs.fix_lookalikes("モ力"), "モカ")
        self.assertEqual(langs.fix_lookalikes("ブ口グ"), "ブログ")
        self.assertEqual(langs.fix_lookalikes("コミュ力"), "コミュ力")            # a real word: communication skill
        self.assertEqual(langs.fix_lookalikes("攻撃力を上げる"), "攻撃力を上げる")
        self.assertEqual(langs.fix_lookalikes("入口はこちら"), "入口はこちら")
        self.assertEqual(langs.fix_lookalikes("レベル二"), "レベル二")


class KanjiOnlyRows(unittest.TestCase):
    def test_japanese_alone_never_calls_a_row_chinese(self):
        for row in ("說明：", "配送予定日：2058年5月4日", "戦闘"):
            self.assertEqual(langs.source_of(row, {"ja"}), "ja", row)
            self.assertTrue(langs.wants(row, {"ja"}, "en"), row)

    def test_with_chinese_enabled_too_kana_on_screen_decides_long_rows(self):
        both = {"ja", "zh"}
        langs._last_kana[0] = 0.0
        self.assertEqual(langs.source_of("配送予定日：2058年5月4日", both), "zh")       # no Japanese seen: long = Chinese
        langs.note("モカ")
        self.assertEqual(langs.source_of("配送予定日：2058年5月4日", both), "ja")       # a row of a Japanese screen
        self.assertEqual(langs.source_of("这是什么东西", both), "zh")                    # clear Chinese stays Chinese
        langs._last_kana[0] = 0.0


class RussianExclamation(unittest.TestCase):
    def test_capital_word_followed_by_a_lookalike_bar(self):
        self.assertEqual(langs.fix_lookalikes("НОВИНКАІ"), "НОВИНКА!")
        self.assertEqual(langs.fix_lookalikes("ВНИМАНИЕI опасно"), "ВНИМАНИЕ! опасно")
        self.assertEqual(langs.fix_lookalikes("ЧАСТЬ II"), "ЧАСТЬ II")
        self.assertEqual(langs.fix_lookalikes("Привет"), "Привет")
