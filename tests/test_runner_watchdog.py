"""The model runner's watchdog shell: the server ends with lenslate (also after kill -9) and on stop()."""
import os
import subprocess
import sys
import time
import unittest

from tests import ROOT  # noqa: F401
import llm


def alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:   # a zombie counts as gone
        return open("/proc/%d/stat" % pid).read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


def child_of(pid):
    for _ in range(50):
        out = subprocess.run(["ps", "-o", "pid=", "--ppid", str(pid)], capture_output=True, text=True).stdout.split()
        if out:
            return int(out[0])
        time.sleep(0.05)
    return None


def watchdog(parent_pid, *cmd):
    return subprocess.Popen(["sh", "-c", llm.WATCHDOG, "lenslate-runner", str(parent_pid)] + list(cmd))


class Watchdog(unittest.TestCase):
    def test_server_ends_when_lenslate_is_killed(self):
        parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1000)"])
        wd = watchdog(parent.pid, "sleep", "1000")
        server = child_of(wd.pid)
        self.assertTrue(llm._is_runner(wd.pid))
        parent.kill()
        parent.wait()
        wd.wait(5)
        self.assertFalse(alive(server))

    def test_terminate_stops_the_server_at_once(self):
        wd = watchdog(os.getpid(), "sleep", "1000")
        server = child_of(wd.pid)
        t = time.time()
        wd.terminate()
        wd.wait(5)
        self.assertLess(time.time() - t, 2)
        time.sleep(0.1)
        self.assertFalse(alive(server))

    def test_watchdog_exits_with_the_server(self):
        self.assertEqual(watchdog(os.getpid(), "sh", "-c", "exit 3").wait(5), 3)

    def test_stale_pid_is_not_a_runner(self):
        self.assertFalse(llm._is_runner(os.getpid()))


if __name__ == "__main__":
    unittest.main()
