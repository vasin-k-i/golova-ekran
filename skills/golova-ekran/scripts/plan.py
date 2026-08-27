#!/usr/bin/env python3
"""Шаг 5 — что оставляем, что режем, чем оформляем. Пишет work/plan.json.

Порядок железный: сначала тишина, СРАЗУ за ней проход по повторам, оговоркам
и мусору, и только потом раскладка и вставки. Если чистить речь, когда вставки
уже прибиты к таймкодам, любая вырезанная фраза сдвигает всю карту вставок.

Длительности считаем В КАДРАХ — ровно так же, как их потом нарежет cut.py.
Если складывать сырые секунды, план расходится с резкой, и картинка выходит
короче звука (ловилось на два кадра при 130 склейках).
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
        for a, b, mode, panel in P.MODES.get(t["id"], [(0, 1e9, "A", None)]):
            oa, ob = src_to_out(t["id"], a), src_to_out(t["id"], b)
            if ob - oa > 0.2:
                blocks.append(dict(a=oa, b=ob, m=mode, panel=panel))
    blocks.sort(key=lambda x: x["a"])
    for i in range(len(blocks) - 1):
        blocks[i]["b"] = blocks[i + 1]["a"]
    blocks[0]["a"] = 0.0
    blocks[-1]["b"] = total

    ins = []
    for it in getattr(P, "INSERTS", []):
        oa = src_to_out(it["take"], it["at"])
        ins.append(dict(it, a=oa, b=round(oa + it["dur"], 3)))

    bw = None
    if BW_SEG is not None:
        if BW_SEG not in out_of:
            lib.die(f"сегмент BW={BW_SEG} выкинут — он не может быть примером")
        bw = dict(a=out_of[BW_SEG][0], b=out_of[BW_SEG][1])

    lib.write_json("plan.json", dict(
        fps=FPS, out_dur=total, keeps=keeps, blocks=blocks, inserts=ins, bw=bw,
        seg_out={str(k): v for k, v in out_of.items()}))

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
    print("\nдальше: montage.py cut")


if __name__ == "__main__":
    main()
