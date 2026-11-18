"""Word spaces in kana-only Japanese lines.

Retro games and children's games written without kanji put spaces between words ("なんいど を えらんでください",
seen 2026-11-18 in a WOLF RPG game). The readers drop those spaces, the words run together and every translator
guesses wrong (なんいど, "difficulty", came out as "ID"). In normal Japanese a space is rare, but in a line without any
kanji a wide empty gap between letters is a word break, so it is put back here from the line's picture.

Pure Python + numpy (used by the OCR helper; the tests run it on drawn pictures).
"""
import re

KANA = re.compile(r"[ぁ-ゟァ-ヺーｦ-ﾟ]")
HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
MIN_LETTERS = 4      # shorter lines are labels: a gap inside them is layout, not a word break
GAP_OF_H = 0.45      # a word gap is at least this share of the line height ...
GAP_OF_MEDIAN = 2.5  # ... and this many times the usual gap between letters


PUNCT = "、。，．・！？!?…「」『』（）()〜～ー"
SPACES = re.compile(r"[ 　]+")


def kana_only(text):
    """A Japanese line written in kana only (no kanji) and long enough."""
    t = text.strip()
    letters = [c for c in t if c.isalpha()]
    return (len(letters) >= MIN_LETTERS and not HAN.search(t)
            and sum(1 for c in letters if KANA.match(c)) >= 0.8 * len(letters))


def ink_runs(gray):
    """(start, end) column runs holding ink in a grey line picture (2D array), background taken from the border."""
    import numpy as np
    g = np.asarray(gray, dtype=float)
    if g.ndim != 2 or g.shape[1] < 2:
        return []
    border = np.concatenate([g[0], g[-1], g[:, 0], g[:, -1]])
    ink = (np.abs(g - np.median(border)) > 40).any(axis=0)
    runs, start = [], None
    for x, on in enumerate(ink):
        if on and start is None:
            start = x
        elif not on and start is not None:
            runs.append((start, x))
            start = None
    if start is not None:
        runs.append((start, len(ink)))
    return runs


def word_spaces(text, gray):
    """text with spaces put back at the wide gaps of its line picture, or text unchanged when it is not a kana-only
    line. The reader sometimes keeps a few of the gaps itself (as full-width spaces): those become plain spaces,
    and when the picture shows the gaps the reader's spaces are replaced by the picture's."""
    if not kana_only(text):
        return text
    own = SPACES.sub(" ", text.strip())
    found = _from_picture(SPACES.sub("", own), gray)
    return found if found is not None and found.count(" ") >= own.count(" ") else own


def _from_picture(text, gray):
    import numpy as np
    h = np.asarray(gray).shape[0]
    runs = ink_runs(gray)
    if len(runs) < 2:
        return None
    gaps = [b[0] - a[1] for a, b in zip(runs, runs[1:])]
    usual = float(np.median(gaps))
    wide = max(GAP_OF_H * h, GAP_OF_MEDIAN * max(1.0, usual))
    breaks = [i for i, g in enumerate(gaps) if g >= wide]
    if not breaks:
        return None
    # words = ink between wide gaps; the letters are shared out by each word's ink width (kana are about square)
    words, start = [], runs[0][0]
    for i in breaks:
        words.append((start, runs[i][1]))
        start = runs[i + 1][0]
    words.append((start, runs[-1][1]))
    widths = [b - a for a, b in words]
    total = float(sum(widths))
    chars = list(text)
    n = len(chars)
    cuts, acc = [], 0.0
    for w in widths[:-1]:
        acc += w
        cuts.append(int(round(n * acc / total)))
    if any(b <= a for a, b in zip([0] + cuts, cuts + [n])):
        return None          # a word with no letters: the picture and the text do not match, leave it
    pieces = ["".join(chars[a:b]) for a, b in zip([0] + cuts, cuts + [n])]
    out = pieces[0]
    for p in pieces[1:]:     # the empty room beside a comma or a bracket is no word break
        out += p if out[-1] in PUNCT or p[0] in PUNCT else " " + p
    return out
