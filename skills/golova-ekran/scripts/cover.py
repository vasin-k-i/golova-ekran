#!/usr/bin/env python3
"""Шаг 9 — обложка 1920×1080 для YouTube.

Настраивается блоком COVER в project.py:

    COVER = dict(
        eyebrow="АВТОМОНТАЖ ГОВОРЯЩЕЙ ГОЛОВЫ",
        lines=["ЭТО ВИДЕО", "СМОНТИРОВАЛ", "ИИ"],   # последняя — акцентом
        badge="0 ₽ ЗА РОЛИК",
        sub=["паузы, оговорки и вставки —", "всё автоматом, локально"],
        chips=[("01", "БЛОГЕРУ", "монтирует сам, по ночам"), …],
        photo=("01", 175.0),          # дубль и секунда, откуда взять портрет
        photo_crop="crop=950:1316:65:260",   # необязательно
    )

Заголовок обязан читаться в превью 320×180 — кегль подбирается под колонку
автоматически, но три-четыре слова в строке уже не влезут, так что пиши коротко.
"""
import os
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import lib
import design

P = lib.load_project()
C = getattr(P, "COVER", None)
W, H = 1920, 1080
ORANGE = design.ORANGE
INK, DIM, CARD = design.INK, design.DIM, design.CARD_BG
FB, FR = design.FB, design.FR
f = lambda p, s: ImageFont.truetype(p, s)
COL = (70, 1160)


def photo():
    take_id, t = C.get("photo", (P.TAKES[0]["id"], lib.duration(P.TAKES[0]["head"]) / 2))
    src = next(x["head"] for x in P.TAKES if x["id"] == take_id)
    raw = os.path.join(lib.work_dir(), "cover_src.png")
    vf = (C["photo_crop"] + "," if C.get("photo_crop") else "")
    vf += "scale=820:-2,eq=contrast=1.06:saturation=1.04"
    lib.run([lib.FF, "-y", "-v", "error", "-ss", f"{t}", "-i", src,
             "-frames:v", "1", "-vf", vf, raw])
    im = Image.open(raw).convert("RGB")
    im = im.resize((820, max(1080, im.size[1] * 820 // im.size[0])), Image.LANCZOS)
    if im.size[1] > 1080:
        top = min(im.size[1] - 1080, max(0, (im.size[1] - 1080) // 3))
        im = im.crop((0, top, 820, top + 1080))
    im = im.convert("RGBA")
    a = Image.new("L", im.size, 255)
    d = ImageDraw.Draw(a)
    for x in range(320):                       # левый край растворяется в фоне
        d.line([(x, 0), (x, im.size[1])], fill=int(255 * (x / 320) ** 1.4))
    for y in range(70):
        d.line([(0, im.size[1] - 1 - y), (im.size[0], im.size[1] - 1 - y)],
               fill=int(255 * (y / 70)))
    im.putalpha(a.filter(ImageFilter.GaussianBlur(3)))
    return im


def fit_size(d, lines, target, start=140, low=54):
    for size in range(start, low, -2):
        fo = f(FB, size)
        if all(d.textlength(s, fo) <= target for s in lines):
            return size
    return low


def main():
    if not C:
        print("COVER в project.py не задан — обложку не делаю")
        return
    im = Image.new("RGB", (W, H), (15, 14, 16))
    glow = Image.new("RGB", (W, H), (15, 14, 16))
    g = ImageDraw.Draw(glow)
    g.ellipse([-460, H - 430, 900, H + 620], fill=(96, 34, 12))
    g.ellipse([1150, -420, 2200, 420], fill=(38, 34, 44))
    im = Image.blend(im, glow.filter(ImageFilter.GaussianBlur(150)), 0.55)
    p = photo()
    im.paste(p, (1060, 0), p)

    d = ImageDraw.Draw(im)
    colw = COL[1] - COL[0]
    if C.get("eyebrow"):
        design.text(d, (COL[0], 92), C["eyebrow"], f(FB, 25), ORANGE)

    lines = C.get("lines", [])
    size = fit_size(d, lines, colw)
    fh = f(FB, size)
    y = 138
    for i, line in enumerate(lines):
        design.text(d, (COL[0] - 4, y), line, fh,
                    ORANGE if i == len(lines) - 1 and len(lines) > 1 else INK)
        y += int(size * 1.12)
    y -= int(size * 1.12)

    if C.get("badge"):
        bx = COL[0] + int(d.textlength(lines[-1], fh)) + 48
        by = y + 20
        bw = int(d.textlength(C["badge"], f(FB, 46))) + 68
        d.rounded_rectangle([bx, by, bx + bw, by + 96], 18, fill=ORANGE)
        design.text(d, (bx + 34, by + 22), C["badge"], f(FB, 46), (22, 11, 6))

    if C.get("sub"):
        d.rounded_rectangle([COL[0], 706, COL[0] + 6, 796], 3, fill=ORANGE)
        for i, line in enumerate(C["sub"][:2]):
            design.text(d, (COL[0] + 26, 704 + i * 44), line, f(FR, 31), DIM, bold=False)

    chips = C.get("chips", [])
    if chips:
        cw, gap, top, chh = 336, 22, 866, 128
        for i, (num, who, pain) in enumerate(chips[:3]):
            x0 = COL[0] + i * (cw + gap)
            d.rounded_rectangle([x0, top, x0 + cw, top + chh], 16, fill=CARD,
                                outline=(70, 62, 68), width=2)
            d.text((x0 + 24, top + 22), num, font=f(FB, 22), fill=ORANGE)
            d.text((x0 + 24, top + 50), who, font=f(FB, 33), fill=INK)
            design.text(d, (x0 + 24, top + 92), pain, f(FR, 23), DIM, bold=False)

    name = getattr(P, "OUT_NAME", "Ролик")
    out = os.path.join(lib.out_dir(), f"Обложка — {name}.jpg")
    im.save(out, quality=95, subsampling=0)
    im.resize((480, 270), Image.LANCZOS).save(
        os.path.join(lib.work_dir(), "cover_preview.png"))
    print(f"обложка: {out} · кегль заголовка {size} px")
    print(f"превью для проверки читаемости: {lib.work_dir()}/cover_preview.png")


if __name__ == "__main__":
    main()
