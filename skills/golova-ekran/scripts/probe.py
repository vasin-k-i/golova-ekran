#!/usr/bin/env python3
"""Разведка материала: синхронизация, окна показа, контактные листы, черновик конфига.

Это единственный шаг, который что-то УГАДЫВАЕТ. Всё остальное потом считает
по написанному, поэтому здесь важно не соврать: каждое число печатается вместе
с тем, насколько ему можно верить.

Что делает:
  · геометрия и fps каждого файла, с учётом поворота (телефон пишет landscape
    с флагом поворота — ffmpeg разворачивает сам, но знать об этом надо);
  · сдвиг экрана относительно головы — кросс-корреляцией огибающих, отдельно
    в начале, середине и конце, чтобы поймать расхождение хода часов;
  · окна, где на экране ИГРАЕТ видео (см. references/02-cutting.md — звук
    плеера тише порога тишины, и обычная резка выносит показ целиком);
  · контактные листы: по ним человек или агент выбирает кроп рабочего окна;
  · черновик project.py со всеми найденными числами.
"""
import argparse
import os
import subprocess

import lib

SR = 16000
HOP = 40                      # 2,5 мс на отсчёт огибающей — хватает на сдвиг
ENV_HOP = 1600                # 100 мс на отсчёт для профиля громкости


def envelope(path, sr=SR, hop=HOP, ss=None, t=None):
    import numpy as np
    cmd = [lib.FF, "-v", "error"]
    if ss is not None:
        cmd += ["-ss", f"{ss}"]
    if t is not None:
        cmd += ["-t", f"{t}"]
    cmd += ["-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    n = len(x) // hop * hop
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    e = np.abs(x[:n].reshape(-1, hop)).mean(1)
    return (e - e.mean()) / (e.std() + 1e-9)


def lag(a, b, hop=HOP, sr=SR):
    """Где кусок a сидит внутри b. Возвращает (сдвиг в секундах, совпадение)."""
    import numpy as np
    if len(a) == 0 or len(b) == 0:
        return 0.0, 0.0
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    c = np.fft.irfft(np.fft.rfft(b, n) * np.conj(np.fft.rfft(a, n)), n)
    c = np.concatenate([c[-len(a):], c[:len(b)]])
    i = int(np.argmax(c))
    # Нормируем на кусок b ТОЙ ЖЕ длины, что и a, а не на весь файл: иначе
    # длинный экран занижает совпадение в разы и всё выглядит ненадёжным.
    k = i - len(a)
    seg = b[max(0, k):max(0, k) + len(a)]
    if len(seg) < len(a):
        seg = np.pad(seg, (0, len(a) - len(seg)))
    peak = float(c[i] / (np.sqrt((a ** 2).sum() * (seg ** 2).sum()) + 1e-9))
    return k * hop / sr, peak


def sync(head, screen, dur):
    """Сдвиг экрана относительно головы, проверенный в трёх точках.

    Экран = голова + offset. Меряем на трёх окнах: если числа расходятся
    больше чем на 40 мс — у дорожек разный ход часов, константа не спасёт.
    """
    b = envelope(screen)
    res = []
    for name, ss, t in (("начало", 0, min(60, dur)),
                        ("середина", max(0, dur / 2 - 30), min(60, dur)),
                        ("конец", max(0, dur - 60), 60)):
        a = envelope(head, ss=ss, t=t)
        off, peak = lag(a, b)
        res.append((name, round(off - ss, 3), round(peak, 3)))
    offs = [o for _, o, _ in res]
    drift = max(offs) - min(offs)
    return res, round(sum(offs) / len(offs), 3), round(drift, 3)


def levels(path):
    """Профиль громкости в окнах по 100 мс, в дБ."""
    import numpy as np
    raw = subprocess.run([lib.FF, "-v", "error", "-i", path, "-vn", "-ac", "1",
                          "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    n = len(x) // ENV_HOP * ENV_HOP
    if n == 0:
        return np.zeros(0)
    return 20 * np.log10(np.sqrt((x[:n].reshape(-1, ENV_HOP) ** 2).mean(1)) + 1e-12)


def find_play(db, gap=60.0, min_len=3.0):
    """Окна, где на экране играет видео.

    Опорные уровни берём из самой дорожки: пол комнаты — 5-й перцентиль,
    речь — 75-й. Полоса плеера лежит между ними. Засеваем секунды, где полоса
    держится и речи нет, потом склеиваем засевы через паузы на комментарий.
    """
    import numpy as np
    if len(db) < 100:
        return [], None
    floor, speech = np.percentile(db, 5), np.percentile(db, 75)
    lo, hi = floor + 8, speech - 8
    if hi - lo < 6:                       # полосы нет — показа в дубле нет
        return [], (round(lo, 1), round(hi, 1))
    band = (db >= lo) & (db < hi)
    loud = db >= hi
    k = 30                                # окно 3 с
    seeds = []
    for i in range(0, len(db) - k):
        w_band, w_loud = band[i:i + k].mean(), loud[i:i + k].mean()
        if w_band >= 0.5 and w_loud <= 0.2:
            seeds.append(i * 0.1)
    if not seeds:
        return [], (round(lo, 1), round(hi, 1))
    wins, start, prev = [], seeds[0], seeds[0]
    for s in seeds[1:]:
        if s - prev > gap:
            wins.append((start, prev + 3.0))
            start = s
        prev = s
    wins.append((start, prev + 3.0))
    wins = [(round(max(0, a - 0.5), 1), round(min(len(db) * 0.1, b + 0.5), 1))
            for a, b in wins if b - a >= min_len]
    return wins, (round(lo, 1), round(hi, 1))


def sheet(path, out, count=9, crop=None, width=520):
    """Контактный лист — по нему выбирают кроп рабочего окна."""
    from PIL import Image, ImageDraw
    d = lib.duration(path)
    tmp = os.path.join(lib.work_dir(), "_sheet")
    os.makedirs(tmp, exist_ok=True)
    ims = []
    for i in range(count):
        t = d * (i + 0.5) / count
        f = os.path.join(tmp, f"{i:02d}.jpg")
        vf = (f"{crop}," if crop else "") + f"scale={width}:-2"
        lib.run([lib.FF, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", path,
                 "-frames:v", "1", "-vf", vf, f])
        ims.append((t, Image.open(f).convert("RGB")))
    w, h = ims[0][1].size
    cols = 3
    rows = (len(ims) + cols - 1) // cols
    s = Image.new("RGB", (w * cols, h * rows), (12, 12, 12))
    dr = ImageDraw.Draw(s)
    for i, (t, im) in enumerate(ims):
        x, y = (i % cols) * w, (i // cols) * h
        s.paste(im, (x, y))
        dr.text((x + 8, y + 6), lib.ms(t), fill=(255, 180, 60))
    s.save(out, quality=84)
    return out


def draft(pairs, results):
    """Черновик project.py — с найденными числами и местами под решения."""
    lines = ['"""Конфиг ролика. Числа проставлены `montage.py probe`.',
             '',
             'Решения, которые probe за тебя не примет:',
             '  crop     — рабочее окно на записи экрана (смотри work/probe/*_screen.jpg)',
             '  MODES    — какая раскладка где (заполняется после расшифровки)',
             '  DROP     — мусорные сегменты (после `montage.py transcribe`)',
             '"""',
             '',
             'OUT_NAME = "Ролик"',
             f'FPS = {results[0]["fps"]}',
             '',
             'TAKES = [']
    for p, r in zip(pairs, results):
        lines.append(f'    dict(id="{r["id"]}",')
        lines.append(f'         head={r["head"]!r},')
        if r.get("screen"):
            lines.append(f'         screen={r["screen"]!r},')
            lines.append(f'         offset={r["offset"]},'
                         f'   # совпадение {r["peak"]}, расхождение {r["drift"]} с')
            cw = r["screen_w"]
            ch = r["screen_h"]
            lines.append(f'         crop=({cw}, {ch}, 0, 0),'
                         f'   # ← подгони под рабочее окно')
        if r["play"]:
            lines.append(f'         play={r["play"]},'
                         f'   # на экране играет видео — режем тихим порогом')
        else:
            lines.append('         play=[],')
        lines.append('    ),')
    lines += [']', '',
              '# Раскладки: A экран карточкой + голова колонкой · B экран крупно',
              '#            D инфографика вместо экрана · C голова во весь кадр',
              '# (такт, от, до, режим, имя панели или None) — время в исходнике дубля',
              'MODES = {']
    for r in results:
        lines.append(f'    "{r["id"]}": [(0, 1e9, "A", None)],')
    lines += ['}', '',
              '# Заполняется после `montage.py transcribe` — см. work/transcript.txt',
              'DROP = []            # номера мусорных сегментов',
              'TRIM = []            # адресные вырезы: ("id дубля", от, до) в секундах',
              'BW = None            # оговорка-пример: номер сегмента, красим в ч/б',
              '',
              'PANELS = {}          # инфографика: имя → dict(eyebrow=…, w1=…, w2=…, items=[…])',
              'INSERTS = []         # окна-вставки: dict(n=…, take=…, at=…, dur=…, lay=…, src=…, label=…)',
              '',
              '# Наезд за курсором на записи экрана — ищется сам, см. references/06-zoom.md',
              "ZOOM = dict(max=1.35, rate=0.05, push=6.0, min_scene=3.0, moves=6, skip=[])",
              '']
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="разведка материала")
    ap.add_argument("--pair", nargs=2, action="append", metavar=("HEAD", "SCREEN"),
                    help="дубль: файл с головой и запись экрана")
    ap.add_argument("--head-only", action="append", metavar="HEAD",
                    help="дубль без записи экрана")
    ap.add_argument("--no-sheets", action="store_true")
    a = ap.parse_args()
    items = [(h, s) for h, s in (a.pair or [])] + [(h, None) for h in (a.head_only or [])]
    if not items:
        lib.die("нечего смотреть: задай --pair ГОЛОВА ЭКРАН или --head-only ФАЙЛ")

    pdir = os.path.join(lib.work_dir(), "probe")
    os.makedirs(pdir, exist_ok=True)
    results = []
    for i, (head, screen) in enumerate(items, 1):
        for f in (head, screen):
            if f and not os.path.exists(f):
                lib.die(f"нет файла {f}")
        tid = f"{i:02d}"
        hi = lib.video_info(head)
        hd = lib.duration(head)
        if not lib.has_audio(head):
            lib.die(f"в {head} нет звука — с этой дорожки берётся весь звук ролика")
        print(f"\n── дубль {tid} ─────────────────────────────────")
        print(f"  голова  {os.path.basename(head)}  {hi['w']}×{hi['h']}  "
              f"{hi['fps']:.3f} fps  {lib.ms(hd)}"
              + (f"  (поворот {hi['rotation']}°)" if hi["rotation"] else ""))
        r = dict(id=tid, head=os.path.abspath(head), fps=int(round(hi["fps"])),
                 play=[], screen=None)
        if screen:
            si = lib.video_info(screen)
            sd = lib.duration(screen)
            print(f"  экран   {os.path.basename(screen)}  {si['w']}×{si['h']}  "
                  f"{si['fps']:.3f} fps  {lib.ms(sd)}")
            if lib.has_audio(screen):
                trio, off, drift = sync(head, screen, hd)
                for name, o, peak in trio:
                    print(f"     {name:9s} экран = голова {o:+.3f} с   совпадение {peak:.2f}")
                best = max(p for _, _, p in trio)
                verdict = ("надёжно" if best >= 0.6 else
                           "слабовато — проверь глазами по хлопку или щелчку мыши")
                print(f"     принято: {off:+.3f} с · расхождение по дорожке "
                      f"{drift * 1000:.0f} мс · {verdict}")
                if drift > 0.04:
                    print("     ! дорожки идут с разной скоростью — константы мало, "
                          "режь дубль на части или тяни звук")
                r.update(offset=off, peak=best, drift=drift)
            else:
                print("     в записи экрана нет звука — сдвиг не вычислить, ставлю 0")
                r.update(offset=0.0, peak=0.0, drift=0.0)
            r.update(screen=os.path.abspath(screen), screen_w=si["w"], screen_h=si["h"])

        db = levels(head)
        wins, band = find_play(db)
        if band:
            print(f"  полоса плеера {band[0]:.0f}…{band[1]:.0f} дБ")
        if wins:
            total = sum(b - a for a, b in wins)
            print(f"  ПОКАЗ С ЭКРАНА: {len(wins)} окно(а), {total:.0f} с — "
                  f"{', '.join(f'{lib.ms(x)}–{lib.ms(y)}' for x, y in wins)}")
            print("     внутри режем тихим порогом, иначе показ вырежется целиком")
        else:
            print("  показа с экрана не нашёл")
        r["play"] = wins
        results.append(r)

        if not a.no_sheets:
            sheet(head, f"{pdir}/{tid}_head.jpg")
            if screen:
                sheet(screen, f"{pdir}/{tid}_screen.jpg")

    path = os.path.join(lib.project_dir(), "project.py")
    if os.path.exists(path):
        path += ".new"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(draft(items, results))
    print(f"\nчерновик конфига: {path}")
    if not a.no_sheets:
        print(f"контактные листы: {pdir}/ — по ним выбери crop рабочего окна")


if __name__ == "__main__":
    main()
