#!/usr/bin/env python3
"""Шаг 7а — наезд за курсором на записи экрана. Пишет work/zoom.json.

Зачем. В раскладке A рабочее окно ужимается до карточки 1160 px шириной:
терминал и мелкий шрифт в браузере на ней не читаются. Медленный наезд на то
место, где прямо сейчас идёт действие, возвращает читаемость и заодно ведёт
взгляд — зритель смотрит туда, куда показывают, а не ищет по всему экрану.

Что считаем действием. Курсора в кадре может не быть вовсе: половина работы
идёт с клавиатуры, а в терминале мышь вообще не нужна. Поэтому ловим не
стрелку, а ИЗМЕНЕНИЕ. Разницу соседних кадров раскладываем по сетке 32×18
и берём центр тяжести горящих клеток: двигают мышь — горит клетка под мышью,
печатают — горит каретка, открылось меню — горит меню. Шаблонный поиск самой
стрелки работал бы только на одной теме курсора и ломался бы на текстовом
«луче» и на «руке» над ссылкой.

Границы сцен. Горит больше трети сетки — на экране сменилась вся картинка:
скролл, переход на другую страницу, другое окно. Это граница: наезд
начинается заново. Внутри сцены камеру не сбрасываем никогда — зритель не
должен замечать монтаж. Сброс попадает ровно на смену картинки и потому
не читается как рывок.

Анализируем work/scr_cut.mp4 — экран УЖЕ нарезанный, то есть в таймкодах
готового ролика. Пересчитывать вырезы не нужно: что нашли, то и есть время
внутри блока.

Камера по ключам (CAM в project.py). Автонаезд хорош там, где на экране
работают руками. Когда человек РАССКАЗЫВАЕТ про цифру на графике, нужен
другой наезд: быстро (0,6–1,0 с, easeInOut) туда, о чём речь, держать,
пока говорит, и выехать. Такие места ставятся ключами: (дубль, секунда,
зум, x, y). Блок с ключами берёт только ключи, автонаезд в нём молчит.
Стоп-кадр (FREEZE) — то же самое: живой записи там нет, ездим камерой
по замершему кадру, и автонаезд, посчитанный по живой записи, туда не ставим.
"""
import os
import subprocess
import sys

import lib

P = lib.load_project()
G = lib.read_json("geometry.json")
PL = lib.read_json("plan.json")
W = lib.work_dir()
SRC = f"{W}/scr_cut.mp4"

AW, AH = 320, 180          # кадр анализа
CX, CY = 32, 18            # сетка: клетка 10×10 px
RATE = 5                   # выборок в секунду
NOISE = 3.0                # ниже — шум кодека, а не действие
HOT = 8.0                  # абсолютный порог «клетка изменилась»
BIG = 0.30                 # доля таких клеток, после которой сменилась вся картинка
TIGHT = 4                  # горит не больше стольких клеток → почти наверняка курсор
DEAD = 0.05                # мельче этого центр не двигаем
MAXPAN = 0.18              # дальше этого за сцену не едем — камера не должна бродить
EDGE = 0.06                # ближе к краю центр не пускаем — рамка упрётся

Z = getattr(P, "ZOOM", {})
ZMAX = float(Z.get("max", 1.35)) if Z is not None else 1.0
ZRATE = float(Z.get("rate", 0.05)) if Z is not None else 0.0
PUSH = float(Z.get("push", 6.0)) if Z is not None else 0.0
MIN_SCENE = float(Z.get("min_scene", 3.0)) if Z is not None else 0.0
MAX_MOVES = int(Z.get("moves", 6)) if Z is not None else 0
SKIP = set(Z.get("skip", [])) if Z is not None else set()
RESET = 0.04               # за столько секунд до конца сцены отъезжаем обратно


# ── что происходит на экране ────────────────────────────────────────────────
def samples():
    """Разница соседних кадров, разложенная по сетке. Один проход по файлу."""
    import numpy as np

    cmd = [lib.FF, "-v", "error", "-i", SRC, "-an", "-vf",
           f"fps={RATE},scale={AW}:{AH}:flags=area,format=gray",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = AW * AH
    prev, i, out = None, 0, []
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        cur = np.frombuffer(buf, np.uint8).reshape(AH, AW).astype(np.int16)
        if prev is not None:
            out.append(cell_stat(np, np.abs(cur - prev), i / RATE))
        prev, i = cur, i + 1
    p.stdout.close()
    p.wait()
    return out


def cell_stat(np, diff, t):
    """Два разных порога на один кадр — и это не лишнее.

    `spread` (сколько площади сменилось) считаем АБСОЛЮТНЫМ порогом. Соблазн
    взять для этого адаптивный порог кончается тем, что смену картинки перестаёт
    видно вообще: когда меняется весь экран, растёт и медиана, а вместе с ней
    порог — «горящих» клеток снова единицы. На проверочном ролике так и вышло,
    из трёх настоящих склеек нашлась одна.

    Центр тяжести, наоборот, ищем адаптивным порогом: шум записи зависит от
    битрейта и от того, что на экране. Фиксированный порог на тёмной теме
    терминала не находит ничего, а на светлом браузере находит везде.
    """
    cells = diff.reshape(CY, AH // CY, CX, AW // CX).mean(axis=(1, 3))
    spread = float((cells > HOT).mean())
    thr = max(NOISE, 4.0 * float(np.median(cells)))
    hot = cells > thr
    n = int(hot.sum())
    if not n:
        return dict(t=round(t, 3), e=0.0, spread=spread, x=None, y=None, tight=False)
    w = np.where(hot, cells - thr, 0.0)
    tot = float(w.sum())
    ys, xs = np.nonzero(hot)
    fx = float((w[hot] * (xs + 0.5)).sum() / tot / CX)
    fy = float((w[hot] * (ys + 0.5)).sum() / tot / CY)
    return dict(t=round(t, 3), e=tot, spread=spread,
                x=fx, y=fy, tight=n <= TIGHT)


# ── сцены и точки внимания ──────────────────────────────────────────────────
def wmedian(vals, ws):
    """Медиана, а не среднее: одна вспышка в углу не должна утаскивать центр."""
    half = sum(ws) / 2.0
    acc = 0.0
    for v, w in sorted(zip(vals, ws)):
        acc += w
        if acc >= half:
            return v
    return vals[-1]


def target(pts):
    """Куда смотреть. Точечные изменения весят вдвое — это почти всегда курсор.

    Вес берём как корень из энергии, а не саму энергию. Иначе одна вспышка
    перевешивает всё: открывшееся меню даёт разницу в сотню раз больше, чем
    едущий курсор, и центр сцены встаёт туда, где на один кадр мигнуло,
    вместо того места, где человек работал десять секунд.
    """
    if not pts:
        return None
    ws = [s["e"] ** 0.5 * (2.0 if s["tight"] else 1.0) for s in pts]
    x = wmedian([s["x"] for s in pts], ws)
    y = wmedian([s["y"] for s in pts], ws)
    return (min(1 - EDGE, max(EDGE, x)), min(1 - EDGE, max(EDGE, y)))


def scenes_of(block, S):
    """Режем блок по кадрам, где сменилась вся картинка."""
    marks = [block["a"]]
    marks += [s["t"] for s in S if block["a"] < s["t"] < block["b"]
              and s["spread"] >= BIG]
    marks.append(block["b"])
    return [(a, b) for a, b in zip(marks, marks[1:]) if b - a >= MIN_SCENE]


def zmax_for(mode):
    """Дальше этого наезд начнёт растягивать пиксели: в холсте их просто нет.

    Экран нормализован в холст SCR_W×SCR_H, а в кадре живёт коробкой поменьше.
    Отношение одного к другому — бесплатный запас на наезд. В раскладке A
    коробка меньше, поэтому и запас больше.
    """
    bw, bh = G[f"{mode}_SCR"][2], G[f"{mode}_SCR"][3]
    return round(min(ZMAX, G["SCR_W"] / bw, G["SCR_H"] / bh), 3)


def cam_keys(block, cams):
    """Камера по ключам: каждый ключ — переезд за dur с easeInOut и удержание.

    Узлы те же, что у автонаезда (smoothstep между соседними), поэтому одна
    и та же функция ведёт и zoompan в A/B, и композитор в S.
    """
    o = block["a"]
    # в маленьком окне SH до 2× — это ещё родные пиксели записи, не растяжение
    cmax = float(G.get("CAM_MAX_SH", 2.0) if block["m"] == "SH" else G.get("CAM_MAX", 1.8))
    zk, xk, yk = [[0.0, 1.0]], [[0.0, 0.5]], [[0.0, 0.5]]
    notes = []
    for c in cams:
        z = min(cmax, max(1.0, c["z"]))
        if c["z"] > cmax:
            notes.append(f"z {c['z']} срезан до {cmax}: дальше текст экрана мылится")
        bw = G[f"{block['m']}_SCR"][2]
        if z * bw > G["SCR_W"] * 1.02:
            notes.append(f"{lib.ms(c['t'])} z {z:.2f} растягивает экран "
                         f"в {z * bw / G['SCR_W']:.2f} раза — мелкий текст помылится")
        t0 = round(max(0.0, c["t"] - o), 3)
        if c["dur"] <= 0.05:
            # мгновенный сброс: ставится ровно на смену картинки (стоп-кадр,
            # переход на другую страницу) и потому не читается как рывок
            t0, t1 = round(max(0.0, t0 - 0.002), 3), t0
        else:
            t1 = round(t0 + max(0.3, c["dur"]), 3)
        for tr, v in ((zk, z), (xk, c["x"]), (yk, c["y"])):
            prev = tr[-1][1]
            if t0 <= tr[-1][0]:
                t0 = round(tr[-1][0] + 0.001, 3)
                t1 = max(t1, round(t0 + 0.001, 3))
            tr.append([t0, prev])
            tr.append([t1, round(v, 4)])
    return (zk, xk, yk), notes


def keys_for(block, scs, S, freezes=()):
    """Узлы наезда в локальном времени блока."""
    zmax = zmax_for(block["m"])
    moves = []
    for a, b in scs:
        pts = [s for s in S if a <= s["t"] < b and s["spread"] < BIG
               and s["e"] > NOISE]
        half = max(1, len(pts) * 55 // 100)
        c0, c1 = target(pts[:half]), target(pts[half:])
        if c0 is None:
            continue                       # экран замер — наезжать не на что
        d = 9.9 if c1 is None else abs(c1[0] - c0[0]) + abs(c1[1] - c0[1])
        if c1 is None or d < DEAD:
            c1 = c0                        # действие с места не ушло — камеру не двигаем
        elif d > MAXPAN:
            k = MAXPAN / d                 # ушло далеко — идём следом, но не через весь кадр
            c1 = (c0[0] + (c1[0] - c0[0]) * k, c0[1] + (c1[1] - c0[1]) * k)
        dur = b - a
        pdur = max(0.5, min(PUSH, dur - RESET * 3))
        z1 = round(min(zmax, 1.0 + ZRATE * pdur), 3)
        if z1 < 1.02:
            continue
        moves.append(dict(a=a, b=b, dur=dur, pdur=pdur, z=z1, c0=c0, c1=c1))
    # на стоп-кадре живой записи нет — автонаезд, посчитанный по ней, туда не ставим
    moves = [m for m in moves
             if not any(m["b"] > f["a"] and m["a"] < f["b"] for f in freezes)]
    moves.sort(key=lambda m: -m["dur"])
    moves = sorted(moves[:MAX_MOVES], key=lambda m: m["a"])

    o = block["a"]
    zk, xk, yk = [], [], []

    def add(track, t, v):
        # узлы должны строго возрастать: у соседних сцен конец одной совпадает
        # с началом другой, и такой узел надо сдвинуть, а не потерять
        t = round(t - o, 3)
        if track and t <= track[-1][0]:
            t = round(track[-1][0] + 0.001, 3)
        track.append([t, round(v, 4)])

    for m in moves:
        add(zk, m["a"], 1.0)
        add(zk, m["a"] + m["pdur"], m["z"])
        add(zk, m["b"] - RESET, m["z"])
        add(zk, m["b"], 1.0)
        add(xk, m["a"], m["c0"][0])
        add(yk, m["a"], m["c0"][1])
        add(xk, m["b"], m["c1"][0])
        add(yk, m["b"], m["c1"][1])
    return moves, (zk, xk, yk)


# ── ход ─────────────────────────────────────────────────────────────────────
def main():
    blocks = PL["blocks"]
    auto = not (Z is None or ZRATE <= 0)
    if not auto and not PL.get("cams"):
        lib.write_json("zoom.json", dict(blocks={}))
        print("наезд выключен (ZOOM = None в project.py) — экран показываем целиком")
        return
    if not os.path.exists(SRC):
        lib.die(f"нет {SRC} — сначала `montage.py cut`")
    if not any(t.get("screen") for t in P.TAKES):
        lib.write_json("zoom.json", dict(blocks={}))
        print("записи экрана нет ни у одного дубля — наезжать не на что")
        return

    S = samples() if auto else []
    if auto:
        print(f"· разобрал {len(S)} выборок ({RATE}/с), "
              f"смен картинки {sum(1 for s in S if s['spread'] >= BIG)}")
    else:
        print("· автонаезд выключен (ZOOM = None) — ставлю только камеру по ключам")

    cams = PL.get("cams", [])
    freezes = PL.get("freezes", [])
    out, total = {}, 0.0
    for i, b in enumerate(blocks):
        if b["m"] not in lib.SCREEN_MODES or i in SKIP:
            continue
        mine = [c for c in cams if b["a"] - 1e-6 <= c["t"] < b["b"]]
        frz = [f for f in freezes if f["block"] == i]
        if mine:
            (zk, xk, yk), notes = cam_keys(b, mine)
            out[str(i)] = dict(z=zk, fx=xk, fy=yk, manual=True)
            total += b["b"] - b["a"]
            print(f"  блок {i:02d} {b['m']}  камера по ключам: {len(mine)}"
                  + (f" · стоп-кадр с {lib.ms(frz[0]['a'])}" if frz else ""))
            for c in mine:
                print(f"     {lib.ms(c['t'])}  z {c['z']:.2f}  центр {c['x']:.2f}/{c['y']:.2f}"
                      f"  за {c['dur']:.1f} с")
            for n in notes:
                print(f"     ! {n}")
            continue
        if not auto:
            continue
        moves, (zk, xk, yk) = keys_for(b, scenes_of(b, S), S, frz)
        if not zk:
            continue
        out[str(i)] = dict(z=zk, fx=xk, fy=yk)
        total += sum(m["dur"] for m in moves)
        print(f"  блок {i:02d} {b['m']}  наездов {len(moves)}  "
              f"потолок z {zmax_for(b['m']):.2f}")
        for m in moves:
            print(f"     {lib.ms(m['a'])} → {lib.ms(m['b'])}  z 1.00→{m['z']:.2f}  "
                  f"центр {m['c0'][0]:.2f}/{m['c0'][1]:.2f}"
                  + ("" if m["c1"] == m["c0"] else
                     f" → {m['c1'][0]:.2f}/{m['c1'][1]:.2f}"))

    lib.write_json("zoom.json", dict(blocks=out))
    dur = PL["out_dur"]
    print(f"\nнаезд стоит на {total:.0f} с из {dur:.0f} ({total / dur * 100:.0f} %)")
    if not out:
        print("   ничего не нашлось: экран статичный или всё время меняется целиком")
    print("блок с лишним наездом гасится через ZOOM['skip'] = [номер блока]")
    print("дальше: montage.py build")


if __name__ == "__main__":
    sys.exit(main())
