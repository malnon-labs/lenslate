#!/usr/bin/env bash
# Build lenslate's AppImages (run by .github/workflows/release.yml on a v* tag; works on any x86-64 Linux with
# curl, tar and python3; build on an old distro - the CI uses Ubuntu 22.04 - so the result runs on older glibc too).
#
#   packaging/build-appimage.sh            dist/lenslate-<version>-x86_64.AppImage
#   packaging/build-appimage.sh --offline  dist/lenslate-<version>-offline-x86_64.AppImage: the same, plus an offline
#                                          pack with quickmt Japanese -> English, quickmt Chinese -> English and OPUS
#                                          English -> Portuguese (Brazil), imported on first start
#   ... --dir-only                         stop before packing: build/appimage*/AppDir (run its AppRun to try it)
#
# Inside: a standalone Python (python-build-standalone), Qt from PyPI (PySide6-Essentials), the engine packages of
# requirements-engine.txt with every OCR model fetched (the image is read-only, so nothing may download later into
# it), meikiocr's models, libxcb-cursor (Qt's X11 plugin needs it), and the app. packaging/AppRun says how it runs.
# Every download is pinned and checked against a SHA-256 recorded here.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="$PWD"
OFFLINE=0; DIR_ONLY=0
for a in "$@"; do
  case "$a" in --offline) OFFLINE=1 ;; --dir-only) DIR_ONLY=1 ;; *) echo "unknown option $a" >&2; exit 2 ;; esac
done
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' version.py)"
SUFFIX=""
[ "$OFFLINE" = 1 ] && SUFFIX="-offline"
NAME="lenslate-$VERSION$SUFFIX-x86_64.AppImage"
WORK="$SRC/build/appimage$SUFFIX"
DIR="$WORK/AppDir"
DL="$SRC/build/downloads"
LIMIT=$((2000 * 1000 * 1000))      # GitHub's limit per release file is 2 GiB; stay clearly under it

# python-build-standalone 20261026, CPython 3.12.16 (checksum from the release's SHA256SUMS)
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-x86_64-unknown-linux-gnu-install_only.tar.gz"
PY_SHA="6a79e922e50006b601f29e688407659da1c2b86ebcd4e9c7254cf234be8b89de"
# appimagetool 1.9.1 (the project publishes no checksum file; this is the SHA-256 of the file as downloaded
# 2026-11-18 - a changed file is not used)
TOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
TOOL_SHA="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
QT_PIN="PySide6-Essentials==6.12.0"      # the same Qt install.sh uses where the distro has none

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
fetch() {   # url sha256 file
  mkdir -p "$DL"
  if [ ! -f "$DL/$3" ] || ! echo "$2  $DL/$3" | sha256sum -c --quiet - 2>/dev/null; then
    curl -fL --retry 3 -o "$DL/$3.part" "$1"
    echo "$2  $DL/$3.part" | sha256sum -c --quiet - || { echo "checksum mismatch: $1" >&2; exit 1; }
    mv "$DL/$3.part" "$DL/$3"
  fi
}

say "lenslate $VERSION -> dist/$NAME"
rm -rf "$WORK"; mkdir -p "$DIR/usr/share/lenslate" "$DIR/usr/lib" "$SRC/dist"

say "Python"
fetch "$PY_URL" "$PY_SHA" python.tar.gz
tar -xzf "$DL/python.tar.gz" -C "$DIR/usr"          # -> usr/python
PYB="$DIR/usr/python/bin/python3"

say "Qt and the engine packages"
"$PYB" -m pip install -q --no-cache-dir --upgrade pip
"$PYB" -m pip install -q --no-cache-dir "$QT_PIN" -r requirements-engine.txt

say "the app"
APP="$DIR/usr/share/lenslate/app"
mkdir -p "$APP"
cp -r ./*.py ./*.qml requirements-engine.txt README.md install.sh LICENSE NOTICE.md CHANGELOG.md seeds i18n samples hooks packaging "$APP"/
git rev-parse --short=12 HEAD > "$APP/COMMIT" 2>/dev/null || true

say "OCR models (into the image: it is read-only later)"
export HF_HUB_CACHE="$DIR/usr/hf"
"$PYB" -c 'from PIL import Image, ImageDraw; i = Image.new("RGB", (320, 64)); ImageDraw.Draw(i).text((10, 20), "Hello 123", fill=(255, 255, 255)); i.save(__import__("sys").argv[1])' "$WORK/probe.png"
# a real read (full and quick path) in every reader mode: some models load only on their first use
for mode in "LENSLATE_OCR_SCRIPT=cjk" "LENSLATE_OCR_SCRIPT=korean" "LENSLATE_OCR_SCRIPT=eslav" "LENSLATE_OCR_READER=meiki"; do
  printf '{"path": "%s"}\n{"op": "detect", "path": "%s"}\n{"op": "read_lines", "path": "%s", "boxes": [[0, 0, 320, 64]]}\n' \
    "$WORK/probe.png" "$WORK/probe.png" "$WORK/probe.png" |
    env LENSLATE_OCR_GPU=off "$mode" "$PYB" -I "$APP/ocr_server.py" 2>/dev/null | grep -q '"error"' &&
    { echo "OCR helper failed in $mode" >&2; exit 1; }
done

say "libxcb-cursor (Qt's X11 plugin)"
for d in /usr/lib/x86_64-linux-gnu /usr/lib64 /usr/lib; do
  if [ -e "$d/libxcb-cursor.so.0" ]; then cp -L "$d/libxcb-cursor.so.0" "$DIR/usr/lib/"; break; fi
done
[ -e "$DIR/usr/lib/libxcb-cursor.so.0" ] || echo "!! libxcb-cursor.so.0 not found on the build system (apt install libxcb-cursor0)" >&2

if [ "$OFFLINE" = 1 ]; then
  say "offline pack: quickmt ja->en, quickmt zh->en, OPUS en->pt-BR"
  export LENSLATE_MODELS="$WORK/models"
  for m in quickmt-ja-en quickmt-zh-en opus-en-ptbr; do python3 lenslate.py models get "$m" >/dev/null; done
  python3 lenslate.py models pack "$DIR/usr/share/lenslate/offline-pack.tar" quickmt-ja-en quickmt-zh-en opus-en-ptbr
  unset LENSLATE_MODELS
fi

say "AppDir"
install -m755 packaging/AppRun "$DIR/AppRun"
cp packaging/lenslate.png "$DIR/lenslate.png"
cp packaging/lenslate.png "$DIR/.DirIcon"
cat > "$DIR/lenslate.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=lenslate
Comment=Translate text anywhere on screen, in place
Exec=lenslate gui
Icon=lenslate
Categories=Utility;Game;
Terminal=false
EOF
find "$DIR" -name __pycache__ -type d -prune -exec rm -rf {} +

if [ "$DIR_ONLY" = 1 ]; then
  du -sh "$DIR"; echo "AppDir ready: $DIR/AppRun"; exit 0
fi
say "appimagetool"
fetch "$TOOL_URL" "$TOOL_SHA" appimagetool
chmod +x "$DL/appimagetool"
OUT="$SRC/dist/$NAME"
ARCH=x86_64 "$DL/appimagetool" --appimage-extract-and-run --comp zstd "$DIR" "$OUT"
size=$(stat -c %s "$OUT")
echo "size: $((size / 1000 / 1000)) MB"
[ "$size" -lt "$LIMIT" ] || { echo "too big for a GitHub release file ($size bytes)" >&2; exit 1; }
(cd "$SRC/dist" && sha256sum "$NAME" > "$NAME.sha256" && cat "$NAME.sha256")
