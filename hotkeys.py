"""Global hotkeys for lenslate's four commands on every desktop (`lenslate hotkeys ...`).

KDE gets its hotkeys from the installer (shortcut files + kglobalshortcutsrc). Everywhere else a hotkey is a line
in the desktop's own settings that runs `lenslate select` and so on; this module prints those lines ready to paste,
and on Cinnamon and GNOME (which keep custom shortcuts in gsettings) it can write and remove them itself:

  lenslate hotkeys                 what to do on this desktop
  lenslate hotkeys DESKTOP         the same for another one: kde, gnome, cinnamon, xfce, mate, hyprland, sway, i3, niri
  lenslate hotkeys install         Cinnamon / GNOME: add the four shortcuts (keys that are free; never replaces one)
  lenslate hotkeys remove          Cinnamon / GNOME: take lenslate's shortcuts out again

Tried on a real desktop: KDE Plasma 6 only (the installer's shortcuts). The Cinnamon and GNOME writer was run
against those desktops' real settings schemas in a container (tests/scripts/hotkeys_containers.sh, 2026-11-12:
install, install again, remove; taken keys detected) - not yet with the desktop itself reacting to the keys.
The paste-ready lines for the other desktops follow their documented formats and have not been run there.
"""
import ast
import os
import shutil
import subprocess

ACTIONS = [("select", "pick the area to translate"),
           ("now", "translate the area again"),
           ("auto", "auto refresh on / off"),
           ("toggle", "hide / show the translations")]
KEYS = ["Z", "X", "C", "V"]                       # same order as ACTIONS: the keys the KDE installer uses
# Key sets tried in order (modifiers, keys). The first one whose four keys are all free is used. Ctrl+Alt+Z/X/C/V
# are free in the default shortcuts of KDE, GNOME, Cinnamon, Xfce, MATE, Hyprland, Sway, niri and i3 (checked
# 2026-11-18 against each desktop's own default files), sit under the left hand, and exist on every laptop.
# Ctrl+Alt+arrows (the keys before 0.1.0) switch workspaces on GNOME, Cinnamon, MATE and Xfce.
KEY_SETS = [(("Ctrl", "Alt"), KEYS), (("Ctrl", "Alt", "Shift"), ["F9", "F10", "F11", "F12"])]
MARK = "lenslate: "                                 # every shortcut lenslate writes has a name starting with this

GS = {  # desktops whose custom shortcuts are a gsettings list
    "cinnamon": {"schema": "org.cinnamon.desktop.keybindings", "list": "custom-list",
                 "item": "org.cinnamon.desktop.keybindings.custom-keybinding",
                 "path": "/org/cinnamon/desktop/keybindings/custom-keybindings/%s/", "ids": True, "array": True,
                 # the built-in shortcuts live in separate schemas (found with the real schemas in a container:
                 # Ctrl+Alt+arrows switch workspaces in ...keybindings.wm)
                 "scan": ["org.cinnamon.desktop.keybindings", "org.cinnamon.desktop.keybindings.wm",
                          "org.cinnamon.desktop.keybindings.media-keys", "org.cinnamon.muffin.keybindings",
                          "org.cinnamon.muffin.wayland.keybindings", "org.cinnamon.runtime-keybindings"],
                 "where": "System Settings > Keyboard > Shortcuts > Custom Shortcuts"},
    "gnome": {"schema": "org.gnome.settings-daemon.plugins.media-keys", "list": "custom-keybindings",
              "item": "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding",
              "path": "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/%s/", "ids": False,
              "array": False,
              "scan": ["org.gnome.desktop.wm.keybindings", "org.gnome.shell.keybindings", "org.gnome.mutter.keybindings",
                       "org.gnome.mutter.wayland.keybindings", "org.gnome.settings-daemon.plugins.media-keys"],
              "where": "Settings > Keyboard > View and Customise Shortcuts > Custom Shortcuts"},
}
NAMES = {"kde": "KDE Plasma", "gnome": "GNOME", "cinnamon": "Cinnamon", "xfce": "Xfce", "mate": "MATE",
         "hyprland": "Hyprland", "sway": "Sway", "i3": "i3", "niri": "niri", "other": "this desktop"}


def desktop(env=None):
    env = os.environ if env is None else env
    cur = env.get("XDG_CURRENT_DESKTOP", "").lower()
    for key, name in (("kde", "kde"), ("cinnamon", "cinnamon"), ("gnome", "gnome"), ("xfce", "xfce"), ("mate", "mate"),
                      ("hyprland", "hyprland"), ("sway", "sway"), ("niri", "niri"), ("i3", "i3")):
        if key in cur:
            return name
    if env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland"
    if env.get("NIRI_SOCKET"):
        return "niri"
    if env.get("SWAYSOCK"):
        return "sway"
    if env.get("I3SOCK"):
        return "i3"
    return "other"


def command():
    """The lenslate command as a desktop should run it (full path: a desktop's shortcut runner may not have
    ~/.local/bin in its PATH)."""
    return shutil.which("lenslate") or os.path.expanduser("~/.local/bin/lenslate")


def gtk_key(mods, key):
    """('Ctrl', 'Alt'), 'Up' -> '<Primary><Alt>Up' (the GTK spelling Cinnamon, GNOME, Xfce and MATE use)."""
    names = {"Ctrl": "<Primary>", "Alt": "<Alt>", "Super": "<Super>", "Shift": "<Shift>"}
    return "".join(names[m] for m in mods) + (key.lower() if len(key) == 1 else key)   # GTK: letters are lower case


def _same_key(a, b):
    def norm(k):
        k = k.replace("<Control>", "<Primary>").replace("<Ctrl>", "<Primary>").replace("<Mod4>", "<Super>")
        mods = sorted(m.lower() for m in k.replace(">", "> ").split() if m.startswith("<"))
        return "".join(mods), k.rsplit(">", 1)[-1].lower()
    return norm(a) == norm(b)


def lines(desk, cmd=None, keys=None):
    """Ready-to-paste text for a desktop: [(heading, [line, ...])]."""
    cmd = cmd or command()
    mods, names = keys or KEY_SETS[0]
    plus = "+".join(mods)
    pairs = list(zip(ACTIONS, names))
    if desk == "hyprland":
        m = " ".join(x.upper().replace("CTRL", "CTRL") for x in mods)
        return [("Add to ~/.config/hypr/hyprland.conf (applies when saved):",
                 ["bind = %s, %s, exec, %s %s    # %s" % (m, k, cmd, a, what) for (a, what), k in pairs])]
    if desk in ("sway", "i3"):
        sm = "+".join({"Ctrl": "Ctrl", "Alt": "Mod1", "Super": "Mod4", "Shift": "Shift"}[x] for x in mods)
        conf = "~/.config/sway/config (then: swaymsg reload)" if desk == "sway" else "~/.config/i3/config (then: i3-msg reload)"
        return [("Add to %s:" % conf,
                 ["bindsym %s+%s exec %s %s    # %s" % (sm, k.lower() if len(k) == 1 else k, cmd, a, what)
                  for (a, what), k in pairs])]
    if desk == "niri":
        nm = "+".join({"Super": "Mod"}.get(x, x) for x in mods)
        return [("Add inside the  binds { ... }  block of ~/.config/niri/config.kdl (applies when saved):",
                 ['%s+%s { spawn "%s" "%s"; }    // %s' % (nm, k, cmd, a, what) for (a, what), k in pairs])]
    if desk == "xfce":
        return [("Run these (or use Settings > Keyboard > Application Shortcuts):",
                 ['xfconf-query -c xfce4-keyboard-shortcuts -n -t string -p "/commands/custom/%s" -s "%s %s"'
                  % (gtk_key(mods, k), cmd, a) for (a, _what), k in pairs])]
    if desk == "mate":
        out = []
        for i, ((a, what), k) in enumerate(pairs):
            p = "org.mate.control-center.keybinding:/org/mate/desktop/keybindings/lenslate%d/" % i
            out += ['gsettings set %s name "%s%s"' % (p, MARK, what), 'gsettings set %s action "%s %s"' % (p, cmd, a),
                    'gsettings set %s binding "%s"' % (p, gtk_key(mods, k))]
        return [("Run these (or use Control Centre > Keyboard Shortcuts > Add):", out)]
    if desk in GS:
        return [("Run  lenslate hotkeys install  - or add them by hand in %s:" % GS[desk]["where"],
                 ["%-22s %s %s    (%s)" % (plus + "+" + k, cmd, a, what) for (a, what), k in pairs])]
    if desk == "kde":
        return [("The installer adds these (System Settings > Keyboard > Shortcuts shows and changes them):",
                 ["%-22s %s %s    (%s)" % (plus + "+" + k, cmd, a, what) for (a, what), k in pairs])]
    return [("Bind these commands to keys in your desktop's keyboard-shortcut settings (suggested keys shown):",
             ["%-22s %s %s    (%s)" % (plus + "+" + k, cmd, a, what) for (a, what), k in pairs])]


# ------------------------------------------------------------------------------------ gsettings desktops
def _gs(*args):
    r = subprocess.run(["gsettings"] + list(args), capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "gsettings failed")
    return r.stdout.strip()


def _parse(text):
    """A gsettings value ("['a', 'b']", "@as []", "'x'") as Python."""
    text = text.strip()
    if text.startswith("@"):
        text = text.split(" ", 1)[1]
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def taken_keys(spec, gs=_gs):
    """{key spelling: what uses it} for every shortcut the desktop has now (its own and custom ones)."""
    used = {}
    for schema in spec["scan"]:
        try:
            out = gs("list-recursively", schema)
        except RuntimeError:
            continue
        for row in out.splitlines():
            parts = row.split(" ", 2)
            if len(parts) < 3:
                continue
            val = _parse(parts[2])
            for k in ([val] if isinstance(val, str) else val if isinstance(val, list) else []):
                if isinstance(k, str) and k and k != "disabled" and ("<" in k or len(k) > 1):
                    used[k] = parts[1]
    for ident in custom_ids(spec, gs):
        try:
            name = _parse(gs("get", _item(spec, ident), "name"))
            b = _parse(gs("get", _item(spec, ident), "binding"))
        except RuntimeError:
            continue
        for k in ([b] if isinstance(b, str) else b):
            if k:
                used[k] = "custom shortcut \"%s\"" % name
    return used


def custom_ids(spec, gs=_gs):
    return list(_parse(gs("get", spec["schema"], spec["list"])) or [])


def _item(spec, ident):
    return "%s:%s" % (spec["item"], spec["path"] % ident if spec["ids"] else ident)


def _ours(spec, gs=_gs):
    out = []
    for ident in custom_ids(spec, gs):
        try:
            if str(_parse(gs("get", _item(spec, ident), "name"))).startswith(MARK):
                out.append(ident)
        except RuntimeError:
            continue
    return out


def choose_keys(used):
    """The first key set with all four keys free, or None."""
    for mods, names in KEY_SETS:
        if not any(_same_key(gtk_key(mods, k), u) for k in names for u in used):
            return mods, names
    return None


def check_store(spec, gs=_gs):
    """Write a value under a path only lenslate uses and read it back; raise if it does not come back.
    gsettings writes through the desktop's settings service but reads the database file itself, from
    $XDG_CONFIG_HOME/dconf: with a different XDG_CONFIG_HOME than the desktop's (a test set-up, a sandbox) it reads an
    empty database, sees no shortcuts, and would write over the user's own (seen 2026-11-13 on Cinnamon)."""
    probe = "%s:%s" % (spec["item"], spec["path"] % "lenslate-probe")
    token = "%sprobe %d" % (MARK, os.getpid())
    try:
        gs("set", probe, "name", token)
        back = _parse(gs("get", probe, "name"))
    finally:
        try:
            gs("reset", probe, "name")
        except RuntimeError:
            pass
    if back != token:
        raise RuntimeError("the shortcut settings read back differently from what was written (is XDG_CONFIG_HOME "
                           "different from the desktop's?); nothing was changed")


def install(desk, gs=_gs, cmd=None):
    """Add lenslate's four shortcuts. Returns the text to print. Existing shortcuts are never changed: keys in use
    are skipped in favour of the next free set, and lenslate's own earlier entries are replaced."""
    spec = GS[desk]
    cmd = cmd or command()
    check_store(spec, gs)
    remove(desk, gs)
    used = taken_keys(spec, gs)
    keys = choose_keys(used)
    if keys is None:
        return ("Every key set lenslate knows is already in use here. Add the four commands by hand in %s:\n  %s"
                % (spec["where"], "\n  ".join("%s %s" % (cmd, a) for a, _w in ACTIONS)))
    mods, names = keys
    ids = custom_ids(spec, gs)
    out = []
    if keys != KEY_SETS[0]:
        first = [gtk_key(KEY_SETS[0][0], k) for k in KEY_SETS[0][1]]
        busy = sorted({"%s (%s)" % (k, w) for k in first for u, w in used.items() if _same_key(k, u)})
        out.append("Ctrl+Alt+Z/X/C/V are partly taken on this desktop: %s. Using %s instead."
                   % ("; ".join(busy), "+".join(mods) + "+" + "/".join(names)))
    for (action, what), key in zip(ACTIONS, names):
        if spec["ids"]:
            n = 0
            while "custom%d" % n in ids:
                n += 1
            ident = "custom%d" % n
        else:
            ident = spec["path"] % ("lenslate-" + action)
        item = _item(spec, ident)
        binding = gtk_key(mods, key)
        gs("set", item, "name", MARK + what)
        gs("set", item, "command", "%s %s" % (cmd, action))
        gs("set", item, "binding", "['%s']" % binding if spec["array"] else binding)
        ids.append(ident)
        out.append("  %-22s %s %s" % ("+".join(mods) + "+" + key, cmd, action))
    gs("set", spec["schema"], spec["list"], str(ids))
    out.append("Change or remove them in %s, or with: lenslate hotkeys remove" % spec["where"])
    return "\n".join(out)


def remove(desk, gs=_gs):
    spec = GS[desk]
    check_store(spec, gs)
    mine = _ours(spec, gs)
    if not mine:
        return 0
    for ident in mine:
        for key in ("name", "command", "binding"):
            try:
                gs("reset", _item(spec, ident), key)
            except RuntimeError:
                pass
    gs("set", spec["schema"], spec["list"], str([i for i in custom_ids(spec, gs) if i not in mine]))
    return len(mine)


def cli(args):
    desk = desktop()
    if args and args[0] in ("install", "remove"):
        if desk not in GS:
            print("lenslate writes shortcuts itself only on Cinnamon and GNOME%s. Here:\n"
                  % (" (on KDE the installer does it)" if desk == "kde" else ""))
            return cli([])
        if not shutil.which("gsettings"):
            print("gsettings was not found; add the shortcuts by hand:\n")
            return cli([desk])
        try:
            if args[0] == "install":
                print("lenslate shortcuts on %s:" % NAMES[desk])
                print(install(desk))
            else:
                print("%d lenslate shortcuts removed" % remove(desk))
        except RuntimeError as e:
            print("could not change the shortcuts (%s); add them by hand:\n" % e)
            return cli([desk]) or 1
        return 0
    if args:
        if args[0].lower() not in NAMES:
            print("unknown desktop %r; one of: %s" % (args[0], ", ".join(k for k in NAMES if k != "other")))
            return 1
        desk = args[0].lower()
    print("Hotkeys for lenslate on %s" % NAMES[desk])
    for head, body in lines(desk):
        print("\n" + head)
        for ln in body:
            print("  " + ln)
    if desk in ("cinnamon", "gnome") and not args:
        print("\n`lenslate hotkeys install` checks that these keys are free here and picks others if not.")
    return 0
