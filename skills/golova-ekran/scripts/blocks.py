#!/usr/bin/env python3
"""Шаг 7 — сборка кадра. Каждый блок раскладки рендерится отдельно, потом concat.

Посегментная сборка не ради красоты: пересобрать один блок — секунды,
пересобрать девятиминутный ролик целиком — минуты. `montage.py build 5`
пересоберёт только пятый блок, остальные возьмёт готовыми.

Границы блоков считаем В КАДРАХ и жёстко задаём -frames:v. Иначе каждый блок
округляется вверх на кадр-другой, за полтора десятка блоков набегает полсекунды,
и к финалу губа уезжает от звука.
"""
import glob
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import lib

P = lib.load_project()
G = lib.read_json("geometry.json")
PL = lib.read_json("plan.json")
W = lib.work_dir()
M = os.path.join(lib.project_dir(), "masks")
INS = os.path.join(lib.project_dir(), "ins")
BLK = f"{W}/blocks"
FPS = PL["fps"]
HEAD, SCR = f"{W}/head_cut.mp4", f"{W}/scr_cut.mp4"
BG_EQ = "eq=brightness=-0.30:saturation=0.50"
DUR = lib.read_json("ins/durations.json") if \
    os.path.exists(os.path.join(W, "ins/durations.json")) else {}
if os.path.exists(f"{INS}/durations.json"):
    import json
    DUR = json.load(open(f"{INS}/durations.json", encoding="utf-8"))
ZOOM = (lib.read_json("zoom.json")["blocks"]
        if os.path.exists(os.path.join(W, "zoom.json")) else {})


def box(name):
    return tuple(G[name])


def head_chain(tag):
    x, y, w, h, _ = box(f"{tag}_HEAD")
    return f"[0:v]{cover(w, h)}[hd]"


def cover(w, h):
    return (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1")


def screen_chain(i, w, h):
    """Экран в свою коробку — с наездом за курсором, если zoom.py его нашёл.

    Наезд делает zoompan, а не crop: у crop ширина и высота считаются ОДИН раз
    при сборке фильтра, меняются только x и y — то есть панорама есть, а
    наезда нет. zoompan пересчитывает и рамку, и положение на каждом кадре
    и сам отдаёт готовый размер коробки.

    Время внутри выражений — `ot`, локальное время блока: каждый блок
    рендерится своим вызовом ffmpeg со своим нулём.

    tpad подстраховывает хвост: zoompan иногда не отдаёт последний кадр,
    а число кадров блока прибито намертво.
    """
    z = ZOOM.get(str(i))
    if not z:
        return f"scale={w}:{h},setsar=1"
    return ("tpad=stop_mode=clone:stop_duration=0.5,"
            f"zoompan=z='{lib.pw_expr(z['z'], 'ot')}'"
            f":x='clip(({lib.pw_expr(z['fx'], 'ot')})*iw-iw/zoom/2,0,iw-iw/zoom)'"
            f":y='clip(({lib.pw_expr(z['fy'], 'ot')})*ih-ih/zoom/2,0,ih-ih/zoom)'"
            f":d=1:fps={FPS}:s={w}x{h},setsar=1")


def panel_states(name):
    fs = sorted(glob.glob(f"{M}/panel_{name}_*.png"),
                key=lambda p: int(p.rsplit("_", 1)[1][:-4]))
    if not fs:
        lib.die(f"нет картинок панели «{name}» — проверь PANELS в project.py")
    return fs


def build_block(i_blk):
    i, blk = i_blk
    mode = blk["m"]
    fa, fb = int(round(blk["a"] * FPS)), int(round(blk["b"] * FPS))
    nf = fb - fa
    a, ln = fa / FPS, round(nf / FPS, 3)
    out = f"{BLK}/{i:03d}.mp4"

    ins = [x for x in PL["inserts"]
           if x["a"] >= a - 0.001 and x["b"] <= a + ln + 0.001]
    for x in ins:
        if x["lay"] != mode:
            lib.die(f"вставка {x['n']} ждёт раскладку {x['lay']}, а блок {mode}")

    cmd = [lib.FF, "-y", "-v", "error",
           "-ss", f"{a:.3f}", "-t", f"{ln:.3f}", "-i", HEAD,
           "-ss", f"{a:.3f}", "-t", f"{ln:.3f}", "-i", SCR]
    statics = {"A": ["shadow_a.png", "mask_scr_a.png", "mask_head_a.png"],
               "B": ["shadow_b.png", "mask_scr_b.png", "mask_head_b.png"],
               "D": ["shadow_a.png", "mask_head_a.png"],
               "C": []}[mode]
    for s in statics:
        cmd += ["-loop", "1", "-t", f"{ln:.3f}", "-i", f"{M}/{s}"]
    idx = 2 + len(statics)

    bgsrc = "1:v" if mode != "C" else "0:v"
    g = [f"[{bgsrc}]split=2[s1][s2]",
         f"[s1]scale=320:-2,gblur=sigma=10,{cover(1920, 1080)},{BG_EQ}[bg]"]
    if mode in ("A", "B"):
        sx, sy, sw, sh, _ = box(f"{mode}_SCR")
        hx, hy, hw, hh, _ = box(f"{mode}_HEAD")
        low = mode.lower()
        g += ["[bg][2:v]overlay=0:0[bg2]",
              f"[s2]{screen_chain(i, sw, sh)}[sc]",
              "[sc][3:v]alphamerge[sca]",
              f"[bg2][sca]overlay={sx}:{sy}[v0]",
              f"[0:v]{cover(hw, hh)}[hd]",
              "[hd][4:v]alphamerge[hda]",
              f"[v0][hda]overlay={hx}:{hy}[vb]"]
        cur = "vb"
    elif mode == "C":
        hw = 1080 * G["A_HEAD"][2] // G["A_HEAD"][3] if not G["portrait"] else 608
        hw = (hw // 2) * 2
        g += ["[s2]nullsink", f"[0:v]{cover(hw, 1080)}[hd]",
              f"[bg][hd]overlay={(1920 - hw) // 2}:0[vb]"]
        cur = "vb"
    else:
        sx, sy, sw, sh, _ = box("A_SCR")
        hx, hy, hw, hh, _ = box("A_HEAD")
        g += ["[s2]nullsink", "[bg][2:v]overlay=0:0[bg2]"]
        cur = "bg2"
        states = panel_states(blk["panel"])
        step = ln / len(states)
        for k, png in enumerate(states):
            t0 = k * step
            t1 = ln if k == len(states) - 1 else (k + 1) * step
            cmd += ["-loop", "1", "-t", f"{ln:.3f}", "-i", png]
            g.append(f"[{cur}][{idx}:v]overlay={sx}:{sy}:"
                     f"enable='between(t,{t0:.3f},{t1:.3f})':eof_action=pass[p{idx}]")
            cur = f"p{idx}"
            idx += 1
        g += [f"[0:v]{cover(hw, hh)}[hd]", "[hd][3:v]alphamerge[hda]",
              f"[{cur}][hda]overlay={hx}:{hy}[vd]"]
        cur = "vd"

    for x in ins:
        rel = round(x["a"] - a, 3)
        cmd += ["-loop", "1", "-t", f"{ln:.3f}", "-i", f"{M}/deco_{x['n']}.png"]
        cmd += ["-i", f"{INS}/{x['n']}.mp4"]
        dec, clip = idx, idx + 1
        idx += 2
        pos = G[f"{mode}_POS"]
        inn = G[f"{mode}_INNER"]
        en = f"between(t,{rel:.3f},{rel + DUR[x['n']]:.3f})"
        g.append(f"[{clip}:v]tpad=start_duration={rel:.3f}:start_mode=add:color=black,"
                 f"setpts=PTS-STARTPTS[cl{x['n']}]")
        g.append(f"[{cur}][{dec}:v]overlay={pos[0]}:{pos[1]}:enable='{en}':"
                 f"eof_action=pass[d{x['n']}]")
        g.append(f"[d{x['n']}][cl{x['n']}]overlay={inn[0]}:{inn[1]}:enable='{en}':"
                 f"eof_action=pass[o{x['n']}]")
        cur = f"o{x['n']}"

    bw = PL.get("bw")
    if bw and bw["b"] > a + 0.001 and bw["a"] < a + ln - 0.001:
        r0, r1 = max(bw["a"], a) - a, min(bw["b"], a + ln) - a
        sx, sy, sw, sh, _ = box("A_SCR" if mode != "B" else "B_SCR")
        cmd += ["-loop", "1", "-t", f"{ln:.3f}", "-i", f"{M}/bw_plaque.png"]
        g.append(f"[{cur}]hue=s=0:enable='between(t,{r0:.3f},{r1:.3f})'[gray]")
        g.append(f"[gray][{idx}:v]overlay={sx}:{sy + sh - 176}:"
                 f"enable='between(t,{r0:.3f},{r1:.3f})':eof_action=pass[bwo]")
        cur = "bwo"
        idx += 1

    g.append(f"[{cur}]format=yuv420p[vout]")
    cmd += ["-filter_complex", ";".join(g), "-map", "[vout]", "-frames:v", str(nf),
            "-fps_mode", "cfr", "-r", str(FPS), "-c:v", "libx264",
            "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", out]
    lib.run(cmd)
    return i, mode, blk.get("panel"), nf, lib.nframes(out), [x["n"] for x in ins]


def main():
    os.makedirs(BLK, exist_ok=True)
    blocks = PL["blocks"]
    placed = {x["n"] for blk in blocks for x in PL["inserts"]
              if x["a"] >= blk["a"] - 0.001 and x["b"] <= blk["b"] + 0.001}
    missing = [x["n"] for x in PL["inserts"] if x["n"] not in placed]
    if missing:
        lib.die(f"вставки не попали ни в один блок: {missing} — "
                "сдвинь at или растяни блок в MODES")

    only = {int(x) for x in sys.argv[1:] if x.isdigit()}
    todo = [(i, b) for i, b in enumerate(blocks) if not only or i in only]
    with ThreadPoolExecutor(max_workers=3) as ex:
        res = sorted(ex.map(build_block, todo))
    if only:
        res = [next((r for r in res if r[0] == i),
                    (i, blocks[i]["m"], blocks[i].get("panel"), 0,
                     lib.nframes(f"{BLK}/{i:03d}.mp4"), []))
               for i in range(len(blocks))]
    tw = tg = 0
    for i, mode, panel, want, got, keys in res:
        tw += want
        tg += got
        tag = mode + ("/" + panel if panel else "")
        flag = "" if want in (got, 0) else "  ← кадры не сошлись"
        print(f"  блок {i:02d} {tag:11s} {got:6d} кадр  "
              f"вставки: {','.join(keys) or '—'}{flag}")
    print(f"  всего кадров: {tg}")

    lst = f"{BLK}/list.txt"
    with open(lst, "w") as fh:
        for i, *_ in res:
            fh.write(f"file '{i:03d}.mp4'\n")
    lib.run([lib.FF, "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", lst, "-c", "copy", f"{W}/video_nosound.mp4"])
    print(f"\nсклеено: {lib.duration(f'{W}/video_nosound.mp4'):.2f} с "
          f"(план {PL['out_dur']:.2f} с)")
    print("дальше: montage.py final")


if __name__ == "__main__":
    main()
