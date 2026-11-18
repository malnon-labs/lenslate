"""RPG Maker MV / MZ support: text handling shared by the in-game plugin (via `lenslate serve`) and pre-translation.

The plugin (hooks/rpgm/Lenslate.js) sends the game's raw text, exactly as the game stores it:
  - a message box: all its lines joined with "\\n" (Game_Message.allText()), escape codes included
  - a choice, a speaker name (MZ name box), a database text (item name, skill description, menu word ...)
split() turns raw text into segments: literal pieces kept as they are (escape codes, line breaks) and pieces to
translate (cache keys). Pre-translation (extract() + the same split()) produces the very same keys, so the
plugin later finds every line in the cache.

Escape codes: \\N[n] \\P[n] (names), \\V[n] (variables), \\I[n] (icons), \\G (currency) stay in the translation as
placeholders <1>, <2> ... and are put back afterwards. Codes at the start or end of the text (a coloured speaker
line, a wait at the end) are kept around the translation. Other codes inside a sentence (colour changes, waits,
speed) are dropped: a translation cannot keep a colour on the "same" word.
"""
import glob
import json
import os
import re

# Ren'Py: {tags} (formatting, pauses) and [variables]; variables are kept as placeholders, tags inside a sentence
# are dropped (a pause or italics can't be placed reliably in the translation), tags at the edges stay.
RENPY_CODE = re.compile(r"\{[^{}]*\}|\[[^\[\]]*\]")
RENPY_KEEP = re.compile(r"\[[^\[\]]+\]")
CODE = re.compile(r"\\(?:[A-Za-z]+\[[^\]]*\]|[A-Za-z]+<[^>]*>|[{}!.|^$<>GgCcIiNnVvPp](?![a-zA-Z]))|\\\\")
KEEP = re.compile(r"\\(?:[NnPpVvIi]\[[^\]]*\]|[Gg](?![a-zA-Z]))")
PLACE = re.compile(r"<(\d+)>")
JP = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")


def translatable(text):
    """In a language lenslate translates (config [translator] sources) and not already in the target language."""
    import config as cfgmod
    import langs
    return langs.wants(text, langs.sources(cfgmod.get("translator.sources")),
                       langs.target_code(cfgmod.get("translator.language")))


def _strip_edges(text, CODE=CODE, KEEP=KEEP):
    """-> (prefix codes, inner text, suffix codes). Only decoration codes (colour, wait ...) and spaces count as
    edges; name/variable/icon codes stay inside, where they become placeholders."""
    def edge_len(t, rev=False):
        n = 0
        while True:
            rest = t[:len(t) - n] if rev else t[n:]
            if not rest:
                return n
            if (rest[-1] if rev else rest[0]).isspace():
                n += 1
                continue
            found = None
            for m in CODE.finditer(rest):
                if (m.end() == len(rest)) if rev else (m.start() == 0):
                    found = m
            if found is None or KEEP.fullmatch(found.group(0)):
                return n
            n += len(found.group(0))
    a = edge_len(text)
    pre, rest = text[:a], text[a:]
    b = edge_len(rest, rev=True)
    return pre, rest[:len(rest) - b], rest[len(rest) - b:]


def protect(text, CODE=CODE, KEEP=KEEP):
    """Inner text -> (key with <n> placeholders, [codes]). Unkept inline codes are dropped."""
    kept = []

    def sub(m):
        if KEEP.fullmatch(m.group(0)):
            kept.append(m.group(0))
            return "<%d>" % len(kept)
        return ""
    key = CODE.sub(sub, text)
    key = re.sub(r"\s*\n\s*", " ", key).strip()
    return key, kept


def restore(translation, kept):
    used = set()

    def sub(m):
        i = int(m.group(1))
        if 1 <= i <= len(kept):
            used.add(i)
            return kept[i - 1]
        return ""
    out = PLACE.sub(sub, translation)
    missing = [kept[i - 1] for i in range(1, len(kept) + 1) if i not in used and not kept[i - 1].startswith("\\I")]
    return (out + " " + " ".join(missing)).strip() if missing else out


def _speaker(line):
    """An MV speaker line: short, no sentence punctuation, often coloured: '\\c[2]アオイ\\c[0]'."""
    pre, inner, suf = _strip_edges(line)
    plain = CODE.sub("", inner).strip()
    if 0 < len(plain) <= 12 and JP.search(plain) and not re.search(r"[。、！？!?…「」『』（）]", plain):
        return pre, plain, suf
    return None


def split(raw, kind="message", engine="rpgm"):
    """Raw game text -> list of segments: ("lit", text) or ("tr", key, kept_codes)."""
    if engine == "renpy":
        # "[[" / "{{" are literal brackets in Ren'Py: hide them from the tag scanner, show them as plain brackets
        # to the translator, and escape any bracket in the translation again before it goes back to the game
        hidden = raw.replace("[[", "\ue000").replace("{{", "\ue001")
        pre, inner, suf = _strip_edges(hidden, RENPY_CODE, RENPY_KEEP)
        key, kept = protect(inner, RENPY_CODE, RENPY_KEEP)
        unhide = lambda t: t.replace("\ue000", "[[").replace("\ue001", "{{")
        if key and translatable(key):
            return [("lit", unhide(pre)), ("tr", key.replace("\ue000", "[").replace("\ue001", "{"), kept, "renpy"),
                    ("lit", unhide(suf))]
        return [("lit", raw)]
    segs = []
    if kind == "message" and "\n" in raw:
        first, body = raw.split("\n", 1)
        sp = _speaker(first)
        if sp and body.strip():
            pre, name, suf = sp
            segs += [("lit", pre), ("tr", name, []), ("lit", suf + "\n")]
            raw = body
    pre, inner, suf = _strip_edges(raw)
    key, kept = protect(inner)
    segs.append(("lit", pre))
    if key and translatable(key):
        segs.append(("tr", key, kept))
    else:
        segs.append(("lit", inner))
    segs.append(("lit", suf))
    return segs


def keys(raw, kind="message", engine="rpgm"):
    return [s[1] for s in split(raw, kind, engine) if s[0] == "tr"]


def assemble(segs, translations):
    """translations: {key: text}. Returns the translated raw text, or None if a key is missing."""
    out = []
    for s in segs:
        if s[0] == "lit":
            out.append(s[1])
        else:
            tr = translations.get(s[1])
            if tr is None:
                return None
            if len(s) > 3 and s[3] == "renpy":   # brackets the translator wrote are text, not tags/variables
                tr = re.sub(r"(?<!<)\[", "[[", PLACE.sub(lambda m: "\ue002%s\ue003" % m.group(1), tr))
                tr = tr.replace("{", "{{").replace("\ue002", "<").replace("\ue003", ">")
            out.append(restore(tr, s[2]))
    return "".join(out)


# ------------------------------------------------------------------------------------------------ extraction
def rpgm_plain(raw):
    return CODE.sub("", raw)


def data_dir(game):
    for d in (os.path.join(game, "www", "data"), os.path.join(game, "data")):
        if os.path.exists(os.path.join(d, "System.json")):
            return d
    return None


def js_dir(game):
    for d in (os.path.join(game, "www", "js"), os.path.join(game, "js")):
        if os.path.exists(os.path.join(d, "plugins.js")):
            return d
    return None


def engine(game):
    jd = js_dir(game)
    if not jd:
        return None
    return "mz" if os.path.exists(os.path.join(jd, "rmmz_core.js")) else "mv"


def _load(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _event_texts(cmds):
    """Messages (lines joined like Game_Message.allText), choices, speaker names, scroll texts."""
    out = []
    msg, scroll = None, None
    for c in cmds or []:
        code, p = c.get("code"), c.get("parameters") or []
        if code != 401 and msg is not None:
            out.append(("message", "\n".join(msg)))
            msg = None
        if code != 405 and scroll is not None:
            out.append(("message", "\n".join(scroll)))
            scroll = None
        if code == 101:
            msg = []
            if len(p) > 4 and isinstance(p[4], str) and p[4]:
                out.append(("name", p[4]))           # MZ name box
        elif code == 401 and msg is not None:
            msg.append(p[0] if p else "")
        elif code == 105:
            scroll = []
        elif code == 405 and scroll is not None:
            scroll.append(p[0] if p else "")
        elif code == 102 and p:
            out += [("choice", ch) for ch in p[0]]
        elif code == 402 and len(p) > 1:            # "when [choice]" branch label = same text as the choice
            pass
    if msg:
        out.append(("message", "\n".join(msg)))
    if scroll:
        out.append(("message", "\n".join(scroll)))
    return out


DB_FIELDS = {
    "Actors.json": ("name", "nickname", "profile"),
    "Classes.json": ("name",),
    "Skills.json": ("name", "description", "message1", "message2"),
    "Items.json": ("name", "description"),
    "Weapons.json": ("name", "description"),
    "Armors.json": ("name", "description"),
    "Enemies.json": ("name",),
    "States.json": ("name", "message1", "message2", "message3", "message4"),
}


def extract(game):
    """Every translatable text of an RPG Maker MV/MZ game -> list of (kind, raw text), unique, in game order."""
    d = data_dir(game)
    if not d:
        raise RuntimeError("no RPG Maker MV/MZ data folder in %s" % game)
    out = []
    for fn, fields in DB_FIELDS.items():
        for obj in _load(os.path.join(d, fn)) or []:
            if obj:
                out += [("text", obj[f]) for f in fields if isinstance(obj.get(f), str) and obj[f]]
    sysj = _load(os.path.join(d, "System.json")) or {}
    out += [("text", sysj.get("gameTitle", ""))]
    terms = sysj.get("terms", {})
    for k in ("basic", "commands", "params"):
        out += [("text", t) for t in terms.get(k, []) if isinstance(t, str) and t]
    out += [("text", t) for t in (terms.get("messages") or {}).values() if isinstance(t, str) and t]
    for k in ("elements", "skillTypes", "weaponTypes", "armorTypes", "equipTypes"):
        out += [("text", t) for t in sysj.get(k, []) if isinstance(t, str) and t]
    for ce in _load(os.path.join(d, "CommonEvents.json")) or []:
        if ce:
            out += _event_texts(ce.get("list"))
    for ev in _load(os.path.join(d, "Troops.json")) or []:
        for p in (ev or {}).get("pages", []) or []:
            out += _event_texts(p.get("list"))
    for f in sorted(glob.glob(os.path.join(glob.escape(d), "Map[0-9]*.json"))):   # folder names like "[Kimochi] ..."
        m = _load(f) or {}
        if m.get("displayName"):
            out.append(("text", m["displayName"]))
        for ev in m.get("events") or []:
            for p in (ev or {}).get("pages", []) or []:
                out += _event_texts(p.get("list"))
    seen, uniq = set(), []
    for kind, raw in out:
        if raw and translatable(rpgm_plain(raw)) and (kind, raw) not in seen:
            seen.add((kind, raw))
            uniq.append((kind, raw))
    return uniq
