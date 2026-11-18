"""Seed packs: ready-made translations of menu / UI words and common short lines, per language pair.

Why: the small processor translators get lone words wrong (quickmt en->zh: Inventory -> 产品目录, Equip -> 设备展示,
Continue -> 继续阅读) because a single word has no context. A menu word has one usual translation in games, so a
curated list fixes it for every translator, instantly, without a model call.

Files: seeds/<src>-<tgt>.tsv shipped with lenslate, and the same names in ~/.local/share/lenslate/seeds (packs you
add or download; their lines win over the shipped ones). Format: `original<TAB>translation`, one per line;
blank lines and lines starting with # are ignored.

Matching is on the WHOLE line only (never inside a sentence), so it helps menus and labels, not dialogue. The
comparison ignores letter case, repeated spaces, full-width/half-width forms and a trailing colon or "...";
those are put back on the translation (INVENTORY -> INVENTÁRIO, "Volume:" -> "音量："). Your own corrections
(Fix translations page) always win over a pack line.
"""
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DIRS = [os.path.join(HERE, "seeds"),
        os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "lenslate", "seeds")]

TAIL = re.compile(r"\s*([:：]|\.\.\.|…|！|!|\?|？)$")
LATIN_TARGETS = {"en", "es", "pt"}
_packs = {}   # (src, tgt) -> (mtimes, {key: translation})


def norm(text, tail=True):
    """Comparison form: NFKC (full-width -> normal), single spaces, case folded; tail=True also drops a trailing
    colon / ellipsis / ! / ?."""
    t = unicodedata.normalize("NFKC", text)
    t = re.sub(r"\s+", " ", t).strip()
    if tail:
        t = TAIL.sub("", t)
    return t.casefold()


def files(src, tgt):
    name = "%s-%s.tsv" % (src, tgt)
    return [os.path.join(d, name) for d in DIRS]


def read(path):
    """{key: translation} from one pack file ({} if missing). Two keys per line: the exact form ("=" + text with
    its end mark, translation as written) and the bare form (no end mark; the translation's end mark removed too,
    lookup puts the original's back). A line written without an end mark owns the bare form."""
    out, bare_owner = {}, {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip() or line.lstrip().startswith("#") or "\t" not in line:
                    continue
                orig, tr = line.split("\t", 1)
                orig, tr = orig.strip(), tr.strip()
                if orig and tr:
                    out["=" + norm(orig, tail=False)] = tr
                    k, plain = norm(orig), not TAIL.search(unicodedata.normalize("NFKC", orig).strip())
                    if plain or not bare_owner.get(k):
                        out[k] = TAIL.sub("", tr).lstrip("¿¡") if not plain else tr
                        bare_owner[k] = plain
    except OSError:
        pass
    return out


def pack(src, tgt):
    """The merged pack for a pair, re-read when one of its files changes (one stat() per file)."""
    paths = files(src, tgt)
    stamp = []
    for p in paths:
        try:
            stamp.append(os.stat(p).st_mtime)
        except OSError:
            stamp.append(None)
    cached = _packs.get((src, tgt))
    if cached and cached[0] == stamp:
        return cached[1]
    data = {}
    for p in paths:            # later folders (the user's) override earlier ones (shipped)
        data.update(read(p))
    _packs[(src, tgt)] = (stamp, data)
    return data


# a label followed by its value: "Playtime 6:57:43", "Discovered 539/596", "Ascensions 9/50", "Volume 80%"
NUM_TAIL = re.compile(r"^(.*?[^\W\d_][^\d]*?)\s*[:：]?\s+([\d][\d\s:/.,%x×+\-]*)$")


def lookup(text, src, tgt):
    """The pack translation of a whole line, adapted to its shape, or None. A line that is a pack label followed
    by a number ("Playtime 6:57:43") gets the label's translation with the number kept."""
    if not src or not tgt or src == tgt:
        return None
    tr = _lookup(text, src, tgt)
    if tr is None:
        m = NUM_TAIL.match(unicodedata.normalize("NFKC", text).strip())
        if m:
            label = _lookup(m.group(1), src, tgt)
            if label is not None:
                tr = label.rstrip(":： ") + " " + m.group(2).strip()
    return tr


def _lookup(text, src, tgt):
    p = pack(src, tgt)
    s = unicodedata.normalize("NFKC", text).strip()
    tr = p.get("=" + norm(text, tail=False))
    exact = tr is not None
    if not exact:
        tr = p.get(norm(text))
    if tr is None:
        return None
    m = TAIL.search(s)
    if m and not exact:
        end = m.group(1)
        if tgt == "zh":
            end = {":": "：", "!": "！", "?": "？", "...": "…"}.get(end, end)
        elif end in ("：", "！", "？"):
            end = {"：": ":", "！": "!", "？": "?"}[end]
        if not tr.endswith(end):
            tr += end
        if tgt == "es" and end in ("?", "!") and tr[:1] not in "¿¡":
            tr = {"?": "¿", "!": "¡"}[end] + tr      # Spanish opens questions and exclamations too
    letters = [c for c in s if c.isalpha()]
    if tgt in LATIN_TARGETS and len(letters) >= 2 and all(c.isupper() for c in letters):
        tr = tr.upper()      # INVENTORY -> INVENTÁRIO
    return tr


def available():
    """[(src, tgt, number of lines)] of every pack found."""
    pairs = set()
    for d in DIRS:
        try:
            for fn in os.listdir(d):
                m = re.fullmatch(r"([a-z]+)-([a-z]+)\.tsv", fn)
                if m:
                    pairs.add((m.group(1), m.group(2)))
        except OSError:
            pass
    return sorted((s, t, sum(1 for k in pack(s, t) if k.startswith("="))) for s, t in pairs)
