"""`lenslate ocr-gpu install | remove | status`: read text on the graphics card (NVIDIA, CUDA 12).

Swaps the engine environment's OCR runtime (onnxruntime, processor only) for its CUDA build plus NVIDIA's runtime
libraries from pip (about 3.4 GB; no system CUDA install needed), then [ocr] gpu uses it: "reader" = only the
text reader on the GPU (~0.4 GB); "all" = finding and reading on the GPU (~1.6 GB, the Fastest preset). `remove`
swaps back.
"""
import os
import shutil
import subprocess

import config as cfgmod

ENGINE_PY = os.path.join(cfgmod.DATA_DIR, "engine", "bin", "python")
GPU_PKG = "onnxruntime-gpu[cuda,cudnn]==1.23.2"     # tested with RapidOCR 3.10 on an RTX 4060
CPU_PKG = "onnxruntime==1.31.1"


def _uv(*args):
    uv = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
    subprocess.run([uv, "pip"] + list(args) + ["--python", ENGINE_PY], check=True)


_INSTALLED = [None]   # once found installed, it stays installed for this process (install()/remove() reset it)


def installed():
    """Is the CUDA build of the text reader in lenslate's engine? (starts the engine's Python: ~0.1 s, longer
    when the PC is busy; a failure or timeout is retried once and never remembered as 'not installed')."""
    if _INSTALLED[0]:
        return True
    for _attempt in range(2):
        try:
            out = subprocess.run([ENGINE_PY, "-I", "-c", "import onnxruntime as o; print(','.join(o.get_available_providers()))"],
                                 capture_output=True, text=True, timeout=60).stdout
            if "CUDAExecutionProvider" in out:
                _INSTALLED[0] = True
                return True
            if out.strip():          # the engine answered: really not installed
                return False
        except (OSError, subprocess.SubprocessError):
            pass
    return False


def has_nvidia():
    return shutil.which("nvidia-smi") is not None


def _swap(old, new_pkg, old_pkg):
    """Replace one onnxruntime build by the other (both use the same module folder, so the old one must go first).
    If installing the new one fails (no network, disk full), the old one is put back: before, a failed GPU install
    left the engine with no onnxruntime at all and OCR stopped working."""
    _uv("uninstall", old)
    try:
        _uv("install", new_pkg)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        try:
            _uv("install", old_pkg)
        except (RuntimeError, OSError, subprocess.SubprocessError):
            pass
        raise


def install():
    if not has_nvidia():
        raise RuntimeError("no NVIDIA graphics card found (nvidia-smi missing); GPU OCR needs one")
    _swap("onnxruntime", GPU_PKG, CPU_PKG)
    _INSTALLED[0] = None
    cfgmod.set("ocr.gpu", "reader" if cfgmod.get("ocr.gpu") == "off" else cfgmod.get("ocr.gpu"))


def remove():
    _swap("onnxruntime-gpu", CPU_PKG, GPU_PKG)
    _INSTALLED[0] = None
    cfgmod.set("ocr.gpu", "off")


def cli(args):
    cmd = args[0] if args else "status"
    try:
        if cmd == "install":
            print("installing the CUDA build of the OCR runtime (about 3.4 GB) ...")
            install()
            print("done: text is read on the graphics card (restart lenslate: lenslate quit)")
        elif cmd == "remove":
            remove()
            print("removed: text is read on the processor again (restart lenslate: lenslate quit)")
        else:
            print("GPU OCR: %s, setting [ocr] gpu = %s" % ("installed" if installed() else "not installed",
                                                          cfgmod.get("ocr.gpu")))
            print("usage: lenslate ocr-gpu install | remove | status")
    except (RuntimeError, subprocess.CalledProcessError) as e:
        print("lenslate: %s" % e)
        return 1
    return 0
