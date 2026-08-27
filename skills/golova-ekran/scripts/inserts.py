#!/usr/bin/env python3
"""Шаг 6б — клипы вставок и плашки к ним.

Вставка — это окно в экранной зоне с подписью сверху: показать кусок другого
своего видео, не разбирая основной кадр. Звук источника не берём НИКОГДА:
во вставках только картинка, говорит по-прежнему автор.

⚠️ -t ставим ДО -i: если после, ускорение через setpts растягивает выборку
и в кадр уезжает лишнее.
⚠️ boxblur требует радиус меньше половины меньшей стороны области — на узких
полосках (таблички с именами высотой 32 px) с большим радиусом он падает.
"""
import os
from concurrent.futures import ThreadPoolExecutor

import lib
import design

P = lib.load_project()
G = lib.read_json("geometry.json")
INS = os.path.join(lib.project_dir(), "ins")
M = os.path.join(lib.project_dir(), "masks")
FPS = P.FPS


def build(it):
    lay = it["lay"]
    w, h = G[f"{lay}_INNER"][2], G[f"{lay}_INNER"][3]
    out = f"{INS}/{it['n']}.mp4"
    tail = [f"scale={w}:{h}:force_original_aspect_ratio=increase",
            f"crop={w}:{h}", "setsar=1"]
    if it.get("speed", 1) != 1:
        tail.append(f"setpts=PTS/{it['speed']}")
    tail.append(f"fps={FPS}")

    regions = it.get("blur") or []
    crop = it.get("crop")
    if regions:
        g = [f"[0:v]{crop}[c]" if crop else "[0:v]null[c]",
             f"[c]split={len(regions) + 1}[b0]" +
             "".join(f"[r{i}]" for i in range(len(regions)))]
        cur = "b0"
        for i, (x, y, rw, rh) in enumerate(regions):
            r = max(3, min(24, min(rw, rh) // 5))
            g.append(f"[r{i}]crop={rw}:{rh}:{x}:{y},"
                     f"boxblur=luma_radius={r}:luma_power=2:"
                     f"chroma_radius={r}:chroma_power=2[bb{i}]")
            g.append(f"[{cur}][bb{i}]overlay={x}:{y}[o{i}]")
            cur = f"o{i}"
        g.append(f"[{cur}]{','.join(tail)}[v]")
        args = ["-filter_complex", ";".join(g), "-map", "[v]"]
    else:
        args = ["-vf", ",".join(([crop] if crop else []) + tail)]

    src_len = it["dur"] * it.get("speed", 1)
    lib.run([lib.FF, "-y", "-v", "error", "-ss", f"{it.get('ss', 0)}",
             "-t", f"{src_len}", "-i", it["src"], "-an", *args,
             "-fps_mode", "cfr", "-r", str(FPS), "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", out])

    design.deco(it.get("label", ""), tuple(G[f"{lay}_CANVAS"]),
                tuple(G[f"{lay}_CARD"][2:4]), G[f"{lay}_CARD"][4],
                f"{M}/deco_{it['n']}.png")
    return it["n"], round(lib.duration(out), 3)


def main():
    items = getattr(P, "INSERTS", [])
    if not items:
        print("вставок нет — пропускаю")
        lib.write_json("ins_durations.json", {})
        os.makedirs(INS, exist_ok=True)
        with open(f"{INS}/durations.json", "w") as fh:
            fh.write("{}")
        return
    os.makedirs(INS, exist_ok=True)
    for it in items:
        if not os.path.exists(it["src"]):
            lib.die(f"вставка {it['n']}: нет файла {it['src']}")
    with ThreadPoolExecutor(max_workers=3) as ex:
        res = dict(ex.map(build, items))
    import json
    with open(f"{INS}/durations.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    for it in items:
        print(f"  {it['n']}  {res[it['n']]:5.2f} с   {it.get('label', '')}")


if __name__ == "__main__":
    main()
