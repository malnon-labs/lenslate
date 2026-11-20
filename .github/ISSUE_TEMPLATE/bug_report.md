---
name: Problem report
about: Something is read wrong, translated wrong, placed wrong, slow, or does not start
---

**What happened, and what did you expect?**


**Where** (game or program, and whether it runs fullscreen, borderless or in a window)


**Your system** - paste the output of these three commands:

```
lenslate --version
lenslate capture
lenslate hwcheck
```

**A debug recording (the most useful thing you can attach)**

1. `touch ~/.cache/lenslate/debug-on` then `lenslate quit`
2. Reproduce the problem (a minute is enough).
3. `lenslate quit`, then `rm ~/.cache/lenslate/debug-on`
4. Zip the newest folder in `~/.cache/lenslate/debug/` and attach it.

The recording holds screenshots of the area you chose and the text read from it - look through it first and
leave out anything private. It never contains anything outside the chosen area, but a desktop notification that
popped up inside it can be in a picture (on Cinnamon, GNOME, Hyprland, Sway and niri; KDE and Xfce/MATE cover them).
Turn on Do Not Disturb while recording to be safe.

**Settings** (optional): `~/.config/lenslate/config.toml` - remove the `deepl_key` line if you have one.
