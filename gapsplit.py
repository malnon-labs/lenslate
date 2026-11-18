"""Split a read line where its picture shows two separate things side by side.

Tabs that stand apart (General / Graphics / Sound / Input, each in its own box) were read as one line and became
one wide card: the quick finder's pieces of a row are joined when they are less than a line height apart, and the
full reader's finder sometimes boxes the whole row. In the picture they are clearly apart: a box border stands in
the gap between two words, or the gap is far wider than a word space. This module finds those spots and shares the
text out between the pieces.

Pure Python + numpy (used by the OCR helper; the tests run it on drawn pictures).
"""
import re

WIDE_GAP = 1.1        # a gap this many line heights wide separates two items (a word space is ~0.3)
WORD_GAP = 0.22       # gaps narrower than this (in line heights) are inside a word
BAR_SHARE = 0.68      # an unbroken vertical stroke over this share of the picture's height is a border line
MARGIN = 0.3          # the margin above and below the line box the caller crops with, in line heights
CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿가-힯ｦ-ﾟ]")


def _ink(gray):
    """Boolean ink mask: pixels far from the picture's usual (background) brightness. Rows that are nearly all
    ink (a box's top or bottom edge crossing the line) are cleared, so they do not join everything."""
    import numpy as np
    g = np.asarray(gray, dtype=float)
    raw = np.abs(g - np.median(g)) > 40
    rows = raw.mean(axis=1) >= 0.6
    ink = raw.copy()
    ink[rows] = False
    return ink, int((~rows).sum()), raw


def _longest_runs(ink):
    """Per column: the longest unbroken vertical run of ink."""
    import numpy as np
    H, w = ink.shape
    best, cur = np.zeros(w, dtype=int), np.zeros(w, dtype=int)
    for y in range(H):
        cur = np.where(ink[y], cur + 1, 0)
        best = np.maximum(best, cur)
    return best


def pieces(gray, h=None):
    """[(x1, x2)] spans of the line picture that are separate items, or [] when the line is one thing.
    Gaps are measured in the height of the text's own rows (finder boxes have loose margins); h is a fallback."""
    import numpy as np
    ink, rows, raw = _ink(gray)
    H, w = ink.shape
    if w < 4 or rows < 4:
        return []
    runs_v = _longest_runs(raw)      # (a border runs on through a row that crosses it)
    # a border: an unbroken stroke over most of the picture's height. The picture is the line box with a margin of
    # MARGIN line heights above and below, so a letter's stroke covers at most 1 / (1 + 2 * MARGIN) of it
    bar = runs_v >= BAR_SHARE * H
    letters_h = ink[:, ~bar].mean(axis=1) if (~bar).any() else ink.mean(axis=1)
    band = np.nonzero(letters_h >= 0.02)[0]       # the text's own rows (finder boxes have loose margins)
    h = float(band[-1] - band[0] + 1) if len(band) >= 3 else float(h or H)
    col = ink.sum(axis=0)
    letters = (col > 0) & ~bar
    runs, start = [], None
    for x in range(w):
        if letters[x] and start is None:
            start = x
        elif not letters[x] and start is not None:
            runs.append([start, x])
            start = None
    if start is not None:
        runs.append([start, w])
    if len(runs) < 2:
        return []
    # letters into words (gaps narrower than a word space), then words into items
    words = [runs[0]]
    for a, b in runs[1:]:
        if a - words[-1][1] < WORD_GAP * h and not bar[words[-1][1]:a].any():
            words[-1][1] = b
        else:
            words.append([a, b])
    items = [list(words[0])]
    for a, b in words[1:]:
        gap = a - items[-1][1]
        bordered = bar[items[-1][1]:a].any()
        if gap >= WIDE_GAP * h or (bordered and gap >= WORD_GAP * h):
            items.append([a, b])
        else:
            items[-1][1] = b
    return [tuple(i) for i in items] if len(items) > 1 else []


def _width(t):
    return sum(2 if CJK.match(c) else 1 for c in t)


def share_text(text, spans):
    """Share text out over the picture's item spans. Latin text is cut at its spaces (each cut at the space closest
    to where the picture says), Chinese/Japanese text at the character closest. None when it does not fit."""
    t = text.strip()
    total_px = float(spans[-1][1] - spans[0][0])
    marks = [(spans[i][1] + spans[i + 1][0]) / 2.0 - spans[0][0] for i in range(len(spans) - 1)]
    full = float(_width(t)) or 1.0
    pos, acc = [], 0
    for c in t:                  # text position (in width units) at the start of each character
        pos.append(acc)
        acc += _width(c)
    spaces = [i for i, c in enumerate(t) if c == " "]
    cuts = []
    for m in marks:
        want = m / total_px * full
        if spaces:
            i = min(spaces, key=lambda k: abs(pos[k] - want))
        elif CJK.search(t):
            i = min(range(1, len(t)), key=lambda k: abs(pos[k] - want)) if len(t) > 1 else 0
        else:
            return None          # one Latin word: nothing to cut
        cuts.append(i)
    if len(set(cuts)) != len(cuts) or cuts != sorted(cuts) or 0 in cuts:
        return None
    out, prev = [], 0
    for i in cuts:
        out.append(t[prev:i].strip())
        prev = i
    out.append(t[prev:].strip())
    return out if all(out) else None


def split(text, gray, h=None):
    """[(piece_text, x1, x2)] in the picture's columns, or None when the line stays whole."""
    if len(text.strip()) < 2:
        return None
    spans = pieces(gray, h)
    if not spans:
        return None
    parts = share_text(text, spans)
    if parts is None:
        return None
    return [(p, a, b) for p, (a, b) in zip(parts, spans)]


def stacked_rows(gray, min_h=6):
    """[(y1, y2)] text rows inside one finder box that holds more than one (a box around two menu rows), or []
    when it is one row. A row break is a band of rows without any ink between two rows of text."""
    import numpy as np
    ink, _, _ = _ink(gray)
    H = ink.shape[0]
    filled = ink.any(axis=1)
    rows, start = [], None
    for y in range(H):
        if filled[y] and start is None:
            start = y
        elif not filled[y] and start is not None:
            rows.append([start, y])
            start = None
    if start is not None:
        rows.append([start, H])
    rows = [r for r in rows if r[1] - r[0] >= 2]
    # bits of one row (dakuten, a dot above) join their row: only rows of real text height count
    merged = []
    for r in rows:
        if merged and (r[1] - r[0] < min_h or merged[-1][1] - merged[-1][0] < min_h or r[0] - merged[-1][1] < 2):
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    if len(merged) < 2:
        return []
    hs = sorted(b - a for a, b in merged)
    if hs[0] < 0.6 * hs[-1]:
        return []            # rows of very different heights: one row with parts that stand out, not two rows
    return [tuple(r) for r in merged]
