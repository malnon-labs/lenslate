#!/usr/bin/env python3
"""Screenshot of one window on KDE Wayland through KWin (the same call lenslate's overlay uses), for live tests.

Run it with lenslate's private interpreter, the only one KWin lets capture windows:
  ~/.local/libexec/lenslate/lenslate-python tests/scripts/game_live/shot.py CLASS_OR_TITLE OUT.png [MAX_WIDTH]
  ~/.local/libexec/lenslate/lenslate-python tests/scripts/game_live/shot.py --list

CLASS_OR_TITLE: part of the window class or title, any case ("risk of rain"). The overlay's cards are never in the
picture (they are a separate surface): to see the cards, use Spectacle (`spectacle -b -n -f -o out.png`), and never
while lenslate itself is capturing with Spectacle. MAX_WIDTH shrinks the saved picture (smaller files to look at).
Prints: window id, class, title, geometry.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, HERE)


def windows():
    out = []
    ids = subprocess.run(["kdotool", "search", "--class", "."], capture_output=True, text=True, timeout=5).stdout.split()
    for w in ids:
        def ask(what):
            return subprocess.run(["kdotool", what, w], capture_output=True, text=True, timeout=5).stdout.strip()
        out.append((w, ask("getwindowclassname"), ask("getwindowname")))
    return out


def find(pattern):
    p = pattern.lower()
    hits = [w for w in windows() if p in w[1].lower() or p in w[2].lower()]
    return hits[0] if hits else None


def main(argv):
    if argv[:1] == ["--list"] or not argv:
        for w in windows():
            print("%s  %-28s %s" % w)
        return 0
    hit = find(argv[0])
    if hit is None:
        print("no window matches %r" % argv[0])
        return 1
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])   # noqa: F841
    import lenslate as ls
    t = ls.window_target(hit[0])
    img = ls.kwin_capture_window(hit[0])
    if len(argv) > 2 and img.width() > int(argv[2]):
        img = img.scaledToWidth(int(argv[2]), Qt.SmoothTransformation)
    img.save(argv[1])
    print("%s  %s | %s  geometry %s  saved %dx%d" % (hit[0], hit[1], hit[2], t.rect.getRect() if t else None,
                                                     img.width(), img.height()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
