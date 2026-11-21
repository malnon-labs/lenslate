"""The AppImage's app menu entry: added for the AppImage where it is, removed again, install.sh's entry untouched."""
import os
import unittest

from tests import SCRATCH

import appmenu


class AppMenu(unittest.TestCase):
    def setUp(self):
        self.img = os.path.join(SCRATCH, "my apps", "lenslate-0.2.0-x86_64.AppImage")   # a folder with a space
        os.makedirs(os.path.dirname(self.img), exist_ok=True)
        open(self.img, "w").close()
        self.old = os.environ.get("LENSLATE_APPIMAGE")
        os.environ["LENSLATE_APPIMAGE"] = self.img

    def tearDown(self):
        for p in (appmenu.entry_path(), appmenu.icon_path()):
            if os.path.exists(p):
                os.remove(p)
        if self.old is None:
            os.environ.pop("LENSLATE_APPIMAGE", None)
        else:
            os.environ["LENSLATE_APPIMAGE"] = self.old

    def test_add_and_remove(self):
        self.assertIsNone(appmenu.state())
        appmenu.install()
        self.assertEqual(appmenu.state(), "ours")
        text = open(appmenu.entry_path(), encoding="utf-8").read()
        self.assertIn('Exec="%s" gui' % self.img, text)
        self.assertIn("Icon=lenslate", text)
        self.assertTrue(os.path.exists(appmenu.icon_path()))
        self.assertTrue(appmenu.remove())
        self.assertIsNone(appmenu.state())
        self.assertFalse(os.path.exists(appmenu.icon_path()))

    def test_the_installers_entry_is_left_alone(self):
        os.makedirs(appmenu.apps_dir(), exist_ok=True)
        with open(appmenu.entry_path(), "w") as f:
            f.write("[Desktop Entry]\nName=lenslate\nExec=/home/x/.local/bin/lenslate gui\n")
        self.assertEqual(appmenu.state(), "installed")
        self.assertFalse(appmenu.remove())
        with self.assertRaises(RuntimeError):
            appmenu.install()
        self.assertIn("/home/x/.local/bin/lenslate", open(appmenu.entry_path()).read())

    def test_not_an_appimage(self):
        os.environ.pop("LENSLATE_APPIMAGE")
        self.assertIsNone(appmenu.appimage())
        with self.assertRaises(RuntimeError):
            appmenu.install()


if __name__ == "__main__":
    unittest.main()
