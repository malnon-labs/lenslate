"""The refresh worker (OcrPipeline._run) on drawn scenes with a stand-in reader: which old cards survive a change."""
import unittest

from tests import ROOT  # noqa: F401 - sets up the scratch folders first
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

APP = QGuiApplication.instance() or QGuiApplication([])
import lenslate as ls  # noqa: E402

W, H = 1920, 1080


def scene(lines, shade):
    """A picture with a bar where every text line is, on a background of the given shade."""
    img = QImage(W, H, QImage.Format_RGB32)
    img.fill(QColor(shade, shade, shade))
    p = QPainter(img)
    for box, *_rest in lines:
        p.fillRect(QRect(box[0], box[1], box[2] - box[0], box[3] - box[1]), QColor(240, 240, 240))
    p.end()
    return img


class Cache:
    """Every line is already translated (no model in the test)."""
    def get(self, text):
        return "EN " + text

    def put(self, text, tr):
        pass

    def save(self):
        pass

    def translate_batch(self, texts, *a, **k):
        return {}


class Worker(ls.OcrPipeline):
    """Reads from a list of (box, text) instead of the OCR helper."""
    def __init__(self, lines, history):
        super().__init__(QRect(0, 0, W, H), QRect(0, 0, W, H), history, False, None, None, Cache(), 1.0)
        self.lines = lines
        self.result = None
        self.done.connect(lambda cards, state: setattr(self, "result", (cards, state)))

    def grab(self):
        return scene(self.lines, self.shade)

    def _inside(self, rect):
        return [ln for ln in self.lines
                if rect[0] <= (ln[0][0] + ln[0][2]) / 2 <= rect[2] and rect[1] <= (ln[0][1] + ln[0][3]) / 2 <= rect[3]]

    def detect_rect(self, crop, rect, side=1280):
        return [list(ln[0]) for ln in self._inside(rect)], 0.0

    def read_rect(self, crop, rect, scale):   # a line is (box, text) or (box, text, reader score)
        return [{"box": list(ln[0]), "text": ln[1], "score": ln[2] if len(ln) > 2 else 0.99}
                for ln in self._inside(rect)], 0.0

    def read_known(self, crop, rect, boxes):
        return self.read_rect(crop, rect, 1.0)


def run(lines, shade, history):
    w = Worker(lines, history)
    w.shade = shade
    w._run()
    return w.result


class OldCards(unittest.TestCase):
    def test_cards_of_small_reread_areas_do_not_stay_when_a_big_area_changes_too(self):
        """Found live in Risk of Rain 2 (2026-11-12): logbook list -> item page. The left panel changed as one big
        area; three tab labels on the right were re-read as small areas, nothing was found there, and their cards
        stayed up for good (and a "Back" button got a second card on every refresh)."""
        page = [([170, 200 + 50 * i, 1000, 235 + 50 * i], "一覧の行その%dです。" % i) for i in range(12)]
        tabs = [([1190, 155, 1330, 195], "チャレンジ"), ([1410, 155, 1740, 195], "プロフィール"),
                ([1400, 335, 1690, 380], "ファラデースパー")]
        back = [([165, 980, 228, 1020], "戻る")]
        cards, state = run(page + tabs + back, 20, [])
        self.assertEqual(len(cards), 16)
        history = [(state["grid"], cards)]
        # the item page: other text in the big panel, the tabs are gone, "Back" moved by a few pixels
        page2 = [([170, 210 + 50 * i, 1000, 245 + 50 * i], "説明の文章その%dです。" % i) for i in range(12)]
        back2 = [([165, 990, 228, 1030], "戻る")]
        cards2, _state = run(page2 + back2, 60, history)
        texts = sorted(c["orig"] for c in cards2)
        self.assertNotIn("チャレンジ", texts)
        self.assertNotIn("ファラデースパー", texts)
        self.assertEqual(texts.count("戻る"), 1)
        self.assertEqual(len(cards2), 13)


class HoverHighlight(unittest.TestCase):
    """A button that lights up under the mouse is read badly; its good card must stay (Risk of Rain 2: "Back")."""
    MENU = [([100, 300 + 60 * i, 400, 340 + 60 * i], t) for i, t in enumerate(["はじめから", "つづきから", "せってい"])]
    BACK = [165, 980, 228, 1020]

    def test_a_doubtful_reading_does_not_replace_a_confident_card(self):
        cards, state = run(self.MENU + [(self.BACK, "戻る")], 20, [])
        history = [(state["grid"], cards)]
        for bad in (("戾三", 0.45), ("戾る", 0.74)):               # thrown away as junk / kept but doubtful
            lit = self.MENU + [([160, 975, 233, 1025], bad[0], bad[1])]
            got, _ = run(lit, 20, history)
            texts = sorted(c["orig"] for c in got)
            self.assertEqual(texts.count("戻る"), 1, bad)
            self.assertNotIn(bad[0], texts)
            self.assertEqual(len(got), 4)

    def test_a_confident_new_reading_still_replaces_it(self):
        cards, state = run(self.MENU + [(self.BACK, "戻る")], 20, [])
        got, _ = run(self.MENU + [([160, 975, 233, 1025], "次へ", 0.97)], 20, [(state["grid"], cards)])
        texts = sorted(c["orig"] for c in got)
        self.assertIn("次へ", texts)
        self.assertNotIn("戻る", texts)


class ListRows(unittest.TestCase):
    """Rows of a form ("Label: value") are separate cards; a wrapped paragraph is still one."""

    @staticmethod
    def rows(texts, x=170, w=None):
        return [{"box": [x, 500 + 30 * i, x + (w[i] if w else 12 * len(t)), 528 + 30 * i], "text": t, "score": 0.99}
                for i, t in enumerate(texts)]

    def test_form_rows_stay_apart(self):
        import textflow as tf
        en = ["Estimated Delivery: 05/04/2058", "Shipping Method: Standard Priority",
              "Shipping Address: Museum of Natural History, Ninten", "Island, Earth"]
        got = [b["text"] for b in tf.group_blocks(self.rows(en, w=[400, 400, 620, 150]))]
        self.assertEqual(got, en[:2] + ["Shipping Address: Museum of Natural History, Ninten Island, Earth"])
        ko = ["주문:테이크아웃 커피 컵,473ml입니다", "송장 번호:32*****r"]          # no space after the colon
        self.assertEqual(len(tf.group_blocks(self.rows(ko, w=[400, 220]))), 2)
        ja = ["配送予定日：2058年5月4日です", "配送方法：標準の配送になります"]
        self.assertEqual(len(tf.group_blocks(self.rows(ja, w=[400, 400]))), 2)

    def test_wrapped_text_is_still_one_card(self):
        import textflow as tf
        para = ["My finest brew. Hope it doesn't spoil during transit and", "that we meet again at 10:30 tomorrow",
                "to drink it together."]
        self.assertEqual(len(tf.group_blocks(self.rows(para, w=[700, 700, 300]))), 1)


class MenusAndTabs(unittest.TestCase):
    def test_two_capitalised_short_rows_are_two_buttons(self):
        import textflow as tf
        rows = ListRows.rows(["Меняющиеся режимы игры", "Журнал"], w=[330, 100])
        self.assertEqual(len(tf.group_blocks(rows)), 2)
        rows = ListRows.rows(["Alternate Game Modes", "Logbook"], w=[330, 110])
        self.assertEqual(len(tf.group_blocks(rows)), 2)
        para = ListRows.rows(["The planet is not on any star map we know and", "Captain Reyes wants a full report."],
                             w=[700, 520])
        self.assertEqual(len(tf.group_blocks(para)), 1)                  # running text: more words, still one card

    def test_touching_bracketed_items_are_split(self):
        import textflow as tf
        got = tf.split_touching([{"box": [98, 151, 454, 197], "text": "[アイテム&装備][モンスター", "score": 0.95},
                                 {"box": [500, 151, 600, 197], "text": "環境", "score": 1.0}])
        self.assertEqual([g["text"] for g in got], ["[アイテム&装備]", "[モンスター", "環境"])
        self.assertAlmostEqual(got[0]["box"][2], got[1]["box"][0])
        self.assertTrue(250 < got[0]["box"][2] < 330)
        self.assertEqual(len(tf.merge_rows(got[:2])), 2)                 # and they are not joined again
        one = lambda t: [g["text"] for g in tf.split_touching([{"box": [0, 0, 300, 40], "text": t, "score": 0.9}])]  # noqa: E731
        self.assertEqual(one("[アイテム&装備]モンスター"), ["[アイテム&装備]", "モンスター"])
        self.assertEqual(one("[E] Interact"), ["[E] Interact"])           # a key and its label stay together
        self.assertEqual(one("「はい」と答えた"), ["「はい」と答えた"])       # a quote inside a sentence
        self.assertEqual(one("【重要】お知らせ"), ["【重要】お知らせ"])

    def test_glued_russian_tabs_and_logo_junk(self):
        import textflow as tf
        got = tf.split_touching([{"box": [1410, 154, 1819, 194], "text": "Статистика профиляИстория попыток", "score": 0.99}])
        self.assertEqual([g["text"] for g in got], ["Статистика профиля", "История попыток"])
        near = {"box": [1830, 154, 1900, 194], "text": "Дрон", "score": 0.99}     # the next tab, a few pixels on
        self.assertEqual([r["text"] for r in tf.merge_rows(got + [near])], ["Статистика профиля", "История попыток", "Дрон"])
        keep = tf.split_touching([{"box": [0, 0, 300, 40], "text": "Новая игра в Москве", "score": 0.99}])
        self.assertEqual(len(keep), 1)
        logo = [{"box": [698, 74, 1266, 302], "text": "上HRINE", "score": 0.45},
                {"box": [100, 500, 400, 540], "text": "はじめから", "score": 0.99}]
        self.assertEqual([ln["text"] for ln in tf.plausible(logo, 1080)], ["はじめから"])

    def test_a_lone_bracket_at_the_edge_is_a_button_border(self):
        import textflow as tf
        for raw, want in (("НОВИНКА]", "НОВИНКА"), ("[モンスター", "モンスター"), ("Шпора Фарадея]", "Шпора Фарадея"),
                          ("[E] Interact", "[E] Interact"), ("【重要】", "【重要】"), ("[アイテム&装備]", "[アイテム&装備]"),
                          ("]", "]"), ("a[1] = b[2]", "a[1] = b[2]")):
            self.assertEqual(tf.strip_stray_brackets(raw), want)

    def test_lone_unsure_characters_are_dropped(self):
        import textflow as tf
        lines = [{"box": [114, 202, 148, 236], "text": "日", "score": 0.36},
                 {"box": [300, 202, 334, 236], "text": "力", "score": 0.97},
                 {"box": [98, 151, 454, 197], "text": "アイテム", "score": 0.5}]
        self.assertEqual([ln["text"] for ln in tf.plausible(lines, 1080)], ["力", "アイテム"])
        icons = [{"box": [405, 780, 836, 852], "text": "*日○曰", "score": 0.459},
                 {"box": [405, 900, 836, 940], "text": "はい", "score": 0.93}]
        self.assertEqual([ln["text"] for ln in tf.plausible(icons, 1080)], ["はい"])


if __name__ == "__main__":
    unittest.main()
