//=============================================================================
// Lenslate.js - live translation for RPG Maker MV / MZ through lenslate (installed by `lenslate hook install`)
//=============================================================================
/*:
 * @target MZ MV
 * @plugindesc Translates the game's text with lenslate running on this computer (nothing leaves the PC).
 * @author lenslate
 * @help
 * Messages, choices, speaker names, item/skill/menu texts and map names are sent to lenslate's local
 * translation server (`lenslate serve`, 127.0.0.1) and shown translated in the game's own windows.
 * Long translations are word-wrapped to fit the message window (and made a little smaller if needed).
 * If lenslate is not running the game simply stays in its original language.
 * Remove with: lenslate hook remove <game folder>
 */
(function () {
  "use strict";
  var GAME = "__LENSLATE_GAME__";
  var BASE = "http://127.0.0.1:__LENSLATE_PORT__/g/" + encodeURIComponent(GAME);
  var SRC_RE = new RegExp("__LENSLATE_SRC__");   // scripts of the languages lenslate translates (config sources)
  var memo = {};          // raw text -> translation (this session)
  var down = 0;           // time until which the server is considered unreachable

  function available() { return Date.now() > down; }

  function request(method, url, body) {
    if (!available()) return null;
    try {
      var x = new XMLHttpRequest();
      x.open(method, url, false);                 // synchronous: the text is needed before it is drawn
      if (body) x.setRequestHeader("Content-Type", "text/plain");   // text/plain: no CORS preflight
      x.send(body || null);
      if (x.status === 200) return x.responseText;
      return null;                                // 500 = could not translate this one
    } catch (e) {
      down = Date.now() + 30000;                  // lenslate not running: stop asking for 30 s
      return null;
    }
  }

  function tr(text, kind) {
    if (!text || !SRC_RE.test(text)) return text;
    var k = kind + "\u0001" + text;
    if (memo[k] !== undefined) return memo[k];
    var out = request("GET", BASE + "/translate?engine=rpgm&kind=" + kind + "&text=" + encodeURIComponent(text));
    if (out !== null) memo[k] = out;
    return out === null ? text : out;
  }

  // Many texts at once, only what lenslate already has (the rest is translated in the background for next time).
  function trBatch(list, kind) {
    var todo = [], idx = [];
    for (var i = 0; i < list.length; i++) {
      var t = list[i];
      if (t && SRC_RE.test(t) && memo[kind + "\u0001" + t] === undefined) { todo.push({text: t, kind: kind}); idx.push(i); }
    }
    if (todo.length) {
      var res = request("POST", BASE + "/batch", JSON.stringify({items: todo, engine: "rpgm", wait: false}));
      if (res) {
        var out = JSON.parse(res).out;
        for (var j = 0; j < out.length; j++) if (out[j] !== null) memo[kind + "\u0001" + todo[j].text] = out[j];
      }
    }
    return list.map(function (t) { var m = memo[kind + "\u0001" + t]; return m === undefined ? t : m; });
  }

  // ---------------------------------------------------------------------------- word wrap for messages
  var measurer = null;
  function measure(text, size) {
    if (!measurer) measurer = new Bitmap(1, 1);
    measurer.fontFace = (typeof $gameSystem !== "undefined" && $gameSystem.mainFontFace) ? $gameSystem.mainFontFace()
                      : (Window_Base.prototype.standardFontFace ? Window_Base.prototype.standardFontFace() : "GameFont");
    measurer.fontSize = size;
    return measurer.measureTextWidth(text.replace(/\\[A-Za-z]+\[[^\]]*\]|\\[A-Za-z{}!.|^$<>]/g, ""));
  }
  function baseSize() {
    if (typeof $gameSystem !== "undefined" && $gameSystem.mainFontSize) return $gameSystem.mainFontSize();   // MZ
    return Window_Base.prototype.standardFontSize ? Window_Base.prototype.standardFontSize() : 28;          // MV
  }
  function wrapWidth() {
    var w = Graphics.boxWidth - 2 * (Window_Base.prototype.standardPadding ? Window_Base.prototype.standardPadding() : 12) - 8;
    if ($gameMessage.faceName && $gameMessage.faceName() !== "") w -= 168;   // text starts right of the face (MV and MZ)
    return w;
  }
  function wrapLines(text, size, width) {
    var out = [];
    text.split("\n").forEach(function (line) {
      var words = line.split(" "), cur = "";
      words.forEach(function (w) {
        var next = cur ? cur + " " + w : w;
        if (cur && measure(next, size) > width) { out.push(cur); cur = w; } else cur = next;
      });
      out.push(cur);
    });
    return out;
  }
  function wrapMessage(text) {
    var lines = text.split("\n"), head = "";
    // MV speaker line (translated separately by lenslate): keep it as the first line
    if (lines.length > 1 && measure(lines[0], baseSize()) < wrapWidth() / 2) { head = lines.shift() + "\n"; }
    var body = lines.join(" "), size = baseSize(), width = wrapWidth(), maxLines = head ? 3 : 4;
    var wrapped = wrapLines(body, size, width), shrink = "";
    for (var step = 1; step <= 2 && wrapped.length > maxLines && size - 12 >= 16; step++) {   // \} = 12 px smaller
      shrink += "\\}"; size -= 12;
      wrapped = wrapLines(body, size, width);
    }
    return head + shrink + wrapped.join("\n");
  }

  // ------------------------------------------------------------------------------------------ messages
  var _allText = Game_Message.prototype.allText;
  Game_Message.prototype.allText = function () {
    var raw = _allText.call(this);
    if (this._lenslateRaw === raw) return this._lenslateOut;
    var out = tr(raw, "message");
    if (out !== raw) out = wrapMessage(out);
    this._lenslateRaw = raw; this._lenslateOut = out;
    return out;
  };

  var _setChoices = Game_Message.prototype.setChoices;
  Game_Message.prototype.setChoices = function (choices, defaultType, cancelType) {
    _setChoices.call(this, trBatch(choices, "choice").map(function (c, i) {
      return c === choices[i] ? tr(c, "choice") : c;
    }), defaultType, cancelType);
  };

  if (Game_Message.prototype.setSpeakerName) {   // MZ name box
    var _setSpeaker = Game_Message.prototype.setSpeakerName;
    Game_Message.prototype.setSpeakerName = function (name) { _setSpeaker.call(this, tr(name, "name")); };
  }

  // ------------------------------------------------- any other single-line text (HUDs, custom plugin windows)
  // Only translations lenslate already has are used (no waiting while the game draws); new texts are queued and
  // appear the next time that window is drawn.
  var _drawText = Window_Base.prototype.drawText;
  Window_Base.prototype.drawText = function (text, x, y, maxWidth, align) {
    if (typeof text === "string" && SRC_RE.test(text)) text = trBatch([text], "text")[0];
    return _drawText.call(this, text, x, y, maxWidth, align);
  };
  // drawTextEx: text with escape codes (help windows, HUD plugins). Message windows don't use it, so no line is
  // translated twice; database texts are already English by then and skipped by the Japanese check.
  var _drawTextEx = Window_Base.prototype.drawTextEx;
  Window_Base.prototype.drawTextEx = function (text, x, y, width) {
    if (typeof text === "string" && SRC_RE.test(text)) text = trBatch([text], "text")[0];
    return _drawTextEx.apply(this, [text, x, y, width].concat([].slice.call(arguments, 4)));
  };

  // -------------------------------------------------------------------------------- database and menus
  var FIELDS = {
    $dataActors: ["name", "nickname", "profile"], $dataClasses: ["name"],
    $dataSkills: ["name", "description", "message1", "message2"], $dataItems: ["name", "description"],
    $dataWeapons: ["name", "description"], $dataArmors: ["name", "description"], $dataEnemies: ["name"],
    $dataStates: ["name", "message1", "message2", "message3", "message4"]
  };
  function translateObjects(list, fields) {
    var refs = [];
    (list || []).forEach(function (o) { if (o) fields.forEach(function (f) { if (typeof o[f] === "string" && o[f]) refs.push([o, f]); }); });
    var out = trBatch(refs.map(function (r) { return r[0][r[1]]; }), "text");
    refs.forEach(function (r, i) { r[0][r[1]] = out[i]; });
  }
  function translateArray(arr) {
    if (!arr) return;
    var out = trBatch(arr, "text");
    for (var i = 0; i < arr.length; i++) arr[i] = out[i];
  }

  var _onLoad = DataManager.onLoad;
  DataManager.onLoad = function (object) {
    _onLoad.call(this, object);
    try {
      for (var name in FIELDS) if (window[name] === object) translateObjects(object, FIELDS[name]);
      if (object === window.$dataSystem) {
        var t = object.terms;
        ["basic", "commands", "params"].forEach(function (k) { translateArray(t[k]); });
        var keys = Object.keys(t.messages || {}), vals = trBatch(keys.map(function (k) { return t.messages[k]; }), "text");
        keys.forEach(function (k, i) { t.messages[k] = vals[i]; });
        ["elements", "skillTypes", "weaponTypes", "armorTypes", "equipTypes"].forEach(function (k) { translateArray(object[k]); });
      }
      if (object === window.$dataMap && object.displayName) object.displayName = trBatch([object.displayName], "text")[0];
    } catch (e) { console.warn("lenslate:", e); }
  };
})();
