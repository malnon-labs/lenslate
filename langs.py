"""Languages lenslate translates from (sources) and into (targets), and per-line language detection.

Sources: Japanese, Chinese (Simplified + Traditional), English. Targets: English, Spanish, Portuguese (Brazil),
Chinese (Simplified) (2026-11-10: Chinese and Brazilian players reading English games are the biggest audiences
after English speakers).
A line's language is recognised from its script: kana -> Japanese; Chinese characters without kana -> Chinese;
Latin letters -> English (Spanish/Portuguese lines also look Latin; they are only translated when English is a
source and the target is not a Latin-script language the line could already be in - see wants()).
Korean and Russian (2026-11-11) are sources of their own: each needs its own reader model (the main reader has
no Hangul or Cyrillic), so they are chosen alone ("Korean only"), never part of Auto; English on the same screen
is still read. No processor translator exists for them here: the language model or an online service translates.
"""
import re
import time

SOURCES = {"ja": "Japanese", "zh": "Chinese", "en": "English"}          # "Auto": read by the main reader
OWN_READER = {"ko": "Korean", "ru": "Russian"}                           # chosen alone: their own reader model
ALL_SOURCES = dict(SOURCES, **OWN_READER)
READER_OF = {"ko": "korean", "ru": "eslav"}                              # PaddleOCR reader family per language
TARGETS = {"en": "English", "es": "Spanish", "pt": "Portuguese (Brazil)", "zh": "Chinese (Simplified)"}
TARGET_CODES = {v.lower(): k for k, v in TARGETS.items()}
TARGET_CODES.update({"portuguese": "pt", "brazilian portuguese": "pt", "chinese": "zh", "simplified chinese": "zh"})

KANA = re.compile(r"[぀-ヿｦ-ﾟ]")
HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
LATIN = re.compile(r"[A-Za-zÀ-ɏ]")
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ가-힯]")


def detect(text):
    """'ja', 'zh', 'ko', 'ru', 'en' or None (numbers/symbols only)."""
    if KANA.search(text):
        return "ja"
    if HANGUL.search(text):
        return "ko"
    if HAN.search(text):
        return "zh"
    if CYRILLIC.search(text):
        return "ru"
    if len(LATIN.findall(text)) >= 2:
        return "en"
    return None


# Kanji-only text (戦闘, 休憩, 山札) is written the same in Japanese and Chinese, so it cannot be told apart on its
# own. Context decides: when Chinese is not translated it is Japanese; when both are, it is Japanese if Japanese
# (kana) was seen on screen recently. Without this, every kanji-only menu word of a Japanese game counted as
# Chinese and was skipped when only Japanese was enabled.
KANA_SEEN_FOR = 120.0    # seconds a sighting of kana keeps the screen "Japanese"
_last_kana = [0.0]


def note(text):
    """Remember that Japanese (kana) is on screen; call for every line read."""
    if KANA.search(text):
        _last_kana[0] = time.time()


# Clear signs of Chinese in kanji-only text: Chinese grammar words and pronouns Japanese does not use
ZH_MARKERS = re.compile("[吗呢们這这您吧么麼嗎們说說没沒还還让讓给給啊呀哪]")


def chinese_only_chars(text):
    """Simplified Chinese characters (设, 读, 这, 离 ...) are not in Japanese's character set (Shift-JIS)."""
    for ch in HAN.findall(text):
        try:
            ch.encode("cp932")
        except UnicodeEncodeError:
            return True
    return False


def source_of(text, enabled):
    """The source language of a line. Kanji-only text: Chinese if it shows Chinese-only characters or grammar
    words, or is a long sentence; otherwise (short words like 戦闘, 休憩) the context above decides."""
    lang = detect(text)
    if lang != "zh" or "ja" not in enabled:
        return lang
    if "zh" not in enabled:
        # only Japanese is turned on: kanji-only text is Japanese, whatever it looks like. (Seen in Risk of Rain 2
        # with "Translate from: Japanese": the rows 說明： - a 説 read as its old form - and 配送予定日：2058年5月4日
        # were taken for Chinese and got no card at all.)
        return "ja"
    if chinese_only_chars(text) or ZH_MARKERS.search(text):
        return "zh"
    if time.time() - _last_kana[0] < KANA_SEEN_FOR:
        return "ja"          # kana on this screen: a long kanji-only row (a date, a form entry) belongs to it too
    return "zh" if len(HAN.findall(text)) >= 8 else lang


def target_code(language):
    return TARGET_CODES.get(language.strip().lower(), "en")


def sources(setting):
    """'ja,zh,en' -> {'ja','zh','en'} (unknown codes dropped)."""
    return {s.strip().lower() for s in setting.split(",") if s.strip().lower() in ALL_SOURCES}


def reader_script(setting):
    """Which reader the OCR helper loads for a "Translate from" setting: "korean" / "eslav" when that language is
    chosen (it also reads English), otherwise "cjk" (Japanese, Chinese, English)."""
    enabled = sources(setting)
    return next((READER_OF[c] for c in READER_OF if c in enabled), "cjk")


def wants(text, enabled, target):
    """Should this line be translated? Its language must be an enabled source and not the target."""
    note(text)
    lang = source_of(text, enabled)
    if lang is None or lang not in enabled or lang == target:
        return False
    if lang == "en" and target != "en":
        # a Latin line in a Spanish/Portuguese game is not English: skip lines with clear Spanish/Portuguese marks
        if re.search(r"[ñáéíóúãõçâêôà¿¡]", text, re.I):
            return False
    return True


def source_left(text, tr, lang, target="en"):
    """Share of the translation still in the source script (0..1): a sign the model did not translate.
    Into Chinese, Chinese characters are the target's own script: only kana left over (Japanese) counts."""
    if target == "zh" and lang in ("ja", "en"):
        letters = [c for c in tr if c.isalpha()]
        if not HAN.search(tr) and (lang == "ja" or re.search(r"\b[a-z]{3,}", text)):
            return 1.0   # no Chinese at all: not translated (a model answered in English) - a lone name may stay
        if lang == "en" and not HAN.search(tr) and tr.strip().lower() == text.strip().lower() and re.search(r"[a-z]", text):
            return 1.0   # the English came back unchanged ("Inventory" -> "Inventory"): not translated
        if lang == "ja":
            return sum(1 for c in letters if KANA.match(c)) / max(1, len(letters))
        # English -> Chinese: Latin left over counts, except short game terms kept as they are (HP, MP, EXP, OK)
        # and names written the same in the original
        keep = {w for w in re.findall(r"[A-Za-z]+", text) if (w.isupper() and len(w) <= 4) or w[:1].isupper()}
        left = sum(len(w) for w in re.findall(r"[A-Za-z]+", tr) if w not in keep)
        return left / max(1, len(letters))
    if lang in ("ja", "zh"):
        letters = [c for c in tr if c.isalpha()]
        return sum(1 for c in letters if CJK.match(c)) / max(1, len(letters))
    if lang in ("ko", "ru"):
        script = HANGUL if lang == "ko" else CYRILLIC
        letters = [c for c in tr if c.isalpha()]
        return sum(1 for c in letters if script.match(c)) / max(1, len(letters))
    if lang == "en":   # Latin -> Latin: unchanged text means not translated
        # except a single word, which may rightly stay the same in Spanish/Portuguese (Menu, Hotel, Normal, a name):
        # before, these were rejected and asked again on every refresh. Two words ("Load Game") are not let through.
        same = tr.strip().lower() == text.strip().lower()
        return 1.0 if same and len(text) > 3 and len(text.split()) > 1 else 0.0
    return 0.0


def client_regex(enabled):
    """JavaScript/Python character class for hooks: the scripts that can hold text to translate."""
    parts = []
    if "ja" in enabled or "zh" in enabled:
        parts.append("\\u3040-\\u30ff\\u3400-\\u9fff")
    if "ko" in enabled:
        parts.append("\\uac00-\\ud7af")
    if "ru" in enabled:
        parts.append("\\u0400-\\u04ff")
    if "en" in enabled:
        parts.append("A-Za-z")
    return "[" + "".join(parts) + "]" if parts else "[\\u3040-\\u30ff\\u3400-\\u9fff]"


# Latin letters that look like Cyrillic ones. The Cyrillic reader mixes them up inside Russian words ("ЖypHал",
# "НOВИНКА": seen in Risk of Rain 2, 2026-11-12), and a word spelled in two alphabets is translated as nonsense.
_LOOKALIKE = str.maketrans("ABCEHKMOPTXaceopxy", "АВСЕНКМОРТХасеорху")
_CYR = re.compile(r"[Ѐ-ӿ]")
_LAT = re.compile(r"[A-Za-z]")
_WORD = re.compile(r"[^\W\d_]+")


# Kanji that look like katakana. Between two katakana letters they are a misread ("ブ口グ" -> ブログ); so is a
# two-letter word of one katakana and one of them ("モ力" -> モカ, Risk of Rain 2's "Mocha" came out as "Mo-ryoku").
# At the end of a longer katakana word the kanji can be real (コミュ力), so that is left alone.
_KATA_LIKE = {"力": "カ", "口": "ロ", "工": "エ", "二": "ニ", "夕": "タ", "卜": "ト", "八": "ハ", "一": "ー"}
_KATA = re.compile(r"[\u30A1-\u30FA\u30FC]")
_KATA_MID = re.compile(r"(?<=[\u30A1-\u30FA\u30FC])[力口工二夕卜八一](?=[\u30A1-\u30FA\u30FC])")
_KATA_PAIR = re.compile(r"^(?:[\u30A1-\u30FA][力口工二夕卜八]|[力口工二夕卜八][\u30A1-\u30FA])$")


_CYR_BANG = re.compile(r"(?<=[А-ЯЁ]{3})[ІIl](?![\w])")


def fix_lookalikes(text):
    """Repairs of letters read as their look-alikes from another script. Russian: words that mix Cyrillic and
    Latin letters get their Latin look-alikes turned into Cyrillic - only when every Latin letter of the word is
    such a look-alike (so "USB-кабель" or "Wi-Fi" next to Russian text is not touched). Japanese: see _KATA_LIKE."""
    if _KATA.search(text):
        text = _KATA_MID.sub(lambda m: _KATA_LIKE[m.group(0)], text)
        if _KATA_PAIR.match(text.strip()):
            text = "".join(_KATA_LIKE.get(c, c) for c in text)
    if _CYR.search(text):
        # "І" (not a Russian letter) or a Latin I / l after a Russian word in capitals is its exclamation mark
        text = _CYR_BANG.sub("!", text)
    if not _CYR.search(text) or not _LAT.search(text):
        return text

    def one(m):
        w = m.group(0)
        if not _CYR.search(w) or not _LAT.search(w):
            return w
        fixed = w.translate(_LOOKALIKE)
        return fixed if not _LAT.search(fixed) else w
    return _WORD.sub(one, text)
