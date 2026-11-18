"""lenslate colour tokens + application stylesheet (light/dark aware). Spec: docs/UX-GUIDE.md.

Only widgets with a `role` property are styled; everything else stays native Breeze."""
from string import Template

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

TOKENS = {
    "light": dict(
        surface_card="#ffffff", surface_sunken="#e3e5e7", text_muted="#5b6168", text_disabled="#9aa1a8",
        border_subtle="#c3c7cb", border_strong="#757c84",
        accent="#1b6dac", accent_tint="#dbeaf6", accent_text="#0f4a78",
        primary="#1b6dac", primary_hover="#185d8f", primary_hover_border="#185d8f", primary_pressed="#124b73",
        on_primary="#ffffff", hover_tint="#e3eef8", pressed_tint="#cfe2f3",
        success="#1d7a3a", success_hover="#186a32", success_pressed="#145a2a",
        success_text="#1d7a3a", success_tint="#dff3e5",
        warning_text="#9c4f00", warning_tint="#fdf0dc",
        danger="#b8322a", danger_text="#b8322a", danger_text_on_tint="#8f2a22", danger_tint="#fbe7e5",
        badge_cpu="#5b6168", badge_gpu="#1b6dac", badge_allgpu="#7b3fa0"),
    "dark": dict(
        surface_card="#2a2e32", surface_sunken="#1a1d20", text_muted="#a9b1b9", text_disabled="#6e757c",
        border_subtle="#454a50", border_strong="#7d848c",
        accent="#5cbcf0", accent_tint="#1d3448", accent_text="#bfe3f8",
        primary="#1f78b8", primary_hover="#1f78b8", primary_hover_border="#5cbcf0", primary_pressed="#185d8f",
        on_primary="#ffffff", hover_tint="#2f3a45", pressed_tint="#1d3448",
        success="#1d7a3a", success_hover="#186a32", success_pressed="#145a2a",
        success_text="#5fcf80", success_tint="#1f3327",
        warning_text="#f5a742", warning_tint="#3a2f1c",
        danger="#b8322a", danger_text="#f2777a", danger_text_on_tint="#f2777a", danger_tint="#3a2224",
        badge_cpu="#5b6168", badge_gpu="#1b6dac", badge_allgpu="#7b3fa0"),
}

QSS = Template("""
/* ---------- sidebar ---------- */
QFrame#navside { background: $surface_sunken; border: none; border-right: 1px solid $border_subtle; }
QListWidget#nav { background: $surface_sunken; border: none; padding: 6px; outline: 0; }
QToolButton#navtoggle { border: none; border-radius: 6px; padding: 4px 8px; margin: 6px 6px 0 6px; color: $text; }
QToolButton#navtoggle:hover { background: $hover_tint; }
QListWidget#nav::item { min-height: 32px; padding: 0 10px; margin: 1px 0; border-radius: 6px; color: $text; }
QListWidget#nav::item:hover { background: $hover_tint; }
QListWidget#nav::item:selected { background: $accent_tint; color: $accent_text; border-left: 3px solid $accent; }

/* ---------- surfaces ---------- */
QFrame[role="card"]  { background: $surface_card; border: 1px solid $border_subtle; border-radius: 8px; }
QFrame[role="card"][state="current"]          { background: $accent_tint; border: 1px solid $accent; }
QFrame[role="card"][state="selected"]         { border: 2px solid $accent; }
QFrame[role="card"][state="current selected"] { background: $accent_tint; border: 2px solid $accent; }
QFrame[role="card"][state="warning"]          { background: $warning_tint; border: 1px solid $warning_text; }
QFrame[role="panel"] { background: $surface_sunken; border: 1px solid $border_subtle; border-radius: 8px; }
QGroupBox { background: $surface_card; border: 1px solid $border_subtle; border-radius: 8px;
            margin-top: 14px; padding: 12px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 10px; padding: 0 4px; }
QPlainTextEdit[role="log"] { background: $surface_sunken; border: 1px solid $border_subtle; border-radius: 6px; }

/* ---------- text ---------- */
QLabel[role="title"]   { font-size: ${fs_title}pt; font-weight: 600; }
QLabel[role="section"] { font-size: ${fs_section}pt; font-weight: 600; }
QLabel[role="cardtitle"] { font-size: ${fs_card}pt; font-weight: 700; }
QLabel[role="muted"]   { color: $text_muted; }
QLabel[role="hint"]    { color: $text_muted; font-size: ${fs_hint}pt; }
QLabel[role="rating"]  { color: $warning_text; letter-spacing: 1px; }
QLabel[role="kbd"]     { background: $surface_sunken; border: 1px solid $border_strong; border-radius: 4px;
                         padding: 1px 6px; font-weight: 600; }
QLabel[role="badge"]   { color: #ffffff; border-radius: 4px; padding: 1px 6px;
                         font-size: ${fs_hint}pt; font-weight: 600; }
QLabel[role="badge"][kind="cpu"]    { background: $badge_cpu; }
QLabel[role="badge"][kind="gpu"]    { background: $badge_gpu; }
QLabel[role="badge"][kind="allgpu"] { background: $badge_allgpu; }
QLabel[role="chip"] { border-radius: 4px; padding: 1px 6px; font-size: ${fs_hint}pt; font-weight: 600;
                      background: $surface_sunken; color: $text_muted; }
QLabel[role="chip"][kind="success"] { background: $success_tint; color: $success_text; }
QLabel[role="chip"][kind="warning"] { background: $warning_tint; color: $warning_text; }
QLabel[role="chip"][kind="accent"]  { background: $accent_tint;  color: $accent_text; }
QLabel[role="message"] { border-radius: 6px; padding: 8px 12px; background: $accent_tint; color: $accent_text;
                         border-left: 4px solid $accent; }
QFrame[role="tip"] { border-radius: 6px; background: $accent_tint; border-left: 4px solid $accent; }
QFrame[role="tip"] QLabel { background: transparent; color: $text; }
QLabel[role="message"][kind="warning"] { background: $warning_tint; color: $text; border-left-color: $warning_text; }
QLabel[role="message"][kind="error"]   { background: $danger_tint; color: $danger_text_on_tint;
                                         border-left-color: $danger; }

/* ---------- help bar ---------- */
QLabel[role="helpbar"] { background: $surface_sunken; border: none; border-top: 1px solid $border_subtle;
                         padding: 8px 12px; color: $text; }
QLabel[role="helpbar"][state="idle"]  { color: $text_muted; }
QLabel[role="helpbar"][state="error"] { background: $danger_tint; color: $danger_text_on_tint;
                                        border-top: 2px solid $danger; }

/* ---------- buttons (only widgets with a role; the rest stay native Breeze) ---------- */
QPushButton[role] { min-height: 30px; padding: 3px 14px; border-radius: 6px;
                    border: 1px solid $border_strong; background: $surface_card; color: $text; }
QPushButton[role]:hover   { background: $hover_tint; border-color: $accent; }
QPushButton[role]:pressed { background: $pressed_tint; }

QPushButton[role="primary"]         { background: $primary; border-color: $primary; color: $on_primary; font-weight: 600; }
QPushButton[role="primary"]:hover   { background: $primary_hover; border-color: $primary_hover_border; }
QPushButton[role="primary"]:pressed { background: $primary_pressed; border-color: $primary_pressed; }

QPushButton[role="download"]         { background: $success; border-color: $success; color: $on_primary; font-weight: 600; }
QPushButton[role="download"]:hover   { background: $success_hover; border-color: $success_hover; }
QPushButton[role="download"]:pressed { background: $success_pressed; border-color: $success_pressed; }

QPushButton[role="danger"]         { background: transparent; border-color: $danger; color: $danger_text; }
QPushButton[role="danger"]:hover   { background: $danger_tint; color: $danger_text_on_tint; }
QPushButton[role="danger"]:pressed { background: $danger_tint; border-width: 2px; padding: 2px 13px; }

QPushButton[role="quiet"]         { background: transparent; border-color: transparent; color: $accent; }
QPushButton[role="quiet"]:hover   { background: $hover_tint; border-color: transparent; }
QPushButton[role="quiet"]:pressed { background: $pressed_tint; }

/* segmented choosers: pos = first | mid | last | only */
QPushButton[role="segment"]               { border-radius: 0; padding: 3px 14px; }
QPushButton[role="segment"][pos="first"]  { border-top-left-radius: 6px; border-bottom-left-radius: 6px; }
QPushButton[role="segment"][pos="last"]   { border-top-right-radius: 6px; border-bottom-right-radius: 6px;
                                            border-left: 0; }
QPushButton[role="segment"][pos="mid"]    { border-left: 0; }
QPushButton[role="segment"][pos="only"]   { border-radius: 6px; }
QPushButton[role="segment"]:checked       { background: $primary; border-color: $primary; color: $on_primary;
                                            font-weight: 600; }
QPushButton[role="segment"]:checked:hover { background: $primary_hover; border-color: $primary_hover_border; }

/* focus: after hover so it wins; filled buttons get a ring in the text colour (contrasts with the fill) */
QPushButton[role]:focus                    { border: 2px solid $accent; padding: 2px 13px; }
QPushButton[role="primary"]:focus,
QPushButton[role="download"]:focus,
QPushButton[role="segment"]:checked:focus  { border: 2px solid $on_primary; }

/* thin progress bar (role "thin"): no text inside; a label next to it says what is happening */
QProgressBar[role="thin"] { border: 1px solid $border_subtle; border-radius: 4px; background: $surface_sunken;
                            min-height: 10px; max-height: 10px; }
QProgressBar[role="thin"]::chunk { background: $accent; border-radius: 3px; }

/* disabled last so it always wins */
QPushButton[role]:disabled { background: $surface_window; border: 1px solid $border_subtle;
                             color: $text_disabled; font-weight: 400; }
""")


def is_dark(pal=None):
    pal = pal or QApplication.palette()
    return pal.color(QPalette.Window).lightness() < 128   # works on every Qt 6; colorScheme() can be Unknown


def tokens():
    """The token set for the current palette; surfaces/text from the palette, semantic colours fixed."""
    pal = QApplication.palette()
    t = dict(TOKENS["dark" if is_dark(pal) else "light"])
    t["surface_window"] = pal.color(QPalette.Window).name()
    t["text"] = pal.color(QPalette.WindowText).name()
    if not is_dark(pal):
        t["surface_card"] = pal.color(QPalette.Base).name()
    base = QApplication.font().pointSizeF() if QApplication.font().pointSizeF() > 0 else 10.0
    t.update(fs_title="%.1f" % (base * 1.6), fs_section="%.1f" % (base * 1.2),
             fs_card="%.1f" % (base * 1.3), fs_hint="%.1f" % max(9.0, base - 1))
    return t


def color(name):
    """A token for inline rich text, e.g. "<span style='color:%s'>" % theme.color("danger_text")."""
    return tokens()[name]


_last = [None]


def apply(app=None):
    """Set the application stylesheet; skipped when nothing changed (a palette-change event can come back while the
    stylesheet is being set)."""
    app = app or QApplication.instance()
    qss = QSS.substitute(tokens())
    if qss == _last[0]:
        return
    _last[0] = qss
    app.setStyleSheet(qss)


def set_role(w, role=None, **props):
    """Give a widget a style role (and e.g. kind=, state=, pos=); re-polish so the QSS applies at once."""
    if role is not None:
        w.setProperty("role", role)
    for k, v in props.items():
        w.setProperty(k, v)
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()
    return w


def segment_row(buttons):
    """Mark buttons of one segmented chooser: role=segment and pos=first/mid/last/only; ✓ on the checked one."""
    n = len(buttons)
    for i, b in enumerate(buttons):
        pos = "only" if n == 1 else "first" if i == 0 else "last" if i == n - 1 else "mid"
        label = b.text().removeprefix("✓ ")
        b.setText(("✓ " + label) if b.isChecked() else label)
        b.toggled.connect(lambda on, b=b, label=label: b.setText(("✓ " + label) if on else label))
        set_role(b, "segment", pos=pos)
        # the checked state is bold and has "✓ ": reserve that width so the label never gets clipped
        f = b.font()
        f.setWeight(QFont.DemiBold)
        b.setMinimumWidth(max(b.minimumWidth(), QFontMetrics(f).horizontalAdvance("✓ " + label) + 34))
    return buttons


class _Follow(QObject):
    """Re-apply the stylesheet when the user switches light/dark (KDE changes the palette live)."""

    def eventFilter(self, obj, ev):
        if obj is QApplication.instance() and ev.type() == QEvent.ApplicationPaletteChange:
            apply()
        return False


def install(app):
    apply(app)
    app._theme_follow = _Follow(app)
    app.installEventFilter(app._theme_follow)
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorSchemeChanged"):          # Qt >= 6.5
        hints.colorSchemeChanged.connect(lambda _s: apply(app))
