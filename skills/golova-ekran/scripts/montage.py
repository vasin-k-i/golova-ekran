#!/usr/bin/env python3
"""Единая точка входа. Все шаги — отсюда.

  montage.py check                       что стоит на машине, чего не хватает
  montage.py scan --dir ПАПКА            что за файлы лежат: длина, гео, звук
  montage.py probe --pair ГОЛОВА ЭКРАН   сдвиг, окна показа, черновик конфига
  montage.py segments                    резка тишины
  montage.py transcribe                  расшифровка каждого сегмента отдельно
  montage.py repeats                     что режем дословно + кандидаты в повторы
  montage.py repeats --approve "кто, когда"   отметка: список согласован человеком
  montage.py screenmap                   что на экране, пока он говорит: фраза → кадр
  montage.py plan                        что режем и чем оформляем
  montage.py design                      маски, тени, панели инфографики
  montage.py inserts                     клипы вставок и плашки
  montage.py cut                         резка дорожек кадр в кадр
  montage.py zoom                        наезд за курсором и камера по ключам на экране
  montage.py gfx [ID ...]                графика HyperFrames (необязательно, нужен node ≥ 22)
  montage.py matte                       маска человека под «текст за головой» (необязательно)
  montage.py preview 12.5,40             контрольные кадры студии до сборки → work/check/
  montage.py build [N ...]               сборка кадра (без номеров — все блоки)
  montage.py final                       звук (+ музыка и SFX, если заданы) и мастер
  montage.py frames                      сетки кадров на каждой смене плана и наезде
  montage.py cover                       обложка
  montage.py all                         design → inserts → cut → zoom → gfx → matte →
                                         build → final → frames

build и final не собирают мастер без отметки `repeats --approve`. Обход — только
явно: `--skip-repeats` (мастер получит в имени «БЕЗ ЧИСТКИ ПОВТОРОВ»).

Конфиг ролика — project.py в текущей папке (или в GEK_PROJECT).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def run_step(name, args=()):
    """Шаги запускаем не тем, чем запустили нас.

    Половина шагов тянет pillow и numpy, а `python3` из PATH на маке обычно
    homebrew-овский, где их нет. Иначе пайплайн падает трейсбеком на импорте
    вместо внятного «поставь вот это».
    """
    import lib
    py = lib.pick_python()
    if not py:
        lib.die("не нашёл python с pillow и numpy. Поставь их "
                "(`/usr/bin/pip3 install --user pillow numpy`) "
                "или укажи нужный интерпретатор через GEK_PYTHON")
    r = subprocess.run([py, os.path.join(HERE, f"{name}.py"), *args])
    if r.returncode:
        raise SystemExit(r.returncode)


def scan(argv):
    import argparse
    import lib
    ap = argparse.ArgumentParser(prog="montage.py scan")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--ext", default="mov,mp4,mkv,m4v,webm,avi")
    a = ap.parse_args(argv)
    exts = tuple("." + e.strip().lower() for e in a.ext.split(","))
    files = sorted(os.path.join(a.dir, f) for f in os.listdir(a.dir)
                   if f.lower().endswith(exts))
    if not files:
        lib.die(f"в {a.dir} не нашёл видеофайлов ({a.ext})")
    print(f"{'файл':46s} {'размер кадра':>13s} {'fps':>7s} {'длина':>9s}  звук")
    for f in files:
        try:
            i = lib.video_info(f)
            d = lib.duration(f)
        except Exception:
            print(f"{os.path.basename(f)[:46]:46s}  — не читается")
            continue
        rot = "↻" if i["rotation"] else " "
        print(f"{os.path.basename(f)[:46]:46s} {i['w']:>6d}×{i['h']:<6d}{rot}"
              f"{i['fps']:>7.2f} {lib.ms(d):>9s}  "
              f"{'есть' if lib.has_audio(f) else 'НЕТ'}")
    print("\nПары для probe подбирай по длине и времени съёмки: у головы и экрана")
    print("длительность отличается на секунды, а не на минуты. Голова — та дорожка,")
    print("где звук чище (обычно телефон), с неё берётся весь звук ролика.")


def check(argv):
    subprocess.run(["bash", os.path.join(HERE, "check_deps.sh"), *argv])


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "scan":
        return scan(rest)
    if cmd == "check":
        return check(rest)
    if cmd == "all":
        flags = [x for x in rest if x == "--skip-repeats"]
        for s in ("design", "inserts", "cut", "zoom", "gfx", "matte", "blocks",
                  "final", "frames"):
            print(f"\n═══ {s} ═══", flush=True)
            run_step(s, flags if s in ("blocks", "final") else ())
        return
    if cmd == "preview":
        return run_step("compose", ["--preview", *rest])
    alias = {"build": "blocks"}
    step = alias.get(cmd, cmd)
    if step not in ("probe", "segments", "transcribe", "repeats", "screenmap", "plan", "design",
                    "inserts", "cut", "zoom", "gfx", "matte", "blocks", "final",
                    "frames", "cover"):
        print(__doc__)
        raise SystemExit(f"не знаю команду «{cmd}»")
    run_step(step, rest)


if __name__ == "__main__":
    main()
