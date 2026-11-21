"""lenslate's version: one place (`lenslate --version`, the settings window, debug recordings, bug reports).

Raise VERSION with every release and add its section to CHANGELOG.md. The commit is added when known: a
development copy asks git, an installed copy reads the COMMIT file the installer writes next to the code.
"""
import os
import subprocess

VERSION = "0.2.0"
HERE = os.path.dirname(os.path.abspath(__file__))


def commit():
    try:
        with open(os.path.join(HERE, "COMMIT"), encoding="utf-8") as f:
            return f.read().strip()[:12]
    except OSError:
        pass
    if os.path.exists(os.path.join(HERE, ".git")):
        try:
            return subprocess.run(["git", "-C", HERE, "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                  timeout=3).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return ""


def describe():
    c = commit()
    return "%s (%s)" % (VERSION, c) if c else VERSION
