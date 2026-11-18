"""OCR helper code in the engine environment: vertical text, finder rounding, tile seams. Skipped when the engine
environment (or its models) is not installed; never downloads anything."""
import json
import os
import subprocess
import tempfile
import unittest

from tests import ROOT, SCRATCH

ENGINE_PY = os.path.expanduser("~/.local/share/lenslate/engine/bin/python")


@unittest.skipUnless(os.path.exists(ENGINE_PY), "engine environment not installed")
class OcrEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = tempfile.mkdtemp(dir=SCRATCH)
        r = subprocess.run([ENGINE_PY, "-I", os.path.join(ROOT, "tests", "scripts", "ocr_checks.py"), ROOT, out],
                           capture_output=True, text=True, timeout=600)
        # (importing ocr_server points stdout at stderr: the helper protocol keeps the real stdout for itself)
        lines = [ln for ln in (r.stdout + "\n" + r.stderr).splitlines() if ln.startswith('{"')]
        if r.returncode or not lines:
            raise unittest.SkipTest("OCR models not available offline: %s" % r.stderr.strip()[-200:])
        cls.res = json.loads(lines[-1])
        if "skip" in cls.res:
            raise unittest.SkipTest(cls.res["skip"])

    def test_quick_reads_a_vertical_column(self):
        self.assertEqual(self.res["vertical_quick"], ["最後のチェックポイント"])

    def test_finder_sizes_are_rounded(self):
        self.assertLessEqual(len(self.res["finders"]), 2, self.res["finders"])

    def test_tile_seams_are_joined(self):
        self.assertEqual(len(self.res["row_join"]), 1, self.res["row_join"])
        self.assertEqual(len(self.res["col_join"]), 1, self.res["col_join"])

    def test_helper_runs_isolated_from_another_folder(self):
        """lenslate starts the helper with `python -I` from anywhere: its own modules must still import."""
        from PIL import Image
        img = os.path.join(tempfile.mkdtemp(dir=SCRATCH), "blank.png")
        Image.new("RGB", (64, 32), (0, 0, 0)).save(img)
        r = subprocess.run([ENGINE_PY, "-I", os.path.join(ROOT, "ocr_server.py")], input=json.dumps({"path": img}) + "\n",
                           capture_output=True, text=True, timeout=300, cwd=SCRATCH,
                           env=dict(os.environ, LENSLATE_OCR_GPU="off", HF_HUB_OFFLINE="1"))
        answers = [json.loads(ln) for ln in r.stdout.splitlines() if ln.startswith("{")]
        self.assertTrue(answers and "lines" in answers[-1], r.stdout[-300:] + r.stderr[-300:])


if __name__ == "__main__":
    unittest.main()
