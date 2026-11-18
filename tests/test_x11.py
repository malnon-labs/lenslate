"""X11 helper: answers None instead of ending the process when X reports an error (needs an X server: skipped
without one; XWayland counts)."""
import os
import unittest

from tests import SCRATCH  # noqa: F401

import x11


@unittest.skipUnless(os.environ.get("DISPLAY") and x11.available(), "no X server")
class X11Helper(unittest.TestCase):
    def test_a_window_that_is_gone(self):
        gone = 0x7FFFFF0          # not a window: X answers BadWindow / BadDrawable
        self.assertIsNone(x11.geometry(gone))
        self.assertEqual(x11.window_class(gone), "")
        self.assertIsNone(x11.grab_window(gone))
        x11.raise_window(gone)
        self.assertIsNotNone(x11.pointer())       # the connection still works after the errors

    def test_active_window_is_an_id_or_none(self):
        wid = x11.active_window()
        self.assertTrue(wid is None or isinstance(wid, int))
        if wid:
            g = x11.geometry(wid)
            self.assertTrue(g is None or (g[2] > 0 and g[3] > 0))


if __name__ == "__main__":
    unittest.main()
