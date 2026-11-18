"""Hotkeys outside KDE: desktop detection, ready-to-paste lines, and the gsettings writer against a fake store."""
import unittest

from tests import ROOT  # noqa: F401 - sets up the scratch folders first
import hotkeys as hk


class FakeSettings:
    """A tiny gsettings: {(schema-or-item, key): text value}."""

    def __init__(self, values):
        self.v = dict(values)

    def __call__(self, verb, where, key=None, value=None):
        if verb == "list-recursively":
            rows = ["%s %s %s" % (s, k, val) for (s, k), val in self.v.items() if s == where]
            if not rows:
                raise RuntimeError("no such schema")
            return "\n".join(rows)
        if verb == "get":
            return self.v.get((where, key), "''" if key != "binding" else "@as []")
        if verb == "set":
            self.v[(where, key)] = value if value.startswith("[") else "'%s'" % value
            return ""
        if verb == "reset":
            self.v.pop((where, key), None)
            return ""
        raise AssertionError(verb)


CIN = "org.cinnamon.desktop.keybindings"


def item(n):
    return "%s.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/custom%d/" % (CIN, n)


class Desktops(unittest.TestCase):
    def test_detection(self):
        for env, want in (({"XDG_CURRENT_DESKTOP": "KDE"}, "kde"), ({"XDG_CURRENT_DESKTOP": "X-Cinnamon"}, "cinnamon"),
                          ({"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, "gnome"), ({"XDG_CURRENT_DESKTOP": "Hyprland"}, "hyprland"),
                          ({"NIRI_SOCKET": "/run/x"}, "niri"), ({"SWAYSOCK": "/run/s"}, "sway"), ({}, "other")):
            self.assertEqual(hk.desktop(env), want, env)

    def test_lines_for_every_desktop_name_all_four_commands(self):
        for desk in hk.NAMES:
            text = "\n".join(ln for _h, body in hk.lines(desk, cmd="/x/lenslate") for ln in body)
            for action, _what in hk.ACTIONS:
                self.assertIn("lenslate %s" % action if desk != "niri" else '"%s"' % action, text, desk)
        self.assertIn("bind = CTRL ALT, Z, exec, /x/lenslate select", hk.lines("hyprland", cmd="/x/lenslate")[0][1][0])
        self.assertIn("bindsym Ctrl+Mod1+z exec /x/lenslate select", hk.lines("sway", cmd="/x/lenslate")[0][1][0])


class Cinnamon(unittest.TestCase):
    def test_free_keys_are_used_and_removed_again(self):
        gs = FakeSettings({(CIN, "custom-list"): "['custom0']", (item(0), "name"): "'Terminal'",
                           (item(0), "command"): "'xterm'", (item(0), "binding"): "['<Super>t']",
                           (CIN + ".wm", "x"): "['<Super>x']"})
        gs.v[(CIN, "expo")] = "@as []"
        out = hk.install("cinnamon", gs, cmd="/x/lenslate")
        self.assertIn("Ctrl+Alt+Z", out)
        self.assertEqual(gs.v[(CIN, "custom-list")], "['custom0', 'custom1', 'custom2', 'custom3', 'custom4']")
        self.assertEqual(gs.v[(item(1), "binding")], "['<Primary><Alt>z']")
        self.assertEqual(gs.v[(item(1), "command")], "'/x/lenslate select'")
        self.assertEqual(gs.v[(item(0), "command")], "'xterm'")                 # someone else's: untouched
        hk.install("cinnamon", gs, cmd="/x/lenslate")                            # again: replaced, not doubled
        self.assertEqual(len(hk.custom_ids(hk.GS["cinnamon"], gs)), 5)
        self.assertEqual(hk.remove("cinnamon", gs), 4)
        self.assertEqual(gs.v[(CIN, "custom-list")], "['custom0']")
        self.assertEqual(gs.v[(item(0), "binding")], "['<Super>t']")

    def test_taken_keys_move_to_the_next_set(self):
        gs = FakeSettings({(CIN, "custom-list"): "@as []", (CIN, "some-action"): "['<Control><Alt>c']"})
        out = hk.install("cinnamon", gs, cmd="/x/lenslate")
        self.assertIn("some-action", out)
        self.assertEqual(gs.v[(item(0), "binding")], "['<Primary><Alt><Shift>F9']")
        self.assertEqual(gs.v[(CIN, "some-action")], "['<Control><Alt>c']")

class StoreMismatch(unittest.TestCase):
    def test_reads_from_another_database_change_nothing(self):
        """Writes reach the desktop, reads come from an empty file (other XDG_CONFIG_HOME): stop before writing."""
        real = FakeSettings({(CIN, "custom-list"): "['custom0']", (item(0), "name"): "'Flameshot'",
                             (item(0), "command"): "'flameshot gui'", (item(0), "binding"): "['KP_Divide']"})
        empty = FakeSettings({})

        def split(verb, where, key=None, value=None):
            return (empty if verb in ("get", "list-recursively") else real)(verb, where, key, value)
        before = dict(real.v)
        with self.assertRaises(RuntimeError):
            hk.install("cinnamon", gs=split, cmd="lenslate")
        with self.assertRaises(RuntimeError):
            hk.remove("cinnamon", gs=split)
        self.assertEqual(real.v, before)



class ChangeKeys(unittest.TestCase):
    """The settings window's "Keyboard shortcuts" dialog: parse, check, apply (Cinnamon fake, KDE fake bus)."""

    def test_parse_and_spellings(self):
        self.assertEqual(hk.normal("<Primary><Alt>z"), "Ctrl+Alt+Z")
        self.assertEqual(hk.normal("ctrl+shift+alt+f12"), "Ctrl+Alt+Shift+F12")
        self.assertEqual(hk.gtk_key(*hk.parse("Super+PgUp")), "<Super>Page_Up")
        self.assertEqual(hk.from_qt_code(hk.qt_code("Ctrl+Alt+Up")), "Ctrl+Alt+Up")
        self.assertIsNotNone(hk.usable("Shift+Z"))
        self.assertIsNone(hk.usable("F9"))
        with self.assertRaises(ValueError):
            hk.parse("Hyper+Q")

    def test_cinnamon_set_and_read_back(self):
        gs = FakeSettings({(CIN, "custom-list"): "['custom0']", (item(0), "name"): "'Terminal'",
                           (item(0), "command"): "'xterm'", (item(0), "binding"): "['<Primary><Alt>t']",
                           (CIN + ".wm", "x"): "['<Super>x']"})
        gs.v[(CIN, "expo")] = "@as []"
        hk.install("cinnamon", gs, cmd="/x/lenslate")
        self.assertEqual(hk.current("cinnamon", gs), hk.DEFAULTS)
        bad = hk.conflicts("cinnamon", {"select": "Ctrl+Alt+T", "now": "Ctrl+Alt+C"}, gs)
        self.assertIn("Terminal", bad["select"])                    # someone else's key
        self.assertIn("auto refresh", bad["now"])                   # lenslate's own "auto" keeps Ctrl+Alt+C
        with self.assertRaises(RuntimeError):
            hk.apply("cinnamon", {"select": "Ctrl+Alt+T"}, gs, cmd="/x/lenslate")
        self.assertEqual(hk.current("cinnamon", gs)["select"], "Ctrl+Alt+Z")   # nothing changed
        hk.apply("cinnamon", {"select": "Super+F9", "toggle": ""}, gs, cmd="/x/lenslate")
        now = hk.current("cinnamon", gs)
        self.assertEqual((now["select"], now["now"], now["toggle"]), ("Super+F9", "Ctrl+Alt+X", None))
        self.assertIn("'xterm'", gs.v.values())                    # the user's own shortcut is untouched

    def test_kde_through_a_fake_bus(self):
        keys = {"net.local.lenslate-select.desktop": [hk.qt_code("Ctrl+Alt+Z")]}
        owners = {hk.qt_code("Meta+E"): [("org.kde.dolphin.desktop", "Dolphin: Dolphin")]}

        def bus(method, *args):
            if method == "shortcut":
                got = keys.get(args[2], [])
                return ["ai", str(len(got))] + [str(c) for c in got]
            if method == "setForeignShortcut":
                keys[args[2]] = [int(c) for c in args[7:7 + int(args[6])]]
                return []
            if method == "owners":
                return owners.get(args[0], [])
            raise AssertionError(method)
        self.assertEqual(hk.current("kde", bus=bus)["select"], "Ctrl+Alt+Z")
        self.assertEqual(hk.conflicts("kde", {"auto": "Meta+E"}, bus=bus), {"auto": "Dolphin: Dolphin"})
        import tempfile
        old = hk.APPS
        hk.APPS = tempfile.mkdtemp()
        try:
            hk.apply("kde", {"now": "Ctrl+Alt+X"}, bus=bus, cmd="/x/lenslate")
        finally:
            hk.APPS = old
        self.assertEqual(hk.current("kde", bus=bus)["now"], "Ctrl+Alt+X")
