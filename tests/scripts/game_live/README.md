# Live tests on a real game (KDE Wayland, this PC)

Helpers for driving a real game and lenslate together without a person at the keyboard. First used 2026-11-12 on
Risk of Rain 2; everything below was measured in that session.

| File | What it does |
|---|---|
| `shot.py` | screenshot of one window through KWin (run with `~/.local/libexec/lenslate/lenslate-python`); no cards in it |
| `screen.sh` | the primary monitor as the user sees it, cards included (Spectacle) |
| `input.sh` | fake keys, clicks and pointer moves (ydotool), window focus (kdotool) |
| `ror2_language.sh` | Risk of Rain 2: switch the game language from the main menu |
| `ror2_pass.sh` | Risk of Rain 2: one whole language pass (main menu + a logbook item page), pictures and text pairs saved |

The quick way to repeat the test: steps 1-3 below, start the game and skip the intro, then for each language set
the test copy's `[translator] sources` (`ko` and `ru` must be chosen alone and need a language model or an online
translator) and run `ror2_pass.sh ja|ko|ru|zh|en OUT_DIR`. It ends back at the main menu in the default language.

## Before anything
1. **Monitors on.** With the displays asleep Steam never starts the game (it sat at "waiting for user response to
   CreatingProcess") and KWin captures are black: `kscreen-doctor --dpms on`, then keep them awake with
   `kde-inhibit --power --screenSaver sleep 14400 &` (stop it by its PID at the end).
2. **Input daemon:** `ydotoold &` (no sudo here). Stop it by PID at the end.
3. **A separate lenslate for the test**, so your own settings and translation caches are not touched:
   `export XDG_CONFIG_HOME=<scratch>/cfg XDG_CACHE_HOME=<scratch>/cache LENSLATE_DEBUG=1`, write
   `<scratch>/cfg/lenslate/config.toml` (`[general] setup_done = true`, `[translator] online_fallback = false`
   so no game text leaves the PC, the translator under test), make sure no other lenslate runs (`lenslate status`
   without those variables), then start it with `setsid nohup lenslate region 0 0 1920 1080 DP-2 > log 2>&1 < /dev/null &`.
   A fresh cache folder makes the first language-model load slow (~50 s: Vulkan shaders are compiled again).
   Every command for this copy needs the same variables. `lenslate quit` before testing changed code.
4. Results to read: the daemon log, and `<scratch>/cache/lenslate/debug/<time>/runs.jsonl` (one record per
   refresh: lines read, cards, timings; the first record names the lenslate version).

## Risk of Rain 2 (Steam app 632360, Proton, Unity)
- Start: `steam steam://rungameid/632360` (about 60 s to the window; class `steam_app_632360`, title
  `Risk of Rain 2`; fullscreen 1920x1080 on DP-2 at 0,0).
- Intro cinematic: Space once shows "Skip", Space again skips (`input.sh key 57`, wait 1 s, `input.sh key 57`);
  the main menu is up about 5 s later. The cinematic has subtitles - short dialogue lines over a moving picture.
- Main menu (1920x1080 pixel positions): Singleplayer 165,553 - Multiplayer 165,601 - Alternate Game Modes
  165,649 - Logbook 225,697 - Music 165,745 - Settings 165,793 - Quit to Desktop 180,842 (quits at once, no
  question). Language flag: 1515,86.
- Language: `ror2_language.sh ja` (and `default` at the end - to leave the game in "Default (English)"). The list has
  German, English, two Spanish, French, Italian, Japanese, Korean, Portuguese (Brazil), Russian, Turkish and
  Simplified Chinese - every source language lenslate reads. The change applies at once.
- Logbook (walls of text): click Logbook, then an item in the grid (first row: x = 195 + 84*n, y = 400; the
  second item, 300,400, is "Mocha": a description, counters, an order form of "Label: value" rows and a paragraph).
  The right half of an item page is a slowly turning 3D model (always "changed" for auto refresh).
  "Back" is at 195,1003 on both logbook pages. Esc does not go back there.
- Windowed mode for window tests: Alt+Enter (`ydotool key 56:1 28:1 28:0 56:0`) gives a 1920x1108 window with a
  title bar; `kdotool windowsize ID 1280 748`, `kdotool windowmove ID 300 150`. Alt+Enter again = fullscreen.
- Settings menus: not driven yet (Settings 165,793 from the main menu).

## Pointer and keys (ydotool 1.0.4 on Plasma 6)
- A relative move travels twice the number given, and `mousemove -a` only reaches the corner 0,0 reliably:
  `input.sh move X Y` goes to the corner and then moves by half the target. Coordinates are primary-monitor pixels.
- `kdotool getmouselocation` does not follow these moves while the game has the pointer: look at a screenshot.
- A click during a screen change is lost: wait for the new screen (2-5 s), then click. Check with `shot.py`.
- Wheel: `ydotool mousemove -w -x 0 -y -3` = three notches down.

## What the first session found (2026-11-12)
Worked in the real game: KWin window capture of a Proton / Unity fullscreen game, cards on the text, auto refresh
through screen changes, first cards 1-2 s after a new screen, the area following the window when it was resized
and moved, Japanese -> English with PLaMo 0.8B and Gemma, English -> Portuguese (Brazil) with the processor models.
Korean, Russian and Simplified Chinese (Gemma) read and translated both screens too.
Fixed from what was seen: cards of small re-read areas staying up after a big change (and buttons collecting
duplicate cards); "Label: value" rows merged into one card. Still open, see docs/ROADMAP.md "Found in the first
real-game test".

## Other paths on the same game (all done once, 2026-11-12)
- **X11 path:** the game is an X11 client of XWayland, so `export LENSLATE_PLATFORM=x11` before starting the test
  copy runs lenslate's X11 code (window search, Xcomposite capture, unmanaged overlay) against it.
- **Portal path:** `export LENSLATE_CAPTURE=portal`; KDE's dialog "Screen Sharing Requested" appears as a normal
  window (find it with `kdotool search --name "Screen Sharing Requested"`, activate it, click its search box at
  dialog x+630, y+83, `ydotool type "Risk of"`, click the one tile left at dialog x+368, y+190). With the box
  "without asking next time" ticked the next start shows no dialog.
- **Two monitors:** Alt+Enter, then `kdotool windowmove ID 2010 170` puts the window on DP-3 (1920,56 1280x1024).
  `screen.sh` shows the primary monitor only: for DP-3 cut (1920,0,3200,1080) out of a Spectacle full shot.
- **Display scale:** `kscreen-doctor output.DP-2.scale.1.25`, test, then ALWAYS
  `kscreen-doctor output.DP-2.scale.1 output.DP-2.position.0,0 output.DP-3.position.1920,56`. At 1.25 the game is
  1536x864 logical, a Spectacle full shot is twice the logical size, and `kdotool search --class` came back empty
  once (search by name instead). Pointer positions for input.sh are logical pixels then.
