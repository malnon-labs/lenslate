#!/bin/bash
# Run install.sh on clean systems in rootless podman containers (no sudo on the host needed):
#   tests/scripts/installer_containers.sh [OUT_DIR] [NAME...]      names: fedora debian ubuntu arch opensuse
# For each system: a copy of the repo (git-tracked files only) is mounted read-only, copied inside, and then:
#   1. ./install.sh --yes --no-model   as a normal user with password-less sudo, as if in a KDE Wayland session
#   2. lenslate --version / hwcheck / capture / models / hotkeys / preset     (the installed copy, distro Python + Qt)
#   3. the offline tests on the distro's Python and PySide6
#   4. ./install.sh --yes --no-model again (upgrade over an existing install, settings kept)
#   5. ./install.sh --uninstall, and a check of what is left
# What a container cannot show: the overlay, capture, hotkeys and the tray (no desktop inside). The KDE-only steps
# of the installer run as far as they can without a session. Logs: OUT_DIR/<name>.log, summary on the terminal.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-/tmp/lenslate-installer-test}"; shift || true
mkdir -p "$OUT/src"
(cd "$ROOT" && git ls-files -z | xargs -0 cp --parents -t "$OUT/src" 2>/dev/null)
(cd "$ROOT" && git rev-parse --short HEAD > "$OUT/src/COMMIT")
declare -A IMG=([fedora]=registry.fedoraproject.org/fedora:44 [debian]=docker.io/library/debian:13
                [ubuntu]=docker.io/library/ubuntu:26.04 [arch]=docker.io/library/archlinux:latest
                [opensuse]=docker.io/opensuse/tumbleweed:latest)
declare -A PREP=(
  [fedora]="dnf install -y -q sudo util-linux curl tar gzip which procps-ng"
  [debian]="apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq sudo curl ca-certificates tar gzip procps"
  [ubuntu]="apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq sudo curl ca-certificates tar gzip procps"
  [arch]="pacman -Syu --noconfirm --needed sudo curl tar gzip which procps-ng"
  [opensuse]="zypper -n install sudo util-linux curl tar gzip which procps shadow")
[ "$#" -gt 0 ] || set -- fedora debian ubuntu arch opensuse
cat > "$OUT/inside.sh" <<'IN'
set -u
step() { printf '\n##### %s\n' "$*"; }
ok()   { printf 'RESULT %-34s %s\n' "$1" "$2"; }
cp -r /src ~/lenslate-src && cd ~/lenslate-src
export XDG_CURRENT_DESKTOP=KDE XDG_SESSION_TYPE=wayland WAYLAND_DISPLAY=wayland-0 PATH="$HOME/.local/bin:$PATH" DEBIAN_FRONTEND=noninteractive
step "1. install"; ./install.sh --yes --no-model; ok install "exit $?"
step "2. commands"
for c in "--version" hwcheck capture models "hotkeys" "hotkeys niri" preset; do
  out="$(lenslate $c 2>&1)"; rc=$?; echo "--- lenslate $c (exit $rc)"; echo "$out" | head -12; ok "lenslate $c" "exit $rc"
done
step "3. offline tests on the distro Python"
py="$(sed -n 's/^PY="\(.*\)"/\1/p' ~/.local/bin/lenslate | head -1)"; [ -x "$py" ] || py=python3
QT_QPA_PLATFORM=offscreen "$py" -m unittest discover -s tests -t . 2>&1 | tail -6; ok "unit tests ($py)" "exit ${PIPESTATUS[0]}"
"$py" -c "import PySide6, sys; print('python', sys.version.split()[0], 'PySide6', PySide6.__version__)"
step "4. engine"; ~/.local/share/lenslate/engine/bin/python -c "import rapidocr, onnxruntime, ctranslate2, sentencepiece; print('engine imports ok', onnxruntime.__version__)"; ok "engine imports" "exit $?"
step "5. upgrade (install again)"; mkdir -p ~/.config/lenslate; lenslate preset nogpu >/dev/null 2>&1; ./install.sh --yes --no-model >/tmp/again.log 2>&1; rc=$?; tail -4 /tmp/again.log; ok "second install" "exit $rc"
ok "settings kept" "$(grep -c nogpu ~/.config/lenslate/config.toml 2>/dev/null) line(s)"
step "6. uninstall"; ./install.sh --uninstall; ok uninstall "exit $?"
ok "left behind" "$(ls ~/.local/bin/lenslate ~/.local/share/lenslate/app ~/.local/share/applications/*lenslate* 2>/dev/null | wc -l) file(s) (0 expected)"
IN
chmod -R a+rX "$OUT/src" "$OUT/inside.sh"
for name in "$@"; do
  (
    podman run --rm --pull=missing -v "$OUT/src:/src:ro,z" -v "$OUT/inside.sh:/inside.sh:ro,z" "${IMG[$name]}" bash -c "
      (${PREP[$name]}) > /tmp/prep.log 2>&1 || { echo 'RESULT prepare FAILED'; tail -15 /tmp/prep.log; }
      useradd -m tester 2>/dev/null; mkdir -p /etc/sudoers.d; echo 'tester ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/tester
      grep -q sudoers.d /etc/sudoers 2>/dev/null || echo 'tester ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
      su - tester -c 'bash /inside.sh'" > "$OUT/$name.log" 2>&1
    echo "== $name: $(grep -c '^RESULT' "$OUT/$name.log") results" 
  ) &
done
wait
for name in "$@"; do echo; echo "=== $name"; grep '^RESULT' "$OUT/$name.log"; grep -a '^.\{0,12\}\(!!\|xx\) ' "$OUT/$name.log" | sed 's/\x1b\[[0-9;]*m//g' | sort -u | head -12; done
