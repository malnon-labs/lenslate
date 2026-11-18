"""Offline packs: one file of processor translators, checked file by file on import."""
import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest

from tests import ROOT, SCRATCH  # noqa: F401 - sets up the scratch folders first
import models


class OfflinePack(unittest.TestCase):
    def setUp(self):
        self.m = models.BY_NAME["quickmt-ja-en"]
        self.keep = None
        if os.path.exists(self.m.path):          # (scratch models folder; never the user's)
            self.keep = tempfile.mkdtemp(dir=SCRATCH)
            shutil.move(self.m.path, os.path.join(self.keep, "m"))
        os.makedirs(self.m.path)
        for f in self.m.files:
            with open(os.path.join(self.m.path, f), "wb") as fh:
                fh.write(("fake %s\n" % f).encode() * 50)
        open(os.path.join(self.m.path, ".complete"), "w").write("{}")
        self.dir = tempfile.mkdtemp(dir=SCRATCH)
        self.pack = os.path.join(self.dir, "p.tar")
        models.make_pack(self.pack, ["quickmt-ja-en"])

    def tearDown(self):
        shutil.rmtree(self.m.path, ignore_errors=True)
        if self.keep:
            shutil.move(os.path.join(self.keep, "m"), self.m.path)

    def _wipe(self):
        shutil.rmtree(self.m.path)
        self.assertFalse(self.m.installed())

    def test_round_trip(self):
        self._wipe()
        done, skipped = models.import_pack(self.pack)
        self.assertEqual((done, skipped), (["quickmt-ja-en"], []))
        self.assertTrue(self.m.installed())
        self.assertEqual(models.import_pack(self.pack), ([], ["quickmt-ja-en"]))   # already there

    def _rewrite(self, change):
        """A copy of the pack with one member changed by change(name, data) -> data."""
        out = os.path.join(self.dir, "bad.tar")
        with tarfile.open(self.pack) as src, tarfile.open(out, "w") as dst:
            for mem in src.getmembers():
                data = change(mem.name, src.extractfile(mem).read())
                mem.size = len(data)
                dst.addfile(mem, io.BytesIO(data))
        return out

    def test_a_changed_file_is_refused(self):
        bad = self._rewrite(lambda n, d: d.replace(b"fake", b"evil") if n.endswith("model.bin") else d)
        self._wipe()
        with self.assertRaises(RuntimeError):
            models.import_pack(bad)
        self.assertFalse(self.m.installed())

    def test_another_revision_is_refused(self):
        def change(n, d):
            if n != models.PACK_MANIFEST:
                return d
            j = json.loads(d)
            j["models"]["quickmt-ja-en"]["revision"] = "0" * 40
            return json.dumps(j).encode()
        with self.assertRaises(RuntimeError):
            models.import_pack(self._rewrite(change))

    def test_not_a_pack(self):
        p = os.path.join(self.dir, "x.tar")
        open(p, "w").write("hello")
        with self.assertRaises(RuntimeError):
            models.read_pack(p)


if __name__ == "__main__":
    unittest.main()
