#!/usr/bin/env python3
"""OCR helper for lenslate. Runs inside ocr-venv (RapidOCR + onnxruntime, CPU) and keeps the models loaded.

Protocol: one JSON object per line on stdin  {"path": "/run/user/1000/x.png", "scale": 1.0}
          one JSON object per line on stdout {"lines": [{"box": [x1,y1,x2,y2], "text": str, "score": float}], "secs": float}
                                          or {"error": str}
Models: PP-OCRv6 small finder + reader, PP-OCRv5 mobile for the quick finder (testbench 2026-11-10 on my
real screenshots: v6 small 99.6% vs v5 mobile 99.4%, ~10-25% less processor time; both beat the removed server
models, which were 1.4-3x slower). Careful reading never resizes the image (upscaling small
crops made them ~15x slower; downscaling big ones loses small text).
Reader "meiki" (LENSLATE_OCR_READER, the Ultrafast preset): meikiocr, a reader trained on Japanese game text, ~7x
less processor work; Japanese only (lines that come back as Latin text are read again by the PaddleOCR reader).
"""
import json
import os
import sys
import time

# The protocol gets a private copy of stdout; file descriptor 1 (and sys.stdout) then point at stderr, so a library
# that prints (model loaders, onnxruntime, CTranslate2 warnings) can never put a stray line between lenslate's answers.
# (Same block in ocr_server.py and mt_server.py: helpers run with `python -I`, so they cannot share a module.)
_PROTO = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
os.dup2(2, 1)
sys.stdout = sys.stderr


def send(obj, req=None):
    """One answer line. The request's "id" is echoed so the client can tell answers apart."""
    if req is not None and "id" in req:
        obj["id"] = req["id"]
    _PROTO.write(json.dumps(obj, ensure_ascii=False) + "\n")
    _PROTO.flush()

import numpy as np
from PIL import Image, ImageOps
from rapidocr import ModelType, OCRVersion, RapidOCR

MIN_SIDE = 48  # very small crops get a border so the detector has room around the text
# Every crop gets a margin: the text detector misses text close to the image edge (an English line 25 px from the
# top lost everything after its third word; with the margin it was read whole).
EDGE_PAD = int(os.environ.get("LENSLATE_OCR_EDGE_PAD", "32"))

# Where OCR runs (config [ocr] gpu): "off" = processor; "reader" = only the recogniser on the graphics card;
# "all" = finding and reading on the graphics card (lowest processor use; ~1.6 GB of GPU memory, each engine capped
# at 1 GB). Needs `lenslate ocr-gpu install` (CUDA build of onnxruntime + NVIDIA libraries from pip).
GPU_MODE = {"1": "reader", "0": "off", "": "off"}.get(os.environ.get("LENSLATE_OCR_GPU", ""),
                                                      os.environ.get("LENSLATE_OCR_GPU", "off"))
_CUDA = None
if GPU_MODE in ("reader", "all"):
    try:
        import onnxruntime
        onnxruntime.preload_dlls()   # NVIDIA libraries from the pip packages (no system CUDA install needed)
        if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
            _CUDA = {"EngineConfig.onnxruntime.use_cuda": True,
                     "EngineConfig.onnxruntime.cuda_ep_cfg.arena_extend_strategy": "kSameAsRequested",
                     "EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search": "HEURISTIC"}
    except Exception as e:  # noqa: BLE001 - fall back to the processor
        print("lenslate OCR: GPU not available (%s); using the processor" % e, file=sys.stderr, flush=True)
    if _CUDA is None:
        GPU_MODE = "off"


# Which PaddleOCR models read (LENSLATE_OCR_MODEL): "<version>-<size>" for the finder and the reader, or
# "<finder>/<reader>". Default PP-OCRv6 small (ships inside the rapidocr package). The quick finder (gate) is always
# PP-OCRv5 mobile. Other values exist for `lenslate testbench ocr` (v5-mobile downloads on first use).
_VERS = {"v4": OCRVersion.PPOCRV4, "v5": OCRVersion.PPOCRV5, "v6": OCRVersion.PPOCRV6}


def _model(spec):
    ver, size = spec.split("-")
    return _VERS[ver], ModelType(size)


_spec = os.environ.get("LENSLATE_OCR_MODEL", "") or "v6-small"
DET_MODEL, REC_MODEL = (_model(x) for x in (_spec.split("/") if "/" in _spec else (_spec, _spec)))
# Korean and Russian (LENSLATE_OCR_SCRIPT = korean | eslav, from "Translate from"): the main reader has no Hangul or
# Cyrillic (PP-OCRv6 covers Chinese, Japanese and Latin scripts only), so PP-OCRv5's reader for that script is used
# (it reads English letters and digits too). RapidOCR downloads it on first use (~8 MB, checksum checked).
SCRIPT = os.environ.get("LENSLATE_OCR_SCRIPT", "") or "cjk"
REC_LANG = {}
if SCRIPT in ("korean", "eslav"):
    from rapidocr.utils.typings import LangRec
    REC_MODEL = (OCRVersion.PPOCRV5, ModelType.MOBILE)
    REC_LANG = {"Rec.lang_type": LangRec.KOREAN if SCRIPT == "korean" else LangRec.ESLAV}


class Engine:
    """A RapidOCR engine on the graphics card when asked. An image the GPU cannot take (out of memory: e.g. the
    full-size detector on a big frame) is done on the processor instead, and so is every image at least
    that big from then on; smaller ones stay on the graphics card."""

    def __init__(self, params, gpu, cap_mb=None):
        if cap_mb is None:    # MB per engine; finders get a smaller share (LENSLATE_OCR_GPU_CAP = engine,finder)
            cap_mb = int(os.environ.get("LENSLATE_OCR_GPU_CAP", "384,640").split(",")[1 if "Global.use_rec" in params else 0])
        self.params, self.gpu = params, gpu and _CUDA is not None
        self.cpu_from = None          # pixel count the GPU failed at
        self.cpu_e = None
        p = dict(params)
        if self.gpu:
            p.update(_CUDA)
            p["EngineConfig.onnxruntime.cuda_ep_cfg.gpu_mem_limit"] = cap_mb * 1024 * 1024
            p["EngineConfig.onnxruntime.intra_op_num_threads"] = 2
        self.e = RapidOCR(params=p)

    def _cpu(self, img):
        if self.cpu_e is None:
            self.cpu_e = RapidOCR(params=self.params)
        return self.cpu_e(img)

    def __call__(self, img):
        if not self.gpu:
            return self.e(img)
        px = img.size[0] * img.size[1] if hasattr(img, "size") and not isinstance(img.size, int) else 0
        if self.cpu_from is not None and px >= self.cpu_from:
            return self._cpu(img)
        try:
            return self.e(img)
        except Exception as e:  # noqa: BLE001
            print("lenslate OCR: graphics card could not take a %d-pixel image (%s); images this big use the "
                  "processor" % (px, str(e)[:100]), file=sys.stderr, flush=True)
            self.cpu_from = px if self.cpu_from is None else min(self.cpu_from, px)
            return self._cpu(img)


NO_SHRINK = 8192   # see "Global.max_side_len" below

engine = Engine({
    "Det.ocr_version": DET_MODEL[0], "Det.model_type": DET_MODEL[1],
    "Rec.ocr_version": REC_MODEL[0], "Rec.model_type": REC_MODEL[1], **REC_LANG,
    "Det.limit_type": "max", "Det.limit_side_len": 4096,
    # RapidOCR also shrinks every image to at most Global.max_side_len (default 2000) before the detector's own
    # limit: a 1440p area was read at 0.76x and 4K at 0.51x, and the 2x small-text re-read of a 1920 px area came
    # back at ~1x. Lifted, so the sizes chosen here (and Det.limit_side_len) are what the models really get.
    "Global.max_side_len": NO_SHRINK,
    # no text-orientation classifier: screen text is never upside down, and the classifier made the reader lose a
    # small hint line on a test game's menu (found with it off)
    "Global.use_cls": False,
    "Global.log_level": "error",
    # 6 threads is as fast as all 12 here; the rest stays free for the game
    "EngineConfig.onnxruntime.intra_op_num_threads": int(os.environ.get("LENSLATE_OCR_THREADS", "6")),
}, GPU_MODE == "all")


# fast text *detector* used as a gate before the expensive OCR: finds where text is, does not read it
gate = None if GPU_MODE == "all" else Engine({
    "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.MOBILE,
    "Det.limit_type": "max", "Det.limit_side_len": 1280 + 2 * EDGE_PAD,
    "Global.use_cls": False, "Global.use_rec": False, "Global.log_level": "error", "Global.max_side_len": NO_SHRINK,
    "EngineConfig.onnxruntime.intra_op_num_threads": int(os.environ.get("LENSLATE_OCR_THREADS", "6")),
}, GPU_MODE == "all")


# full-resolution fast detector for whole-screen reads (finds small UI text the 1280 one misses; ~0.8 s at 1080p
# instead of a full OCR pass over the whole frame)
_gates = {1280 + 2 * EDGE_PAD: gate} if gate is not None else {}
# A finder with limit N reads every image up to N px exactly as one made for that image's own size, so requested
# sizes are rounded up to these (plus the edge margin, which the image gets before the finder sees it). Before, every
# new area size loaded one more finder for good (6 sizes: 7 models, 211 -> 392 MB, a 0.3-0.5 s stall each).
GATE_SIZES = (1280 + 2 * EDGE_PAD, 1920 + 2 * EDGE_PAD)
MAX_EXTRA_GATES = 2   # bigger sizes (4K whole-screen reads): the last few are kept


def _pad(img, pad):
    """Margin around a crop made by copying the edge pixels outward. A margin filled with one colour (the corner
    pixel) made the detector miss a small hint line near the edge of a test game's menu screen; copied edges keep
    the text near the border looking natural and still give English lines near the top the room they need."""
    import numpy as np
    a = np.asarray(img)
    return Image.fromarray(np.pad(a, ((pad, pad), (pad, pad), (0, 0)), mode="edge"))


def _gate(side):
    """The finder for images whose longest side (without the edge margin) should be at most `side` px."""
    if GPU_MODE == "all":
        # on the graphics card one full-size finder serves every request (smaller images are not resized up, so
        # crops read the same; it saves the GPU memory of a second finder)
        side = max(side, 1920)
    side += 2 * EDGE_PAD
    side = next((g for g in GATE_SIZES if g >= side), side)
    if side not in _gates:
        extra = [k for k in _gates if k not in GATE_SIZES]
        while len(extra) >= MAX_EXTRA_GATES:
            del _gates[extra.pop(0)]   # the oldest big one (dicts keep insertion order)
        _gates[side] = Engine({
            "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.MOBILE,
            "Det.limit_type": "max", "Det.limit_side_len": side,
            "Global.use_cls": False, "Global.use_rec": False, "Global.log_level": "error", "Global.max_side_len": NO_SHRINK,
            "EngineConfig.onnxruntime.intra_op_num_threads": int(os.environ.get("LENSLATE_OCR_THREADS", "6")),
        }, GPU_MODE == "all")
    return _gates[side]


def detect(path, side=1280):
    if READER == "meiki" and FINDER != "paddle":
        return _meiki_find(_bgr(path))
    img = _pad(Image.open(path).convert("RGB"), EDGE_PAD)
    r = _gate(side)(img)
    out = []
    for box in ([] if r.boxes is None else r.boxes):
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        out.append([float(min(xs)) - EDGE_PAD, float(min(ys)) - EDGE_PAD, float(max(xs)) - EDGE_PAD, float(max(ys)) - EDGE_PAD])
    return out


def read(path, scale=1.0):
    if READER == "meiki":     # find the lines, then read them with meikiocr (it scales every line to 32 px itself)
        boxes = detect(path, 4096)
        return [{"box": r["box"], "text": r["text"], "score": r["score"]} for r in meiki_read_lines(path, boxes)]
    img = Image.open(path).convert("RGB")
    if scale != 1.0:  # small text: OCR misses lines and characters below ~20 px, so read it enlarged
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    pad = EDGE_PAD
    if min(img.size) < MIN_SIDE:
        pad = max(pad, (MIN_SIDE - min(img.size)) // 2 + 8)
    img = _pad(img, pad)
    r = engine(img)
    out = []
    if r.boxes is not None:
        for box, text, score in zip(r.boxes, r.txts, r.scores):
            xs = [p[0] for p in box]; ys = [p[1] for p in box]
            out.append({"box": [float(v - pad) / scale for v in (min(xs), min(ys), max(xs), max(ys))],
                        "text": text, "score": float(score)})
    return out


# the *recogniser* alone: reads text lines, no detection (the fast detector already found the lines;
# running the full OCR again on the same spot cost ~0.3-0.6 s per read)
_rec_params = {
    "Rec.ocr_version": REC_MODEL[0], "Rec.model_type": REC_MODEL[1], **REC_LANG,
    "Global.use_det": False, "Global.use_cls": False, "Global.log_level": "error",
    "EngineConfig.onnxruntime.intra_op_num_threads": int(os.environ.get("LENSLATE_OCR_THREADS", "6")),
}
# recogniser on the graphics card in "reader" and "all" modes: ~12x faster line reading (4 dialogue lines: 0.02 s
# instead of 0.22 s) for ~0.4 GB of GPU memory, capped at 512 MB
OCR_GPU = GPU_MODE in ("reader", "all")
_rec_params_cpu = dict(_rec_params)
_rec_cpu = None   # processor recogniser, made the first time the graphics card runs out of its memory share
if OCR_GPU:
    _rec_params.update(_CUDA)
    _rec_params["EngineConfig.onnxruntime.cuda_ep_cfg.gpu_mem_limit"] = 512 * 1024 * 1024
_rec_engine = RapidOCR(params=_rec_params)
MAX_RATIO = 9.0   # the recogniser fails on very wide line images (a 790x53 English line came back empty): cut them


def _pieces(arr, h):
    """Cut a line image (numpy, H x W x 3) into pieces no wider than MAX_RATIO * h. Each cut goes in the middle of
    the widest empty gap near it (between words, or between Chinese/Japanese characters).
    Returns [(start, end, gap_before_px)]: gap_before_px = width of the gap the piece was cut from."""
    import numpy as np
    w = arr.shape[1]
    target = int(MAX_RATIO * h)
    if w <= target:
        return [(0, w, 0)]
    gray = arr.mean(axis=2)
    border = np.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]])
    empty = (np.abs(gray - np.median(border)) > 40).sum(axis=0) == 0
    out, start, gap = [], 0, 0
    while w - start > target:
        lo, hi = start + int(0.5 * target), start + target
        best, best_w, i = None, 0, lo
        while i < hi:   # widest run of empty columns in the window
            if empty[i]:
                j = i
                while j < w and empty[j]:
                    j += 1
                if j - i > best_w:
                    best, best_w = (i + j) // 2, j - i
                i = j
            else:
                i += 1
        cut = best if best is not None else hi
        out.append((start, cut, gap))
        start, gap = cut, best_w
    out.append((start, w, gap))
    return out


def _recognise(rec, jobs, TextRecInput):
    """Recognise line images. On the graphics card a batch of very wide lines (long paragraph lines, big 4K text)
    can exceed the reader's memory cap: then the batch is retried in small chunks, and if that fails too it is read
    on the processor (same model, same text; slower)."""
    try:
        return rec(TextRecInput(img=jobs))
    except Exception as e:  # noqa: BLE001
        if not OCR_GPU:
            raise
        print("lenslate OCR: graphics card could not read %d lines at once (%s); retrying in small chunks"
              % (len(jobs), str(e)[-80:]), file=sys.stderr, flush=True)
    txts, scores = [], []
    try:
        for i in range(0, len(jobs), 2):
            r = rec(TextRecInput(img=jobs[i:i + 2]))
            txts += list(r.txts)
            scores += list(r.scores)
        return type("Rec", (), {"txts": txts, "scores": scores})()
    except Exception as e:  # noqa: BLE001
        print("lenslate OCR: still too big for the graphics card (%s); these lines are read on the processor"
              % str(e)[-80:], file=sys.stderr, flush=True)
    global _rec_cpu
    if _rec_cpu is None:
        _rec_cpu = RapidOCR(params=_rec_params_cpu)._load_rec_model()
    return _rec_cpu(TextRecInput(img=jobs))


VERTICAL_RATIO = 1.5   # a line box this many times taller than wide is a vertical column (RapidOCR's own rule)


def _is_column(b):
    return (b[3] - b[1]) >= VERTICAL_RATIO * (b[2] - b[0]) and (b[2] - b[0]) >= 8


def join_row_boxes(boxes):
    """Join finder boxes that are pieces of one line: same row (they overlap vertically by at least 60% of the
    smaller height) and at most a word gap apart. The finder often returns English words, or parts of words, as
    separate boxes; read one by one with a margin, neighbours overlapped and repeated letters ("Hey, d" + "y, do you
    see th" + "e that light ...", "Load C" + "d Game") - testbench 2026-11-10. Columns further apart stay separate
    (a label and its value)."""
    out = [list(map(float, b)) for b in boxes]
    joined = True
    while joined:              # until nothing joins any more (a joined box can now reach a third one)
        joined = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                a, b = out[i], out[j]
                h = min(b[3] - b[1], a[3] - a[1])
                if h <= 0 or _is_column(a) or _is_column(b):
                    continue   # vertical columns side by side are separate lines, never one wide row
                same_row = min(b[3], a[3]) - max(b[1], a[1]) >= 0.6 * h
                gap = max(b[0], a[0]) - min(b[2], a[2])   # negative = they overlap
                if same_row and gap <= 0.9 * h:
                    out[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del out[j]
                    joined = True
                    break
            if joined:
                break
    return sorted(out, key=lambda b: (b[1], b[0]))


def read_lines(path, boxes, latin_matters=True):
    """Read the given line boxes ([x1,y1,x2,y2] in the image) with the recogniser only, all in one batch. Pieces of
    one line are joined first (join_row_boxes)."""
    import numpy as np
    from rapidocr.ch_ppocr_rec import TextRecInput
    boxes = join_row_boxes(boxes)
    rec = _rec_engine._load_rec_model()
    img = np.array(Image.open(path).convert("RGB"))
    H, W = img.shape[:2]
    jobs, owners = [], []
    for li, (x1, y1, x2, y2) in enumerate(boxes):
        # a vertical column (tategaki): turned a quarter to the left so it reads as a line, as RapidOCR's full
        # read does (the reader only reads horizontal lines: a column came back as "20")
        vertical = _is_column((x1, y1, x2, y2))
        h = max(1.0, (x2 - x1) if vertical else (y2 - y1))   # the line's thickness
        # a little room around the line: the fast detector's boxes are tight and clip ascenders/descenders
        along, across = 0.35 * h, 0.2 * h
        mx, my = (across, along) if vertical else (along, across)
        cx1, cy1 = max(0, int(x1 - mx)), max(0, int(y1 - my))
        cx2, cy2 = min(W, int(x2 + mx)), min(H, int(y2 + my))
        if cx2 - cx1 < 4 or cy2 - cy1 < 4:
            continue
        line = img[cy1:cy2, cx1:cx2]
        if vertical:
            line = np.rot90(line)
        for a, b, gap in _pieces(line, line.shape[0]):
            jobs.append(np.ascontiguousarray(line[:, a:b]))
            owners.append((li, gap >= 0.25 * h))
    if not jobs:
        return []
    res = _recognise(rec, jobs, TextRecInput)
    texts, scores = {}, {}
    for (li, word_gap), t, sc in zip(owners, res.txts, res.scores):
        t = (t or "").strip()
        if not t:
            continue
        prev = texts.get(li, "")
        # a piece cut at a word-sized gap of a Latin line: put the space back
        sep = " " if prev and word_gap and prev[-1].isascii() and t[0].isascii() else ""
        texts[li] = prev + sep + t
        scores[li] = min(scores.get(li, 1.0), float(sc))
    out = []
    for li, (x1, y1, x2, y2) in enumerate(boxes):
        t, sc = texts.get(li, ""), scores.get(li, 0.0)
        letters = [c for c in t if c.isalpha()]
        latin = bool(letters) and sum(c.isascii() for c in letters) >= 0.5 * len(letters)
        # unsure: the caller reads the whole area again with the full OCR (the recogniser alone drops words on
        # wide Latin lines, and an empty/low-score result may be a detector box that clipped the text)
        if (not t) or (sc < 0.3 and len(t) <= 2):
            continue   # an icon or a decoration the fast detector took for text: not text
        out.append({"box": [float(x1), float(y1), float(x2), float(y2)], "text": t, "score": sc,
                    "unsure": sc < 0.5 or (latin and latin_matters)})
    return out


# ------------------------------------------------------------------------------------------- meikiocr reader
READER = os.environ.get("LENSLATE_OCR_READER", "paddle")      # paddle | meiki
# where meiki finds its lines: "paddle" = the PaddleOCR mobile finder (full resolution, no line limit); "meiki" =
# meikiocr's own finder on the whole area (it shrinks the area to 960x544 and keeps at most 64 lines); "tiles" =
# meikiocr's finder on tiles of about 960x544 (64 lines per tile), lines cut by a tile edge joined again; "auto" =
# whole area up to about 1080p (measured best there: 0.16-0.63 s a screen), tiles above (a 4K area would be shrunk 4x)
FINDER = os.environ.get("LENSLATE_OCR_FINDER", "auto")
MEIKI_RATIO = 26.0   # meikiocr reads a 960x32 strip: longer lines are squeezed into garbage, so they are cut into pieces
_meiki = [None]


def meiki():
    if _meiki[0] is None:
        import onnxruntime as ort
        orig = ort.SessionOptions

        def opts(*a, **k):    # meikiocr makes its own sessions with every core: cap them like ours
            o = orig(*a, **k)
            o.intra_op_num_threads = int(os.environ.get("LENSLATE_OCR_THREADS", "6"))
            return o
        ort.SessionOptions = opts
        orig_sess = ort.InferenceSession
        gpu = GPU_MODE == "all" and _CUDA is not None
        cap = int(os.environ.get("LENSLATE_MEIKI_GPU_MB", "512")) * 1024 * 1024

        def sess(path, *a, **k):   # graphics card: capped arena, grown only as needed (it took 1.6 GB uncapped)
            if gpu:
                k["providers"] = [("CUDAExecutionProvider", {"gpu_mem_limit": cap,
                                                             "arena_extend_strategy": "kSameAsRequested",
                                                             "cudnn_conv_algo_search": "HEURISTIC"}),
                                  "CPUExecutionProvider"]
            return orig_sess(path, *a, **k)
        ort.InferenceSession = sess
        try:
            from meikiocr import MeikiOCR
            # on the graphics card (Reading on: GPU): measured on 7 1080p screens 1.27 s / 1.3 core-s instead of
            # 3.0 s / 13.7 core-s on the processor
            _meiki[0] = MeikiOCR(provider="CUDAExecutionProvider" if gpu else "CPUExecutionProvider",
                                 max_batch_size=int(os.environ.get("LENSLATE_MEIKI_BATCH", "2" if gpu else "8")))
        finally:
            ort.SessionOptions = orig
            ort.InferenceSession = orig_sess
    return _meiki[0]


def _bgr(path):
    import numpy as np
    return np.ascontiguousarray(np.array(Image.open(path).convert("RGB"))[:, :, ::-1])


def _meiki_find(img):
    """Line boxes [x1,y1,x2,y2] from meikiocr's finder (whole area or tiles)."""
    m = meiki()
    H, W = img.shape[:2]
    if FINDER == "meiki" or (W <= 1000 and H <= 600) or (FINDER == "auto" and W * H <= 1.2 * 1920 * 1080):
        return [list(map(float, b["bbox"])) for b in m.run_detection(img)]
    cols, rows = -(-W // 960), -(-H // 544)
    tw, th = -(-W // cols), -(-H // rows)
    ov = TILE_OVERLAP
    boxes, seams = [], [c * tw for c in range(1, cols)]
    seams_y = [r * th for r in range(1, rows)]
    for r in range(rows):
        for c in range(cols):
            x0, y0 = max(0, c * tw - ov), max(0, r * th - ov)
            x1, y1 = min(W, (c + 1) * tw + ov), min(H, (r + 1) * th + ov)
            for b in m.run_detection(np.ascontiguousarray(img[y0:y1, x0:x1])):
                bx = b["bbox"]
                boxes.append([float(bx[0] + x0), float(bx[1] + y0), float(bx[2] + x0), float(bx[3] + y0)])
    return _merge_tiles(boxes, seams, seams_y)


TILE_OVERLAP = 32   # px each tile reaches past its edge


def _merge_tiles(boxes, seams, seams_y=()):
    """Drop the copies found twice in a tile overlap, and join a line that a tile edge cut in two (a row at a
    vertical seam, a column at a horizontal seam). The two halves can overlap by up to twice TILE_OVERLAP: both
    tiles see that strip, so before, a line crossing a seam stayed two lines with the overlap read twice
    ("最後のチェックポイ" + "ントが記録されます")."""
    reach = 2 * TILE_OVERLAP + 16
    def area(b):
        return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])

    out = []
    for b in sorted(boxes, key=area, reverse=True):
        dup = False
        for o in out:
            ix = max(0.0, min(b[2], o[2]) - max(b[0], o[0]))
            iy = max(0.0, min(b[3], o[3]) - max(b[1], o[1]))
            if ix * iy >= 0.6 * area(b):
                dup = True
                break
        if not dup:
            out.append(list(b))
    joined = True
    while joined:
        joined = False
        for i, a in enumerate(out):
            for j, b in enumerate(out):
                if i == j:
                    continue
                h = min(a[3] - a[1], b[3] - b[1])
                w = min(a[2] - a[0], b[2] - b[0])
                if h <= 0 or w <= 0:
                    continue
                if _is_column(a) and _is_column(b):   # a vertical column cut by a horizontal seam
                    same_col = min(a[2], b[2]) - max(a[0], b[0]) >= 0.5 * w
                    near = -(reach + 0.5 * w) <= b[1] - a[3] <= 0.6 * w
                    at_seam = any(abs(a[3] - s) < reach or abs(b[1] - s) < reach for s in seams_y)
                    ok = same_col and near and at_seam and a[1] < b[1]
                else:
                    same_row = min(a[3], b[3]) - max(a[1], b[1]) >= 0.5 * h
                    near = -(reach + 0.5 * h) <= b[0] - a[2] <= 0.6 * h
                    at_seam = any(abs(a[2] - s) < reach or abs(b[0] - s) < reach for s in seams)
                    ok = same_row and near and at_seam and a[0] < b[0] and b[2] > a[2]
                if ok:
                    out[i] = [a[0], min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del out[j]
                    joined = True
                    break
            if joined:
                break
    out.sort(key=lambda b: (b[1], b[0]))
    return out


def meiki_read_lines(path, boxes):
    """Read line boxes with meikiocr. Long lines are cut into pieces at gaps (it reads at most ~48 characters);
    lines that come back mostly Latin are read again by the PaddleOCR reader (meikiocr drops spaces)."""
    m = meiki()
    img = _bgr(path)
    H, W = img.shape[:2]
    rgb = np.ascontiguousarray(img[:, :, ::-1])
    pieces, owners, crops = [], [], []
    vert = []   # indexes (into pieces) of vertical columns: meikiocr's own vertical reader, no cutting
    for li, (x1, y1, x2, y2) in enumerate(boxes):
        if _is_column((x1, y1, x2, y2)):
            w = max(1.0, x2 - x1)
            cx1, cy1 = max(0, int(x1 - 0.15 * w)), max(0, int(y1 - 0.2 * w))
            cx2, cy2 = min(W, int(x2 + 0.15 * w)), min(H, int(y2 + 0.2 * w))
            if cx2 - cx1 < 4 or cy2 - cy1 < 4:
                continue
            crops.append((li, (cx1, cy1, cx2, cy2)))
            vert.append(len(pieces))
            pieces.append({"bbox": [cx1, cy1, cx2, cy2]})   # (it splits long columns itself, with overlap)
            owners.append((li, False))
            continue
        h = max(1.0, y2 - y1)
        cx1, cy1 = max(0, int(x1 - 0.2 * h)), max(0, int(y1 - 0.15 * h))
        cx2, cy2 = min(W, int(x2 + 0.2 * h)), min(H, int(y2 + 0.15 * h))
        if cx2 - cx1 < 4 or cy2 - cy1 < 4:
            continue
        crops.append((li, (cx1, cy1, cx2, cy2)))
        line = rgb[cy1:cy2, cx1:cx2]
        global MAX_RATIO
        keep, MAX_RATIO = MAX_RATIO, MEIKI_RATIO
        try:
            cuts = _pieces(line, cy2 - cy1)
        finally:
            MAX_RATIO = keep
        for a, b, gap in cuts:
            pieces.append({"bbox": [cx1 + a, cy1, cx1 + b, cy2]})
            owners.append((li, gap >= 0.25 * h))
    if not pieces:
        return []
    res = [{"text": "", "chars": [], "is_vertical": False} for _ in pieces]
    horiz = [i for i in range(len(pieces)) if i not in set(vert)]
    if horiz:
        m._process_recognition_pipeline(img, pieces, horiz, res, 0.1, 1.0, False)
    if vert:   # before, columns went through the horizontal reader too and came back as garbage ("oeE")
        m._process_recognition_pipeline(img, pieces, vert, res, 0.1, 1.0, True)
    texts, scores = {}, {}
    for (li, word_gap), r in zip(owners, res):
        t = (r.get("text") or "").strip()
        if not t:
            continue
        confs = [c.get("conf", 1.0) for c in r.get("chars") or []]
        prev = texts.get(li, "")
        sep = " " if prev and word_gap and prev[-1].isascii() and t[0].isascii() else ""
        texts[li] = prev + sep + t
        scores[li] = min(scores.get(li, 1.0), sum(confs) / len(confs) if confs else 0.5)
    # Latin lines: the PaddleOCR reader keeps the spaces and reads English far better
    latin = [li for li, t in texts.items()
             if sum(c.isascii() and c.isalpha() for c in t) >= 0.5 * max(1, sum(c.isalpha() for c in t))
             and sum(c.isalpha() for c in t) >= 2]
    if latin:
        redo = read_lines(path, [boxes[li] for li in latin], False)
        by_box = {tuple(r["box"]): r for r in redo}
        for li in latin:
            r = by_box.get(tuple(float(v) for v in boxes[li]))
            if r:
                texts[li], scores[li] = r["text"], r["score"]
    out = []
    for li, (x1, y1, x2, y2) in enumerate(boxes):
        t, sc = texts.get(li, ""), scores.get(li, 0.0)
        if not t or (sc < 0.3 and len(t) <= 2):
            continue
        out.append({"box": [float(x1), float(y1), float(x2), float(y2)], "text": t, "score": float(sc),
                    "unsure": sc < 0.5})
    return out


def main():
    send({"ready": True})
    for line in sys.stdin:
        req = None
        try:
            req = json.loads(line)
            t = time.time()
            if req.get("op") == "read_lines":
                lines = (meiki_read_lines(req["path"], req["boxes"]) if READER == "meiki" else
                         read_lines(req["path"], req["boxes"], bool(req.get("latin_matters", True))))
                resp = {"lines": lines, "secs": round(time.time() - t, 3)}
            elif req.get("op") == "detect":
                resp = {"boxes": detect(req["path"], int(req.get("side", 1280))), "secs": round(time.time() - t, 3)}
            else:
                lines = read(req["path"], float(req.get("scale", 1.0)))
                resp = {"lines": lines, "secs": round(time.time() - t, 3)}
        except Exception as e:  # noqa: BLE001
            resp = {"error": "%s: %s" % (type(e).__name__, e)}
        send(resp, req if isinstance(req, dict) else None)


if __name__ == "__main__":
    main()
