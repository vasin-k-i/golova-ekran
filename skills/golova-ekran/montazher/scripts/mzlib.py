"""Общее для «Монтажёра»: конфиг проекта, перевод времени исходника в время ролика, поиск слова.

Конфиг — файл `montazher.py` в папке проекта (MZ_PROJECT или текущая папка). Пути в нём —
относительно папки проекта. Нарезанная голова и звук — из основного пайплайна golova-ekran
(`montage.py cut` → work/head_cut.mp4, work/audio_cut.wav; work/plan.json — карта вырезов).
"""
import importlib.util
import json
import os
import sys

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPTS)
PROJ = os.path.abspath(os.environ.get("MZ_PROJECT", os.getcwd()))
W, H, FPS = 1920, 1080, 30


def load_module(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sys.path.insert(0, SCRIPTS)
    sp.loader.exec_module(m)
    return m


def die(msg):
    sys.stderr.write(f"✗ {msg}\n")
    raise SystemExit(1)


_cfg_path = os.path.join(PROJ, "montazher.py")
if not os.path.exists(_cfg_path):
    die(f"нет {_cfg_path}. Начни с `montazher.py init` — он положит шаблоны.")
C = load_module("mz_config", _cfg_path)


def P(rel):
    return rel if os.path.isabs(rel) else os.path.join(PROJ, rel)


HEAD = P(getattr(C, "HEAD", "work/head_cut.mp4"))
AUDIO = P(getattr(C, "AUDIO", "work/master_audio.wav"))
PLAN = P(getattr(C, "PLAN", "work/plan.json"))
WORDS = P(getattr(C, "WORDS", "work/words.json"))
FONTS = P(getattr(C, "FONTS", "fonts"))
OUT = P(getattr(C, "OUT", "out/монтаж.mp4"))
WORK = P("work/mz")
FCX, FCY = getattr(C, "FACE", (W // 2, H * 0.37))
GRADE = getattr(C, "GRADE", "eq=contrast=1.04:saturation=1.06:brightness=0.005")
ACCENT = getattr(C, "ACCENT", "#FFD23F")
os.makedirs(WORK, exist_ok=True)
# цепочка звука речи: мастер ≈ −14 LUFS (проверено на арбитраже: −14,1)
AUDIO_CHAIN = getattr(C, "AUDIO_CHAIN", "highpass=f=75,acompressor=threshold=0.08:ratio=2.5:attack=5:release=150:makeup=1,"
                      "volume=19dB,alimiter=limit=0.84:level=false:attack=1:release=60")
# окно камеры в углу (PIP) и голова сбоку (SPLIT) — кроп от лица
PIP = dict(w=480, h=360, x=W - 480 - 48, y=H - 360 - 48, r=28,
           crop=(720, 540, int(min(max(0, FCX - 360), W - 720)), int(min(max(0, FCY - 270), H - 540))))
SPL = dict(hx=1200, crop=(720, 1080, int(min(max(0, FCX - 360), W - 720)), 0), pw=1110, ph=624, px=45, py=228, r=22)


def take_sources():
    """id дубля → исходный файл головы, из project.py основного пайплайна golova-ekran."""
    p = os.path.join(PROJ, "project.py")
    if not os.path.exists(p):
        return {}
    m = load_module("gek_project", p)
    return {t["id"]: t["head"] for t in getattr(m, "TAKES", [])}

try:
    with open(PLAN, encoding="utf-8") as fh:
        KEEPS = json.load(fh)["keeps"]
except FileNotFoundError:
    KEEPS = []
try:
    with open(WORDS, encoding="utf-8") as fh:
        _WORDS = json.load(fh)
except FileNotFoundError:
    _WORDS = {}


def s2o(take, t):
    """Секунда исходника дубля → секунда готового ролика (паузы вырезаны).
    Точка во вырезанной паузе прижимается к началу следующей фразы; за концом дубля — к его концу."""
    acc, last = 0.0, None
    for k in KEEPS:
        if k["take"] == take:
            if t < k["a"]:
                return acc
            if t <= k["b"]:
                return acc + min(t - k["a"], k["d"])
            last = acc + k["d"]
        elif last is not None:
            return last
        acc += k["d"]
    return last if last is not None else acc


def Wd(take, pref, after=0.0):
    """Секунда исходника, где начинается слово pref (первое после after). Тайминги — work/words.json."""
    pref = pref.lower()
    best = None
    for key, ws in _WORDS.items():
        if not key.startswith(take + "@"):
            continue
        for t, w in ws:
            ww = w.lower().strip(".,!?:;«»\"()—-")
            if t >= after and ww.startswith(pref) and (best is None or t < best):
                best = t
    if best is None:
        raise KeyError(f"{take}: нет слова «{pref}» после {after} — сначала `montazher.py words`")
    return best


def edl():
    return load_module("mz_edl", P(getattr(C, "EDL", "edl.py")))
