#!/bin/bash
# `lenslate hotkeys install / remove` against the REAL settings schemas of GNOME and Cinnamon, in a rootless podman
# container (Debian 13 with the desktops' schema packages, a private D-Bus session, the dconf store). It proves the
# gsettings calls, schema names and value formats; it cannot prove that the desktop then reacts to the keys.
#   tests/scripts/hotkeys_containers.sh
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"; mkdir -p "$T/src"; (cd "$ROOT" && git ls-files -z | xargs -0 cp --parents -t "$T/src"); chmod -R a+rX "$T"
cat > "$T/run.sh" <<'IN'
export HOME=/root PATH=/root/.local/bin:$PATH
mkdir -p /root/.local/bin; printf '#!/bin/sh\nexec python3 /src/lenslate.py "$@"\n' > /root/.local/bin/lenslate; chmod +x /root/.local/bin/lenslate
for desk in GNOME X-Cinnamon; do
  export XDG_CURRENT_DESKTOP=$desk
  echo "===== $desk"
  if [ $desk = GNOME ]; then S=org.gnome.settings-daemon.plugins.media-keys; L=custom-keybindings; else S=org.cinnamon.desktop.keybindings; L=custom-list; fi
  echo "before: $(gsettings get $S $L)"
  python3 /src/hotkeys.py 2>/dev/null; python3 -c "
import sys; sys.path.insert(0,'/src'); import hotkeys; sys.exit(hotkeys.cli(['install']))"; echo "install exit $?"
  echo "list: $(gsettings get $S $L)"
  python3 -c "
import sys; sys.path.insert(0,'/src'); import hotkeys as h
spec=h.GS[h.desktop()]
for i in h.custom_ids(spec): print('  ', h._gs('get', h._item(spec,i), 'name'), h._gs('get', h._item(spec,i), 'command'), h._gs('get', h._item(spec,i), 'binding'))"
  python3 -c "
import sys; sys.path.insert(0,'/src'); import hotkeys; sys.exit(hotkeys.cli(['install']))" >/dev/null; echo "again: $(gsettings get $S $L)"
  python3 -c "
import sys; sys.path.insert(0,'/src'); import hotkeys; sys.exit(hotkeys.cli(['remove']))"; echo "after remove: $(gsettings get $S $L)"
done
IN
podman run --rm -v "$T/src:/src:ro,z" -v "$T/run.sh:/run.sh:ro,z" docker.io/library/debian:13 bash -c "
  apt-get update -qq >/dev/null 2>&1; DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends python3 libglib2.0-bin dbus dbus-user-session dconf-gsettings-backend dconf-service gsettings-desktop-schemas gnome-settings-daemon-common cinnamon-desktop-data cinnamon-common muffin-common >/dev/null 2>&1 || echo 'package install had errors'
  dbus-run-session -- bash /run.sh" 2>&1 | grep -v "^$" | cut -c1-230
rm -rf "$T"
