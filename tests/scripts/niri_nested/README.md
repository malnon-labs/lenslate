# niri nested in a KDE (or any Wayland) session

Runs niri as a window with its OWN D-Bus session and its own portals (xdg-desktop-portal + the GNOME backend), so
the real session is not touched. Needs `niri` and `xdg-desktop-portal-gnome` (Fedora: `sudo dnf install niri
xdg-desktop-portal-gnome`). First used 2026-11-13.

    tests/scripts/niri_nested/start.sh WORKDIR        # niri + portals; writes WORKDIR/env (socket, bus, IPC)
    source WORKDIR/lenv.sh                            # this shell now talks to the nested niri
    QT_QPA_PLATFORM=wayland python3 tests/scripts/niri_nested/game.py PICTURE --full &   # a stand-in game
    python3 tests/scripts/niri_nested/fakeshare.py PICTURE region 0 0 1280 800 &        # lenslate, see below
    niri msg action screenshot-screen -d true         # pictures land in WORKDIR/shots
    kill $(cat WORKDIR/niri.pid)                      # ends niri, its bus and portals

What works nested: the layer-shell overlay (lenslate's surface sits in niri's Overlay layer, above a fullscreen
window), the portal's share dialog (answer it with clicks into the niri window: the KDE window adds a 28 px title
bar), and everything after the capture. What does NOT: the screen share itself - niri's winit backend has no GBM
device ("error starting screencast: no GBM device available"; `render-drm-device` does not help), and the portal
then sends no answer at all. `fakeshare.py` therefore runs real lenslate with the portal stream replaced by a fixed
picture. The real PipeWire stream on niri needs a real niri session (log in to niri).
The niri config is the packaged default plus `debug { dbus-interfaces-in-non-session-instances }` - without it a
nested niri offers no org.gnome.Mutter.ScreenCast, and the portal has nothing to share from.
Start niri from a shell whose WAYLAND_DISPLAY is the OUTER session (a shell that sourced lenv.sh points at the
nested one and niri fails with EventLoopCreation).
