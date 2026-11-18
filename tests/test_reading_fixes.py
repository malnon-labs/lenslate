"""Reading fixes found while making the README screenshots (2026-11-18): word spaces in kana-only lines."""
import unittest

import numpy as np

from tests import ROOT  # noqa: F401 - sets up the scratch folders first
import kanaspace
import textflow as tf


def drawn_line(words, letter=20, inner=3, space=20, h=24):
    """A dark line picture with white 'letters' (blocks): words = letter counts per word."""
    w = sum(n * letter + (n - 1) * inner for n in words) + space * (len(words) - 1) + 20
    img = np.zeros((h, w), dtype=np.uint8)
    x = 10
    for wi, n in enumerate(words):
        for i in range(n):
            img[3:h - 3, x:x + letter] = 255
            x += letter + (inner if i < n - 1 else 0)
        x += space
    return img


class KanaSpaces(unittest.TestCase):
    def test_spaces_put_back_at_word_gaps(self):
        img = drawn_line([4, 1, 7])
        self.assertEqual(kanaspace.word_spaces("なんいどをえらんでください", img), "なんいど を えらんでください")

    def test_no_wide_gap_no_change(self):
        img = drawn_line([12])
        self.assertEqual(kanaspace.word_spaces("なんいどをえらんでください", img), "なんいどをえらんでください")

    def test_lines_with_kanji_or_spaces_are_left_alone(self):
        img = drawn_line([2, 3])
        self.assertEqual(kanaspace.word_spaces("難易度を選ぶ", img), "難易度を選ぶ")
        self.assertEqual(kanaspace.word_spaces("Hello", img), "Hello")

    def test_reader_spaces_kept_and_completed(self):
        img = drawn_line([4, 1, 7])
        self.assertEqual(kanaspace.word_spaces("なんいど\u3000をえらんでください", img), "なんいど を えらんでください")
        self.assertEqual(kanaspace.word_spaces("なんいど\u3000を\u3000えらんでください", drawn_line([14])),
                         "なんいど を えらんでください")

    def test_no_space_after_punctuation(self):
        img = drawn_line([5, 4])
        self.assertEqual(kanaspace.word_spaces("そうだね、いこうか", img), "そうだね、いこうか")
        self.assertEqual(kanaspace.word_spaces("Hello world", img), "Hello world")

    def test_mismatch_is_left_alone(self):
        img = drawn_line([1, 1, 1, 1, 1, 1])   # six words but only five letters read
        self.assertEqual(kanaspace.word_spaces("あいうえお", img), "あいうえお")

    def test_merge_rows_keeps_a_word_gap_between_kana_pieces(self):
        got = [{"box": [0, 0, 80, 24], "text": "なんいど", "score": 0.9},
               {"box": [100, 0, 120, 24], "text": "を", "score": 0.9}]
        self.assertEqual([r["text"] for r in tf.merge_rows(got)], ["なんいど を"])
        got = [{"box": [0, 0, 80, 24], "text": "難易度", "score": 0.9},
               {"box": [100, 0, 120, 24], "text": "を", "score": 0.9}]
        self.assertEqual([r["text"] for r in tf.merge_rows(got)], ["難易度を"])


if __name__ == "__main__":
    unittest.main()


def ln(text, y, h=20):
    return {"box": [10, y, 200, y + h], "text": text, "score": 0.9}


class UltrafastFallback(unittest.TestCase):
    def want(self, got, mem=None, enabled=("ja",), reading="accurate", area_h=240):
        return tf.ultrafast_wanted(got, set(enabled), reading, "cjk", {} if mem is None else mem, area_h)

    def test_sparse_japanese_area_is_tried(self):
        self.assertTrue(self.want([ln("はじめから", 10), ln("つづきから", 40)]))

    def test_full_area_or_other_languages_are_not(self):
        self.assertFalse(self.want([ln("はじめから", i * 25) for i in range(6)]))         # plenty read
        self.assertFalse(self.want([ln("はじめから", 10)], enabled=("zh", "en")))            # Japanese off
        self.assertFalse(self.want([ln("はじめから", 10)], reading="ultrafast"))             # already Ultrafast
        self.assertFalse(self.want([ln("設定", 10)], enabled=("ja", "zh")))                  # maybe Chinese
        self.assertFalse(self.want([ln("はじめから", 10), ln("つづきから", 40)], area_h=70))  # no room for more
        self.assertFalse(self.want([]))

    def test_memory_of_the_region(self):
        mem = {}
        got = [ln("はじめから", 10)]
        alt = [ln("はじめから", 10), ln("つづきから", 40), ln("おぷしょん", 70)]
        self.assertTrue(tf.reads_more(alt, got))
        self.assertFalse(tf.reads_more(got, got))
        tf.note_ultrafast(mem, False)
        tf.note_ultrafast(mem, False)
        self.assertFalse(self.want(got, mem))                       # gave up after two misses
        tf.note_ultrafast(mem, True)
        self.assertTrue(self.want([ln("はじめから", i * 25) for i in range(6)], mem))   # it helped: always
