#!/bin/bash
# Risk of Rain 2 (Steam 632360, 1920x1080 fullscreen on the primary monitor): switch the game's language from the
# MAIN MENU with the flag button (top right). The change applies at once, no restart.
#   ror2_language.sh default|de|en|es-mx|es|fr|it|ja|ko|pt-br|ru|tr|zh
# List order measured 2026-11-12 (game ver. 1.5.0): 0 Default (English), 1 Deutsch, 2 English, 3 Español (Mexico),
# 4 Español, 5 Français, 6 Italiano, 7 日本語, 8 한국어, 9 Português (Brazil), 10 Русский, 11 Türkçe, 12 简化字.
# Four rows show at a time (y = 118, 156, 192, 229); one wheel notch scrolls one row; the list stops with row 9 on top.
# The list always opens at its top. Only run it when the main menu is fully up (a click during a screen change is
# lost), and CHECK the result with a screenshot: one run in three attempts missed during the first session.
# While the game is in Japanese the first row is two lines tall, so the rows below it sit ~18 px lower: go to
# "default" first, then to the language wanted.
# ALWAYS finish a test with `ror2_language.sh default` - the game's normal setting.
set -e
D="$(dirname "$0")"
names=(default de en es-mx es fr it ja ko pt-br ru tr zh)
idx=-1; for i in "${!names[@]}"; do [ "${names[$i]}" = "$1" ] && idx=$i; done
[ "$idx" -ge 0 ] || { sed -n 2,9p "$0"; exit 1; }
top=$(( idx > 9 ? 9 : idx )); row=$(( idx - top )); ys=(124 156 192 229)
"$D/input.sh" click 1515 86; sleep 1.5
if [ "$top" -gt 0 ]; then
  "$D/input.sh" move 1440 190
  ydotool mousemove -w -x 0 -y "-$top" >/dev/null
fi
sleep 1.0
"$D/input.sh" click 1420 "${ys[$row]}"
sleep 2.5
