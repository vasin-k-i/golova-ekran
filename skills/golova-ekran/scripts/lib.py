#!/usr/bin/env python3
"""Общее для всех шагов: конфиг проекта, вызовы ffmpeg, шрифты.

Конфиг ролика лежит рядом с материалом в файле project.py и подхватывается
отсюда. Пути к ffmpeg берём из PATH, но даём переопределить через окружение —
на маке homebrew кладёт их не туда, где их ищет системный python.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys

FF = os.environ.get("FFMPEG", shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg")
FP = os.environ.get("FFPROBE", shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe")

_PY = None


def pick_python():
    """Интерпретатор, у которого РЕАЛЬНО есть pillow и numpy.

    Верить `python3` из PATH нельзя. На маке первым обычно стоит
    homebrew-овский, а пакетов в нём нет и не будет: он «externally managed»
    и на `pip3 install` отвечает отказом. Зато системный /usr/bin/python3
    часто уже укомплектован. Поэтому не гадаем, а проверяем импортом.

    Пусто — значит pillow и numpy не нашлись нигде; ставить их надо в тот
    python, который потом задать через GEK_PYTHON.
    """
    global _PY
    if _PY is not None:
        return _PY or None
    env = os.environ.get("GEK_PYTHON")
    names = ("python3", "python3.14", "python3.13", "python3.12",
             "python3.11", "python3.10", "python3.9")
    cands = [env, sys.executable] + [shutil.which(n) for n in names] + \
            ["/usr/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
    seen = set()
    for p in cands:
        if not p or p in seen or not os.path.exists(p):
            continue
        seen.add(p)
        if subprocess.run([p, "-c", "import PIL, numpy"],
                          capture_output=True).returncode == 0:
            _PY = p
            return p
    _PY = ""
    return None


# ── конфиг ──────────────────────────────────────────────────────────────────
def project_dir():
    return os.path.abspath(os.environ.get("GEK_PROJECT", os.getcwd()))


def work_dir():
    d = os.path.join(project_dir(), "work")
    os.makedirs(d, exist_ok=True)
    return d


def out_dir():
    d = os.path.join(project_dir(), "out")
    os.makedirs(d, exist_ok=True)
    return d


def load_project():
    p = os.path.join(project_dir(), "project.py")
    if not os.path.exists(p):
        die(f"нет {p}. Сначала `montage.py probe` — он его и напишет.")
    spec = importlib.util.spec_from_file_location("project", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for t in m.TAKES:
        t.setdefault("play", [])
        t.setdefault("screen", None)
        t.setdefault("offset", 0.0)
        t.setdefault("crop", None)
        t.setdefault("head_from_screen", None)
    return m


def read_json(name):
    with open(os.path.join(work_dir(), name), encoding="utf-8") as fh:
        return json.load(fh)


def write_json(name, data):
    with open(os.path.join(work_dir(), name), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def die(msg):
    sys.stderr.write(f"✗ {msg}\n")
    raise SystemExit(1)


# ── ffmpeg ──────────────────────────────────────────────────────────────────
def run(cmd, quiet=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write("✗ " + " ".join(str(c) for c in cmd[:14]) + " …\n")
        sys.stderr.write(r.stderr[-2500:] + "\n")
        raise RuntimeError("ffmpeg")
    return r


def sh(cmd):
    """Без падения — когда нужен именно stderr (silencedetect, volumedetect)."""
    return subprocess.run(cmd, capture_output=True, text=True)


def duration(f):
    return float(run([FP, "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=nw=1:nk=1", f]).stdout)


def nframes(f):
    out = run([FP, "-v", "error", "-select_streams", "v:0", "-count_frames",
               "-show_entries", "stream=nb_read_frames",
               "-of", "default=nw=1:nk=1", f]).stdout.strip()
    return int(out) if out.isdigit() else 0


def video_info(f):
    """Ширина/высота УЖЕ с учётом поворота — ffmpeg разворачивает сам."""
    out = run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries",
               "stream=width,height,r_frame_rate:stream_side_data=rotation",
               "-of", "json", f]).stdout
    d = json.loads(out)["streams"][0]
    w, h = int(d["width"]), int(d["height"])
    rot = 0
    for sd in d.get("side_data_list", []):
        if "rotation" in sd:
            rot = int(sd["rotation"])
    if abs(rot) % 180 == 90:
        w, h = h, w
    num, den = d["r_frame_rate"].split("/")
    return dict(w=w, h=h, fps=float(num) / float(den), rotation=rot)


def has_audio(f):
    out = run([FP, "-v", "error", "-select_streams", "a", "-show_entries",
               "stream=index", "-of", "csv=p=0", f]).stdout.strip()
    return bool(out)


def ms(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


def pw_expr(keys, var="t"):
    """Кусочно-гладкая функция времени для выражений ffmpeg.

    keys — [(время, значение), …] по возрастанию времени. Между узлами
    smoothstep, за крайними узлами — константа. Наезд и его центр гоняются
    через одну и ту же функцию: так рамка растёт и едет синхронно, без рывка
    на стыке узлов.

    Линейная интерполяция здесь не годится: на узле скорость меняется
    скачком, и на медленном наезде этот излом видно как щелчок.
    """
    ks = [(float(t), float(v)) for t, v in keys]
    if len(ks) == 1:
        return f"{ks[0][1]:.4f}"
    e = f"{ks[-1][1]:.4f}"
    for (ta, va), (tb, vb) in reversed(list(zip(ks, ks[1:]))):
        d = max(1e-3, tb - ta)
        u = f"clip(({var}-{ta:.3f})/{d:.3f},0,1)"
        e = (f"if(lt({var},{tb:.3f}),{va:.4f}+({vb - va:.4f})*"
             f"({u})*({u})*(3-2*({u})),{e})")
    return e


# ── шрифты ──────────────────────────────────────────────────────────────────
_FONT_CACHE = {}

BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
REGULAR_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
# Запасные для символов, которых нет в основном шрифте (у Arial нет ₽).
FALLBACK_CANDIDATES = [
    ("/System/Library/Fonts/HelveticaNeue.ttc", 1, 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0, 0),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 0, 0),
]


def font_path(bold=True):
    key = ("bold" if bold else "regular")
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    env = os.environ.get("GEK_FONT_BOLD" if bold else "GEK_FONT_REGULAR")
    cands = ([env] if env else []) + (BOLD_CANDIDATES if bold else REGULAR_CANDIDATES)
    for p in cands:
        if p and os.path.exists(p):
            _FONT_CACHE[key] = p
            return p
    die("не нашёл шрифт. Поставь DejaVu/Liberation или задай GEK_FONT_BOLD "
        "и GEK_FONT_REGULAR путями к .ttf")


def has_glyph(path, ch, index=0):
    """У отсутствующего символа bbox тоже непустой — рисуется «тофу».
    Поэтому сравниваем растр с растром заведомо отсутствующего кодпоинта."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        f = ImageFont.truetype(path, 48, index=index)
    except Exception:
        return False

    def raster(c):
        im = Image.new("L", (80, 80), 0)
        ImageDraw.Draw(im).text((5, 5), c, font=f, fill=255)
        return im.tobytes()

    tofu = raster("\ue123")
    return raster(ch) != tofu and raster(ch) != raster(" ")


def fallback_for(ch, bold=True):
    """Шрифт, в котором символ есть. Кэшируем — проверка не бесплатная."""
    key = (ch, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    for path, bi, ri in FALLBACK_CANDIDATES:
        idx = bi if bold else ri
        if os.path.exists(path) and has_glyph(path, ch, idx):
            _FONT_CACHE[key] = (path, idx)
            return _FONT_CACHE[key]
    _FONT_CACHE[key] = None
    return None
