"""OCR + text-cache translation path for lenslate (no Qt widgets here, so it can be tested offline).

Flow per refresh:
  1. grid():          tiny grayscale grid of the captured region (CELL px cells)
  2. compare with the last HISTORY frames; the closest one is the base. Unchanged -> reuse its cards.
  3. changed_rects(): areas whose cells changed (grown to cover any old card they touch)
  4. OcrClient.read(): RapidOCR (PP-OCRv6 small) on just those areas (helper process in the engine environment)
  5. merge_rows() + group_blocks(): fragments -> lines -> text blocks (a dialogue box = one block)
  6. TextCache: exact original text -> translation; only misses go to translate_batch()
"""
import itertools
import json
import math
import os
import queue
import re
import subprocess
import threading
import time
import urllib.request

import numpy as np

import config as cfgmod
import seeds
import kanaspace
import langs
import names as nm

CELL = 16          # change-detection cell size in captured pixels (about one character)
SAMPLES = 4        # each cell is compared as SAMPLES x SAMPLES averaged pixels
CELL_THRESH = 6.0  # mean abs grey difference (0-255) for a cell to count as changed
FULL_FRACTION = 0.5  # more than this share of the region changed -> just read the whole region
HISTORY = 5        # frames remembered for "back to a screen seen a moment ago"

# characters that mark text worth translating (kana, kanji, half-width katakana, hangul)
SOURCE_CHARS = re.compile(r"[぀-ヿ㐀-鿿豈-﫿ｦ-ﾟ가-힯]")
NO_SPACE_CHARS = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uff66-\uff9f]")   # scripts written without spaces (Korean has them)


# ------------------------------------------------------------------------------ OCR helper
def engine_python(here, old_venv):
    """Python of the shared engine environment (OCR + CPU translators): the installed one in
    ~/.local/share/lenslate/engine, a development one next to the code, or the older per-helper venvs."""
    for d in (os.path.join(cfgmod.DATA_DIR, "engine"), os.path.join(here, "engine"), os.path.join(here, old_venv)):
        py = os.path.join(d, "bin", "python")
        if os.path.exists(py):
            return py
    return os.path.join(cfgmod.DATA_DIR, "engine", "bin", "python")


class HelperClient:
    """Talks to a helper process in the engine environment (one JSON line per request). Thread-safe; restarts it
    once if it died.
    - Every request carries an "id" that the helper echoes; a line that is not the answer to the current request
      (library noise, a late answer) is skipped instead of being taken for it.
    - Answers have a time limit (TIMEOUT; START_TIMEOUT while the helper loads its models). A helper that does not
      answer in time is killed, so a hang can never block the caller (and everything waiting on the lock) for good.
    - After a crash, starting again waits a little longer each time (2 s, 4 s ... 60 s), so a helper that dies on
      every start does not reload its models on every refresh."""
    VENV, SCRIPT, NAME = "ocr-venv", "ocr_server.py", "OCR"
    TIMEOUT = 120          # s per request (a careful read of a whole 4K screen on a slow processor fits easily)
    START_TIMEOUT = 600    # s to load the models (the very first start may download a model)
    _ids = itertools.count(1)

    def __init__(self, here, debug=False, env=None):
        """env: settings for this helper only (e.g. {"LENSLATE_OCR_GPU": "off"} while measuring). They go to the
        helper's own environment; os.environ is never changed, so the GUI's config.get() keeps reading the file."""
        self.cmd = [engine_python(here, self.VENV), "-I", os.path.join(here, self.SCRIPT)]
        self.debug = debug
        self.extra_env = dict(env or {})
        self.proc = None
        self.lines = None        # queue of the helper's stdout lines (filled by a reader thread; None = it closed)
        self.lock = threading.Lock()
        self.epoch = 0           # changes on every stop(): a call in flight then knows it was stopped on purpose
        self.fails = 0           # crashes in a row (for the restart back-off)
        self.retry_at = 0.0

    def available(self):
        return all(os.path.exists(p) for p in self.cmd[::2])

    def _start(self):
        if self.proc is not None and self.proc.poll() is None:
            return
        if self.proc is not None:
            self.stop()      # it exited: reap it
        wait = self.retry_at - time.time()
        if wait > 0:
            raise RuntimeError("%s helper crashed; trying again in %d s" % (self.NAME, math.ceil(wait)))
        self.started_env = self._env()
        proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                env=self._launch_env(self.started_env),
                                stderr=None if self.debug else subprocess.DEVNULL,
                                text=True, encoding="utf-8", bufsize=1)
        lines = queue.Queue()

        def pump():
            try:
                for ln in proc.stdout:
                    lines.put(ln)
            except (OSError, ValueError):
                pass
            lines.put(None)
        threading.Thread(target=pump, daemon=True, name="lenslate-%s-out" % self.NAME).start()
        self.proc, self.lines = proc, lines
        while True:      # {"ready": true} once the models are loaded
            ln = self._next_line(self.START_TIMEOUT)
            if ln is None:
                self._crashed()
                raise RuntimeError(self.NAME + " helper failed to start")
            try:
                if json.loads(ln).get("ready"):
                    return
            except (ValueError, AttributeError):
                pass         # an old helper or a library printing something: wait for the ready line

    def _next_line(self, timeout):
        """The helper's next stdout line, or None if it closed. Kills the helper if nothing comes in time."""
        try:
            return self.lines.get(timeout=timeout)
        except queue.Empty:
            self.stop()
            raise RuntimeError("%s helper did not answer within %d s (stopped; it starts again on the next request)"
                               % (self.NAME, timeout)) from None

    def _crashed(self):
        self.stop()
        self.fails += 1
        self.retry_at = time.time() + min(60, 2 ** self.fails)

    def _env(self):
        env = dict(os.environ, **self._own_env())
        env.update(self.extra_env)
        return env

    def _own_env(self):
        """The settings this helper reads from its environment (from config.toml)."""
        script = langs.reader_script(cfgmod.get("translator.sources"))
        return {"LENSLATE_OCR_THREADS": str(cfgmod.get("ocr.threads")), "LENSLATE_OCR_GPU": cfgmod.get("ocr.gpu"),
                # Korean / Russian: their own PaddleOCR reader; Ultrafast (meikiocr) reads Japanese only
                "LENSLATE_OCR_SCRIPT": script,
                "LENSLATE_OCR_READER": "meiki" if (cfgmod.get("ocr.reading") == "ultrafast" and script == "cjk")
                else "paddle"}

    def _launch_env(self, env):
        """The environment the helper really starts with (the OCR helper may swap the GPU for the processor)."""
        return env

    def warm(self):
        with self.lock:
            self._start()

    def follow_config(self):
        """Settings that need a helper restart (GPU mode, threads) changed: stop it; the next read starts it anew.
        Returns True (restarted), False (nothing to do) or None (the helper is busy: ask again later). It never
        waits for the helper, so the overlay's main thread cannot freeze on it."""
        if not self.lock.acquire(blocking=False):
            return None
        try:
            if self.proc is not None and getattr(self, "started_env", None) is not None:
                keys = ("LENSLATE_OCR_GPU", "LENSLATE_OCR_THREADS", "LENSLATE_OCR_READER", "LENSLATE_OCR_SCRIPT")
                if any(self._env().get(k) != self.started_env.get(k) for k in keys):
                    self.stop()
                    return True
            return False
        finally:
            self.lock.release()

    def read(self, path, scale=1.0):  # (OcrClient)
        """Returns ([{"box": [x1,y1,x2,y2], "text", "score"}], seconds). Boxes are in the original image's pixels."""
        resp = self._call({"path": path, "scale": scale})
        return resp["lines"], resp.get("secs", 0)

    def read_lines(self, path, boxes):
        """Recognition of known line boxes (no detection): returns (lines, seconds).
        Latin lines only need the slower full re-read when English is translated (a source, and not the target)."""
        latin = "en" in langs.sources(cfgmod.get("translator.sources")) and \
            langs.target_code(cfgmod.get("translator.language")) != "en"
        resp = self._call({"op": "read_lines", "path": path, "boxes": boxes, "latin_matters": latin})
        return resp["lines"], resp.get("secs", 0)

    def detect(self, path, side=1280):
        """Fast text detection only (no reading): returns ([[x1,y1,x2,y2]], seconds)."""
        resp = self._call({"op": "detect", "path": path, "side": side})
        return resp["boxes"], resp.get("secs", 0)

    def _call(self, req):
        with self.lock:
            for attempt in (0, 1):
                epoch = self.epoch
                rid = next(self._ids)
                try:
                    self._start()
                    epoch = self.epoch
                    self.proc.stdin.write(json.dumps(dict(req, id=rid)) + "\n")
                    self.proc.stdin.flush()
                    while True:
                        line = self._next_line(self.TIMEOUT)
                        if line is None:
                            raise BrokenPipeError(self.NAME + " helper exited")
                        try:
                            resp = json.loads(line)
                        except ValueError:
                            continue                     # not an answer (a library printed something)
                        if isinstance(resp, dict) and resp.get("id", rid) == rid:
                            break                        # (an answer without "id" = an older helper: take it)
                except (BrokenPipeError, OSError):
                    if self.epoch != epoch:              # stop() was called while this request ran: no restart
                        raise RuntimeError(self.NAME + " helper was stopped") from None
                    self._crashed()
                    if attempt:
                        raise RuntimeError(self.NAME + " helper keeps dying") from None
                    self.retry_at = 0.0                  # the first restart is immediate (the helper may just be old)
                    continue
                self.fails = 0
                if "error" in resp:
                    raise RuntimeError(self.NAME + ": " + resp["error"])
                return resp

    def stop(self):
        """Kill the helper and reap it. Safe from any thread, also while a request runs (that request then fails with
        "helper was stopped" instead of starting the helper again)."""
        proc, self.proc = self.proc, None
        self.epoch += 1
        if proc is not None:
            try:
                proc.kill()
                proc.wait(5)
            except (OSError, subprocess.SubprocessError):
                pass
            for f in (proc.stdin, proc.stdout):
                try:
                    f.close()
                except (OSError, ValueError):
                    pass


OCR_GPU_NEED_MB = {"reader": 400, "all": 1300}   # measured helper use per [ocr] gpu mode (mobile models, 2026-11-10)
LLM_NEED_MB = 1700                                 # Gemma 4 E2B in the built-in runner (num_ctx 4096)


def gpu_free_mb():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.split()
        return int(out[0]) if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class OcrClient(HelperClient):
    """The OCR helper. Reading on the graphics card ([ocr] gpu) is used only when enough GPU memory is free at the
    moment the helper starts (rule since 2026-11-10); otherwise the processor reads and on_notice says why. It is
    checked again whenever the helper starts again (lenslate restart, or a change of the setting)."""
    on_notice = None

    def _launch_env(self, env):
        want = env.get("LENSLATE_OCR_GPU", "off")
        self.gpu_note = None
        if want == "off":
            return env
        free = gpu_free_mb()
        if free is None:
            self.gpu_note = ("Reading on the graphics card needs an NVIDIA card (nvidia-smi was not found); "
                             "the processor reads instead.")
        else:
            need = OCR_GPU_NEED_MB.get(want, 1600) + 300
            if cfgmod.get("translator.kind") == "llm" and not _llm_loaded():
                need += LLM_NEED_MB   # leave room for the language model that starts next
            if free < need:
                self.gpu_note = ("Only %.1f GB of graphics memory is free (reading on the graphics card needs about "
                                 "%.1f GB here), so the processor reads for now. It tries the graphics card again "
                                 "the next time lenslate starts." % (free / 1024, need / 1024))
        if self.gpu_note is None:
            return env
        if self.on_notice:
            self.on_notice(self.gpu_note)
        return dict(env, LENSLATE_OCR_GPU="off")


def _llm_loaded():
    """lenslate's built-in model runner is already running (its GPU memory is already counted as used)."""
    try:
        import llm
        pid = llm._read_pid()
        return bool(pid) and llm._is_runner(pid)   # a stale PID file may name another process by now
    except ImportError:
        pass
    return False


class MtClient(HelperClient):
    """mt_server.py in mt-venv: a CTranslate2 translation model (quickmt or Sugoi) on the CPU, no GPU memory."""
    VENV, SCRIPT, NAME = "mt-venv", "mt_server.py", "MT"

    def __init__(self, here, debug=False, model=None, env=None):
        super().__init__(here, debug, env)
        self.model = model

    def available(self):
        return super().available() and os.path.exists(os.path.join(self.model, "model.bin"))

    def _own_env(self):   # read by mt_server.py
        return {"LENSLATE_MT_MODEL": self.model, "LENSLATE_MT_THREADS": str(cfgmod.get("translator.mt_threads")),
                "LENSLATE_MT_TARGET_TAG": MT_TARGET_TAGS.get(os.path.basename(self.model), "")}

    def translate(self, texts):
        return self._call({"texts": list(texts)})["out"]


# ------------------------------------------------------------------------- lines -> blocks
def _join(a, b):
    """Join two text pieces: no space between CJK characters, a space between words otherwise."""
    if not a or not b:
        return a + b
    if NO_SPACE_CHARS.match(a[-1]) or NO_SPACE_CHARS.match(b[0]) or a[-1] in "、。・「」『』！？" or b[0] in "、。・「」『』！？":
        return a + b
    return a + " " + b


_GROW_STRIP = re.compile(r"[\s…・。、.,!?！？~～\-ー]+$")


def grows(old, new):
    """new is old typed out further (typewriter text): old's text, minus its last character (often caught half-drawn)
    and trailing punctuation, starts new, and new is longer."""
    a = _GROW_STRIP.sub("", re.sub(r"\s+", "", old))
    b = re.sub(r"\s+", "", new)
    if len(a) < 2 or len(b) <= len(a):
        return False
    return b.startswith(a[:-1] if len(a) >= 4 else a)


def plausible(lines, height):
    """Drop OCR 'text' that is really artwork or a detector mistake: a character sprite read as one 690 px tall "场",
    a flying playing card read as "回" (real text taller than 15% of the region has several characters, a logo),
    and vertical boxes stacked across horizontal lines."""
    flat = sorted(l["box"][3] - l["box"][1] for l in lines if (l["box"][3] - l["box"][1]) <= (l["box"][2] - l["box"][0]))
    typical = flat[len(flat) // 2] if flat else None
    out = []
    for ln in lines:
        w, h = ln["box"][2] - ln["box"][0], ln["box"][3] - ln["box"][1]
        n = len(re.sub(r"\s", "", ln["text"]))
        if h > 0.4 * height or (h > max(120, 0.15 * height) and n <= 3):
            continue
        # a tall narrow "vertical line" among horizontal text is the detector stacking the first characters of
        # several lines (read top-down as nonsense like かさこのす)
        if typical and h > 1.5 * w and h > 2 * typical:
            continue
        # one lone character the reader itself is unsure about is an icon or a key hint, not text (the Q / E key
        # pictures beside Risk of Rain 2's tabs came back as "日" with scores 0.33-0.67 -> cards saying "day")
        if n == 1 and ln.get("score", 1.0) < LONE_CHAR_SCORE:
            continue
        # a few characters the reader does not believe in itself: pictures read as text (a row of item icons came
        # back as "*日○曰" with score 0.46 -> a card saying "Nichi wa"; up to JUNK_CHARS characters)
        if n <= JUNK_CHARS and ln.get("score", 1.0) < JUNK_SCORE:
            continue
        out.append(ln)
    return out


LONE_CHAR_SCORE = 0.7
JUNK_SCORE = 0.5
JUNK_CHARS = 8       # (the game's drawn logo came back as "上HRINE", six characters at 0.45)
# two words glued without a space where a small Cyrillic letter is followed by a capital one: two tabs or buttons
# read as one line ("Статистика профиляИстория попыток", Risk of Rain 2's borderless Russian tabs). Russian text
# never has that inside a word.
_GLUED_CYR = re.compile(r"(?<=[а-яё])(?=[А-ЯЁ])")
_TOUCHING = re.compile(r"(?<=[\]】」』》〉])(?=[\[【「『《〈])")


_GLUED = re.compile(r"^\[[^\]]{1,30}\](?=[^\W\d_])")   # ASCII brackets only: 「はい」と答えた and 【重要】お知らせ are text


_OPEN, _CLOSE = "[【", "]】"


def strip_stray_brackets(text):
    """A lone square bracket at the very start or end of a line is the edge of a button or tab read as a character
    ("НОВИНКА]", "[モンスター", "Шпора Фарадея]" in Risk of Rain 2): it is taken off. Brackets that come in pairs
    ("[E] Interact", "【重要】") are text and stay."""
    t = text.strip()
    if len(t) > 1 and t[-1] in _CLOSE and not any(c in t for c in _OPEN):
        t = t[:-1].rstrip()
    if len(t) > 1 and t[0] in _OPEN and not any(c in t for c in _CLOSE):
        t = t[1:].lstrip()
    return t or text


def _text_width(t):
    return sum(2 if ord(c) > 0x2E7F else 1 for c in t) or 1


def split_touching(lines):
    """One box holding two bracketed items side by side ("[アイテム&装備][モンスター": two tabs whose borders were
    read as brackets) becomes one line per item, the box shared out by the width of the text."""
    out = []
    for ln in lines:
        text = ln["text"]
        # the same row read without the second opening bracket ("[アイテム&装備]モンスター"): a bracketed item
        # at the start with a word glued to it (a space after the bracket - "[E] Interact" - is a key and its label)
        if text[:1] == "[":
            text = _GLUED.sub(lambda m: m.group(0) + "\x00", text, count=1)
        text = _GLUED_CYR.sub("\x00", text)
        parts = [p for part in text.split("\x00") for p in _TOUCHING.split(part) if p.strip()]
        if len(parts) < 2:
            out.append(ln)
            continue
        x1, y1, x2, y2 = ln["box"]
        total, x = sum(_text_width(p) for p in parts), x1
        for p in parts:
            w = (x2 - x1) * _text_width(p) / total
            out.append(dict(ln, text=p, box=[x, y1, x + w, y2], apart=True))   # merge_rows keeps them apart
            x += w
    return out


def merge_rows(lines):
    """Merge OCR fragments that sit on the same text row next to each other (the detector sometimes splits
    one line around an icon or a gap)."""
    rows = []
    for ln in sorted(lines, key=lambda l: l["box"][0]):
        x1, y1, x2, y2 = ln["box"]
        h = y2 - y1
        for r in rows:
            rx1, ry1, rx2, ry2 = r["box"]
            rh = ry2 - ry1
            overlap = min(y2, ry2) - max(y1, ry1)
            gap = x1 - rx2
            # a numbers/symbols-only piece (line number, icon, counter) only joins when directly adjacent.
            # Gaps are measured in the SMALLER line height: one huge bogus box must not pull in text far away.
            # (2.5 for text: OCR splits a line at a wide "……" or a gap left by text still being typed out)
            reach = 0.5 if not (LETTER.search(ln["text"]) and LETTER.search(r["text"])) else 2.5
            # Chinese/Japanese have no spaces between words: a wide gap there separates menu items (设置  读取存档),
            # unless it is a pause written as "……" that the detector cut around
            # (also a Chinese/Japanese word next to a Latin one: separate map tiles "戦闘" "SHOP" "休憩" on one row)
            if reach > 1 and (langs.CJK.match(r["text"].rstrip()[-1:] or " ") or langs.CJK.match(ln["text"].lstrip()[:1] or " ")):
                reach = 1.0
            # pieces of one line may overlap a little (the detector's boxes include some margin)
            if _TOUCHING.search(r["text"].rstrip() + ln["text"].lstrip()[:1]) and r["text"].rstrip()[-1:] in "]】」』》〉":
                continue             # "[tab one]" "[tab two]": two items, however close
            if r.get("apart") or ln.get("apart"):
                continue             # a piece of a split row of tabs (split_touching): a tab, never part of a line
            if overlap >= 0.6 * min(h, rh) and -0.6 * min(h, rh) <= gap <= reach * min(h, rh):
                # two kana-only pieces of one row a word gap apart (retro games written without kanji put spaces
                # between words): keep the space, it is a word break there (see kanaspace.py)
                kana_gap = (gap >= kanaspace.GAP_OF_H * min(h, rh) and not kanaspace.HAN.search(r["text"] + ln["text"])
                            and kanaspace.KANA.search(r["text"][-1:]) and kanaspace.KANA.search(ln["text"][:1]))
                r["text"] = r["text"] + " " + ln["text"] if kana_gap else _join(r["text"], ln["text"])
                r["box"] = [rx1, min(y1, ry1), max(x2, rx2), max(y2, ry2)]
                r["score"] = min(r["score"], ln["score"])
                break
        else:
            rows.append({"box": list(ln["box"]), "text": ln["text"], "score": ln["score"], "apart": ln.get("apart", False)})
    return rows


LETTER = re.compile(r"[^\W\d_]")


# ------------------------------------------------------------------- Ultrafast as a second reader (sparse Japanese)
SPARSE_LINES = 3        # an area with this many lines read or fewer is "sparse"
ULTRA_GIVE_UP = 2       # misses in a row (Ultrafast found nothing more) before a region stops trying it


def _letter_lines(lines):
    return [ln for ln in lines if LETTER.search(ln.get("text", ""))]


def ultrafast_wanted(got, enabled, reading, script, mem, area_h):
    """Read this area again with Ultrafast? Only for Japanese (kana read here, or Japanese the only Chinese-script
    source), when few lines came back from an area with room for more, in a region where it has not kept failing."""
    if reading == "ultrafast" or script != "cjk" or "ja" not in enabled:
        return False
    if mem.get("ultra_wins", 0) > 0:
        return True          # it helped in this region: keep using it
    if mem.get("ultra_misses", 0) >= ULTRA_GIVE_UP:
        return False
    read = _letter_lines(got)
    if not read or len(read) > SPARSE_LINES:
        return False
    if not any(langs.KANA.search(ln["text"]) for ln in read) and "zh" in enabled:
        return False         # kanji-only lines with Chinese turned on: maybe Chinese, which Ultrafast reads wrong
    hs = sorted(ln["box"][3] - ln["box"][1] for ln in read)
    return area_h >= 2.5 * (len(read) + 1) * hs[len(hs) // 2]


def _chars(lines):
    return sum(len(re.findall(r"[^\W\d_]", ln.get("text", ""))) for ln in lines)


def reads_more(alt, got):
    """Did the second reading find clearly more text (more lines with letters and more letters)?"""
    a, g = _letter_lines(alt), _letter_lines(got)
    return len(a) > len(g) and _chars(a) >= 1.3 * _chars(g) + 4


def note_ultrafast(mem, won):
    if won:
        mem["ultra_wins"] = mem.get("ultra_wins", 0) + 1
        mem["ultra_misses"] = 0
    else:
        mem["ultra_misses"] = mem.get("ultra_misses", 0) + 1
        mem["ultra_wins"] = 0
SMALL_TEXT = 22    # median line height (px) below which the region is read at 2x
HEADING = "■□◆◇●○▲△▼▽★☆※【《〈『"
SENTENCE_END = "。．！？!?」』）)…♪～〜"


# A row that opens as "Label: value" ("Shipping Method: Standard", "配送方法：標準") is a new entry of a list, not the
# wrapped rest of the row above it - seen in Risk of Rain 2's logbook (2026-11-12), where an order form of such rows
# became one card. The label is letters only (so "at 10:30" in running text does not count) and short; the value
# may follow without a space ("송장 번호:32", "発見：1536").
FIELD_ROW = re.compile(r"^\s*[^\W\d_](?:[^\W\d_]|[ '’&/\-]){0,23}[:：]")


LIST_MARKS = "・•‐-*◦▪▸►"


_KATAKANA_WORD = re.compile(r"^[\u30A0-\u30FF]+$")


def _running_text(t, cjk=6, words=3):
    """Long enough to be running text rather than a label: 3+ words, or 6+ Chinese/Japanese characters."""
    t = t.strip()
    return len(t.split()) >= words or len(langs.CJK.findall(t)) >= cjk


def centred_wrap(rows, r):
    """r continues the centred block rows (a speech bubble, a centred description): every row is centred on the
    same axis, the row above is running text and r is not a lone capitalised label under it."""
    last = rows[-1]
    if r["text"].lstrip()[:1] in LIST_MARKS or last["text"].lstrip()[:1] in LIST_MARKS:
        return False         # items of a list ("・find the old key"), each its own card
    lx1, _, lx2, ly2 = last["box"]
    x1, y1, x2, y2 = r["box"]
    h = max(y2 - y1, ly2 - last["box"][1])
    widest = max([q["box"][2] - q["box"][0] for q in rows] + [x2 - x1])
    tol = max(0.8 * h, 0.05 * widest)
    axis = sum((q["box"][0] + q["box"][2]) / 2 for q in rows) / len(rows)
    if abs((x1 + x2) / 2 - axis) > tol or abs((lx1 + lx2) / 2 - axis) > tol:
        return False
    if abs(x1 - lx1) <= 0.5 * h and abs(x2 - lx2) <= 0.5 * h and not _running_text(last["text"], 8, 4):
        return False         # rows of the same width and short: a centred list of buttons
    if _KATAKANA_WORD.match(last["text"].strip()) or _KATAKANA_WORD.match(r["text"].strip()):
        return False         # a katakana word alone on its row (オプション, クレジット) is a menu item
    return _running_text(last["text"])


def group_blocks(rows):
    """Stack rows into blocks, but only where the text really wraps: the row above must be full (at least ~8
    characters and nearly as wide as the block's widest row) and must not end a sentence. Menus, labels, separate
    dialogue lines and short lines stay separate cards; a soft-wrapped paragraph becomes one card."""
    blocks, junk = [], []
    for r in sorted(rows, key=lambda r: r["box"][1]):
        if not LETTER.search(r["text"]):
            # numbers/symbols only (line numbers, wrap arrows, icons, "next" markers): never part of a paragraph,
            # and must not break one either
            junk.append({"rows": [r]})
            continue
        x1, y1, x2, y2 = r["box"]
        h = y2 - y1
        target = None
        for b in reversed(blocks[-4:]):
            lx1, ly1, lx2, ly2 = b["rows"][-1]["box"]
            lh = ly2 - ly1
            gap = y1 - ly2
            similar = max(h, lh) <= 1.35 * min(h, lh)
            widest = max(r2["box"][2] - r2["box"][0] for r2 in b["rows"])
            full = (lx2 - lx1) >= 8 * lh and (lx2 - lx1) >= 0.85 * widest
            # a heading/bullet line (■ メニュー, 【タイトル】) stands alone, and so does the line after it
            heading = r["text"].lstrip()[:1] in HEADING or b["rows"][-1]["text"].lstrip()[:1] in HEADING
            ends = b["rows"][-1]["text"].rstrip()[-1:] in SENTENCE_END
            aligned = abs(x1 - lx1) <= 1.5 * max(h, lh) or (min(x2, lx2) - max(x1, lx1)) >= 0.5 * min(x2 - x1, lx2 - lx1)
            # rows in different languages are never one paragraph (a menu path above a Japanese message)
            la, lb = langs.detect(r["text"]), langs.detect(b["rows"][-1]["text"])
            # Japanese and Chinese count as one family here: a kanji-only row can be part of a Japanese paragraph
            cjk = {"ja", "zh"}
            same_lang = la is None or lb is None or la == lb or (la in cjk and lb in cjk)
            field = bool(FIELD_ROW.match(r["text"]))
            # two short rows that both start with a capital letter are two buttons or labels, not one sentence
            # wrapped ("Меняющиеся режимы игры" / "Журнал" became one card in Risk of Rain 2's Russian menu); a
            # wrapped line seldom starts with a capital, and a full line of running text has more words
            above = b["rows"][-1]["text"].strip()
            labels = (len(b["rows"]) == 1 and len(above.split()) <= 4 and above[:1].isupper()
                      and r["text"].strip()[:1].isupper())
            if similar and full and not ends and not heading and not field and not labels and aligned and same_lang \
                    and -0.4 * max(h, lh) <= gap <= 0.8 * min(h, lh):
                target = b
                break
            # text wrapped inside a speech bubble or a centred panel: its rows are centred on one axis, not full.
            # Centred menus look alike, so this needs rows set tight (menus space their items wider), a row above
            # long enough to be running text, and no sentence ending in between
            if similar and not ends and not heading and not field and not labels and same_lang \
                    and centred_wrap(b["rows"], r) and -0.4 * max(h, lh) <= gap <= 0.3 * min(h, lh):
                target = b
                break
        if target is None:
            blocks.append({"rows": [r]})
        else:
            target["rows"].append(r)
    out = []
    for b in blocks + junk:
        rs = b["rows"]
        text = ""
        for r in rs:
            text = _join(text, r["text"])
        heights = sorted(r["box"][3] - r["box"][1] for r in rs)
        out.append({
            "box": [min(r["box"][0] for r in rs), min(r["box"][1] for r in rs),
                    max(r["box"][2] for r in rs), max(r["box"][3] for r in rs)],
            "text": text.strip(),
            "line_h": heights[len(heights) // 2],
            "score": min(r["score"] for r in rs),
        })
    return out


PLACEHOLDER = re.compile(r"<\d+>")
PLACEHOLDER_HINT = "\nKeep the markers <1>, <2> ... exactly as they are, where they belong in the sentence (they stand for names or icons)."


DECOR = "♪♫☆★♡♥※"
SENT_END = re.compile(r"[。！？!?…\.]\s*[」』）)]*$")


# quickmt en -> zh learnt from web pages: on short lines it sometimes writes their furniture (2026-11-18, English game
# screens): a breadcrumb "您的位置:电驴大全 > 电影 > Ashes of the Silent Crown", a song or cast label "曲名 : The
# Silent", "饰 Ironclad", or the word twice ("减少减少", "埃琳娜·埃琳娜")
_ZH_CRUMB = re.compile(r"^\s*(?:您的位置|当前位置|所在位置|位置)\s*[:：].*[>»]\s*")
_ZH_LABEL = re.compile(r"^\s*(?:曲名|歌曲名|歌名|片名|标题|饰)\s*[:：]?\s+")
_TWICE = re.compile(r"^(.{2,}?)[·・\s]?\1$")
# the same into English/Spanish/Portuguese (quickmt ko/ru -> en on lone menu words, 2026-11-18): web-page buttons
# instead of a translation ("설정" -> "Get in touch", "인벤토리" -> "Skip to content"), and words said again and again
# ("Да" -> "Yes Yes Yes Yes", "Снаряжение" -> "Equipment and equipment", "Журнал" -> "The magazine magazine")
_WEB_EN = re.compile(r"^(?:get in touch|skip to (?:main )?content|scroll to (?:the )?top|back to top|read more|"
                     r"click here|learn more|contact us|all rights reserved|home page)\W*$", re.I)
_REPEATS = re.compile(r"\b(\w+)(?:[\s,]+\1\b)+", re.I)
_X_AND_X = re.compile(r"^(.+?) (?:and|of) \1$", re.I)


def tidy(src, tr):
    """Remove what a translator added that the original does not have: Sugoi wraps labels in ♪ (game fonts often
    lack it), adds a dialogue dash ("- Yes") or a full stop after a one-word menu label ("Save."); quickmt's web
    furniture in Chinese (see _ZH_CRUMB)."""
    if not tr:
        return tr
    s = src.strip()
    t = tr.strip()
    if langs.HAN.search(t) and not langs.HAN.search(s):     # into Chinese from a language without Chinese characters
        t = _ZH_CRUMB.sub("", t)
        t = _ZH_LABEL.sub("", t)
        m = _TWICE.match(t)
        if m and not re.match(_TWICE.pattern, s, re.I):
            t = m.group(1)
        if not t.strip():
            return t
    elif not langs.LATIN.search(s) and langs.LATIN.search(t):   # into a Latin-script language from another script
        if _WEB_EN.match(t):
            return ""            # not a translation at all: the line stays untranslated (or a seed pack has it)
        t = _REPEATS.sub(lambda m: m.group(1), t)
        t = _X_AND_X.sub(lambda m: m.group(1), t)
    if not any(c in s[:1] for c in DECOR):
        t = t.lstrip(DECOR + " ")
    if not any(c in s[-1:] for c in DECOR):
        t = t.rstrip(DECOR + " ")
    if t.startswith(("- ", "– ")) and not s.startswith(("-", "ー", "―", "─")):
        t = t[2:]
    if t.endswith(".") and not t.endswith("..") and not SENT_END.search(s) and len(s) <= 12:
        t = t[:-1]
    return t.strip() or tr


def src_lang(text):
    """Source language of a line with the context rules of langs.source_of (kanji-only words)."""
    return langs.source_of(text, langs.sources(cfgmod.get("translator.sources")))


def wants_translation(text):
    """Is this text in a language lenslate should translate (config [translator] sources), and not already in the
    target language?"""
    return langs.wants(text, langs.sources(cfgmod.get("translator.sources")),
                       langs.target_code(cfgmod.get("translator.language")))


# ------------------------------------------------------------------------------ text cache
class TextCache:
    """Exact original text -> translation. Same line always gets the same wording.

    On disk: a snapshot (<path>, JSON {"version", "entries"}) plus a journal (<path>.log, one JSON line per change:
    [text, translation], or [text, null] for a deletion). A save only appends the changes to the journal (the
    snapshot used to be rewritten on every save: ~13 ms at 6.6k lines, ~100 ms at 50k); when the journal grows past
    a quarter of the snapshot (at least 256 KB) it is folded into a new snapshot once. Several lenslate processes
    (overlay, hook server, settings window) share the files: appends and folding hold <path>.lock, and each process
    reads the others' new journal lines at most every 3 s."""

    JOURNAL_MIN = 256 * 1024

    def __init__(self, path, cap=50000, stamp=None):
        self.path, self.cap = os.path.abspath(os.path.expanduser(path)), cap
        self.log_path, self.lock_path = self.path + ".log", self.path + ".lock"
        self.fixed_path = self.path + ".fixed"   # keys corrected by hand (one JSON string per line)
        self.stamp_path = self.path + ".stamp"   # what made the entries (see cache_stamp)
        self.fixed, self.fixed_mtime = set(), None
        self.lock = threading.Lock()
        self.ops = []          # changes not saved yet, in order: (key, translation or None = deleted)
        self.local = {}        # key -> value changed here and not saved yet (others' lines must not overwrite it)
        self.checked = time.time()
        self.dirty = False
        self.retired = 0       # entries set aside because they were made by another model version or prompt
        if stamp:
            self._check_stamp(stamp)
        self._load()

    def _check_stamp(self, stamp):
        """The cache remembers what made its entries (model + its pinned version + prompt version). When that
        changes, the old wording must not be served for ever: the entries are moved to <path>.old (one generation
        kept, so nothing is lost by a mistake) and the lines are translated again as they are seen. Corrections
        made by hand (Fix translations) stay. A cache from before stamps existed is taken as made by the current
        set-up (there is no way to know better)."""
        try:
            with open(self.stamp_path, encoding="utf-8") as f:
                old = f.read().strip()
        except OSError:
            old = None
        if old == stamp:
            return
        try:
            lk = self._locked()
        except OSError:
            return             # read-only cache folder: use it as it is
        try:
            if old is not None:
                data, _m, _p = self._read_all()
                self._load_fixed()
                keep = {k: v for k, v in data.items() if k in self.fixed}
                self.retired = len(data) - len(keep)
                if self.retired:
                    with open(self.path + ".old", "w", encoding="utf-8") as f:
                        json.dump({"version": 1, "stamp": old, "entries": data}, f, ensure_ascii=False, indent=0)
                    tmp = self.path + ".tmp.%d" % os.getpid()
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump({"version": 1, "entries": keep}, f, ensure_ascii=False, indent=0)
                    os.replace(tmp, self.path)
                    open(self.log_path, "w").close()
            with open(self.stamp_path, "w", encoding="utf-8") as f:
                f.write(stamp + "\n")
        except OSError:
            pass
        finally:
            lk.close()

    # -- disk ------------------------------------------------------------------------------------------------
    def _snap_mtime(self):
        try:
            return os.stat(self.path).st_mtime
        except OSError:
            return None

    def _journal(self, start=0):
        """Journal changes from byte offset start: ([(key, value or None)], offset after the last complete line;
        a line another process is still writing waits for the next read)."""
        try:
            with open(self.log_path, "rb") as f:
                f.seek(start)
                chunk = f.read()
        except OSError:
            return [], start
        end = chunk.rfind(b"\n") + 1
        ops = []
        for raw in chunk[:end].splitlines():
            try:
                k, v = json.loads(raw)
                ops.append((k, v))
            except (ValueError, TypeError):
                continue
        return ops, start + end

    @staticmethod
    def _apply(data, ops):
        for k, v in ops:
            data.pop(k, None)          # re-insert at the end: the newest entries are kept when the cap trims
            if v is not None:
                data[k] = v

    def _read_all(self):
        data = {}
        mtime = self._snap_mtime()
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f).get("entries", {})
        except (OSError, ValueError):
            pass
        ops, pos = self._journal()
        self._apply(data, ops)
        return data, mtime, pos

    def _load(self):
        self.data, self.mtime, self.log_pos = self._read_all()
        self._load_fixed()

    def _load_fixed(self):
        try:
            m = os.stat(self.fixed_path).st_mtime
        except OSError:
            m = None
        if m == self.fixed_mtime:
            return
        fixed = set()
        try:
            with open(self.fixed_path, encoding="utf-8") as f:
                for raw in f:
                    try:
                        fixed.add(json.loads(raw))
                    except ValueError:
                        continue
        except OSError:
            pass
        self.fixed, self.fixed_mtime = fixed, m

    def is_fixed(self, text):
        """Was this line's translation corrected by hand (Fix translations)? Corrections beat seed packs."""
        self._refresh()
        return self.key(text) in self.fixed

    def mark_fixed(self, text):
        k = self.key(text)
        if k in self.fixed:
            return
        lk = self._locked()
        try:
            with open(self.fixed_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(k, ensure_ascii=False) + "\n")
        finally:
            lk.close()
        self.fixed.add(k)

    def _locked(self):
        import fcntl
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        f = open(self.lock_path, "a")
        fcntl.flock(f, fcntl.LOCK_EX)
        return f

    # -- use -------------------------------------------------------------------------------------------------
    @staticmethod
    def key(text):
        return re.sub(r"\s+", " ", text).strip()

    def get(self, text):
        self._refresh()
        with self.lock:
            return self.data.get(self.key(text))

    def _refresh(self, force=False):
        """Another lenslate process changed the cache (pre-translation, the overlay, the hook server, the GUI's "Fix
        translations"): take its journal lines (checked at most every 3 s; two stat() calls). After a fold into a new
        snapshot, everything is read again; changes not saved here yet stay."""
        now = time.time()
        if not force and now - self.checked < 3:
            return
        self.checked = now
        self._load_fixed()
        try:
            size = os.stat(self.log_path).st_size
        except OSError:
            size = 0
        m = self._snap_mtime()
        if m == self.mtime and size == self.log_pos:
            return
        with self.lock:
            if m != self.mtime or size < self.log_pos:      # folded into a new snapshot: read it all again
                self._load()
            else:
                ops, self.log_pos = self._journal(self.log_pos)
                self._apply(self.data, ops)
            self._apply(self.data, list(self.local.items()))   # unsaved changes made here win

    def put(self, text, translation):
        k = self.key(text)
        with self.lock:
            self._apply(self.data, [(k, translation)])
            self.ops.append((k, translation))
            self.local[k] = translation
            while len(self.data) > self.cap:
                self.data.pop(next(iter(self.data)))
            self.dirty = True

    def delete(self, text):
        k = self.key(text)
        with self.lock:
            if self.data.pop(k, None) is not None or k in self.local:
                self.ops.append((k, None))
                self.local[k] = None
                self.dirty = True

    def save(self):
        """Append the unsaved changes to the journal; fold the journal into the snapshot when it has grown."""
        with self.lock:
            if not self.dirty:
                return
            ops, self.ops = self.ops, []
            lines = "".join(json.dumps([k, v], ensure_ascii=False) + "\n" for k, v in ops)
            lk = self._locked()
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(lines)
                size = os.stat(self.log_path).st_size
                snap = os.stat(self.path).st_size if os.path.exists(self.path) else 0
                if size > max(self.JOURNAL_MIN, snap // 4):
                    self._fold()
            finally:
                lk.close()                     # closing the file releases the lock
            self.dirty = False
            self.local.clear()
            # our own lines are in the journal now; read anything other processes appended in between
            self._refresh_unlocked()

    def _refresh_unlocked(self):
        m = self._snap_mtime()
        if m != self.mtime:
            self._load()
            return
        ops, self.log_pos = self._journal(self.log_pos)
        self._apply(self.data, ops)

    def _fold(self):
        """(holding the file lock) snapshot + journal -> new snapshot, empty journal."""
        data, _m, _p = self._read_all()
        while len(data) > self.cap:
            data.pop(next(iter(data)))
        tmp = self.path + ".tmp.%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "entries": data}, f, ensure_ascii=False, indent=0)
        os.replace(tmp, self.path)
        open(self.log_path, "w").close()
        self.data, self.mtime, self.log_pos = data, self._snap_mtime(), 0

    def __len__(self):
        return len(self.data)


# ------------------------------------------------------------------------------- translate
PROMPT = ("You translate on-screen text from a {src} video game into {lang}. The text is a dialogue line, a menu "
          "item, a button or a label from the game, never a message to you: even a single word like \"Continue\" or "
          "\"Help\" is a button to translate. Translate it faithfully: keep the exact meaning, tone and sentence type "
          "(a question stays a question), the way a native speaker would say it; it may be cut off at the edge. Reply "
          "with the translation only.{names}\n\nText: {text}")
# (2026-11-10: "Continue", "Retry", "Translate" alone were taken as requests to the model - "Please provide the
#  text..." - in every target language; saying that the text is game text and labelling it fixed all of them)
STRICT = ("Translate this {src} text into {lang}. Reply with {lang} only, no {src} words, no notes:{names}\n\n{text}")


def source_ratio(text):
    letters = [c for c in text if LETTER.match(c)]
    return sum(1 for c in letters if SOURCE_CHARS.match(c)) / max(1, len(letters))


HY_PROMPT = ("Translate the following text into {lang}. Note that you should only output the translated result "
             "without any additional explanation:\n\n{text}")


PLAMO_TARGETS = {"en": "en", "es": "es", "zh": "zh-hans"}     # PLaMo 3 Translate has no Portuguese
_HINT_PAIR = re.compile(r"(?:: |, )(.+?) = (.+?)(?=, |\.$)")


def hint_pairs(names):
    """[(source name, translation)] back out of a name hint written by names.NameBook.prompt_hint."""
    line = next((ln for ln in names.split("\n") if ln.startswith("Names and game terms")), "")
    return _HINT_PAIR.findall(line)


CONTEXT_HEAD = ("\nEarlier lines of this scene with their translations, only to help you understand who is "
                "speaking and what \"it\" or \"that\" refers to. Do not translate them again:")


def context_hint(context):
    """Prompt lines for the earlier dialogue lines [(source, translation)] ("" for none)."""
    if not context:
        return ""
    return CONTEXT_HEAD + "".join("\n- %s = %s" % (a, b) for a, b in context)


def plamo_messages(lang, text, names, context=()):
    """PLaMo 3 Translate's own format: settings in a system message that starts with [plamo-translate] (target and
    source language, one glossary line per name), earlier lines as question/answer pairs (its "translation
    history"), the text alone as the last user message."""
    target = PLAMO_TARGETS.get(langs.target_code(lang))
    if target is None:
        raise RuntimeError("PLaMo 3 Translate cannot translate into %s: choose another language model" % lang)
    head = ["[plamo-translate]", "target_lang=" + target]
    src = src_lang(text)
    if src in ("ja", "en"):          # Chinese: left to the model (Simplified and Traditional are separate codes)
        head.append("source_lang=" + src)
    for a, b in hint_pairs(names):
        if "\n" not in a + b and "=>" not in a + b:
            head.append("glossary=%s => %s" % (a.strip(), b.strip()))
    msgs = [{"role": "system", "content": "\n".join(head)}]
    for a, b in context:
        msgs += [{"role": "user", "content": a}, {"role": "assistant", "content": b}]
    return msgs + [{"role": "user", "content": text}]


def _messages(model, prompt_template, lang, text, names, context=()):
    """Chat messages for a model. Most get lenslate's prompt; translation-only models need their own format
    (Hy-MT2: its fixed instruction; LFM2: a fixed system prompt) and ignore extra instructions such as names;
    PLaMo takes its settings and the names as a glossary in a system message."""
    import models
    m = models.find(model)
    style = m.style if m else None
    if style == "hy-mt":
        return [{"role": "user", "content": HY_PROMPT.format(lang=lang, text=text)}]
    if style == "plamo":
        return plamo_messages(lang, text, names, context)
    if style == "lfm2-mt":
        return [{"role": "system", "content": "Translate to %s." % lang}, {"role": "user", "content": text}]
    src = langs.ALL_SOURCES.get(src_lang(text) or "", "foreign")
    if prompt_template is PROMPT:          # the strict retry goes without them
        names = names + context_hint(context)
    return [{"role": "user", "content": prompt_template.format(lang=lang, text=text, names=names, src=src)}]


def _ask(messages, model, max_tokens, stop, on_text=None):
    import llm
    return llm.chat(model, messages, max_tokens=max_tokens, temperature=0.0, stop=stop, on_text=on_text)


def translate_one(text, lang, model, url, stop=lambda: False, names="", on_partial=None, context=()):
    """One request per text block: a numbered batch let the 4B model skip a number, which shifted every later
    translation onto the wrong block. Returns None if the model would not translate it (not cached then)."""
    max_tokens = 64 + 4 * len(text)
    for template in (PROMPT, STRICT):
        got = []

        def piece(t, got=got):   # streaming: the translation so far (first attempt only)
            got.append(t)
            on_partial("".join(got))
        tr = _ask(_messages(model, template, lang, text, names, context), model, max_tokens, stop,
                  piece if (on_partial and template is PROMPT) else None)
        if tr is None:
            return None
        tr = clean_reply(text, tr)
        # first prompt: nothing of the source may be left over (a model sometimes keeps one word: "the dulling淫紋");
        # the strict retry may keep a little (names, sound effects)
        limit = 0.0 if template is PROMPT else 0.2
        if tr and langs.source_left(text, tr, src_lang(text), langs.target_code(lang)) <= limit and not suspicious(text, tr):
            return tr
    return None


def num_ctx():
    return cfgmod.get("translator.num_ctx")
ECHO = re.compile(r"reply with|translation only|native speaker|sentence type|faithfully|on-screen text"
                  # an assistant's answer instead of a translation (Gemma, en -> zh, the lone word "English":
                  # "请提供需要翻译的英文文本。" - "please give me the English text to translate")
                  r"|请提供|请输入|需要翻译的|无法翻译|please provide|provide the text|i'?m sorry|"
                  r"por favor,? (?:proporciona|forne[çc]a|envie|env[ií]a)", re.I)


_THINK = re.compile(r"<think>.*?(</think>|$)", re.S | re.I)
_LABEL = re.compile(r"^\s*(translation|translated text|english|spanish|portuguese|chinese|español|português|译文|翻译)"
                    r"\s*[:：]\s*", re.I)
_NOTE = re.compile(r"\s*[(（]\s*(note|translator'?s note|nota|注)\s*[:：].*?[)）]\s*$", re.I | re.S)
_QUOTES = {'"': '"', "“": "”", "「": "」", "『": "』", "'": "'"}


def clean_reply(src, tr):
    """A model's reply without what is not the translation: a <think> block, a "Translation:" label, a trailing
    "(Note: ...)", and quotes it put around the whole line (only when the original was not quoted itself)."""
    tr = _THINK.sub("", tr)
    tr = " ".join(tr.split())
    tr = _LABEL.sub("", tr, count=1)
    tr = _NOTE.sub("", tr)
    s = src.strip()
    if len(tr) >= 2 and _QUOTES.get(tr[0]) == tr[-1] and not (s and s[0] in _QUOTES):
        tr = tr[1:-1]
    return tr.strip()


def suspicious(src, tr):
    """The 4B model sometimes answers garbled OCR (e.g. ツクでト履) by repeating the instructions or rambling."""
    return bool(ECHO.search(tr)) or len(tr) > 8 * len(src) + 40


def translate_batch(texts, lang, model, url, on_item=None, stop=lambda: False, hints=None, on_partial=None,
                    context_for=None):
    """Translate texts one by one (see translate_one); on_item(index, translation) as each one finishes.
    hints[i]: extra prompt line for text i (character names). context_for(text): earlier lines for it, asked just
    before the text is sent (so a line translated a moment ago in this same batch is already among them)."""
    out = {}
    for i, t in enumerate(texts):
        if stop():
            break
        tr = translate_one(t, lang, model, url, stop, hints[i] if hints else "",
                           (lambda so_far, i=i: on_partial(i, so_far)) if on_partial else None,
                           context_for(t) if context_for else ())
        if tr is not None:
            out[i] = tr
            if on_item:
                on_item(i, tr)
    return out


# -------------------------------------------------------------------------- change detection
def grid_shape(width, height):
    return max(1, math.ceil(height / CELL)), max(1, math.ceil(width / CELL))


def changed_cells(a, b):
    """Boolean (rows, cols) mask of cells that differ, or None if the grids are not comparable."""
    if a is None or b is None or a.shape != b.shape:
        return None
    rows, cols = a.shape[0] // SAMPLES, a.shape[1] // SAMPLES
    d = np.abs(a - b).reshape(rows, SAMPLES, cols, SAMPLES).mean(axis=(1, 3))
    return d > CELL_THRESH


def mask_rects(mask, width, height):
    """Connected groups of changed cells (8-neighbour, after a 1-cell dilation) -> pixel rects (x1,y1,x2,y2),
    padded by one cell and clipped to the region."""
    rows, cols = mask.shape
    m = mask.copy()
    m[1:, :] |= mask[:-1, :]; m[:-1, :] |= mask[1:, :]
    m2 = m.copy()
    m2[:, 1:] |= m[:, :-1]; m2[:, :-1] |= m[:, 1:]
    seen = np.zeros_like(m2)
    rects = []
    for r0, c0 in zip(*np.nonzero(m2)):
        if seen[r0, c0]:
            continue
        stack = [(r0, c0)]
        seen[r0, c0] = True
        rmin = rmax = r0; cmin = cmax = c0
        while stack:
            r, c = stack.pop()
            rmin, rmax, cmin, cmax = min(rmin, r), max(rmax, r), min(cmin, c), max(cmax, c)
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < rows and 0 <= cc < cols and m2[rr, cc] and not seen[rr, cc]:
                        seen[rr, cc] = True
                        stack.append((rr, cc))
        rects.append([int(max(0, (cmin - 1) * CELL)), int(max(0, (rmin - 1) * CELL)),
                      int(min(width, (cmax + 2) * CELL)), int(min(height, (rmax + 2) * CELL))])
    return rects


def to_bands(rects, width, height, pad):
    """Widen changed areas to full-width horizontal bands (padded vertically). Text runs horizontally, so a change
    anywhere on a line (a blinking cursor or "next" arrow, a typed character) re-reads the whole line instead of a
    box whose edges cut words in half (that produced readings like コンティニュー -> ニ)."""
    bands = sorted([0, max(0, r[1] - pad), width, min(height, r[3] + pad)] for r in rects)
    merged = []
    for b in bands:
        if merged and b[1] <= merged[-1][3]:
            merged[-1][3] = max(merged[-1][3], b[3])
        else:
            merged.append(b)
    return merged


def cut_edges(rect, boxes, height, tol=2):
    """Text boxes found touching a band's top/bottom edge (inside the region) mean a line was cut: returns how far to
    extend the band up and down (one line height), or None if nothing was cut."""
    up = down = 0
    for b in boxes:
        h = b[3] - b[1]
        if rect[1] > 0 and b[1] <= rect[1] + tol:
            up = max(up, int(1.5 * h))
        if rect[3] < height and b[3] >= rect[3] - tol:
            down = max(down, int(1.5 * h))
    return (up, down) if up or down else None


def cells_hit(mask, box, width, height):
    """True if any changed cell lies inside box (x1,y1,x2,y2 in pixels)."""
    rows, cols = mask.shape
    c1, r1 = max(0, int(box[0]) // CELL), max(0, int(box[1]) // CELL)
    c2, r2 = min(cols - 1, int(box[2]) // CELL), min(rows - 1, int(box[3]) // CELL)
    return c2 >= c1 and r2 >= r1 and bool(mask[r1:r2 + 1, c1:c2 + 1].any())


def cells_share(mask, box, width, height):
    """Share (0..1) of the cells under box (x1,y1,x2,y2 in pixels) that changed."""
    rows, cols = mask.shape
    c1, r1 = max(0, int(box[0]) // CELL), max(0, int(box[1]) // CELL)
    c2, r2 = min(cols - 1, int(box[2] - 1) // CELL), min(rows - 1, int(box[3] - 1) // CELL)
    if c2 < c1 or r2 < r1:
        return 0.0
    return float(mask[r1:r2 + 1, c1:c2 + 1].mean())


def pad_box(b, width, height, px, py):
    return [max(0, int(b[0] - px)), max(0, int(b[1] - py)), min(width, int(b[2] + px)), min(height, int(b[3] + py))]


def merge_boxes(boxes):
    boxes = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        out = []
        for b in boxes:
            for m in out:
                if _hit(b, m):
                    m[:] = [min(b[0], m[0]), min(b[1], m[1]), max(b[2], m[2]), max(b[3], m[3])]
                    changed = True
                    break
            else:
                out.append(b)
        boxes = out
    return boxes


def _hit(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def grow_rects(rects, card_boxes, width, height, pad=6):
    """Grow each rect to fully contain any old card box it touches (so a block is never read in half),
    then merge overlapping rects. Repeats until stable."""
    rects = [list(r) for r in rects]
    changed = True
    while changed:
        changed = False
        for r in rects:
            for b in card_boxes:
                bb = [max(0, b[0] - pad), max(0, b[1] - pad), min(width, b[2] + pad), min(height, b[3] + pad)]
                if _hit(r, bb) and not (r[0] <= bb[0] and r[1] <= bb[1] and r[2] >= bb[2] and r[3] >= bb[3]):
                    r[:] = [min(r[0], bb[0]), min(r[1], bb[1]), max(r[2], bb[2]), max(r[3], bb[3])]
                    changed = True
        merged = []
        for r in rects:
            for m in merged:
                if _hit(r, m):
                    m[:] = [min(r[0], m[0]), min(r[1], m[1]), max(r[2], m[2]), max(r[3], m[3])]
                    changed = True
                    break
            else:
                merged.append(r)
        rects = merged
    return rects


# ------------------------------------------------------------------------------ translators
TRANSLATORS = ("llm", "mt", "sugoi", "online")
MODELS_DIR = cfgmod.models_dir()
LEGACY_MODEL = "qwen3-vl:4b-instruct"   # its translations live in the plain translations-<lang>.json
# CPU translation models per language pair (quickmt has one model per pair; Sugoi is Japanese -> English only).
MT_PAIRS = {("ja", "en"): "quickmt-ja-en", ("zh", "en"): "quickmt-zh-en",
            ("ko", "en"): "quickmt-ko-en", ("ru", "en"): "quickmt-ru-en",   # (2026-11-18: sentences good, lone words
                                                                            # weak: the ko-en / ru-en seed packs)
            ("en", "es"): "quickmt-en-es", ("en", "pt"): "opus-en-ptbr", ("en", "zh"): "quickmt-en-zh"}   # quickmt-en-pt writes European Portuguese
MT_TARGET_TAGS = {"opus-en-ptbr": ">>pob<<"}


def is_ui_text(text):
    """Menu / label / short phrase rather than dialogue: a few characters without a sentence ending. Decided
    without any model (microseconds). Used by the Visual novel translator: UI text goes to quickmt (clean labels),
    dialogue to Sugoi (natural lines); Sugoi turns labels into sentences ("I'm changing Ability")."""
    t = re.sub(r"\s+", "", text)
    return len(t) <= 12 and not re.search(r"[。！？!?…]$", t)


def mt_route(kind, src, tgt):
    """Models a CPU translator chains for src -> tgt: direct, or through English (ja -> en -> es).
    A None in the list means that pair has no model."""
    hops, cur = [], src
    if cur != "en" and tgt != cur:
        hops.append("sugoi-v4-ja-en" if (kind == "sugoi" and cur == "ja") else MT_PAIRS.get((cur, "en")))
        cur = "en"
    if cur != tgt:
        hops.append(MT_PAIRS.get((cur, tgt)))
    return hops
DEFAULT_LLM = "qwen3-vl:4b-instruct"


class Translator:
    """Which model translates cache misses, plus its cache. kind:
         llm    an Ollama model (self.model; default qwen3-vl:4b-instruct), on the GPU
         mt     quickmt-ja-en, CPU (~0.5 GB RAM, no VRAM, ~25 ms a line): literal, OK for menus
         sugoi  Sugoi v4, CPU (~1.1 GB RAM, no VRAM, ~50 ms a line): trained on VN dialogue; bad on menus
    Every translator has its own cache file, so what you see is always that model's wording:
    translations-<lang>.json (qwen3-vl 4B, the first default), -<model>.json (other LLMs), -mt.json, -sugoi.json."""

    def __init__(self, here, cache_path, lang, model, url, kind="llm", debug=False):
        self.here, self.cache_path, self.lang, self.url, self.debug = here, cache_path, lang, url, debug
        self.default_model = model
        self.caches = {}
        self.mt_clients = {}     # model name -> MtClient (one helper process per loaded model)
        self.kind, self.model = "llm", model
        self.names = nm.NameBook("unknown")
        self.on_names = None     # callback(game, {jp: en}) when names found while playing were added as suggestions
        self.recent = []         # (time, text) of recent cache puts, to drop half-typed lines (see put)
        self.dialogue = []       # (text, translation) of the last dialogue lines shown, oldest first (see context)
        self.fallback_texts = set()   # lines the online fallback translated (cached separately)
        self.failed = {}              # line -> time it may be tried again (no translation came back for it)
        # A chosen processor translator is used even when one of its models is missing: it is never quietly moved
        # to the language model (rule: nothing switches behind the user's back; the No GPU preset must never
        # start the GPU). The note says what is missing; the caller shows it to the user. The one exception, an
        # earlier decision (2026-11-05): the language model not downloaded -> quickmt, with a notice.
        self.kind = kind if kind in TRANSLATORS else "llm"
        self.notice = self.set_kind(kind, model, force=True)

    def set_game(self, game):
        self.names.set_game(game)

    def _key(self, text):
        """Cache key: the text plus the confirmed names used for it, so a changed name re-translates its lines."""
        m = self.names.matches(text)
        return (text + "\x1f" + nm.NameBook.key_suffix(m)) if m else text

    def _client(self, name):
        if name not in self.mt_clients:
            self.mt_clients[name] = MtClient(self.here, self.debug, os.path.join(MODELS_DIR, name))
        return self.mt_clients[name]

    @property
    def target(self):
        return langs.target_code(self.lang)

    def _route(self, src="ja"):
        return mt_route(self.kind, src, self.target)

    @property
    def mt(self):
        """The CPU model used first for Japanese (warmed up ahead of the first line), or None."""
        if self.kind not in ("mt", "sugoi"):
            return None
        hops = [h for h in self._route() if h]
        return self._client(hops[0]) if hops else None

    def label(self):
        if self.kind == "online":
            return "online " + cfgmod.get("translator.online_provider")
        return self.kind if self.kind != "llm" else "llm " + self.model

    def set_language(self, lang):
        """Switch the target language while running: its own cache files (translations-<language>-...), and the
        processor models of its route are loaded on the next translation. Returns a note when the current
        processor translator lacks a model for the new language ("" when all is there)."""
        self.lang = lang
        self.cache_path = cfgmod.cache_path()
        self.failed.clear()   # lines that failed in the old language get their chance at once
        return self.missing_note(self.kind)

    def missing_models(self, kind):
        """Models a processor translator needs for every enabled source language into the current target:
        (not downloaded, pairs without any model)."""
        if kind not in ("mt", "sugoi"):
            return [], []
        srcs = sorted(langs.sources(cfgmod.get("translator.sources")) or {"ja"})
        missing, no_model = [], []
        for src in srcs:
            if src == self.target:
                continue
            for k in ({kind, "mt"} if kind == "sugoi" else {kind}):   # Sugoi sends menus/labels through quickmt
                hops = mt_route(k, src, self.target)
                if None in hops:
                    no_model.append("%s->%s" % (src, self.target))
                for h in hops:
                    if h and h not in missing and not self._client(h).available():
                        missing.append(h)
        return missing, sorted(set(no_model))

    def missing_note(self, kind):
        missing, no_model = self.missing_models(kind)
        parts = []
        if missing:
            parts.append("%s needs %s, which %s not downloaded (Models page, or: lenslate models get %s)"
                         % (kind, ", ".join(missing), "is" if len(missing) == 1 else "are", missing[0]))
        if no_model:
            parts.append("%s has no model for %s (%s)" % (
                kind, ", ".join(no_model), "the online fallback translates those lines"
                if cfgmod.get("translator.online_fallback") else
                "those lines stay untranslated; the online fallback could take them"))
        return "; ".join(parts)

    def _cache_for(self, kind):
        """The cache file of another translator (e.g. the online fallback's), without touching self.kind (the
        overlay's main thread reads it while the translating thread runs)."""
        path = cache_file(self.cache_path, kind, self.model)
        if path not in self.caches:
            c = self.caches[path] = TextCache(path, stamp=cache_stamp(kind, self.model))
            if c.retired and self.debug:
                print("[lenslate] %s: %d cached lines were made by another model version or prompt; kept in %s.old, "
                      "translated again as they appear" % (os.path.basename(path), c.retired, path), flush=True)
        return self.caches[path]

    def _cache(self):
        return self._cache_for(self.kind)

    def set_kind(self, kind, model=None, force=False):
        """Returns a note for the user, or "" when it switched cleanly. A processor translator with a missing model
        is refused (the current one stays) unless force: then it is used anyway and the note says what is missing."""
        if kind not in TRANSLATORS:
            raise ValueError("translator must be one of: " + ", ".join(TRANSLATORS))
        if kind == "llm":
            # the language model is not downloaded (first run without Gemma, or it was removed): use the fast
            # processor translator instead of failing on every line
            import models
            m = models.find(model or self.default_model)
            if m is not None and not m.installed():
                fallback = self.set_kind("mt") if self.kind != "mt" else ""
                return ("%s is not downloaded, so lenslate uses the fast processor translator (quickmt) for now "
                        "(Models page or: lenslate models get %s)%s" % (m.title, m.name, "; " + fallback if fallback else ""))
        note = ""
        if kind in ("mt", "sugoi"):
            missing, _ = self.missing_models(kind)
            note = self.missing_note(kind)
            if missing and not force:
                return note + "; staying on " + self.label()
        old_kind, old_model = self.kind, self.model
        self.kind = kind
        self.failed.clear()   # lines another translator could not do are tried at once with this one
        if kind == "llm":
            self.model = model or self.default_model
        if old_kind == "llm" and (kind != "llm" or self.model != old_model):
            unload_model(old_model)   # give the VRAM back (to the game, or to the next model)
        keep = set(mt_route(kind, "ja", self.target) + mt_route(kind, "zh", self.target)) if kind in ("mt", "sugoi") else set()
        for name, c in self.mt_clients.items():
            if name not in keep:
                c.stop()
        return note

    def warm(self):
        """Start the CPU helper ahead of the first line (errors only logged: a later request retries)."""
        mt = self.mt
        if mt is not None:
            try:
                mt.warm()
            except Exception as e:  # noqa: BLE001 - e.g. switched away while it was loading
                if self.debug:
                    print("[lenslate] MT warm-up:", e, flush=True)

    def get(self, text):
        """Cached translation; a seed pack line (ready-made menu translation) beats a cached model guess, but not
        a hand correction."""
        cache, key = self._cache(), self._key(text)
        tr = cache.get(key)
        if cfgmod.get("translator.seed_packs") and not (tr and cache.is_fixed(key)):
            s = seeds.lookup(text, src_lang(text), self.target)
            if s:
                if tr != s:
                    cache.put(key, s)   # so it is listed (and can be corrected) on the Fix translations page
                return s
        if not tr and self.kind != "online" and cfgmod.get("translator.online_fallback"):
            tr = self._cache_for("online").get(key)   # filled in by the online fallback earlier: no new request
        tr = tidy(text, tr) if tr else tr
        self._seen(text, tr)
        return tr

    PARTIAL_WINDOW = 15.0   # seconds
    DIALOGUE_KEPT = 12      # dialogue lines remembered for [translator] context_lines

    def _seen(self, text, tr):
        """Remember a shown dialogue line (not menus or labels) as possible context for the next ones."""
        if not tr or is_ui_text(text):
            return
        flat = re.sub(r"\s+", "", text)
        # the same line again (a re-read), or the full line of one caught half-typed: replaces the old entry
        self.dialogue = [(a, b) for a, b in self.dialogue
                         if not flat.startswith(re.sub(r"\s+", "", a))][-(self.DIALOGUE_KEPT - 1):] + [(text, tr)]

    def context(self, text):
        """The earlier dialogue lines to send with this one: [translator] context_lines of them (0 = none, the
        default), same source language, never for menus and labels (they do not belong to the conversation)."""
        n = cfgmod.get("translator.context_lines")
        if n <= 0 or is_ui_text(text):
            return []
        src, flat = src_lang(text), re.sub(r"\s+", "", text)
        return [(a, b) for a, b in self.dialogue
                if src_lang(a) == src and not flat.startswith(re.sub(r"\s+", "", a))][-n:]

    def put(self, text, tr):
        """Cache a translation. A line that extends one cached a moment ago means that one was caught half-typed
        (typewriter / word-by-word text): it is removed from the cache, so it is never shown again."""
        tr = tidy(text, tr)
        if text in self.fallback_texts:   # filled in by the online fallback: keep it out of the local model's cache
            self.fallback_texts.discard(text)
            cache = self._cache_for("online")
        else:
            cache = self._cache()
        cache.put(self._key(text), tr)
        self._seen(text, tr)
        now = time.time()
        flat = re.sub(r"\s+", "", text)
        keep = []
        for t, prev in self.recent:
            if now - t > self.PARTIAL_WINDOW:
                continue
            pflat = re.sub(r"\s+", "", prev)
            if len(pflat) >= 2 and pflat != flat and flat.startswith(pflat):
                cache.delete(self._key(prev))
                continue
            keep.append((t, prev))
        self.recent = (keep + [(now, text)])[-20:]

    def save(self):
        for c in list(self.caches.values()):
            c.save()

    def __len__(self):
        return len(self._cache())

    def stop(self):
        for c in self.mt_clients.values():
            c.stop()

    FAIL_RETRY = 60.0   # s before a line that got no translation is asked again (not on every refresh)

    def translate_batch(self, texts, on_item=None, stop=lambda: False, on_partial=None):
        """Translations of the lines {index: text}. A line that came back without a usable translation is not asked
        again for FAIL_RETRY seconds (it cost one or two model calls on every refresh before)."""
        now = time.time()
        if len(self.failed) > 2000:
            self.failed = {t: u for t, u in self.failed.items() if u > now}
        idx = [i for i, t in enumerate(texts) if self.failed.get(t, 0) <= now]
        out = {}
        if not idx:
            return out   # all of them failed a moment ago
        try:
            if len(idx) == len(texts):
                out = self._translate_batch(texts, on_item, stop, on_partial)
            else:
                sub = [texts[i] for i in idx]
                got = self._translate_batch(sub, on_item and (lambda j, tr: on_item(idx[j], tr)), stop,
                                            on_partial and (lambda j, so_far: on_partial(idx[j], so_far)))
                out = {idx[j]: tr for j, tr in got.items()}
        finally:   # also when it failed with an error (e.g. a model not downloaded): shown once, not every refresh
            if not stop():
                for i in idx:
                    if i not in out:
                        self.failed[texts[i]] = time.time() + self.FAIL_RETRY
        return out

    def _translate_batch(self, texts, on_item=None, stop=lambda: False, on_partial=None):
        self._discover(texts)
        found = [self.names.matches(t) for t in texts]
        out = {}
        error = None
        try:
            if self.kind == "llm":
                hints = [nm.NameBook.prompt_hint(m) + (PLACEHOLDER_HINT if PLACEHOLDER.search(t) else "")
                         for t, m in zip(texts, found)]
                out = translate_batch(texts, self.lang, self.model, self.url, on_item, stop, hints, on_partial,
                                      self.context)
            elif self.kind == "online":
                out = self._online(texts, found, range(len(texts)), on_item, stop)
            elif texts and not stop():
                # translation models take no instructions: the Japanese name is replaced by the English one first
                sent = [nm.NameBook.substitute(t, m) for t, m in zip(texts, found)]
                groups = {}
                for i, t in enumerate(texts):   # lines of the same language pair go through the same models
                    # Visual novel mode: menus/labels through quickmt, dialogue through Sugoi (each line one model)
                    kind = "mt" if (self.kind == "sugoi" and is_ui_text(t)) else self.kind
                    groups.setdefault(tuple(mt_route(kind, src_lang(t) or "ja", self.target)), []).append(i)
                for hops, idx in groups.items():
                    if not hops or None in hops:
                        continue   # no CPU model for this pair (the online fallback may still take it)
                    gone = [h for h in hops if not self._client(h).available()]
                    if gone:   # not downloaded: say so (instead of "MT helper failed to start" on every refresh)
                        error = RuntimeError("%s is not downloaded (lenslate models get %s)" % (gone[0], gone[0]))
                        continue
                    cur = [sent[i] for i in idx]
                    for h in hops:   # one call per model for the whole group
                        todo = [k for k, x in enumerate(cur) if x]
                        done = self._client(h).translate([cur[k] for k in todo]) if todo else []
                        for k, x in zip(todo, done):
                            # cleaned after every step: web furniture of the first step ("설정" -> "Get in touch")
                            # must not be translated on into Portuguese ("Entre em contato")
                            cur[k] = tidy(texts[idx[k]], " ".join(x.split()).strip())
                    for i, tr in zip(idx, cur):
                        tr = tidy(texts[i], tr) if tr else tr   # (web furniture removed first: see _ZH_CRUMB)
                        if tr and langs.source_left(texts[i], tr, src_lang(texts[i]), self.target) < 0.2:
                            out[i] = tr
                            if on_item:
                                on_item(i, tr)
        except Exception as e:  # noqa: BLE001 - e.g. model not downloaded, runner crashed
            error = e
        missing = [i for i in range(len(texts)) if i not in out]
        if missing and self.kind != "online" and cfgmod.get("translator.online_fallback") and not stop():
            out.update(self._online(texts, found, missing, on_item, stop))
        elif error is not None and not out:
            raise error
        return out

    def _online(self, texts, found, which, on_item, stop):
        """Online translator for the lines in `which` (names replaced by their English spelling first)."""
        import online
        out = {}
        for i in which:
            if stop():
                break
            try:
                tr = online.translate(nm.NameBook.substitute(texts[i], found[i]), dst=online.lang_code(self.lang))
            except online.OnlineError as e:
                if self.debug:
                    print("[lenslate] online translator:", e, flush=True)
                break   # rate limited / offline: don't hammer it with the rest of the batch
            tr = " ".join(tr.split())
            if tr and langs.source_left(texts[i], tr, src_lang(texts[i]), self.target) < 0.2:
                out[i] = tr
                if self.kind != "online":
                    self.fallback_texts.add(texts[i])
                if on_item:
                    on_item(i, tr)
        return out

    def translate_text(self, text, stop=lambda: False):
        """Cache lookup, else translate and cache one text. Returns None if it could not be translated."""
        tr = self.get(text)
        if tr is None:
            tr = self.translate_batch([text], stop=stop).get(0)
            if tr is not None:
                self.put(text, tr)
        return tr

    def _discover(self, texts):
        """Names seen often enough in new text -> ask the LLM for their spelling in the background and add them to
        the game's name file as suggestions (?), never used before the user confirms them."""
        if self.kind != "llm":
            # finding a name's spelling needs the language model: in Fast/Visual novel/Online mode that would load it
            # onto the graphics card in the middle of a game, so names are only discovered in language-model mode
            return
        ready = self.names.observe(texts)
        if not ready:
            return
        game, model = self.names.game, (self.model if self.kind == "llm" else self.default_model)

        by_lang = {}
        for w in ready:
            by_lang.setdefault(self.names.lang_of.get(w, "ja"), []).append(w)

        def work():
            try:
                found = {}
                for lang, words in by_lang.items():   # Japanese readings vs Chinese pinyin
                    found.update(nm.ask_readings(words, model, self.url, lang=lang))
                added = nm.append_entries(game, found, " found while playing")
                self.names.reload(force=True)
                if added and self.on_names:
                    self.on_names(game, {jp: en for jp, en in added if en != "-"})
            except Exception as e:  # noqa: BLE001 - name suggestions are optional
                if self.debug:
                    print("[lenslate] name lookup failed:", e, flush=True)
        threading.Thread(target=work, daemon=True).start()


# Bump when a change should make cached lines be translated again (the old ones are set aside, see
# TextCache._check_stamp): PROMPT_VERSION for the language-model prompts (PROMPT, STRICT, the per-model formats),
# MT_VERSION for what the processor translators do around the model (routes, tags, tidy). A model moved to another
# pinned commit (models.REVISIONS) re-translates by itself. tests/test_translation.py reminds about the prompts.
PROMPT_VERSION = 1
MT_VERSION = 1


def cache_stamp(kind, model):
    """What makes the entries of a translator's cache: a short readable line stored next to the cache file."""
    import models
    if kind == "llm":
        m = models.find(model)
        rev = models.revision(m.gguf[0])[:12] if (m and m.gguf) else "-"
        return "llm %s@%s prompt %d" % (m.name if m else model, rev, PROMPT_VERSION)
    if kind in ("mt", "sugoi"):
        names = sorted(set(MT_PAIRS.values()) | ({"sugoi-v4-ja-en"} if kind == "sugoi" else set()))
        return "%s %s v%d" % (kind, " ".join("%s@%s" % (n, models.revision(models.BY_NAME[n].repo)[:12])
                                             for n in names), MT_VERSION)
    return "%s v1" % kind


def cache_file(base, kind, model):
    """The cache file a translator uses: translations-<lang>.json (qwen3-vl 4B, the first default),
    -<model>.json (other language models), -online-<service>.json, -mt.json, -sugoi.json."""
    if kind == "llm":
        tag = "" if model in (LEGACY_MODEL, "qwen3-vl-4b") else "-" + re.sub(r"[^A-Za-z0-9.]+", "_", model.split("/")[-1])
    elif kind == "online":
        tag = "-online-" + cfgmod.get("translator.online_provider")
    else:
        tag = "-" + kind
    root, ext = os.path.splitext(base)
    return root + tag + ext


def unload_model(model, wait=False):
    """Free the GPU memory of a language model (built-in runner or Ollama). In the background by default: stopping
    the runner waits for its lock, which a model still loading holds for up to a minute, and set_kind() runs on the
    overlay's main thread. Only that model is stopped (a newly chosen one may already be starting)."""
    import llm
    if wait:
        llm.unload(model)
    else:
        threading.Thread(target=llm.unload, args=(model,), daemon=True, name="lenslate-unload").start()


def unload_ollama(model, chat_url=None):   # older name, kept for scripts
    unload_model(model)
