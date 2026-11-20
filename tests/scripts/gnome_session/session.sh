#!/bin/bash
# Runs INSIDE the container (see run.sh): Xvfb, GNOME Shell 48 on X11 + gsd-media-keys (which runs custom
# shortcuts), then `lenslate hotkeys set` and the keys pressed; the command they run is a stub that notes its arguments.
set -u
export DISPLAY=:1 XDG_SESSION_TYPE=x11 XDG_CURRENT_DESKTOP=GNOME APPIMAGE_EXTRACT_AND_RUN=1 NO_CLEANUP=1
export XDG_RUNTIME_DIR=/tmp/rt; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
Xvfb :1 -screen 0 1920x1080x24 +extension GLX +render >/tmp/xvfb.log 2>&1 &
sleep 2; eval "$(dbus-launch --sh-syntax)"; export DBUS_SESSION_BUS_ADDRESS
# gnome-shell needs a system bus: a stand-in bus daemon run as the user
export DBUS_SYSTEM_BUS_ADDRESS=$(dbus-daemon --session --fork --print-address)
LIBGL_ALWAYS_SOFTWARE=1 gnome-shell --x11 --replace >/tmp/shell.log 2>&1 &
sleep 25
/usr/libexec/gsd-media-keys >/tmp/gsd.log 2>&1 &
sleep 5
echo "== gnome-shell: $(pgrep -x gnome-shell >/dev/null && echo running || echo NOT RUNNING) $(gnome-shell --version 2>/dev/null)"
echo "== gsd-media-keys: $(pgrep -f gsd-media-keys >/dev/null && echo running || echo NOT RUNNING)"
A=/dist/lenslate.AppImage
$A version 2>&1 | grep '^lenslate'
echo "== hotkeys set: $($A hotkeys set now=Ctrl+Alt+X toggle=Ctrl+Alt+C 2>&1 | grep -v '^qt\.' | tail -1)"
gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings
for p in $(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings | tr -d "[],'"); do
  i=org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$p
  echo "   $(gsettings get $i name) $(gsettings get $i command) $(gsettings get $i binding)"; done
# the command the keys run: a stub that notes its arguments (the desktop's part is what is tested here)
printf '#!/bin/sh\necho "$@" >> /tmp/ran.txt\n' > ~/.local/bin/lenslate; chmod +x ~/.local/bin/lenslate
sleep 3
xdotool key --clearmodifiers ctrl+alt+x; sleep 3
xdotool key --clearmodifiers ctrl+alt+c; sleep 3
echo "== keys ran: $(tr '\n' ' ' < /tmp/ran.txt 2>/dev/null)"
echo "== hotkeys remove: $($A hotkeys remove 2>&1 | grep -v '^qt\.' | tail -1)"
echo "== left: $(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)"
tail -5 /tmp/gsd.log
