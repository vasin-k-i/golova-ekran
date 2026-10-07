#!/usr/bin/env python3
"""Шаг 7 — сборка кадра. Каждый блок раскладки рендерится отдельно, потом concat.

Посегментная сборка не ради красоты: пересобрать один блок — секунды,
пересобрать девятиминутный ролик целиком — минуты. `montage.py build 5`
пересоберёт только пятый блок, остальные возьмёт готовыми.

Границы блоков считаем В КАДРАХ и жёстко задаём -frames:v. Иначе каждый блок
округляется вверх на кадр-другой, за полтора десятка блоков набегает полсекунды,
и к финалу губа уезжает от звука.

Блоки студии (H, HC, S, T) рисует композитор compose.py. Он считает кадр на
питоне, поэтому длинный блок режется на куски по ~10 с, и куски идут в
несколько процессов сразу (GEK_JOBS, по умолчанию до 6). Кадры читаются
подряд через трубу ffmpeg — один поиск на кусок, а не на каждый кадр.
"""
import glob
import os
import subprocess
import sys
import time
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
    # panel_<имя>_<k>.png — для D; panel_<имя>_h_<k>.png (панель в H) сюда не берём
    import re
    pat = re.compile(rf"panel_{re.escape(name)}_(\d+)\.png$")
    fs = sorted((p for p in glob.glob(f"{M}/panel_{name}_*.png")
                 if pat.search(os.path.basename(p))),
                key=lambda p: int(pat.search(os.path.basename(p)).group(1)))
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
            "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            # те же метки цвета, что у блоков студии: склейка без перекодирования
            # берёт параметры потока из первого файла
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-color_range", "tv", out]
    lib.run(cmd)
    return i, mode, blk.get("panel"), nf, lib.nframes(out), [x["n"] for x in ins]


PART = 300          # кадров в куске студии: ~10 с при 30 fps


def build_studio(todo):
    """Блоки студии: режем на куски, гоним в несколько процессов, склеиваем.

    Каждый кусок — отдельный процесс compose.py со своим чтением кадров через
    ffmpeg. Процессы, а не потоки: кадр собирается на питоне, и в одном
    процессе потоки упираются в GIL.
    """
    for i, b in todo:
        for x in PL["inserts"]:
            if b["a"] - 0.001 <= x["a"] < b["b"] and (b["m"] != "H" or x["lay"] != "H"):
                lib.die(f"вставка {x['n']} (lay={x['lay']}) попала в блок {b['m']}: "
                        "в студии вставки ставятся только в H с lay=\"H\" — "
                        "сдвинь at или раскладку")
    jobs = int(os.environ.get("GEK_JOBS", "0")) or max(1, min(6, (os.cpu_count() or 4) // 2))
    parts = []
    for i, b in todo:
        fa, fb = int(round(b["a"] * FPS)), int(round(b["b"] * FPS))
        n = max(1, round((fb - fa) / PART))
        for k in range(n):
            f0 = fa + (fb - fa) * k // n
            f1 = fa + (fb - fa) * (k + 1) // n
            parts.append((i, k, f0, f1, f"{BLK}/{i:03d}_p{k:02d}.mp4"))
    py = sys.executable
    here = os.path.dirname(os.path.abspath(__file__))
    t0 = time.time()
    run, done, stats = [], 0, []
    queue = sorted(parts, key=lambda p: -(p[3] - p[2]))
    print(f"  студия: {len(todo)} блок(ов), {sum(p[3] - p[2] for p in parts)} кадров, "
          f"{len(parts)} кусков в {jobs} процесса(ов)")
    while queue or run:
        while queue and len(run) < jobs:
            i, k, f0, f1, out = queue.pop(0)
            pr = subprocess.Popen([py, os.path.join(here, "compose.py"), "--part",
                                   str(i), str(f0), str(f1), out],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  stdin=subprocess.DEVNULL, text=True)
            run.append((pr, (i, k, f0, f1, out)))
        time.sleep(0.2)
        for pr, meta in list(run):
            if pr.poll() is None:
                continue
            run.remove((pr, meta))
            so, se = pr.communicate()
            if pr.returncode:
                for p2, _ in run:
                    p2.kill()
                sys.stderr.write(se[-3000:])
                lib.die(f"кусок {meta[1]} блока {meta[0]} не собрался")
            n, dt = so.strip().split()[-2:]
            stats.append((int(n), float(dt)))
            done += 1
    wall = time.time() - t0
    frames = sum(n for n, _ in stats)
    per = frames / max(1e-6, sum(dt for _, dt in stats))
    print(f"  студия собрана за {wall:.0f} с: {frames / max(wall, 1e-6):.1f} кадр/с всего, "
          f"{per:.1f} кадр/с на процесс")

    res = []
    for i, b in todo:
        mine = sorted(p for p in parts if p[0] == i)
        lst = f"{BLK}/{i:03d}_parts.txt"
        with open(lst, "w") as fh:
            for p in mine:
                fh.write(f"file '{os.path.basename(p[4])}'\n")
        out = f"{BLK}/{i:03d}.mp4"
        lib.run([lib.FF, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                 "-i", lst, "-c", "copy", out])
        for p in mine:
            os.remove(p[4])
        os.remove(lst)
        fa, fb = int(round(b["a"] * FPS)), int(round(b["b"] * FPS))
        res.append((i, b["m"], b.get("panel"), fb - fa, lib.nframes(out), []))
    return res


def main():
    lib.repeats_guard(P, sys.argv[1:], "build")
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
    classic = [x for x in todo if x[1]["m"] not in lib.STUDIO]
    studio = [x for x in todo if x[1]["m"] in lib.STUDIO]
    with ThreadPoolExecutor(max_workers=3) as ex:
        res = sorted(ex.map(build_block, classic))
    if studio:
        res = sorted(res + build_studio(studio))
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
