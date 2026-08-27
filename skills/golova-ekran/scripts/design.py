#!/usr/bin/env python3
"""Шаг 4 — геометрия кадра и вся статичная графика.

Раскладки (холст 1920×1080):
  A  экран карточкой слева + голова справа — рабочая лошадка
  B  экран крупно + голова маленькой карточкой — когда надо читать экран
  D  инфографика на месте экрана + та же голова
  C  голова во весь кадр на своей размытой копии — если записи экрана нет

Коробки под экран фиксированы, а РЕАЛЬНЫЙ прямоугольник считается под
пропорции твоего кропа: экран вписывается в коробку без полей и без растяжки.
Поэтому маски и тени рисуются под конкретный проект, а не берутся готовыми.
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

M = os.path.join(lib.project_dir(), "masks")
FB, FR = lib.font_path(True), lib.font_path(False)
f = lambda p, s: ImageFont.truetype(p, s)


# ── геометрия ───────────────────────────────────────────────────────────────
def head_portrait():
    inf = lib.video_info(P.TAKES[0]["head"])
    t = P.TAKES[0]
    if t.get("head_from_screen"):
        _, _, w, h = t["head_from_screen"]
        return h > w
    return inf["h"] > inf["w"]


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


def fit(box, ar):
    """Вписываем прямоугольник с пропорциями ar в коробку, без полей."""
    x, y, w, h, r = box
    if w / h > ar:
        w2, h2 = int(round(h * ar)), h
    else:
        w2, h2 = w, int(round(w / ar))
    w2 -= w2 % 2
    h2 -= h2 % 2
    return (x + (w - w2) // 2, y + (h - h2) // 2, w2, h2, r)


def geometry():
    ar = screen_ar()
    port = head_portrait()
    g = dict(
        ar=ar, portrait=port,
        A_SCR=fit(A_BOX, ar), B_SCR=fit(B_BOX, ar),
        A_HEAD=A_HEAD_P if port else A_HEAD_L,
        B_HEAD=B_HEAD_P if port else B_HEAD_L,
        A_CARD=A_CARD, B_CARD=B_CARD,
    )
    # холст нормализованного экрана: с запасом под самую крупную раскладку
    bw, bh = g["B_SCR"][2], g["B_SCR"][3]
    k = max(1.0, 1500 / bw, 1056 / bh)
    g["SCR_W"] = int(bw * k) // 2 * 2
    g["SCR_H"] = int(bh * k) // 2 * 2
    for tag in ("A", "B"):
        card = g[f"{tag}_CARD"]
        g[f"{tag}_CANVAS"] = (card[2] + MARGIN * 2, CARD_TOP + card[3] + MARGIN)
        g[f"{tag}_POS"] = (card[0] - MARGIN, card[1] - CARD_TOP)
        g[f"{tag}_INNER"] = (card[0] + BZ, card[1] + BZ,
                             card[2] - BZ * 2, card[3] - BZ * 2)
    return g


def cover_crop(w, h):
    """Масштабируем с покрытием и подрезаем по центру — без растяжки."""
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


# ── текст с запасным шрифтом под редкие символы ─────────────────────────────
def text(d, xy, s, font, fill, bold=True):
    """Пишет строку, подставляя запасной шрифт под символы, которых нет
    в основном. Повод — знак рубля: в Arial его нет, и вместо ₽ рисуется
    пустой прямоугольник. Проверяем только необычные символы: обычная
    кириллица и латиница есть везде, а проверка не бесплатная."""
    x, y = xy
    runs = []
    for ch in s:
        good = True if ord(ch) < 0x2000 else lib.has_glyph(font.path, ch)
        if runs and runs[-1][0] == good:
            runs[-1][1] += ch
        else:
            runs.append([good, ch])
    for good, part in runs:
        fo = font
        if not good:
            fb = lib.fallback_for(part[0], bold)
            if fb:
                fo = ImageFont.truetype(fb[0], font.size, index=fb[1])
        d.text((x, y), part, font=fo, fill=fill)
        x += d.textlength(part, fo)
    return x


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
    fo = f(FB, 27)
    pw = int(d.textlength(label, fo)) + 76
    pl = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(pl).rounded_rectangle(
        [MARGIN, MARGIN, MARGIN + pw, MARGIN + PLAQUE_H], 12, fill=PLAQUE)
    im.alpha_composite(pl)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([MARGIN + 16, MARGIN + 15, MARGIN + 22, MARGIN + PLAQUE_H - 15],
                        3, fill=ORANGE)
    text(d, (MARGIN + 36, MARGIN + 13), label, fo, INK)
    im.save(path)


def bw_plaque(path, title, sub):
    """Подпись на единственную оговорку, которую оставили в кадре нарочно.
    Подложка накрывает ОБЕ строки: под ней бывает светлый скриншот."""
    im = Image.new("RGBA", (1160, 136), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = max(int(d.textlength(title, f(FB, 31))), int(d.textlength(sub, f(FR, 25)))) + 100
    d.rounded_rectangle([0, 0, w, 128], 14, fill=(8, 9, 12, 242))
    d.rounded_rectangle([22, 22, 28, 106], 3, fill=ORANGE)
    text(d, (50, 20), title, f(FB, 31), INK)
    text(d, (50, 70), sub, f(FR, 25), (206, 201, 201), bold=False)
    im.save(path)


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


def panel(spec, k, cw, ch, r):
    """Один кадр панели: зажжено k пунктов из списка, остальные притушены."""
    im = panel_base(cw, ch, r)
    d = ImageDraw.Draw(im)
    pad = int(cw * 0.067)
    y = int(ch * 0.078)
    text(d, (pad + 4, y), spec.get("eyebrow", ""), f(FB, 21), ORANGE)
    ft = f(FB, int(ch * 0.10))
    x = text(d, (pad, y + 40), spec.get("w1", "") + " ", ft, INK)
    text(d, (x, y + 40), spec.get("w2", ""), ft, ORANGE)
    y += 40 + int(ch * 0.127)

    items = spec.get("items", [])
    bullets = spec.get("bullets", [])
    if items:
        five = len(items) >= 5
        fn, fi = f(FB, 25), f(FB, 35 if five else 37)
        step = int(ch * (0.093 if five else 0.105))
        yy = y + 40
        for i, line in enumerate(items):
            live = i < k
            d.text((pad + 4, yy + 7), f"{i + 1:02d}", font=fn,
                   fill=ORANGE if live else OFF)
            text(d, (pad + 62, yy), line, fi, INK if live else (56, 51, 55))
            yy += step
    elif bullets:
        fi = f(FB, 36)
        yy = y + 34
        for line in bullets:
            d.ellipse([pad + 6, yy + 13, pad + 20, yy + 27], fill=ORANGE)
            text(d, (pad + 48, yy), line, fi, INK)
            yy += 66
        if spec.get("cta"):
            d.rounded_rectangle([pad, yy + 26, pad + 446, yy + 96], 14, fill=ORANGE)
            text(d, (pad + 38, yy + 44), spec["cta"], f(FB, 32), (20, 10, 6))
    if spec.get("note"):
        text(d, (pad + 4, ch - 96), spec["note"], f(FR, 25), DIM, bold=False)
    return im


def main():
    os.makedirs(M, exist_ok=True)
    g = geometry()
    for tag in ("A", "B"):
        s, h = g[f"{tag}_SCR"], g[f"{tag}_HEAD"]
        mask(s[2], s[3], s[4], f"{M}/mask_scr_{tag.lower()}.png")
        mask(h[2], h[3], h[4], f"{M}/mask_head_{tag.lower()}.png")
        shadow([s, h], f"{M}/shadow_{tag.lower()}.png")
    bw = getattr(P, "BW_LABEL", ("ОГОВОРКА — ВОТ ТАК ОНА ВЫГЛЯДИТ",
                                 "эту оставили нарочно, остальные вырезаны"))
    bw_plaque(f"{M}/bw_plaque.png", bw[0], bw[1])

    cw, ch, r = g["A_SCR"][2], g["A_SCR"][3], g["A_SCR"][4]
    total = 0
    for name, spec in getattr(P, "PANELS", {}).items():
        n = max(1, len(spec.get("items", [])) or 1)
        for k in range(1, n + 1):
            panel(spec, k, cw, ch, r).save(f"{M}/panel_{name}_{k}.png")
        total += n
    lib.write_json("geometry.json", {k: v for k, v in g.items()})
    print(f"голова {'вертикальная' if g['portrait'] else 'горизонтальная'} · "
          f"пропорции экрана {g['ar']:.3f}")
    print(f"  A: экран {g['A_SCR'][:4]} · голова {g['A_HEAD'][:4]}")
    print(f"  B: экран {g['B_SCR'][:4]} · голова {g['B_HEAD'][:4]}")
    print(f"  холст экрана {g['SCR_W']}×{g['SCR_H']}")
    print(f"маски и тени готовы · панелей {total} кадров "
          f"({len(getattr(P, 'PANELS', {}))} наборов)")


if __name__ == "__main__":
    main()
