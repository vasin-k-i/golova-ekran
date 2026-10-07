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


# ── отметка «проход по повторам сделан» ────────────────────────────────────
REPEATS_FILE = "repeats_ok.json"
NO_REPEATS_TAG = "БЕЗ ЧИСТКИ ПОВТОРОВ"


def repeats_key(P):
    """Отметка привязана к резке тишины и к спискам: поменял — согласуй заново."""
    import hashlib
    segs = read_json("segments.json") if os.path.exists(
        os.path.join(work_dir(), "segments.json")) else []
    base = [(s["take"], s["a"], s["b"]) for s in segs]
    lists = (sorted(getattr(P, "DROP", [])), list(getattr(P, "TRIM", [])),
             getattr(P, "BW", None))
    return hashlib.sha1(repr((base, lists)).encode()).hexdigest()


def repeats_state(P):
    p = os.path.join(project_dir(), REPEATS_FILE)
    if not os.path.exists(p):
        return False, "✗ проход по повторам НЕ отмечен"
    with open(p, encoding="utf-8") as fh:
        d = json.load(fh)
    if d.get("cut_hash") != repeats_key(P):
        return False, ("✗ отметка устарела: после согласования поменялись "
                       "DROP/TRIM/BW или резка тишины — согласуй список заново")
    return True, f"✓ проход по повторам согласован: {d.get('note')} ({d.get('date')})"


def write_repeats_ok(P, note):
    import time
    with open(os.path.join(project_dir(), REPEATS_FILE), "w", encoding="utf-8") as fh:
        # поле не «key»: gitleaks принимает «key» рядом с хэшем за API-ключ
        json.dump(dict(cut_hash=repeats_key(P), note=note,
                       date=time.strftime("%Y-%m-%d %H:%M")), fh, ensure_ascii=False)


def repeats_guard(P, argv, step):
    """build и final не собирают мастер без согласованного прохода по повторам.

    Обход — только явным флагом --skip-repeats: тогда это видно и в консоли,
    и в имени файла мастера. Возвращает True, если идём в обход.
    """
    ok, msg = repeats_state(P)
    skip = "--skip-repeats" in argv
    if ok:
        return False
    if not skip:
        die(f"{step}: {msg}.\n"
            "  Сначала проход по повторам и оговоркам (SKILL.md, шаг 4): "
            "`montage.py repeats`,\n  список — человеку ДО резки, после «да» — "
            "`montage.py repeats --approve \"кто и когда\"`.\n"
            "  Собрать в обход можно только явно: --skip-repeats "
            "(мастер получит пометку в имени)")
    bar = "!" * 64
    print(f"{bar}\n  {step}: {NO_REPEATS_TAG} (--skip-repeats). Такой ролик человеку\n"
          f"  не показывать: в нём остались фальстарты и оговорки.\n{bar}", flush=True)
    return True


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


def pw(keys, t):
    """То же, что pw_expr, но для питона: композитор считает кадр сам.

    Узлы и smoothstep — те же, поэтому наезд в раскладках студии (S) ведёт
    себя ровно так же, как zoompan в классических A/B.
    """
    if not keys:
        return None
    if t <= keys[0][0] or len(keys) == 1:
        return float(keys[0][1])
    for (ta, va), (tb, vb) in zip(keys, keys[1:]):
        if t < tb:
            u = min(1.0, max(0.0, (t - ta) / max(1e-3, tb - ta)))
            return va + (vb - va) * u * u * (3 - 2 * u)
    return float(keys[-1][1])


def ease(p):
    """easeInOut (кубический): перестроения раскладок и выезды карточек."""
    p = min(max(p, 0.0), 1.0)
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def ease_out(p):
    p = min(max(p, 0.0), 1.0)
    return 1 - (1 - p) ** 3


def lerp(a, b, p):
    return a + (b - a) * p


# ── раскладки ───────────────────────────────────────────────────────────────
# Классические собирает ffmpeg блоками (blocks.py), студийные — композитор
# на питоне (compose.py): у них перестроения, тени и наезд по ключевым кадрам.
CLASSIC = ("A", "B", "C", "D")
STUDIO = ("H", "HC", "S", "T")


def face_side(P):
    """С какой стороны кадра ставим голову.

    По умолчанию — напротив взгляда: человек, который смотрит влево
    (на экран ноутбука сбоку), должен стоять справа и смотреть в кадр.
    Поставь его слева — он «смотрит в угол», в рамку.
    """
    side = getattr(P, "FACE_SIDE", None)
    if side in ("left", "right"):
        return side
    gaze = getattr(P, "GAZE", "left")
    return "right" if gaze != "right" else "left"


# ── HyperFrames (необязательный модуль графики и масок) ─────────────────────
def node_bin():
    """Каталог с node ≥ 22 — HyperFrames на старом node не стартует.

    На маке node из PATH часто старый (nvm), а свежий лежит у homebrew
    в node@22/24/26 и в PATH не прописан. Ищем по версии, а не по имени.
    """
    import glob
    import re as _re
    env = os.environ.get("GEK_NODE_BIN")
    cands = ([env] if env else [])
    w = shutil.which("node")
    if w:
        cands.append(os.path.dirname(w))
    for pat in ("/opt/homebrew/opt/node@*/bin", "/usr/local/opt/node@*/bin",
                "/opt/homebrew/opt/node/bin", "/usr/local/opt/node/bin",
                os.path.expanduser("~/.nvm/versions/node/v*/bin")):
        cands += sorted(glob.glob(pat), reverse=True)
    for d in cands:
        node = os.path.join(d, "node")
        if not os.path.exists(node):
            continue
        r = subprocess.run([node, "--version"], capture_output=True, text=True)
        m = _re.match(r"v(\d+)", r.stdout.strip())
        if m and int(m.group(1)) >= 22:
            return d
    return None


def hf_env():
    d = node_bin()
    if not d:
        return None
    env = dict(os.environ)
    env["PATH"] = d + os.pathsep + env.get("PATH", "")
    return env


def hf_run(args, **kw):
    """npx hyperframes … со свежим node и закрытым stdin.

    stdin закрываем всегда: npx внутри цикла `while read` съедает остальные
    строки цикла, и обрабатывается только первая. Здесь цикла нет, но привычка
    дешёвая, а грабля дорогая.
    """
    env = hf_env()
    if env is None:
        raise RuntimeError("node ≥ 22 не найден")
    return subprocess.run(["npx", "--yes", "hyperframes", *args], env=env,
                          stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, **kw)


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
MONO_CANDIDATES = [
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
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


def font_mono():
    """Моноширинный — для подписи раздела и таймкода. Нет — берём обычный."""
    if "mono" in _FONT_CACHE:
        return _FONT_CACHE["mono"]
    env = os.environ.get("GEK_FONT_MONO")
    for p in ([env] if env else []) + MONO_CANDIDATES:
        if p and os.path.exists(p):
            _FONT_CACHE["mono"] = p
            return p
    _FONT_CACHE["mono"] = font_path(False)
    return _FONT_CACHE["mono"]


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
