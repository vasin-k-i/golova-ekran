#!/usr/bin/env python3
"""«Монтажёр» — монтаж длинного YouTube-ролика поверх чистого мастера golova-ekran.

Основа — человек во весь кадр, вставки на каждом смысловом шаге (скринкасты, документы
карточкой рядом или за человеком, би-роллы), текст прямо по видео, хук из ударных фраз
с переходами-кругами и полноэкранная отбивка. Правила стиля — GUIDE.md рядом.

Порядок (папка проекта = та же, где project.py основного пайплайна; MZ_PROJECT — другая):
  montazher.py init              шаблоны montazher.py + edl.py, шрифт Montserrat
  montazher.py words             пословные таймкоды каждого куска речи → work/words.json
  montazher.py audio             звук мастера речи → work/master_audio.wav (≈ −14 LUFS)
  montazher.py check             монтажный лист: покрытие, повторы, файлы, ритм, текст
  montazher.py texts [id …]      текст по видео (HyperFrames) → work/mz/texts/work/gfx
  montazher.py render probe|all  пробные отрывки (PROBE в edl.py) или весь ролик
  montazher.py hook              хук: план → слои текста → нарезка с кругами и музыкой
  montazher.py final             отбивка + склейка хук → отбивка → ролик → OUT
  montazher.py sheet [шаг]       контактный лист готового ролика (кадр каждые N с)
  montazher.py all               check → texts → render all → hook → final

До `words` нужен основной пайплайн до резки: segments → transcribe → repeats --approve → plan → cut
(work/plan.json, work/head_cut.mp4, work/audio_cut.wav).
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GEK = os.path.join(os.path.dirname(ROOT), "scripts", "montage.py")
PROJ = os.path.abspath(os.environ.get("MZ_PROJECT", os.getcwd()))
FONT_URLS = {
    "Montserrat[wght].ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
    "Montserrat-Italic[wght].ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Italic%5Bwght%5D.ttf",
}


def run(script, *args, env=None):
    e = dict(os.environ, MZ_PROJECT=PROJ, **(env or {}))
    r = subprocess.run([sys.executable, os.path.join(HERE, script), *args], env=e)
    if r.returncode:
        sys.exit(r.returncode)


def init():
    for name in ("montazher.py", "edl.py"):
        dst = os.path.join(PROJ, name)
        if os.path.exists(dst):
            print(f"· {name} уже есть — не трогаю")
        else:
            shutil.copy(os.path.join(ROOT, "templates", name), dst)
            print(f"+ {name}")
    fd = os.path.join(PROJ, "fonts")
    os.makedirs(fd, exist_ok=True)
    for name, url in FONT_URLS.items():
        p = os.path.join(fd, name)
        if not os.path.exists(p):
            r = subprocess.run(["curl", "-fsSL", "-o", p, url])
            print(("+ " if r.returncode == 0 else "✗ не скачал ") + f"fonts/{name}")
    print("дальше: words → audio → правишь edl.py → check → render probe")


def gfx(sub, module, ids):
    """Заглушка-проект для gfx.py основного скилла и рендер кусков."""
    d = os.path.join(PROJ, "work", "mz", sub)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "project.py"), "w", encoding="utf-8") as fh:
        fh.write("# создан montazher.py — не править, править edl.py / montazher.py\n"
                 f"import os, sys\nsys.path.insert(0, {HERE!r})\nos.environ.setdefault('MZ_PROJECT', {PROJ!r})\n"
                 f"from {module} import *  # noqa\n")
    env = dict(os.environ, GEK_PROJECT=d, MZ_PROJECT=PROJ)
    env.setdefault("GEK_HF_WORKERS", "1")         # многопоточный захват падает при нехватке памяти
    r = subprocess.run([sys.executable, GEK, "gfx", *ids], env=env)
    if r.returncode:
        sys.exit(r.returncode)


def words():
    """whisper-cli по каждому куску исходника (куски ≤ 90 с по границам вырезов) → слово и его секунда."""
    plan = json.load(open(os.path.join(PROJ, "work", "plan.json"), encoding="utf-8"))
    sys.path.insert(0, HERE)
    os.environ["MZ_PROJECT"] = PROJ
    import mzlib as L
    src = L.take_sources()
    model = os.environ.get("WHISPER_MODEL", os.path.expanduser("~/.whisper-models/ggml-large-v3.bin"))
    lang = os.environ.get("WHISPER_LANG", "ru")
    chunks, cur = [], None
    for k in plan["keeps"]:
        if cur and cur[0] == k["take"] and k["b"] - cur[1] <= 90:
            cur[2] = k["b"]
        else:
            cur = [k["take"], k["a"], k["b"]]
            chunks.append(cur)
    out_p = os.path.join(PROJ, "work", "words.json")
    out = json.load(open(out_p, encoding="utf-8")) if os.path.exists(out_p) else {}
    tmp = os.path.join(PROJ, "work", "mz", "words")
    os.makedirs(tmp, exist_ok=True)
    for i, (tk, a, b) in enumerate(chunks):
        key = f"{tk}@{a:.1f}"
        if key in out:
            continue
        a0 = max(0.0, a - 0.15)
        wav = os.path.join(tmp, f"{tk}_{a:.1f}.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a0:.3f}", "-to", f"{b + 0.15:.3f}", "-i", src[tk],
                        "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
        subprocess.run(["whisper-cli", "-m", model, "-l", lang, "-ml", "1", "-sow", "-oj", "-of", wav[:-4], "-f", wav, "-np"],
                       check=True, capture_output=True)
        js = json.load(open(wav[:-4] + ".json", encoding="utf-8"))
        ws = []
        for seg in js.get("transcription", []):
            txt = seg["text"]
            t = round(a0 + seg["offsets"]["from"] / 1000, 2)
            if not txt.strip():
                continue
            if ws and not txt.startswith(" "):
                ws[-1][1] += txt.strip()                   # кусок слова — к предыдущему
            else:
                ws.append([t, txt.strip()])
        out[key] = ws
        print(f"  {i + 1}/{len(chunks)}  {key}: {len(ws)} слов", flush=True)
        json.dump(out, open(out_p, "w", encoding="utf-8"), ensure_ascii=False)
    print("слова →", out_p, "· помни: таймкоды whisper сдвинуты на 0,1–0,3 с, края вставок сверяй глазами")


def audio():
    sys.path.insert(0, HERE)
    os.environ["MZ_PROJECT"] = PROJ
    import mzlib as L
    src = os.path.join(PROJ, "work", "audio_cut.wav")
    if not os.path.exists(src):
        L.die("нет work/audio_cut.wav — сначала `montage.py cut` основного пайплайна")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-af", L.AUDIO_CHAIN, "-ar", "48000", "-ac", "2",
                    "-c:a", "pcm_s16le", L.AUDIO], check=True)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", L.AUDIO, "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    lufs = [ln for ln in r.stderr.splitlines() if ln.strip().startswith("I:")]
    print("звук →", L.AUDIO, "·", lufs[-1].strip() if lufs else "", "(цель ≈ −14 LUFS; иначе правь volume в AUDIO_CHAIN)")


def sheet(step="10"):
    sys.path.insert(0, HERE)
    os.environ["MZ_PROJECT"] = PROJ
    import mzlib as L
    base, _ = os.path.splitext(L.OUT)
    dst = f"{base} — лист.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", L.OUT, "-vf",
                    f"fps=1/{step},scale=384:-2,drawtext=text='%{{pts\\:hms}}':x=8:y=8:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.5,tile=6x8",
                    "-frames:v", "1", dst], check=True)
    print("лист →", dst)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "init":
        init()
    elif cmd == "words":
        words()
    elif cmd == "audio":
        audio()
    elif cmd == "check":
        run("mz_check.py")
    elif cmd == "texts":
        gfx("texts", "mz_texts", args)
    elif cmd == "render":
        run("mz_render.py", *(args or ["probe"]))
    elif cmd == "hook":
        run("mz_hook.py", "plan")
        gfx("hook", "mz_hookgfx", [])
        run("mz_hook.py", "render")
    elif cmd == "final":
        run("mz_hook.py", "final")
    elif cmd == "sheet":
        sheet(*args)
    elif cmd == "all":
        run("mz_check.py")
        gfx("texts", "mz_texts", [])
        run("mz_render.py", "all")
        sys.path.insert(0, HERE)
        os.environ["MZ_PROJECT"] = PROJ
        import mzlib as L
        if (getattr(L.C, "HOOK", None) or {}).get("phrases"):
            run("mz_hook.py", "plan")
            gfx("hook", "mz_hookgfx", [])
            run("mz_hook.py", "render")
        run("mz_hook.py", "final")
    else:
        print(f"не знаю команду {cmd}\n{__doc__}")
        sys.exit(2)


if __name__ == "__main__":
    main()
