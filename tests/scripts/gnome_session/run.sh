#!/bin/bash
# `lenslate hotkeys set` on a REAL GNOME Shell (48, X11 session under Xvfb, rootless podman): the keys are pressed and
# GNOME must run lenslate's commands. GNOME 49+ has no X11 session; this checks the gsettings / media-keys path, which
# is the same on Wayland.
#   tests/scripts/gnome_session/run.sh dist/lenslate-<version>-x86_64.AppImage
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
IMG="$(readlink -f "$1")"
podman image exists lenslate-gnome-test || podman build -q -t lenslate-gnome-test "$HERE"
timeout 600 podman run --rm --security-opt label=disable --userns=keep-id -v "$IMG:/dist/lenslate.AppImage:ro" \
  -v "$HERE/session.sh:/session.sh:ro" lenslate-gnome-test bash /session.sh 2>&1 | grep -a '^=='
