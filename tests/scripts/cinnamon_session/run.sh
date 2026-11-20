#!/bin/bash
# lenslate's AppImage in a REAL Cinnamon session on X11 (Xvfb + cinnamon in a rootless podman container), for when no
# X11 machine is at hand: cards on a test screen (X11 window capture, bundled Qt), `hotkeys set` and the keys
# actually pressed (Cinnamon runs the commands), and a notification inside the area (left out by its text).
#   tests/scripts/cinnamon_session/run.sh dist/lenslate-<version>-x86_64.AppImage [models-dir] [out-dir]
# The offline AppImage needs no models dir (it is tested without network: its pack is imported on first start).
# The online one needs quickmt-ja-en, e.g. ~/.local/share/lenslate/models/quickmt-ja-en's parent folder.
# Without network (the offline image) Cinnamon's notification service does not start in the container: the
# notification check needs the online run. Not covered: real GPU drivers, compositing on real hardware, exclusive fullscreen games.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../../.." && pwd)"
IMG="$(readlink -f "$1")"; MODELS="${2:-}"; OUT="${3:-$(mktemp -d)}"; mkdir -p "$OUT"
podman image exists lenslate-cinnamon-test || podman build -q -t lenslate-cinnamon-test "$HERE"
args=(--rm --security-opt label=disable --userns=keep-id -v "$IMG:/dist/lenslate.AppImage:ro"
      -v "$ROOT/samples/testbench:/samples:ro" -v "$OUT:/out" -v "$HERE/session.sh:/session.sh:ro")
if [ -n "$MODELS" ]; then args+=(-v "$(readlink -f "$MODELS"):/models:ro"); else args+=(--network none); fi
timeout 900 podman run "${args[@]}" lenslate-cinnamon-test bash /session.sh 2>&1 | grep -a '^=='
echo "screenshots and logs: $OUT"
