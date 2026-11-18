# Security

## Reporting a problem

Please **don't** open a public issue for a security problem. Use GitHub's private reporting instead:
[Report a vulnerability](https://github.com/malnon-labs/lenslate/security/advisories/new). Include what an
attacker could do and how to reproduce it. You'll get an answer as soon as possible; lenslate is a one-person
project, so please allow a few days.

Only the newest release gets security fixes.

## Things worth knowing

- **Window capture on KDE.** To read a game window without asking every time, the source install gives
  lenslate a private copy of the Python interpreter, which KWin allows to take screenshots. Any script run with
  that copy can take screenshots silently. To revoke it, delete
  `~/.local/share/applications/net.local.lenslate-capture.desktop` and `~/.local/libexec/lenslate/`. lenslate
  then falls back to Spectacle, which can only read the focused window. Details: [docs/USAGE.md](docs/USAGE.md#platforms).
- **The hook server** (`lenslate serve`) listens on 127.0.0.1 only, and refuses requests that come from web pages.
- **Downloads** of the translation models, llama.cpp and kdotool are pinned to one version and checked against a
  recorded checksum. The game-hook downloads (BepInEx, XUnity.AutoTranslator) are not checked yet.
- **Online translators** send the text on screen to that service. They are off by default; see
  [docs/PRIVACY.md](docs/PRIVACY.md).
