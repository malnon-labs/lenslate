# Using lenslate: the full reference

The [README](../README.md) is the short tour. This page has the details: commands, settings, translators,
presets, game hooks and how a refresh works.

## Hotkeys and commands
Every action is a button in the settings window (Overlay page) and in the tray icon's menu. The hotkeys are for
use inside a game. They were Ctrl+Alt+arrows before 0.1.0; those switch workspaces on GNOME, Cinnamon, MATE and
Xfce. Run `./install.sh` (KDE) or `lenslate hotkeys install` (Cinnamon, GNOME) again to move to the new keys.
Choosing your own keys inside lenslate is planned.

| Hotkey | Command | What it does |
| --- | --- | --- |
| Ctrl+Alt+Z | `lenslate select` | drag a box around the area to watch (Esc / right-click cancels), then translate |
| Ctrl+Alt+X | `lenslate now` | full re-read of the chosen area (translations still come from the cache) |
| Ctrl+Alt+C | `lenslate auto` | toggle auto-refresh (every 1 s; only changed text is read) |
| Ctrl+Alt+V | `lenslate toggle` | hide / show the overlay; hiding pauses auto-refresh, showing resumes it |

The installer adds these hotkeys on KDE. On other desktops run `lenslate hotkeys`: it prints the lines to paste for Hyprland, Sway, i3, niri, Xfce and MATE, and `lenslate hotkeys install` writes the shortcuts on Cinnamon and GNOME (with keys that are still free there). Also: `lenslate gui`
(settings window and tray icon), `lenslate opacity [0.1-1]` (card background, default 1 = solid; below 0.95 the text gets
a thin outline so it stays readable), `lenslate reset` (hide and forget the current screen; `clear` is an alias of
`toggle`, because KDE keeps running a hotkey's old command until KWin restarts), `lenslate region X Y W H
[SCREEN]`, `lenslate status`, `lenslate quit`. `lenslate help` lists everything.

## Install and first setup (details)
`./install.sh` (from the source download) installs the missing system packages (asks for sudo only if something is missing), uv, the engine environment
(~/.local/share/lenslate/engine: OCR + CPU translators), the `lenslate` command, KDE hotkeys, the window-capture
permission. It downloads no translation model in a desktop session: the setup window asks first.

In a desktop session the first start of the window (`lenslate gui`, or the installer's last question) opens the
**setup window**: tick the languages you read (Japanese, Chinese, English, Korean, Russian - Korean and Russian one
at a time, with English) and the one to translate into. Only what those languages need is downloaded: the small
processor translators for them (always, ~0.4 GB each; Korean and Russian have none) and, with a preset that uses
the graphics card, one language model - PLaMo 3 Translate 0.8B for Japanese into English (most natural dialogue,
0.6 GB of GPU memory, non-commercial licence), Gemma 4 E2B for every other mix. A model you chose yourself is kept.
Then a preset suggested for this PC's hardware (any other can be picked; a preset that does not fit gets a warning
with a yes/no choice), then every download with what it translates, its size and licence. Nothing big is
fetched until you press Download. `lenslate setup` opens it again (also: Translation page > Run setup again);
`lenslate hwcheck` prints what was found and which presets fit. Without a desktop (or `--yes`) the installer asks
its questions in the terminal instead.

## Settings
Everything is in `~/.config/lenslate/config.toml`; each setting is explained in the file (the same text the GUI will
shows on hover). Changes apply while lenslate runs. An environment variable can override one setting for a test run
(e.g. LENSLATE_DEBUG=1); the variable names are in config.py.

## Models
    lenslate models               # catalog: what is installed, size, memory
    lenslate models get sugoi-v4-ja-en
CPU models download straight from Hugging Face (resumable). Language models run on lenslate's built-in runner:
the first language model you get also downloads llama.cpp's official build (Vulkan: NVIDIA, AMD and Intel graphics;
95 MB) into ~/.local/share/lenslate/runtime, so nothing else needs to be installed. lenslate starts it when a
translation needs it and stops it when you quit or switch to a CPU translator (its GPU memory goes back to the game).
If Ollama already has the same model file, lenslate links to it instead of downloading it again. Ollama still works:
[translator] llm_backend = "ollama", or any Ollama model name as llm_model. Runner log: ~/.cache/lenslate/llama-server.log.
The first start of a model compiles GPU code once (~30 s); later starts take ~2 s.

## Languages
Translate from (config [translator] sources): Japanese, Chinese (Simplified and Traditional), English - and, each
with its own reader model and chosen alone, Korean or Russian (see below). Each line's
language is recognised from its script (kana = Japanese, Chinese characters without kana = Chinese, Latin = English);
text already in the target language is left alone. Translate into ([translator] language): English, Spanish,
Portuguese (Brazil). Chosen from Steam's language statistics (English, Simplified Chinese, Russian on top) and the
localization industry's priority targets (Spanish, Brazilian Portuguese); Korean and Russian sources need extra OCR
models and come later.
- Language models (Gemma) and online translators translate any pair directly (Gemma writes Brazilian Portuguese).
- CPU translators: quickmt ja-en, zh-en, en-es and OPUS en-pt (set to Brazilian Portuguese with its >>pob<< tag;
  quickmt's own en-pt writes European Portuguese); other pairs go through English (ja -> en -> es). Sugoi is
  Japanese -> English only (then on to Spanish/Portuguese). Going through English loses some meaning on single words.
- OCR (PP-OCRv6 small) reads Japanese, Simplified and Traditional Chinese and English with one model. Every crop gets a
  margin (text near the edge was missed), rows in different languages stay separate cards.
- Korean and Russian (new 2026-11-11): pick "Korean (and English)" or "Russian (and English)" in Translate from
  (config: `sources = "ko,en"` / `"ru,en"`). The main reader has no Hangul or Cyrillic, so the OCR helper loads
  PaddleOCR's PP-OCRv5 reader for that script (a few MB, fetched on first use). There is no processor translator for
  them here: use a language model (Gemma, PLaMo) or an online service. Ultrafast reading is Japanese only.
- Name lists find candidates in Japanese text (さん/ちゃん/くん...) and Chinese text (先生/师姐/大哥..., "李明：", 【】;
  pinyin spellings); entries you add by hand work for any language.

## Hooks: translation inside the game (no screen reading)
    lenslate hook status GAME_FOLDER          # engine and whether a hook is installed
    lenslate hook install GAME_FOLDER         # backs up every file it changes
    lenslate hook pretranslate GAME_FOLDER    # RPG Maker MV/MZ: translate all text now (instant while playing)
    lenslate hook remove GAME_FOLDER          # restores the backups
While playing, `lenslate serve` must run (start it yourself, or from your game launcher).
- RPG Maker MV / MZ: plugin js/plugins/Lenslate.js. Messages (word-wrapped to the window, made smaller when needed),
  choices, speaker lines, item/skill/menu texts, map names, and other text drawn by plugins (only already-translated
  text there; new text is queued). Escape codes: names/variables/icons kept as placeholders, colour changes inside a
  sentence dropped. Pre-translation reads data/*.json (a test game: 6,589 texts).
- Ren'Py (7 and 8): game/zz_lenslate.rpy. Dialogue and menus translated before they are shown; names and buttons
  from the cache; the whole script is queued for background translation when the game starts.
- Unity: points XUnity.AutoTranslator at lenslate (BepInEx + XUnity are installed first when missing).
- No hook yet (use the screen overlay): Wolf RPG, RPG Maker VX Ace/VX/XP, KiriKiri and others.

## Presets
The Translation page: Languages first, then a **Preset** row, then the steps ("How it reads and translates") with
the Your PC panel estimating exactly the steps set. Change any step to make your own combination (shown as
Custom). `lenslate preset nogpu|balanced|fastest` from the command line (old names light/fast still work).
1. **Reading** (PaddleOCR PP-OCRv6 small models; quick finder PP-OCRv5 mobile), with a **CPU | GPU** switch:
   *Quick* = the finder marks each line once (area shrunk to at most 1920 px), the reader reads only those boxes.
   *Ultrafast* = meikiocr (trained on Japanese game text) finds and reads, English lines re-read by PaddleOCR;
   Japanese only, tiny UI text is missed. GPU = NVIDIA/CUDA (one-time 3.4 GB download; used only when the memory
   is free, otherwise the processor reads and a notice says why); Ultrafast on the GPU uses a 512 MB arena, batch 2.
   *Careful* (full-size finder, small text re-read enlarged) is no longer offered: on 18 test screens it found
   nothing Quick missed and was 2-3x slower. It still works from config.toml (`[ocr] reading = "accurate"`) and
   shows in the row while it is in use.
2. **Translator**: *Cheapest (quickmt)*, *Visual novel (quickmt + Sugoi)*, *Language model* (the chosen model;
   your own Ollama model too), *Online*. An "if the local translator fails, use online" box sits under it.

| Preset | Reading | Runs on | Translator |
| --- | --- | --- | --- |
| No GPU | Quick | Processor | Cheapest (quickmt) |
| Balanced (recommended) | Quick | Processor | Language model |
| Fastest | Quick | Graphics card (NVIDIA) | Language model |

Presets never change the language model you chose or the typewriter wait (Overlay page). The setup window (or,
without a desktop, the installer: `lenslate models get --needed`, then `models pick` / `models use`) offers the
language model for your languages: declined, cancelled or failed -> No GPU. Picking a preset
runs a hardware check (graphics-card memory with room left for a game, NVIDIA for Fastest, RAM, disk space);
problems are shown and you choose. Options the languages or the PC cannot use are greyed out with the reason, and
switched away from by themselves when the languages change (gui.OPTION_LIMITS).

## Testbench: try every preset on test screens
`lenslate testbench` runs test screens through every preset with the real refresh code and writes
`~/.cache/lenslate/testbench/<time>/report.html`: time until the translation shows (first time / again, plus
model start-up), the steps (find + read, translate), a preview of each preset's overlay drawn on the image, and the
lines side by side. Built-in screens (`samples/testbench/`, redraw with `lenslate testbench samples`): title menu,
status menu, visual-novel dialogue, a Kate wall of text, a Chinese screen, small HUD text. Your own screenshots:
drop PNG/JPG files into `~/Pictures/lenslate-tests/` (they are included automatically), or pass files:
`lenslate testbench --presets light,fast shot1.png`. `--4k` adds 4K versions (built-in screens drawn at 4K, your
screenshots enlarged), `--half` reads big text at half size (`[ocr] big_text = half`). Uses empty caches; your settings and caches are not touched.

Offline tests (no models, network or GPU; own empty config and cache folders): `python3 -m unittest discover -s
tests -t .` from the project folder.

## Speed
- Fast line reads: the fast text detector's line boxes go straight to the recogniser (no second
  detection) for areas with up to 300 lines; Latin text (when English is translated), unsure lines and busy areas are
  read the full way. Recorded test session: 8.4 s vs 10.7 s; dialogue OCR 0.12-0.27 s. LENSLATE_FAST_LINES=0: off.
- Areas that keep changing but hold nothing to translate (an animated sprite next to pixel-art signs) are ignored
  for 30 s. Big changes use the fast detector at full resolution (never a full OCR pass over the frame).
- Typewriter wait: experimental, off by default ([refresh] settle_step).
- Optional: [overlay] placeholder ("…" card at once), [translator] stream (language-model text fills the card as
  it is written), [ocr] gpu (`lenslate ocr-gpu install`, 3.4 GB, NVIDIA): `reader` = line reading on the card
  (+0.4 GB GPU memory); `all` = finding and reading on the card (~1.6 GB): the processor stays almost idle
  (0.07 s of processor work per dialogue box instead of 3.5 s). The **Fastest** preset uses `all`.

## Troubleshooting / contributing
Debug recording: set `enabled = true` under [debug] in config.toml (or run with LENSLATE_DEBUG=1, or
`touch ~/.cache/lenslate/debug-on` to turn it on for hotkey-started sessions; delete the file to turn it off).
Each session then writes ~/.cache/lenslate/debug/<time>/: session.log, runs.jsonl (one record per refresh: what changed,
what was read, OCR text, translations, timings) and the captured image of every real read. Attach that folder (it
contains screenshots of your game) to a bug report. Debug runs can be replayed offline: build an OcrPipeline with
grab() returning the saved images (see the test scripts in the history).

## Translators
`lenslate translator [llm [MODEL] | mt | sugoi | online]` or the Translation page; saved in config.toml, switches live.
- `llm`: a language model on the graphics card through lenslate's built-in runner (llama.cpp) or Ollama. Models
  (`lenslate models`): **Gemma 4 E2B** (default: any language pair, corrects misread characters, 1.7 GB of GPU
  memory, ~0.13 s a line); **PLaMo 3 Translate 0.8B / 2B** (translation-only models, the most natural Japanese ->
  English dialogue in the 2026-11-11 test round; 0.8B needs only 0.5 GB and ~0.05 s a line; they do not correct
  misread characters, have no Portuguese, and are free for personal / non-commercial use only); Qwen3.5 4B
  uncensored; Hy-MT2 (experimental). Switching model or away from llm unloads the old one.
- `mt`: quickmt (CTranslate2, processor, ~0.5 GB RAM, ~30 ms a line). Literal; fine for menus and labels, weakest on
  casual dialogue. One model per language pair; other pairs go through English.
- `sugoi`: "Visual novel" mode: menus and labels through quickmt, dialogue through Sugoi v4 (processor, ~1.1 GB
  RAM, ~50 ms a line; Japanese -> English only; NTT non-commercial licence).
- `online`: Google / Bing / Yandex / DeepL (needs a key), off by default; can also be only the fallback when the
  local translator fails.
- Every translator has its own cache file in `~/.cache/lenslate/`, so what you see is always that translator's
  wording. Cached lines are instant and keep their wording; there is no fuzzy matching (a misread character = a new
  entry). Corrections you make on the Names & fixes page always win.
- Seed packs (`seeds/<from>-<to>.tsv`, setting `[translator] seed_packs`, on by default): ready-made translations
  of common menu / UI lines (en->zh/pt/es ~665 lines each, ja->en and zh->en ~300). Whole lines only. Your own
  packs: `~/.local/share/lenslate/seeds/<from>-<to>.tsv`.
- Earlier lines as context (`[translator] context_lines`, 0 = off): a language model gets the last few dialogue
  lines with each new one, so it knows who is speaking and what "it" refers to (in tests "the teacher said they'd
  come" became "she" after a line saying the teacher is a woman). Menus and labels never get context; a line is
  still translated once and keeps that wording.

Character names (`names.py`, `lenslate names ...`)
- Per-game lists `~/.config/lenslate/names/<game>.tsv` (+ `global.tsv`): `蒼汰<TAB>Sota` = used, `?蒼汰<TAB>Sota` =
  suggestion (not used until confirmed), `-客` = rejected. `<game>` = exe name, lower case, no .exe (overlay: the
  window class; hook mode: `http://127.0.0.1:14366/g/<game>/translate`).
- Language models get the names that occur in the line (PLaMo: as its glossary); quickmt / Sugoi get the name
  replaced before translating. The cache key includes the names used, so a changed spelling re-translates only the
  lines containing it.
- Filled from the game files (`lenslate names scan GAME_FOLDER`) or while playing (a new name seen 3 times is
  looked up and added as a suggestion, with a notification; language-model mode only). Confirm on the Names & fixes
  page or with `lenslate names ok GAME all`.

Typewriter text
- A line that grows keeps its old card with "…" until it stops. A cached line that a later line (within 15 s)
  extends is removed from the cache (it was caught half-typed).
- Settle wait, experimental and off by default (`[refresh] settle_step`, e.g. 0.15): lenslate re-captures until
  nothing new is drawn in those rows, then reads once.

## How a refresh works (`textflow.py`)
1. The area is captured (see Platforms) and turned into a grid of 16 px cells.
2. It is compared with the last 5 frames. Identical to a remembered frame -> its cards are shown again, nothing is
   read. Otherwise a fast text finder (PP-OCRv5 mobile detector) looks at the changed parts; only text whose own
   pixels changed is read again. Animated backgrounds and moving sprites next to unchanged text cost ~0.1-0.5 s.
   Areas that keep changing but hold nothing to translate are ignored for 30 s.
3. Found lines go to the reader (Quick: the finder's boxes straight to the recogniser; small text is read again at
   2x). Pieces on one row are merged; a row continues the block above only when that row is full and does not end
   a sentence (real wrapped text). Menus, labels and separate dialogue lines stay separate cards. Implausible
   "text" (a sprite read as one huge character) is dropped; rows in different languages never merge.
4. Each block's exact text is looked up in the cache; misses are translated one block per request and appear
   area by area as they finish. A reply that is still mostly in the source language is retried once and never
   cached; a line that failed is not asked again for 60 s.
5. Card layout: the card keeps the original block's place and height; the font starts at ~80% of the original
   line height, the card may grow a little to the right, then the text wraps, then the font shrinks. Cards never
   cover each other. Positions are in logical pixels at any display scale.

## Platforms
- **KDE Plasma 6, Wayland** (main platform). The overlay is a layer-shell surface on the overlay layer, so it sits
  above fullscreen games, and it uses Qt's *software* renderer on purpose (the GPU renderer silently draws nothing
  when the game and a model fill the graphics memory). Capture: KWin's window capture (~20 ms, works when the
  window is not focused, never contains the cards). KWin allows that interface only for programs listed in a
  desktop file, so the installer gives lenslate a private copy of the Python interpreter
  (`~/.local/libexec/lenslate/lenslate-python`, `net.local.lenslate-capture.desktop` with
  `X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2`). Any script run with that copy can take screenshots
  silently; delete the desktop file and the copy to revoke it (lenslate then falls back to Spectacle: only the
  focused window, auto-refresh pauses when unfocused). After a Python update, re-run the installer.
- **X11 sessions** (new 2026-11-11; tested on Linux Mint 22.3 Cinnamon with 125 % scaling, windowed and fullscreen
  test windows, and on a bare nested X server). `x11.py` finds the focused window and
  captures it through the Composite extension (the window's own picture: no cards in it, also when covered). The
  overlay is an unmanaged window cut to the cards and raised again every second; without a compositing manager the
  cards are opaque. Not yet tried: real 3D / Proton games, several monitors. Live-test helpers:
  `tests/scripts/x11_live/`.
- **Other Wayland desktops with layer-shell (Hyprland, Sway ...)** (new 2026-11-11; untested there). Capture goes
  through the screen-sharing portal and PipeWire (`portalcap.py`; `[capture] backend = "portal"` forces it on KDE
  too). The desktop asks once which window or screen to share and remembers it; `lenslate share` asks again. The
  portal does not say where a window is, so a shared window must fill its monitor (fullscreen / borderless). A
  shared screen works anywhere but contains the cards: they blink around every read and auto-refresh is not
  offered. GNOME has no layer-shell: the overlay cannot be placed there yet.
- `LENSLATE_PLATFORM=x11|wayland` forces a backend for a test.
- What to share, which window sizes work and what to expect on each desktop: **[CAPTURE.md](CAPTURE.md)**, or `lenslate capture`.

Which monitor? The picker opens on the monitor under the mouse and shows that monitor's frozen frame; the cards go
on the monitor of the chosen area. (KWin ignores the requested screen on a surface's very first map, so lenslate
checks 250 ms later and re-maps once.)

## Resources (RTX 4060 8 GB, Ryzen 5 5500, measured with a game running)
- Idle / hidden: ~0. Auto on a quiet scene: ~4% of the machine. A tick with nothing new: ~0.13 s; a new dialogue
  line: ~0.3-0.9 s. A whole 1080p screen: ~1-3 s Quick on the processor, ~0.2-0.6 s on the graphics card.
- RAM: lenslate ~0.2-0.3 GB, OCR helper ~0.6-1 GB, model runner ~0.9 GB (model on the GPU). Language-model requests
  use a 4096-token context to keep GPU memory low.
- Stylised logo lettering and thick outlined title fonts read badly (オプション -> オブション); normal UI and dialogue
  text reads well.

## Robustness
- A new area or `toggle` cancels the running translation and drops its late results. `now` while a refresh is
  running is queued, not lost.
- Only one lenslate can run (lock file); bad commands get an error reply. `lenslate <command>` with nothing running
  starts lenslate and stays in the foreground. Stop it with `lenslate quit` (`toggle` / `reset` only hide the cards).
- After editing lenslate's files, `lenslate quit` first: the running one keeps the old code.

