"""Translator routing (no silent switch to the GPU model), reply cleanup, acceptance checks, sentence splitting."""
import os
import re
import unittest

from tests import ROOT
import config as cfgmod
import langs
import textflow as tf


class NoSilentSwitch(unittest.TestCase):
    def test_processor_translator_with_missing_model_is_kept_and_explained(self):
        cfgmod.set_many({"translator.sources": "ja,en", "translator.online_fallback": False})
        t = tf.Translator(ROOT, os.path.join(cfgmod.CACHE_DIR, "t.json"), "Spanish", "gemma-4-e2b",
                          "http://127.0.0.1:9", "mt")
        self.assertEqual(t.kind, "mt")                       # never quietly the language model (GPU)
        self.assertIn("quickmt-ja-en", t.notice)
        self.assertIn("quickmt-en-es", t.notice)
        with self.assertRaises(RuntimeError) as e:
            t.translate_batch(["こんにちは"])
        self.assertIn("not downloaded", str(e.exception))
        note = t.set_kind("sugoi")                           # an interactive switch is refused, with the reason
        self.assertIn("staying on mt", note)
        self.assertEqual(t.kind, "mt")

    def test_missing_model_note_matches_the_fallback_setting(self):
        t = tf.Translator(ROOT, os.path.join(cfgmod.CACHE_DIR, "n.json"), "English", "gemma-4-e2b",
                          "http://127.0.0.1:9", "mt")
        t.missing_models = lambda kind: ([], ["ko->en"])
        cfgmod.set("translator.online_fallback", True)
        self.assertIn("the online fallback translates those lines", t.missing_note("mt"))
        cfgmod.set("translator.online_fallback", False)
        self.assertIn("stay untranslated", t.missing_note("mt"))

    def test_online_fallback_results_are_read_back(self):
        cfgmod.set_many({"translator.online_fallback": True, "translator.seed_packs": False})
        t = tf.Translator(ROOT, os.path.join(cfgmod.CACHE_DIR, "o.json"), "English", "gemma-4-e2b",
                          "http://127.0.0.1:9", "mt")
        t._cache_for("online").put(t._key("おはよう"), "Good morning")
        self.assertEqual(t.get("おはよう"), "Good morning")      # no new online request for it
        cfgmod.set("translator.online_fallback", False)

    def test_failed_lines_after_an_error_wait_too_and_a_switch_clears_them(self):
        t = tf.Translator(ROOT, os.path.join(cfgmod.CACHE_DIR, "e.json"), "English", "gemma-4-e2b",
                          "http://127.0.0.1:9", "mt")
        calls = []

        def broken(texts, *a, **k):
            calls.append(list(texts))
            raise RuntimeError("quickmt-ja-en is not downloaded")
        t._translate_batch = broken
        with self.assertRaises(RuntimeError):
            t.translate_batch(["あいう"])
        self.assertEqual(t.translate_batch(["あいう"]), {})       # not asked again (no error on every refresh)
        self.assertEqual(len(calls), 1)
        t.set_language("Spanish")                                  # a new language: tried again at once
        with self.assertRaises(RuntimeError):
            t.translate_batch(["あいう"])
        self.assertEqual(len(calls), 2)

    def test_failed_lines_are_not_asked_again_at_once(self):
        t = tf.Translator(ROOT, os.path.join(cfgmod.CACHE_DIR, "f.json"), "English", "gemma-4-e2b",
                          "http://127.0.0.1:9", "mt")
        calls = []

        def fake(texts, *a, **k):
            calls.append(list(texts))
            return {}
        t._translate_batch = fake
        t.translate_batch(["あいう"])
        t.translate_batch(["あいう", "かきく"])
        self.assertEqual(calls, [["あいう"], ["かきく"]])


class ReplyCleanup(unittest.TestCase):
    def test_clean_reply(self):
        cases = [("こんにちは", "<think>\nhmm</think>Hello", "Hello"),
                 ("メニュー", "Translation: Menu", "Menu"),
                 ("行こう", '"Let us go"', "Let us go"),
                 ("「行こう」", '"Let us go"', '"Let us go"'),     # the original was quoted: keep them
                 ("あ", "Ah (Note: a sigh)", "Ah"),
                 ("x", '"He said "hi', '"He said "hi')]           # unbalanced: left alone
        for src, reply, want in cases:
            self.assertEqual(tf.clean_reply(src, reply), want)

    def test_acceptance(self):
        self.assertEqual(langs.source_left("Menu", "Menu", "en", "es"), 0.0)          # rightly the same word
        self.assertEqual(langs.source_left("Load Game", "Load Game", "en", "es"), 1.0)  # two words: not translated
        self.assertEqual(langs.source_left("Go to the menu now", "Go to the menu now", "en", "es"), 1.0)
        self.assertEqual(langs.source_left("Inventory", "Inventory", "en", "zh"), 1.0)
        self.assertEqual(langs.source_left("Inventory", "物品栏", "en", "zh"), 0.0)


def _mt_text_functions():
    """split() and join() of mt_server.py, without importing it (it needs CTranslate2 from the engine)."""
    src = open(os.path.join(ROOT, "mt_server.py"), encoding="utf-8").read()
    ns = {"re": re}
    exec(src[src.index("# a sentence-level model"):src.index("def translate(texts):")], ns)   # noqa: S102
    return ns["split"], ns["join"]


class Sentences(unittest.TestCase):
    def test_split(self):
        split, _ = _mt_text_functions()
        self.assertEqual(split("「行こう。早く」と彼は言った。次の文。"), ["「行こう。早く」と彼は言った。", "次の文。"])
        self.assertEqual(split("「待って！」「何？」"), ["「待って！」", "「何？」"])
        self.assertEqual(split("Hello Mr. Smith. How are you? I am J. Doe! Fine."),
                         ["Hello Mr. Smith.", "How are you?", "I am J. Doe!", "Fine."])

    def test_join(self):
        _, join = _mt_text_functions()
        self.assertEqual(join(["我们走吧", "快点!"]), "我们走吧。快点!")
        self.assertEqual(join(["Let's go.", "Hurry."]), "Let's go. Hurry.")


if __name__ == "__main__":
    unittest.main()


class PlamoFormat(unittest.TestCase):
    """PLaMo 3 Translate takes settings and names in a system message, not lenslate's prompt."""

    def test_names_become_glossary_lines(self):
        import names as nm
        import textflow as tf
        hint = nm.NameBook.prompt_hint([("ボウ太", "Bouta"), ("躯籠温泉", "Kukuro Onsen")]) + tf.PLACEHOLDER_HINT
        self.assertEqual(tf.hint_pairs(hint), [("ボウ太", "Bouta"), ("躯籠温泉", "Kukuro Onsen")])
        self.assertEqual(tf.hint_pairs(""), [])
        msgs = tf.plamo_messages("English", "ボウ太さん、こんにちは", hint)
        self.assertEqual(msgs[0]["content"], "[plamo-translate]\ntarget_lang=en\nsource_lang=ja\n"
                         "glossary=ボウ太 => Bouta\nglossary=躯籠温泉 => Kukuro Onsen")
        self.assertEqual(msgs[1], {"role": "user", "content": "ボウ太さん、こんにちは"})

    def test_targets(self):
        import textflow as tf
        self.assertIn("target_lang=zh-hans", tf.plamo_messages("Chinese (Simplified)", "Continue", "")[0]["content"])
        with self.assertRaises(RuntimeError):       # no Portuguese in the model: said, not sent
            tf.plamo_messages("Portuguese (Brazil)", "Continue", "")


class ContextLines(unittest.TestCase):
    """[translator] context_lines: earlier dialogue lines go along with a new one (off by default)."""

    def make(self):
        return tf.Translator(ROOT, os.path.join(cfgmod.CACHE_DIR, "ctx.json"), "English", "gemma-4-e2b",
                             "http://127.0.0.1:9/api/chat", "llm", False)

    def test_off_by_default_and_only_dialogue(self):
        t = self.make()
        t.put("田中先生は女性で、とても厳しい。", "Ms. Tanaka is a woman, and very strict.")
        self.assertEqual(t.context("先生は明日来るって言ってたよ。"), [])
        os.environ["LENSLATE_CONTEXT"] = "3"
        try:
            self.assertEqual(t.context("先生は明日来るって言ってたよ。"),
                             [("田中先生は女性で、とても厳しい。", "Ms. Tanaka is a woman, and very strict.")])
            self.assertEqual(t.context("オプション"), [])                    # a menu word: no context
            t.put("装備", "Equipment")                                       # and never becomes context
            t.put("Stay sharp. They'll be on us any minute now.", "x")       # another language: not for this line
            self.assertEqual(len(t.context("先生は明日来るって言ってたよ。")), 1)
        finally:
            os.environ.pop("LENSLATE_CONTEXT")

    def test_half_typed_and_repeated_lines(self):
        t = self.make()
        os.environ["LENSLATE_CONTEXT"] = "8"
        try:
            t.put("ねえ、あの塔の上に", "Hey, on top of that tower")
            t.put("ねえ、あの塔の上に光が見えるよ。", "Hey, I can see a light on top of that tower.")
            t.put("誰かいるのかな？本当に？", "Is someone there? Really?")
            t.get("ねえ、あの塔の上に光が見えるよ。")          # shown again (a re-read): one entry, now the newest
            got = t.context("明日の朝、一緒に確かめに行こう。")
            self.assertEqual([a for a, _b in got], ["誰かいるのかな？本当に？", "ねえ、あの塔の上に光が見えるよ。"])
            # the line itself (or its half-typed start) is never its own context
            self.assertEqual([a for a, _b in t.context("誰かいるのかな？本当に？ええ。")], ["ねえ、あの塔の上に光が見えるよ。"])
        finally:
            os.environ.pop("LENSLATE_CONTEXT")

    def test_prompt_shapes(self):
        ctx = [("田中先生は女性で、とても厳しい。", "Ms. Tanaka is a woman, and very strict.")]
        own = tf._messages("gemma-4-e2b", tf.PROMPT, "English", "先生は明日来るって言ってたよ。", "", ctx)
        self.assertEqual(len(own), 1)
        self.assertIn("- 田中先生は女性で、とても厳しい。 = Ms. Tanaka is a woman, and very strict.", own[0]["content"])
        self.assertTrue(own[0]["content"].endswith("Text: 先生は明日来るって言ってたよ。"))
        strict = tf._messages("gemma-4-e2b", tf.STRICT, "English", "先生は明日来るって言ってたよ。", "", ctx)
        self.assertNotIn("Ms. Tanaka", strict[0]["content"])
        plamo = tf._messages("plamo-3-translate-0.8b", tf.PROMPT, "English", "先生は明日来るって言ってたよ。", "", ctx)
        self.assertEqual([m["role"] for m in plamo], ["system", "user", "assistant", "user"])
        self.assertEqual(plamo[-1]["content"], "先生は明日来るって言ってたよ。")


class CacheStamp(unittest.TestCase):
    """A cache remembers which model version and prompt made its entries; a change sets the old entries aside."""

    def test_prompt_change_needs_a_version_decision(self):
        import hashlib
        seen = hashlib.sha256((tf.PROMPT + tf.STRICT + tf.HY_PROMPT).encode()).hexdigest()[:16]
        known = {1: "abb5a9f1b986a5d1"}
        self.assertEqual(known.get(tf.PROMPT_VERSION), seen,
                         "The translation prompt changed. If cached lines should be translated again with it, raise "
                         "textflow.PROMPT_VERSION; then put the new fingerprint (%s) in this test." % seen)

    def test_stamp_names_model_revision_and_prompt(self):
        import models
        s = tf.cache_stamp("llm", "gemma-4-e2b")
        self.assertIn(models.REVISIONS["unsloth/gemma-4-E2B-it-GGUF"][:12], s)
        self.assertIn("prompt %d" % tf.PROMPT_VERSION, s)
        self.assertNotEqual(s, tf.cache_stamp("llm", "plamo-3-translate-0.8b"))
        self.assertIn("quickmt-ja-en@", tf.cache_stamp("mt", ""))
        self.assertIn("sugoi-v4-ja-en@", tf.cache_stamp("sugoi", ""))
        self.assertTrue(tf.cache_stamp("llm", "someone/else:latest"))     # an Ollama model outside the catalog

    def test_old_entries_are_set_aside_but_corrections_stay(self):
        import json
        path = os.path.join(cfgmod.CACHE_DIR, "stamp-test.json")
        c = tf.TextCache(path)                       # a cache from before stamps existed
        c.put("こんにちは", "Hello")
        c.put("はい", "Yes")
        c.save()
        c = tf.TextCache(path, stamp="llm a@1 prompt 1")
        self.assertEqual((c.retired, c.get("はい")), (0, "Yes"))          # adopted as it is
        c.put("いいえ", "Nope")
        c.mark_fixed("いいえ")
        c.save()
        c = tf.TextCache(path, stamp="llm a@1 prompt 1")
        self.assertEqual((c.retired, len(c)), (0, 3))                     # same set-up: nothing happens
        c = tf.TextCache(path, stamp="llm a@2 prompt 1")                  # the model moved to another commit
        self.assertEqual(c.retired, 2)
        self.assertIsNone(c.get("はい"))
        self.assertEqual(c.get("いいえ"), "Nope")                         # a hand correction
        with open(path + ".old", encoding="utf-8") as f:
            old = json.load(f)
        self.assertEqual(old["entries"]["はい"], "Yes")
        self.assertEqual(old["stamp"], "llm a@1 prompt 1")
        self.assertEqual(tf.TextCache(path, stamp="llm a@2 prompt 1").retired, 0)
