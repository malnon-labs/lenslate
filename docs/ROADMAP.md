# lenslate roadmap

Where lenslate is going, what I've decided along the way, and the numbers behind those decisions. The newest
release is **0.1.0** (an early preview). Changes per version are in [CHANGELOG.md](../CHANGELOG.md).

## Goals

- A screen translator for Linux that can read anything on screen: games, comics, videos, pictures, documents.
  Reading the screen (OCR) is the core; game hooks (Unity, RPG Maker, Ren'Py) are a bonus.
- Local first. Online translators are opt-in, as the main translator or only as a fallback.
- The translation sits on the original text, in place. No subtitle bar or second window.
- A new user picks one preset and is ready to go; every option shows what it costs (speed, memory, quality,
  download size, licence).
- Nothing switches behind the user's back: when something doesn't fit, lenslate warns and asks.
- A clean interface: short labels, the explanations on hover.
- Version 1.0 = KDE Plasma 6 (Wayland) and X11 desktops, with the settings window, command line, installer and
  config file. Then Hyprland / niri / Sway and GNOME; Windows and macOS after that.

## Next

### 0.2: still to do before the release
- **Build the AppImages again** with the 2026-11-21 changes (the files in dist/ are older: their settings window
  does not open on a PC whose NVIDIA card is off) and try the new ones once more on the X11 laptop. The older
  offline AppImage was tried on real X11 hardware (Linux Mint 22 Cinnamon, 3072x1728 at 2x, fresh home): translators
  imported, cards on a Japanese RPG Maker screen, automatic translation through a screen change, settings window,
  setup window and tray menu.
- A VirusTotal scan of each new AppImage, linked in the release notes.
- A native speaker's look at the windows in Portuguese, Chinese, Japanese, Korean and Russian (every text is
  translated, about 200 of them on 2026-11-21; none has been checked by a native speaker yet).
- **Cards over other windows (seen on the X11 laptop):** when another window covers part of the area (the setup
  window, a tray menu) or a tiling helper moves and resizes the game window, the old cards stay drawn on top of
  everything, in the old places, until the game window is back. Hide the cards while the game window is not the one
  the player sees over the area.

### Clean-ups (from a review of the app against desktop-app practice, 2026-11-20)
Done for 0.2 (2026-11-21): the README says what was tested; every visible text translated, with a test; settings
lenslate switches by itself said in a notice with Undo; the first-run fixes (the click hint in the overlay, one name
for the overlay, setup's Next downloading); settings-window screenshots retaken; the Names page's empty-list note.

Before 1.0:
- **Keyboard and screen readers:** help also on keyboard focus, accessible names from the same help text (the folded
  sidebar keeps its page names), visible one-line descriptions on the important controls and "?" buttons instead of
  the permanent hover bar; help bars that grow with large fonts. Release check: every control usable without a mouse.
- **A calmer settings window:** theme icons instead of emoji, radio buttons / dropdowns where KDE uses them, the
  typewriter timings and timing tables under an "Advanced" fold, one way of applying settings on every page.
- **Packaging:** a final app ID (reverse-DNS) with AppStream metadata checked in CI; update information inside the
  AppImage and an opt-in "check for updates" (off by default); AUR / COPR packages for KDE.
- **Code:** the old *.bak copies out of the project folder; the first-run window renamed from setup.py (packaging tools
  treat that name as an install script); a package with pyproject.toml; gui.py split per page and lenslate.py into
  daemon / capture / layout parts; one place for the pinned versions.
- **CI:** the distro Pythons the window runs on (3.14, 3.15), ruff, a smoke test that opens every page, actions pinned
  by commit, write permission only for the release job, signed provenance for release files.
- **Contributors:** a short ARCHITECTURE.md and the dev setup (install.sh --dev) in CONTRIBUTING; UX-GUIDE.md moved out
  of the user docs; a short highlights list per release in the changelog.

Later:
- A hold-to-peek key (original text while held) and area profiles (dialogue, menu, subtitles).
- Online translators labelled as unofficial endpoints that may break.
- gettext catalogs and Weblate before asking native speakers to help.
- A local crash log and a "Copy debug info" button (still no telemetry).

### Languages
- Brazilian Portuguese quality on real English games (OPUS on the processor, Gemma).
- Seed packs: review the wording, grow them from real game screens, per-pair downloads instead of shipping all.
- Real English game screenshots with answer keys for the testbench (only drawn screens so far).
- Chinese text inside hooked games (the game's own fonts may lack Chinese glyphs): untested.

### Other desktops
- **niri / Sway:** the portal capture and the layer-shell overlay work in a nested niri (share dialog, overlay
  above a fullscreen window, cards on the text with a stand-in stream). Still to try: the real PipeWire stream in
  a real niri login. Expected gaps: the mouse position for the picker (use `niri msg` / `swaymsg`), Sway's portal
  shares whole outputs only (cards blink, no auto refresh).
- **Hyprland:** same as niri, plus `hyprctl` gives the focused window and its position, so windowed games could
  work with a shared window. Design: one small "window finder" module with a back end per desktop (kdotool,
  Xlib, hyprctl, niri msg, swaymsg). Not in Fedora's repositories.
- **GNOME (Wayland):** no layer-shell. Options: the X11 overlay as an XWayland window (does Mutter keep it above a
  fullscreen game?) or a small GNOME Shell extension that draws the cards.
- The installer's package lists on these desktops are untested.

### Later
- **Browser integration** for pictures on web pages (manga, images): an extension that hands the picture to
  lenslate over native messaging and shows the result on the page. To learn from: Easydict (native messaging to
  a desktop OCR app), Budou OCR Scanlator (overlay inside the page), MangoTL (extension + local server). Text on
  web pages is out of scope: browsers already translate it.
- Translation cache tools: corrections kept apart from the size cap (and per game); a review tool that finds junk,
  fragments and misreads in the cache and suggests fixes for me to accept or reject.
- A text-hooker bridge (LunaHook) for engines without a hook (KiriKiri, WOLF RPG, RPG Maker VX Ace).
- Automatic CPU / GPU switching, opt-in only.
- Windows and macOS.

### Still to test on real hardware
- An exclusive-fullscreen game (none tried so far offered it).
- The Unity hook's own BepInEx + XUnity install on a real game (only test folders so far).
- Hotkeys on a real GNOME login (the keys work in a GNOME Shell 48 session in a container; Cinnamon also live earlier).
- Upgrading from an old install with old caches.

## Known weak spots (accepted for 0.1)

1. Highlighted or glowing buttons are misread.
2. A page that slides in is read mid-slide; the cards sit a few pixels off until the next change.
3. A turning 3D model keeps its part of the screen "changed", so the text finder runs on it every refresh.
4. Outlined or decorative lettering (titles, logos) is missed or misread.
5. Tiny marks in the art can be read as a lone character.
6. A card can drop out for one refresh and come back.
7. On a slow processor at a high resolution, a whole new screen takes ~5-8 s with Quick reading.
8. The processor translators get lone words wrong without context (レア → "Rhea"); seed packs cover the common
   ones, a language model does better.

## Decisions

| Date | Decision |
|---|---|
| 2026-11-04 | Source languages Japanese, Chinese (Simplified + Traditional), English; targets English, Spanish, Portuguese (Brazil). Korean and Russian later. |
| 2026-11-04 | Default language model Gemma 4 E2B (best game translations in my tests, 1.7 GB of GPU memory). A built-in llama.cpp runner; Ollama optional. |
| 2026-11-04 | Online translators (Google, Bing, Yandex, DeepL) off by default, each with its own cache, usable as a fallback. |
| 2026-11-05 | Typewriter wait: experimental, off by default. |
| 2026-11-05 | quickmt (CC-BY) is the processor translator; Sugoi (non-commercial) and Gemma are optional downloads. |
| 2026-11-05 | No automatic CPU/GPU switching. A GPU-memory check may only warn and ask. |
| 2026-11-05 | The first start shows every download so the user decides what gets installed. |
| 2026-11-10 | Presets are visible steps (Reading, Runs on, Translator), each explaining how it works: **No GPU**, **Balanced**, **Fastest**. Graphics-card reading only when its memory is free (otherwise the processor, with a notice). |
| 2026-11-10 | OCR: PP-OCRv6 small reads, PP-OCRv5 mobile finds (measurements below); the server models are gone. Ultrafast = meikiocr, Japanese only. Careful reading hidden from the interface (it found nothing Quick missed on 18 screens and was 2-3x slower). |
| 2026-11-10 | Half-size reading for 4K screens: an option, off by default. |
| 2026-11-10 | Translation cache saved append-only. Main audiences besides English speakers: Chinese and Brazilian players of English games, so English must read well and fast, and Chinese (Simplified) became a target. |
| 2026-11-11 | Quick reading keeps the 2x re-read of small text (same time, reads better). |
| 2026-11-11 | No draggable subtitle bar: the in-place overlay is lenslate's strong point. |
| 2026-11-11 | PLaMo 3 Translate 0.8B / 2B added to the catalog; TranslateGemma 4B and a Hy-MT2 manga fine-tune rejected (test round below). |
| 2026-11-11 | lenslate stays a separate app; other programs (game launchers) talk to it through its command line. |
| 2026-11-13 | Licence GPL-3.0-or-later. Default card opacity 1 (solid). |
| 2026-11-13 | Setup by language: tick the languages you read, only their translators are downloaded. PLaMo 0.8B for Japanese → English, Gemma otherwise. |
| 2026-11-18 | First public version is 0.1.0, not 1.0: everything is in, but it's lightly tested and unpolished. |
| 2026-11-18 | Default hotkeys Ctrl+Alt+Z / X / C / V (the old Ctrl+Alt+arrows switch workspaces on GNOME, Cinnamon, MATE and Xfce). |
| 2026-11-18 | Downloads: source tarball now; AppImage and offline AppImage next. |
| 2026-11-18 | Icon: a magnifying glass whose glass turns the Japanese あ under it into an A. |
| 2026-11-18 | AppImage on Wayland runs the app on the distro's Python Qt (the overlay layer only works with the system's Qt); its own Qt only on X11, or through XWayland with a notice. The engine and every OCR model are inside the image. |
| 2026-11-18 | Korean and Russian get quickmt on the processor despite weak lone words: sentences are good, and the seed packs carry the menus. |
| 2026-11-18 | The windows' translations are JSON catalogs keyed by the English text (a missing entry stays English). |

## Measured facts

Measured on my PC: Ryzen 5 5500 (6 threads for OCR), RTX 4060 8 GB, Fedora KDE Plasma 6.

**Translators**

| | quickmt | Sugoi v4 | Gemma 4 E2B | PLaMo 3 Translate 0.8B |
|---|---|---|---|---|
| Runs on | processor | processor | graphics card | graphics card (or processor) |
| Memory | ~0.5 GB RAM | ~1.1 GB RAM | ~1.7 GB VRAM | ~0.5 GB VRAM |
| Download | 0.4 GB per pair | 1.1 GB | 3.1 GB | 0.6 GB |
| Per new line | ~0.03 s | ~0.05 s | ~0.15 s | ~0.05 s |
| Menus | good, literal | poor (labels become sentences) | good | good |
| Dialogue | weakest | good | very good | most natural (Japanese → English) |
| Repairs misread characters | no | no | yes | no |
| Languages | one model per pair | Japanese → English | any pair | Japanese ↔ English best; no Portuguese |

**Reading (OCR)**, sums over the built-in 1080p test screens:

| Reader | Careful, processor | Quick, processor | Quick, graphics card | Accuracy (Careful / Quick) |
|---|---|---|---|---|
| PP-OCRv5 server (removed) | 47.7 s | 20.4 s | 5.5 s | 98.7% / 99.8% |
| PP-OCRv5 mobile | 15.4 s | 14.6 s | 2.2 s | 99.1% / 99.8% |
| PP-OCRv6 small (default) | 11.4 s | 9.0 s | 2.8 s | 98.9% / 99.2% |
| PP-OCRv6 medium | 45.4 s | 23.2 s | 2.8 s | 98.8% / 99.3% |

On 7 real game screenshots with hand-written answer keys: PP-OCRv6 small Quick 99.6%; Ultrafast (meikiocr)
90-100% on Japanese (misses tiny top-bar text), ~80% on Chinese. Other tools tried on the same screens:
NDLOCR-Lite 89%, EasyOCR 87% (slow), Tesseract 80%, Manga OCR + comic detector 74%.

**In games and videos (0.1.0):**
- A new dialogue line: 0.3-0.9 s until the card shows; a whole 1080p screen 1-3 s (Quick, processor) or
  0.2-0.6 s (graphics card).
- A video with subtitles in the picture (auto refresh on): each new subtitle got its card ~1 s after it
  appeared (0.6-1.0 s per read).
- Translation cache: about 66% of the lines read are lines seen before (re-reads of a changed area, menus);
  a hit takes microseconds instead of 0.03-0.2 s.

**Translation model test round** (2026-11-11; 39 Japanese game lines, 18 English lines into pt-BR / zh / es,
10 Chinese lines; one line per request):

| Model | s / line | GPU memory | Japanese → English | Other pairs | Verdict |
|---|---|---|---|---|---|
| Gemma 4 E2B | 0.13 | 1.6 GB | good; a few stiff lines; repairs misreads | pt-BR, zh, es usable | default |
| PLaMo 3 Translate 0.8B | 0.05 | 0.5 GB | most natural dialogue, names right; no misread repair | es / zh fine on sentences; no Portuguese | added |
| PLaMo 3 Translate 2B | 0.13 | 1.8 GB | a little more natural than 0.8B | better es / zh; no Portuguese | added |
| Hy-MT2 1.8B | 0.13 | 1.4 GB | literal, some wrong senses | pt-BR / zh good | experimental |
| TranslateGemma 4B | 0.24 | 2.8 GB | changes the meaning, wrong names, adds content | pt-BR ok | rejected |
| Hy-MT2 manga fine-tune | 0.10 | 1.4 GB | lively but drops text | – | rejected |

**Live in Risk of Rain 2 with the processor translators** (2026-11-18; main menu, logbook, an item page; cards
0.5-3.8 s after a new screen): English → Chinese, Korean → English and Russian → English all worked. Sentences and
"Label: value" rows came out well in all three; lone labels were where quickmt failed, often with web-page phrases
("Add to Cart", "Go to Top", 公司简介): those are rejected now and the seed packs got the game's labels. Tabs about a
line height apart had become one card ("Item & Equipment Monster"): fixed.

**English → Chinese on English game screens** (2026-11-18; 7 screens, ~60 lines): Gemma 4 E2B gave usable
Chinese for nearly everything (one line answered like an assistant, now rejected). quickmt en-zh was right on
sentences and settings, wrong on lone words (MSAA → 荣誉证书, Oak Staff → 橡树员工) and sometimes wrote web-page
leftovers ("您的位置:电驴大全 > 电影 > …", "曲名 : …"): those are removed now, and the en-zh pack covers the common
labels. **quickmt ko-en / ru-en**: good sentences, poor lone words ("설정" → "Get in touch"): the seed packs cover
menus. ~0.03 s a line on the processor, 0.36 / 0.41 GB.

## Done

- **0.2 (in progress, 2026-11-20):** desktop notifications inside the area are no longer read (KDE / X11
  notification windows covered before reading and recording; elsewhere their lines are left out by their text);
  the launcher copies KDE's private Python again after a distro Python upgrade (3.14 → 3.15 had stopped lenslate
  from starting). reading fixes from the README screenshots (ー read for 一, word spaces in
  kana-only lines, wrapped text in bubbles and centred panels joined, boxed tabs and far-apart words split, two
  rows in one Ultrafast box split, Ultrafast as a second reader for sparse Japanese); English → Chinese tested on
  English game screens (quickmt's web leftovers removed, en-zh pack grown); processor translators and seed packs
  for Korean and Russian, seed packs through English; hotkeys changed inside lenslate; offline packs; the
  AppImage build; lenslate's windows in five more languages; a readability pass on the settings window.
- **0.1.0 (2026-11-18), first public version:** the source tarball with checksum on GitHub; README rewritten for
  new users with real screenshots (games, comics, video) and translated into Chinese and Brazilian Portuguese;
  FEATURES, PRIVACY, CONTRIBUTING and SECURITY pages; the app icon; colour icons in the settings window; new
  default hotkeys; CI for the tests and the release.
- **Live tests on real games and desktops:** Risk of Rain 2 (Proton, KDE Wayland: KWin capture, auto refresh,
  the area following the window, two monitors, 125% scale, the X11 path through XWayland, portal capture),
  Slay the Spire 2 and Hotline Miami on a real X11 desktop (Linux Mint Cinnamon), Slay the Spire 2 menus on KDE,
  a Japanese RPG Maker MZ game, Pepper&Carrot comics, and Sintel with Japanese subtitles. Hotkeys on a running
  Cinnamon. niri nested in KDE.
- **Installer** tested in clean containers: Fedora 44, Debian 13, Ubuntu 26.04, Arch, openSUSE Tumbleweed
  (install, offline tests, reinstall, uninstall).
- **Release basics:** version number, changelog, licence notice for everything downloaded, issue template,
  pinned and checksum-verified downloads, caches stamped with the model and prompt version.
- **Platforms:** KDE Wayland (layer-shell overlay, KWin window capture), X11 (Xcomposite capture, unmanaged
  overlay), the screen-sharing portal for other Wayland desktops, mixed display scales, two monitors.
- **Languages:** Korean and Russian sources with their own reader; Chinese (Simplified) target; seed packs of
  menu translations; look-alike letter repair (katakana/kanji, Cyrillic/Latin); earlier lines as context for
  the language model (off by default).
- **Translators:** PLaMo 3 Translate in the catalog; Visual novel mode (menus to quickmt, dialogue to Sugoi);
  online fallback; per-translator caches; character name lists; corrections that always win.
- **Reading:** PP-OCRv6 small, Ultrafast (meikiocr), graphics-card reading, cards area by area, typed-out text
  without flicker, vertical text, splitting of touching tabs, junk filtering.
- **Settings window and setup:** presets with a "Your PC" panel and measured estimates, setup by language, hardware
  check, testbench, game hooks page, names & fixes page.
- **Game hooks:** RPG Maker MV / MZ (with pre-translation), Ren'Py 7 / 8, Unity (XUnity.AutoTranslator, with its
  own BepInEx install).
