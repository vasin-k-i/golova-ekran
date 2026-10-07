#!/usr/bin/env python3
"""Шаг 8 — звук к картинке и мастер.

Про звук. Речь с телефона обычно идёт на −25…−30 LUFS, но пики от щелчков и
касаний стола дотягивают до −1 дБ. Гребёнка в 20+ дБ не даёт loudnorm поднять
уровень линейно, и он останавливается на −16 LUFS, а acompressor такие всплески
не догоняет: у него attack в миллисекундах, а щелчок короче.

Поэтому цепочка простая и предсказуемая: срез низа, честное усиление и быстрый
lookahead-лимитер, который и снимает щелчки.

⚠️ У alimiter параметр level по умолчанию ВКЛЮЧЁН — он подтягивает выход
обратно к нулю и полностью съедает limit. Без level=false пик уезжает
за 0 dBTP, сколько ни ставь лимит.

Музыка и звуки (необязательно). MUSIC — подложка: −31 LUFS, под голосом
прижимается ещё на 6 дБ и поднимается в паузах, смена трека — наплывом 1,6 с.
SFX — свуш на перестроение раскладки, тихий клик на появление пункта или
плашки, мягкий удар на полноэкранную карточку (не чаще раза в минуту),
−20…−25 дБ. Всё это кладётся на уже выровненный голос, и итог ещё раз
приводится к −14 LUFS тем же лимитером.
"""
import json
import os
import re
import subprocess

import lib

P = lib.load_project()
W, OUT = lib.work_dir(), lib.out_dir()
PL = lib.read_json("plan.json")
VIDEO, AUDIO = f"{W}/video_nosound.mp4", f"{W}/audio_cut.wav"
TARGET_LUFS = getattr(P, "TARGET_LUFS", -14.0)
GAIN = getattr(P, "AUDIO_GAIN_DB", None)
CHAIN_TAIL = "alimiter=limit=0.78:level=false:attack=1:release=60"


def loud(f, af=None):
    cmd = [lib.FF, "-hide_banner", "-nostats", "-i", f, "-af",
           (af + "," if af else "") +
           f"loudnorm=I={TARGET_LUFS}:TP=-1.5:print_format=json", "-f", "null", "-"]
    log = lib.sh(cmd).stderr
    m = re.search(r"\{[^{}]*input_i[^{}]*\}", log, re.S)
    if not m:
        lib.die("loudnorm не отдал замер — проверь звуковую дорожку")
    r = json.loads(m.group(0))
    return float(r["input_i"]), float(r["input_tp"]), float(r["input_lra"])


def sample():
    """Кусок дорожки для подбора усиления.

    Замер loudnorm по всему файлу занимает десятки секунд, а подбор требует
    нескольких проходов. Поэтому ищем на выжимке: три куска по 40 с из начала,
    середины и конца. Итог всё равно меряем по готовому мастеру целиком.
    """
    out = f"{W}/audio_sample.wav"
    if os.path.exists(out):
        return out
    d = lib.duration(AUDIO)
    if d <= 150:
        return AUDIO
    parts = []
    for i, ss in enumerate((d * 0.08, d * 0.45, max(0, d - 60))):
        p = f"{W}/_smp{i}.wav"
        lib.run([lib.FF, "-y", "-v", "error", "-ss", f"{ss:.2f}", "-t", "40",
                 "-i", AUDIO, "-c", "copy", p])
        parts.append(p)
    lst = f"{W}/_smp.txt"
    with open(lst, "w") as fh:
        for p in parts:
            fh.write(f"file '{os.path.basename(p)}'\n")
    lib.run([lib.FF, "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", lst, "-c", "copy", out])
    return out


def pick_gain():
    """Подбираем усиление под цель по замеру, а не на глаз.

    Лимитер съедает часть усиления, причём тем больше, чем сильнее давим,
    поэтому одним делением не обойтись — идём итерациями по невязке.
    """
    smp = sample()
    i0, tp0, _ = loud(AUDIO)
    print(f"исходный звук: {i0:.1f} LUFS, пик {tp0:.1f} dBTP")
    if smp != AUDIO:
        print(f"   усиление подбираю на выжимке {lib.duration(smp):.0f} с")
    g = round(TARGET_LUFS - i0, 1)
    for _ in range(6):
        af = f"highpass=f=75,volume={g}dB,{CHAIN_TAIL}"
        i1, tp1, _ = loud(smp, af)
        print(f"   пробую +{g:.1f} дБ → {i1:.1f} LUFS, пик {tp1:.1f} dBTP")
        if abs(i1 - TARGET_LUFS) < 0.3:
            return g
        step = TARGET_LUFS - i1
        g = round(g + max(-6.0, min(6.0, step)), 1)
        if g > 40:
            print("   ! дорожка совсем тихая — проверь запись, усиление упёрлось")
            return 40.0
    return g


SR = 48000
SFX_KIT = dict(whoosh=("whoosh-short.mp3", -21.0), whoosh_big=("whoosh-cinematic.mp3", -19.0),
               whoosh_soft=("whoosh-short.mp3", -26.0),
               impact=("impact-bass-1.mp3", -21.0), click=("click-soft.mp3", -24.0))
SFX_DIRS = ["~/.claude/skills/hyperframes-media/assets/sfx",
            "~/.codex/skills/hyperframes-media/assets/sfx"]


def load(path, n=None):
    import numpy as np
    raw = subprocess.run([lib.FF, "-nostdin", "-v", "error", "-i", path, "-f", "f32le",
                          "-ac", "2", "-ar", str(SR), "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.float32).reshape(-1, 2).copy()
    return a if n is None else a[:n]


def db(x):
    return 10 ** (x / 20)


def sfx_setup():
    cfg = getattr(P, "SFX", None)
    if cfg is None:
        return None, {}
    kit = dict(SFX_KIT)
    kit.update({k: v for k, v in cfg.items() if k != "dir"})
    dirs = [cfg.get("dir")] if cfg.get("dir") else SFX_DIRS
    for d in dirs:
        d = os.path.expanduser(d)
        if os.path.isdir(d):
            return d, kit
    print("   ! SFX включены, но библиотеку звуков не нашёл — задай SFX['dir']")
    return None, kit


def music_bed(voice, n):
    """Подложка: −31 LUFS, прижим под голос до −6 дБ, наплыв 1,6 с на смене трека."""
    import numpy as np
    tracks = PL.get("music", [])
    bed = np.zeros((n, 2), np.float32)
    xf = int(1.6 * SR)
    for k, m in enumerate(tracks):
        if not os.path.exists(m["src"]):
            lib.die(f"музыка: нет файла {m['src']}")
        a = int(m["a"] * SR)
        b = int(tracks[k + 1]["a"] * SR) + xf // 2 if k + 1 < len(tracks) else n
        b = min(b, n)
        x = load(m["src"])
        if not len(x) or b <= a:
            continue
        reps = int(np.ceil((b - a) / len(x)))
        x = np.tile(x, (reps, 1))[:b - a]            # короткий трек — по кругу
        i_lufs = loud(m["src"])[0]
        x *= db(m["lufs"] - i_lufs)
        if k:                                        # вход наплывом
            q = min(xf, len(x))
            x[:q] *= np.linspace(0, 1, q)[:, None]
        if k + 1 < len(tracks):                      # выход наплывом
            q = min(xf, len(x))
            x[-q:] *= np.linspace(1, 0, q)[:, None]
        bed[a:b] += x
    q = int(0.6 * SR)
    bed[:q] *= np.linspace(0, 1, q)[:, None]
    q = min(n, int(1.8 * SR))
    bed[n - q:] *= np.linspace(1, 0, q)[:, None]
    env = np.abs(voice).mean(1)
    w = int(0.25 * SR)
    env = np.convolve(env, np.ones(w, np.float32) / w, mode="same")
    ref = float(np.percentile(env, 95)) or 1.0
    duck = np.clip(1 - env / (ref * 0.08), db(-6), 1.0)   # под голосом −6 дБ
    return bed * duck[:, None]


def sfx_track(n):
    import numpy as np
    d, kit = sfx_setup()
    out = np.zeros((n, 2), np.float32)
    if not d:
        return out, {}
    ev = [list(e) for e in PL.get("events", [])] + \
         [[t, f, g] for t, f, g in PL.get("sfx_extra", [])]
    ev.sort(key=lambda e: e[0])
    cache, count, last_impact = {}, {}, -1e9
    for e in ev:
        t, name = float(e[0]), e[1]
        if name == "impact":
            if t - last_impact < 60:                 # удар — не чаще раза в минуту
                continue
            last_impact = t
        fname, gain = kit.get(name, (name, -24.0))
        if len(e) > 2:
            gain = float(e[2])
        path = fname if os.path.isabs(fname) else os.path.join(d, fname)
        if not os.path.exists(path):
            continue
        if path not in cache:
            cache[path] = load(path)
        x = cache[path] * db(gain)
        i = int(t * SR)
        if i < 0 or i >= n:
            continue
        j = min(n, i + len(x))
        out[i:j] += x[:j - i]
        count[name] = count.get(name, 0) + 1
    return out, count


def mix_master(g, master):
    """Голос (уже с усилением и лимитером) + подложка + звуки → снова −14 LUFS."""
    import numpy as np
    vo = f"{W}/voice_proc.wav"
    lib.run([lib.FF, "-y", "-v", "error", "-i", AUDIO, "-af",
             f"highpass=f=75,volume={g}dB,{CHAIN_TAIL}", "-ar", str(SR), "-ac", "2", vo])
    voice = load(vo)
    n = len(voice)
    bed = music_bed(voice, n) if PL.get("music") else np.zeros_like(voice)
    fx, count = sfx_track(n)
    raw = f"{W}/mix_raw.wav"
    subprocess.run([lib.FF, "-nostdin", "-y", "-v", "error", "-f", "f32le", "-ar", str(SR),
                    "-ac", "2", "-i", "-", raw], input=(voice + bed + fx).tobytes(), check=True)
    i0 = loud(raw)[0]
    gain = round(TARGET_LUFS - i0, 2)
    lib.run([lib.FF, "-y", "-v", "error", "-i", VIDEO, "-i", raw,
             "-af", f"volume={gain}dB,{CHAIN_TAIL}", "-map", "0:v", "-map", "1:a",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
             "-movflags", "+faststart", "-shortest", master])
    parts = []
    if PL.get("music"):
        parts.append(f"музыка {len(PL['music'])} трек(а), −31 LUFS, под голосом ещё −6 дБ")
    if count:
        parts.append("звуков " + str(sum(count.values())) + " (" +
                     ", ".join(f"{k} {v}" for k, v in sorted(count.items())) + ")")
    print("   " + " · ".join(parts))


def main():
    import sys
    raw_cut = lib.repeats_guard(P, sys.argv[1:], "final")
    dv, da = lib.duration(VIDEO), lib.duration(AUDIO)
    print(f"картинка {dv:.3f} с · звук {da:.3f} с · "
          f"расхождение {abs(dv - da) * 1000:.0f} мс")
    if abs(dv - da) > 0.05:
        print("   ! дорожки разъехались — проверь резку")

    g = GAIN if GAIN is not None else pick_gain()
    chain = f"highpass=f=75,volume={g}dB,{CHAIN_TAIL}"
    name = getattr(P, "OUT_NAME", "Ролик")
    if raw_cut:
        name += f" — {lib.NO_REPEATS_TAG}"
    master = os.path.join(OUT, f"{name}.mp4")
    if PL.get("music") or getattr(P, "SFX", None) is not None:
        mix_master(g, master)
    else:
        lib.run([lib.FF, "-y", "-v", "error", "-i", VIDEO, "-i", AUDIO, "-af", chain,
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                 "-movflags", "+faststart", "-shortest", master])
    i1, tp1, lra = loud(master)
    print(f"\nготово: {master}")
    print(f"  {lib.duration(master):.2f} с · {os.path.getsize(master) / 1e6:.0f} МБ")
    print(f"  громкость: {i1:.1f} LUFS, пик {tp1:.1f} dBTP, LRA {lra:.1f}")
    print(f"  (YouTube приводит к −14 LUFS и только приглушает — тише сдавать незачем)")


if __name__ == "__main__":
    main()
