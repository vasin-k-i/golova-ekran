#!/usr/bin/env python3
"""Шаг 7в (необязательный) — маска человека для «текста за головой».

Крупное слово или цифра встаёт МЕЖДУ фоном и человеком: кусок графики
со слоем layer="bg" рисуется поверх кадра, а человек по маске — поверх него.
Маску считает `hyperframes remove-background` (u2net) на процессоре — это
небыстро (~4–5 кадров/с), поэтому только на окнах кусков bg, а не на всём ролике.

Таких мест — одно на мысль, не чаще раза в 15–20 с: на главной цифре или слове.

⚠️ Грабля, на которой теряли время: `npx` и `ffmpeg` внутри цикла
`while read … done` съедают stdin цикла, и обрабатывается только первое окно.
Здесь цикл на питоне и stdin закрыт у каждого вызова; если пишешь такое
на bash — `< /dev/null` у npx и `-nostdin` у ffmpeg.
"""
import os
import shutil
import time

import lib

P = lib.load_project()
PL = lib.read_json("plan.json")
W = lib.work_dir()
FPS = PL["fps"]
HEAD = f"{W}/head_cut.mp4"
DEVICE = os.environ.get("GEK_MATTE_DEVICE", "cpu")


def frames_of(gid):
    d = f"{W}/gfx/{gid}"
    return len([f for f in os.listdir(d) if f.endswith(".png")]) if os.path.isdir(d) else 0


def one(g):
    n = frames_of(g["id"])
    if not n:
        return g["id"], 0, "нет кадров графики — сначала montage.py gfx"
    out = f"{W}/matte/{g['id']}"
    # ключ — что режем и где окно, а не время файла: cut пересклеивает head_cut
    # каждый раз, и по mtime маска считалась бы заново на каждом прогоне
    import hashlib
    key = hashlib.sha1(repr((g["a"], n, PL["keeps"])).encode()).hexdigest()
    if os.path.exists(f"{out}/.done") and open(f"{out}/.done").read() == key:
        return g["id"], n, "готова"
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    f0 = int(round(g["a"] * FPS))
    seg, mov = f"{out}/_seg.mp4", f"{out}/_seg.mov"
    lib.run([lib.FF, "-nostdin", "-y", "-v", "error", "-ss", f"{max(0, f0 - 0.5) / FPS:.4f}",
             "-i", HEAD, "-frames:v", str(n), "-an", "-c:v", "libx264", "-crf", "12",
             "-pix_fmt", "yuv420p", seg])
    t0 = time.time()
    r = lib.hf_run(["remove-background", seg, "-o", mov, "--device", DEVICE])
    if r.returncode or not os.path.exists(mov):
        return g["id"], 0, f"remove-background упал: {(r.stderr or r.stdout)[-500:]}"
    lib.run([lib.FF, "-nostdin", "-y", "-v", "error", "-i", mov, "-vf", "alphaextract",
             f"{out}/%05d.png"])
    os.remove(seg)
    os.remove(mov)
    got = len([f for f in os.listdir(out) if f.endswith(".png")])
    with open(f"{out}/.done", "w") as fh:
        fh.write(key)
    return g["id"], got, f"{got / max(1e-6, time.time() - t0):.1f} кадр/с"


def main():
    bgs = [g for g in PL.get("gfx", []) if g.get("layer") == "bg"]
    if not bgs:
        print("кусков графики за головой (layer=\"bg\") нет — маска не нужна")
        return
    if not lib.node_bin():
        print("✗ маску считает HyperFrames, ему нужен node ≥ 22 — не нашёл.")
        print("  Куски bg лягут поверх головы, без маски. Поставь node@22 и повтори.")
        return
    print(f"· маска человека на {len(bgs)} окнах, считает {DEVICE} — это небыстро")
    for g in bgs:
        gid, n, msg = one(g)
        print(f"  {'✓' if n else '✗'} {gid:16s} {lib.ms(g['a'])}  {n:4d} кадр  {msg}")
    print("дальше: montage.py build")


if __name__ == "__main__":
    main()
