"""`lenslate testbench`: run test screens through every preset, time each step and preview the translations.

    lenslate testbench                  all presets, the built-in test screens + your own screenshots
    lenslate testbench --presets light,fast   only these presets
    lenslate testbench my1.png my2.jpg  only these images (plus nothing else)
    lenslate testbench --4k             also 4K versions (built-in screens drawn at 4K, your screenshots enlarged)
    lenslate testbench --half           read big text at half size ([ocr] big_text = half, the 4K option)
    lenslate testbench samples          (re)draw the built-in test screens (1920x1080)
    lenslate testbench ocr [--models v5-mobile,v6-small,meiki] [--4k] [--no-gpu]
                                        compare OCR models: time, processor core-seconds, GPU memory, accuracy
                                        (screens with an answer key: samples/testbench/<name>.txt, or a .txt
                                        next to your screenshot with the text it shows, one line per line)

Test screens: samples/testbench/*.png (drawn by this file: title menu, status menu, visual-novel dialogue, a
Kate-style wall of text, a Chinese game screen, small HUD hints). Your own screenshots: put PNG/JPG files in
~/Pictures/lenslate-tests/ (whole screens or just the part you would pick as the area).

Each image goes through the real refresh code (OcrPipeline with the screen capture replaced by the image), so the
times are what the overlay would take after you pick that area:
  find + read = text finder and reader (OCR); translate = every new line through the preset's translator;
  first time = nothing cached yet; seen again = the same text read again (translations come from the cache).
Model loading is timed separately ("start-up"): it happens once per lenslate start, not per screen.
Every preset gets an empty translation cache (your real caches are not touched or used).
Output: ~/.cache/lenslate/testbench/<time>/report.html (+ preview images, results.json).
"""
import glob
import html
import json
import os
import shutil
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no windows: drawing and fonts only

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "samples", "testbench")
USER_DIR = os.path.expanduser("~/Pictures/lenslate-tests")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


# --------------------------------------------------------------------------------------------- test screens
def make_samples(out=SAMPLES, scale=1.5):
    """Draw the test screens. The layouts are written for 1280x720; scale 1.5 = 1080p (default), 3 = 4K."""
    from PySide6.QtCore import QPointF, QRect, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QRadialGradient

    os.makedirs(out, exist_ok=True)
    JP, ZH = "Noto Sans CJK JP", "Noto Sans CJK SC"

    def font(px, fam=JP, bold=False):
        f = QFont(fam)
        f.setPixelSize(px)
        f.setBold(bold)
        return f

    def canvas(w, h, top, bottom):
        img = QImage(round(w * scale), round(h * scale), QImage.Format_RGB32)
        p = QPainter(img)
        p.scale(scale, scale)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor(top))
        g.setColorAt(1, QColor(bottom))
        p.fillRect(0, 0, w, h, g)
        return img, p

    truth = []   # every string drawn on the current screen: the testbench's answer key (<screen>.txt)

    def text(p, x, y, s, f, color="#f0f0f0", shadow=True):
        truth.append(s)
        p.setFont(f)
        if shadow:
            p.setPen(QColor(0, 0, 0, 170))
            p.drawText(x + 2, y + 2, s)
        p.setPen(QColor(color))
        p.drawText(x, y, s)

    def panel(p, r, fill=(15, 20, 45, 215), border="#c9b47a"):
        p.setPen(QPen(QColor(border), 2))
        p.setBrush(QColor(*fill))
        p.drawRoundedRect(QRectF(r), 10, 10)

    # 1. title menu: big title, menu items, small version line
    img, p = canvas(1280, 720, "#0d1b3a", "#2c1a3f")
    rg = QRadialGradient(QPointF(900, 260), 320)
    rg.setColorAt(0, QColor(255, 220, 150, 90))
    rg.setColorAt(1, QColor(255, 220, 150, 0))
    p.fillRect(0, 0, 1280, 720, rg)
    p.setBrush(QColor(10, 12, 25))
    p.setPen(Qt.NoPen)
    p.drawRect(820, 260, 70, 460)                     # the tower
    p.drawPolygon([QPointF(810, 262), QPointF(855, 170), QPointF(900, 262)])
    text(p, 90, 170, "封印の塔と星降る夜", font(64, bold=True), "#ffe7a8")
    for i, s in enumerate(["ニューゲーム", "コンティニュー", "オプション", "クレジット", "ゲーム終了"]):
        text(p, 140, 330 + i * 58, ("▶ " if i == 0 else "   ") + s, font(32), "#ffffff" if i == 0 else "#c8c8d8")
    text(p, 1040, 700, "Ver. 1.0.3", font(16), "#a0a0b0", False)
    text(p, 90, 700, "Aボタンで決定　Bボタンで戻る", font(16), "#a0a0b0", False)
    p.end()
    img.save(os.path.join(out, "1-title-menu.png"))
    _save_truth(os.path.join(out, "1-title-menu.png"), truth)

    # 2. RPG status / item menu: many short labels and numbers, medium-small text
    img, p = canvas(1280, 720, "#1b2440", "#111726")
    panel(p, QRect(30, 30, 380, 660))
    for i, s in enumerate(["アイテム", "装備", "スキル", "ステータス", "クエスト", "セーブ", "タイトルに戻る"]):
        text(p, 70, 95 + i * 62, s, font(28), "#ffffff" if i == 1 else "#cfd3e6")
    panel(p, QRect(440, 30, 810, 300))
    text(p, 470, 80, "ミナ　Lv 12　見習い魔導士", font(26), "#ffe7a8")
    stats = [("HP", "340 / 520"), ("MP", "45 / 90"), ("攻撃力", "88"), ("防御力", "61"), ("素早さ", "73"), ("運", "19")]
    for i, (k, v) in enumerate(stats):
        x, y = 480 + (i % 2) * 380, 140 + (i // 2) * 52
        text(p, x, y, k, font(22), "#cfd3e6")
        text(p, x + 150, y, v, font(22), "#ffffff")
    panel(p, QRect(440, 350, 810, 340))
    text(p, 470, 395, "装備中", font(24), "#ffe7a8")
    gear = [("武器", "樫の杖"), ("盾", "なし"), ("頭", "旅人の帽子"), ("体", "見習いのローブ"), ("装飾品", "星のペンダント")]
    for i, (k, v) in enumerate(gear):
        text(p, 480, 445 + i * 44, k, font(20), "#9fa6c4")
        text(p, 620, 445 + i * 44, v, font(20), "#ffffff")
    text(p, 470, 675, "魔力が少し上がる不思議なペンダント。夜になると淡く光る。", font(17), "#cfd3e6", False)
    p.end()
    img.save(os.path.join(out, "2-status-menu.png"))
    _save_truth(os.path.join(out, "2-status-menu.png"), truth)

    # 3. visual-novel dialogue: scenery + dialogue box with a name plate
    img, p = canvas(1280, 720, "#f3a46b", "#5a3a6e")
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(40, 30, 60))
    p.drawEllipse(QPointF(300, 760), 520, 260)
    p.drawEllipse(QPointF(1050, 780), 600, 280)
    p.setBrush(QColor(70, 55, 95))
    p.drawEllipse(QPointF(640, 330), 120, 150)            # a character silhouette
    p.drawRoundedRect(QRectF(520, 430, 240, 300), 60, 60)
    panel(p, QRect(60, 470, 1160, 220), (12, 14, 30, 225), "#e8d9b0")
    panel(p, QRect(90, 440, 170, 50), (60, 40, 90, 240), "#e8d9b0")
    text(p, 125, 475, "ミナ", font(26, bold=True), "#ffe7a8")
    text(p, 110, 545, "ねえ、あの塔の上に光が見えるよ。誰かいるのかな？", font(30))
    text(p, 110, 595, "おばあちゃんが言ってた。満月の夜に光ったら、", font(30))
    text(p, 110, 645, "扉が開くんだって……本当だったんだ。", font(30))
    text(p, 1150, 670, "▼", font(20), "#e8d9b0", False)
    p.end()
    img.save(os.path.join(out, "3-dialogue.png"))
    _save_truth(os.path.join(out, "3-dialogue.png"), truth)

    # 4. wall of text in a text editor (Kate-like: white page, line numbers, the samples/ja-test.txt text)
    lines = open(os.path.join(HERE, "samples", "ja-test.txt"), encoding="utf-8").read().splitlines()
    img = QImage(round(1280 * scale), round(720 * scale), QImage.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    p.scale(scale, scale)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.fillRect(0, 0, 1280, 34, QColor("#eff0f1"))
    p.fillRect(0, 34, 48, 686, QColor("#f7f7f7"))
    small = QFont("sans-serif")
    small.setPixelSize(13)
    text(p, 12, 23, "ja-test.txt — Kate", small, "#31363b", False)
    f = font(17)
    p.setFont(f)
    y = 60
    first = next((i for i, ln in enumerate(lines) if ln.startswith("■ 会話")), 0)   # dialogue + long paragraphs
    for n, line in list(enumerate(lines, 1))[first:]:
        mono = QFont("monospace")
        mono.setPixelSize(13)
        text(p, 10, y, "%2d" % n, mono, "#a0a0a0", False)
        # wrap long lines at the window edge, the way the editor shows them
        rest = line
        while True:
            p.setFont(f)
            cut = len(rest)
            while cut > 0 and p.fontMetrics().horizontalAdvance(rest[:cut]) > 1200:
                cut -= 1
            text(p, 60, y, rest[:cut], f, "#232629", False)
            rest = rest[cut:]
            y += 26
            if not rest:
                break
        if y > 710:
            break
    p.end()
    img.save(os.path.join(out, "4-wall-of-text.png"))
    _save_truth(os.path.join(out, "4-wall-of-text.png"), truth)

    # 5. Chinese game screen (Simplified): quest dialogue + menu buttons
    img, p = canvas(1280, 720, "#16352f", "#0b1a17")
    panel(p, QRect(60, 60, 520, 330), (10, 30, 25, 220), "#8fd1b5")
    text(p, 90, 110, "任务：寻找失落的钥匙", font(28, ZH, True), "#d8ffe9")
    for i, s in enumerate(["与村长对话", "前往北方森林", "击败森林守卫（0/3）", "返回村庄"]):
        text(p, 100, 170 + i * 50, ("✔ " if i == 0 else "□ ") + s, font(24, ZH), "#cfe9df")
    panel(p, QRect(60, 470, 1160, 210), (8, 22, 18, 230), "#8fd1b5")
    text(p, 100, 525, "村长", font(26, ZH, True), "#ffe7a8")
    text(p, 100, 585, "年轻人，北方的森林最近很不太平。如果你能找回那把钥匙，", font(28, ZH))
    text(p, 100, 635, "我就把祖传的宝剑送给你。", font(28, ZH))
    for i, s in enumerate(["继续", "存档", "设置"]):
        panel(p, QRect(900, 80 + i * 80, 260, 56), (20, 50, 40, 230), "#8fd1b5")
        text(p, 990, 118 + i * 80, s, font(26, ZH), "#ffffff")
    p.end()
    img.save(os.path.join(out, "5-chinese.png"))
    _save_truth(os.path.join(out, "5-chinese.png"), truth)

    # 6. small HUD text: hints, quest tracker, item pickup (14-16 px: the hardest case)
    img, p = canvas(1280, 720, "#4d6b3a", "#26341d")
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(90, 70, 50))
    p.drawRect(560, 300, 160, 200)                        # a chest-ish box
    panel(p, QRect(940, 20, 320, 150), (0, 0, 0, 150), "#00000000")
    text(p, 960, 50, "クエスト", font(16, bold=True), "#ffe7a8")
    text(p, 960, 78, "・古びた鍵を探す", font(15), "#ffffff")
    text(p, 960, 102, "・鍛冶屋に話しかける", font(15), "#ffffff")
    text(p, 960, 126, "・薬草を集める（2/5）", font(15), "#ffffff")
    panel(p, QRect(560, 520, 170, 36), (0, 0, 0, 160), "#00000000")
    text(p, 575, 545, "Eキーで調べる", font(16), "#ffffff")
    panel(p, QRect(20, 600, 360, 100), (0, 0, 0, 150), "#00000000")
    text(p, 40, 630, "薬草を手に入れた！", font(15), "#b5ff9a")
    text(p, 40, 656, "所持金が足りません。", font(15), "#ffb0b0")
    text(p, 40, 682, "セーブしました。", font(15), "#ffffff")
    text(p, 20, 30, "HP 340/520　MP 45/90", font(14), "#ffffff")
    p.end()
    img.save(os.path.join(out, "6-small-hud.png"))
    _save_truth(os.path.join(out, "6-small-hud.png"), truth)

    # English game screens (2026-11-10: Chinese and Brazilian players reading English games are the main audience)
    SANS, SERIF = "Noto Sans", "Noto Serif"
    # 7. English title menu
    img, p = canvas(1280, 720, "#10202e", "#2b1d33")
    text(p, 90, 170, "Ashes of the Silent Crown", font(56, SERIF, True), "#f3dca0")
    for i, s in enumerate(["New Game", "Continue", "Load Game", "Options", "Credits", "Quit to Desktop"]):
        text(p, 140, 300 + i * 52, ("> " if i == 0 else "  ") + s, font(30, SANS), "#ffffff" if i == 0 else "#c8c8d8")
    text(p, 1080, 700, "v0.9.4 beta", font(15, SANS), "#a0a0b0", False)
    text(p, 90, 700, "Press Enter to select, Esc to go back", font(15, SANS), "#a0a0b0", False)
    p.end()
    img.save(os.path.join(out, "7-en-title.png"))
    _save_truth(os.path.join(out, "7-en-title.png"), truth)

    # 8. English RPG status screen: labels, numbers, an item description
    img, p = canvas(1280, 720, "#1b2440", "#111726")
    panel(p, QRect(30, 30, 380, 660))
    for i, s in enumerate(["Items", "Equipment", "Skills", "Status", "Quests", "Save", "Return to Title"]):
        text(p, 70, 95 + i * 62, s, font(26, SANS), "#ffffff" if i == 1 else "#cfd3e6")
    panel(p, QRect(440, 30, 810, 300))
    text(p, 470, 80, "Elena   Lv 12   Apprentice Mage", font(24, SANS), "#ffe7a8")
    for i, (k, v) in enumerate([("HP", "340 / 520"), ("MP", "45 / 90"), ("Attack", "88"), ("Defense", "61"),
                                ("Agility", "73"), ("Luck", "19")]):
        x, y = 480 + (i % 2) * 380, 140 + (i // 2) * 52
        text(p, x, y, k, font(21, SANS), "#cfd3e6")
        text(p, x + 150, y, v, font(21, SANS), "#ffffff")
    panel(p, QRect(440, 350, 810, 340))
    text(p, 470, 395, "Equipped", font(23, SANS), "#ffe7a8")
    for i, (k, v) in enumerate([("Weapon", "Oak Staff"), ("Shield", "None"), ("Head", "Traveler's Hat"),
                                ("Body", "Novice Robe"), ("Accessory", "Starlight Pendant")]):
        text(p, 480, 445 + i * 44, k, font(19, SANS), "#9fa6c4")
        text(p, 640, 445 + i * 44, v, font(19, SANS), "#ffffff")
    text(p, 470, 675, "A strange pendant that slightly raises magic power. It glows faintly at night.", font(16, SANS),
         "#cfd3e6", False)
    p.end()
    img.save(os.path.join(out, "8-en-status.png"))
    _save_truth(os.path.join(out, "8-en-status.png"), truth)

    # 9. English dialogue box: long lines, name plate, contractions and punctuation
    img, p = canvas(1280, 720, "#f3a46b", "#5a3a6e")
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(40, 30, 60))
    p.drawEllipse(QPointF(300, 760), 520, 260)
    p.drawEllipse(QPointF(1050, 780), 600, 280)
    panel(p, QRect(60, 470, 1160, 220), (12, 14, 30, 225), "#e8d9b0")
    panel(p, QRect(90, 440, 170, 50), (60, 40, 90, 240), "#e8d9b0")
    text(p, 125, 475, "Elena", font(26, SANS, True), "#ffe7a8")
    text(p, 110, 545, "Hey, do you see that light on top of the tower? Is someone up there?", font(28, SANS))
    text(p, 110, 595, "Grandma always said that if it shone on a full-moon night,", font(28, SANS))
    text(p, 110, 645, "the gate would open... I guess she wasn't lying after all.", font(28, SANS))
    p.end()
    img.save(os.path.join(out, "9-en-dialogue.png"))
    _save_truth(os.path.join(out, "9-en-dialogue.png"), truth)

    # 10. English settings page: many small labels and values (14-17 px)
    img, p = canvas(1280, 720, "#15181f", "#0d0f14")
    text(p, 60, 70, "Settings", font(34, SANS, True), "#ffffff")
    rows = [("Master Volume", "80%"), ("Music Volume", "65%"), ("Sound Effects", "70%"), ("Voice Volume", "100%"),
            ("Text Speed", "Fast"), ("Auto-Advance Delay", "1.5 s"), ("Screen Mode", "Borderless Window"),
            ("Resolution", "1920 x 1080"), ("V-Sync", "On"), ("Subtitles", "On"), ("Language", "English"),
            ("Camera Shake", "Reduced"), ("Skip Unread Text", "Off")]
    for i, (k, v) in enumerate(rows):
        y = 130 + i * 40
        text(p, 80, y, k, font(17, SANS), "#d0d4dc", False)
        text(p, 560, y, v, font(17, SANS), "#ffffff", False)
    text(p, 80, 690, "Changes are saved automatically. Some options require a restart.", font(14, SANS), "#8a8f99", False)
    p.end()
    img.save(os.path.join(out, "10-en-settings.png"))
    _save_truth(os.path.join(out, "10-en-settings.png"), truth)

    # 11. English HUD: quest tracker, pickup messages, interaction prompt (small text)
    img, p = canvas(1280, 720, "#4d6b3a", "#26341d")
    panel(p, QRect(900, 20, 360, 160), (0, 0, 0, 150), "#00000000")
    text(p, 920, 50, "Quest: The Silent Crown", font(16, SANS, True), "#ffe7a8")
    text(p, 920, 78, "- Find the old key", font(15, SANS), "#ffffff")
    text(p, 920, 102, "- Talk to the blacksmith", font(15, SANS), "#ffffff")
    text(p, 920, 126, "- Gather herbs (2/5)", font(15, SANS), "#ffffff")
    text(p, 920, 150, "- Return to the village elder", font(15, SANS), "#ffffff")
    panel(p, QRect(540, 520, 200, 36), (0, 0, 0, 160), "#00000000")
    text(p, 555, 545, "[E] Examine chest", font(16, SANS), "#ffffff")
    panel(p, QRect(20, 590, 400, 110), (0, 0, 0, 150), "#00000000")
    text(p, 40, 620, "You picked up a Healing Herb!", font(15, SANS), "#b5ff9a")
    text(p, 40, 646, "You don't have enough gold.", font(15, SANS), "#ffb0b0")
    text(p, 40, 672, "Game saved.", font(15, SANS), "#ffffff")
    text(p, 20, 30, "HP 340/520   MP 45/90", font(14, SANS), "#ffffff")
    p.end()
    img.save(os.path.join(out, "11-en-hud.png"))
    _save_truth(os.path.join(out, "11-en-hud.png"), truth)
    return sorted(glob.glob(os.path.join(out, "*.png")))


def _save_truth(png, truth):
    with open(os.path.splitext(png)[0] + ".txt", "w", encoding="utf-8") as f:
        f.write("\n".join(truth) + "\n")
    truth.clear()


def default_images():
    imgs = sorted(glob.glob(os.path.join(SAMPLES, "*.png")))
    if os.path.isdir(USER_DIR):
        imgs += sorted(f for f in glob.glob(os.path.join(USER_DIR, "*")) if f.lower().endswith(IMG_EXT))
    return imgs


def images_4k(images, out):
    """4K versions: the built-in screens drawn again at 4K (sharp); other images enlarged (marked "upscaled":
    a real 4K capture is sharper, so the reading time is close but the accuracy can differ)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    d = os.path.join(out, "4k")
    drawn = {os.path.basename(f): f for f in make_samples(d, 3.0)}
    res = []
    for p in images:
        b = os.path.basename(p)
        if os.path.dirname(os.path.abspath(p)) == SAMPLES and b in drawn:
            dest = os.path.join(d, os.path.splitext(b)[0] + "-4k.png")
            os.replace(drawn[b], dest)
        else:
            img = QImage(p)
            if img.isNull():
                continue
            f = 3840 / max(1, img.width())
            dest = os.path.join(d, os.path.splitext(b)[0] + "-4k-upscaled.png")
            img.scaled(round(img.width() * f), round(img.height() * f), Qt.IgnoreAspectRatio,
                       Qt.SmoothTransformation).save(dest)
        res.append(dest)
    for f in drawn.values():
        if os.path.exists(f):
            os.remove(f)
    return res


# --------------------------------------------------------------------------------------------- one preset
def _apply_env(preset):
    """The preset's settings as environment overrides (config.toml is not changed)."""
    import config as cfgmod
    v = cfgmod.PRESETS[preset]["values"]
    env = {"LENSLATE_READING": v.get("ocr.reading", "accurate"), "LENSLATE_OCR_GPU": v.get("ocr.gpu", "off"),
           "LENSLATE_TRANSLATOR": v["translator.kind"], "LENSLATE_SETTLE": str(v.get("refresh.settle_step", 0.0))}
    if v.get("translator.llm_model"):
        env["LENSLATE_MODEL"] = v["translator.llm_model"]
    os.environ.update(env)


class _Log:
    """Stands in for lenslate's debug recorder: keeps the last refresh's record (its step times)."""
    on = True

    def __init__(self):
        self.last = None

    def text(self, _line):
        pass

    def record(self, rec, image=None):
        self.last = rec


def _render(img, cards, opacity):
    """The overlay's cards drawn onto a copy of the image (same layout code as the live overlay)."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
    import lenslate as ls
    out = img.copy()
    if not cards:
        return out
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    for c in ls.layout_cards(cards, QRect(0, 0, img.width(), img.height())):
        card, px, align, mx, my = c["layout"]
        bg = QColor(c["bg"])
        bg.setAlphaF(opacity)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(card, 3, 3)
        f = QFont(QGuiApplication.font())
        f.setPixelSize(px)
        p.setFont(f)
        r = card.adjusted(mx, my, -mx, -my)
        flags = Qt.TextWordWrap | Qt.AlignVCenter | (Qt.AlignLeft if align == "left" else Qt.AlignHCenter)
        if opacity < 0.95:   # the overlay's thin outline in the card colour
            p.setPen(QColor(c["bg"]))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                p.drawText(r.translated(dx, dy), flags, c["tr"] or "")
        p.setPen(QColor(c["fg"]))
        p.drawText(r, flags, c["tr"] or "")
    p.end()
    return out


def _read_once(img, ocr, tr, scale=None):
    """One forced refresh of the whole image through the real pipeline: (record, cards, scale)."""
    from PySide6.QtCore import QRect
    import lenslate as ls
    region = QRect(0, 0, img.width(), img.height())
    p = ls.OcrPipeline(region, region, [], True, None, ocr, tr, scale)
    p.grab = lambda: img
    got = {}
    p.done.connect(lambda cards, state: got.update(cards=cards, state=state))
    p.failed.connect(lambda msg: got.update(error=msg))
    ls.LOG.last = None
    t = time.time()
    p._run()
    wall = time.time() - t
    if "error" in got:
        raise RuntimeError(got["error"])
    rec = dict(ls.LOG.last or {})
    rec["wall_s"] = round(wall, 3)
    rec["first_s"] = rec.get("first_card_s")
    return rec, got.get("cards") or [], (got.get("state") or {}).get("scale", scale)


def run_preset(preset, images, out, progress=print):
    import config as cfgmod
    import textflow as tf
    import lenslate as ls
    _apply_env(preset)
    res = {"preset": preset, "label": cfgmod.PRESETS[preset]["label"], "images": {}}
    cache = os.path.join(out, "cache-%s.json" % preset)
    t = time.time()
    ocr = tf.OcrClient(HERE)
    tr = tf.Translator(HERE, cache, cfgmod.get("translator.language"), cfgmod.get("translator.llm_model"),
                       cfgmod.get("translator.ollama_url"), cfgmod.get("translator.kind"))
    res["translator"] = tr.label() if hasattr(tr, "label") else tr.kind
    want = cfgmod.PRESETS[preset]["values"]["translator.kind"]
    if tr.kind != want:
        res["note"] = "its model is not downloaded: used %s instead" % tr.kind
    elif tr.notice:   # a processor model is missing: those lines stay untranslated (it is never replaced)
        res["note"] = tr.notice
    ocr.warm()
    tr.warm()
    for warm_text in ("テスト", "测试"):   # load the translation model(s) now, so per-screen times are steady-state
        try:
            tr.translate_batch([warm_text])
        except Exception:  # noqa: BLE001 - that route's model is missing (see the note)
            pass
    res["startup_s"] = round(time.time() - t, 2)
    opacity = cfgmod.get("overlay.opacity")
    for path in images:
        name = os.path.basename(path)
        progress("  %s: %s" % (res["label"], name))
        from PySide6.QtGui import QImage
        img = QImage(path).convertToFormat(QImage.Format_RGB32)
        tf.langs._last_kana[0] = 0.0
        try:
            first, cards, scale = _read_once(img, ocr, tr)
            again, _c, _s = _read_once(img, ocr, tr, scale)
        except Exception as e:  # noqa: BLE001 - one bad image must not stop the run
            res["images"][name] = {"error": str(e)}
            continue
        prev = "preview-%s-%s.png" % (preset, os.path.splitext(name)[0])
        _render(img, cards, max(opacity, 0.85)).save(os.path.join(out, prev))
        res["images"][name] = {
            "find_read_s": round(first.get("gate_s", 0) + first.get("ocr_s", 0), 2),
            "translate_s": first.get("translate_s", 0), "total_s": first.get("wall_s"),
            "first_s": first.get("first_s"), "size": [img.width(), img.height()],
            "again_s": again.get("wall_s"), "lines": len(first.get("new") or []), "scale": scale,
            "new": [{"orig": n["orig"], "tr": n["tr"], "after_s": n.get("after_s")} for n in first.get("new") or []],
            "preview": prev}
    ocr.stop()
    tr.stop()
    import llm
    llm.RUNNER.stop()   # give the graphics card back before the next preset
    for f in glob.glob(os.path.join(out, "cache-%s*" % preset)):   # one file per translator kind
        os.remove(f)
    return res


# --------------------------------------------------------------------------------------------- report
CSS = """
:root{--bg:#f6f7f9;--fg:#1d2228;--mut:#5d6773;--card:#fff;--line:#d9dde3;--acc:#2f7fd1;--good:#1f8a4c;--bad:#c0392b}
@media (prefers-color-scheme:dark){:root{--bg:#16191d;--fg:#e6e9ed;--mut:#9aa4af;--card:#1f2328;--line:#343a42;--acc:#5aa7f0;--good:#4cc17e;--bad:#e57366}}
body{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0;padding:24px;max-width:1500px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:19px;margin:34px 0 8px}h3{font-size:16px;margin:18px 0 6px}
.mut{color:var(--mut)}table{border-collapse:collapse;background:var(--card);margin:8px 0}
td,th{border:1px solid var(--line);padding:5px 9px;text-align:left;vertical-align:top}th{font-weight:600}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.best{color:var(--good);font-weight:600}.slow{color:var(--bad)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px}
figure img{width:100%;border-radius:4px;display:block}figcaption{font-size:13px;margin-top:6px}
.wrap{overflow-x:auto}.tr td{font-size:14px;min-width:160px}
"""


def report(results, images, out, hw):
    import config as cfgmod
    names = [os.path.basename(p) for p in images]
    for p in images:
        shutil.copy(p, os.path.join(out, "orig-" + os.path.basename(p)))
    sizes = {}
    for r in results:
        for n, d in r["images"].items():
            if d.get("size"):
                sizes[n] = "%d×%d" % tuple(d["size"])

    def head(n):
        return "%s<br><span class=mut>%s</span>" % (html.escape(n), sizes.get(n, ""))
    h = ["<!doctype html><meta charset=utf-8><title>lenslate testbench</title><style>%s</style>" % CSS,
         "<h1>lenslate testbench</h1><p class=mut>%s · %s · %s · translating into %s · %s</p>" % (
             html.escape(hw["cpu"]), html.escape(hw.get("gpu") or "no NVIDIA card"), time.strftime("%Y-%m-%d %H:%M"),
             html.escape(cfgmod.get("translator.language")), "each preset started with an empty cache"),
         "<p class=mut><b>first time</b> = until the last card shows: the area is read and every line is new "
         "(translated by the model); <b>first cards</b> = when the first cards appear (areas are shown one by one); "
         "<b>again</b> = the area is read again and every translation comes from the cache (in live play "
         "an area that did not change is not even read: ~0.1 s). <b>start-up</b> = loading "
         "the models once when lenslate starts. Live play adds ~0.1 s per refresh for capturing the window. "
         "Quality = Balanced on still images; live it also waits up to 0.8 s for typed-out text to finish. "
         "The whole image is the area here: picking only a dialogue box is faster. %s</p>" % (
             "Big text: read at half size ([ocr] big_text = half)." if os.environ.get("LENSLATE_BIG_TEXT") == "half"
             else "Big text: normal size.")]
    # summary: rows = presets, columns = images (first time / seen again)
    h.append("<h2>Time until the translation shows</h2><div class=wrap><table><tr><th>Preset</th>"
             "<th>start-up</th>" + "".join("<th>%s</th>" % head(n) for n in names) + "</tr>")
    best = {}
    for n in names:
        vals = [r["images"].get(n, {}).get("total_s") for r in results]
        vals = [v for v in vals if v is not None]
        best[n] = min(vals) if vals else None
    for r in results:
        row = "<tr><td><b>%s</b>%s</td><td class=n>%.1f s</td>" % (
            r["label"], "<br><span class=mut>%s</span>" % html.escape(r["note"]) if r.get("note") else "", r["startup_s"])
        for n in names:
            d = r["images"].get(n, {})
            if "error" in d:
                row += "<td class=slow>failed: %s</td>" % html.escape(d["error"])
                continue
            cls = "best" if d.get("total_s") == best[n] else "slow" if best[n] and d["total_s"] > 3 * best[n] + 0.5 else ""
            row += ("<td class=n><span class='%s'>%.2f s</span><br><span class=mut>first cards %s<br>again %.2f s"
                    "</span></td>") % (cls, d["total_s"], "%.2f s" % d["first_s"] if d.get("first_s") else "—",
                                       d["again_s"])
        h.append(row + "</tr>")
    h.append("</table></div>")
    # step breakdown
    h.append("<h2>Steps (first time)</h2><div class=wrap><table><tr><th>Preset</th>" + "".join(
        "<th>%s</th>" % head(n) for n in names) + "</tr>")
    for r in results:
        row = "<tr><td><b>%s</b></td>" % r["label"]
        for n in names:
            d = r["images"].get(n, {})
            row += "<td class=n>%s</td>" % ("—" if "error" in d or not d else
                                            "find+read %.2f s<br>translate %.2f s<br>%d lines%s" % (
                                                d["find_read_s"], d["translate_s"], d["lines"],
                                                ", read at 2x" if d.get("scale") == 2.0 else ""))
        h.append(row + "</tr>")
    h.append("</table></div>")
    # per image: previews + line-by-line translations
    for n in names:
        h.append("<h2>%s</h2><div class=grid><figure><a href='orig-%s'><img src='orig-%s' loading=lazy></a>"
                 "<figcaption>original</figcaption></figure>" % (html.escape(n), html.escape(n), html.escape(n)))
        for r in results:
            d = r["images"].get(n, {})
            if d.get("preview"):
                h.append("<figure><a href='%s'><img src='%s' loading=lazy></a><figcaption><b>%s</b> · %.2f s · "
                         "%d lines</figcaption></figure>" % (d["preview"], d["preview"], r["label"], d["total_s"],
                                                            d["lines"]))
        h.append("</div>")
        origs = []
        for r in results:
            for x in r["images"].get(n, {}).get("new", []):
                if x["orig"] not in origs:
                    origs.append(x["orig"])
        if origs:
            h.append("<h3>Lines</h3><div class=wrap><table class=tr><tr><th>Original</th>" + "".join(
                "<th>%s</th>" % r["label"] for r in results) + "</tr>")
            for o in origs[:60]:
                row = "<tr><td>%s</td>" % html.escape(o)
                for r in results:
                    m = {x["orig"]: x["tr"] for x in r["images"].get(n, {}).get("new", [])}
                    row += "<td>%s</td>" % (html.escape(m[o] or "") if o in m else "<span class=mut>(not read)</span>")
                h.append(row + "</tr>")
            h.append("</table></div>")
    path = os.path.join(out, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(h))
    return path


# --------------------------------------------------------------------------------------------- OCR models
OCR_MODELS = ["v6-small", "v5-mobile", "meiki"]
OCR_MODEL_INFO = {"v6-small": "PP-OCRv6 small (default)", "v5-mobile": "PP-OCRv5 mobile",
                  "meiki": "meikiocr (Ultrafast)"}


def _truth(path):
    """The answer key of a built-in screen (the strings it was drawn with), or None for other images."""
    import re
    b = re.sub(r"-4k(-upscaled)?$", "", os.path.splitext(os.path.basename(path))[0])
    f = os.path.join(SAMPLES, b + ".txt")
    if not os.path.exists(f):
        f = os.path.join(USER_DIR, b + ".txt")    # your own screenshot's answer key, if you wrote one
    if not os.path.exists(f):
        return None
    import unicodedata
    keep = []
    for ln in open(f, encoding="utf-8").read().splitlines():
        ln = unicodedata.normalize("NFKC", ln).replace("▶", "").replace("▼", "").replace("✔", "").replace("□", "")
        # English keeps its word spaces (a reader that drops them hurts the translation); other text loses all
        ln = " ".join(ln.split()) if re.search(r"[A-Za-z]{2}", ln) else re.sub(r"\s", "", ln)
        if ln and not ln.isdigit():   # editor line numbers are not text anyone translates
            keep.append(ln)
    return keep


def _accuracy(truth, texts):
    """Share of the answer key's characters found, in order, in the text read. Each drawn string is matched against
    all the text read joined together, so an engine that splits one drawn line into two pieces (or merges two lines
    into one block) is not punished for it; only missing or wrong characters count."""
    import re
    from difflib import SequenceMatcher
    import unicodedata
    joined = unicodedata.normalize("NFKC", " ".join(texts))   # full/half-width forms count alike
    flat, spaced = re.sub(r"\s", "", joined), " ".join(joined.split())
    total = hit = 0
    for g in truth:
        blob = spaced if " " in g else flat
        total += len(g)
        hit += sum(m.size for m in SequenceMatcher(None, g, blob, autojunk=False).get_matching_blocks())
    if not total:
        return None
    recall = hit / total
    # precision: letters read that the answer key has (repeated or junk letters lower it; numbers and punctuation,
    # which the keys leave out when they stand alone, do not count)
    from collections import Counter
    want = Counter(c for g in truth for c in g if c.isalpha())
    got = Counter(c for c in flat if c.isalpha())
    precision = sum(min(n, want[c]) for c, n in got.items()) / max(1, sum(got.values()))
    return 2 * recall * precision / max(1e-9, recall + precision)


class _GpuWatch:
    """Highest GPU memory (MB) a process used while this runs (nvidia-smi every 0.2 s)."""

    def __init__(self, pid):
        import subprocess
        import threading
        self.pid, self.peak, self.stop_ev = pid, 0, threading.Event()

        def loop():
            while not self.stop_ev.is_set():
                try:
                    out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                                          "--format=csv,noheader,nounits"], capture_output=True, text=True,
                                         timeout=3).stdout
                    for row in out.splitlines():
                        pid_s, mb = [x.strip() for x in row.split(",")]
                        if int(pid_s) == self.pid:
                            self.peak = max(self.peak, int(mb))
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
                self.stop_ev.wait(0.2)
        self.t = threading.Thread(target=loop, daemon=True)
        self.t.start()

    def done(self):
        self.stop_ev.set()
        self.t.join()
        return self.peak


def run_ocr_model(model, reading, gpu, images, out, progress=print):
    """One OCR model in one reading mode through the real pipeline (translator: quickmt, it only fills the cards)."""
    import bench
    import textflow as tf
    import config as cfgmod
    os.environ.update(LENSLATE_OCR_MODEL="v6-small" if model == "meiki" else model, LENSLATE_READING=reading,
                      LENSLATE_OCR_GPU=gpu, LENSLATE_TRANSLATOR="mt", LENSLATE_SETTLE="0")
    res = {"model": model, "reading": reading, "gpu": gpu, "images": {}}
    cache = os.path.join(out, "cache-ocr.json")
    t = time.time()
    ocr = tf.OcrClient(HERE)
    tr = tf.Translator(HERE, cache, cfgmod.get("translator.language"), cfgmod.get("translator.llm_model"),
                      cfgmod.get("translator.ollama_url"), "mt")
    ocr.warm()
    if ocr.started_env.get("LENSLATE_OCR_GPU") != ocr._launch_env(dict(ocr.started_env)).get("LENSLATE_OCR_GPU"):
        res["note"] = "graphics card memory was not free: read on the processor"
    tr.warm()
    tr.translate_batch(["テスト"])
    tr.translate_batch(["测试"])
    res["startup_s"] = round(time.time() - t, 2)
    pid = ocr.proc.pid
    from PySide6.QtGui import QImage
    watch = _GpuWatch(pid) if gpu != "off" else None
    for path in images:
        name = os.path.basename(path)
        progress("  %s %s %s: %s" % (model, reading, gpu, name))
        img = QImage(path).convertToFormat(QImage.Format_RGB32)
        tf.langs._last_kana[0] = 0.0
        _read_once(img, ocr, tr)   # warm-up for this image size (first-shape cost of the runtime)
        c0 = bench._cpu_s(pid)
        try:
            rec, cards, _scale = _read_once(img, ocr, tr)
        except Exception as e:  # noqa: BLE001
            res["images"][name] = {"error": str(e)}
            continue
        texts = [ln["text"] for ln in rec.get("ocr_lines") or []]
        truth = _truth(path)
        res["images"][name] = {
            "read_s": round(rec.get("gate_s", 0) + rec.get("ocr_s", 0), 2), "first_s": rec.get("first_s"),
            "total_s": rec.get("wall_s"), "cpu_s": round(bench._cpu_s(pid) - c0, 2), "size": [img.width(), img.height()],
            "texts": texts, "acc": None if truth is None else round(_accuracy(truth, texts), 4)}
    res["gpu_mb"] = watch.done() if watch else 0
    ocr.stop()
    tr.stop()
    for f in glob.glob(os.path.join(out, "cache-ocr*")):
        os.remove(f)
    return res


def ocr_report(results, images, out, hw):
    names = [os.path.basename(p) for p in images]
    for p in images:
        shutil.copy(p, os.path.join(out, "orig-" + os.path.basename(p)))

    def label(r):
        return "%s<br><span class=mut>%s · %s</span>" % (OCR_MODEL_INFO.get(r["model"], r["model"]),
                                                         {"accurate": "Careful", "fast": "Quick",
                                                          "ultrafast": "Ultrafast"}[r["reading"]],
                                                         "graphics card" if r["gpu"] != "off" else "processor")
    h = ["<!doctype html><meta charset=utf-8><title>OCR model comparison</title><style>%s</style>" % CSS,
         "<h1>OCR model comparison</h1><p class=mut>%s · %s · %s · %s OCR threads</p>" % (
             html.escape(hw["cpu"]), html.escape(hw.get("gpu") or "no NVIDIA card"), time.strftime("%Y-%m-%d %H:%M"),
             os.environ.get("LENSLATE_OCR_THREADS", "6")),
         "<p class=mut>The whole image is the area, read through the real pipeline after one warm-up read of the "
         "same image size. <b>read</b> = finding + reading time; <b>CPU</b> = processor core-seconds the OCR helper "
         "used for that read (6 cores busy for 1 s = 6); <b>accuracy</b> = share of the drawn characters that "
         "were read (built-in screens only; your screenshots have no answer key, compare their text below). "
         "Quick reading always finds text with PP-OCRv5 mobile; the model choice changes its reader. "
         "<b>GPU</b> = highest graphics memory of the OCR helper.</p>",
         "<h2>Summary</h2><div class=wrap><table><tr><th>Model</th><th>start-up</th><th>GPU</th>" +
         "".join("<th>%s<br><span class=mut>%s</span></th>" % (html.escape(n), "") for n in names) + "</tr>"]
    for r in results:
        row = "<tr><td>%s%s</td><td class=n>%.1f s</td><td class=n>%s</td>" % (
            label(r), "<br><span class=slow>%s</span>" % r["note"] if r.get("note") else "", r["startup_s"],
            "%d MB" % r["gpu_mb"] if r["gpu_mb"] else "—")
        for n in names:
            d = r["images"].get(n, {})
            if not d or "error" in d:
                row += "<td class=slow>%s</td>" % html.escape(d.get("error", "—"))
                continue
            row += "<td class=n>%.2f s<br><span class=mut>CPU %.1f</span>%s</td>" % (
                d["read_s"], d["cpu_s"], "" if d["acc"] is None else "<br><b>%.1f%%</b>" % (100 * d["acc"]))
        h.append(row + "</tr>")
    h.append("</table></div>")
    for n in names:
        h.append("<h2>%s</h2><figure style='max-width:720px'><img src='orig-%s' loading=lazy></figure>"
                 % (html.escape(n), html.escape(n)))
        h.append("<div class=wrap><table class=tr><tr>" + "".join("<th>%s</th>" % label(r) for r in results) + "</tr><tr>")
        for r in results:
            d = r["images"].get(n, {})
            h.append("<td>%s</td>" % "<br>".join(html.escape(t) for t in d.get("texts", [])))
        h.append("</tr></table></div>")
    path = os.path.join(out, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(h))
    return path


def ocr_cli(args, images, flags):
    import config as cfgmod
    import bench
    import ocrgpu
    models = OCR_MODELS
    for i, a in enumerate(args):
        if a == "--models" and i + 1 < len(args):
            models = args[i + 1].split(",")
    modes = [("accurate", "off"), ("fast", "off")]
    if ocrgpu.installed() and "--no-gpu" not in flags:
        modes += [("accurate", "all"), ("fast", "all")]
    out = os.path.join(cfgmod.CACHE_DIR, "testbench", "ocr-" + time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out, exist_ok=True)
    if "--4k" in flags:
        images = images + images_4k(images, out)
    print("lenslate testbench ocr: %d images x %d models x %d modes -> %s" % (len(images), len(models), len(modes), out))
    results = []
    for reading, gpu in modes:
        for m in models:
            rd = reading
            if m == "meiki":           # meikiocr: its own reading mode, always on the processor
                if (reading, gpu) != ("fast", "off"):
                    continue
                rd = "ultrafast"
            print("%s %s %s ..." % (m, rd, gpu), flush=True)
            results.append(run_ocr_model(m, rd, gpu, images, out, lambda s: print(s, flush=True)))
            with open(os.path.join(out, "results.json"), "w") as f:
                json.dump(results, f, ensure_ascii=False, indent=1)
            ocr_report(results, images, out, bench.hardware())
    path = ocr_report(results, images, out, bench.hardware())
    print("report: %s" % path)
    return 0


# --------------------------------------------------------------------------------------------- command
def cli(args):
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841 - fonts and images need it
    import config as cfgmod
    if args[:1] == ["samples"]:
        for f in make_samples():
            print(f)
        return 0
    ocr_mode = args[:1] == ["ocr"]
    if ocr_mode:
        args = args[1:]
    presets = list(cfgmod.PRESET_ORDER)
    images, flags = [], set()
    i = 0
    while i < len(args):
        if args[i] == "--models":
            i += 2
            continue
        if args[i] in ("--4k", "--half", "--no-gpu"):
            flags.add(args[i])
            i += 1
            continue
        if args[i] == "--presets" and i + 1 < len(args):
            presets = [p for p in args[i + 1].split(",") if p in cfgmod.PRESETS]
            i += 2
            continue
        images.append(os.path.abspath(args[i]))
        i += 1
    if not os.path.exists(SAMPLES) or not glob.glob(os.path.join(SAMPLES, "*.png")):
        make_samples()
    images = images or default_images()
    os.environ["LENSLATE_BIG_TEXT"] = "half" if "--half" in flags else "normal"
    os.environ["LENSLATE_SOURCES"] = "ja,zh,en"   # test screens include Chinese
    os.environ["LENSLATE_DEBUG"] = "0"
    import lenslate as ls
    ls.LOG = _Log()
    if ocr_mode:
        return ocr_cli(args, images, flags)
    out = os.path.join(cfgmod.CACHE_DIR, "testbench", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out, exist_ok=True)
    big = images_4k(images, out) if "--4k" in flags else []
    print("lenslate testbench: %d images x %d presets -> %s" % (len(images), len(presets), out))
    results = []
    import ocrgpu
    import bench
    for p in presets:
        if cfgmod.PRESETS[p]["values"].get("ocr.gpu") == "all" and not ocrgpu.installed():
            print("  skipping %s: reading on the graphics card is not installed (lenslate ocr-gpu install)" % p)
            continue
        if p == "quality" and "balanced" in [r["preset"] for r in results]:
            # identical on still images (the typewriter wait only acts on text that is still being typed)
            q = json.loads(json.dumps(next(r for r in results if r["preset"] == "balanced")))
            q.update(preset="quality", label=cfgmod.PRESETS["quality"]["label"],
                     note="same as Balanced on still images (+ up to 0.8 s typewriter wait live)")
            results.append(q)
            continue
        print("preset %s ..." % p, flush=True)
        r = run_preset(p, images, out, lambda s: print(s, flush=True))
        if big:   # 4K: a second pass with its own empty cache (the same text was just translated at 1080p)
            r4 = run_preset(p, big, out, lambda s: print(s, flush=True))
            r["images"].update(r4["images"])
        results.append(r)
    with open(os.path.join(out, "results.json"), "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    path = report(results, images + big, out, bench.hardware())
    print("report: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
