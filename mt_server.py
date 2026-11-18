#!/usr/bin/env python3
"""Light CPU translator helper for lenslate. Runs inside mt-venv (CTranslate2 + sentencepiece) and keeps the model
loaded. Default model: quickmt-ja-en (200M-parameter Japanese->English transformer, int8 on CPU, ~0.4 GB RAM,
no GPU at all), at ~/.local/share/lenslate/models/quickmt-ja-en (LENSLATE_MT_MODEL to change).

Protocol: one JSON object per line on stdin  {"texts": ["...", ...]}
          one JSON object per line on stdout {"out": ["...", ...], "secs": float}  or {"error": str}
          An "id" in the request is echoed in its answer.
"""
import json
import os
import re
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

import ctranslate2
import sentencepiece as spm

MODEL = os.path.expanduser(os.environ.get("LENSLATE_MT_MODEL", "~/.local/share/lenslate/models/quickmt-ja-en"))
THREADS = int(os.environ.get("LENSLATE_MT_THREADS", "4"))

translator = ctranslate2.Translator(MODEL, device="cpu", compute_type="int8", intra_threads=THREADS)


def spm_file(*names):
    for n in names:
        if os.path.exists(os.path.join(MODEL, n)):
            return os.path.join(MODEL, n)
    raise FileNotFoundError("no sentencepiece model in %s (%s)" % (MODEL, names))


# quickmt: src/tgt.spm.model; Sugoi (fairseq export): spm/spm.ja|en.nopretok.model; OPUS-MT (Marian): source/target.spm
src_sp = spm.SentencePieceProcessor(model_file=spm_file("src.spm.model", "spm/spm.ja.nopretok.model", "source.spm"))
tgt_sp = spm.SentencePieceProcessor(model_file=spm_file("tgt.spm.model", "spm/spm.en.nopretok.model", "target.spm"))
MARIAN = os.path.exists(os.path.join(MODEL, "source.spm"))
# multi-target OPUS models need the target language as a first token, e.g. >>pob<< = Brazilian Portuguese
TARGET_TAG = os.environ.get("LENSLATE_MT_TARGET_TAG", "")

# a sentence-level model: split a block into sentences and translate them together as a batch
OPEN, CLOSE = "「『（(【", "」』）)】"
CJK_END = "。！？!?…"
QUOTE_PARTICLES = "とっはをもの"   # 「...」と彼は言った: the quote belongs to the sentence that follows
LATIN_BREAK = re.compile(r"[.!?]\s+(?=[A-Z0-9\"'(¿¡])")
ABBREV = re.compile(r"(\b(Mr|Mrs|Ms|Dr|St|Sr|Jr|Prof|vs|etc|No|Vol|e\.g|i\.e)|\b[A-Z])\.$")


def split(text):
    """Sentences of a block. Never inside 「...」 quotes (a quoted sentence lost its quote marks and was translated
    in two halves), never after an abbreviation such as "Mr." or an initial."""
    text = re.sub(r"\s+", " ", text).strip()
    parts, cur, depth, i = [], "", 0, 0
    while i < len(text):
        ch = text[i]
        cur += ch
        if ch in OPEN:
            depth += 1
        elif ch in CLOSE:
            depth = max(0, depth - 1)
            if depth == 0 and ch in "」』" and not (i + 1 < len(text) and text[i + 1] in QUOTE_PARTICLES):
                while i + 1 < len(text) and text[i + 1] in CJK_END:   # 「...」。 keeps its full stop
                    i += 1
                    cur += text[i]
                parts.append(cur)
                cur = ""
        elif depth == 0 and ch in "。！？":
            while i + 1 < len(text) and text[i + 1] in CJK_END + "」』":
                i += 1
                cur += text[i]
            parts.append(cur)
            cur = ""
        elif depth == 0 and ch in ".!?":
            m = LATIN_BREAK.match(text, i)
            if m and not (ch == "." and ABBREV.search(cur)):
                parts.append(cur)
                cur = ""
        i += 1
    parts.append(cur)
    parts = [p.strip() for p in parts if p.strip()]
    return parts or [text]


CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff00-\uffef。、！？「」『』]")


def join(pieces):
    """Translated sentences back into one text: no space between Chinese (or Japanese) sentences."""
    out = ""
    for p in (x.strip() for x in pieces):
        if not p:
            continue
        if not out:
            out = p
        elif CJK.match(out[-1]) and CJK.match(p[0]):
            # Chinese: no space; the sentences were split at a full stop, which the model sometimes drops
            out += p if out[-1] in "。！？!?…」』，、" else "。" + p
        else:
            out += " " + p
    return out


def translate(texts):
    pieces, owner = [], []
    for i, t in enumerate(texts):
        for s in split(t):
            toks = src_sp.encode(s, out_type=str)
            if MARIAN:   # Marian models expect the end-of-sentence token on the source (and the target tag first)
                toks = ([TARGET_TAG] if TARGET_TAG else []) + toks + ["</s>"]
            pieces.append(toks)
            owner.append(i)
    if not pieces:
        return [""] * len(texts)
    res = translator.translate_batch(pieces, beam_size=4, max_decoding_length=256, max_batch_size=32)
    out = [[] for _ in texts]
    for i, r in zip(owner, res):
        out[i].append(tgt_sp.decode([t for t in r.hypotheses[0] if t != "<unk>"]))
    return [join(x) for x in out]


def main():
    send({"ready": True})
    for line in sys.stdin:
        req = None
        try:
            req = json.loads(line)
            t0 = time.time()
            out = translate(req.get("texts", []))
            send({"out": out, "secs": round(time.time() - t0, 3)}, req)
        except Exception as e:  # never die on one bad request
            send({"error": repr(e)}, req if isinstance(req, dict) else None)


if __name__ == "__main__":
    main()
