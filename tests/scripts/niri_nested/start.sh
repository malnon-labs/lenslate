#!/bin/bash
# Nested niri with its own D-Bus session and portals; see README.md.   start.sh WORKDIR
set -eu
W="$(mkdir -p "$1" && cd "$1" && pwd)"; mkdir -p "$W/shots" "$W/cfg/lenslate" "$W/cache"; rm -f "$W/env"
sed -e 's#^spawn-at-startup "waybar"#// spawn-at-startup "waybar"#' -e 's#^    // skip-at-startup#    skip-at-startup#' \
    -e "s#^screenshot-path .*#screenshot-path \"$W/shots/%H-%M-%S.png\"#" -e 's#^// prefer-no-csd#prefer-no-csd#' \
    /usr/share/doc/niri/default-config.kdl > "$W/niri.kdl"
printf '\ndebug {\n    dbus-interfaces-in-non-session-instances\n}\n' >> "$W/niri.kdl"
[ -f "$W/cfg/lenslate/config.toml" ] || printf '[general]\nsetup_done = true\n[translator]\nkind = "mt"\nsources = "ja"\nonline_fallback = false\n' > "$W/cfg/lenslate/config.toml"
cat > "$W/inner.sh" <<IN
#!/bin/bash
export XDG_CURRENT_DESKTOP=niri XDG_SESSION_TYPE=wayland
niri -c "$W/niri.kdl" > "$W/niri.log" 2>&1 &
echo \$! > "$W/niri.pid"
for i in \$(seq 50); do sleep 0.2; grep -q 'listening on Wayland socket' "$W/niri.log" && break; done
SOCK=\$(grep -o 'listening on Wayland socket: [^ ]*' "$W/niri.log" | awk '{print \$NF}')
{ echo "socket=\$SOCK"; echo "DBUS_SESSION_BUS_ADDRESS=\$DBUS_SESSION_BUS_ADDRESS"
  echo "NIRI_SOCKET=\$(ls \$XDG_RUNTIME_DIR/niri.\$SOCK.*.sock | head -1)"; } > "$W/env.part"
export WAYLAND_DISPLAY=\$SOCK
dbus-update-activation-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE
/usr/libexec/xdg-desktop-portal-gnome > "$W/portal-gnome.log" 2>&1 &
sleep 1
/usr/libexec/xdg-desktop-portal -r > "$W/portal.log" 2>&1 &
mv "$W/env.part" "$W/env"
wait \$(cat "$W/niri.pid")
IN
chmod +x "$W/inner.sh"
(setsid nohup dbus-run-session -- "$W/inner.sh" > "$W/outer.log" 2>&1 < /dev/null &)
for i in $(seq 60); do sleep 0.25; [ -f "$W/env" ] && break; done
[ -f "$W/env" ] || { echo "niri did not start; see $W/niri.log"; exit 1; }
cat > "$W/lenv.sh" <<EOV
source <(grep -E "^(DBUS|NIRI)" "$W/env" | sed 's/^/export /')
export WAYLAND_DISPLAY=\$(grep socket "$W/env" | cut -d= -f2) XDG_CURRENT_DESKTOP=niri XDG_SESSION_TYPE=wayland
export XDG_CONFIG_HOME="$W/cfg" XDG_CACHE_HOME="$W/cache" LENSLATE_DEBUG=1
unset DISPLAY KDE_FULL_SESSION KDE_SESSION_VERSION
EOV
cat "$W/env"
