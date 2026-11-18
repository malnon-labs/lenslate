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


def centred(texts, widths, cx=500, h=24, gap=6):
    rows, y = [], 100
    for t, w in zip(texts, widths):
        rows.append({"box": [cx - w / 2, y, cx + w / 2, y + h], "text": t, "score": 0.9})
        y += h + gap
    return rows


class CentredBlocks(unittest.TestCase):
    def test_wrapped_description_in_a_centred_panel_is_one_card(self):
        rows = centred(["Deal 8 damage to all enemies and", "apply 2 Vulnerable to each of", "them."],
                       [420, 360, 70])
        self.assertEqual([b["text"] for b in tf.group_blocks(rows)],
                         ["Deal 8 damage to all enemies and apply 2 Vulnerable to each of them."])

    def test_speech_bubble_in_japanese(self):
        rows = centred(["きょうはいいてんきだから", "いっしょにさんぽしよう"], [260, 240])
        self.assertEqual(len(tf.group_blocks(rows)), 1)

    def test_centred_menu_stays_apart(self):
        self.assertEqual(len(tf.group_blocks(centred(["Start Game", "Options", "Quit"], [200, 140, 80], gap=18))), 3)
        self.assertEqual(len(tf.group_blocks(centred(["Start Game", "Options", "Quit"], [200, 140, 80], gap=6))), 3)
        self.assertEqual(len(tf.group_blocks(centred(["はじめから", "つづきから", "おわる"], [130, 130, 80]))), 3)

    def test_sentences_stay_apart(self):
        rows = centred(["とびらにはかぎがかかっている。", "かぎをさがそう"], [300, 210])
        self.assertEqual(len(tf.group_blocks(rows)), 2)

    def test_off_axis_rows_stay_apart(self):
        rows = centred(["Deal 8 damage to all enemies and", "apply 2 Vulnerable"], [420, 200])
        rows[1]["box"][0] += 300; rows[1]["box"][2] += 300
        self.assertEqual(len(tf.group_blocks(rows)), 2)


import gapsplit  # noqa: E402


def tab_row(words, boxed=True, h=30, margin=9, letter=12, space=6, pad=10, apart=6):
    """A line picture (with margins) of words in separate boxes: words = letter counts per word."""
    H = h + 2 * margin
    width = sum(n * (letter + 2) for n in words) + len(words) * (2 * pad + apart + 4) + 20
    img = np.full((H, width), 30, dtype=np.uint8)
    x, spans = 10, []
    for n in words:
        if boxed:
            img[2:H - 2, x] = 220; img[2:H - 2, x + 1] = 220
        x0 = x + 2 + pad
        for i in range(n):                       # a letter: two strokes and a bar (text is mostly background)
            lx = x0 + i * (letter + 2)
            img[margin + 4:margin + h - 4, lx:lx + 2] = 230
            img[margin + 4:margin + h - 4, lx + letter - 2:lx + letter] = 230
            img[margin + h // 2, lx:lx + letter] = 230
        x1 = x0 + n * (letter + 2)
        spans.append((x0, x1))
        x = x1 + pad
        if boxed:
            img[2:H - 2, x] = 220; img[2:H - 2, x + 1] = 220
        x += 2 + (apart if boxed else space * 7)
    return img, spans


class TabsApart(unittest.TestCase):
    def test_boxed_tabs_are_split(self):
        img, _ = tab_row([7, 8, 5, 5])
        got = gapsplit.split("General Graphics Sound Input", img)
        self.assertEqual([p[0] for p in got], ["General", "Graphics", "Sound", "Input"])

    def test_far_apart_words_are_split(self):
        img, _ = tab_row([7, 8], boxed=False)
        self.assertEqual([p[0] for p in gapsplit.split("General Graphics", img)], ["General", "Graphics"])

    def test_chinese_tabs(self):
        img, _ = tab_row([2, 2, 2])
        self.assertEqual([p[0] for p in gapsplit.split("常规图形声音", img)], ["常规", "图形", "声音"])

    def test_a_sentence_stays_whole(self):
        img = np.full((48, 400), 30, dtype=np.uint8)
        x = 10
        for n in (3, 5, 5, 3):                   # words with normal spaces, tall letters among them
            for i in range(n):
                top = 9 if i % 2 else 15          # ascenders and x-height letters
                img[top:39, x:x + 2] = 230
                img[15:39, x + 8:x + 10] = 230
                img[27, x:x + 10] = 230
                x += 12
            x += 8
        self.assertIsNone(gapsplit.split("The quick brown fox", img))

    def test_two_rows_in_one_box(self):
        img = np.full((80, 200), 30, dtype=np.uint8)
        for x in range(10, 150, 8):
            img[8:32, x:x + 2] = 230
        for x in range(10, 120, 8):
            img[48:72, x:x + 2] = 230
        self.assertEqual(gapsplit.stacked_rows(img), [(8, 32), (48, 72)])
        one = np.full((40, 200), 30, dtype=np.uint8)
        for x in range(10, 150, 8):
            one[8:32, x:x + 2] = 230
        self.assertEqual(gapsplit.stacked_rows(one), [])
