#!/usr/bin/env python3
"""Шаг 10 — контрольные сетки кадров с готового мастера. Смотреть глазами.

  work/check/changes_NN.jpg  каждая смена плана: до, посреди перестроения, после
  work/check/cams_NN.jpg     каждый наезд на экран и стоп-кадр: начало и конец
  work/check/overview.jpg    12 кадров по всей длине

Кадры берутся из мастера, а не из плана: проверять надо то, что уедет к зрителю.
Ищешь: не наехало ли что-то на лицо, не вылез ли текст, не уехал ли за рамку
наезда тот кусок экрана, ради которого сцену снимали, стоит ли голова справа.
"""
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

import lib

P = lib.load_project()
PL = lib.read_json("plan.json")
W = lib.work_dir()
ZM = (lib.read_json("zoom.json")["blocks"]
      if os.path.exists(os.path.join(W, "zoom.json")) else {})
OUT = os.path.join(W, "check")
TW, TH = 640, 360


def source():
    name = getattr(P, "OUT_NAME", "Ролик")
    for m in (f"{name}.mp4", f"{name} — {lib.NO_REPEATS_TAG}.mp4"):
        p = os.path.join(lib.out_dir(), m)
        if os.path.exists(p):
            return p
    return f"{W}/video_nosound.mp4"


def grab(src, t):
    raw = subprocess.run([lib.FF, "-nostdin", "-v", "error", "-ss", f"{max(0, t):.3f}",
                          "-i", src, "-frames:v", "1", "-vf", f"scale={TW}:{TH}",
                          "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    if len(raw) < TW * TH * 3:
        return Image.new("RGB", (TW, TH), (30, 30, 30))
    return Image.frombuffer("RGB", (TW, TH), raw[:TW * TH * 3], "raw", "RGB", 0, 1)


def sheets(src, items, name, cols=3, per=12):
    if not items:
        return []
    f = ImageFont.truetype(lib.font_path(True), 20)
    outs = []
    for k in range(0, len(items), per):
        chunk = items[k:k + per]
        rows = (len(chunk) + cols - 1) // cols
        im = Image.new("RGB", (TW * cols, (TH + 34) * rows), (12, 12, 12))
        d = ImageDraw.Draw(im)
        for j, (t, cap) in enumerate(chunk):
            x, y = (j % cols) * TW, (j // cols) * (TH + 34)
            im.paste(grab(src, t), (x, y + 34))
            d.text((x + 8, y + 6), f"{lib.ms(t)}  {cap}", font=f, fill=(255, 190, 70))
        p = os.path.join(OUT, f"{name}_{k // per + 1:02d}.jpg")
        im.save(p, quality=86)
        outs.append(p)
    return outs


def main():
    os.makedirs(OUT, exist_ok=True)
    src = source()
    if not os.path.exists(src):
        lib.die("мастера ещё нет — сначала build и final")
    blocks = PL["blocks"]
    morph = float(PL.get("morph", 0.7))
    ch = []
    for i, b in enumerate(blocks):
        if i and b["m"] != blocks[i - 1]["m"]:
            tag = f"{blocks[i - 1]['m']}→{b['m']}"
            ch += [(b["a"] - 0.3, f"{tag} до"), (b["a"] + morph / 2, f"{tag} перестроение"),
                   (b["a"] + morph + 0.3, f"{tag} после")]
    cams = []
    for i, b in enumerate(blocks):
        z = ZM.get(str(i))
        if not z:
            continue
        o = b["a"]
        if z.get("manual"):
            for c in PL.get("cams", []):
                if b["a"] <= c["t"] < b["b"]:
                    cams += [(c["t"], f"{b['m']} камера: старт"),
                             (c["t"] + c["dur"] + 0.2, f"{b['m']} камера z {c['z']:.2f}")]
        else:
            zk = z["z"]
            for (t0, v0), (t1, v1) in zip(zk, zk[1:]):
                if v1 > v0 + 0.01:
                    cams += [(o + t0, f"{b['m']} наезд: старт"),
                             (o + t1, f"{b['m']} наезд z {v1:.2f}")]
    for fr in PL.get("freezes", []):
        cams.append((fr["a"] + 0.2, "стоп-кадр"))
    cams.sort()
    dur = PL["out_dur"]
    ov = [(dur * (k + 0.5) / 12, blocks[next(i for i, b in enumerate(blocks)
                                             if b["a"] <= dur * (k + 0.5) / 12 < b["b"])]["m"])
          for k in range(12)]
    made = sheets(src, ch, "changes") + sheets(src, cams, "cams") + sheets(src, ov, "overview")
    if ov:
        os.replace(os.path.join(OUT, "overview_01.jpg"), os.path.join(OUT, "overview.jpg"))
        made[-1] = os.path.join(OUT, "overview.jpg")
    print(f"с {os.path.basename(src)}: смен плана {len(ch) // 3}, наездов и стоп-кадров "
          f"{len(cams)} кадров")
    for p in made:
        print(f"  {p}")
    print("посмотри их глазами: лицо справа, ничего не наехало, текст в рамках")


if __name__ == "__main__":
    main()
