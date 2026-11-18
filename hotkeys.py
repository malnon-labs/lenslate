"""Global hotkeys for lenslate's four commands on every desktop (`lenslate hotkeys ...`).

KDE gets its hotkeys from the installer (shortcut files + kglobalshortcutsrc). Everywhere else a hotkey is a line
in the desktop's own settings that runs `lenslate select` and so on; this module prints those lines ready to paste,
and on Cinnamon and GNOME (which keep custom shortcuts in gsettings) it can write and remove them itself:

  lenslate hotkeys                 what to do on this desktop
  lenslate hotkeys DESKTOP         the same for another one: kde, gnome, cinnamon, xfce, mate, hyprland, sway, i3, niri
  lenslate hotkeys install         Cinnamon / GNOME: add the four shortcuts (keys that are free; never replaces one)
  lenslate hotkeys remove          Cinnamon / GNOME: take lenslate's shortcuts out again
  lenslate hotkeys set select=Ctrl+Alt+Z ...   KDE / Cinnamon / GNOME: change the keys (checked for clashes first;
                                   also the "Keyboard shortcuts" button in the settings window)

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
    key = {"PgUp": "Page_Up", "PgDown": "Page_Down", "Backspace": "BackSpace", "Space": "space"}.get(key, key)
    return "".join(names[m] for m in mods) + (key.lower() if len(key) == 1 else key)   # GTK: letters are lower case


def _same_key(a, b):
    def norm(k):
        k = k.replace("<Control>", "<Primary>").replace("<Ctrl>", "<Primary>").replace("<Mod4>", "<Super>")
        mods = sorted(m.lower() for m in k.replace(">", "> ").split() if m.startswith("<"))
        return "".join(mods), k.rsplit(">", 1)[-1].lower()
    return norm(a) == norm(b)


def _pairs(keys):
    """[(action, what, mods, key)] from a key set (mods, [key per action]) or a {action: "Ctrl+Alt+Z"} map."""
    if isinstance(keys, dict):
        out = []
        for a, what in ACTIONS:
            if keys.get(a):
                mods, key = parse(keys[a])
                out.append((a, what, mods, key))
        return out
    mods, names = keys
    return [(a, what, tuple(mods), k) for (a, what), k in zip(ACTIONS, names)]


def lines(desk, cmd=None, keys=None):
    """Ready-to-paste text for a desktop: [(heading, [line, ...])]. keys: a key set or a {action: combo} map."""
    cmd = cmd or command()
    pairs = _pairs(keys or KEY_SETS[0])
    if desk == "hyprland":
        return [("Add to ~/.config/hypr/hyprland.conf (applies when saved):",
                 ["bind = %s, %s, exec, %s %s    # %s" % (" ".join(x.upper() for x in mods), k, cmd, a, what)
                  for a, what, mods, k in pairs])]
    if desk in ("sway", "i3"):
        conf = "~/.config/sway/config (then: swaymsg reload)" if desk == "sway" else "~/.config/i3/config (then: i3-msg reload)"
        return [("Add to %s:" % conf,
                 ["bindsym %s+%s exec %s %s    # %s" % (
                     "+".join({"Ctrl": "Ctrl", "Alt": "Mod1", "Super": "Mod4", "Shift": "Shift"}[x] for x in mods),
                     k.lower() if len(k) == 1 else k, cmd, a, what) for a, what, mods, k in pairs])]
    if desk == "niri":
        return [("Add inside the  binds { ... }  block of ~/.config/niri/config.kdl (applies when saved):",
                 ['%s+%s { spawn "%s" "%s"; }    // %s' % ("+".join({"Super": "Mod"}.get(x, x) for x in mods), k, cmd, a,
                                                        what) for a, what, mods, k in pairs])]
    if desk == "xfce":
        return [("Run these (or use Settings > Keyboard > Application Shortcuts):",
                 ['xfconf-query -c xfce4-keyboard-shortcuts -n -t string -p "/commands/custom/%s" -s "%s %s"'
                  % (gtk_key(mods, k), cmd, a) for a, _what, mods, k in pairs])]
    if desk == "mate":
        out = []
        for i, (a, what, mods, k) in enumerate(pairs):
            p = "org.mate.control-center.keybinding:/org/mate/desktop/keybindings/lenslate%d/" % i
            out += ['gsettings set %s name "%s%s"' % (p, MARK, what), 'gsettings set %s action "%s %s"' % (p, cmd, a),
                    'gsettings set %s binding "%s"' % (p, gtk_key(mods, k))]
        return [("Run these (or use Control Centre > Keyboard Shortcuts > Add):", out)]
    rows = ["%-22s %s %s    (%s)" % (combo(mods, k), cmd, a, what) for a, what, mods, k in pairs]
    if desk in GS:
        return [("Run  lenslate hotkeys install  - or add them by hand in %s:" % GS[desk]["where"], rows)]
    if desk == "kde":
        return [("The installer adds these (System Settings > Keyboard > Shortcuts shows and changes them):", rows)]
    return [("Bind these commands to keys in your desktop's keyboard-shortcut settings (suggested keys shown):", rows)]


# ------------------------------------------------------------------------------------ key combinations
MODS = ("Ctrl", "Alt", "Shift", "Super")
_MOD_ALIASES = {"ctrl": "Ctrl", "control": "Ctrl", "primary": "Ctrl", "alt": "Alt", "mod1": "Alt", "shift": "Shift",
                "super": "Super", "meta": "Super", "win": "Super", "mod4": "Super", "logo": "Super"}
# Qt key codes (KDE's KGlobalAccel speaks them) for the keys a shortcut may end in
_QT_NAMED = {"Escape": 0x01000000, "Tab": 0x01000001, "Backspace": 0x01000003, "Return": 0x01000004,
             "Enter": 0x01000005, "Insert": 0x01000006, "Delete": 0x01000007, "Pause": 0x01000008, "Print": 0x01000009,
             "Home": 0x01000010, "End": 0x01000011, "Left": 0x01000012, "Up": 0x01000013, "Right": 0x01000014,
             "Down": 0x01000015, "PgUp": 0x01000016, "PgDown": 0x01000017, "Space": 0x20}
_QT_NAMED.update({"F%d" % n: 0x01000030 + n - 1 for n in range(1, 36)})
_KEY_ALIASES = {"pageup": "PgUp", "page_up": "PgUp", "prior": "PgUp", "pagedown": "PgDown", "page_down": "PgDown",
                "next": "PgDown", "esc": "Escape", "del": "Delete", "ins": "Insert", "space": "Space"}
_QT_MODS = {"Shift": 0x02000000, "Ctrl": 0x04000000, "Alt": 0x08000000, "Super": 0x10000000}


def parse(text):
    """"Ctrl+Alt+Z" / "<Primary><Alt>z" / "ctrl+alt+f9" -> (("Ctrl", "Alt"), "Z"). Raises ValueError."""
    t = (text or "").strip()
    if not t:
        raise ValueError("empty shortcut")
    if t.startswith("<"):
        parts = [p for p in t.replace(">", ">\x00").split("\x00") if p]
        mods_raw, key = [p.strip("<>") for p in parts[:-1]], parts[-1]
    else:
        bits = t.split("+")
        if t.endswith("++"):
            bits = bits[:-2] + ["+"]
        mods_raw, key = bits[:-1], bits[-1]
    mods = []
    for m in mods_raw:
        name = _MOD_ALIASES.get(m.strip().lower())
        if name is None:
            raise ValueError("unknown modifier %r in %r" % (m, text))
        if name not in mods:
            mods.append(name)
    key = key.strip()
    key = _KEY_ALIASES.get(key.lower(), key)
    named = {k.lower(): k for k in _QT_NAMED}
    if key.lower() in named:
        key = named[key.lower()]
    elif len(key) == 1:
        key = key.upper()
    else:
        raise ValueError("unknown key %r in %r" % (key, text))
    return tuple(m for m in MODS if m in mods), key


def combo(mods, key):
    return "+".join(list(mods) + [key])


def normal(text):
    """A shortcut in lenslate's spelling ("Ctrl+Alt+Z"), or raise ValueError."""
    return combo(*parse(text))


def usable(text):
    """Why a shortcut cannot be used as a global hotkey, or None. A lone letter or Shift+letter would fire while
    typing in the game; it needs Ctrl, Alt or Super (or an F-key)."""
    try:
        mods, key = parse(text)
    except ValueError as e:
        return str(e)
    if not (set(mods) & {"Ctrl", "Alt", "Super"}) and not key.startswith("F"):
        return "needs Ctrl, Alt or Super (a key alone would fire while you type)"
    return None


def qt_code(text):
    mods, key = parse(text)
    code = _QT_NAMED.get(key, ord(key) if len(key) == 1 else 0)
    for m in mods:
        code |= _QT_MODS[m]
    return code


def from_qt_code(code):
    mods = tuple(m for m in MODS if code & _QT_MODS[m])
    base = code & 0x01FFFFFF
    key = next((k for k, v in _QT_NAMED.items() if v == base), None) or (chr(base).upper() if 0x20 < base < 0x110000 else None)
    return combo(mods, key) if key else None


DEFAULTS = {a: combo(KEY_SETS[0][0], k) for (a, _w), k in zip(ACTIONS, KEYS)}


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


# ------------------------------------------------------------------------ changing the keys (settings window)
KDE_FILES = {a: ["net.local.lenslate-%s.desktop" % a] for a, _w in ACTIONS}
KDE_FILES["toggle"].append("net.local.lenslate-clear.desktop")    # its name before 0.1.0
APPS = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "applications")


def writable(desk):
    """Can lenslate change the keys on this desktop itself? (Otherwise it shows lines to paste.)"""
    if desk == "kde":
        return bool(shutil.which("busctl")) and _kde_up()
    return desk in GS and bool(shutil.which("gsettings"))


def _bus(*args):
    r = subprocess.run(["busctl", "--user", "call", "org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel"]
                       + [str(a) for a in args], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "KGlobalAccel did not answer")
    return r.stdout.split()


def _kde_up():
    try:
        _bus("isGlobalShortcutAvailable", "is", 0, "")
        return True
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return False


def _kde_file(action):
    """The shortcut file KDE knows this action by (an older install may use the old name), or the new name."""
    for f in KDE_FILES[action]:
        if os.path.exists(os.path.join(APPS, f)):
            return f
    return KDE_FILES[action][0]


def _kde_get(f, bus=_bus):
    out = bus("shortcut", "as", 4, f, "_launch", "", "")      # "ai N code..."
    codes = [int(x) for x in out[2:]] if len(out) > 2 else []
    return from_qt_code(codes[0]) if codes else None


def current(desk, gs=_gs, bus=_bus):
    """{action: "Ctrl+Alt+Z" or None} as the desktop has them now, or None when lenslate cannot read them here."""
    if desk == "kde":
        try:
            return {a: _kde_get(_kde_file(a), bus) for a, _w in ACTIONS}
        except (RuntimeError, OSError, subprocess.SubprocessError, ValueError):
            return None
    if desk not in GS:
        return None
    spec, out = GS[desk], {a: None for a, _w in ACTIONS}
    try:
        for ident in _ours(spec, gs):
            cmd = str(_parse(gs("get", _item(spec, ident), "command")))
            action = cmd.rsplit(" ", 1)[-1]
            b = _parse(gs("get", _item(spec, ident), "binding"))
            b = b[0] if isinstance(b, list) and b else b
            if action in out and isinstance(b, str) and b:
                try:
                    out[action] = normal(b)
                except ValueError:
                    pass
    except RuntimeError:
        return None
    return out


def conflicts(desk, keys, gs=_gs, bus=_bus):
    """{action: what already uses its key} for keys used by something other than lenslate (and keys given to two
    of lenslate's actions at once)."""
    out, seen = {}, {}
    for a, k in (current(desk, gs, bus) or {}).items():   # lenslate's other keys, kept as they are
        if k and a not in keys:
            seen.setdefault(k, a)
    for a, k in keys.items():
        if not k:
            continue
        why = usable(k)
        if why:
            out[a] = why
            continue
        n = normal(k)
        if n in seen:
            out[a] = "also given to \"%s\"" % dict(ACTIONS)[seen[n]]
        seen.setdefault(n, a)
    if desk == "kde":
        ours = {f for fs in KDE_FILES.values() for f in fs}
        for a, k in keys.items():
            if not k or a in out:
                continue
            try:
                rows = _kde_owners(qt_code(k), bus)
            except (RuntimeError, OSError, subprocess.SubprocessError):
                continue
            other = [r for r in rows if r[0] not in ours]
            if other:
                out[a] = other[0][1]
    elif desk in GS:
        spec = GS[desk]
        try:
            vals = [_parse(gs("get", _item(spec, i), "binding")) for i in _ours(spec, gs)]
            mine = {m for v in vals for m in (v if isinstance(v, list) else [v])}
            used = {u: w for u, w in taken_keys(spec, gs).items() if u not in mine}
        except RuntimeError:
            used = {}
        for a, k in keys.items():
            if not k or a in out:
                continue
            hit = next((w for u, w in used.items() if _same_key(gtk_key(*parse(k)), u)), None)
            if hit:
                out[a] = hit
    return out


def _kde_owners(code, bus=_bus):
    """[(component, "Friendly component: friendly action")] of KDE shortcuts on a key code."""
    r = subprocess.run(["busctl", "--user", "--json=short", "call", "org.kde.kglobalaccel", "/kglobalaccel",
                        "org.kde.KGlobalAccel", "getGlobalShortcutsByKey", "i", str(code)],
                       capture_output=True, text=True, timeout=10) if bus is _bus else None
    if r is None:
        return bus("owners", code)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    import json
    data = json.loads(r.stdout).get("data", [[]])[0]
    # each: [componentUnique, componentFriendly?, ...] - KGlobalShortcutInfo: (uniqueName, friendlyName,
    # componentUniqueName, componentFriendlyName, contextUniqueName, contextFriendlyName, keys, defaultKeys)
    return [(row[2], "%s: %s" % (row[3] or row[2], row[1] or row[0])) for row in data]


def _kde_desktop_file(action, f, cmd, real=True):
    path = os.path.join(APPS, f)
    if os.path.exists(path):
        return
    os.makedirs(APPS, exist_ok=True)
    with open(path, "w") as fh:
        fh.write("[Desktop Entry]\nExec=%s %s\nName=%s%s\nNoDisplay=true\nStartupNotify=false\nType=Application\n"
                 "X-KDE-GlobalAccel-CommandShortcut=true\n" % (cmd, action, MARK, dict(ACTIONS)[action]))
    if real and shutil.which("kbuildsycoca6"):
        subprocess.run(["kbuildsycoca6"], capture_output=True, timeout=60)


def apply(desk, keys, gs=_gs, bus=_bus, cmd=None):
    """Set lenslate's keys on the desktop: keys = {action: "Ctrl+Alt+Z" or "" (no key)}. Checks first; nothing is
    changed when a key is unusable or taken (RuntimeError says which). Returns a short report."""
    bad = conflicts(desk, keys, gs, bus)
    if bad:
        raise RuntimeError("; ".join("%s: %s is %s" % (dict(ACTIONS)[a], keys[a], w if w.startswith(("needs", "also", "unknown", "empty"))
                                                       else "already used by " + w) for a, w in bad.items()))
    cmd = cmd or command()
    if desk == "kde":
        for a, _w in ACTIONS:
            if a not in keys:
                continue
            f = _kde_file(a)
            _kde_desktop_file(a, f, cmd, real=bus is _bus)
            codes = [qt_code(keys[a])] if keys[a] else []
            bus("setForeignShortcut", "asai", 4, f, "_launch", "", "", len(codes), *codes)
            if bus is _bus and shutil.which("kwriteconfig6"):   # (KGlobalAccel saves it too; this keeps the file in step)
                subprocess.run(["kwriteconfig6", "--file", "kglobalshortcutsrc", "--group", "services", "--group", f,
                                "--key", "_launch", normal(keys[a]) if keys[a] else "none"], capture_output=True,
                               timeout=10)
        got = current(desk, gs, bus) or {}
        wrong = [a for a in keys if keys[a] and got.get(a) != normal(keys[a])]
        if wrong:
            raise RuntimeError("KDE did not take the new key for: %s" % ", ".join(dict(ACTIONS)[a] for a in wrong))
        return "saved in KDE's shortcuts"
    if desk not in GS:
        raise RuntimeError("lenslate cannot change shortcuts on %s itself" % NAMES.get(desk, desk))
    spec = GS[desk]
    check_store(spec, gs)
    have = current(desk, gs) or {}
    want = {a: (normal(keys[a]) if keys.get(a) else None) if a in keys else have.get(a) for a, _w in ACTIONS}
    remove(desk, gs)
    ids = custom_ids(spec, gs)
    for a, what in ACTIONS:
        if not want[a]:
            continue
        if spec["ids"]:
            n = 0
            while "custom%d" % n in ids:
                n += 1
            ident = "custom%d" % n
        else:
            ident = spec["path"] % ("lenslate-" + a)
        item = _item(spec, ident)
        binding = gtk_key(*parse(want[a]))
        gs("set", item, "name", MARK + what)
        gs("set", item, "command", "%s %s" % (cmd, a))
        gs("set", item, "binding", "['%s']" % binding if spec["array"] else binding)
        ids.append(ident)
    gs("set", spec["schema"], spec["list"], str(ids))
    return "saved in %s" % spec["where"]


def cli(args):
    desk = desktop()
    if args and args[0] == "set":
        # lenslate hotkeys set select=Ctrl+Alt+Z now=Ctrl+Alt+X ...  (an empty value removes that key)
        keys = {}
        for a in args[1:]:
            name, _, key = a.partition("=")
            if name not in dict(ACTIONS):
                print("unknown command %r; one of: %s" % (name, ", ".join(x for x, _w in ACTIONS)))
                return 1
            keys[name] = key
        if not keys:
            print("usage: lenslate hotkeys set select=Ctrl+Alt+Z now=Ctrl+Alt+X auto=Ctrl+Alt+C toggle=Ctrl+Alt+V")
            return 1
        if not writable(desk):
            print("lenslate cannot change shortcuts on %s itself; add these by hand:\n" % NAMES[desk])
            for head, body in lines(desk, keys=dict(current(desk) or DEFAULTS, **{k: v for k, v in keys.items() if v})):
                print(head)
                for ln in body:
                    print("  " + ln)
            return 1
        try:
            print(apply(desk, keys))
        except (RuntimeError, ValueError) as e:
            print("nothing changed: %s" % e)
            return 1
        return 0
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
