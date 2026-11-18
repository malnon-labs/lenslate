"""Language-model backends for lenslate: the built-in runner (llama.cpp's llama-server) or Ollama.

Built-in runner: lenslate downloads llama.cpp's official release build (Vulkan: NVIDIA, AMD and Intel graphics;
or the plain processor build) into ~/.local/share/lenslate/runtime/llama.cpp, and model files (GGUF) into the
model folder. It starts llama-server on 127.0.0.1 (config [translator] runner_port) when a translation needs it
and stops it when lenslate quits or switches to a CPU translator, so the GPU memory goes back to the game.
Nothing else needs to be installed.

Ollama: used when [translator] llm_backend = "ollama", or in "auto" mode for a model that only Ollama has.

All callers use chat(): messages in, text out (optionally streamed), whichever backend serves the model.
"""
import atexit
import json
import os
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.request

import config as cfgmod

LLAMA_BUILD = "b12110"   # pinned: the version lenslate was tested with
RELEASE = "https://github.com/ggml-org/llama.cpp/releases/download/%s/llama-%s-bin-%s.tar.gz"
FLAVORS = {"vulkan": "ubuntu-vulkan-x64", "cpu": "ubuntu-x64"}
# SHA-256 of the release archives of LLAMA_BUILD (recorded 2026-11-12): this is a program that lenslate runs, so a
# file that differs is not unpacked. When LLAMA_BUILD changes, download both archives once and put their sums here.
RELEASE_SHA256 = {"vulkan": "a5d741940956ec62e8783aee7e5a4c7c761af867d6f027c3277a51e1a3ac59b0",
                  "cpu": "368227edcc229be5f9bed16a2223d79b5e41d0ac2e19bcf5825e82291c060e55"}
RUNTIME_DIR = os.path.join(cfgmod.DATA_DIR, "runtime", "llama.cpp")


# --------------------------------------------------------------------------------------------- runtime install
def has_vulkan():
    try:
        out = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True, timeout=5).stdout
        return "libvulkan.so.1" in out
    except (OSError, subprocess.SubprocessError):
        return os.path.exists("/usr/lib64/libvulkan.so.1") or os.path.exists("/usr/lib/x86_64-linux-gnu/libvulkan.so.1")


def server_binary():
    for root, _dirs, files in os.walk(RUNTIME_DIR):
        if "llama-server" in files:
            return os.path.join(root, "llama-server")
    return None


def runtime_info():
    try:
        with open(os.path.join(RUNTIME_DIR, "installed.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def install_runtime(progress=None, flavor=None):
    """Download and unpack llama.cpp's release build. progress(done, total, status)."""
    progress = progress or (lambda *a: None)
    flavor = flavor or ("vulkan" if has_vulkan() else "cpu")
    url = RELEASE % (LLAMA_BUILD, LLAMA_BUILD, FLAVORS[flavor])
    tmp = RUNTIME_DIR + ".download"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    archive = os.path.join(tmp, "llama.tar.gz")
    req = urllib.request.Request(url, headers={"User-Agent": "lenslate"})
    with urllib.request.urlopen(req, timeout=60) as r, open(archive, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            progress(done, total, "llama.cpp %s (%s)" % (LLAMA_BUILD, flavor))
    if total and done != total:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError("llama.cpp download incomplete (%d of %d bytes); try again" % (done, total))
    want = RELEASE_SHA256.get(flavor)
    if want:
        import hashlib
        h = hashlib.sha256()
        with open(archive, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        if h.hexdigest() != want:
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError("llama.cpp %s: the downloaded file is not the one lenslate was tested with "
                               "(checksum differs); nothing was installed" % LLAMA_BUILD)
    with tarfile.open(archive) as t:
        t.extractall(tmp, filter="data")
    os.remove(archive)
    with open(os.path.join(tmp, "installed.json"), "w") as f:
        json.dump({"build": LLAMA_BUILD, "flavor": flavor}, f)
    shutil.rmtree(RUNTIME_DIR, ignore_errors=True)
    os.makedirs(os.path.dirname(RUNTIME_DIR), exist_ok=True)
    os.replace(tmp, RUNTIME_DIR)
    if not server_binary():
        raise RuntimeError("llama-server not found in the downloaded build")
    progress(1, 1, "done")
    return flavor


# ------------------------------------------------------------------------------------------------ backends
def resolve(model):
    """-> ("builtin", gguf path) or ("ollama", ollama model name) for a configured model name."""
    import models
    m = models.find(model)
    pref = cfgmod.get("translator.llm_backend")
    if m is not None:
        if pref != "ollama" and m.gguf_installed() and server_binary():
            return "builtin", m.gguf_path
        if m.ollama and pref != "builtin":
            return "ollama", m.ollama
        if pref == "builtin" or not m.ollama:
            raise RuntimeError("%s is not downloaded yet (lenslate models get %s)" % (m.title, m.name))
    if model.endswith(".gguf") and os.path.isfile(os.path.expanduser(model)):
        return "builtin", os.path.expanduser(model)
    return "ollama", model


class Runner:
    """One llama-server for this process. Several lenslate processes (overlay, hook server) share it: whoever
    needs it first starts it; the others find it on the port and use it."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.model = None
        atexit.register(self.stop)

    @property
    def port(self):
        return cfgmod.get("translator.runner_port")

    def _url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def _serving(self):
        """Path of the model the server on our port has loaded, or None if nothing answers."""
        try:
            with urllib.request.urlopen(self._url("/props"), timeout=2) as r:
                props = json.load(r)
            return props.get("model_path") or props.get("default_generation_settings", {}).get("model") or "?"
        except (OSError, ValueError):
            return None

    def ensure(self, gguf):
        with self.lock:
            serving = self._serving()
            if serving is not None and (serving == "?" or os.path.realpath(serving) == os.path.realpath(gguf)):
                self.model = gguf
                return
            if serving is not None:
                self._stop_locked(force_foreign=True)
            binary = server_binary()
            if not binary:
                raise RuntimeError("the built-in model runner is not installed (lenslate models runtime)")
            os.makedirs(cfgmod.CACHE_DIR, exist_ok=True)
            log = open(os.path.join(cfgmod.CACHE_DIR, "llama-server.log"), "a")
            cmd = [binary, "-m", gguf, "--host", "127.0.0.1", "--port", str(self.port),
                   "-c", str(cfgmod.get("translator.num_ctx")), "-ngl", str(cfgmod.get("translator.gpu_layers")),
                   "--jinja", "-np", "1", "--no-webui"]
            env = dict(os.environ, LD_LIBRARY_PATH=os.path.dirname(binary) + ":" + os.environ.get("LD_LIBRARY_PATH", ""))
            # A small watchdog shell starts the server and stops it as soon as this lenslate process is gone, also
            # after a crash or kill -9 (atexit does not run then): an orphaned server kept 1.7-3 GB of GPU memory.
            self.proc = subprocess.Popen(["sh", "-c", WATCHDOG, "lenslate-runner", str(os.getpid())] + cmd,
                                         stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env)
            self.model = gguf
            for _ in range(600):   # loading a 3 GB model onto the GPU takes a few seconds
                if self.proc.poll() is not None:
                    raise RuntimeError("llama-server exited (see ~/.cache/lenslate/llama-server.log)")
                try:
                    with urllib.request.urlopen(self._url("/health"), timeout=1) as r:
                        if json.load(r).get("status") == "ok":
                            return
                except (OSError, ValueError):
                    pass
                time.sleep(0.1)
            raise RuntimeError("llama-server did not start within 60 s")

    def _stop_locked(self, force_foreign=False):
        if self.proc is not None and self.proc.poll() is None:
            mine = self.proc.pid
            self.proc.terminate()
            try:
                self.proc.wait(8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(2)
            if _read_pid() == mine:
                _remove_pid()
        elif force_foreign:
            # started by another lenslate process with a different model: ask it to exit via its PID file (only if
            # that PID really is a model runner: a stale file could name any process by now)
            pid = _read_pid()
            if pid and _is_runner(pid):
                try:
                    os.kill(pid, 15)
                    time.sleep(1)
                except OSError:
                    pass
            _remove_pid()
        self.proc = None
        self.model = None

    def stop(self, model=None):
        """Stop the server this process started (quitting: a server another lenslate process started and still uses
        stays). model: switching away from that model - only if the server still serves it (another one may have
        been started since), and then also a server this process found running and reused (its GPU memory is what
        the switch is meant to free; a lenslate process that still needs it starts it again)."""
        with self.lock:
            if model is None:
                self._stop_locked()
                return
            if self.model is None or os.path.realpath(self.model) != os.path.realpath(model):
                return
            self._stop_locked(force_foreign=self.proc is None)

    def chat(self, messages, max_tokens, temperature, on_text=None, stop=lambda: False):
        body = {"messages": messages, "stream": True, "max_tokens": max_tokens, "temperature": temperature,
                "cache_prompt": True, "chat_template_kwargs": {"enable_thinking": False},
                # PLaMo 3 Translate ends a translation with one of these (its model card); other models never write them
                "stop": ["<|plamo:tag|>", "<|plamo:bos|>"]}
        req = urllib.request.Request(self._url("/v1/chat/completions"), json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        out = []
        with urllib.request.urlopen(req, timeout=300) as r:
            for raw in r:
                if stop():
                    return None
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                delta = json.loads(data)["choices"][0].get("delta", {}).get("content") or ""
                if delta:
                    out.append(delta)
                    if on_text:
                        on_text(delta)
        return "".join(out).strip()


def _pid_path():
    return os.path.join(cfgmod.CACHE_DIR, "llama-server.pid")


def _read_pid():
    try:
        return int(open(_pid_path()).read().strip())
    except (OSError, ValueError):
        return None


def _remove_pid():
    try:
        os.unlink(_pid_path())
    except OSError:
        pass


def _is_runner(pid):
    """The process is lenslate's model runner (its watchdog shell or llama-server itself)."""
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            cmd = f.read()
    except OSError:
        return False
    return b"lenslate-runner" in cmd or b"llama-server" in cmd


# sh -c WATCHDOG lenslate-runner <lenslate pid> <server command...>: runs the server, ends it when lenslate is gone
# or on TERM (Runner.stop, another lenslate process switching models), and exits when the server exits.
WATCHDOG = (
    'parent=$1; shift; "$@" & child=$!; '
    'trap \'kill $child 2>/dev/null; wait $child; exit 0\' TERM INT HUP; '
    'while kill -0 "$parent" 2>/dev/null && kill -0 "$child" 2>/dev/null; do sleep 1 & wait $!; done; '
    'kill $child 2>/dev/null; wait $child')


RUNNER = Runner()


def _ollama_chat(model, messages, max_tokens, temperature, on_text, stop):
    body = json.dumps({
        "model": model, "stream": True, "keep_alive": "30m", "think": False,
        "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": cfgmod.get("translator.num_ctx")},
        "messages": messages,
    }).encode()
    req = urllib.request.Request(cfgmod.get("translator.ollama_url"), body, {"Content-Type": "application/json"})
    out = []
    with urllib.request.urlopen(req, timeout=300) as r:
        for chunk in r:
            if stop():
                return None
            msg = json.loads(chunk)
            if "error" in msg:
                raise RuntimeError("Ollama: " + msg["error"])
            piece = msg.get("message", {}).get("content", "")
            if piece:
                out.append(piece)
                if on_text:
                    on_text(piece)
            if msg.get("done"):
                break
    return "".join(out).strip()


def chat(model, messages, max_tokens=256, temperature=0.0, on_text=None, stop=lambda: False):
    """Send a chat to whichever backend serves `model`. Returns the reply text (None if stopped)."""
    kind, target = resolve(model)
    if kind == "builtin":
        RUNNER.ensure(target)
        _write_pid()
        return RUNNER.chat(messages, max_tokens, temperature, on_text, stop)
    return _ollama_chat(target, messages, max_tokens, temperature, on_text, stop)


def _write_pid():
    if RUNNER.proc is not None and RUNNER.proc.poll() is None:
        os.makedirs(cfgmod.CACHE_DIR, exist_ok=True)
        with open(_pid_path(), "w") as f:
            f.write(str(RUNNER.proc.pid))


def unload(model):
    """Free the GPU memory the model uses (switching to a CPU translator or another model)."""
    try:
        kind, target = resolve(model)
    except RuntimeError:
        return
    if kind == "builtin":
        RUNNER.stop(target)
        return
    url = cfgmod.get("translator.ollama_url").rsplit("/api/", 1)[0] + "/api/generate"
    try:
        req = urllib.request.Request(url, json.dumps({"model": target, "keep_alive": 0}).encode(),
                                     {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except (OSError, ValueError):
        pass


def describe(model):
    try:
        kind, target = resolve(model)
    except RuntimeError as e:
        return "not available: %s" % e
    return "built-in runner (%s)" % os.path.basename(target) if kind == "builtin" else "Ollama (%s)" % target
