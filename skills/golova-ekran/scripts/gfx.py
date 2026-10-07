#!/usr/bin/env python3
"""Шаг 7б (необязательный) — графика HyperFrames: HTML/CSS/JS → PNG с альфой.

Встроенная графика скилла — PIL-панели, карточки T и плашки (design.py):
работает везде и без лишних зависимостей. Этот шаг — для тех, у кого стоит
HyperFrames (нужен node ≥ 22): тогда графику можно верстать как веб-страницу —
схемы, счётчики, пункты по слову, «текст за головой» — и анимировать GSAP.

Каждый кусок — отдельная композиция в project.py:

    GFX = [dict(id="g01", take="01", at=12.4, dur=6.9, layer="fg",
                html='<div class="chip" id="c" style="left:96px;top:120px">…</div>',
                css="", js='HF.pop(tl, "#c", 0.2); HF.out(tl, "#c", 6.4);',
                sfx=[(0.2, "click")])]

  layer="bg" — кусок встаёт МЕЖДУ фоном и человеком (нужен `montage.py matte`),
  layer="fg" — поверх всего. Время в js — от начала куска.

Что делает шаг:
  · собирает каждый кусок в свою папку work/gfx/src/<id>/ (шрифты — локальные
    файлы, gsap — локальный файл; ничего не тянется с CDN во время рендера);
  · гоняет `hyperframes check` и НЕ рендерит кусок, у которого текст вылезает
    из рамки или уезжает за кадр — печатает, что и на сколько;
  · рендерит `--format png-sequence` в work/gfx/<id>/ (кадры RGBA).

⚠️ Непрозрачный кадр HyperFrames пишет в PNG БЕЗ альфы. Это не «пустой кадр»,
а альфа 1 — композитор так и считает, иначе полноэкранные карточки пропадают.

  montage.py gfx            все куски (готовые и не менявшиеся пропускает)
  montage.py gfx g03 g07    только эти
  GFX_CHECK = False         в project.py — рендерить без проверки (не советую)
"""
import hashlib
import json
import os
import shutil
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import lib

P = lib.load_project()
W = lib.work_dir()
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "assets", "gfx")
SRC = f"{W}/gfx/src"
SHARED = f"{SRC}/_shared"
FPS = P.FPS
GSAP_URL = "https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js"
CACHE = os.path.expanduser("~/.cache/golova-ekran")


def gsap_file():
    """gsap.min.js — локальным файлом: рендер не должен зависеть от сети."""
    env = os.environ.get("GEK_GSAP")
    if env and os.path.exists(env):
        return env
    cached = os.path.join(CACHE, "gsap.min.js")
    if os.path.exists(cached):
        return cached
    os.makedirs(CACHE, exist_ok=True)
    print(f"· gsap ещё не скачан — беру один раз в {cached}")
    try:
        urllib.request.urlretrieve(GSAP_URL, cached)
    except Exception as e:
        lib.die(f"не скачал gsap ({e}). Положи gsap.min.js руками и укажи "
                "GEK_GSAP=/путь/gsap.min.js")
    return cached


def font_face(family, path, weight="400"):
    ext = os.path.splitext(path)[1].lower()
    fmt = {".ttf": "truetype", ".otf": "opentype", ".woff2": "woff2",
           ".woff": "woff"}.get(ext)
    if not fmt:
        return ""
    name = f"{family.replace(' ', '_')}_{weight.replace(' ', '-')}{ext}"
    shutil.copy(path, f"{SHARED}/fonts/{name}")
    return (f'@font-face{{font-family:"{family}";src:url("fonts/{name}") '
            f'format("{fmt}");font-weight:{weight};font-style:normal}}\n')


def shared():
    """Общие файлы кусков: стиль, помощники, gsap и шрифты — всё локально.

    Шрифты — из GFX_FONTS в project.py (display, text, text_bold, mono: пути
    к .ttf/.otf/.woff2), чего нет — берётся тем же шрифтом, что рисует PIL.
    Без своих @font-face компилятор HyperFrames сам подтягивает шрифт из
    Google Fonts — и в кадре оказывается не тот шрифт, что задумывали.
    """
    os.makedirs(f"{SHARED}/fonts", exist_ok=True)
    fonts = dict(display=lib.font_path(True), text=lib.font_path(False),
                 text_bold=lib.font_path(True), mono=lib.font_mono())
    fonts.update({k: v for k, v in (getattr(P, "GFX_FONTS", None) or {}).items() if v})
    css = (font_face("GEK Display", fonts["display"], "100 900") +
           font_face("GEK Text", fonts["text"], "400") +
           font_face("GEK Text", fonts["text_bold"], "700") +
           font_face("GEK Mono", fonts["mono"], "400"))
    with open(f"{SHARED}/fonts.css", "w", encoding="utf-8") as fh:
        fh.write(css)
    shutil.copy(f"{ASSETS}/shared.css", f"{SHARED}/shared.css")
    shutil.copy(f"{ASSETS}/lib.js", f"{SHARED}/lib.js")
    shutil.copy(gsap_file(), f"{SHARED}/gsap.min.js")
    return fonts


def build_piece(p, tpl):
    acc = "#%02X%02X%02X" % tuple(getattr(P, "ACCENT", (232, 84, 30)))
    d = f"{SRC}/{p['id']}"
    os.makedirs(d, exist_ok=True)
    html = tpl.format(id=p["id"], dur=p["dur"], acc=acc, css=p.get("css", ""),
                      html=p.get("html", ""), js=p.get("js", ""))
    with open(f"{d}/index.html", "w", encoding="utf-8") as fh:
        fh.write(html)
    for name in ("fonts.css", "fonts", "shared.css", "lib.js", "gsap.min.js"):
        link = f"{d}/{name}"
        if os.path.islink(link) or os.path.isfile(link):
            os.remove(link)
        elif os.path.isdir(link):
            shutil.rmtree(link)
        os.symlink(f"../_shared/{name}", link)
    key = hashlib.sha1((html + open(f"{SHARED}/fonts.css").read()).encode()).hexdigest()
    return d, key


def check(p, d):
    """Вылезающий текст, перекрытия, уход за кадр — до рендера, а не на мастере."""
    r = lib.hf_run(["check", d, "--json", "--no-contrast", "--samples", "12",
                    "--at-transitions"])
    try:
        rep = json.loads(r.stdout[r.stdout.index("{"):])
    except Exception:
        return [f"check не отработал: {(r.stderr or r.stdout)[-400:]}"]
    bad, seen = [], set()
    for sec in ("layout", "runtime"):
        for x in rep.get(sec, {}).get("findings", []):
            if x.get("severity") != "error" and "overflow" not in x.get("code", ""):
                continue
            txt = x.get("text") or x.get("selector") or ""
            if (x.get("code"), txt) in seen:        # одно и то же на разных секундах
                continue
            seen.add((x.get("code"), txt))
            bad.append(f"{x.get('code')} на {x.get('time', '?')} с: «{txt[:60]}» — "
                       f"{x.get('fixHint') or x.get('message')}")
    return bad


def render(p, d, key):
    out = f"{W}/gfx/{p['id']}"
    stamp = f"{out}/.key"
    if os.path.exists(stamp) and open(stamp).read() == key:
        return p["id"], len([f for f in os.listdir(out) if f.endswith(".png")]), "готов"
    if getattr(P, "GFX_CHECK", True):
        bad = check(p, d)
        if bad:
            return p["id"], 0, "НЕ ПРОШЁЛ check:\n      " + "\n      ".join(bad)
    shutil.rmtree(out, ignore_errors=True)
    r = lib.hf_run(["render", d, "--format", "png-sequence", "-o", out,
                    "-f", str(FPS), "--quiet"])
    if r.returncode:
        return p["id"], 0, f"рендер упал: {(r.stderr or r.stdout)[-600:]}"
    n = len([f for f in os.listdir(out) if f.endswith(".png")])
    with open(stamp, "w") as fh:
        fh.write(key)
    return p["id"], n, "отрисован"


def main():
    pieces = getattr(P, "GFX", [])
    if not pieces:
        print("графики HyperFrames нет (GFX в project.py пуст) — пропускаю")
        return
    if not lib.node_bin():
        print("✗ HyperFrames нужен node ≥ 22 — не нашёл. Графика GFX пропущена;")
        print("  панели, карточки T и плашки скилла (PIL) работают и без него.")
        print("  Поставить: brew install node@22 (или задай GEK_NODE_BIN=/путь/к/bin)")
        return
    only = set(sys.argv[1:])
    todo = [p for p in pieces if not only or p["id"] in only]
    for p in todo:
        if "dur" not in p:
            lib.die(f"у куска {p['id']} нет dur — сколько секунд он идёт")
    shared()
    with open(f"{ASSETS}/piece.html", encoding="utf-8") as fh:
        tpl = fh.read()
    built = [(p,) + build_piece(p, tpl) for p in todo]
    with ThreadPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(lambda x: render(*x), built))
    fail = 0
    for pid, n, msg in res:
        ok = n > 0
        fail += not ok
        print(f"  {'✓' if ok else '✗'} {pid:16s} {n:4d} кадр  {msg}", flush=True)
    if fail:
        lib.die(f"не готово кусков: {fail}. Поправь вёрстку (ширина по тексту, "
                "перенос вместо nowrap) и запусти `montage.py gfx` снова")
    print("дальше: montage.py matte (если есть куски layer=\"bg\"), потом build")


if __name__ == "__main__":
    main()
