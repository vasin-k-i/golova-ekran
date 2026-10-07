#!/usr/bin/env python3
"""Шаг 6 — экран к общему холсту и резка обеих дорожек кадр в кадр.

Сдвиг экрана вшивается ЗДЕСЬ, при нормализации: нулю нормализованного экрана
соответствует нуль головы. Иначе поправку пришлось бы возить через все
дальнейшие шаги, отдельную на каждый дубль.

Режем чанками по 20 сегментов: одно выражение select на полторы сотни
диапазонов ffmpeg не берёт — парсер падает на «Cannot allocate memory».
"""
import os
from concurrent.futures import ThreadPoolExecutor

import lib

P = lib.load_project()
G = lib.read_json("geometry.json")
PL = lib.read_json("plan.json")
W = lib.work_dir()
FPS = P.FPS
CHUNK = 20
FADE_IN, FADE_OUT = 0.03, 0.08
SEEK_PAD = 12.0
BEZEL = "0x101115"


def fresh(path, key):
    """Готовый промежуточный файл годится, только если собран с теми же вводными.

    Раньше хватало «файл есть»: поправил DROP или кроп, перезапустил cut —
    и молча получил старую резку. Теперь рядом лежит ключ вводных.
    """
    k = path + ".key"
    return (os.path.exists(path) and os.path.exists(k)
            and open(k).read() == key)


def stamp(path, key):
    with open(path + ".key", "w") as fh:
        fh.write(key)


def normalize_screen(t):
    """Кроп рабочего окна → холст SCR_W×SCR_H → нуль совпадает с нулём головы.

    Если записи экрана у дубля нет, всё равно делаем дорожку той же длины —
    размытую копию головы. Так все дубли остаются одной длины и склейка не
    разъезжается; такие дубли ставь в раскладку C или D.
    """
    out = f"{W}/scr_{t['id']}.mp4"
    key = repr((t.get("screen"), t.get("crop"), t.get("offset"), t["head"],
                G["SCR_W"], G["SCR_H"], FPS))
    if fresh(out, key):
        return out
    _normalize(t, out)
    stamp(out, key)
    return out


def _normalize(t, out):
    if not t.get("screen"):
        lib.run([lib.FF, "-y", "-v", "error", "-i", t["head"], "-an", "-vf",
                 f"scale=320:-2,gblur=sigma=12,"
                 f"scale={G['SCR_W']}:{G['SCR_H']}:force_original_aspect_ratio=increase,"
                 f"crop={G['SCR_W']}:{G['SCR_H']},eq=brightness=-0.25:saturation=0.5,"
                 f"fps={FPS},setsar=1",
                 "-fps_mode", "cfr", "-r", str(FPS), "-c:v", "libx264",
                 "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", out])
        return out
    vf = []
    if t.get("crop"):
        cw, ch, cx, cy = t["crop"]
        vf.append(f"crop={cw}:{ch}:{cx}:{cy}")
    vf += [f"scale={G['SCR_W']}:{G['SCR_H']}:force_original_aspect_ratio=decrease",
           f"pad={G['SCR_W']}:{G['SCR_H']}:(ow-iw)/2:(oh-ih)/2:color={BEZEL}",
           f"fps={FPS}", "setsar=1"]
    cmd = [lib.FF, "-y", "-v", "error"]
    off = t.get("offset", 0.0)
    if off >= 0:
        cmd += ["-ss", f"{off:.3f}"]
    else:
        vf.append(f"tpad=start_duration={-off:.3f}:start_mode=clone")
    cmd += ["-i", t["screen"], "-an", "-vf", ",".join(vf),
            "-fps_mode", "cfr", "-r", str(FPS), "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", out]
    lib.run(cmd)
    return out


def spans(keeps):
    out = []
    for k in keeps:
        n1, n2 = int(round(k["a"] * FPS)), int(round(k["b"] * FPS)) - 1
        if n2 >= n1:
            out.append((n1, n2))
    return out


def cut_video(src, dst, sp, tag, tail=0.0):
    d = f"{W}/{tag}"
    os.makedirs(d, exist_ok=True)
    groups = [sp[i:i + CHUNK] for i in range(0, len(sp), CHUNK)]

    def one(ig):
        i, g = ig
        terms = [f"between(t,{n1 / FPS - 0.004:.4f},{n2 / FPS + 0.004:.4f})"
                 for n1, n2 in g]
        start = max(0.0, g[0][0] / FPS - SEEK_PAD)
        pad = f",tpad=stop_mode=clone:stop_duration={tail}" if tail else ""
        out = f"{d}/{i:03d}.mp4"
        lib.run([lib.FF, "-y", "-v", "error", "-copyts", "-ss", f"{start:.3f}",
                 "-i", src, "-an", "-vf",
                 f"fps={FPS}{pad},select='{'+'.join(terms)}',setpts=N/{FPS}/TB",
                 "-fps_mode", "cfr", "-r", str(FPS), "-c:v", "libx264",
                 "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", out])
        return out, sum(b - a + 1 for a, b in g), lib.nframes(out)

    with ThreadPoolExecutor(max_workers=5) as ex:
        res = list(ex.map(one, enumerate(groups)))
    bad = [(i, w, g) for i, (_, w, g) in enumerate(res) if w != g]
    if bad:
        print(f"   ! {tag}: кадры не сошлись в группах {bad[:5]}")
    lst = f"{d}/list.txt"
    with open(lst, "w") as fh:
        for f, _, _ in res:
            fh.write(f"file '{os.path.basename(f)}'\n")
    lib.run([lib.FF, "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", lst, "-c", "copy", dst])
    return sum(g for _, _, g in res)


def cut_audio(src, sp, tag):
    """Звук режем по тем же кадровым границам и прибиваем длину.

    ⚠️ -ss/-t ставим ДО -i: если после, фильтр видит исходные таймкоды и
    afade=out срабатывает раньше начала сегмента — на выходе тишина.
    ⚠️ apad+atrim обязательны: -t перед -i округляется до кадра AAC-декодера
    (~21 мс), каждый сегмент выходит чуть длиннее, и на сотне склеек звук
    уезжает от картинки на десятки миллисекунд.
    """
    d = f"{W}/{tag}"
    os.makedirs(d, exist_ok=True)

    def one(i_nn):
        i, (n1, n2) = i_nn
        a, ln = n1 / FPS, (n2 - n1 + 1) / FPS
        out = f"{d}/{i:04d}.wav"
        af = (f"afade=t=in:st=0:d={FADE_IN},"
              f"afade=t=out:st={max(0, ln - FADE_OUT):.4f}:d={FADE_OUT},"
              f"apad,atrim=0:{ln:.6f}")
        lib.run([lib.FF, "-y", "-v", "error", "-ss", f"{a:.4f}", "-t", f"{ln:.4f}",
                 "-i", src, "-vn", "-af", af, "-ac", "1", "-ar", "48000",
                 "-c:a", "pcm_s16le", out])
        return out

    with ThreadPoolExecutor(max_workers=8) as ex:
        files = list(ex.map(one, enumerate(sp)))
    lst = f"{d}/list.txt"
    with open(lst, "w") as fh:
        for f in files:
            fh.write(f"file '{os.path.basename(f)}'\n")
    out = f"{W}/a_{tag}.wav"
    lib.run([lib.FF, "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", lst, "-c", "copy", out])
    return out


def main():
    print("· приводим экран к общему холсту…")
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(normalize_screen, P.TAKES))

    heads, scrs, auds = [], [], []
    for t in P.TAKES:
        tid = t["id"]
        sp = spans([k for k in PL["keeps"] if k["take"] == tid])
        if not sp:
            continue
        want = sum(b - a + 1 for a, b in sp)
        key = repr((sp, t["head"], FPS))
        h = f"{W}/head_{tid}.mp4"
        if fresh(h, key):
            gh = lib.nframes(h)
        else:
            gh = cut_video(t["head"], h, sp, f"hs_{tid}")
            stamp(h, key)
        heads.append(h)
        s = f"{W}/scrc_{tid}.mp4"
        skey = key + open(f"{W}/scr_{tid}.mp4.key").read()
        if fresh(s, skey):
            gs = lib.nframes(s)
        else:
            gs = cut_video(f"{W}/scr_{tid}.mp4", s, sp, f"ss_{tid}", tail=25)
            stamp(s, skey)
        scrs.append(s)
        auds.append(cut_audio(t["head"], sp, f"as_{tid}"))
        print(f"  дубль {tid}: {len(sp):3d} сегм · голова {gh} кадр · "
              f"экран {gs} кадр (ждали {want})")

    outs = [("head_cut.mp4", heads), ("audio_cut.wav", auds),
            ("scr_cut.mp4", scrs)]
    for name, files in outs:
        lst = f"{W}/cc_{name}.txt"
        with open(lst, "w") as fh:
            for f in files:
                fh.write(f"file '{os.path.basename(f)}'\n")
        lib.run([lib.FF, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                 "-i", lst, "-c", "copy", f"{W}/{name}"])
        print(f"  {name:16s} {lib.duration(f'{W}/{name}'):8.3f} с")
    print(f"  план: {PL['out_dur']:.3f} с")
    print("дальше: montage.py build")


if __name__ == "__main__":
    main()
