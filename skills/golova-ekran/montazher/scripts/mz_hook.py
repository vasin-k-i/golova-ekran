#!/usr/bin/env python3
"""Хук, отбивка и финальная склейка «Монтажёра».

Хук — 6–10 ударных фраз из исходников встык: звук без пауз (GAP 0,03 с), картинка уходящей
фразы держится ещё CIRC секунд, поверх неё из лица растёт круг со следующей фразой (ускорение,
центр уезжает к середине кадра, светлый ободок). Удар-отъезд 1,3 → 1,0 на первом кадре, внутри
фразы — медленный наезд. Под хуком музыка с ducking под голос, в конце обрыв и 0,2 с тишины.
Отбивка — полноэкранная заливка шторкой с титулом, свист + низкий удар. Затем основной ролик.

  mz_hook.py plan     → work/mz/hook/plan.json (тайминги для слоёв текста)
  mz_hook.py render   → work/mz/hook/hook.mp4
  mz_hook.py final    → отбивка + склейка hook + sep + body → OUT из montazher.py

Границы фраз (с, до) — секунды исходника, КАЖДУЮ проверь расшифровкой клипа: пословные
таймкоды whisper сдвинуты на 0,1–0,3 с, и фраза начинается с хвоста предыдущего слова.
"""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

import mzlib as L

W, H, FPS = L.W, L.H, L.FPS
HOOK = getattr(L.C, "HOOK", None) or {}
CIRC = HOOK.get("circ", 0.55)
GAP = HOOK.get("gap", 0.03)
SEP = HOOK.get("sep", 1.4)
T = os.path.join(L.WORK, "hook")
os.makedirs(T, exist_ok=True)
GFX = os.path.join(T, "work", "gfx")
SRC = dict(L.take_sources(), **HOOK.get("sources", {}))
FCX, FCY = L.FCX, L.FCY
GRADE = HOOK.get("grade", "eq=contrast=1.06:saturation=1.08:brightness=0.005")


def phrases():
    if not HOOK.get("phrases"):
        L.die("в montazher.py нет HOOK['phrases'] — см. шаблон")
    out = []
    for p in HOOK["phrases"]:
        tk, a, b, lead, key = p[:5]
        t_key = p[5] if len(p) > 5 else 0.1
        size = p[6] if len(p) > 6 else 150
        out.append((tk, a, b, lead, key, t_key, size))
    return out


def timeline():
    t, blocks = 0.0, []
    for i, (tk, a, b, lead, key, t_key, size) in enumerate(phrases()):
        blocks.append(dict(i=i, take=tk, a=a, b=b, start=round(t, 3), lead=lead, key=key, t_key=t_key, size=size))
        t += (b - a) + GAP
    end = round(t + 0.25, 3)                      # хвост последней фразы под обрыв музыки
    for i, bl in enumerate(blocks):
        bl["vis_end"] = round(blocks[i + 1]["start"] + CIRC if i + 1 < len(blocks) else end, 3)
    return blocks, end


def plan():
    blocks, end = timeline()
    ph = [dict(id=f"h{bl['i'] + 1}", dur=round(bl["vis_end"] - bl["start"], 3), lead=bl["lead"], key=bl["key"].upper(),
               t_lead=0.12 if bl["i"] else 0.05, t_key=round(max(0.18 if bl["i"] else 0.1, bl["t_key"]), 3), size=bl["size"])
          for bl in blocks]
    with open(os.path.join(T, "plan.json"), "w", encoding="utf-8") as fh:
        json.dump(dict(phrases=ph, hook_end=end, sep=SEP), fh, ensure_ascii=False, indent=1)
    for bl in blocks:
        print(f"  h{bl['i'] + 1}  {bl['take']} {bl['a']:.2f}–{bl['b']:.2f}  «{bl['lead']}» {bl['key'].upper()}")
    print(f"хук {end} с, фраз {len(blocks)}, отбивка {SEP} с")


def reader(cmd, w=W, h=H):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    size = w * h * 3

    def nxt():
        buf = p.stdout.read(size)
        return None if len(buf) < size else np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    return p, nxt


def zbase(i):
    z = HOOK.get("zoom")
    return z[i % len(z)] if z else (1.0, 1.22, 1.0, 1.25, 1.05)[i % 5]


def head_block(tk, a, dur, z0, z1, impact=False):
    zz = f"({z0}+({z1}-{z0})*it/{dur:.3f})"
    if impact:
        zz = f"(if(lt(it,0.15),1.3-0.3*(1-pow(1-it/0.15,3)),{zz}))"
    vf = (f"{GRADE},fps={FPS},zoompan=z='{zz}':x='min(max(0,{FCX}-iw/zoom/2),iw-iw/zoom)':"
          f"y='min(max(0,{FCY}-ih/zoom*0.42),ih-ih/zoom)':d=1:s={W}x{H}:fps={FPS}")
    if tk not in SRC:
        L.die(f"нет исходника дубля {tk}: добавь HOOK['sources'] или TAKES в project.py")
    return reader(["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{dur + 0.2:.3f}", "-i", SRC[tk],
                   "-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])


def overlay(base, png):
    if not os.path.exists(png):
        return base
    im = np.asarray(Image.open(png).convert("RGBA"))
    a = im[..., 3:4].astype(np.float32) / 255.0
    return (base.astype(np.float32) * (1 - a) + im[..., :3] * a).astype(np.uint8)


YY, XX = np.mgrid[0:H, 0:W].astype(np.float32)
RMAX = float(np.hypot(W, H))


def circle_mask(k, cx, cy):
    r = RMAX * (k ** 2.2)                        # ускорение: сначала медленно, потом на весь кадр
    d = np.sqrt((XX - cx) ** 2 + (YY - cy) ** 2)
    return np.clip((r - d) / 3.0 + 0.5, 0, 1)[..., None]


def ring(base, mask):
    edge = (mask > 0.02) & (mask < 0.98)
    base[edge[..., 0]] = (base[edge[..., 0]].astype(np.float32) * 0.6 + 255 * 0.4).astype(np.uint8)
    return base


def gfx_frame(pid, t):
    return os.path.join(GFX, pid, f"frame_{int(t * FPS) + 1:06d}.png")


def encoder(path):
    return subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                             "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)


def render():
    blocks, end = timeline()
    n = int(round(end * FPS))
    readers, frames = {}, {}
    enc = encoder(f"{T}/hook_v.mp4")
    for f in range(n):
        t = f / FPS
        layers = []
        for bl in (b for b in blocks if b["start"] <= t < b["vis_end"]):
            i = bl["i"]
            if i not in readers:
                z0 = zbase(i)
                readers[i] = head_block(bl["take"], bl["a"], bl["vis_end"] - bl["start"], z0, z0 + 0.05, impact=(i == 0))
            fr = readers[i][1]()
            fr = frames.get(i) if fr is None else fr
            frames[i] = fr
            layers.append((bl, overlay(fr, gfx_frame(f"h{i + 1}", t - bl["start"]))))
        base = layers[0][1].copy()
        for bl, img in layers[1:]:
            k = (t - bl["start"]) / CIRC
            if k >= 1:
                base = img
                continue
            cx, cy = FCX + (W / 2 - FCX) * k, FCY + (H / 2 - FCY) * k
            m = circle_mask(k, cx, cy)
            base = ring((base.astype(np.float32) * (1 - m) + img.astype(np.float32) * m).astype(np.uint8), m)
        enc.stdin.write(base.tobytes())
    enc.stdin.close()
    enc.wait()
    for p, _ in readers.values():
        p.kill()
    # звук: фразы встык (та же цепочка, что у мастера) + музыка с ducking, обрыв в конце
    parts = []
    for bl in blocks:
        w, d = f"{T}/a{bl['i']}.wav", bl["b"] - bl["a"]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{bl['a']:.3f}", "-t", f"{d:.3f}", "-i", SRC[bl["take"]], "-vn",
                        "-af", f"{L.AUDIO_CHAIN},afade=t=in:d=0.012,afade=t=out:st={d - 0.03:.3f}:d=0.03,apad=pad_dur={GAP}",
                        "-ar", "48000", "-ac", "2", w], check=True)
        parts.append(w)
    with open(f"{T}/a.txt", "w") as fh:
        fh.write("".join(f"file '{p}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{T}/a.txt", "-af",
                    f"apad,atrim=0:{end:.3f}", "-c:a", "pcm_s16le", f"{T}/voice.wav"], check=True)
    music = HOOK.get("music")
    gain = HOOK.get("gain_db", -3.5)               # хук громче мастера: сводим к тем же −14 LUFS
    if music:
        fc = (f"[1:a]atrim=0:{end:.3f},asetpts=PTS-STARTPTS,volume={HOOK.get('music_db', -16)}dB,"
              f"afade=t=out:st={end - 0.06:.3f}:d=0.06[m];[m][0:a]sidechaincompress=threshold=0.05:ratio=4:attack=10:release=250[md];"
              f"[0:a][md]amix=inputs=2:normalize=0:duration=first,volume={gain}dB[a]")
        cmd = ["-i", f"{T}/voice.wav", "-i", L.P(music), "-filter_complex", fc, "-map", "[a]"]
    else:
        cmd = ["-i", f"{T}/voice.wav", "-af", f"volume={gain}dB"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", *cmd, "-ar", "48000", "-ac", "2", f"{T}/hook_a.wav"], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f"{T}/hook_v.mp4", "-i", f"{T}/hook_a.wav",
                    "-filter_complex", "[0:v]tpad=stop_mode=clone:stop_duration=0.2[v];[1:a]apad=pad_dur=0.2[a]",
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-b:a", "192k", "-shortest", f"{T}/hook.mp4"], check=True)
    print("хук:", f"{T}/hook.mp4", end, "с")


def sep_render(body):
    """Под заливкой — последний кадр хука, после середины — первый кадр ролика."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-sseof", "-0.1", "-i", f"{T}/hook_v.mp4", "-frames:v", "1",
                    f"{T}/hook_last.png"], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", body, "-vf", "select=eq(n\\,0)", "-frames:v", "1",
                    f"{T}/body_first.png"], check=True)
    a = np.asarray(Image.open(f"{T}/hook_last.png").convert("RGB").resize((W, H)))
    b = np.asarray(Image.open(f"{T}/body_first.png").convert("RGB").resize((W, H)))
    n = int(round(SEP * FPS))
    enc = encoder(f"{T}/sep_v.mp4")
    for f in range(n):
        t = f / FPS
        enc.stdin.write(overlay((a if t < SEP / 2 else b).copy(), gfx_frame("sep", t)).tobytes())
    enc.stdin.close()
    enc.wait()
    d = SEP
    fx = (f"anoisesrc=d={d}:c=pink:r=48000:a=0.6,highpass=f=500,lowpass=f=9000,"
          f"volume='if(lt(t,0.32),t/0.32,if(lt(t,0.4),1-(t-0.32)/0.08,if(between(t,{d - 0.4},{d - 0.02}),(t-{d - 0.4})/0.38*0.7,0)))':eval=frame,volume=-12dB[n];"
          f"sine=f=55:d={d}:r=48000,volume='if(between(t,0.3,0.9),exp(-(t-0.3)*6),0)':eval=frame,volume=-4dB[s];"
          "[n][s]amix=inputs=2:normalize=0,aformat=channel_layouts=stereo[a]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f"{T}/sep_v.mp4", "-f", "lavfi", "-t", str(d), "-i",
                    "anullsrc=r=48000:cl=stereo", "-filter_complex", fx, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", f"{T}/sep.mp4"], check=True)


def final():
    body = os.path.join(L.WORK, "body.mp4")
    if not os.path.exists(body):
        L.die("нет work/mz/body.mp4 — сначала `montazher.py render all`")
    os.makedirs(os.path.dirname(L.OUT), exist_ok=True)
    if not HOOK.get("phrases"):                    # без хука: ролик = тело
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", body, "-c", "copy", "-movflags", "+faststart", L.OUT], check=True)
        print("готово (без хука):", L.OUT)
        return
    if not os.path.exists(f"{T}/hook.mp4"):
        L.die("нет хука — `montazher.py hook`")
    sep_render(body)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", body, "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", f"{T}/body_n.mp4"], check=True)
    with open(f"{T}/all.txt", "w") as fh:
        fh.write("".join(f"file '{T}/{x}'\n" for x in ("hook.mp4", "sep.mp4", "body_n.mp4")))
    os.makedirs(os.path.dirname(L.OUT), exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{T}/all.txt", "-c:v", "libx264",
                    "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", L.OUT], check=True)
    with open(os.path.join(T, "plan.json"), encoding="utf-8") as fh:
        hook_end = json.load(fh)["hook_end"]
    base, ext = os.path.splitext(L.OUT)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", L.OUT, "-t", f"{hook_end + SEP + 20:.2f}", "-c", "copy",
                    f"{base} — начало{ext}"], check=True)
    print("готово:", L.OUT, "· начало для просмотра:", f"{base} — начало{ext}")


if __name__ == "__main__":
    {"plan": plan, "render": render, "final": final}[sys.argv[1]]()
