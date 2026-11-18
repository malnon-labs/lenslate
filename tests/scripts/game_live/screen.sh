#!/bin/bash
# The whole desktop WITH lenslate's cards, as the user sees it (Spectacle), cut to the primary monitor and shrunk.
#   screen.sh OUT.png [WIDTH]     (only while lenslate captures through KWin - two Spectacle runs at once fail)
set -e
tmp="$(mktemp --suffix=.png)"
spectacle -b -n -f -o "$tmp" 2>/dev/null
python3 - "$tmp" "$1" "${2:-1280}" <<'PY'
import sys
from PIL import Image
im = Image.open(sys.argv[1]).crop((0, 0, 1920, 1080))
w = int(sys.argv[3])
im.resize((w, w * 1080 // 1920)).save(sys.argv[2])
PY
rm -f "$tmp"
