#!/usr/bin/env bash
# lenslate installer: one command, any distro (first release: KDE Plasma on Wayland, and X11 sessions).
#
#   ./install.sh              install from this folder (copies the app to ~/.local/share/lenslate/app)
#   ./install.sh --dev        use this folder in place (for development: edits take effect immediately)
#   ./install.sh --no-model   download no translation model (offline install; translation needs one later)
#   ./install.sh --yes        don't ask questions (installs system packages with sudo)
#   ./install.sh --uninstall  remove lenslate (keeps your settings, name lists and translation cache)
#
# What it does, in order:
#   1. installs a few system packages with your distro's package manager (asks for your password once):
#      Python with PySide6 (Qt) and NumPy, the KDE overlay layer, kdotool, Spectacle, notify-send
#      (in an X11 session: Python, PySide6, NumPy, notify-send and the X Composite library only)
#   2. installs uv (a Python environment manager) into ~/.local/bin if it is missing
#   3. creates the engine environment ~/.local/share/lenslate/engine (screen OCR + CPU translators)
#   4. puts the `lenslate` command in ~/.local/bin and the app in ~/.local/share/lenslate/app
#   5. KDE Wayland: lets lenslate capture game windows directly (see "Capture permission" in README)
#   6. KDE: adds the hotkeys Ctrl+Alt+Z/X/C/V (only those not already taken)
#   7. translation models: in a desktop session nothing yet - the setup window asks which languages you need and
#      downloads only their translators (and a language model if you want one); without a desktop (or --yes) the
#      processor translators for the configured languages, then a question about the language model
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/lenslate"
APP="$DATA/app"
ENGINE="$DATA/engine"
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
LIBEXEC="$HOME/.local/libexec/lenslate"
DEV=0; MODEL=1; YES=0; UNINSTALL=0
for a in "$@"; do
  case "$a" in
    --dev) DEV=1 ;; --no-model) MODEL=0 ;; --yes|-y) YES=1 ;; --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown option $a (see --help)"; exit 2 ;;
  esac
done

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*"; exit 1; }
# questions read the terminal, not stdin: with `curl ... | bash` stdin is the script itself
ask()  {
  [ "$YES" = 1 ] && return 0
  if [ -r /dev/tty ]; then read -r -p "$1 [Y/n] " r < /dev/tty; else r=n; fi
  [ -z "$r" ] || [[ "$r" =~ ^[Yy] ]]
}

HOTKEYS=("select:Ctrl+Alt+Z:lenslate: pick region"
         "now:Ctrl+Alt+X:lenslate: translate now"
         "auto:Ctrl+Alt+C:lenslate: toggle auto"
         "toggle:Ctrl+Alt+V:lenslate: toggle overlay")

if [ "$UNINSTALL" = 1 ]; then
  say "removing lenslate"
  "$BIN/lenslate" quit >/dev/null 2>&1 || true
  rm -rf "$APP" "$ENGINE" "$LIBEXEC" "$DATA/gui"
  rm -f "$BIN/lenslate" "$APPS/net.local.lenslate-capture.desktop" "$APPS/lenslate.desktop" \
    "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/lenslate.svg"
  for h in "${HOTKEYS[@]}"; do rm -f "$APPS/net.local.lenslate-${h%%:*}.desktop"; done
  echo "kept: ~/.config/lenslate (settings, name lists), ~/.cache/lenslate (translations), $DATA/models"
  exit 0
fi

# ------------------------------------------------------------------------------------------ 1. system packages
. /etc/os-release
like=" ${ID:-} ${ID_LIKE:-} "
case "$like" in
  *" fedora "*|*" rhel "*)
    PM=(sudo dnf install -y)
    PKGS=(python3 python3-pyside6 python3-numpy layer-shell-qt kdotool spectacle libnotify) ;;
  *" arch "*)
    PM=(sudo pacman -S --needed --noconfirm)
    PKGS=(python pyside6 python-numpy layer-shell-qt spectacle libnotify) ;;   # kdotool is AUR-only: binary below
  *" debian "*|*" ubuntu "*)
    PM=(sudo apt-get install -y)
    PKGS=(python3 python3-numpy python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtqml
          python3-pyside6.qtquick python3-pyside6.qtnetwork python3-pyside6.qtwidgets
          qml6-module-qtquick qml6-module-qtquick-window layer-shell-qt qml6-module-org-kde-layershell
          kde-spectacle libnotify-bin) ;;   # needs Plasma 6: Debian 13+, Ubuntu 25.04+ (24.04 is Plasma 5)
  *" suse "*|*" opensuse "*)
    PM=(sudo zypper install -y)
    # (run on Tumbleweed in a container 2026-11-12: python3-pyside6 / python3-numpy resolve to the python313-
    #  packages; the QML side of layer-shell is its own package; kdotool is not packaged: binary below)
    PKGS=(python3 python3-pyside6 python3-numpy layer-shell-qt6 layer-shell-qt6-imports spectacle libnotify-tools) ;;
  *) PM=(); PKGS=() ;;
esac

# X11 session: windows, capture and the overlay go through X itself (x11.py), so the KDE Wayland pieces are not
# needed there; the Composite library is (window capture).
X11_SESSION=0
if [ -z "${WAYLAND_DISPLAY:-}" ] && { [ "${XDG_SESSION_TYPE:-}" = "x11" ] || [ -n "${DISPLAY:-}" ]; }; then
  X11_SESSION=1
  keep=()
  for p in "${PKGS[@]}"; do
    case "$p" in layer-shell-qt*|qml6-module-org-kde-layershell|kdotool|spectacle|kde-spectacle) ;; *) keep+=("$p") ;; esac
  done
  PKGS=("${keep[@]}")
  case "${PM[1]:-}" in     # + libxcb-cursor: needed by Qt's X11 plugin when Qt comes from PyPI (see OWN_QT below)
    dnf) PKGS+=(libXcomposite xcb-util-cursor) ;; pacman) PKGS+=(libxcomposite xcb-util-cursor) ;;
    apt-get) PKGS+=(libxcomposite1 libxcb-cursor0) ;; zypper) PKGS+=(libXcomposite1 libxcb-cursor0) ;;
  esac
fi

# Wayland desktops other than KDE (Hyprland, Sway, GNOME ...): capture goes through the screen-sharing portal and
# PipeWire (portalcap.py), read with GStreamer; KWin's helpers are not used there.
if [ "$X11_SESSION" = 0 ] && [[ "${XDG_CURRENT_DESKTOP:-KDE}" != *KDE* ]]; then
  keep=()
  for p in "${PKGS[@]}"; do case "$p" in kdotool|spectacle|kde-spectacle) ;; *) keep+=("$p") ;; esac; done
  PKGS=("${keep[@]}")
  case "${PM[1]:-}" in
    dnf) PKGS+=(python3-gobject pipewire-gstreamer) ;;
    pacman) PKGS+=(python-gobject gst-plugin-pipewire) ;;
    apt-get) PKGS+=(python3-gi gir1.2-gstreamer-1.0 gstreamer1.0-pipewire) ;;
    zypper) PKGS+=(python3-gobject gstreamer-plugin-pipewire) ;;
  esac
fi

if [ "${#PM[@]}" -eq 0 ]; then
  warn "unknown distro ($ID); install yourself: Python 3 with PySide6 (QtQuick) and NumPy, layer-shell-qt, kdotool, spectacle, notify-send"
else
  # only what is missing (no password prompt when everything is there)
  missing=()
  for p in "${PKGS[@]}"; do
    case "${PM[1]}" in
      dnf|zypper) rpm -q "$p" >/dev/null 2>&1 || rpm -q --whatprovides "$p" >/dev/null 2>&1 || missing+=("$p") ;;
      pacman) pacman -Qi "$p" >/dev/null 2>&1 || missing+=("$p") ;;
      apt-get) dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p") ;;
    esac
  done
  PKGS=("${missing[@]}")
fi
if [ "${#PM[@]}" -gt 0 ] && [ "${#PKGS[@]}" -eq 0 ]; then
  say "system packages: all present"
elif [ "${#PM[@]}" -gt 0 ]; then
  say "system packages to install (${PM[1]}): ${PKGS[*]}"
  if ask "install them now with sudo?"; then
    # Debian/Ubuntu: package names vary a little between releases; install what exists, report the rest
    if [ "${PM[1]}" = "apt-get" ]; then
      sudo apt-get update -qq || true
      ok=(); for p in "${PKGS[@]}"; do apt-cache show "$p" >/dev/null 2>&1 && ok+=("$p") || warn "not in this release: $p"; done
      PKGS=("${ok[@]}")
    fi
    # one unknown name makes dnf / zypper / pacman refuse the whole list: then each package gets its own try
    "${PM[@]}" "${PKGS[@]}" || {
      warn "installing them together failed; trying one by one"
      for p in "${PKGS[@]}"; do "${PM[@]}" "$p" >/dev/null 2>&1 || warn "could not install $p"; done
    }
  fi
fi

mkdir -p "$BIN"
PY="$(command -v python3 || true)"
[ -n "$PY" ] || die "python3 not found"
# The app's own Python needs PySide6 (Qt) and NumPy. Normally the distro's packages; where the distro has no
# PySide6 (Linux Mint 22, Ubuntu 24.04 ...) an X11 session can use the PyPI build in its own environment instead
# (set up after uv, below). On Wayland that is not possible: the overlay layer (layer-shell-qt) only works with
# the distro's own Qt.
OWN_QT=0
if ! "$PY" -c 'import PySide6.QtQuick, numpy' 2>/dev/null; then
  if [ "$X11_SESSION" = 1 ]; then
    OWN_QT=1
  else
    die "PySide6 (with QtQuick) or NumPy is missing for $PY, and a Wayland session needs the distro's own (see README, Install)"
  fi
fi
# kdotool (finds the game window on KDE) is not packaged everywhere: use the project's own release binary
if [ "$X11_SESSION" = 0 ] && ! command -v kdotool >/dev/null && [[ "${XDG_CURRENT_DESKTOP:-}" == *KDE* ]]; then
  say "kdotool (not in your distro's repositories): downloading the official release into ~/.local/bin"
  tmp="$(mktemp -d)"
  # the release file is checked against the checksum recorded here (2026-11-12): a changed file is not installed
  curl -fsSL -o "$tmp/k.tgz" https://github.com/jinliu/kdotool/releases/download/v0.3.0/kdotool-0.3.0-x86_64-unknown-linux-gnu.tar.gz &&
    echo "2079cc1d492b6e83e04def4d9376e34fcb36a4e3bdc637c8c2ee6fa547ce90ff  $tmp/k.tgz" | sha256sum -c --quiet - &&
    tar -xzf "$tmp/k.tgz" -C "$tmp" && install -m755 "$(find "$tmp" -name kdotool -type f | head -1)" "$BIN/kdotool" ||
    warn "could not install kdotool; lenslate will capture the whole screen instead of the game window"
  rm -rf "$tmp"
fi

# --------------------------------------------------------------------------------------------- 2. uv
if ! command -v uv >/dev/null; then
  say "installing uv (Python environment manager) into ~/.local/bin"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ "$OWN_QT" = 1 ]; then
  say "this distro has no PySide6 package: installing Qt for lenslate into $DATA/gui (PyPI, about 250 MB)"
  uv venv -q --allow-existing --python 3.12 "$DATA/gui"
  uv pip install -q --python "$DATA/gui/bin/python" "PySide6-Essentials==6.12.0" "numpy==2.5.4"
  PY="$DATA/gui/bin/python"
  # Qt's X11 plugin needs libxcb-cursor (package libxcb-cursor0 / xcb-util-cursor; asked for above)
  QT_QPA_PLATFORM=xcb "$PY" -c 'from PySide6.QtGui import QGuiApplication; QGuiApplication([])' >/dev/null 2>&1 ||
    warn "Qt could not open the X display: install libxcb-cursor0 (Debian/Ubuntu/Mint) or xcb-util-cursor (Fedora/Arch), then run install.sh again"
fi

# --------------------------------------------------------------------------------------------- 4. app files
mkdir -p "$DATA" "$BIN" "$APPS"
if [ "$DEV" = 1 ]; then
  APPDIR="$SRC"
  say "development install: running from $SRC"
else
  APPDIR="$APP"
  say "copying the app to $APP"
  rm -rf "$APP.new"; mkdir -p "$APP.new"
  (cd "$SRC" && cp -r *.py *.qml requirements-engine.txt README.md install.sh "$APP.new"/)
  [ -d "$SRC/samples" ] && cp -r "$SRC/samples" "$APP.new"/
  [ -d "$SRC/seeds" ] && cp -r "$SRC/seeds" "$APP.new"/
  [ -d "$SRC/i18n" ] && cp -r "$SRC/i18n" "$APP.new"/     # lenslate's windows in other languages
  [ -d "$SRC/hooks" ] && cp -r "$SRC/hooks" "$APP.new"/   # game plugins (lenslate hook install)
  [ -d "$SRC/packaging" ] && cp -r "$SRC/packaging" "$APP.new"/   # the app icon
  for f in LICENSE NOTICE.md CHANGELOG.md; do [ -f "$SRC/$f" ] && cp "$SRC/$f" "$APP.new"/; done
  # which commit this copy was made from (shown by `lenslate --version` and written into debug recordings)
  if [ -f "$SRC/COMMIT" ]; then cp "$SRC/COMMIT" "$APP.new"/
  elif [ -d "$SRC/.git" ] && command -v git >/dev/null; then git -C "$SRC" rev-parse --short HEAD > "$APP.new/COMMIT" 2>/dev/null || true; fi
  rm -rf "$APP"; mv "$APP.new" "$APP"
fi

# --------------------------------------------------------------------------------------------- 3. engine
say "engine environment (OCR + CPU translators): $ENGINE"
uv venv -q --allow-existing --python 3.12 "$ENGINE"
# with graphics-card reading installed (lenslate ocr-gpu install), the requirements would put the processor-only
# onnxruntime back over the CUDA build (same module folder): keep the CUDA build in that case
if uv pip show -q --python "$ENGINE/bin/python" onnxruntime-gpu >/dev/null 2>&1; then
  grep -v '^onnxruntime==' "$APPDIR/requirements-engine.txt" > "$ENGINE/requirements-gpu.txt"
  uv pip install -q --python "$ENGINE/bin/python" -r "$ENGINE/requirements-gpu.txt"
  uv pip uninstall -q --python "$ENGINE/bin/python" onnxruntime >/dev/null 2>&1 || true
  uv pip install -q --python "$ENGINE/bin/python" --reinstall "onnxruntime-gpu[cuda,cudnn]==1.23.2"
else
  uv pip install -q --python "$ENGINE/bin/python" -r "$APPDIR/requirements-engine.txt"
fi
# the OCR models that are not inside the packages (the quick finder, meikiocr's two models) download the first time
# they are used: in the middle of the first read, and offline that read failed. Fetch them now.
say "OCR models (fetched now, so the first read does not wait for a download)"
LENSLATE_OCR_GPU=off "$ENGINE/bin/python" -I "$APPDIR/ocr_server.py" </dev/null >/dev/null 2>&1 ||
  warn "could not fetch the OCR models now; they download on the first read instead"
LENSLATE_OCR_GPU=off "$ENGINE/bin/python" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import ocr_server; ocr_server.meiki()' \
  "$APPDIR" </dev/null >/dev/null 2>&1 ||
  warn "could not fetch meikiocr's models now (Ultrafast reading); they download on its first read instead"

# ---------------------------------------------------------------------- 5. capture permission (KDE Wayland)
RUNPY="$PY"
if [ "${XDG_SESSION_TYPE:-}" = wayland ] && [[ "${XDG_CURRENT_DESKTOP:-}" == *KDE* ]]; then
  say "KDE Wayland: allowing lenslate to capture game windows directly"
  # KWin allows its screenshot interface only for programs listed in a desktop file. lenslate gets its own copy
  # of the Python interpreter, so only lenslate (not every Python script) has that permission.
  mkdir -p "$LIBEXEC"
  cp "$(readlink -f "$PY")" "$LIBEXEC/lenslate-python"
  RUNPY="$LIBEXEC/lenslate-python"
  cat > "$APPS/net.local.lenslate-capture.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=lenslate screen capture
Comment=Private Python interpreter for lenslate; allowed to use KWin's screenshot interface (window capture without the overlay)
Exec=$RUNPY
NoDisplay=true
X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2
EOF
fi

cat > "$BIN/lenslate" <<EOF
#!/bin/bash
# lenslate (installed by install.sh). Runs on $( [ "$OWN_QT" = 1 ] && echo "its own Python environment with Qt from PyPI" || { [ "$RUNPY" = "$PY" ] && echo "the system Python" || echo "a private copy of the system Python that KWin lets capture windows"; } ).
PY="$RUNPY"
[ -x "\$PY" ] || PY="$PY"
exec "\$PY" "$APPDIR/lenslate.py" "\$@"
EOF
chmod +x "$BIN/lenslate"

# ------------------------------------------------------------------------------------------------ 6. hotkeys
if [[ "${XDG_CURRENT_DESKTOP:-}" == *KDE* ]] && command -v kwriteconfig6 >/dev/null; then
  say "hotkeys"
  for h in "${HOTKEYS[@]}"; do
    cmd="${h%%:*}"; rest="${h#*:}"; key="${rest%%:*}"; name="${rest#*:}"
    f="net.local.lenslate-$cmd.desktop"
    cat > "$APPS/$f" <<EOF
[Desktop Entry]
Exec=$BIN/lenslate $cmd
Name=$name
NoDisplay=true
StartupNotify=false
Type=Application
X-KDE-GlobalAccel-CommandShortcut=true
EOF
    # who has this key now? (group line above the _launch line)
    owner="$(grep -B1 "^_launch=$key\$" "$HOME/.config/kglobalshortcutsrc" 2>/dev/null | grep -o '\[services\]\[[^]]*\]' | head -1 || true)"
    if [ -n "$owner" ] && [[ "$owner" == *net.local.lenslate-* ]] && [[ "$owner" != *"$f"* ]]; then
      rm -f "$APPS/$f"   # an older lenslate shortcut file already runs this command with this key
      echo "  $key  $name (kept: ${owner#\[services\]})"
    elif [ -n "$owner" ] && [[ "$owner" != *"$f"* ]]; then
      warn "$key is already used by ${owner#\[services\]}; set a key for \"$name\" in System Settings > Shortcuts"
    elif grep -q "^_launch=$key\$" "$HOME/.config/kglobalshortcutsrc" 2>/dev/null && [ -z "$owner" ]; then
      warn "$key is already used by another program; set a key for \"$name\" in System Settings > Shortcuts"
    else
      kwriteconfig6 --file kglobalshortcutsrc --group services --group "$f" --key _launch "$key"
      echo "  $key  $name"
    fi
  done
  # the old toggle file name (it was called "clear" before)
  [ -f "$APPS/net.local.lenslate-clear.desktop" ] && sed -i "s|^Exec=.*|Exec=$BIN/lenslate toggle|" "$APPS/net.local.lenslate-clear.desktop"
  command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true
else
  # other desktops: `lenslate hotkeys` prints the lines for this desktop's settings (and writes them itself on
  # Cinnamon and GNOME with `lenslate hotkeys install`). Not done here without asking: it changes desktop settings.
  warn "hotkeys are not set on this desktop yet: run  lenslate hotkeys  to see how (Cinnamon / GNOME: lenslate hotkeys install)"
fi

# ------------------------------------------------------------------------------------ app menu entry (GUI)
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
mkdir -p "$ICONS" && cp "$APPDIR/packaging/lenslate.svg" "$ICONS/lenslate.svg"
cat > "$APPS/lenslate.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=lenslate
GenericName=Screen and game translator
Comment=Translate text on screen and in games with local models
Exec=$BIN/lenslate gui
Icon=lenslate
Categories=Utility;Game;
Keywords=translate;ocr;overlay;japanese;chinese;game;
StartupWMClass=lenslate
EOF

# ------------------------------------------------------------------------------------------------- 7. model
if [ "$MODEL" = 1 ]; then
  if [ "$YES" = 0 ] && { [ -n "${WAYLAND_DISPLAY:-}" ] || [ -n "${DISPLAY:-}" ]; }; then
    # Desktop session: the setup window (first start of `lenslate gui`) asks for the languages, checks this PC,
    # suggests a preset and shows every download with what it translates, its size and licence. Nothing is
    # downloaded here, so a Chinese-only player never gets the Japanese model.
    GUI_SETUP=1
  else
    # No desktop (or --yes): the processor translators for the configured languages ([translator] sources and
    # language in config.toml; default Japanese, Chinese, English -> English), then the language model question.
    say "translation models for your languages - they work on the processor, no graphics card needed"
    "$BIN/lenslate" models get --needed || warn "a translation model download did not finish (lenslate models get --needed retries)"
    llm="$("$BIN/lenslate" models pick)"
    preset=nogpu
    if ask "Download the language model $llm for natural translations (graphics card)? Without it translations are machine-like"; then
      if "$BIN/lenslate" models get "$llm"; then preset=balanced; "$BIN/lenslate" models use "$llm" >/dev/null
      else warn "the language model download did not finish; using the No GPU preset (lenslate's Models page can retry)"; fi
    fi
    "$BIN/lenslate" preset "$preset" >/dev/null && say "preset: $preset"
    if [ "$YES" = 0 ] && ask "Also download Sugoi (1.1 GB, visual-novel dialogue on the processor; NTT non-commercial licence)? [optional]"; then
      "$BIN/lenslate" models get sugoi-v4-ja-en || warn "Sugoi download did not finish"
    fi
    "$BIN/lenslate" setup --done
  fi
fi

case ":$PATH:" in *":$BIN:"*) ;; *) warn "add ~/.local/bin to your PATH to use the lenslate command";; esac
say "done. Open lenslate from the app menu (or: lenslate gui) and press Pick area."
if [ "${GUI_SETUP:-0}" = 1 ]; then
  if ask "Open lenslate's setup window now (languages, a preset that fits this PC, downloads)?"; then
    nohup "$BIN/lenslate" gui >/dev/null 2>&1 &
  else
    say "the setup window opens the first time you start lenslate (or run: lenslate setup)"
  fi
fi
"$BIN/lenslate" models list | sed -n '1,8p'
