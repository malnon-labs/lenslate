# Contributing to lenslate

Thanks for helping! lenslate is young (0.1), so bug reports from real games and real desktops are the most
useful thing right now.

## Reporting a bug

[Open an issue](https://github.com/malnon-labs/lenslate/issues/new/choose) and include:

- your Linux distribution and desktop (for example "Fedora 44, KDE Plasma 6, Wayland")
- the lenslate version (`lenslate --version`) and how you installed it (release download or git)
- the game (or what was on screen), the languages, and the preset or translator you used
- what you expected and what happened

**A debug recording helps the most.** Turn it on with `[debug] enabled = true` in
`~/.config/lenslate/config.toml` (or start lenslate with `LENSLATE_DEBUG=1`), repeat the problem, and attach
the newest folder in `~/.cache/lenslate/debug/`. It contains screenshots of your game, so look through it
first (on Cinnamon, GNOME and tiling desktops a notification that popped up inside the area can be in them too;
Do Not Disturb while recording avoids that).

**A bad translation?** Say which translator made it, and paste the original line and the translation. If the
original line was *read* wrong (a wrong character), that's a reading problem, not a translation problem, and
a screenshot of that spot helps.

## Translating lenslate's pages

The README is available in [简体中文](README.zh-CN.md) and [Português (Brasil)](README.pt-BR.md). If you're a
native speaker and something reads oddly, a pull request or an issue with a better wording is very welcome.
Translating lenslate's own windows is planned.

## Code

- Run the offline tests before a pull request. They need no models, GPU or network:
  `python3 -m unittest discover -s tests -t .`
- Keep changes small and say what you tested on (desktop, game).
- Big changes: open an issue first so we can agree on the approach.
- lenslate is GPL-3.0-or-later. By sending a pull request you agree your change is shared under the same licence.
