"""Character-name and game-term list for lenslate (per game + global; a term like 淫紋<TAB>lewd crest works too), the way LunaTranslator/VNR handle proper nouns.

Files: ~/.config/lenslate/names/global.tsv and ~/.config/lenslate/names/<game>.tsv, one entry per line:
    蒼汰<TAB>Sota            confirmed: used for every translation of this game
    ?加奈子<TAB>Kanako       suggestion (found by `lenslate names scan` or while playing): NOT used until confirmed
    -お客<TAB>               rejected: never suggested again
    # comment
Game entries override global ones. <game> is the game's exe name in lower case without .exe (the overlay takes it
from the window class, hook mode from the XUnity URL, `lenslate names scan` from the exe in the folder).

How a confirmed name is applied:
    llm      the matching entries are added to the prompt ("蒼汰 = Sota"); only names that occur in the line, so
             the prompt stays short
    mt/sugoi the Japanese name is replaced with the English one before translating (they copy Latin words through)
The cache key includes the names used, so changing a name re-translates the lines that contain it.
"""
import json
import os
import re
import threading
import time
import urllib.request

NAMES_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "lenslate", "names")
HEADER = ("# lenslate names for {game}: original<TAB>translation. Lines starting with ? are suggestions (not used yet):\n"
          "# remove the ? to use one (or run: lenslate names ok {game} all), start a line with - to reject it.\n")

# kanji names of 2-4 characters (one kanji is nearly always a word: 客, 彼, 嫁), katakana names of 2-8
_NAME = r"([一-鿿々]{2,4}|[ァ-ヺー]{2,8})"
CANDIDATES = [
    re.compile(_NAME + r"(?=ちゃん|さん|くん|君|様|さま|先輩|先生|たん|氏)"),   # 果歩さん, マオちゃん
    re.compile(r"(?:^|[\s」』）)])" + _NAME + r"(?=[「『])"),                   # ミナ「…」 speaker prefix
    re.compile(r"【" + _NAME + r"】"),                                          # 【加奈子】
]
SEEN_TO_SUGGEST = 3     # a candidate seen this many times while playing is offered as a suggestion


def game_id(name):
    s = os.path.basename(name or "").lower()
    s = re.sub(r"\.exe$", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unknown"


# Chinese: names are 2-3 characters (surname + given name) before a title or a speaker colon, or inside 【】
_ZH = r"([\u4e00-\u9fff]{2,3})"
ZH_TITLES = ("先生|小姐|师兄|師兄|师姐|師姐|师父|師父|师妹|師妹|师弟|師弟|前辈|前輩|大人|老师|老師|公子|姑娘|大哥|大姐|"
             "哥哥|姐姐|殿下|陛下|将军|將軍|掌门|掌門|长老|長老")
ZH_CANDIDATES = [
    re.compile(_ZH + r"(?=" + ZH_TITLES + r")"),            # 李明先生, 林婉儿师姐
    re.compile(r"(?:^|[\s」』）)。！？!?…])" + _ZH + r"(?=[：:])"),     # 李明：你好 (also after a sentence)
    re.compile(r"【" + _ZH + r"】"),
]
# ordinary Japanese words that are often followed by さん/ちゃん/様 (husband-san, the customer, she ...)
JA_NOT_NAMES = {"旦那", "彼女", "彼氏", "奥様", "お客", "客様", "皆様", "皆さん", "お母", "お父", "お姉", "お兄", "母親", "父親",
                "お嬢", "嬢様", "先輩", "後輩", "店長", "店員", "社長", "部長", "課長", "先生", "神様", "王様", "姫様", "お嫁",
                "赤ちゃん", "お兄ちゃん", "お姉ちゃん", "おじ", "おば", "ママ", "パパ", "オーナー", "マスター", "シスター"}
ZH_NOT_NAMES = {"这位", "那位", "這位", "各位", "诸位", "諸位", "我们", "我們", "你们", "你們", "他们", "他們", "大家"}


def candidates(text):
    """Likely character names in a line, by the line's language (Japanese and Chinese have different signs)."""
    import langs
    lang = langs.detect(text)
    out = []
    if lang == "zh":
        for rx in ZH_CANDIDATES:
            out += [m.group(1) for m in rx.finditer(text) if m.group(1) not in ZH_NOT_NAMES]
        return out
    for rx in CANDIDATES:
        out += [m.group(1) for m in rx.finditer(text) if m.group(1) not in JA_NOT_NAMES]
    return out


def _path(game):
    return os.path.join(NAMES_DIR, game + ".tsv")


def read_file(path):
    """-> {jp: (state, en)} with state in "ok", "?", "-"."""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                state = "ok"
                if line[0] in "?-":
                    state, line = line[0], line[1:]
                parts = line.split("\t")
                jp = parts[0].strip()
                en = parts[1].split("#")[0].strip() if len(parts) > 1 else ""
                if jp:
                    out[jp] = (state if (en or state == "-") else "?", en)
    except OSError:
        pass
    return out


def append_entries(game, pairs, note=""):
    """Add suggestions/rejections ({jp: en or "-"}) to the game's file, keeping everything already there."""
    os.makedirs(NAMES_DIR, exist_ok=True)
    path = _path(game)
    have = read_file(path)
    new = [(jp, en) for jp, en in pairs.items() if jp not in have]
    if not new:
        return []
    fresh = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if fresh:
            f.write(HEADER.format(game=game))
        for jp, en in new:
            if en == "-":
                f.write("-%s\t\t# not a name%s\n" % (jp, note))
            else:
                f.write("?%s\t%s\t#%s\n" % (jp, en, note))
    return new


def confirm(game, which):
    """Remove the ? from suggestions (which = list of Japanese names, or ["all"])."""
    path = _path(game)
    try:
        lines = open(path, encoding="utf-8").read().split("\n")
    except OSError:
        return 0
    n = 0
    for i, line in enumerate(lines):
        if line.startswith("?"):
            jp = line[1:].split("\t")[0]
            if "all" in which or jp in which:
                lines[i] = line[1:]
                n += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return n


class NameBook:
    """Confirmed names of one game (+ global), reloaded when the files change, and the while-playing finder."""

    def __init__(self, game="unknown"):
        self.lock = threading.Lock()
        self.game = None
        self.entries = {}      # jp -> en, confirmed only
        self.known = set()     # every jp in the files (confirmed, suggested or rejected)
        self.counts = {}
        self.lang_of = {}      # candidate -> language of the line it was found in ("ja" / "zh")
        self.asked = set()
        self.stamp = None
        self.checked = 0.0
        self.set_game(game)

    def set_game(self, game):
        game = game or "unknown"
        if game != self.game:
            with self.lock:
                self.game, self.stamp, self.counts, self.asked = game, None, {}, set()
            self.reload(force=True)

    def _stamp(self):
        out = []
        for p in (_path("global"), _path(self.game)):
            try:
                out.append(os.stat(p).st_mtime)
            except OSError:
                out.append(None)
        return tuple(out)

    def reload(self, force=False):
        now = time.time()
        if not force and now - self.checked < 2:
            return
        self.checked = now
        st = self._stamp()
        if st == self.stamp:
            return
        merged = read_file(_path("global"))
        merged.update(read_file(_path(self.game)))
        with self.lock:
            self.stamp = st
            self.entries = {jp: en for jp, (s, en) in merged.items() if s == "ok" and en}
            self.known = set(merged)

    def matches(self, text):
        """Confirmed names in the text, longest first, without overlaps (加奈子 wins over 加奈)."""
        self.reload()
        with self.lock:
            hits = sorted((jp for jp in self.entries if jp in text), key=len, reverse=True)
            out, taken = [], text
            for jp in hits:
                if jp in taken:
                    out.append((jp, self.entries[jp]))
                    taken = taken.replace(jp, "\0")
            return out

    @staticmethod
    def key_suffix(m):
        return ";".join("%s=%s" % p for p in sorted(m))

    @staticmethod
    def prompt_hint(m):
        if not m:
            return ""
        return ("\nNames and game terms - use exactly these English translations: "
                + ", ".join("%s = %s" % p for p in m) + ".")

    @staticmethod
    def substitute(text, m):
        for jp, en in m:   # already longest first
            text = text.replace(jp, " %s " % en)
        return re.sub(r"\s+", " ", text).strip()

    def observe(self, texts):
        """Count name candidates in newly seen text; return the ones that just reached SEEN_TO_SUGGEST."""
        self.reload()
        ready = []
        with self.lock:
            for t in texts:
                lang = __import__("langs").detect(t)
                for c in candidates(t):
                    self.lang_of[c] = lang
                    if c in self.known or c in self.asked:
                        continue
                    self.counts[c] = self.counts.get(c, 0) + 1
                    if self.counts[c] >= SEEN_TO_SUGGEST:
                        self.asked.add(c)
                        ready.append(c)
        return ready


ZH_READING_PROMPT = (
    "These words come from a Chinese video game. For each word: if it is a person's or character's name, give "
    "the English spelling an official translation would use (pinyin, surname first, each part capitalized, no "
    "tone marks, e.g. 李明 -> Li Ming, 林婉儿 -> Lin Wan'er). If it is not a name (a title, role, place or "
    "ordinary word), write -.{hints}\n"
    "Reply with one line per word in the form: word<TAB>English\n\n{words}")

READING_PROMPT = (
    "These words come from a Japanese video game / visual novel. For each word: if it is a person's or "
    "character's name, give the English spelling an official translation would use (Hepburn romanization of the "
    "name as written, given names without honorifics, e.g. 蒼汰 -> Sota, 加奈子 -> Kanako). If it is not a "
    "name (a role, title, relationship or ordinary word), write -.{hints}\n"
    "Reply with one line per word in the form: word<TAB>English\n\n{words}")


# models answer with a real tab, a literal "<TAB>", "->", "=", "|" or ":" between the two columns
SEP = re.compile(r"\s*(?:<TAB>|\t|->|=|\|)\s*|:\s+")


def ask_readings(words, model, chat_url, hints=(), lang="ja"):
    """Ask the LLM for the English spelling of candidate names -> {jp: en or "-"}."""
    hint = ""
    if hints:
        hint = ("\nThe game's own internal character ids are: %s. These are usually the romanized character names: "
                "a word whose reading matches one of these ids IS a character name - use that spelling, "
                "capitalized (kaho -> Kaho)." % ", ".join(hints))
    import llm
    prompt = ZH_READING_PROMPT if lang == "zh" else READING_PROMPT
    text = llm.chat(model, [{"role": "user", "content": prompt.format(hints=hint, words="\n".join(words))}],
                    max_tokens=40 * len(words) + 50) or ""
    out = {}
    for line in text.splitlines():
        parts = re.split(SEP, line.strip(), maxsplit=1)
        if len(parts) == 2 and parts[0].strip() in words:
            en = parts[1].strip().strip("`*\"' ")
            bad = not en or en.startswith("-") or re.search(r"[぀-ヿ一-鿿]", en)
            out[parts[0].strip()] = "-" if bad else (en[0].upper() + en[1:] if en.islower() else en)
    return out


# ------------------------------------------------------------------------------------------- scan game files
SCAN_EXT = {".assets", ".resource", ".bundle", ".unity3d", ".txt", ".csv", ".json", ".ks", ".rpy", ".scn", ".tjs",
            ".dat", ".bytes", ".xml", ".yaml", ".yml", ".ini", ""}
JP_RUN = re.compile(r"[぀-ヿ一-鿿々！-～「」『』【】、。…ー～〜\w ,.!?]{4,}")
SPEAKER_ID = re.compile(r"(?:^|[\n,\t])([a-z][a-z0-9_]{2,14}),[A-Za-z0-9_]*,?[^\n]{0,30}?[぀-ゟ]")


def scan_texts(folder, max_bytes=400_000_000):
    """Japanese text runs from the game's files (Unity assets store strings as UTF-8; scripts/CSV/JSON too)."""
    for root, _dirs, files in os.walk(folder):
        if "/." in root:
            continue
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in SCAN_EXT and not re.match(r"level\d+$|sharedassets", fn):
                continue
            p = os.path.join(root, fn)
            try:
                if os.path.getsize(p) > max_bytes:
                    continue
                data = open(p, "rb").read()
            except OSError:
                continue
            for run in JP_RUN.findall(data.decode("utf-8", "ignore")):
                if re.search(r"[぀-ゟ]", run) or len(re.findall(r"[一-鿿]", run)) >= 4:
                    yield run   # Japanese (has kana) or Chinese (4+ Chinese characters)


def scan(folder, model, chat_url, min_count=3, log=print):
    """Find candidate names in a game folder and ask the LLM for their English spelling.
    Returns (game id, {jp: en or "-"}, speaker ids)."""
    import hooks
    game = hooks.game_id(folder)   # same id the game's hook uses
    import langs
    counts, ids, n, lang_of = {}, {}, 0, {}
    for run in scan_texts(folder):
        n += 1
        for c in candidates(run):
            counts[c] = counts.get(c, 0) + 1
            lang_of[c] = langs.detect(run)
        for sid in SPEAKER_ID.findall(run):
            ids[sid] = ids.get(sid, 0) + 1
    words = [w for w, k in sorted(counts.items(), key=lambda x: -x[1]) if k >= min_count][:60]
    speaker_ids = [s for s, k in sorted(ids.items(), key=lambda x: -x[1]) if k >= 5][:20]
    log("game %s: %d text runs, %d candidates (seen %d+ times), speaker ids: %s"
        % (game, n, len(words), min_count, ", ".join(speaker_ids) or "-"))
    known = set(read_file(_path(game))) | set(read_file(_path("global")))
    words = [w for w in words if w not in known]
    if not words:
        return game, {}, speaker_ids
    found = {}
    for lang in ("ja", "zh"):
        group = [w for w in words if lang_of.get(w, "ja") == lang]
        for i in range(0, len(group), 30):
            found.update(ask_readings(group[i:i + 30], model, chat_url, speaker_ids, lang=lang))
    # Second pass: speaker ids no name was matched to, against the rejected words (a small model may not know
    # that 果歩 reads "kaho", but picks it once asked about that id directly).
    used = {v.lower() for v in found.values()}
    left = [i for i in speaker_ids if i.lower() not in used]
    rejected = [w for w, v in found.items() if v == "-"]
    if left and rejected:
        for w, sid in match_ids(rejected, left, model, chat_url).items():
            found[w] = sid[0].upper() + sid[1:]
    return game, found, speaker_ids


MATCH_PROMPT = ("Japanese words from a game: {words}\nRomanized character ids from the same game: {ids}\n"
                "For each word, if its Japanese reading is one of those ids (e.g. 果歩 is read kaho, 蒼汰 is read souta), "
                "reply word<TAB>id. If none matches, reply word<TAB>-. One line per word, nothing else.")


def match_ids(words, ids, model, chat_url):
    import llm
    text = llm.chat(model, [{"role": "user", "content": MATCH_PROMPT.format(words=", ".join(words), ids=", ".join(ids))}],
                    max_tokens=30 * len(words) + 30) or ""
    out = {}
    for line in text.splitlines():
        parts = re.split(SEP, line.strip(), maxsplit=1)
        if len(parts) == 2 and parts[0].strip() in words and parts[1].strip().lower() in ids:
            out[parts[0].strip()] = parts[1].strip().lower()
    return out
