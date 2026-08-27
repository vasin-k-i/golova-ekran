#!/usr/bin/env python3
"""Шаг 2 — резка тишины по амплитуде.

Порог по звуку, НЕ по расшифровке: Whisper врёт про паузы — показывает разрыв
там, где его нет, и наоборот.

Внутри окон play (там, где на экране играет видео) действует свой, тихий порог.
Звук плеера приходит на микрофон примерно на −45 дБ, то есть НИЖЕ обычного
порога −32 дБ, и штатная резка выносит весь показ. Подробности и цифры —
references/02-cutting.md.
"""
import os
import re

import lib

P = lib.load_project()
S = getattr(P, "SILENCE", dict(noise="-32dB", min_sil=0.40, keep=0.25))
PS = getattr(P, "PLAY_SILENCE", dict(noise="-52dB", min_sil=0.80, keep=0.40))


def silences(f, noise, d):
    log = lib.sh([lib.FF, "-hide_banner", "-nostats", "-i", f, "-vn", "-af",
                  f"silencedetect=noise={noise}:d={d}", "-f", "null", "-"]).stderr
    out, st = [], None
    for line in log.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            st = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and st is not None:
            out.append((st, float(m.group(1))))
            st = None
    return out


def subtract(iv, lo, hi):
    out = []
    for a, b in iv:
        if b <= lo or a >= hi:
            out.append((a, b))
            continue
        if a < lo:
            out.append((a, lo))
        if b > hi:
            out.append((hi, b))
    return out


def clip(iv, lo, hi):
    return [(max(a, lo), min(b, hi)) for a, b in iv if min(b, hi) > max(a, lo)]


def silence_map(f, play):
    loud = silences(f, S["noise"], S["min_sil"])
    for p0, p1 in play:
        loud = subtract(loud, p0, p1)
    out = [(a, b, S["keep"] / 2, S["min_sil"]) for a, b in loud]
    if play:
        quiet = silences(f, PS["noise"], PS["min_sil"])
        for p0, p1 in play:
            out += [(a, b, PS["keep"] / 2, PS["min_sil"])
                    for a, b in clip(quiet, p0, p1)]
    return sorted(out)


def build_keeps(dur, sil):
    keeps, pos = [], 0.0
    for a, b, pad, need in sil:
        a = max(0.0, a)
        if b - a < need:
            continue
        ka, kb = a + pad, b - pad
        if ka > pos:
            keeps.append((pos, ka))
        pos = max(pos, kb)
    if pos < dur:
        keeps.append((pos, dur))
    return [(round(a, 3), round(b, 3)) for a, b in keeps if b - a > 0.05]


def main():
    segs, n, src_total = [], 0, 0.0
    for t in P.TAKES:
        dur = lib.duration(t["head"])
        src_total += dur
        ks = build_keeps(dur, silence_map(t["head"], t["play"]))
        for a, b in ks:
            segs.append(dict(i=n, take=t["id"], a=a, b=b, d=round(b - a, 3)))
            n += 1
        pl = sum(p1 - p0 for p0, p1 in t["play"])
        kept = sum(min(b, p1) - max(a, p0) for a, b in ks
                   for p0, p1 in t["play"] if b > p0 and a < p1)
        extra = f"  · показ {kept:.1f} из {pl:.1f} с" if pl else ""
        print(f"дубль {t['id']}: {dur:7.1f} с → {len(ks):3d} сегментов, "
              f"речи {sum(b - a for a, b in ks):7.1f} с{extra}")
    lib.write_json("segments.json", segs)
    tot = sum(s["d"] for s in segs)
    print(f"\nвсего {len(segs)} сегментов · {src_total:.1f} с → {tot:.1f} с "
          f"(−{(1 - tot / src_total) * 100:.1f}%)")
    print("дальше: montage.py transcribe")


if __name__ == "__main__":
    main()
