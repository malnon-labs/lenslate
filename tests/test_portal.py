"""Portal capture: the frame side (GStreamer) with a test picture instead of a shared screen; the portal dialog
itself needs a person and is not tested here."""
import time
import unittest

from tests import SCRATCH  # noqa: F401

import portalcap


@unittest.skipIf(portalcap.missing(), "GStreamer / PipeWire plugin not installed")
class PortalFrames(unittest.TestCase):
    def test_newest_frame_and_waiting_for_a_fresh_one(self):
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        st = portalcap.Stream()
        st._play(Gst, "videotestsrc is-live=true ! video/x-raw,width=320,height=180,framerate=30/1")
        try:
            data, w, h, stride = st.frame(wait=5)
            self.assertEqual((w, h, stride, len(data)), (320, 180, 1280, 320 * 180 * 4))
            self.assertEqual(data[:4], b"\xff\xff\xff\xff")          # the test picture starts with a white bar
            t = time.time()
            self.assertIsNotNone(st.frame(newer_than=t, wait=3))
            self.assertGreater(st.sample_at, t)
        finally:
            st.stop()
        self.assertIsNone(st.frame(wait=0.1))

    def test_token_is_private(self):
        import os
        portalcap._save_token("abc")
        self.assertEqual(portalcap._load_token(), "abc")
        self.assertEqual(os.stat(portalcap.TOKEN_PATH).st_mode & 0o777, 0o600)
        portalcap.forget()
        self.assertEqual(portalcap._load_token(), "")


if __name__ == "__main__":
    unittest.main()
