# Changelog

Newest first. The version is in `version.py` (`lenslate --version`). Dates are year-month-day.
Lines marked *(cache)* make lenslate translate cached lines again: the old ones are kept in `<cache file>.old`.

## Unreleased (0.2)

### 2026-11-18
- **Reading:** ー read for 一 before a kanji is repaired (ー緒 → 一緒, ー人 → 一人; translators made up names for
  them). Kana-only Japanese lines (retro games written without kanji) keep their word spaces, taken from the
  picture. Text wrapped inside a speech bubble or a centred panel becomes one card (comics, subtitles, centred
  descriptions). Tabs in separate boxes and words far apart on one row become separate cards, and Ultrafast no
  longer reads two menu rows in one box as one line. A Japanese area that comes back with only a few lines is
  read again with Ultrafast and the fuller reading is kept ([ocr] ultrafast_fallback, on by default: small pixel
  fonts).
- **Languages:** processor translators for **Korean → English and Russian → English** (quickmt ko-en, ru-en),
  with Korean and Russian seed packs for menus. Seed packs now also work through English (Korean → Portuguese,
  Japanese → Chinese menus) and on "label + number" lines ("Playtime 6:57:43"). English → Chinese tested on
  English game screens: quickmt's web-page leftovers ("您的位置:电驴大全 > …", "曲名 :", doubled words) are removed,
  an assistant-style answer is never shown as a translation, and the en-zh/es/pt packs grew (stats, settings,
  equipment).
- **Keyboard shortcuts** can be changed inside lenslate (Overlay page and setup's last page, or
  `lenslate hotkeys set select=Ctrl+Alt+Z ...`): checked for clashes, written to KDE (KGlobalAccel), Cinnamon or
  GNOME; other desktops get the lines to paste.
- **Offline packs:** `lenslate models pack` / `lenslate models import` and a "Load offline pack…" button: processor
  translators from one file, every file checked against its checksum and the pinned model version.
- **AppImages** (packaging/build-appimage.sh, built by the release workflow): one that downloads translators when
  you pick them, and an offline one with quickmt Japanese → English, quickmt Chinese → English and OPUS English →
  Portuguese (Brazil) inside. On Wayland they use the distro's Python Qt (the overlay layer needs it).
- **lenslate's windows in Portuguese (Brazil), Chinese, Japanese, Korean and Russian** ([general] ui_language,
  auto = the system language). Every text the windows show is translated, hover help and setting explanations
  included (a test checks that nothing is missing); Qt's own buttons follow too. Dropdowns show translated names
  and still save the same values.
- Settings window: side links (Keyboard shortcuts, Load offline pack) sit quietly next to their section; the
  Models page lists the processor translators first.

## 0.1.0 - 2026-11-18

The first public version: everything built since 2026-11-04. Early and lightly tested - expect rough edges.
Tested on KDE Plasma 6 (Wayland) and X11 (Cinnamon); other desktops are untested. Scope of the coming 1.0:
KDE Plasma 6 (Wayland) and X11 desktops, settings window, command line, installer.

### 2026-11-18
- New default hotkeys **Ctrl+Alt+Z / X / C / V** (pick area, translate now, auto refresh, show / hide). The old
  Ctrl+Alt+arrows switch workspaces on GNOME, Cinnamon, MATE and Xfce. Run the installer (KDE) or
  `lenslate hotkeys install` (Cinnamon, GNOME) again to move to them. The fallback set is Ctrl+Alt+Shift+F9-F12
  (Super+Alt+arrows is taken on GNOME and KDE).
- lenslate has its own icon (window, tray, app menu), and the settings window's pages have colour icons on every
  desktop.
- Setup's last page points to the buttons first. The README was rewritten for new users, with real screenshots,
  and is also in Simplified Chinese (README.zh-CN.md) and Brazilian Portuguese (README.pt-BR.md). New pages:
  docs/FEATURES.md, docs/PRIVACY.md, CONTRIBUTING.md, SECURITY.md; the full reference moved to docs/USAGE.md.

### 2026-11-13
- Setup by language: tick the languages you read; only their translators are downloaded (the installer downloads
  none in a desktop session). The language model follows the languages: PLaMo 3 Translate 0.8B for Japanese into
  English, Gemma 4 E2B otherwise; a model you chose yourself is kept. Every model says what it translates (setup,
  Models page, `lenslate models`); non-commercial licences are tagged. New: `lenslate models get --needed`,
  `models pick`, `models use NAME`.
- Models page: cards with a long licence line no longer cut off their description.
- Screen sharing that fails on the desktop's side (no answer from the portal) says so and what to try, instead of
  "the desktop did not answer". niri: share dialog, overlay and cards checked (nested niri; tests/scripts/niri_nested).
- Licences confirmed: meikiocr (Apache-2.0) and its models (LGPL-3.0), kdotool (Apache-2.0).
- Licence: GPL-3.0-or-later. Default card opacity 1 (solid).
- `lenslate hotkeys install` / `remove` check that the settings they read are the ones they write, and change
  nothing otherwise (a different XDG_CONFIG_HOME made them write over an existing shortcut).
- A word wider than its card is drawn smaller instead of being cut off at both sides.
- X11: the window on top of the area is read, not a focused window behind it (a game started over Steam).
- X11 with monitors at different display scales: windows and the pointer are placed per monitor (the game window
  on the scaled monitor was never found).
- Japanese -> English pack: settings words, language names, card-game words.

### Since the last session (2026-11-12, branch `release-basics`)
- The chosen area follows its game window: moved windows carry the area and its cards along; a resized window
  (windowed <-> fullscreen) scales the area and reads it again.
- Cards over text that is gone (new scene, closed dialogue box) come down at the start of the refresh instead of
  staying up until the new picture has been read.
- Fixed (found in a real game): when a big part of the screen and some small parts changed together, the cards of
  the small parts stayed up for good and buttons collected duplicate cards.
- Rows that open as "Label: value" (forms, item statistics) are separate cards instead of one merged paragraph.
- Model downloads are pinned to one commit of each Hugging Face repository (`models.REVISIONS`); the kdotool and
  llama.cpp program downloads are checked against recorded checksums.
- Installer: openSUSE package names corrected; one unknown package no longer stops the others from installing.
- Spanish menu lines from the seed pack keep their opening ¿ / ¡.
- Reading: two tabs read as one line are split; a lone character the reader is unsure about (icons, key hints) is
  dropped; two short capitalised rows (menu buttons) are no longer joined; kanji read in place of look-alike
  katakana (モ力 for モカ) are repaired where that is safe.
- With only Japanese turned on, rows written in kanji alone (dates, form entries) are no longer taken for Chinese
  and skipped; with Chinese on too, they follow the Japanese text seen on the same screen.
- Pictures read as a few low-confidence characters no longer get a card.
- Russian: tabs or buttons read as one glued line are split; a capital word's "!" read as "І" is put right.
- Drawn lettering (logos) read as a few low-confidence characters gets no card.
- A button or tab edge read as a lone "[" or "]" at the start or end of a line is removed.
- Verified on a real game: the X11 path, two monitors, the screen-sharing portal, a 125 % display scale.
- The default card opacity is 1, solid cards (was 0.6: the original text showed through in games). A saved setting stays.
- A button that lights up under the mouse keeps its card (a doubtful reading no longer replaces a confident one).
- Hotkeys on Cinnamon: the built-in workspace keys are seen, so lenslate picks free ones.
- Russian: words read with look-alike Latin letters ("ЖypHал") are turned back into Cyrillic before translating.
- Translation caches remember which model version and prompt made them (`<cache>.stamp`); when that changes, the
  old lines are set aside (`<cache>.old`) and translated again as they appear. Hand corrections stay.
- `lenslate hotkeys`: the four commands on keys outside KDE - ready-to-paste lines for Hyprland, Sway, i3, niri,
  Xfce and MATE; `lenslate hotkeys install` / `remove` on Cinnamon and GNOME (keys that are free).
- `lenslate --version`; the version is shown on the Advanced page and written into debug recordings.
- NOTICE.md (licences of everything lenslate installs or downloads), this changelog, CI workflow, issue template.

### Before that (see docs/ROADMAP.md "Done" for the details and commits)
- Overlay: OCR of a chosen screen area, change detection, text cache, cards over the original text, auto refresh.
- Capture: KWin direct window capture (KDE Wayland), X11 (Xcomposite), screen-sharing portal + PipeWire.
- Reading: PP-OCRv6 / PP-OCRv5 mobile through RapidOCR, Ultrafast (meikiocr, Japanese), optional GPU reading.
- Translators: quickmt and OPUS (processor), Sugoi v4, language models through the built-in llama.cpp runner
  (Gemma 4 E2B default, PLaMo 3 Translate, Qwen3.5, Hy-MT2) or Ollama, online services (off by default).
- Languages: Japanese, Chinese, English, Korean, Russian sources; English, Spanish, Portuguese (Brazil), Chinese
  (Simplified) targets.
- Per-game name lists, seed packs for menu words, Fix translations page, context lines (off by default).
- Game hooks: RPG Maker MV/MZ plugin, Ren'Py script, XUnity.AutoTranslator endpoint.
- Settings window with presets and a hardware check, first-run setup window, testbench, debug recordings.
