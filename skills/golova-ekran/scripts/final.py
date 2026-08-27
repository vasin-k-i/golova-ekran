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
"""
import json
import os
import re

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


def main():
    dv, da = lib.duration(VIDEO), lib.duration(AUDIO)
    print(f"картинка {dv:.3f} с · звук {da:.3f} с · "
          f"расхождение {abs(dv - da) * 1000:.0f} мс")
    if abs(dv - da) > 0.05:
        print("   ! дорожки разъехались — проверь резку")

    g = GAIN if GAIN is not None else pick_gain()
    chain = f"highpass=f=75,volume={g}dB,{CHAIN_TAIL}"
    name = getattr(P, "OUT_NAME", "Ролик")
    master = os.path.join(OUT, f"{name}.mp4")
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
