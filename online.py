"""Online translators for lenslate: Google, Bing, Yandex (free web endpoints) and DeepL (official API, free key).

OFF by default. lenslate is built for local translation; these exist for people who do not want a local model,
or as a last fallback when the local one fails ([translator] online_fallback). Text sent here LEAVES THE
COMPUTER and goes to that company's servers, so the GUI says so wherever one can be switched on.

Google, Bing and Yandex use the same unofficial endpoints their own web pages/apps use: no account, but they can
change or rate-limit at any time (a provider that answers "too many requests" is skipped for a few minutes).
DeepL needs a free API key from deepl.com (500,000 characters a month), set in [translator] deepl_key.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import config as cfgmod

PROVIDERS = ("google", "bing", "yandex", "deepl")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"}
LANG_CODES = {"english": "en", "russian": "ru", "german": "de", "french": "fr", "spanish": "es", "italian": "it",
              "portuguese": "pt", "portuguese (brazil)": "pt", "polish": "pl", "romanian": "ro", "ukrainian": "uk", "chinese": "zh",
              "chinese (simplified)": "zh",
              "korean": "ko", "japanese": "ja", "turkish": "tr", "dutch": "nl", "indonesian": "id",
              "vietnamese": "vi", "thai": "th", "arabic": "ar"}
COOLDOWN = 300          # seconds a rate-limited provider is skipped
NET_COOLDOWN = 30       # seconds a provider is skipped after a network error (offline: no 15 s wait on every line)
_blocked = {}           # provider -> time it may be tried again
_bing = {}              # cached page tokens


class OnlineError(RuntimeError):
    pass


def lang_code(name):
    return LANG_CODES.get(name.strip().lower(), name.strip().lower()[:2])


def _req(url, data=None, headers=None, timeout=15):
    h = dict(UA)
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        if e.code in (429, 403):
            raise OnlineError("rate limited (HTTP %d)" % e.code) from e
        raise OnlineError("HTTP %d" % e.code) from e
    except OSError as e:
        raise OnlineError("network: %s" % e) from e


# lenslate's language codes -> each service's own (Chinese: Simplified for targets; a Chinese source may be either)
GOOGLE = {"zh": "zh-CN", "pt": "pt"}
BING = {"zh": "zh-Hans", "pt": "pt", "auto": "auto-detect"}


def google(text, src, dst):
    q = urllib.parse.urlencode({"client": "gtx", "sl": "auto" if src == "zh" else GOOGLE.get(src, src),
                                "tl": GOOGLE.get(dst, dst), "dt": "t", "q": text})
    body = json.loads(_req("https://translate.googleapis.com/translate_a/single?" + q))
    return "".join(p[0] for p in body[0] if p and p[0])


def _bing_tokens(refresh=False):
    if refresh or not _bing or time.time() - _bing["at"] > 1800:
        page = _req("https://www.bing.com/translator")
        try:
            ig = re.search(r'IG:"([^"]+)"', page).group(1)
            iid = re.search(r'data-iid="([^"]+)"', page).group(1)
            key, token = re.search(r'params_AbusePreventionHelper\s*=\s*\[(\d+),"([^"]+)"', page).groups()
        except AttributeError as e:
            raise OnlineError("Bing changed its page (no token found)") from e
        _bing.update(ig=ig, iid=iid, key=key, token=token, at=time.time())
    return _bing


def bing(text, src, dst):
    for attempt in (0, 1):
        t = _bing_tokens(refresh=attempt == 1)
        data = urllib.parse.urlencode({"fromLang": "auto-detect" if src == "zh" else BING.get(src, src),
                                       "to": BING.get(dst, dst), "text": text, "token": t["token"],
                                       "key": t["key"]}).encode()
        body = _req("https://www.bing.com/ttranslatev3?isVertical=1&IG=%s&IID=%s.1" % (t["ig"], t["iid"]), data,
                    {"Content-Type": "application/x-www-form-urlencoded"})
        try:
            return json.loads(body)[0]["translations"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError):
            continue   # expired token: fetch a new one once
    raise OnlineError("Bing gave no translation")


def yandex(text, src, dst):
    data = urllib.parse.urlencode({"text": text, "lang": "%s-%s" % (src, dst)}).encode()
    body = json.loads(_req("https://translate.yandex.net/api/v1/tr.json/translate?id=%s-0-0&srv=android"
                           % uuid.uuid4().hex, data, {"Content-Type": "application/x-www-form-urlencoded"}))
    if body.get("code") != 200:
        raise OnlineError("Yandex: %s" % body.get("message", body.get("code")))
    return " ".join(body.get("text", []))


def deepl(text, src, dst):
    key = cfgmod.get("translator.deepl_key")
    if not key:
        raise OnlineError("DeepL needs an API key ([translator] deepl_key; free at deepl.com)")
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"   # free keys end in :fx
    dst = {"en": "EN-US", "pt": "PT-BR", "zh": "ZH-HANS"}.get(dst, dst.upper())
    data = json.dumps({"text": [text], "source_lang": src.upper(), "target_lang": dst}).encode()
    body = json.loads(_req("https://%s/v2/translate" % host, data,
                           {"Content-Type": "application/json", "Authorization": "DeepL-Auth-Key " + key}))
    return body["translations"][0]["text"]


FUNCS = {"google": google, "bing": bing, "yandex": yandex, "deepl": deepl}


def translate(text, provider=None, src=None, dst=None):
    """Translate one text with an online provider. Raises OnlineError (rate limit, network, bad answer)."""
    provider = provider or cfgmod.get("translator.online_provider")
    if provider not in FUNCS:
        raise OnlineError("unknown online translator %r" % provider)
    if _blocked.get(provider, 0) > time.time():
        raise OnlineError("%s is rate limited or unreachable; skipped for a while" % provider)
    dst = dst or lang_code(cfgmod.get("translator.language"))
    if src is None:
        import langs
        src = langs.source_of(text, langs.sources(cfgmod.get("translator.sources"))) or "auto"
    try:
        out = FUNCS[provider](text, src, dst).strip()
    except OnlineError as e:
        if "rate limited" in str(e):
            _blocked[provider] = time.time() + COOLDOWN
        elif str(e).startswith("network"):
            _blocked[provider] = time.time() + NET_COOLDOWN
        raise
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:   # the service changed its answer
        raise OnlineError("%s gave an answer lenslate cannot read (%s)" % (provider, type(e).__name__)) from e
    if not out:
        raise OnlineError("%s returned nothing" % provider)
    return out
