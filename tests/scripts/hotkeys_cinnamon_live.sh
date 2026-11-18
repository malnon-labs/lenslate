#!/bin/bash
# A RUNNING Cinnamon desktop reacting to lenslate's hotkeys, without a second PC: Debian 13 in a rootless podman
# container, an X server without a screen (Xvfb), a D-Bus session, Cinnamon itself (software rendering), then
# `lenslate hotkeys install` and real key presses (xdotool). The `lenslate` command inside is a stand-in that writes
# its arguments to a file, so the test shows: keys chosen -> written to the settings -> Cinnamon runs the command.
#   tests/scripts/hotkeys_cinnamon_live.sh
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"; mkdir -p "$T/src"; (cd "$ROOT" && git ls-files -z | xargs -0 cp --parents -t "$T/src"); chmod -R a+rX "$T"
cat > "$T/run.sh" <<'IN'
export HOME=/root XDG_CURRENT_DESKTOP=X-Cinnamon DISPLAY=:9 LIBGL_ALWAYS_SOFTWARE=1 PATH=/root/.local/bin:$PATH
mkdir -p /root/.local/bin
printf '#!/bin/sh\necho "$@" >> /tmp/pressed.txt\n' > /root/.local/bin/lenslate; chmod +x /root/.local/bin/lenslate
Xvfb :9 -screen 0 1280x800x24 >/dev/null 2>&1 &
sleep 2
python3 -c "
import sys; sys.path.insert(0,'/src'); import hotkeys; sys.exit(hotkeys.cli(['install']))"
(cinnamon --replace > /tmp/cinnamon.log 2>&1 &)
for i in $(seq 40); do sleep 1; xdotool search --class cinnamon >/dev/null 2>&1 && break; done
sleep 12
echo "cinnamon running: $(pgrep -x cinnamon | wc -l) process(es); windows: $(xdotool search --name . 2>/dev/null | wc -l)"
for k in Up Right Left Down; do xdotool key --clearmodifiers super+alt+$k; sleep 1.5; done
echo "--- commands Cinnamon ran:"; cat /tmp/pressed.txt 2>/dev/null || echo "(none)"
python3 -c "
import sys; sys.path.insert(0,'/src'); import hotkeys; sys.exit(hotkeys.cli(['remove']))"
rm -f /tmp/pressed.txt; sleep 2
xdotool key --clearmodifiers super+alt+Up; sleep 1.5
echo "--- after remove:"; cat /tmp/pressed.txt 2>/dev/null || echo "(none: the key is free again)"
echo "--- cinnamon log (last lines):"; tail -12 /tmp/cinnamon.log
IN
podman run --rm -v "$T/src:/src:ro,z" -v "$T/run.sh:/run.sh:ro,z" docker.io/library/debian:13 bash -c "
  apt-get update -qq >/dev/null 2>&1
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends python3 libglib2.0-bin dbus dbus-x11 dbus-user-session dconf-gsettings-backend dconf-service xvfb xdotool procps cinnamon cinnamon-common cinnamon-desktop-data muffin-common libgl1-mesa-dri >/dev/null 2>&1 || echo 'package install had errors'
  dbus-run-session -- bash /run.sh" 2>&1 | grep -v "^$\|dbus-daemon\|^Trying\|^Getting\|^Copying\|^Writing" | cut -c1-200
rm -rf "$T"
