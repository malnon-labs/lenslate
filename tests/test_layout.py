"""Overlay card placement: display scale (captured physical pixels -> logical overlay pixels) and collisions."""
import unittest

from tests import ROOT  # noqa: F401 - sets up the scratch folders first
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QGuiApplication, QImage

APP = QGuiApplication.instance() or QGuiApplication([])
import lenslate as ls  # noqa: E402


def card(rect, text="Hello there", lh=32, px_scale=1.0):
    return {"rect": rect, "orig": "x", "tr": text, "bg": QColor(0, 0, 0), "fg": QColor(255, 255, 255),
            "lh": lh, "px_scale": px_scale}


class DisplayScale(unittest.TestCase):
    def test_card_covers_its_logical_box_at_every_scale(self):
        region = QRect(100, 50, 1200, 600)     # logical, on the region's screen
        logical = QRect(300, 200, 400, 40)     # where the text really is, inside the region (logical px)
        want = logical.translated(region.x(), region.y())
        results = []
        for s in (1.0, 1.25, 1.5, 2.0):
            crop = QImage(int(1200 * s), int(600 * s), QImage.Format_RGB32)   # captures are physical pixels
            ps = ls.pixel_scale(crop, region)
            self.assertAlmostEqual(ps, s, places=2)
            phys = QRect(int(300 * s), int(200 * s), int(400 * s), int(40 * s))
            got = ls.layout_cards([card(phys, lh=int(32 * s), px_scale=ps)], region)[0]["layout"][0]
            self.assertTrue(got.contains(want.center()), "scale %s: card %s misses %s" % (s, got, want))
            self.assertLessEqual(abs(got.top() - want.top()), 3)
            self.assertLessEqual(abs(got.height() - want.height()), 4)
            results.append(got.getRect())
        self.assertEqual(len(set(results)), 1, "the same text must give the same card at every scale")

    def test_scale_one_is_unchanged(self):
        crop = QImage(800, 600, QImage.Format_RGB32)
        self.assertEqual(ls.pixel_scale(crop, QRect(0, 0, 800, 600)), 1.0)
        c = card(QRect(10, 10, 100, 20))
        self.assertEqual(ls.to_logical(c)["rect"], QRect(10, 10, 100, 20))


class Collisions(unittest.TestCase):
    def test_widened_cards_do_not_cover_each_other(self):
        region = QRect(0, 0, 1000, 400)
        a = card(QRect(10, 100, 120, 30), "A rather long translation that wants much more room than this", 30)
        b = card(QRect(150, 100, 120, 30), "Another long translation that also wants to grow", 30)
        out = [c["layout"][0] for c in ls.layout_cards([a, b], region)]
        self.assertFalse(out[0].intersects(out[1]), out)


if __name__ == "__main__":
    unittest.main()


class FollowWindow(unittest.TestCase):
    def test_area_moves_and_scales_with_its_window(self):
        area = QRect(300, 400, 600, 200)
        old = QRect(100, 100, 1280, 720)
        self.assertEqual(ls.moved_region(area, old, QRect(500, 60, 1280, 720)), QRect(700, 360, 600, 200))
        full = ls.moved_region(area, old, QRect(0, 0, 1920, 1080))             # windowed -> fullscreen
        self.assertEqual(full, QRect(300, 450, 900, 300))
        self.assertEqual(ls.moved_region(full, QRect(0, 0, 1920, 1080), old), area)   # and back

    def test_daemon_carries_the_area_and_keeps_what_it_read_on_a_move(self):
        class Overlay:
            def __init__(self):
                self.props = {}

            def set(self, k, v):
                self.props[k] = v
        d = ls.Daemon.__new__(ls.Daemon)
        d.overlay, d.screen = Overlay(), QGuiApplication.primaryScreen()
        origin = d.screen.geometry().topLeft()
        d.region = QRect(50, 60, 300, 100)
        d.target = ls.Target("w", QRect(origin.x() + 10, origin.y() + 10, 400, 300))
        d.history, d.junk, d.mem, d.cards, d.raw_cards = ["frame"], [], {"k": 1}, ["c"], ["c"]
        d.gen, d.last_sig, d.text_scale = 3, None, 2.0
        d.follow(ls.Target("w", QRect(origin.x() + 40, origin.y() + 30, 400, 300)))
        self.assertEqual(d.region, QRect(80, 80, 300, 100))
        self.assertEqual((d.overlay.props["regionX"], d.overlay.props["regionY"]), (80, 80))
        self.assertEqual((d.history, d.cards, d.gen, d.text_scale), (["frame"], ["c"], 3, 2.0))
        d.follow(ls.Target("w", QRect(origin.x() + 40, origin.y() + 30, 200, 150)))   # resized: read again
        self.assertEqual(d.region.size(), QRect(0, 0, 150, 50).size())
        self.assertEqual((d.history, d.cards, d.gen, d.text_scale), ([], [], 4, None))


class VanishedCards(unittest.TestCase):
    def test_only_cards_with_changed_picture_and_no_text_left(self):
        import numpy as np
        import textflow as tf
        W, H = 640, 320
        rows, cols = tf.grid_shape(W, H)
        mask = np.zeros((rows, cols), bool)
        mask[:, :cols // 2] = True                                   # the left half of the picture changed
        left, left_text, right = card(QRect(32, 32, 200, 32)), card(QRect(32, 160, 200, 32)), card(QRect(400, 32, 200, 32))
        partly = card(QRect(cols // 2 * tf.CELL - 32, 240, 320, 32))  # typed-out line: a small part changed
        known = [[40, 162, 220, 190]]                                # the quick finder still sees a line there
        gone = ls.vanished_cards([left, left_text, right, partly], mask, known, W, H)
        self.assertEqual([id(c) for c in gone], [id(left)])


class LongWord(unittest.TestCase):
    def test_a_word_wider_than_its_card_is_drawn_smaller_not_cut(self):
        from PySide6.QtGui import QFont, QFontMetrics
        region = QRect(0, 0, 1000, 400)
        for widen in (True, False):
            card_r, size, _a, mx, _my = ls.layout_card(QRect(100, 100, 50, 30), "Settings", region, 30, widen=widen)
            f = QFont(QGuiApplication.font()); f.setPixelSize(size)
            self.assertLessEqual(QFontMetrics(f).horizontalAdvance("Settings"), card_r.width() - 2 * mx,
                                 "widen=%s: %s at %d px" % (widen, card_r, size))


class X11TopWindow(unittest.TestCase):
    def test_the_window_on_top_is_read_not_the_focused_one_behind_it(self):
        """Steam focused, the fullscreen game above it: the game. A small window on top: no override."""
        geo = {1: (0, 0, 1536, 864), 2: (0, 0, 1536, 824), 3: (0, 0, 1536, 864), 4: (500, 300, 400, 300)}
        import types
        had_xb, saved = hasattr(ls, "xb"), getattr(ls, "xb", None)
        try:
            ls.xb = types.SimpleNamespace(hidden=lambda w: w == 9, geometry=lambda w: geo.get(w), stacking=list)
            area = QRect(0, 0, 1536, 864)
            ls.xb.stacking = lambda: [1, 2, 3]            # desktop, Steam, game
            self.assertEqual(ls.x_top_window(area).uuid, "3")
            ls.xb.stacking = lambda: [1, 3, 2, 4]         # a small window on top of Steam
            self.assertIsNone(ls.x_top_window(area))
            geo[9] = (0, 0, 1536, 864)
            ls.xb.stacking = lambda: [1, 2, 9]            # a minimised window is not seen
            self.assertEqual(ls.x_top_window(area).uuid, "2")
        finally:
            ls.xb = saved
            if not had_xb:
                del ls.xb


class X11MixedScales(unittest.TestCase):
    def test_x_pixels_map_through_the_screen_they_are_on(self):
        """KDE XWayland, DP-2 at 100 % and DP-3 at 125 %: X space 2400x1350 + 1280x1024 at 2400,70; Qt: DP-2
        (0,0 1920x1080), DP-3 (2400,70 1024x819), both at ratio 1.25."""
        import types

        class Scr:
            def __init__(self, r):
                self.r = r

            def geometry(self):
                return self.r

            def devicePixelRatio(self):
                return 1.25
        scr = [Scr(QRect(0, 0, 1920, 1080)), Scr(QRect(2400, 70, 1024, 819))]
        real = ls.QGuiApplication
        try:
            ls.QGuiApplication = types.SimpleNamespace(
                screens=lambda: scr, primaryScreen=lambda: scr[0],
                screenAt=lambda p: next((s for s in scr if s.r.contains(p)), None))
            self.assertEqual(ls.x_to_logical(1200, 500), QPoint(960, 400))          # on DP-2
            self.assertEqual(ls.x_to_logical(2400 + 75, 70 + 100), QPoint(2460, 150))   # on DP-3
            ls.xb = types.SimpleNamespace(geometry=lambda w: (2437, 150, 1200, 700))
            self.assertEqual(ls.x_target(5).rect, QRect(2430, 134, 960, 560))
        finally:
            ls.QGuiApplication = real
            if hasattr(ls, "xb") and isinstance(ls.xb, types.SimpleNamespace):
                del ls.xb
