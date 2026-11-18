#!/bin/bash
# One language pass on Risk of Rain 2: main menu + one logbook item page, read and translated by a test copy of
# lenslate, with pictures and the text pairs saved.
#   ror2_pass.sh GAME_LANG OUT_DIR [ITEM_X ITEM_Y]
#     GAME_LANG  a name ror2_language.sh knows (ja ko ru zh pt-br es fr de it tr en ...)
#     OUT_DIR    gets <lang>-menu.png, <lang>-logbook.png, <lang>-item.png (with cards) and <lang>.txt (original ->
#                translation, timings); the logbook screens are read by AUTO refresh, not by a forced read
# Needs, already done by the caller (see README.md): the game at its MAIN MENU in the default language, monitors
# awake, ydotoold running, and the test copy's variables exported (XDG_CONFIG_HOME, XDG_CACHE_HOME, LENSLATE_DEBUG=1)
# with a config.toml whose translator / sources / language fit GAME_LANG. No lenslate may be running.
# Ends at the main menu in the default language again, with the test copy stopped.
set -u
D="$(cd "$(dirname "$0")" && pwd)"; L="$1"; OUT="$2"; IX="${3:-300}"; IY="${4:-400}"
mkdir -p "$OUT"
[ -n "${XDG_CACHE_HOME:-}" ] && [ -n "${XDG_CONFIG_HOME:-}" ] || { echo "export the test copy's XDG_CONFIG_HOME / XDG_CACHE_HOME first"; exit 1; }
"$D/input.sh" focus "risk of rain" >/dev/null || exit 1
[ "$L" = en ] || [ "$L" = default ] || "$D/ror2_language.sh" "$L"
(setsid nohup lenslate region 0 0 1920 1080 DP-2 > "$OUT/$L-daemon.log" 2>&1 < /dev/null &)
dump() {   # the last read of this session: timings and original -> translation
python3 - "$1" <<PY
import glob, json, os, sys
f = sorted(glob.glob(os.path.join(os.environ["XDG_CACHE_HOME"], "lenslate/debug/*/runs.jsonl")))[-1]
recs = [json.loads(x) for x in open(f, encoding="utf-8")]
reads = [r for r in recs if r.get("kind") == "read"]
if not reads:
    print("## %s: no read recorded" % sys.argv[1]); sys.exit()
r = reads[-1]
print("## %s  (%s)  total %.2f s, first cards %s s, reading %.2f s, waiting for translations %.2f s, %d lines read"
      % (sys.argv[1], recs[0].get("translator", "?"), r["total_s"], r["first_card_s"], r["ocr_s"], r["translate_s"], len(r["ocr_lines"])))
for c in r["cards"]:
    print("  %s\n      -> %s" % (c["orig"], c["tr"]))
PY
}
wait_idle() {   # until the read is done (status says busy false), at most $1 seconds
  for _ in $(seq "$1"); do sleep 1; lenslate status 2>/dev/null | grep -q '"busy": false' && return 0; done
}
sleep 6; wait_idle 90; sleep 1
"$D/screen.sh" "$OUT/$L-menu.png"; dump "$L main menu" > "$OUT/$L.txt"
# from here on with auto refresh, as a player would have it: the cards must follow the screen changes by themselves
lenslate auto >/dev/null
"$D/input.sh" click 225 697; sleep 7; wait_idle 60; sleep 1          # Logbook (a row of tabs + the item grid)
"$D/screen.sh" "$OUT/$L-logbook.png"; dump "$L logbook" >> "$OUT/$L.txt"
"$D/input.sh" click "$IX" "$IY"; sleep 9; wait_idle 120; sleep 1      # an item page (slides in; old cards must go)
"$D/screen.sh" "$OUT/$L-item.png"; dump "$L logbook item" >> "$OUT/$L.txt"
lenslate quit >/dev/null; sleep 1
"$D/input.sh" click 195 1003; sleep 3; "$D/input.sh" click 195 1003; sleep 5   # Back, Back
[ "$L" = en ] || [ "$L" = default ] || "$D/ror2_language.sh" default
cat "$OUT/$L.txt"
