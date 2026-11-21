"""The app menu entry for the AppImage (install.sh writes its own entry for an installed lenslate).

The AppImage puts nothing in the app menu by itself; the setup window offers it (ticked) and the Advanced page has
Add / Remove. The entry starts the AppImage file where it is now: moving the file needs Add again. An entry that
install.sh wrote is never touched (it has no MARK line).
"""
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = "X-lenslate-AppImage=true"


def apps_dir():
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "applications")


def icon_path():
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                        "icons", "hicolor", "scalable", "apps", "lenslate.svg")


def entry_path():
    return os.path.join(apps_dir(), "lenslate.desktop")


def appimage():
    """The AppImage lenslate runs from, or None (an installed lenslate, or a git checkout)."""
    path = os.environ.get("LENSLATE_APPIMAGE")
    return path if path and os.path.exists(path) else None


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def state():
    """'ours' (an entry for an AppImage), 'installed' (install.sh's entry) or None (no entry)."""
    text = _read(entry_path())
    if text is None:
        return None
    return "ours" if MARK in text else "installed"


def _quote(path):
    """A path for the Exec line (desktop entry spec: quoted, with \\ " ` $ escaped)."""
    return '"%s"' % "".join("\\" + c if c in '\\"`$' else c for c in path)


def install(path=None):
    """Write the menu entry for the AppImage at `path` (default: the one running). Returns the entry's path."""
    path = path or appimage()
    if not path:
        raise RuntimeError("lenslate is not running from an AppImage")
    if state() == "installed":
        raise RuntimeError("lenslate's installer already made an app menu entry")
    os.makedirs(apps_dir(), exist_ok=True)
    os.makedirs(os.path.dirname(icon_path()), exist_ok=True)
    shutil.copyfile(os.path.join(HERE, "packaging", "lenslate.svg"), icon_path())
    with open(entry_path(), "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\nType=Application\nName=lenslate\nGenericName=Screen and game translator\n"
                "Comment=Translate text on screen and in games with local models\nExec=%s gui\nIcon=lenslate\n"
                "Categories=Utility;Game;\nKeywords=translate;ocr;overlay;japanese;chinese;game;\n"
                "StartupWMClass=lenslate\n%s\n" % (_quote(path), MARK))
    _refresh()
    return entry_path()


def remove():
    """Remove the AppImage's entry (and its icon). install.sh's entry is left alone. True if something was removed."""
    if state() != "ours":
        return False
    os.remove(entry_path())
    try:
        os.remove(icon_path())
    except OSError:
        pass
    _refresh()
    return True


def _refresh():
    """Most menus see the change by themselves; update-desktop-database helps the ones that cache."""
    if shutil.which("update-desktop-database"):
        try:
            subprocess.run(["update-desktop-database", apps_dir()], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
