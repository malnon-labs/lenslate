# Privacy: what goes online and what stays on your PC

Short version: lenslate has **no account, no telemetry and no update check**. While you play, it reads and
translates on your own PC. It only goes online to download the parts you choose, and to translate only if
you turn on an online translator yourself.

## What stays on your PC

- **The pictures of your screen.** lenslate captures the area you picked, reads it on your PC and throws the
  picture away. Pictures are only kept if you turn on a debug recording (below).
- **The text it reads and its translations**, with the local translators (the processor translators and the
  AI models on your graphics card). Translations are cached in `~/.cache/lenslate/` so a line you've seen
  before shows up instantly.
- **Your settings, name lists and corrections** (`~/.config/lenslate/`).
- **The game hooks.** `lenslate serve` answers only programs on your own PC (127.0.0.1), and it turns away
  requests that come from web pages.

## When lenslate goes online

**1. Downloads.** These happen during install, in the setup window, or when you pick a model. Each one is
shown with its size first, and nothing large downloads until you press Download. (The planned offline
AppImage will already contain the reader and three translators, so it will need none of these unless you add
models.)

| What | From |
| --- | --- |
| Translators and AI models | Hugging Face (huggingface.co) |
| The text-reading models | ModelScope (modelscope.cn) and Hugging Face, through the RapidOCR and meikiocr packages |
| The AI model runner (llama.cpp), kdotool on KDE | GitHub (github.com) |
| Python packages for the engine (installer and source install only) | PyPI (pypi.org), through uv from astral.sh |
| BepInEx and XUnity.AutoTranslator (only for `lenslate hook install` on a Unity game) | builds.bepinex.dev, GitHub |

These are normal file downloads: the sites see your IP address and which file you asked for, as with any
download.

**2. Online translators: off unless you turn them on.** If you choose Google, Bing, Yandex or DeepL, either
as your translator or as a fallback when the local one fails, then **the text lenslate reads is sent to that
service**. Their own privacy terms apply. The pictures of your screen are never sent; only the text is.
Your DeepL key is kept in your config file, which only your user can read.

## Debug recordings

A debug recording is off by default. When you turn it on, it saves screenshots of the area, the text read
and the translations into `~/.cache/lenslate/debug/` on your PC. It is only shared if you attach it to a bug
report yourself, so look through it first: it contains pictures of your game.

## Removing everything

`./install.sh --uninstall`. Then remove `~/.config/lenslate`,
`~/.cache/lenslate` and `~/.local/share/lenslate` to delete settings, caches, models and recordings.
