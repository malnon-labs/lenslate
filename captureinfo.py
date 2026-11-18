"""Which screen-capture method lenslate uses on this desktop, and what the user should know about it.

One place for the choice (lenslate.py asks platform()) and for the guidance texts: the settings window (Overlay
page), `lenslate capture`, the notification before the desktop's share dialog, and docs/CAPTURE.md all say the same.
"""
import os

import config as cfgmod


def platform():
    """"x11", "portal" or "kwin". LENSLATE_PLATFORM=x11|wayland forces the session type for a test;
    [capture] backend = "portal" forces the portal on KDE."""
    forced = os.environ.get("LENSLATE_PLATFORM")
    if forced == "x11" or (forced != "wayland" and not os.environ.get("WAYLAND_DISPLAY")
                           and bool(os.environ.get("DISPLAY"))):
        return "x11"
    if cfgmod.get("capture.backend") == "portal" or "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", "KDE").upper():
        return "portal"
    return "kwin"


PORTAL_CHOICE = ("Game fills the screen (fullscreen or borderless)? Share the game WINDOW: the cards stay up and "
                 "automatic translation works. Game in a smaller window? Share the whole SCREEN: a shared window "
                 "that is smaller than the screen puts the cards in the wrong place.")

GUIDES = {
    "kwin": {
        "title": "KDE window capture",
        "summary": "lenslate reads the game window directly through KDE (about 20 ms, also when the window is "
                   "not focused; the cards are never in the picture).",
        "tips": [
            "Any window size works: windowed, borderless or fullscreen.",
            "Click the game once after picking the area, so lenslate knows which window the area belongs to.",
            "If lenslate was not installed with install.sh (no capture permission), it falls back to Spectacle: "
            "only the focused window is read and automatic translation pauses when you click elsewhere.",
        ],
    },
    "x11": {
        "title": "X11 window capture",
        "summary": "lenslate reads the focused window through the X server (its own picture: the cards are never "
                   "in it, and other windows on top do not matter).",
        "tips": [
            "Any window size works: windowed, borderless or fullscreen.",
            "Click the game once after picking the area, so lenslate knows which window the area belongs to.",
            "Without a compositor (some lightweight desktops) the cards are solid instead of see-through.",
            "A minimised game cannot be read.",
        ],
    },
    "portal": {
        "title": "Screen sharing (desktop portal)",
        "summary": "Your desktop asks once which window or screen lenslate may see, and remembers the answer. "
                   "The desktop does not tell lenslate WHERE a shared window is, so what you share matters:",
        "tips": [
            PORTAL_CHOICE,
            "Shared screen: the cards switch off for a moment whenever lenslate reads (they would be read "
            "otherwise), and automatic translation is not offered - press the Translate now hotkey when the "
            "text changes.",
            "Several monitors: share the monitor the game is on, and pick the area on that monitor.",
            "Picked the wrong thing, or changed how the game is shown? Choose again: the button here, or "
            "`lenslate share`.",
            "Needs a desktop with layer-shell for the cards (Hyprland, Sway, niri, KDE). GNOME has none: the "
            "cards cannot be shown there yet.",
        ],
    },
}


def guide(method=None):
    return GUIDES[method or platform()]


def text(method=None):
    """The guide as plain text (command line)."""
    g = guide(method)
    return "%s\n%s\n%s" % (g["title"], g["summary"], "\n".join("- " + t for t in g["tips"]))


if __name__ == "__main__":
    print(text())
