#!/usr/bin/env python3
"""Проверка монтажного листа до рендера — дёшево, за секунду.

  · покрытие: планы идут встык от начала до конца ролика, без дыр и наложений;
  · повторы: один и тот же кусок одного исходника не стоит дважды (Костя: «повторы заметны»);
  · файлы: все src на месте; длина клипа хватает на план (иначе стоп-кадр в хвосте);
  · ритм: смены крупности головы (FULL z) в минуту и длина вставок;
  · текст: куски не налезают друг на друга.
Код выхода 1, если есть ошибки (дыры, повторы, нет файла). Предупреждения — не мешают.
"""
import os
import subprocess
import sys
from collections import defaultdict

import mzlib as L

E = L.edl()
_dur_cache = {}


def dur(src):
    if src not in _dur_cache:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                           capture_output=True, text=True)
        try:
            _dur_cache[src] = float(r.stdout.strip())
        except ValueError:
            _dur_cache[src] = None
    return _dur_cache[src]


def main():
    errs, warns = [], []
    shots = [(L.s2o(t, a), L.s2o(t, b), k, p, (t, a, b)) for t, a, b, k, p in E.SHOTS]
    total = sum(k["d"] for k in L.KEEPS) if L.KEEPS else shots[-1][1]
    # покрытие
    if shots and shots[0][0] > 0.3:
        errs.append(f"начало 0–{shots[0][0]:.2f} с не покрыто планом")
    for (a1, b1, _, _, s1), (a2, b2, _, _, s2) in zip(shots, shots[1:]):
        if a2 - b1 > 1.2:
            errs.append(f"дыра {b1:.2f}–{a2:.2f} с между {s1} и {s2}")
        elif b1 - a2 > 0.05:
            errs.append(f"наложение {a2:.2f}–{b1:.2f} с: {s1} и {s2}")
    if shots and total - shots[-1][1] > 1.2:
        errs.append(f"хвост {shots[-1][1]:.2f}–{total:.2f} с не покрыт")
    # повторы и файлы
    used = defaultdict(list)
    for a, b, k, p, s in shots:
        if b - a < 0.6 and k != "FULL":
            warns.append(f"{s} {k}: вставка {b - a:.2f} с — мелькнёт, не прочитается")
        src = p.get("src")
        if not src:
            continue
        if not os.path.exists(src):
            errs.append(f"{s} {k}: нет файла {src}")
            continue
        ss, sp = p.get("ss", 0.0), p.get("speed", 1.0)
        need = ss + (b - a) * sp
        d = dur(src)
        if d and need > d + 0.05:
            warns.append(f"{s} {k}: клипу {os.path.basename(src)} не хватает {need - d:.2f} с (дальше стоп-кадр)")
        for (x0, x1, s0) in used[src]:
            if ss < x1 - 0.1 and need > x0 + 0.1:
                errs.append(f"повтор: {os.path.basename(src)} {max(ss, x0):.1f}–{min(need, x1):.1f} с — в {s0} и {s}")
        used[src].append((ss, need, s))
    # ритм крупности головы
    per_min = defaultdict(int)
    prev = None
    for a, b, k, p, s in shots:
        if k == "FULL":
            z = p.get("z", 1.0)
            if prev is not None and abs(z - prev) > 0.01:
                per_min[int(a // 60)] += 1
            prev = z
    if per_min:
        m, c = max(per_min.items(), key=lambda x: x[1])
        (warns if c > 4 else []).append(f"смен крупности головы {c} в минуту {m + 1} — больше 4 читается как дёрганье")
    kinds = defaultdict(float)
    for a, b, k, _, _ in shots:
        kinds[k] += b - a
    # текст
    os.environ["MZ_BUILD_GFX"] = "1"
    import mz_texts as G
    gs = sorted(G.GFX, key=lambda g: g["out_at"])
    for g1, g2 in zip(gs, gs[1:]):
        if g2["out_at"] < g1["out_at"] + g1["dur"] - 0.05:
            warns.append(f"текст {g1['id']} и {g2['id']} налезают ({g2['out_at']:.2f} с)")
    warns += G.SHRUNK
    print(f"ролик {total:.1f} с · планов {len(shots)} · текстов {len(G.GFX)}")
    print("  доля: " + ", ".join(f"{k} {v / max(total, 1) * 100:.0f} %" for k, v in sorted(kinds.items(), key=lambda x: -x[1])))
    for w in warns:
        print("  ⚠", w)
    for e in errs:
        print("  ✗", e)
    print("ок" if not errs else f"ошибок {len(errs)} — до рендера исправить")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
