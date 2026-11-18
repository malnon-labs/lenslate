#!/bin/bash
# Fake keyboard and mouse for live game tests on KDE Wayland (ydotool; `ydotoold` must be running - it needs no
# sudo here, the user is in the group that owns /dev/uinput).
#   input.sh focus PATTERN       activate the window whose class or title contains PATTERN (kdotool)
#   input.sh move X Y            pointer to X Y (pixels of the PRIMARY monitor at 0,0 - the game's monitor)
#   input.sh click X Y           move there and left-click
#   input.sh key CODE [CODE...]  press and release Linux key codes (57 space, 1 esc, 28 enter, 103 up, 108 down,
#                                105 left, 106 right, 15 tab)
#   input.sh hold CODE SECONDS   hold a key
# Pointer facts measured 2026-11-12 (ydotool 1.0.4, Plasma 6 Wayland): `mousemove -a` only reaches 0,0 reliably,
# and a relative move travels TWICE the number given. So: go to the corner, then move by half the target.
# `kdotool getmouselocation` does not follow these moves while a game has the pointer: check with a screenshot.
set -e
case "$1" in
  focus)
    w="$(for i in $(kdotool search --class .); do printf '%s\t%s\t%s\n' "$i" "$(kdotool getwindowclassname "$i")" "$(kdotool getwindowname "$i")"; done | grep -i -- "$2" | head -1 | cut -f1)"
    [ -n "$w" ] || { echo "no window matches $2"; exit 1; }
    kdotool windowactivate "$w"; echo "$w" ;;
  move|click)
    ydotool mousemove -a -x 0 -y 0 >/dev/null; sleep 0.15
    ydotool mousemove -x $(( $2 / 2 )) -y $(( $3 / 2 )) >/dev/null; sleep 0.25
    if [ "$1" = click ]; then ydotool click 0xC0 >/dev/null; fi ;;
  key)
    shift; for k in "$@"; do ydotool key "$k:1" "$k:0" >/dev/null; sleep 0.15; done ;;
  hold)
    ydotool key "$2:1" >/dev/null; sleep "$3"; ydotool key "$2:0" >/dev/null ;;
  *) sed -n 2,13p "$0"; exit 1 ;;
esac
