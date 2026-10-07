#!/usr/bin/env python3
"""Шаг 4 — геометрия кадра и вся статичная графика.

Классические раскладки (холст 1920×1080, собирает ffmpeg — blocks.py):
  A  экран карточкой + голова колонкой — рабочая лошадка
  B  экран крупно + голова маленькой карточкой — когда надо читать экран
  D  инфографика на месте экрана + та же голова
  C  голова во весь кадр на своей размытой копии — если записи экрана нет

Раскладки студии (собирает композитор — compose.py, с перестроениями 0,7 с):
  H   голова в карточке сбоку, вторая половина кадра — под графику
  HC  голова крупнее, ближе к центру, графики мало
  S   экран окном на тёмной подложке + камера-прямоугольник в нижнем углу
  SH  голова как в H, а на второй половине — запись экрана меньшим окном
  T   полноэкранная типографическая карточка, голос идёт дальше

Голова всегда стоит НАПРОТИВ взгляда (FACE_SIDE / GAZE в project.py): кто
смотрит влево, тот стоит справа. Вся геометрия описана для лица справа
и зеркалится по x, если лицо слева. Картинку самого человека не зеркалим
никогда — только коробки.

Коробки под экран фиксированы, а РЕАЛЬНЫЙ прямоугольник считается под
пропорции твоего кропа: экран вписывается в коробку без полей и без растяжки.
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import lib

P = lib.load_project()
W, H = 1920, 1080
BEZEL = (16, 17, 21)
PLAQUE = (8, 9, 12, 236)
ORANGE = tuple(getattr(P, "ACCENT", (232, 84, 30)))
INK = (245, 243, 240)
DIM = (150, 142, 145)
BG = (18, 16, 19)
OFF = (62, 57, 61)
CARD_BG = (28, 24, 29)

# ── классика (лицо справа) ──────────────────────────────────────────────────
A_BOX = (56, 132, 1160, 816, 18)
B_BOX = (40, 40, 1420, 1000, 18)
A_HEAD_P = (1300, 40, 560, 1000, 26)       # голова-колонка (телефон вертикально)
B_HEAD_P = (1490, 360, 380, 680, 22)
A_HEAD_L = (1300, 383, 560, 315, 22)       # голова-карточка (камера горизонтально)
B_HEAD_L = (1490, 786, 380, 214, 18)
A_CARD = (96, 564, 596, 344, 16)           # окно вставки внутри экранной зоны A
B_CARD = (80, 620, 660, 380, 16)
MARGIN, PLAQUE_H, GAP, BZ = 40, 54, 18, 10
CARD_TOP = MARGIN + PLAQUE_H + GAP

# ── студия (лицо справа) ────────────────────────────────────────────────────
# Голова описана не кропом в пикселях, а долей рамки: какую часть её высоты
# занимает голова (от макушки до подбородка) и где по высоте стоит центр лица.
# Кроп из этого считается под конкретный исходник — телефон, камеру, что угодно.
STUDIO_HEAD = {
    "H":  dict(box=(1100, 60, 760, 960, 30), head=0.50, eye=0.40),
    "HC": dict(box=(630, 40, 900, 1000, 30), head=0.56, eye=0.40),
    # камера на экранной раскладке: вертикальный прямоугольник, голова с плечами
    # и кусок комнаты. Квадрат вплотную к лицу режет голову по краям — «кринжево».
    "S":  dict(box=(1534, 608, 330, 418, 26), head=0.47, eye=0.37),
}
S_BOX = (40, 66, 1580, 889, 18)            # окно экрана; камера заходит на его угол
# SH: голова как в H, а вторая половина кадра — не пустая темнота, а запись экрана
# меньшим окном; над окном заголовок, под окном плашки-факты
SH_BOX = (60, 250, 1000, 562, 14)
H_PANEL = (96, 190, 920, 700, 24)          # зона под панель в H
H_CARD = (110, 330, 820, 462, 16)          # окно вставки в H
CHIP_S = (36, 36)                          # плашки на экране: отступ от угла окна
CHIP_H = (0, 96)                           # плашки в H: над панелью (y)
HEAD_MAX = 0.9    # масштаб головы к исходному пикселю — потолок, вместе с наездом
PUSH = 0.035      # медленный наезд внутри плана: 1.00 → 1.035
CAM_MAX = 1.8     # потолок наезда на экран в S: дальше текст экрана мылится
CAM_MAX_SH = 2.0  # в маленьком окне SH до 2× — это ещё не растяжение исходника

M = os.path.join(lib.project_dir(), "masks")
FB, FR = lib.font_path(True), lib.font_path(False)
f = lambda p, s: ImageFont.truetype(p, s)
FIT_LOG = []      # что пришлось ужать или перенести — печатаем в конце


# ── геометрия ───────────────────────────────────────────────────────────────
def head_portrait():
    inf = lib.video_info(P.TAKES[0]["head"])
    t = P.TAKES[0]
    if t.get("head_from_screen"):
        _, _, w, h = t["head_from_screen"]
        return h > w
    return inf["h"] > inf["w"]


def head_size():
    inf = lib.video_info(P.TAKES[0]["head"])
    return inf["w"], inf["h"]


def screen_ar():
    """Пропорции рабочего окна: из crop, а если его нет — из самого файла."""
    for t in P.TAKES:
        if t.get("screen"):
            if t.get("crop"):
                cw, ch = t["crop"][0], t["crop"][1]
            else:
                i = lib.video_info(t["screen"])
                cw, ch = i["w"], i["h"]
            return cw / ch
    return 16 / 9


def screen_native_w():
    for t in P.TAKES:
        if t.get("screen"):
            return t["crop"][0] if t.get("crop") else lib.video_info(t["screen"])["w"]
    return 1920


def used_modes():
    """Какие раскладки и панели реально стоят в MODES: {режим: {панели}}."""
    out = {}
    for spans in getattr(P, "MODES", {}).values():
        for sp in spans:
            out.setdefault(sp[2], set())
            if len(sp) > 3 and sp[3]:
                out[sp[2]].add(sp[3])
    return out


def fit(box, ar, align="center"):
    """Вписываем прямоугольник с пропорциями ar в коробку, без полей."""
    x, y, w, h, r = box
    if w / h > ar:
        w2, h2 = int(round(h * ar)), h
    else:
        w2, h2 = w, int(round(w / ar))
    w2 -= w2 % 2
    h2 -= h2 % 2
    dx = {"left": 0, "right": w - w2}.get(align, (w - w2) // 2)
    return (x + dx, y + (h - h2) // 2, w2, h2, r)


def mirror(box):
    x, y, w, h, *rest = box
    return (W - x - w, y, w, h, *rest)


def head_frame(tag, side):
    """Рамка и кроп головы для раскладки студии.

    Правила (правка владельца по пробе):
      · голова не крупнее HEAD_MAX от исходного пикселя, ВКЛЮЧАЯ медленный наезд —
        съёмка с телефона апскейла не держит, крупный план делаем рамкой, а не зумом;
      · кроп не выходит за исходник: если рамка не влезает — уменьшаем рамку,
        а не растягиваем картинку.
    """
    spec = STUDIO_HEAD[tag]
    x, y, bw, bh, r = spec["box"]
    sw, sh = head_size()
    face = getattr(P, "FACE", None) or {}
    fx = float(face.get("x", 0.5)) * sw
    top, chin = float(face.get("top", 0.2)), float(face.get("chin", 0.5))
    face_h = max(0.05, chin - top) * sh
    fy = (top + chin) / 2 * sh

    smax = HEAD_MAX / (1 + PUSH)
    crop_h = face_h / spec["head"]
    if bh / crop_h > smax:                 # голова вышла бы крупнее потолка
        crop_h = bh / smax
    crop_w = crop_h * bw / bh
    k = max(crop_w / sw, crop_h / sh)
    if k > 1:                              # кроп шире исходника — сжимаем его
        crop_w, crop_h = crop_w / k, crop_h / k
    scale = bh / crop_h
    note = ""
    if scale > smax + 1e-6:
        # рамка великовата для такого исходника: уменьшаем её, а не тянем картинку
        nbw = int(crop_w * smax) // 2 * 2
        nbh = int(crop_h * smax) // 2 * 2
        cx = x + bw / 2
        x = int(round(cx - nbw / 2)) if tag != "S" else x + bw - nbw
        if tag == "S":
            y = y + bh - nbh
        bw, bh = nbw, nbh
        scale = bh / crop_h
        note = " (рамка уменьшена: исходник мельче, апскейл запрещён)"
    cx0 = min(max(fx - crop_w / 2, 0), sw - crop_w)
    cy0 = min(max(fy - spec["eye"] * crop_h, 0), sh - crop_h)
    box = (x, y, bw, bh, r)
    return box, (round(cx0, 2), round(cy0, 2), round(crop_w, 2), round(crop_h, 2)), \
        round(scale, 3), round(face_h / crop_h, 2), note


def geometry():
    ar = screen_ar()
    port = head_portrait()
    side = lib.face_side(P)
    flip = mirror if side == "left" else (lambda b: b)
    g = dict(
        ar=ar, portrait=port, side=side,
        A_SCR=flip(fit(A_BOX, ar)), B_SCR=flip(fit(B_BOX, ar)),
        A_HEAD=flip(A_HEAD_P if port else A_HEAD_L),
        B_HEAD=flip(B_HEAD_P if port else B_HEAD_L),
        A_CARD=flip(A_CARD), B_CARD=flip(B_CARD),
    )
    # студия
    g["S_SCR"] = flip(fit(S_BOX, ar, align="left"))
    g["HEAD_SRC"] = head_size()
    face = getattr(P, "FACE", None) or {}
    sw, sh = g["HEAD_SRC"]
    g["FACE"] = (float(face.get("x", 0.5)) * sw,
                 (float(face.get("top", 0.2)) + float(face.get("chin", 0.5))) / 2 * sh)
    notes = {}
    for tag in STUDIO_HEAD:
        box, crop, scale, share, note = head_frame(tag, side)
        g[f"{tag}_HEAD"] = flip(box)
        g[f"{tag}_CROP"] = crop
        g[f"{tag}_SCALE"] = scale
        notes[tag] = (scale, share, note)
    g["SH_SCR"] = flip(fit(SH_BOX, ar, align="left"))
    g["SH_HEAD"], g["SH_CROP"], g["SH_SCALE"] = g["H_HEAD"], g["H_CROP"], g["H_SCALE"]
    g["H_PANEL"] = flip(H_PANEL)
    g["H_CARD"] = flip(H_CARD)
    g["PUSH"], g["HEAD_MAX"], g["CAM_MAX"] = PUSH, HEAD_MAX, CAM_MAX
    g["CAM_MAX_SH"] = CAM_MAX_SH
    # плашки: левый верхний угол картинки плашки (у неё 20 px прозрачного поля под тень)
    sx, sy = g["S_SCR"][0], g["S_SCR"][1]
    g["CHIP_S"] = (sx + CHIP_S[0] - 20, sy + CHIP_S[1] - 20)
    g["CHIP_H"] = (g["H_PANEL"][0] - 20, CHIP_H[1] - 20)
    shx, shy, _, shh, _ = g["SH_SCR"]
    g["CHIP_SH"] = (shx - 20, shy + shh + 30 - 20)   # под окном, в ряд

    # холст нормализованного экрана: с запасом под самую крупную раскладку
    bw, bh = g["B_SCR"][2], g["B_SCR"][3]
    k = max(1.0, 1500 / bw, 1056 / bh)
    used = used_modes()
    scr_w = int(bw * k) if (used.keys() & {"A", "B"}) or not (used.keys() & {"S", "SH"}) else 0
    if "S" in used or "SH" in used:
        # окно экрана в S крупное, а в SH наезд идёт до 2× — берём всё, что есть
        # в исходнике, но не больше, чем нужно наезду
        need = max(int(g["S_SCR"][2] * CAM_MAX) if "S" in used else 0,
                   int(g["SH_SCR"][2] * CAM_MAX_SH) if "SH" in used else 0)
        scr_w = max(scr_w, min(screen_native_w(), need))
    g["SCR_W"] = scr_w // 2 * 2
    g["SCR_H"] = int(round(g["SCR_W"] / ar)) // 2 * 2
    for tag in ("A", "B", "H"):
        card = g[f"{tag}_CARD"]
        g[f"{tag}_CANVAS"] = (card[2] + MARGIN * 2, CARD_TOP + card[3] + MARGIN)
        g[f"{tag}_POS"] = (card[0] - MARGIN, card[1] - CARD_TOP)
        g[f"{tag}_INNER"] = (card[0] + BZ, card[1] + BZ,
                             card[2] - BZ * 2, card[3] - BZ * 2)
    return g, notes


def cover_crop(w, h):
    """Масштабируем с покрытием и подрезаем по центру — без растяжки."""
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


# ── текст с запасным шрифтом под редкие символы ─────────────────────────────
def _runs(s, font):
    runs = []
    for ch in s:
        good = True if ord(ch) < 0x2000 else lib.has_glyph(font.path, ch)
        if runs and runs[-1][0] == good:
            runs[-1][1] += ch
        else:
            runs.append([good, ch])
    return runs


def _font_for(good, part, font, bold):
    if good:
        return font
    fb = lib.fallback_for(part[0], bold)
    return ImageFont.truetype(fb[0], font.size, index=fb[1]) if fb else font


def text(d, xy, s, font, fill, bold=True):
    """Пишет строку, подставляя запасной шрифт под символы, которых нет
    в основном. Повод — знак рубля: в Arial его нет, и вместо ₽ рисуется
    пустой прямоугольник. Проверяем только необычные символы: обычная
    кириллица и латиница есть везде, а проверка не бесплатная."""
    x, y = xy
    for good, part in _runs(s, font):
        fo = _font_for(good, part, font, bold)
        d.text((x, y), part, font=fo, fill=fill)
        x += d.textlength(part, fo)
    return x


def tlen(d, s, font, bold=True):
    """Ширина строки так, как её нарисует text() — с запасными шрифтами."""
    return sum(d.textlength(part, _font_for(good, part, font, bold))
               for good, part in _runs(s, font))


def fit_lines(d, s, path, size, max_w, where, max_lines=2, min_ratio=0.72,
              bold=True):
    """Кегль и переносы под ширину рамки. Текст НЕ выходит за max_w никогда.

    Сначала ужимаем кегль до min_ratio, потом переносим по словам (до
    max_lines строк), и только если не помогло и это — ужимаем дальше.
    Всё, что пришлось ужать или перенести, попадает в FIT_LOG: design.py
    печатает это списком, чтобы человек решил, сократить ли формулировку.

    Повод — проба на живом материале: у узлов схемы стояла фиксированная
    ширина и запрет переноса, и «Реальная практика» вылезла из рамки.
    """
    s = s.strip()
    lo = max(10, int(size * min_ratio))
    for sz in range(size, lo - 1, -1):
        fo = f(path, sz)
        if tlen(d, s, fo, bold) <= max_w:
            if sz < size:
                FIT_LOG.append(f"{where}: «{s}» ужат {size}→{sz} px")
            return fo, [s]
    words = s.split()
    if max_lines > 1 and len(words) > 1:
        for sz in range(size, lo - 1, -1):
            fo = f(path, sz)
            lines, cur = [], ""
            for w_ in words:
                cand = (cur + " " + w_).strip()
                if tlen(d, cand, fo, bold) <= max_w or not cur:
                    cur = cand
                else:
                    lines.append(cur)
                    cur = w_
            lines.append(cur)
            if len(lines) <= max_lines and all(tlen(d, ln, fo, bold) <= max_w
                                               for ln in lines):
                FIT_LOG.append(f"{where}: «{s}» перенесён на {len(lines)} строки, "
                               f"{sz} px")
                return fo, lines
    sz = lo
    while sz > 8 and tlen(d, s, f(path, sz), bold) > max_w:
        sz -= 1
    FIT_LOG.append(f"{where}: «{s}» НЕ ВЛЕЗ даже в {lo} px — ужат до {sz} px, "
                   "сократи формулировку")
    return f(path, sz), [s]


# ── маски, тени, плашки ─────────────────────────────────────────────────────
def mask(w, h, r, path):
    im = Image.new("L", (w, h), 0)
    ImageDraw.Draw(im).rounded_rectangle([0, 0, w - 1, h - 1], r, fill=255)
    im.save(path)


def shadow(boxes, path, blur=28, alpha=155, dy=14):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for x, y, w, h, r in boxes:
        d.rounded_rectangle([x, y + dy, x + w, y + h + dy], r, fill=(0, 0, 0, alpha))
    im.filter(ImageFilter.GaussianBlur(blur)).save(path)


def deco(label, canvas, card_wh, radius, path):
    """Слой вставки: тень + тёмный бейзел + плашка с подписью над ним."""
    cw, ch = canvas
    w, h = card_wh
    im = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    sh = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        [MARGIN, CARD_TOP + 16, MARGIN + w, CARD_TOP + h + 16], radius,
        fill=(0, 0, 0, 190))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(26)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([MARGIN, CARD_TOP, MARGIN + w, CARD_TOP + h], radius,
                        fill=BEZEL + (255,), outline=(255, 255, 255, 46), width=2)
    fo, lines = fit_lines(d, label, FB, 27, w - 76, f"вставка «{label}»", max_lines=1)
    pw = int(tlen(d, lines[0], fo)) + 76
    pl = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(pl).rounded_rectangle(
        [MARGIN, MARGIN, MARGIN + pw, MARGIN + PLAQUE_H], 12, fill=PLAQUE)
    im.alpha_composite(pl)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([MARGIN + 16, MARGIN + 15, MARGIN + 22, MARGIN + PLAQUE_H - 15],
                        3, fill=ORANGE)
    text(d, (MARGIN + 36, MARGIN + (PLAQUE_H - fo.size) // 2 - 1), lines[0], fo, INK)
    im.save(path)


def bw_plaque(path, title, sub, max_w=1160):
    """Подпись на единственную оговорку, которую оставили в кадре нарочно.
    Подложка накрывает ОБЕ строки: под ней бывает светлый скриншот."""
    im = Image.new("RGBA", (max_w, 136), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ft, lt = fit_lines(d, title, FB, 31, max_w - 100, "плашка оговорки", max_lines=1)
    fs, ls = fit_lines(d, sub, FR, 25, max_w - 100, "плашка оговорки", max_lines=1,
                       bold=False)
    w = max(int(tlen(d, lt[0], ft)), int(tlen(d, ls[0], fs, False))) + 100
    d.rounded_rectangle([0, 0, w, 128], 14, fill=(8, 9, 12, 242))
    d.rounded_rectangle([22, 22, 28, 106], 3, fill=ORANGE)
    text(d, (50, 20), lt[0], ft, INK)
    text(d, (50, 70), ls[0], fs, (206, 201, 201), bold=False)
    im.save(path)


def chip(spec, max_w, path):
    """Плашка-подпись на экране или над панелью: «+141 % КЛИКОВ».

    Ширина — по тексту, а не фиксированная: фиксированная ширина и запрет
    переноса и дают вылезающий текст. Не влезает — кегль вниз, потом перенос.
    Акцентная плашка — белым текстом: акцент на акценте не читается.
    """
    dark = spec.get("style") == "dark"
    tmp = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    padx, pady = 24, 16
    sub = spec.get("sub", "")
    fs = f(lib.font_mono(), 15)
    sub_w = int(tlen(tmp, sub.upper(), fs, False)) + 16 if sub else 0
    fo, lines = fit_lines(tmp, spec["text"], FB, 32, max_w - 2 * padx - sub_w,
                          f"плашка «{spec['text']}»", max_lines=2)
    lh = int(fo.size * 1.18)
    tw = max(int(tlen(tmp, ln, fo)) for ln in lines)
    w = tw + 2 * padx + sub_w
    h = lh * len(lines) + 2 * pady
    im = Image.new("RGBA", (w + 40, h + 46), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([20, 30, 20 + w, 30 + h], 14, fill=(0, 0, 0, 120))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(im)
    fill = (14, 15, 18, 236) if dark else ORANGE + (255,)
    d.rounded_rectangle([20, 20, 20 + w, 20 + h], 14, fill=fill,
                        outline=(255, 255, 255, 30) if dark else None, width=1)
    y = 20 + pady - int(fo.size * 0.06)
    for ln in lines:
        text(d, (20 + padx, y), ln, fo, INK if dark else (255, 255, 255))
        y += lh
    if sub:
        text(d, (20 + padx + tw + 16, 20 + h // 2 - 9), sub.upper(), fs,
             (200, 200, 205) if dark else (255, 236, 226), bold=False)
    im.save(path)
    return im.size


# ── инфографика ─────────────────────────────────────────────────────────────
def panel_base(cw, ch, r):
    im = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, cw - 1, ch - 1], r, fill=BG + (255,))
    g = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse([-int(cw * .2), ch - int(ch * .28),
                               int(cw * .48), ch + int(ch * .46)], fill=ORANGE + (34,))
    m = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, cw - 1, ch - 1], r, fill=255)
    im.alpha_composite(Image.composite(g, Image.new("RGBA", (cw, ch), (0, 0, 0, 0)), m)
                       .filter(ImageFilter.GaussianBlur(90)))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, cw - 1, ch - 1], r,
                                         outline=(255, 255, 255, 26), width=2)
    return im


def panel(spec, k, cw, ch, r, name="", log=True):
    """Один кадр панели: зажжено k пунктов из списка, остальные притушены.

    Вёрстка потоком: строки встают одна под другой по реальной высоте,
    каждая подогнана под ширину панели (fit_lines). Не влезло по высоте —
    весь набор кеглей уменьшается ступенькой, пока не влезет.
    """
    global FIT_LOG
    for scale in (1.0, 0.92, 0.85, 0.78, 0.72, 0.66):
        saved = list(FIT_LOG)
        im = panel_base(cw, ch, r)
        d = ImageDraw.Draw(im)
        pad = int(cw * 0.067)
        inner = cw - 2 * pad
        y = int(ch * 0.078)
        where = f"панель «{name}»"
        if spec.get("eyebrow"):
            fo, ls = fit_lines(d, spec["eyebrow"], FB, int(21 * scale), inner - 4,
                               where, max_lines=1)
            text(d, (pad + 4, y), ls[0], fo, ORANGE)
            y += int(fo.size * 1.9)
        w1, w2 = spec.get("w1", ""), spec.get("w2", "")
        tsz = int(ch * 0.10 * scale)
        if w1 or w2:
            ft = f(FB, tsz)
            if tlen(d, f"{w1} {w2}".strip(), ft) <= inner:
                x = text(d, (pad, y), (w1 + " ") if w1 else "", ft, INK)
                text(d, (x, y), w2, ft, ORANGE)
                y += int(tsz * 1.27)
            else:
                for part, col in ((w1, INK), (w2, ORANGE)):
                    if not part:
                        continue
                    fo, ls = fit_lines(d, part, FB, tsz, inner, where, max_lines=2)
                    for ln in ls:
                        text(d, (pad, y), ln, fo, col)
                        y += int(fo.size * 1.12)
                y += int(tsz * 0.15)
        items = spec.get("items", [])
        bullets = spec.get("bullets", [])
        if items:
            five = len(items) >= 5
            fn = f(FB, int(25 * scale))
            isz = int((35 if five else 37) * scale)
            gap = int(ch * (0.035 if five else 0.045))
            yy = y + int(28 * scale)
            for i, line in enumerate(items):
                live = i < k
                fo, ls = fit_lines(d, line, FB, isz, inner - 62, where, max_lines=2)
                d.text((pad + 4, yy + int(fo.size * 0.2)), f"{i + 1:02d}", font=fn,
                       fill=ORANGE if live else OFF)
                for ln in ls:
                    text(d, (pad + 62, yy), ln, fo, INK if live else (56, 51, 55))
                    yy += int(fo.size * 1.2)
                yy += gap
            y = yy
        elif bullets:
            isz = int(36 * scale)
            yy = y + int(24 * scale)
            for line in bullets:
                fo, ls = fit_lines(d, line, FB, isz, inner - 48, where, max_lines=2)
                d.ellipse([pad + 6, yy + 13, pad + 20, yy + 27], fill=ORANGE)
                for ln in ls:
                    text(d, (pad + 48, yy), ln, fo, INK)
                    yy += int(fo.size * 1.25)
                yy += int(18 * scale)
            if spec.get("cta"):
                fo, ls = fit_lines(d, spec["cta"], FB, int(32 * scale), inner - 76,
                                   where, max_lines=1)
                bw_ = int(tlen(d, ls[0], fo)) + 76
                d.rounded_rectangle([pad, yy + 26, pad + bw_, yy + 26 + int(fo.size * 2.2)],
                                    14, fill=ORANGE)
                text(d, (pad + 38, yy + 26 + int(fo.size * 0.55)), ls[0], fo, (20, 10, 6))
                yy += 26 + int(fo.size * 2.2)
            y = yy
        note_h = 0
        if spec.get("note"):
            fo, ls = fit_lines(d, spec["note"], FR, int(25 * scale), inner - 4, where,
                               max_lines=2, bold=False)
            note_h = int(fo.size * 1.3) * len(ls) + int(ch * 0.06)
        if y + note_h <= ch - int(ch * 0.05) or scale == 0.66:
            if spec.get("note"):
                ny = ch - note_h
                for ln in ls:
                    text(d, (pad + 4, ny), ln, fo, DIM, bold=False)
                    ny += int(fo.size * 1.3)
            if y + note_h > ch - int(ch * 0.05):
                FIT_LOG.append(f"{where}: пункты не влезли по высоте даже ужатые — "
                               "убери пункт или сократи")
            elif scale < 1.0 and log:
                FIT_LOG.append(f"{where}: ужата по высоте до {scale:.2f}")
            if not log:
                FIT_LOG = saved
            return im
        FIT_LOG = saved


def tcard(spec, name):
    """Полноэкранная типографическая карточка (раскладка T): удар на 1,5–3 с.

    eyebrow — мелкая подпись капсом, w1 — слово/цифра белым, w2 — акцентом,
    sub — строка пояснения. Каждая строка подогнана под ширину кадра.
    """
    im = Image.new("RGBA", (W, H), (14, 15, 18, 255))
    d = ImageDraw.Draw(im)
    for yy in range(20, H, 40):
        for xx in range(20, W, 40):
            d.ellipse([xx - 1, yy - 1, xx + 1, yy + 1], fill=(255, 255, 255, 14))
    pad = 120
    inner = W - 2 * pad
    where = f"карточка «{name}»"
    big = int(spec.get("size", 180))
    rows = []
    if spec.get("w1"):
        rows.append(fit_lines(d, spec["w1"], FB, big, inner, where, max_lines=2) + (INK,))
    if spec.get("w2"):
        rows.append(fit_lines(d, spec["w2"], FB, big, inner, where, max_lines=2) + (ORANGE,))
    total = sum(int(fo.size * 1.06) * len(ls) for fo, ls, _ in rows)
    y = (H - total) // 2 + 10
    if spec.get("eyebrow"):
        fe, le = fit_lines(d, spec["eyebrow"].upper(), lib.font_mono(), 22, inner,
                           where, max_lines=1, bold=False)
        d.rounded_rectangle([pad + 4, y - 56, pad + 16, y - 44], 3, fill=ORANGE)
        text(d, (pad + 32, y - 62), le[0], fe, (146, 151, 161), bold=False)
    for fo, ls, col in rows:
        for ln in ls:
            text(d, (pad - int(fo.size * 0.04), y - int(fo.size * 0.12)), ln, fo, col)
            y += int(fo.size * 1.06)
    if spec.get("sub"):
        fs, lsub = fit_lines(d, spec["sub"], FR, 34, inner, where, max_lines=2, bold=False)
        y += 24
        for ln in lsub:
            text(d, (pad, y), ln, fs, (146, 151, 161), bold=False)
            y += int(fs.size * 1.3)
    return im


def sh_header(spec, width, name):
    """Заголовок над окном SH: моно-подпись капсом + крупная строка (w1 белым, w2 акцентом).

    Ширина — ровно окно экрана; длинная строка ужимается и переносится,
    за окно не выходит."""
    tmp = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    where = f"заголовок SH «{name}»"
    fe, le = fit_lines(tmp, (spec.get("eyebrow") or "").upper(), lib.font_mono(), 18,
                       width - 24, where, max_lines=1, bold=False)
    line = " ".join(x for x in (spec.get("w1"), spec.get("w2")) if x)
    fl, ll = fit_lines(tmp, line, FB, 46, width, where, max_lines=2)
    lh = int(fl.size * 1.12)
    h = 34 + lh * len(ll) + 6
    im = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if le[0]:
        d.rounded_rectangle([2, 6, 12, 16], 2, fill=ORANGE)
        text(d, (24, 0), le[0], fe, (146, 151, 161), bold=False)
    y = 34
    w1 = spec.get("w1") or ""
    for ln in ll:
        # акцентом — то, что относится к w2
        if w1 and ln.startswith(w1) and spec.get("w2"):
            x = text(d, (0, y), w1 + " ", fl, INK)
            text(d, (x, y), ln[len(w1):].strip(), fl, ORANGE)
        else:
            text(d, (0, y), ln, fl, ORANGE if (spec.get("w2") and not ln.startswith(w1)) else INK)
        y += lh
    return im


def main():
    os.makedirs(M, exist_ok=True)
    g, notes = geometry()
    used = used_modes()
    for tag in ("A", "B"):
        s, h = g[f"{tag}_SCR"], g[f"{tag}_HEAD"]
        mask(s[2], s[3], s[4], f"{M}/mask_scr_{tag.lower()}.png")
        mask(h[2], h[3], h[4], f"{M}/mask_head_{tag.lower()}.png")
        shadow([s, h], f"{M}/shadow_{tag.lower()}.png")
    bw = getattr(P, "BW_LABEL", ("ОГОВОРКА — ВОТ ТАК ОНА ВЫГЛЯДИТ",
                                 "эту оставили нарочно, остальные вырезаны"))
    bw_plaque(f"{M}/bw_plaque.png", bw[0], bw[1])

    panels = getattr(P, "PANELS", {})
    total = 0
    for mode, size_key in (("D", "A_SCR"), ("H", "H_PANEL")):
        cw, ch, r = g[size_key][2], g[size_key][3], g[size_key][4]
        suffix = "" if mode == "D" else "_h"
        for name in sorted(used.get(mode, ())):
            spec = panels.get(name)
            if spec is None:
                lib.die(f"в MODES стоит панель «{name}», а в PANELS её нет")
            n = max(1, len(spec.get("items", [])) or 1)
            for k in range(1, n + 1):
                panel(spec, k, cw, ch, r, name, log=(k == n)) \
                    .save(f"{M}/panel_{name}{suffix}_{k}.png")
            total += n
    for name in sorted(used.get("SH", ())):
        spec = panels.get(name)
        if spec is None:
            lib.die(f"в MODES стоит заголовок SH «{name}», а в PANELS его нет")
        sh_header(spec, g["SH_SCR"][2], name).save(f"{M}/shhead_{name}.png")
        total += 1
    for name in sorted(used.get("T", ())):
        spec = panels.get(name)
        if spec is None:
            lib.die(f"в MODES стоит карточка T «{name}», а в PANELS её нет")
        tcard(spec, name).save(f"{M}/tcard_{name}.png")
        total += 1
    chips = getattr(P, "CHIPS", [])
    for i, c in enumerate(chips):
        chip(c, c.get("max_w", 1000), f"{M}/chip_{i:02d}.png")

    lib.write_json("geometry.json", {k: v for k, v in g.items()})
    print(f"голова {'вертикальная' if g['portrait'] else 'горизонтальная'} "
          f"{g['HEAD_SRC'][0]}×{g['HEAD_SRC'][1]} · лицо {'справа' if g['side'] == 'right' else 'слева'}"
          f" · пропорции экрана {g['ar']:.3f}")
    if any(m in used for m in ("A", "B", "C", "D")):
        print(f"  A: экран {g['A_SCR'][:4]} · голова {g['A_HEAD'][:4]}")
        print(f"  B: экран {g['B_SCR'][:4]} · голова {g['B_HEAD'][:4]}")
    if any(m in used for m in lib.STUDIO):
        for tag in ("H", "HC", "S"):
            sc, share, note = notes[tag]
            print(f"  {tag:2s}: голова {g[f'{tag}_HEAD'][:4]} · масштаб {sc:.2f} "
                  f"(с наездом {sc * (1 + PUSH):.2f}, потолок {HEAD_MAX}) · "
                  f"голова {share * 100:.0f} % высоты рамки{note}")
        print(f"  S : окно экрана {g['S_SCR'][:4]}")
        print(f"  SH: голова как в H, окно экрана {g['SH_SCR'][:4]}, заголовок над ним, "
              "плашки под ним")
        hp = g["H_PANEL"]
        print(f"  зона под графику в H: x {hp[0]}–{hp[0] + hp[2]}, y {hp[1]}–{hp[1] + hp[3]}")
    print(f"  холст экрана {g['SCR_W']}×{g['SCR_H']}")
    print(f"маски и тени готовы · панелей и карточек {total} кадров · плашек {len(chips)}")
    if FIT_LOG:
        print("\nтекст подогнан под рамки:")
        for line in dict.fromkeys(FIT_LOG):
            print(f"   {'✗' if 'НЕ ВЛЕЗ' in line or 'не влезли' in line else '·'} {line}")


if __name__ == "__main__":
    main()
