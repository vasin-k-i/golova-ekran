#!/usr/bin/env python3
"""Шаг 4а — проход по повторам и оговоркам: список на согласование и отметка.

Без этого шага `build` и `final` мастер НЕ собирают. Повод: тестовый ролик
ушёл человеку с фальстартом «с платных курсов, с экспертных… с экспертов и…
прок… прок…» — проход пропустили «потому что тест». Тест тоже смотрят глазами,
и оговорка в нём читается как брак монтажа, а не как черновик.

  montage.py repeats                  что режем (DROP/TRIM) дословно с таймкодами
                                      + кандидаты, которые стоит послушать
  montage.py repeats --approve "кто и когда согласовал список"
                                      отметка «проход сделан, список согласован»

Отметка лежит в проекте рядом с project.py (repeats_ok.json) и привязана к
резке тишины и к спискам DROP/TRIM/BW: поменял список или перерезал тишину —
отметка слетает, и список надо согласовать заново.

Кандидаты — это подсказка, а не решение: из восьми автоматических кандидатов
настоящим фальстартом обычно оказывается один, остальное — разрезанное слово
на стыке. Правило: первое вхождение режем, последнее оставляем; ложный повтор
на стыке не трогаем; вырезать живую речь хуже, чем пропустить повтор.
"""
import re
import sys

import lib

P = lib.load_project()
FILLERS = {"итак", "то есть", "по сути", "ну", "вот", "так", "и", "а", "но", "значит",
           "в общем", "короче", "смотрите", "смотри", "э", "эм", "ммм", "а-а-а"}
SCRAPS = ("продолжение следует", "субтитры", "спасибо за просмотр")


def words(t):
    return re.findall(r"[a-zа-яё0-9]+", t.lower().replace("ё", "е"))


def candidates(T, drop):
    """Что стоит послушать: заход, который повторяется следующим сегментом,
    висящий обрубок, голое слово-паразит. Только то, чего ещё нет в DROP."""
    out = []
    keep = [s for s in T if s["i"] not in drop]
    for k, s in enumerate(keep):
        w = words(s["txt"])
        if not w or any(x in s["txt"].lower() for x in SCRAPS):
            continue
        txt = " ".join(w)
        why = None
        if txt in FILLERS:
            why = "слово-паразит отдельным сегментом"
        else:
            for nxt in keep[k + 1:k + 3]:
                nw = words(nxt["txt"])
                stem = lambda x: x[:5]
                common = len({stem(x) for x in w[:4]} & {stem(x) for x in nw[:6]})
                if s["d"] <= 3.0 and common >= 2 and nxt["a"] - s["b"] < 6:
                    why = f"заход повторяется в №{nxt['i']}: «{nxt['txt'][:70]}»"
                    break
            if not why and s["d"] <= 1.6 and (s["txt"].rstrip().endswith("...")
                                              or len(w) <= 2):
                why = "короткий обрубок — послушай, не фальстарт ли"
        if why:
            out.append((s, why))
    return out


def show():
    T = lib.read_json("transcript.json")
    by = {s["i"]: s for s in T}
    drop = set(getattr(P, "DROP", []))
    trim = list(getattr(P, "TRIM", []))
    scrap_db = getattr(P, "SCRAP_DB", -40.0)
    auto = {s["i"] for s in T if s["mean"] < scrap_db}
    print("РЕЖЕМ (DROP) — дословно, время исходника:")
    total = 0.0
    for i in sorted(drop | auto):
        s = by.get(i)
        if not s:
            continue
        tag = "огрызок по громкости" if i in auto and i not in drop else ""
        total += s["d"]
        print(f"  №{i:<4d} [{s['take']}] {lib.ms(s['a'])}–{lib.ms(s['b'])}  "
              f"{s['d']:4.1f} с  «{s['txt']}» {tag}")
    for tk, a, b in trim:
        total += b - a
        print(f"  TRIM  [{tk}] {lib.ms(a)}–{lib.ms(b)}  {b - a:4.1f} с  (вырез внутри сегмента)")
    print(f"  всего уходит {total:.1f} с")
    cand = candidates(T, drop | auto)
    if cand:
        print("\nКАНДИДАТЫ — послушать, решает человек (в DROP их нет):")
        for s, why in cand:
            print(f"  №{s['i']:<4d} [{s['take']}] {lib.ms(s['a'])}  «{s['txt']}»\n"
                  f"         ↳ {why}")
    st, msg = lib.repeats_state(P)
    print(f"\nотметка: {msg}")
    if not st:
        print("покажи список человеку ДО резки; согласовал — "
              "`montage.py repeats --approve \"кто и когда\"`")


def approve(note):
    if not note.strip():
        lib.die("напиши, кто и когда согласовал список: --approve \"автор, 07.10\"")
    lib.write_repeats_ok(P, note)
    print(f"✓ проход по повторам отмечен: {note}")
    print("  поменяешь DROP/TRIM/BW или перережешь тишину — отметка слетит сама")


def main():
    a = sys.argv[1:]
    if a and a[0] == "--approve":
        return approve(" ".join(a[1:]) or "")
    show()


if __name__ == "__main__":
    main()
