# How lenslate sees the screen: which method, where, and what to do

lenslate needs a picture of the text to read. How it gets one depends on your desktop; `lenslate capture` prints
the method in use and its advice, and the settings window shows the same on the Overlay page ("How lenslate sees
the screen"). The texts there and here come from `captureinfo.py`.

| Your desktop | Method | Game window size | Automatic translation | Cards during a read |
| --- | --- | --- | --- | --- |
| KDE Plasma 6, Wayland | KDE window capture | any | yes, also when the game is not focused | stay up |
| Any X11 session (Cinnamon, Xfce, MATE, KDE on X11 ...) | X11 window capture | any | yes | stay up |
| Hyprland, Sway, niri, other Wayland with layer-shell | Screen sharing (portal), shared **window** | must fill the screen | yes | stay up |
| same | Screen sharing (portal), shared **screen** | any | no (press Translate now) | blink off for a moment |
| GNOME (Wayland) | not usable yet | - | - | no layer-shell: the cards cannot be shown |

## KDE Plasma (Wayland)
Nothing to choose. lenslate reads the game window directly through KDE (about 20 ms, also when the window is not
focused; the cards are never in the picture).
- Any window size works: windowed, borderless or fullscreen.
- Click the game once after picking the area, so lenslate knows which window the area belongs to.
- This needs the capture permission install.sh sets up (README, "Platforms"). Without it lenslate falls back to
  Spectacle: only the focused window is read and automatic translation pauses when you click elsewhere.

## X11 sessions
Nothing to choose. lenslate reads the focused window through the X server (its own picture: the cards are never in
it, and other windows on top do not matter).
- Any window size works.
- Click the game once after picking the area.
- Without a compositor (some lightweight desktops) the cards are solid instead of see-through.
- A minimised game cannot be read.
- Hotkeys: the installer only sets them up on KDE. Elsewhere `lenslate hotkeys` prints what to put where for
  your desktop (and `lenslate hotkeys install` writes the shortcuts on Cinnamon and GNOME).

## Screen sharing (desktop portal): Hyprland, Sway, niri, or `[capture] backend = "portal"`
The first time, your desktop shows its own "share a window or a screen" dialog. lenslate remembers the answer, so
the dialog does not come back. **What you pick there decides how well lenslate works**, because the desktop gives
lenslate the picture but never tells it *where* a shared window is on the screen:

- **The game fills the screen (fullscreen or borderless): share the game WINDOW.** This is the good case: the
  cards stay up, automatic translation works, nothing blinks.
- **The game is in a smaller window: share the whole SCREEN.** A shared window that is smaller than the screen puts
  the cards in the wrong place (lenslate has to assume the window fills the monitor). lenslate tells you when the
  shared window's shape does not match the monitor.
- With a shared screen the cards are part of the picture, so they switch off for a moment whenever lenslate reads,
  and automatic translation is not offered: press the Translate now hotkey when the text changes.
- Several monitors: share the monitor the game is on, and pick the area on that monitor.
- Changed your mind, or changed how the game is shown? `lenslate share` (or "Choose what to share…" on the Overlay
  page) asks again.
- Some desktops only offer whole screens in the dialog (Sway with xdg-desktop-portal-wlr): then the shared-screen
  rules apply.
- Needs: python3-gobject, GStreamer's PipeWire plugin, xdg-desktop-portal with your desktop's backend
  (install.sh installs them on these desktops).

Status: the portal path was built on KDE and tested up to the desktop's dialog and with a test picture; a real
shared window or screen, and Hyprland / Sway / niri themselves, have not been tried yet (docs/ROADMAP.md).

## Forcing a method
- `[capture] backend = "portal"` in config.toml (or Advanced > Screen capture method): use screen sharing on KDE too.
- `LENSLATE_PLATFORM=x11` or `=wayland` for one run: for testing.
