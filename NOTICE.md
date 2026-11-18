# What lenslate installs and downloads, and under which licences

lenslate itself is a set of Python and QML files. It does not contain any of the programs or models below: the
installer and the Models page download them from their own publishers, onto your PC, when you ask for them.
Their licences apply to your use of them. This list is what the app shows piece by piece (Models page, setup
window), collected in one place.

**Read this if you want to use lenslate for more than private play:** Sugoi v4 and PLaMo 3 Translate are free for
personal / non-commercial use only, and Gemma comes with Google's own terms. None of them is installed without you
choosing it (Gemma is offered by the installer and the setup window, with its size and terms named).

## Translation models (config `[paths] models`, default ~/.local/share/lenslate/models)

Every download is pinned to one commit of its repository (`models.py`, `REVISIONS`) and checked against the
checksum Hugging Face publishes for the file.

| Model (lenslate name) | Source | Licence | Downloaded |
|---|---|---|---|
| quickmt-ja-en | huggingface.co/quickmt/quickmt-ja-en | CC-BY-4.0 | installer (asks first) |
| quickmt-zh-en | huggingface.co/quickmt/quickmt-zh-en | CC-BY-4.0 | only when you choose it |
| quickmt-en-es | huggingface.co/quickmt/quickmt-en-es | CC-BY-4.0 | only when you choose it |
| quickmt-en-zh | huggingface.co/quickmt/quickmt-en-zh | CC-BY-4.0 | only when you choose it |
| quickmt-en-pt | huggingface.co/quickmt/quickmt-en-pt | CC-BY-4.0 | only when you choose it |
| opus-en-ptbr | huggingface.co/ooeoeo/opus-mt-tc-big-en-pt-ct2-float16 | CC-BY-4.0 | only when you choose it |
| sugoi-v4-ja-en | huggingface.co/entai2965/sugoi-v4-ja-en-ctranslate2 | NTT non-commercial | only when you choose it |
| gemma-4-e2b | huggingface.co/unsloth/gemma-4-E2B-it-GGUF | Gemma terms of use | installer (asks first) |
| qwen3.5-4b-uncensored | huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive | Apache-2.0 | only when you choose it |
| plamo-3-translate-0.8b | huggingface.co/pfnet/plamo-3-translate-0.8b-GGUF | PLaMo Community License (free for personal and non-commercial use) | only when you choose it |
| plamo-3-translate-2b | huggingface.co/pfnet/plamo-3-translate-2b-GGUF | PLaMo Community License (free for personal and non-commercial use) | only when you choose it |
| hy-mt2-1.8b | huggingface.co/tencent/Hy-MT2-1.8B-GGUF | Apache-2.0 | only when you choose it |
| lfm2-350m-enjp | huggingface.co/LiquidAI/LFM2-350M-ENJP-MT-GGUF | LFM Open License | only when you choose it |
| qwen3-vl-4b | Ollama: qwen3-vl:4b-instruct | Apache-2.0 | only when you choose it |

Licence texts: each model's page at its source. "Gemma terms of use": ai.google.dev/gemma/terms.
"PLaMo Community License": on the pfnet model pages. "NTT non-commercial": the licence of the JParaCrawl data
Sugoi v4 was trained on, as stated by its publisher. "LFM Open License": on the LiquidAI model page.

## Text-reading (OCR) models

| What | Source | Licence |
|---|---|---|
| PP-OCRv6 / PP-OCRv5 finder and reader models | PaddleOCR (PaddlePaddle), packaged or fetched by RapidOCR | Apache-2.0 |
| meikiocr's two models (Ultrafast reading, Japanese) | huggingface.co/rtr46/meiki.text.detect.v0 and meiki.txt.recognition.v0, downloaded by the meikiocr package on first use | LGPL-3.0 |

## Programs and libraries

| What | Used for | Licence |
|---|---|---|
| Qt 6 / PySide6 (the distribution's package, or PyPI on X11) | settings window, overlay | LGPL-3.0 |
| RapidOCR | reading text | Apache-2.0 |
| ONNX Runtime (and onnxruntime-gpu when GPU reading is turned on) | running the OCR models | MIT |
| CTranslate2 | processor translators | MIT |
| SentencePiece | processor translators | Apache-2.0 |
| NumPy | picture comparison | BSD-3-Clause |
| Pillow | pictures in the OCR helper | MIT-CMU (HPND) |
| meikiocr | Ultrafast reading | Apache-2.0 |
| llama.cpp (release build from github.com/ggml-org/llama.cpp) | built-in language-model runner | MIT |
| uv (astral.sh) | builds lenslate's Python environments | MIT or Apache-2.0 |
| kdotool (KDE only; downloaded when the distribution has no package) | finding the game window | Apache-2.0 |
| Ollama (optional, only if you already use it) | another way to run language models | MIT |

## Game hooks (only when you install a hook into a game with `lenslate hook install`)

| What | Used for | Licence |
|---|---|---|
| BepInEx | loader for Unity games | LGPL-2.1 |
| XUnity.AutoTranslator | text hook for Unity games | MIT |
| lenslate's own RPG Maker plugin and Ren'Py script (`hooks/`) | text hooks | same as lenslate |

## Online translators (off by default)

Google, Bing, Yandex and DeepL are web services with their own terms; text you translate with them leaves your
PC. lenslate only sends text there when you turn an online translator or the online fallback on.

## lenslate's own licence

GNU General Public License, version 3 or (at your option) any later version (GPL-3.0-or-later): the full text is
in LICENSE. It covers lenslate's own code, QML files, hooks and seed packs. The models and programs listed above are
separate works under their own licences; lenslate downloads them, it does not include them - a non-commercial model
licence (PLaMo, Sugoi) stays non-commercial whatever lenslate's licence is.
