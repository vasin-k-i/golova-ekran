#!/usr/bin/env python3
"""Компоновщик «Монтажёра»: FULL / PIP / SPLIT / BROLL / CARD + текстовые слои HyperFrames.

Всё во времени готового ролика: голова — work/head_cut.mp4 (нарезана по речи основным
пайплайном), звук — work/master_audio.wav (`montazher.py audio`). Каждый план рендерится
отдельным процессом: ffmpeg читает слои уже нужного размера, numpy накладывает (маски,
тени, текст), ffmpeg кодирует. Готовый план кэшируется по времени и типу — правка одного
плана пересобирает только его (`--force` — всё заново).

  mz_render.py probe   → out/…проба.mp4 (отрывки из PROBE в edl.py)
  mz_render.py all     → work/mz/body.mp4 (весь ролик без хука)
"""
import os
import subprocess
import sys
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import mzlib as L

W, H, FPS = L.W, L.H, L.FPS
HEAD = L.HEAD
TMP = os.path.join(L.WORK, "shots")
GFXDIR = os.path.join(L.WORK, "texts", "work", "gfx")
os.makedirs(TMP, exist_ok=True)
E = L.edl()
import mz_texts as G  # noqa: E402
TEXTS = [(g["id"], g["out_at"], g["dur"]) for g in G.GFX]
FCX, FCY = L.FCX, L.FCY
GRADE = L.GRADE
PIP, SPL = L.PIP, L.SPL


def rounded(w, h, r):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    return np.asarray(m, dtype=np.float32)[..., None] / 255.0


def shadow(w, h, r, blur=26, alpha=0.55, pad=60):
    s = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
    ImageDraw.Draw(s).rounded_rectangle((pad, pad + 12, pad + w, pad + h + 12), r, fill=int(255 * alpha))
    s = s.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(s, dtype=np.float32)[..., None] / 255.0, pad


def paste(base, img, x, y, mask):
    h, w = img.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    sub = img[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
    m = mask[y0 - y:y1 - y, x0 - x:x1 - x]
    roi = base[y0:y1, x0:x1].astype(np.float32)
    base[y0:y1, x0:x1] = (roi * (1 - m) + sub * m).astype(np.uint8)


def darken(base, x, y, sh, pad):
    h, w = sh.shape[:2]
    x, y = x - pad, y - pad
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    m = sh[y0 - y:y1 - y, x0 - x:x1 - x]
    base[y0:y1, x0:x1] = (base[y0:y1, x0:x1].astype(np.float32) * (1 - m)).astype(np.uint8)


def reader(cmd, w, h):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    size = w * h * 3

    def nxt():
        buf = p.stdout.read(size)
        if len(buf) < size:
            return None
        return np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    return p, nxt


def head_cmd(t0, n, vf):
    return ["ffmpeg", "-v", "error", "-ss", f"{t0:.4f}", "-i", HEAD, "-frames:v", str(n),
            "-vf", f"{vf},{GRADE}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]


def clip_cmd(src, ss, n, w, h, speed=1.0, pre=""):
    vf = (f"{pre + ',' if pre else ''}setpts=PTS/{speed},fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={w}:{h},tpad=stop_mode=clone:stop_duration=120")
    return ["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-i", src, "-an", "-frames:v", str(n),
            "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]


def full_vf(z, shift=0):
    """shift > 0 — лицо уезжает вправо на столько пикселей готового кадра (место под карточку слева)."""
    if z <= 1.0 and not shift:
        return f"scale={W}:{H}"
    z = max(z, 1.0 + 2 * abs(shift) / W + 0.001) if shift else z
    cw, ch = int(W / z) // 2 * 2, int(H / z) // 2 * 2
    x = min(max(0, FCX - cw // 2 - int(shift / z)), W - cw)
    y = min(max(0, int(FCY - ch * 0.42)), H - ch)
    return f"crop={cw}:{ch}:{x}:{y},scale={W}:{H}:flags=lanczos"


def matte(t0, n, vf, tag):
    """Маска человека на отрезке головы: hyperframes remove-background → ProRes 4444 с альфой."""
    d = os.path.join(L.WORK, "mattes")
    os.makedirs(d, exist_ok=True)
    mov = os.path.join(d, f"{tag}.mov")
    if os.path.exists(mov):
        return mov
    seg = os.path.join(d, f"{tag}_src.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.4f}", "-i", HEAD, "-frames:v", str(n),
                    "-vf", vf, "-an", "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", seg], check=True)
    env = dict(os.environ)
    if os.environ.get("MZ_NODE_BIN"):          # HyperFrames нужен node ≥ 22
        env["PATH"] = os.environ["MZ_NODE_BIN"] + ":" + env["PATH"]
    subprocess.run(["npx", "--yes", "hyperframes", "remove-background", seg, "-o", mov, "--device", "auto"],
                   check=True, env=env, stdin=subprocess.DEVNULL, capture_output=True)
    return mov


def alpha_reader(mov, n):
    cmd = ["ffmpeg", "-v", "error", "-i", mov, "-frames:v", str(n), "-vf", f"alphaextract,scale={W}:{H}",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

    def nxt():
        buf = p.stdout.read(W * H)
        if len(buf) < W * H:
            return None
        return np.frombuffer(buf, np.uint8).reshape(H, W, 1)
    return p, nxt


def text_layers(a, b):
    return [(tid, t0, d) for tid, t0, d in TEXTS if t0 < b and t0 + d > a]


def overlay_text(base, t, layers, cache):
    for tid, t0, d in layers:
        if not (t0 <= t < t0 + d):
            continue
        i = int((t - t0) * FPS) + 1
        f = os.path.join(GFXDIR, tid, f"frame_{i:06d}.png")
        if not os.path.exists(f):
            continue
        im = np.asarray(Image.open(f).convert("RGBA"))
        a = im[..., 3:4].astype(np.float32) / 255.0
        if a.max() == 0:
            continue
        ys, xs = np.nonzero(im[..., 3])
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        roi = base[y0:y1, x0:x1].astype(np.float32)
        base[y0:y1, x0:x1] = (roi * (1 - a[y0:y1, x0:x1]) + im[y0:y1, x0:x1, :3] * a[y0:y1, x0:x1]).astype(np.uint8)


def ease(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def render_shot(job):
    idx, a, b, kind, p = job
    n = int(round(b * FPS)) - int(round(a * FPS))
    t0 = int(round(a * FPS)) / FPS
    out = os.path.join(TMP, f"s{idx:03d}_{int(t0 * FPS)}_{n}_{kind}.mp4")
    if os.path.exists(out) and os.path.getsize(out) > 1000 and "--force" not in sys.argv:
        return out
    readers = []
    if kind == "FULL":
        readers.append(reader(head_cmd(t0, n, full_vf(p.get("z", 1.0))), W, H))
    elif kind == "PIP":
        cw, ch, cx, cy = PIP["crop"]
        readers.append(reader(clip_cmd(p["src"], p.get("ss", 0), n, W, H, p.get("speed", 1.0)), W, H))
        readers.append(reader(head_cmd(t0, n, f"crop={cw}:{ch}:{cx}:{cy},scale={PIP['w']}:{PIP['h']}:flags=lanczos"),
                              PIP["w"], PIP["h"]))
        pm, (psh, pad) = rounded(PIP["w"], PIP["h"], PIP["r"]), shadow(PIP["w"], PIP["h"], PIP["r"])
    elif kind == "SPLIT":
        cw, ch, cx, cy = SPL["crop"]
        readers.append(reader(clip_cmd(p["src"], p.get("ss", 0), n, SPL["pw"], SPL["ph"], p.get("speed", 1.0)),
                              SPL["pw"], SPL["ph"]))
        readers.append(reader(head_cmd(t0, n, f"crop={cw}:{ch}:{cx}:{cy}"), cw, ch))
        sm, (ssh, spad) = rounded(SPL["pw"], SPL["ph"], SPL["r"]), shadow(SPL["pw"], SPL["ph"], SPL["r"], 30, 0.7)
        hm = np.ones((ch, cw, 1), np.float32)
        g = np.linspace(0, 1, 90, dtype=np.float32)
        hm[:, :90, 0] = g[None, :]                     # мягкий край головы слева
        bg = np.zeros((H, W, 3), np.uint8)
        yy = np.linspace(0, 1, H, dtype=np.float32)[:, None]
        bg[..., 0] = (18 + 10 * yy).astype(np.uint8)
        bg[..., 1] = (19 + 10 * yy).astype(np.uint8)
        bg[..., 2] = (23 + 12 * yy).astype(np.uint8)
    elif kind == "BROLL":
        readers.append(reader(clip_cmd(p["src"], p.get("ss", 0), n, W, H, p.get("speed", 1.0)), W, H))
    elif kind == "CARD":
        cx, cy, cw, ch = p.get("card", (120, 60, 620, 900))
        hvf = full_vf(p.get("z", 1.0), p.get("shift", 0))
        readers.append(reader(head_cmd(t0, n, hvf), W, H))
        readers.append(reader(clip_cmd(p["src"], p.get("ss", 0), n, cw, ch, p.get("speed", 1.0), p.get("pre", "")), cw, ch))
        cm, (csh, cpad) = rounded(cw, ch, 40), shadow(cw, ch, 40, 34, 0.55)
        mt = None
        if p.get("behind"):
            mt = alpha_reader(matte(t0, n, hvf, f"m{idx:03d}_{int(t0 * FPS)}_{n}"), n)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                            "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", out],
                           stdin=subprocess.PIPE)
    layers = text_layers(t0, t0 + n / FPS)
    last = [None] * len(readers)
    for f in range(n):
        frames = []
        for k, (_, nxt) in enumerate(readers):
            fr = nxt()
            if fr is None:
                fr = last[k]
            last[k] = fr
            frames.append(fr)
        if kind in ("FULL", "BROLL"):
            base = frames[0].copy()
        elif kind == "PIP":
            base = frames[0].copy()
            darken(base, PIP["x"], PIP["y"], psh, pad)
            paste(base, frames[1], PIP["x"], PIP["y"], pm)
        elif kind == "CARD":
            head = frames[0]
            base = head.copy()
            k = ease(f / (0.45 * FPS))
            y = int(cy + (1 - k) * 80)
            darken(base, cx, y, csh, cpad)
            sub = base[:, :, :]
            paste(base, frames[1], cx, y, cm * min(1.0, k * 1.6))
            if mt is not None:
                a = mt[1]()
                if a is not None:
                    af = a.astype(np.float32) / 255.0
                    base[:] = (base * (1 - af) + head * af).astype(np.uint8)
        else:
            base = bg.copy()
            paste(base, frames[1], SPL["hx"], 0, hm)
            k = ease(f / (0.4 * FPS))
            x = int(SPL["px"] - (1 - k) * (SPL["pw"] + 120))
            darken(base, x, SPL["py"], ssh, spad)
            paste(base, frames[0], x, SPL["py"], sm)
        overlay_text(base, t0 + f / FPS, layers, None)
        enc.stdin.write(base.tobytes())
    enc.stdin.close()
    enc.wait()
    for pr, _ in readers:
        pr.kill()
    if kind == "CARD" and mt is not None:
        mt[0].kill()
    return out


def jobs(rng=None):
    sh = [(L.s2o(t, a), L.s2o(t, b), k, p) for t, a, b, k, p in E.SHOTS]
    res = []
    for i, (a, b, k, p) in enumerate(sh):
        if i + 1 < len(sh) and abs(sh[i + 1][0] - b) < 1.2:
            b = sh[i + 1][0]
        if b - a < 0.05:
            continue
        res.append([i, a, b, k, p])
    if rng:
        cut = []
        for j in res:
            for lo, hi in rng:
                a, b = max(j[1], lo), min(j[2], hi)
                if b - a > 0.05:
                    cut.append([j[0], a, b, j[3], j[4]])
        res = cut
    return res


def concat(files, dst_v):
    lst = dst_v + ".txt"
    with open(lst, "w") as fh:
        for f in files:
            fh.write(f"file '{f}'\n")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", dst_v], check=True)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    wav = L.AUDIO
    if not os.path.exists(wav):
        L.die(f"нет {wav} — сначала `montazher.py audio`")
    parts = getattr(E, "PROBE", [(0.0, 60.0)]) if mode == "probe" else [(0.0, 1e9)]
    if mode == "probe" and os.environ.get("MZ_PROBE"):       # MZ_PROBE="0,20;300,330"
        parts = [tuple(float(x) for x in r.split(",")) for r in os.environ["MZ_PROBE"].split(";")]
    workers = int(os.environ.get("MZ_WORKERS", "6"))
    outs = []
    for pi, rng in enumerate(parts):
        js = jobs([rng])
        print(f"отрывок {pi + 1}: {rng[0]:.1f}–{min(rng[1], js[-1][2]):.1f} с, планов {len(js)}", flush=True)
        with Pool(workers) as pool:
            files = pool.map(render_shot, js)
        v = os.path.join(L.WORK, f"part{pi}.mp4")
        concat(files, v)
        a0 = int(round(js[0][1] * FPS)) / FPS
        dur = sum(int(round(j[2] * FPS)) - int(round(j[1] * FPS)) for j in js) / FPS
        pa = os.path.join(L.WORK, f"part{pi}.wav")
        fade = "" if mode != "probe" else f",afade=t=in:d=0.3,afade=t=out:st={dur - 0.5:.3f}:d=0.5"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a0:.4f}", "-t", f"{dur:.4f}", "-i", wav,
                        "-af", f"apad,atrim=0:{dur:.4f}{fade}", "-c:a", "pcm_s16le", pa], check=True)
        pm = os.path.join(L.WORK, f"part{pi}_m.mp4")
        vf = [] if mode != "probe" else ["-vf", f"fade=t=in:d=0.3,fade=t=out:st={dur - 0.5:.3f}:d=0.5",
                                         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", v, "-i", pa, "-map", "0:v", "-map", "1:a",
                        *(vf or ["-c:v", "copy"]), "-c:a", "aac", "-b:a", "192k", pm], check=True)
        outs.append(pm)
    if mode == "probe":
        base, ext = os.path.splitext(L.OUT)
        dst = f"{base} — проба{ext}"
    else:
        dst = os.path.join(L.WORK, "body.mp4")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    concat(outs, dst + ".tmp.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", dst + ".tmp.mp4", "-c", "copy", "-movflags", "+faststart", dst], check=True)
    os.remove(dst + ".tmp.mp4")
    print("готово:", dst)


if __name__ == "__main__":
    main()
