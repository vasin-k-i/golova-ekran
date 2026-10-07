#!/usr/bin/env python3
"""Шаг 5 — что оставляем, что режем, чем оформляем. Пишет work/plan.json.

Порядок железный: сначала тишина, СРАЗУ за ней проход по повторам, оговоркам
и мусору, и только потом раскладка и вставки. Если чистить речь, когда вставки
уже прибиты к таймкодам, любая вырезанная фраза сдвигает всю карту вставок.

Длительности считаем В КАДРАХ — ровно так же, как их потом нарежет cut.py.
Если складывать сырые секунды, план расходится с резкой, и картинка выходит
короче звука (ловилось на два кадра при 130 склейках).

Здесь же всё, что привязано ко времени исходника (камера на экран, стоп-кадры,
плашки, подписи разделов, графика, музыка), переводится во время готового
ролика, и считается, сколько раз в минуту меняется план. Больше четырёх
в минуту — зритель начинает следить за монтажом, а не за смыслом.
"""
import lib

P = lib.load_project()
T = lib.read_json("transcript.json")
FPS = P.FPS
SCRAP_DB = getattr(P, "SCRAP_DB", -40.0)
DROP_MANUAL = set(getattr(P, "DROP", []))
TRIM = list(getattr(P, "TRIM", []))
BW_SEG = getattr(P, "BW", None)


def in_play(take_id, a, b):
    for t in P.TAKES:
        if t["id"] == take_id:
            return any(b > p0 and a < p1 for p0, p1 in t["play"])
    return False


# Правило «тише порога = огрызок» НЕ применяется внутри окон показа:
# звук плеера сам по себе тише этого порога.
AUTO = {i for i, s in enumerate(T)
        if s["mean"] < SCRAP_DB and not in_play(s["take"], s["a"], s["b"])}
DROP = (AUTO | DROP_MANUAL) - ({BW_SEG} if BW_SEG is not None else set())


def trim_pieces(take, a, b):
    pieces = [(a, b)]
    for tk, t0, t1 in TRIM:
        if tk != take:
            continue
        nxt = []
        for pa, pb in pieces:
            if t1 <= pa or t0 >= pb:
                nxt.append((pa, pb))
                continue
            if pa < t0:
                nxt.append((pa, t0))
            if pb > t1:
                nxt.append((t1, pb))
        pieces = nxt
    return pieces


MORPH = float(getattr(P, "MORPH", 0.7))   # перестроение раскладки, с
PANEL_OUT = 0.35                          # панель уходит раньше конца блока


def studio_links(blocks):
    """Кто из блоков студии с чего перестраивается.

    Перестроение (0,7 с) бывает только между раскладками студии. Карточка T
    ложится поверх кадра и в цепочку не входит: после неё следующий план
    перестраивается из того, что было ДО карточки.
    """
    prev = None                     # последний блок студии не-T
    for i, b in enumerate(blocks):
        b["studio"] = b["m"] in lib.STUDIO
        b["from"] = None
        if not b["studio"]:
            prev = None
            continue
        if b["m"] == "T":
            b["from"] = prev
            continue
        if prev is not None and (blocks[prev]["m"] != b["m"] or
                                 blocks[i - 1]["m"] == "T"):
            b["from"] = prev
        prev = i
        if b["m"] == "H" and b.get("panel"):
            t_in = b["a"] + (MORPH if b["from"] is not None else 0.0) + 0.15
            t_out = max(t_in + 0.5, b["b"] - PANEL_OUT)
            n = max(1, len(getattr(P, "PANELS", {}).get(b["panel"], {})
                           .get("items", [])) or 1)
            step = (t_out - t_in) / n
            b["panel_t"] = [round(t_in, 3), round(t_out, 3),
                            [round(t_in + k * step, 3) for k in range(n)]]


def entry(x, n_extra):
    """Запись из project.py: кортеж (дубль, секунда, …) или dict(take=, at=, …)."""
    if isinstance(x, dict):
        return x["take"], float(x["at"]), x
    t = tuple(x)
    return t[0], float(t[1]), t[2:2 + n_extra]


def block_at(blocks, t):
    for i, b in enumerate(blocks):
        if b["a"] - 1e-6 <= t < b["b"]:
            return i
    return len(blocks) - 1


def timed_things(src_to_out, blocks, total):
    """Всё, что задано во времени исходника, — во время готового ролика."""
    out = dict(freezes=[], cams=[], chips=[], sections=[], gfx=[], music=[],
               sfx_extra=[], events=[])

    for x in getattr(P, "FREEZE", []):
        take, at, rest = entry(x, 1)
        frame = rest["frame"] if isinstance(rest, dict) else rest[0]
        a = src_to_out(take, at)
        i = block_at(blocks, a)
        if blocks[i]["m"] != "S":
            print(f"   ! стоп-кадр {take}@{at} попал в блок {blocks[i]['m']}, "
                  "а держат его только в S — пропускаю")
            continue
        # держим до конца куска: обратно в живую запись наплывом не возвращаемся
        out["freezes"].append(dict(a=a, b=blocks[i]["b"], take=take,
                                   src=float(frame), block=i))

    for x in getattr(P, "CAM", []):
        take, at, rest = entry(x, 4)
        if isinstance(rest, dict):
            z, cx, cy, dur = rest["z"], rest.get("x", 0.5), rest.get("y", 0.5), \
                rest.get("dur", 0.8)
        else:
            z, cx, cy = rest[0], rest[1], rest[2]
            dur = rest[3] if len(rest) > 3 else 0.8
        out["cams"].append(dict(t=src_to_out(take, at), z=float(z), x=float(cx),
                                y=float(cy), dur=float(dur)))
    out["cams"].sort(key=lambda c: c["t"])

    for i, x in enumerate(getattr(P, "CHIPS", [])):
        a = src_to_out(x["take"], x["at"])
        out["chips"].append(dict(i=i, a=a, b=round(min(total, a + x.get("dur", 3.0)), 3),
                                 m=blocks[block_at(blocks, a)]["m"]))

    for x in getattr(P, "SECTIONS", []):
        take, at, rest = entry(x, 1)
        out["sections"].append([src_to_out(take, at),
                                rest["text"] if isinstance(rest, dict) else rest[0]])
    out["sections"].sort()

    for x in getattr(P, "GFX", []):
        a = src_to_out(x["take"], x["at"])
        out["gfx"].append(dict(id=x["id"], a=a, layer=x.get("layer", "fg"),
                               sfx=[list(s) for s in x.get("sfx", [])]))

    for x in getattr(P, "MUSIC", []):
        a = src_to_out(x.get("take", P.TAKES[0]["id"]), x.get("at", 0.0))
        out["music"].append(dict(src=x["src"], a=a, lufs=float(x.get("lufs", -31.0))))
    out["music"].sort(key=lambda m: m["a"])

    for x in getattr(P, "SFX_EXTRA", []):
        take, at, rest = entry(x, 2)
        out["sfx_extra"].append([src_to_out(take, at), rest[0],
                                 float(rest[1]) if len(rest) > 1 else -24.0])

    # звуковые события: свуш на перестроение, клик на появление, удар на карточку
    ev = out["events"]
    for i, b in enumerate(blocks):
        if i and b["m"] != blocks[i - 1]["m"]:
            if b["m"] == "T":
                ev.append([round(b["a"] - 0.05, 3), "whoosh_big"])
                ev.append([round(b["a"] + 0.3, 3), "impact"])
            elif b["studio"]:
                ev.append([round(b["a"] - 0.12, 3), "whoosh"])
        for t in (b.get("panel_t") or [0, 0, []])[2]:
            ev.append([t, "click"])
    for c in out["chips"]:
        ev.append([c["a"], "click"])
    for g in out["gfx"]:
        for s in g["sfx"]:
            ev.append([round(g["a"] + float(s[0]), 3), s[1]] + list(s[2:3]))
    ev.sort(key=lambda e: e[0])
    return out


def rhythm(blocks, total):
    """Сколько раз в минуту меняется план — цифра в отчёт.

    Правило: не чаще раза в 12–15 с и не больше 4 в минуту. Цифровой зум
    на каждой склейке под это правило не подпадает — он запрещён вовсе:
    1.0↔1.13 на каждой из 575 склеек читался как дёрганая камера.
    """
    ch = [b["a"] for i, b in enumerate(blocks) if i and b["m"] != blocks[i - 1]["m"]]
    mins = max(total / 60.0, 1e-6)
    worst = max([sum(1 for y in ch if x <= y < x + 60) for x in ch] or [0])
    if total < 60:
        worst = len(ch)
    flag = "  ✓" if worst <= 4 else "  ✗ больше 4 в минуту — сведи соседние планы"
    print(f"\nсмен плана {len(ch)} за {lib.ms(total)}: в среднем "
          f"{len(ch) / mins:.1f} в минуту, в самую плотную минуту {worst}{flag}")
    for i, b in enumerate(blocks):
        d = b["b"] - b["a"]
        if b["m"] == "T" and not 1.2 <= d <= 4.0:
            print(f"   ! карточка T {lib.ms(b['a'])} висит {d:.1f} с — держи 1,5–3 с")
        elif b["m"] != "T" and d < 12 and 0 < i < len(blocks) - 1 \
                and blocks[i - 1]["m"] != "T" and blocks[i + 1]["m"] != "T":
            print(f"   ! план {b['m']} {lib.ms(b['a'])} всего {d:.1f} с — "
                  "смена плана реже раза в 12–15 с")


def main():
    keeps, pos, out_of = [], 0.0, {}
    for i, s in enumerate(T):
        if i in DROP:
            continue
        start = pos
        for a, b in trim_pieces(s["take"], s["a"], s["b"]):
            n1, n2 = int(round(a * FPS)), int(round(b * FPS)) - 1
            if n2 < n1:
                continue
            d = (n2 - n1 + 1) / FPS
            keeps.append(dict(take=s["take"], a=round(a, 3), b=round(b, 3), d=d))
            pos += d
        out_of[i] = (round(start, 4), round(pos, 4))
    total = round(pos, 4)
    if not keeps:
        lib.die("после отсева не осталось ни одного сегмента — проверь DROP")

    def src_to_out(take, t):
        acc = 0.0
        for k in keeps:
            if k["take"] == take:
                if t < k["a"]:
                    return round(acc, 4)
                if t <= k["b"]:
                    return round(acc + min(t - k["a"], k["d"]), 4)
            acc += k["d"]
        return round(acc, 4)

    blocks = []
    for t in P.TAKES:
        for sp in P.MODES.get(t["id"], [(0, 1e9, "A", None)]):
            a, b, mode = sp[0], sp[1], sp[2]
            panel = sp[3] if len(sp) > 3 else None
            if mode not in lib.CLASSIC + lib.STUDIO:
                lib.die(f"раскладки «{mode}» нет. Есть: "
                        f"{', '.join(lib.CLASSIC + lib.STUDIO)}")
            oa, ob = src_to_out(t["id"], a), src_to_out(t["id"], b)
            if ob - oa > 0.2:
                blocks.append(dict(a=oa, b=ob, m=mode, panel=panel))
    blocks.sort(key=lambda x: x["a"])
    for i in range(len(blocks) - 1):
        blocks[i]["b"] = blocks[i + 1]["a"]
    blocks[0]["a"] = 0.0
    blocks[-1]["b"] = total
    studio_links(blocks)

    ins = []
    for it in getattr(P, "INSERTS", []):
        oa = src_to_out(it["take"], it["at"])
        ins.append(dict(it, a=oa, b=round(oa + it["dur"], 3)))

    timed = timed_things(src_to_out, blocks, total)

    bw = None
    if BW_SEG is not None:
        if BW_SEG not in out_of:
            lib.die(f"сегмент BW={BW_SEG} выкинут — он не может быть примером")
        bw = dict(a=out_of[BW_SEG][0], b=out_of[BW_SEG][1])

    lib.write_json("plan.json", dict(
        fps=FPS, out_dur=total, keeps=keeps, blocks=blocks, inserts=ins, bw=bw,
        seg_out={str(k): v for k, v in out_of.items()}, morph=MORPH, **timed))

    src = sum(s["d"] for s in T)
    play = sum(k["d"] for k in keeps if in_play(k["take"], k["a"], k["b"]))
    print(f"сегментов {len(T)} → {len(keeps)} (убрали {len(DROP)})")
    print(f"   мусор по громкости: {len(AUTO)} · руками: {len(DROP_MANUAL - AUTO)}")
    if TRIM:
        print(f"   адресных вырезов внутри сегментов: {len(TRIM)}, "
              f"{sum(b - a for _, a, b in TRIM):.1f} с")
    if play:
        print(f"   показ с экрана сохранён: {play:.1f} с")
    if bw:
        print(f"   оговорка №{BW_SEG} оставлена нарочно, ч/б "
              f"{lib.ms(bw['a'])}–{lib.ms(bw['b'])}")
    print(f"речь {src:.1f} с → {total:.2f} с ({lib.ms(total)}) · "
          f"{int(round(total * FPS))} кадров")
    print(f"\nблоков раскладки {len(blocks)}:")
    for b in blocks:
        tag = b["m"] + ("/" + b["panel"] if b["panel"] else "")
        print(f"   {tag:11s} {lib.ms(b['a'])} → {lib.ms(b['b'])}   ({b['b'] - b['a']:.1f} с)")
    for i in ins:
        print(f"   вставка {i['n']} {i['lay']}  {lib.ms(i['a'])} +{i['dur']} с")
    rhythm(blocks, total)
    print(f"\n{lib.repeats_state(P)[1]}")
    for name, n in (("стоп-кадров", len(timed["freezes"])),
                    ("ключей камеры на экран", len(timed["cams"])),
                    ("плашек", len(timed["chips"])),
                    ("кусков графики", len(timed["gfx"])),
                    ("подписей разделов", len(timed["sections"])),
                    ("треков музыки", len(timed["music"]))):
        if n:
            print(f"   {name}: {n}")
    print("\nдальше: montage.py cut")


if __name__ == "__main__":
    main()
