"""Hardware checks when nvidia-smi cannot talk to the card (a hybrid laptop with the NVIDIA card switched off, or a
driver that is not loaded): nvidia-smi then prints an error message instead of data. Seen on the test laptop
(2026-11-21): the settings window did not open at all."""
import os
import stat
import unittest

from tests import SCRATCH

import bench
import hwcheck
import textflow

FAILING = "#!/bin/sh\necho \"NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver. " \
          "Make sure that the latest NVIDIA driver is installed and running.\"\nexit 9\n"


class NvidiaSmiFails(unittest.TestCase):
    def setUp(self):
        self.bin = os.path.join(SCRATCH, "fake-nvidia-bin")
        os.makedirs(self.bin, exist_ok=True)
        path = os.path.join(self.bin, "nvidia-smi")
        with open(path, "w") as f:
            f.write(FAILING)
        os.chmod(path, stat.S_IRWXU)
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = self.bin + os.pathsep + self.old_path

    def tearDown(self):
        os.environ["PATH"] = self.old_path

    def test_no_card_is_reported_and_nothing_crashes(self):
        hw = bench._hardware()
        self.assertIsNone(hw["gpu"])
        self.assertEqual(hw["vram_mb"], 0)
        self.assertIsNone(bench.gpu_now())
        self.assertIsNone(textflow.gpu_free_mb())
        self.assertFalse([g for g in hwcheck.gpus() if g["vendor"] == "NVIDIA" and g["vram_mb"]])


if __name__ == "__main__":
    unittest.main()
