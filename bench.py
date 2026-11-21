"""Speed measurement on this PC, for the Presets page ("≈ 0.40 s per new line on this PC").

Runs once (the window asks first; about 1-2 minutes): reads a rendered Japanese dialogue box in every reading mode,
three whole screens (SCENES) in every mode on the processor and the graphics card, and translates four lines with
every installed translator (quickmt, Sugoi, the language model).
The result is saved with the hardware it was measured on, so a new CPU or GPU triggers a new measurement.
"""
import json
import os
import re
import subprocess
import time

import config as cfgmod

PATH = os.path.join(cfgmod.CACHE_DIR, "benchmark.json")
LINES = ["とにかく進んでみましょう。ここに見取り図がありますし。", "最後のチェックポイントが記録されます。",
         "アビリティ変更", "あっ！敵が来てますよ！安全じゃなかったんですね！"]
# Whole screens for the per-screen estimate (best / typical / worst): read with every reading mode on the processor
# and on the graphics card. The tiny dialogue sample above reads the same in every mode; these do not.
SCENES = (("menu", "Menu", "1-title-menu.png"), ("settings", "Settings screen", "10-en-settings.png"),
          ("wall", "Wall of text", "4-wall-of-text.png"))
OVERHEAD = 0.12   # capture + change check + card drawing per refresh (measured in debug runs: ~0.1-0.15 s)


_HW = []


def hardware():
    """Processor and graphics card names (they do not change while lenslate runs: asked once)."""
    if not _HW:
        _HW.append(_hardware())
    return _HW[0]


def _hardware():
    cpu = "unknown CPU"
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    gpu, vram = None, 0
    try:
        run = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5)
        # a switched-off card (hybrid laptops) or a missing driver: nvidia-smi prints an error message, not data
        out = run.stdout.strip().splitlines() if run.returncode == 0 else []
        if out:
            name, mb = out[0].rsplit(",", 1)
            gpu, vram = name.strip(), int(mb)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return {"cpu": cpu, "gpu": gpu, "vram_mb": vram}


def gpu_now():
    """(utilisation %, memory used MB, memory total MB) or None."""
    try:
        u, m, t = [int(x) for x in subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2).stdout.split(",")]
        return u, m, t
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def load():
    try:
        with open(PATH) as f:
            data = json.load(f)
        return data if data.get("hw") == hardware() else None
    except (OSError, ValueError):
        return None


def _finder_side(path):
    """The finder size the real refresh uses for a whole area this big (OcrPipeline: min(1920, longest side)).
    Measure again used the 1280 default, so it timed Quick on whole screens with a smaller finder than in play."""
    from PySide6.QtGui import QImageReader
    size = QImageReader(path).size()
    return min(1920, max(size.width(), size.height(), 1))


def _sample_image(path):
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    img = QImage(960, 200, QImage.Format_RGB32)
    img.fill(QColor(25, 25, 35))
    p = QPainter(img)
    f = QFont("Noto Sans CJK JP")
    f.setPixelSize(28)
    p.setFont(f)
    p.setPen(QColor(240, 240, 240))
    p.drawText(40, 70, LINES[0])
    p.drawText(40, 125, LINES[3])
    p.end()
    img.save(path)


def _cpu_s(pid):
    """Processor seconds a process has used so far (user + system)."""
    try:
        f = open("/proc/%d/stat" % pid).read().rsplit(")", 1)[1].split()
        return (int(f[11]) + int(f[12])) / os.sysconf("SC_CLK_TCK")
    except (OSError, IndexError, ValueError):
        return 0.0


def run(here, progress=lambda done, total, text="": None):
    import models
    import textflow as tf
    res = {"hw": hardware(), "date": time.strftime("%Y-%m-%d %H:%M")}
    os.makedirs(cfgmod.CACHE_DIR, exist_ok=True)
    img = os.path.join(cfgmod.CACHE_DIR, "benchmark-sample.png")
    _sample_image(img)
    import ocrgpu
    steps = 100  # percent; whole screens take most of the time (18-78)
    progress(0, steps, "Starting the text reader (processor)")
    cpu = {"LENSLATE_OCR_GPU": "off", "LENSLATE_OCR_READER": "paddle"}   # the processor numbers, whatever is set
    ocr = tf.OcrClient(here, env=cpu)
    try:   # (every helper is stopped even when a measurement fails: a GPU one holds ~1.6 GB of graphics memory)
        ocr.read(img)                                  # warm up (model load)
        progress(4, steps, "Dialogue box: Careful reading, processor")
        c, t = _cpu_s(ocr.proc.pid), time.time()
        ocr.read(img); ocr.read(img)
        res["ocr_accurate"], res["cpu_accurate"] = (time.time() - t) / 2, (_cpu_s(ocr.proc.pid) - c) / 2
        progress(7, steps, "Dialogue box: Quick reading, processor")
        c, t = _cpu_s(ocr.proc.pid), time.time()
        for _ in range(2):
            boxes, _s = ocr.detect(img, _finder_side(img))
            ocr.read_lines(img, boxes)
        res["ocr_fast"], res["cpu_fast"] = (time.time() - t) / 2, (_cpu_s(ocr.proc.pid) - c) / 2
    finally:
        ocr.stop()
    progress(10, steps, "Dialogue box: Ultrafast reading, processor")
    try:     # meikiocr finds and reads (Ultrafast preset)
        ocr = tf.OcrClient(here, env=dict(cpu, LENSLATE_OCR_READER="meiki"))
        boxes, _s = ocr.detect(img, _finder_side(img))
        ocr.read_lines(img, boxes)                     # load
        c, t = _cpu_s(ocr.proc.pid), time.time()
        for _ in range(2):
            boxes, _s = ocr.detect(img, _finder_side(img))
            ocr.read_lines(img, boxes)
        res["ocr_ultrafast"], res["cpu_ultrafast"] = (time.time() - t) / 2, (_cpu_s(ocr.proc.pid) - c) / 2
    except Exception:  # noqa: BLE001 - meikiocr missing: the estimate says "not measured"
        res["ocr_ultrafast"] = res["cpu_ultrafast"] = None
    finally:
        ocr.stop()
    res["ocr_gpu_all"] = res["cpu_gpu_all"] = res["ocr_gpu_fast"] = res["cpu_gpu_fast"] = None
    if ocrgpu.installed():
        progress(13, steps, "Dialogue box: Careful and Quick, graphics card")
        try:
            ocr = tf.OcrClient(here, env=dict(cpu, LENSLATE_OCR_GPU="all"))
            ocr.read(img); ocr.read(img)               # load + first GPU run
            c, t = _cpu_s(ocr.proc.pid), time.time()
            ocr.read(img); ocr.read(img)
            res["ocr_gpu_all"], res["cpu_gpu_all"] = (time.time() - t) / 2, (_cpu_s(ocr.proc.pid) - c) / 2
            c, t = _cpu_s(ocr.proc.pid), time.time()
            for _ in range(2):                         # quick reading on the graphics card (Fastest)
                boxes, _s = ocr.detect(img, _finder_side(img))
                ocr.read_lines(img, boxes)
            res["ocr_gpu_fast"], res["cpu_gpu_fast"] = (time.time() - t) / 2, (_cpu_s(ocr.proc.pid) - c) / 2
        except Exception:  # noqa: BLE001 - no usable GPU: the estimate says "not measured"
            pass
        finally:
            ocr.stop()

    progress(18, steps, "Whole screens")
    res["scenes"] = measure_scenes(here, res.get("ocr_gpu_all") is not None,
                                   lambda text, frac=0.0: progress(18 + 60 * frac, steps, text))

    def per_line(kind, model=None):
        tr = tf.Translator(here, os.path.join(cfgmod.CACHE_DIR, "benchmark-cache.json"), "English",
                           model or cfgmod.get("translator.llm_model"), cfgmod.get("translator.ollama_url"), kind)
        if tr.kind != kind or tr.missing_models(kind)[0]:   # its model is not downloaded: "not measured"
            tr.stop()
            return None
        try:
            tr.translate_batch(["テスト"])             # load the model first (not counted)
        except Exception:  # noqa: BLE001
            tr.stop()
            return None

        def helper_cpu():     # processor helpers (quickmt / Sugoi); the language model runs on the GPU
            return sum(_cpu_s(c.proc.pid) for c in tr.mt_clients.values() if c.proc is not None)
        c, t = helper_cpu(), time.time()
        for line in LINES:
            tr.translate_batch([line])
        dt = (time.time() - t) / len(LINES)
        res["cpu_" + kind] = (helper_cpu() - c) / len(LINES)
        tr.stop()
        return dt
    progress(80, steps, "Translating 4 lines: quickmt (processor)")
    res["mt"] = per_line("mt")
    progress(84, steps, "Translating 4 lines: Sugoi (processor)")
    res["sugoi"] = per_line("sugoi") if models.BY_NAME["sugoi-v4-ja-en"].installed() else None
    progress(88, steps, "Translating 4 lines: language model (graphics card; loading it can take a while)")
    llm_model = models.find(cfgmod.get("translator.llm_model")) or models.BY_NAME["gemma-4-e2b"]
    res["llm"] = per_line("llm", llm_model.name) if llm_model.installed() else None
    import llm
    llm.unload(llm_model.name)
    try:
        os.remove(os.path.join(cfgmod.CACHE_DIR, "benchmark-cache.json"))
    except OSError:
        pass
    with open(PATH, "w") as f:
        json.dump(res, f, indent=1)
    progress(steps, steps, "done")
    return res


def estimate(preset, data):
    """Seconds per new line for a preset on this PC, or None if a needed part was not measured."""
    if not data:
        return None
    v = cfgmod.values_of(preset)
    ocr = data.get(_ocr_key(v, "ocr"))
    tr = data.get({"llm": "llm", "mt": "mt", "sugoi": "sugoi"}.get(v["translator.kind"], "-"))
    if ocr is None or tr is None:
        return None
    wait = v.get("refresh.settle_step", 0) * 3 if v.get("refresh.settle_step") else 0   # typewriter checks
    return OVERHEAD + ocr + tr + wait


def measure_scenes(here, gpu, progress=lambda text, frac=0.0: None, repeats=3):
    """Whole-screen reading times for every reading mode on the processor (and graphics card): the MEDIAN of
    `repeats` reads after a warm-up read, so one slow moment (another program, clock changes) does not move the
    estimate. Returns {scene: {"title", "lines", "<mode>_<cpu|gpu>": seconds}}."""
    import statistics
    import textflow as tf
    scenes = {key: {"title": title} for key, title, _f in SCENES}
    shots = {key: os.path.join(here, "samples", "testbench", fn) for key, _t, fn in SCENES}
    # each helper gets its settings as env= (never os.environ: the GUI reads settings in this process)
    runs_plan = [(d, r) for d in ["cpu"] + (["gpu"] if gpu else []) for r in ("paddle", "meiki")]
    for n, (dev, reader) in enumerate(runs_plan):
        env = {"LENSLATE_OCR_GPU": "all" if dev == "gpu" else "off", "LENSLATE_OCR_READER": reader}
        label = "Whole screens, %s reading, %s" % ("Ultrafast" if reader == "meiki" else "Careful and Quick",
                                                   "graphics card" if dev == "gpu" else "processor")
        progress(label + ": starting, one untimed warm-up read of each screen", n / len(runs_plan))
        ocr = tf.OcrClient(here, env=env)
        try:
            modes = ("accurate", "fast") if reader == "paddle" else ("ultrafast",)

            def read(path, mode):
                t = time.time()
                if mode == "accurate":
                    lines, _s = ocr.read(path)
                else:
                    b, _s = ocr.detect(path, _finder_side(path))
                    lines, _s = ocr.read_lines(path, b)
                return time.time() - t, lines
            for path in shots.values():          # warm-up: every screen in every mode once, untimed
                for mode in modes:               # (the first timed screen was ~25% slow without it)
                    read(path, mode)
            for i, (key, path) in enumerate(shots.items()):
                progress("%s: %s (%d of %d)" % (label, scenes[key]["title"].lower(), i + 1, len(shots)),
                         (n + (i + 1) / (len(shots) + 1)) / len(runs_plan))
                for mode in modes:
                    runs = [read(path, mode) for _ in range(repeats)]
                    scenes[key]["%s_%s" % (mode, dev)] = statistics.median(r[0] for r in runs)
                    if mode == "accurate" and dev == "cpu":
                        scenes[key]["lines"] = len(runs[0][1])
        except Exception:  # noqa: BLE001 - e.g. meikiocr missing: that mode says "not measured"
            pass
        finally:
            ocr.stop()
    return scenes


def scene_estimates(values, data):
    """[(title, lines, best, typical, worst)] seconds until a whole screen is translated with these settings:
    best = every line translated before (only reading), typical = half the lines new, worst = every line new.
    None where not measured (Measure again)."""
    if not data or "scenes" not in data:
        return None
    mode = values.get("ocr.reading", "accurate")
    dev = "gpu" if values.get("ocr.gpu") == "all" else "cpu"
    kind = values.get("translator.kind")
    per = data.get({"llm": "llm", "mt": "mt", "sugoi": "sugoi"}.get(kind, "-"))
    out = []
    for key, title, _f in SCENES:
        sc = data["scenes"].get(key, {})
        read, n = sc.get("%s_%s" % (mode, dev)), sc.get("lines")
        if read is None or n is None:
            out.append((title, n, None, None, None))
            continue
        best = OVERHEAD + read
        out.append((title, n, best, None if per is None else best + per * n / 2,
                     None if per is None else best + per * n))
    return out


def _ocr_key(values, what):
    """Benchmark key for a preset's reading: what = "ocr" (seconds) or "cpu" (processor seconds)."""
    if values.get("ocr.gpu") == "all":
        return what + ("_gpu_fast" if values.get("ocr.reading") in ("fast", "ultrafast") else "_gpu_all")
    if values.get("ocr.reading") == "ultrafast":
        return what + "_ultrafast"
    return what + ("_fast" if values.get("ocr.reading") == "fast" else "_accurate")


def cpu_work(preset, data):
    """Processor seconds spent reading one new dialogue box with this preset (None if not measured)."""
    if not data:
        return None
    v = cfgmod.values_of(preset)
    ocr = data.get(_ocr_key(v, "cpu"))
    tr = data.get("cpu_" + v["translator.kind"], 0.0)
    return None if ocr is None else ocr + (tr or 0.0)


def needed_model(preset):
    """Catalog name of the model a preset needs (None = ships with lenslate)."""
    kind = cfgmod.values_of(preset)["translator.kind"]
    if kind == "llm":
        return cfgmod.values_of(preset).get("translator.llm_model") or cfgmod.get("translator.llm_model")
    if kind == "sugoi":
        return "sugoi-v4-ja-en"
    return None
