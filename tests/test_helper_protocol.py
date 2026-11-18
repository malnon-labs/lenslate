"""The JSON-lines protocol with the OCR / MT helpers: noise on stdout, a hang, a crash loop, reaping."""
import os
import subprocess
import sys
import time
import unittest

from tests import ROOT
import textflow as tf

FAKE = os.path.join(ROOT, "tests", "fakes", "fake_helper.py")


class Fake(tf.HelperClient):
    def __init__(self, mode):
        super().__init__(ROOT)
        self.cmd = [sys.executable, "-I", FAKE]
        self.extra_env = {"FAKE_MODE": mode}

    def _own_env(self):
        return {}


class HelperProtocol(unittest.TestCase):
    def test_noise_and_foreign_answers_are_skipped(self):
        c = Fake("noise")
        try:
            self.assertEqual(c.read("A")[0], ["A"])
            self.assertEqual(c.read("B")[0], ["B"])   # never the answer meant for another request
        finally:
            c.stop()

    def test_stop_reaps_the_process(self):
        c = Fake("noise")
        c.read("A")
        pid = c.proc.pid
        c.stop()
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        self.assertEqual(state, "", "a zombie or a live process was left: %r" % state)

    def test_hang_times_out_and_kills(self):
        c = Fake("hang")
        c.TIMEOUT = 1
        t = time.time()
        with self.assertRaises(RuntimeError) as e:
            c.read("A")
        self.assertLess(time.time() - t, 5)
        self.assertIn("did not answer", str(e.exception))
        self.assertIsNone(c.proc)

    def test_crash_loop_backs_off(self):
        c = Fake("crash")
        with self.assertRaises(RuntimeError):
            c.read("A")              # dies, restarted once at once, dies again
        launches_before = c.fails
        with self.assertRaises(RuntimeError) as e:
            c.read("A")              # within the back-off: no new start
        self.assertIn("trying again", str(e.exception))
        self.assertEqual(c.fails, launches_before)

    def test_follow_config_never_waits_for_a_busy_helper(self):
        c = Fake("noise")
        with c.lock:                 # as if a long read were running
            t = time.time()
            self.assertIsNone(c.follow_config())
            self.assertLess(time.time() - t, 0.5)


if __name__ == "__main__":
    unittest.main()
