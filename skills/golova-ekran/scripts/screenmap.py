#!/usr/bin/env python3
"""Шаг 4б — что на экране, пока человек говорит: карта «фраза → кадр экрана».

Запись экрана — это материал, а не фон. Если в куске человек говорит про то же,
что видно на экране (график, таблица запросов, страница сайта), экран надо
показывать — в раскладке S или SH — и наезжать туда, о чём речь. Без карты
это упускается: на пробе так нашлись кабинет с коммерческими запросами
и зелёные столбцы индексации, которых в первой сборке не было вовсе.

Для каждого оставленного сегмента — кадр записи экрана из середины сегмента
(с учётом сдвига и кропа) и сама фраза. Сетки — work/probe/screenmap_NN.jpg.
Работает сразу после transcribe: монтаж ещё не нужен.

  montage.py screenmap
"""
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

import lib

P = lib.load_project()
TW, TH = 480, 270
COLS, PER = 3, 12


def grab(path, t, crop):
    vf = (f"crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]}," if crop else "") + \
        f"scale={TW}:{TH}:force_original_aspect_ratio=decrease,pad={TW}:{TH}:(ow-iw)/2:(oh-ih)/2"
    raw = subprocess.run([lib.FF, "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}",
                          "-i", path, "-frames:v", "1", "-vf", vf, "-pix_fmt", "rgb24",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    if len(raw) < TW * TH * 3:
        return Image.new("RGB", (TW, TH), (30, 30, 30))
    return Image.frombuffer("RGB", (TW, TH), raw[:TW * TH * 3], "raw", "RGB", 0, 1)


def wrap(d, s, font, w, lines=3):
    out, cur = [], ""
    for word in s.split():
        cand = (cur + " " + word).strip()
        if d.textlength(cand, font=font) <= w or not cur:
            cur = cand
        else:
            out.append(cur)
            cur = word
    out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1].rstrip(".,") + "…"
    return out


def main():
    T = lib.read_json("transcript.json")
    takes = {t["id"]: t for t in P.TAKES}
    drop = set(getattr(P, "DROP", []))
    scrap = getattr(P, "SCRAP_DB", -40.0)
    keep = [s for s in T if s["i"] not in drop and s["mean"] >= scrap
            and takes[s["take"]].get("screen")]
    if not keep:
        print("записи экрана нет ни у одного дубля — карта не нужна")
        return
    d_out = os.path.join(lib.work_dir(), "probe")
    os.makedirs(d_out, exist_ok=True)
    fb = ImageFont.truetype(lib.font_path(True), 17)
    fr = ImageFont.truetype(lib.font_path(False), 16)
    made = []
    for k in range(0, len(keep), PER):
        chunk = keep[k:k + PER]
        rows = (len(chunk) + COLS - 1) // COLS
        cell_h = TH + 92
        im = Image.new("RGB", (TW * COLS, cell_h * rows), (12, 12, 12))
        dr = ImageDraw.Draw(im)
        for j, s in enumerate(chunk):
            t = takes[s["take"]]
            x, y = (j % COLS) * TW, (j // COLS) * cell_h
            mid = (s["a"] + s["b"]) / 2 + float(t.get("offset", 0.0))
            im.paste(grab(t["screen"], mid, t.get("crop")), (x, y))
            dr.text((x + 8, y + TH + 4), f"№{s['i']} [{s['take']}] {lib.ms(s['a'])}",
                    font=fb, fill=(255, 190, 70))
            for n, line in enumerate(wrap(dr, s["txt"], fr, TW - 16)):
                dr.text((x + 8, y + TH + 26 + n * 20), line, font=fr, fill=(225, 225, 225))
        p = os.path.join(d_out, f"screenmap_{k // PER + 1:02d}.jpg")
        im.save(p, quality=84)
        made.append(p)
    print(f"сегментов с экраном: {len(keep)}")
    for p in made:
        print(f"  {p}")
    print("посмотри: где экран про то же, о чём говорит человек, — там S или SH и камера\n"
          "по ключам на нужный виджет; где экран не про то — H с панелью или графикой")


if __name__ == "__main__":
    main()
