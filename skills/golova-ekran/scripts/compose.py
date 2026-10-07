#!/usr/bin/env python3
"""Композитор раскладок студии (H, HC, S, T) — кадр за кадром, на питоне.

Классические раскладки A/B/C/D собирает ffmpeg (blocks.py), и там это
правильно: коробки стоят на месте. Здесь — H, SH, HC, S, T. В студии коробки ЕЗДЯТ — карточка головы
перестраивается за 0,7 с, экран въезжает окном, камера плавно наезжает
по ключам, поверх идёт графика со своей альфой и маска человека. В фильтрах
ffmpeg такое не собрать без километра выражений, а на питоне это сто строк.

Слои кадра снизу вверх:
  сцена (тёмная подложка) → линейка и подпись раздела → окно экрана →
  карточка головы → панель / вставка / плашки → графика bg → человек
  по маске → графика fg → полноэкранная карточка T

Нужны только pillow и numpy. Уменьшает pillow честной свёрткой по площади
(ширина фильтра растёт с коэффициентом) — это и есть сверхвыборка, из-за
которой мелкий текст экрана в окне не мылится и не рябит.

  compose.py --part БЛОК F0 F1 ФАЙЛ   кадры [F0, F1) — зовёт blocks.py
  compose.py --preview 12.5,40        контрольные кадры в work/check/
"""
import glob
import os
import subprocess
import sys
import time

import numpy as np
from PIL import (Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont,
                 ImageOps)

import lib

P = lib.load_project()
G = lib.read_json("geometry.json")
PL = lib.read_json("plan.json")
WORK = lib.work_dir()
ZM = (lib.read_json("zoom.json")["blocks"]
      if os.path.exists(os.path.join(WORK, "zoom.json")) else {})
M = os.path.join(lib.project_dir(), "masks")
INS = os.path.join(lib.project_dir(), "ins")
W, H = 1920, 1080
FPS = PL["fps"]
MORPH = float(PL.get("morph", 0.7))
BLOCKS = PL["blocks"]
HEAD, SCR = f"{WORK}/head_cut.mp4", f"{WORK}/scr_cut.mp4"
SW, SH = G["SCR_W"], G["SCR_H"]
PUSH = float(G.get("PUSH", 0.035))
ACC = tuple(getattr(P, "ACCENT", (232, 84, 30)))
RIGHT = G.get("side", "right") == "right"
RULER = bool(getattr(P, "RULER", False))
GRADE = bool(getattr(P, "HEAD_GRADE", True))
BG_RGB, SURF_RGB = (14, 15, 18), (23, 25, 30)
DUR_INS = {}
if os.path.exists(f"{INS}/durations.json"):
    import json
    DUR_INS = json.load(open(f"{INS}/durations.json", encoding="utf-8"))


def clamp(v, a=0.0, b=1.0):
    return min(max(v, a), b)


# ── размеры исходников ──────────────────────────────────────────────────────
def _dims(path, fallback):
    try:
        i = lib.video_info(path)
        return i["w"], i["h"]
    except Exception:
        return fallback


HW, HH = _dims(HEAD, tuple(G["HEAD_SRC"]))
_kx, _ky = HW / G["HEAD_SRC"][0], HH / G["HEAD_SRC"][1]
FACE = (G["FACE"][0] * _kx, G["FACE"][1] * _ky)


def crop_of(tag):
    x, y, w, h = G[f"{tag}_CROP"]
    return (x * _kx, y * _ky, w * _kx, h * _ky)


# ── раскладка во времени ────────────────────────────────────────────────────
def block_at(t):
    for i, b in enumerate(BLOCKS):
        if b["a"] - 1e-6 <= t < b["b"]:
            return i
    return len(BLOCKS) - 1


def push(crop, k):
    """Медленный наезд внутри плана 1.00 → 1.035 к центру лица.

    Не на склейке и не рывком: за весь план. Жизнь в длинном куске даёт он,
    а не цифровой зум на каждой склейке (1.0↔1.13 на каждой из 575 склеек
    читался как дёрганая камера — это запрещено)."""
    z = 1.0 + PUSH * k
    x0, y0, w, h = crop
    px, py = clamp(FACE[0], x0, x0 + w), clamp(FACE[1], y0, y0 + h)
    return (px - (px - x0) / z, py - (py - y0) / z, w / z, h / z)


def base_state(i, t):
    """Состояние блока без перестроения. Медленный наезд на голову считается по
    всему плану (run): H и SH подряд — один план, наезд через них не сбрасывается."""
    b = BLOCKS[i]
    m = b["m"]
    box = G[f"{m}_HEAD"]
    ra, rb = b.get("run", [b["a"], b["b"]])
    k = clamp((t - ra) / max(1e-3, rb - ra))
    scr = m in ("S", "SH")
    return dict(card=tuple(box[:4]), r=box[4], crop=push(crop_of(m), k),
                scr=1.0 if scr else 0.0, sblock=i if scr else None,
                srect=tuple(G[f"{m}_SCR"]) if scr else None)


def mix(s0, s1, p):
    out = dict(card=tuple(lib.lerp(a, b, p) for a, b in zip(s0["card"], s1["card"])),
               r=lib.lerp(s0["r"], s1["r"], p),
               crop=tuple(lib.lerp(a, b, p) for a, b in zip(s0["crop"], s1["crop"])),
               scr=lib.lerp(s0["scr"], s1["scr"], p))
    out["sblock"] = s1["sblock"] if s1["sblock"] is not None else s0["sblock"]
    # S → SH: окно не исчезает, а уменьшается из большого в малое
    if s0["srect"] and s1["srect"]:
        out["srect"] = tuple(lib.lerp(a, b, p) for a, b in zip(s0["srect"], s1["srect"]))
        out["morph_scr"] = True
    else:
        out["srect"] = s1["srect"] or s0["srect"]
    return out


def state(t):
    """Состояние кадра в момент t: карточка, кроп головы, окно экрана, карточка T."""
    i = block_at(t)
    b = BLOCKS[i]
    tcard = None                    # (имя карточки, сдвиг по x в долях ширины)
    if b["m"] == "T":
        j = b["from"]
        st = base_state(j, BLOCKS[j]["b"]) if j is not None else None
        # въезжает справа за 0,45 с (сдвиг — доля ширины кадра); в начале ролика
        # и после классического блока (под ней нечего показывать) — сразу на месте
        x = 1.0 - lib.ease_out((t - b["a"]) / 0.45) if j is not None else 0.0
        return st, (b["panel"], x), i
    st = base_state(i, t)
    j = b["from"]
    if j is not None and t < b["a"] + MORPH:
        p = lib.ease((t - b["a"]) / MORPH)
        st = mix(base_state(j, BLOCKS[j]["b"]), st, p)
    if i and BLOCKS[i - 1]["m"] == "T" and t < b["a"] + MORPH:
        # карточка T уезжает влево, пока под ней перестраивается план
        tcard = (BLOCKS[i - 1]["panel"], -lib.ease((t - b["a"]) / MORPH))
    return st, tcard, i


# ── маски: скругления со сглаживанием ───────────────────────────────────────
_corner = {}
_masks = {}


def corner(r):
    """Четверть круга радиуса r со сглаживанием края в один пиксель (SDF)."""
    r = max(1, int(round(r)))
    if r not in _corner:
        ys, xs = np.mgrid[0:r, 0:r].astype(np.float32) + 0.5
        d = np.sqrt((r - xs) ** 2 + (r - ys) ** 2) - r
        _corner[r] = Image.fromarray((np.clip(0.5 - d, 0, 1) * 255).astype(np.uint8))
    return _corner[r]


def rmask(w, h, r):
    """Скруглённый прямоугольник: белая плашка + четыре сглаженных угла."""
    key = (w, h, int(round(r)))
    if key in _masks:
        return _masks[key]
    r = int(round(min(r, w / 2, h / 2)))
    m = rmask_plain(w, h, r)
    # тонкая светлая кромка: маска минус та же маска, ужатая на 2 px
    ring = ImageChops.subtract(m, ImageOps.expand(
        rmask_plain(w - 4, h - 4, max(0, r - 2)), border=2, fill=0))
    if len(_masks) > 96:
        _masks.clear()
    _masks[key] = (m, ring)
    return _masks[key]


def rmask_plain(w, h, r):
    m = Image.new("L", (max(1, w), max(1, h)), 255)
    r = int(round(min(r, w / 2, h / 2)))
    if r > 0:
        c = corner(r)
        m.paste(c, (0, 0))
        m.paste(c.transpose(Image.FLIP_LEFT_RIGHT), (w - r, 0))
        m.paste(c.transpose(Image.FLIP_TOP_BOTTOM), (0, h - r))
        m.paste(c.transpose(Image.ROTATE_180), (w - r, h - r))
    return m


_shadows = {}


def shadow(canvas, x, y, w, h, r, strength, dy=22, blur=28):
    """Мягкая тень под карточкой. Размываем в четверть размера — в разы дешевле."""
    key = (w, h, int(round(r)))
    if key not in _shadows:
        pad = blur * 2
        big = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
        big.paste(rmask_plain(w, h, r), (pad, pad))
        small = big.resize((big.width // 4, big.height // 4), Image.BILINEAR)
        small = small.filter(ImageFilter.GaussianBlur(blur / 4))
        if len(_shadows) > 48:
            _shadows.clear()
        _shadows[key] = (small.resize(big.size, Image.BILINEAR), pad)
    sm, pad = _shadows[key]
    if strength < 0.999:
        sm = sm.point(lambda v: int(v * strength))
    canvas.paste((0, 0, 0), (x - pad, y - pad + dy), sm)


def scaled(mask, a):
    return mask if a >= 0.999 else mask.point(lambda v: int(v * a))


def card(canvas, img, x, y, r, alpha=1.0, shadow_k=0.55, edge=0.12):
    """Вклеить картинку карточкой: тень, скругление, тонкая светлая кромка."""
    w, h = img.size
    m, ring = rmask(w, h, r)
    if shadow_k > 0:
        shadow(canvas, x, y, w, h, r, shadow_k * alpha)
    canvas.paste(img, (x, y), scaled(m, alpha))
    if edge > 0:
        canvas.paste((255, 255, 255), (x, y), scaled(ring, edge * alpha))


# ── цвет головы: лёгкий контраст и тепло ────────────────────────────────────
_x = np.arange(256, dtype=np.float32) / 255
_y = np.clip(0.5 + (_x - 0.5) * 1.07 + 0.012, 0, 1) ** 1.02
LUT = (list(np.clip(_y * 1.015 * 255, 0, 255).astype(np.uint8)) +
       list(np.clip(_y * 255, 0, 255).astype(np.uint8)) +
       list(np.clip(_y * 0.985 * 255, 0, 255).astype(np.uint8)))


def grade(img):
    if not GRADE:
        return img
    return ImageEnhance.Color(img.point(LUT)).enhance(1.06)


# ── сцена и обвязка ─────────────────────────────────────────────────────────
def build_stage():
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xs - W * (0.28 if RIGHT else 0.72)) / W) ** 2 + ((ys - H * 0.2) / H) ** 2)
    glow = np.clip(1 - d / 0.9, 0, 1) ** 2
    bg, sf = np.array(BG_RGB, np.float32), np.array(SURF_RGB, np.float32)
    img = bg[None, None, :] + (sf - bg)[None, None, :] * glow[..., None] * 0.9
    dots = ((xs % 40 < 2) & (ys % 40 < 2)).astype(np.float32) * 0.035
    img += 255 * dots[..., None]
    vig = np.clip(1 - 0.35 * (((xs - W / 2) / W) ** 2 + ((ys - H / 2) / H) ** 2) * 2, 0, 1)
    return Image.fromarray(np.clip(img * vig[..., None], 0, 255).astype(np.uint8))


STAGE = build_stage()
F_MONO13 = ImageFont.truetype(lib.font_mono(), 13)
F_MONO14 = ImageFont.truetype(lib.font_mono(), 14)
RULER_PX_S = 120


def build_ruler():
    total = int((PL["out_dur"] + 30) * RULER_PX_S)
    im = Image.new("RGBA", (total, 46), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.line([(0, 44), (total, 44)], fill=(39, 42, 49, 230), width=1)
    for q in range(0, int(total / (RULER_PX_S / 4))):
        x = q * RULER_PX_S / 4
        major = q % 4 == 0
        dr.line([(x, 44 - (10 if major else 5)), (x, 44)],
                fill=(60, 64, 74, 230) if major else (45, 48, 56, 230), width=1)
        if q % 8 == 0:
            s = q // 4
            dr.text((x + 4, 14), f"01:{s // 60:02d}:{s % 60:02d}:00", font=F_MONO13,
                    fill=(92, 97, 110, 230))
    return im


RULER_IM = build_ruler() if RULER else None
_labels = {}


def label(text, font, color, spacing=2.0):
    key = (text, font.size, color, spacing)
    if key not in _labels:
        w = int(sum(font.getlength(ch) + spacing for ch in text)) + 8
        im = Image.new("RGBA", (w, 24), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        x = 0
        for ch in text:
            dr.text((x, 3), ch, font=font, fill=color)
            x += font.getlength(ch) + spacing
        _labels[key] = im
    return _labels[key]


def chrome(canvas, t, f):
    if RULER_IM is not None:
        x0 = int(t * RULER_PX_S)
        seg = RULER_IM.crop((x0, 0, x0 + W, 46))
        canvas.paste(seg, (0, 0), seg)
        tc = f"01:{f // FPS // 60:02d}:{f // FPS % 60:02d}:{f % FPS:02d}"
        lb = label(tc, F_MONO14, (107, 112, 128, 255), 1.0)
        canvas.paste(lb, (W - 56 - lb.width, 1036), lb)
    secs = PL.get("sections", [])
    if not secs or t < secs[0][0]:
        return
    i = max(k for k, (ts, _) in enumerate(secs) if ts <= t)
    p = lib.ease((t - secs[i][0]) / 0.3) if i > 0 else 1.0
    for k, a in ((i, p), (i - 1, 1 - p)):
        if k < 0 or a <= 0.01:
            continue
        lb = label(secs[k][1].upper(), F_MONO14, (146, 151, 161, 255))
        canvas.paste(lb, (78, 1036), scaled(lb.getchannel("A"), a))
    canvas.paste(ACC, (58, 1042, 68, 1052))


# ── чтение видео ────────────────────────────────────────────────────────────
class Reader:
    """Кадры подряд через ffmpeg-трубу: один поиск в начале, дальше только чтение.

    Цвет переводим явно как BT.709 и обратно так же — иначе swscale по умолчанию
    берёт BT.601, и лицо на сборке уезжает в зелень относительно классических блоков.
    """

    def __init__(self, path, w, h, f0):
        self.w, self.h, self.last = w, h, None
        ss = max(0.0, (f0 - 0.5) / FPS)
        self.p = subprocess.Popen(
            [lib.FF, "-nostdin", "-v", "error", "-ss", f"{ss:.4f}", "-i", path, "-an",
             "-vf", f"scale={w}:{h}:in_color_matrix=bt709:in_range=tv",
             "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
            stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            bufsize=10 ** 7)

    def read(self):
        n = self.w * self.h * 3
        raw = self.p.stdout.read(n)
        if len(raw) == n:
            self.last = Image.frombuffer("RGB", (self.w, self.h), raw, "raw", "RGB", 0, 1)
        return self.last

    def close(self):
        try:
            self.p.stdout.close()
            self.p.kill()
        except Exception:
            pass


def one_frame(path, t, w, h):
    raw = subprocess.run(
        [lib.FF, "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.4f}", "-i", path,
         "-frames:v", "1", "-vf", f"scale={w}:{h}:in_color_matrix=bt709:in_range=tv",
         "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        capture_output=True, stdin=subprocess.DEVNULL).stdout
    if len(raw) < w * h * 3:
        return Image.new("RGB", (w, h), BG_RGB)
    return Image.frombuffer("RGB", (w, h), raw[:w * h * 3], "raw", "RGB", 0, 1)


_freeze = {}


def freeze_frame(fr):
    key = (fr["take"], fr["src"])
    if key not in _freeze:
        path = f"{WORK}/scr_{fr['take']}.mp4"
        _freeze[key] = one_frame(path, fr["src"], SW, SH)
    return _freeze[key]


# ── картинки из masks/ и графика ────────────────────────────────────────────
_png = {}


def png(path):
    if path not in _png:
        if not os.path.exists(path):
            _png[path] = None
        else:
            im = Image.open(path)
            im.load()
            _png[path] = im.convert("RGBA") if im.mode != "RGBA" else im
        if len(_png) > 64:
            for k in list(_png)[:16]:
                _png.pop(k, None)
    return _png[path]


GFX = []
for g in PL.get("gfx", []):
    files = sorted(glob.glob(f"{WORK}/gfx/{g['id']}/*.png"))
    if files:
        GFX.append(dict(g, files=files, b=g["a"] + len(files) / FPS))


def gfx_frame(g, f):
    i = f - int(round(g["a"] * FPS))
    if i < 0 or i >= len(g["files"]):
        return None
    im = Image.open(g["files"][i])
    im.load()
    if im.mode == "RGB":
        # HyperFrames пишет непрозрачный кадр БЕЗ альфы — это альфа 1, а не «нет кадра»,
        # иначе полноэкранные карточки из графики просто пропадают
        return im, None
    im = im.convert("RGBA")
    a = im.getchannel("A")
    if a.getextrema()[1] < 2:
        return None
    return im.convert("RGB"), a


def matte_frame(g, f):
    i = f - int(round(g["a"] * FPS)) + 1
    p = f"{WORK}/matte/{g['id']}/{i:05d}.png"
    if not os.path.exists(p):
        return None
    m = Image.open(p)
    m.load()
    return m.convert("L")


# ── сборка кадра ────────────────────────────────────────────────────────────
_ins_readers = {}


def insert_frame(x, f):
    n = x["n"]
    f0 = int(round(x["a"] * FPS))
    inner = G["H_INNER"]
    rd = _ins_readers.get(n)
    if rd is None or rd[1] != f - 1:
        if rd:
            rd[0].close()
        rd = (Reader(f"{INS}/{n}.mp4", inner[2], inner[3], f - f0), f - 1)
    im = rd[0].read()
    _ins_readers[n] = (rd[0], f)
    return im


def render(f, head, scr):
    t = f / FPS
    st, tcard, bi = state(t)
    blk = BLOCKS[bi]
    if tcard and abs(tcard[1]) < 1e-4:
        im = png(f"{M}/tcard_{tcard[0]}.png")
        if im is not None:
            return im.convert("RGB")
    canvas = STAGE.copy()
    chrome(canvas, t, f)
    hcard = None
    if st is not None:
        # окно экрана
        if st["scr"] > 0.005 and st.get("srect"):
            on = st["scr"]
            x, y, w, h, r = st["srect"]
            sc = lib.lerp(0.94, 1.0, on)
            w2, h2 = int(round(w * sc)) // 2 * 2, int(round(h * sc)) // 2 * 2
            x2 = int(round(x + (w - w2) / 2))
            # окно въезжает снизу и проявляется; маленькому — сдвиг поменьше
            y2 = int(round(y + (h - h2) / 2 + (1 - on) * min(140, h * 0.16)))
            sb = st["sblock"]
            frame = scr
            for fr in PL.get("freezes", []):
                if fr["block"] == sb and t >= fr["a"] - 1e-6:
                    frame = freeze_frame(fr)
            keys = ZM.get(str(sb)) if sb is not None else None
            lt = clamp(t, BLOCKS[sb]["a"], BLOCKS[sb]["b"]) - BLOCKS[sb]["a"] \
                if sb is not None else 0.0
            z = lib.pw(keys["z"], lt) if keys else 1.0
            fx = lib.pw(keys["fx"], lt) if keys else 0.5
            fy = lib.pw(keys["fy"], lt) if keys else 0.5
            zw, zh = SW / z, SH / z
            cx = clamp(fx * SW, zw / 2, SW - zw / 2)
            cy = clamp(fy * SH, zh / 2, SH - zh / 2)
            buf = frame.resize((w2, h2), Image.BICUBIC,
                               box=(cx - zw / 2, cy - zh / 2, cx + zw / 2, cy + zh / 2))
            card(canvas, buf, x2, y2, r, alpha=on, shadow_k=0.6, edge=0.10)
        # карточка головы
        x, y, w, h = (int(round(v)) for v in st["card"])
        cx0, cy0, cw, ch = st["crop"]
        hbuf = grade(head.resize((w, h), Image.BICUBIC, box=(cx0, cy0, cx0 + cw, cy0 + ch)))
        card(canvas, hbuf, x, y, st["r"])
        hcard = (hbuf, x, y, st["r"], (cx0, cy0, cw, ch))

    # заголовок над окном SH: моно-подпись + крупная строка, проявляется после перестроения
    if blk["m"] == "SH" and blk.get("head_t") and st is not None and st.get("srect"):
        t_in, t_out = blk["head_t"]
        if t_in <= t < t_out + 0.3:
            im = png(f"{M}/shhead_{blk['panel']}.png")
            if im is not None:
                a = lib.ease_out((t - t_in) / 0.4) * (1 - clamp((t - t_out) / 0.3))
                sx, sy = int(st["srect"][0]), int(st["srect"][1])
                dy = int((1 - lib.ease_out((t - t_in) / 0.4)) * 16)
                canvas.paste(im, (sx, sy - im.height - 14 + dy), scaled(im.getchannel("A"), a))

    # вставка в H занимает место панели — панель на это время уходит
    hide = 0.0
    for x in PL.get("inserts", []):
        if x.get("lay") == "H":
            d = float(DUR_INS.get(x["n"], x["dur"]))
            hide = max(hide, clamp((t - x["a"] + 0.25) / 0.25) *
                       (1 - clamp((t - x["a"] - d) / 0.25)))

    # панель в H: въезжает после перестроения, пункты загораются по одному
    if blk["m"] == "H" and blk.get("panel_t") and hide < 0.999:
        t_in, t_out, reveals = blk["panel_t"]
        if t_in <= t < t_out + 0.3:
            a = lib.ease_out((t - t_in) / 0.45) * (1 - clamp((t - t_out) / 0.3)) * (1 - hide)
            k = max(1, sum(1 for r_ in reveals if r_ <= t))
            px, py = G["H_PANEL"][0], G["H_PANEL"][1]
            dx = int((1 - lib.ease_out((t - t_in) / 0.45)) * (-40 if RIGHT else 40))
            cur = png(f"{M}/panel_{blk['panel']}_h_{k}.png")
            if cur is not None:
                fade = clamp((t - reveals[k - 1]) / 0.25) if k > 1 else 1.0
                if fade < 1.0:
                    prv = png(f"{M}/panel_{blk['panel']}_h_{k - 1}.png")
                    canvas.paste(prv, (px + dx, py), scaled(prv.getchannel("A"), a))
                    canvas.paste(cur, (px + dx, py), scaled(cur.getchannel("A"), a * fade))
                else:
                    canvas.paste(cur, (px + dx, py), scaled(cur.getchannel("A"), a))

    # вставки (только в H — в S экран и так занят)
    for x in PL.get("inserts", []):
        if x.get("lay") == "H" and blk["m"] == "H":
            d = float(DUR_INS.get(x["n"], x["dur"]))
            if x["a"] <= t < x["a"] + d:
                dec = png(f"{M}/deco_{x['n']}.png")
                if dec is not None:
                    canvas.paste(dec, tuple(G["H_POS"]), dec)
                clip = insert_frame(x, f)
                if clip is not None:
                    inn = G["H_INNER"]
                    canvas.paste(clip, (inn[0], inn[1]), rmask(inn[2], inn[3], 12)[0])

    # плашки-подписи: всплывают за 0,3 с, уходят за 0,25 с
    live = [c for c in PL.get("chips", []) if c["a"] <= t < c["b"] + 0.25]
    yoff = xoff = 0
    for c in live:
        im = png(f"{M}/chip_{c['i']:02d}.png")
        if im is None:
            continue
        pin = lib.ease_out((t - c["a"]) / 0.3)
        pout = clamp((t - c["b"]) / 0.25)
        a = pin * (1 - pout)
        s = lib.lerp(0.86, 1.0, pin)
        im2 = im if s > 0.995 else im.resize((max(1, int(im.width * s)),
                                              max(1, int(im.height * s))), Image.BICUBIC)
        if c["m"] == "SH":
            # под окном SH плашки-факты идут в ряд
            cx, cy = G["CHIP_SH"]
            canvas.paste(im2, (cx + xoff, cy - int(10 * pout)), scaled(im2.getchannel("A"), a))
            xoff += im.width - 28
            continue
        cx, cy = G["CHIP_S"] if c["m"] == "S" else G["CHIP_H"]
        canvas.paste(im2, (cx, cy + yoff - int(10 * pout)), scaled(im2.getchannel("A"), a))
        yoff += im.height - 30

    # оговорка, оставленная нарочно: ч/б и плашка
    bw = PL.get("bw")
    if bw and bw["a"] <= t < bw["b"]:
        canvas = ImageOps.grayscale(canvas).convert("RGB")
        pl = png(f"{M}/bw_plaque.png")
        if pl is not None:
            bx = G[f"{blk['m']}_SCR"][0] + 24 if blk["m"] in ("S", "SH") else G["H_PANEL"][0]
            canvas.paste(pl, (bx, 900), pl)

    # графика за человеком → человек по маске → графика спереди
    bgs = [g for g in GFX if g["layer"] == "bg" and g["a"] <= t < g["b"]]
    fgs = [g for g in GFX if g["layer"] != "bg" and g["a"] <= t < g["b"]]
    for g in bgs:
        fr = gfx_frame(g, f)
        if fr:
            canvas.paste(fr[0], (0, 0), fr[1])
            m = matte_frame(g, f)
            if m is not None and hcard is not None:
                hbuf, x, y, r, (cx0, cy0, cw, ch) = hcard
                if m.size != (HW, HH):
                    m = m.resize((HW, HH), Image.BILINEAR)
                mm = m.resize(hbuf.size, Image.BILINEAR, box=(cx0, cy0, cx0 + cw, cy0 + ch))
                canvas.paste(hbuf, (x, y), ImageChops.multiply(mm, rmask(*hbuf.size, r)[0]))
    for g in fgs:
        fr = gfx_frame(g, f)
        if fr:
            canvas.paste(fr[0], (0, 0), fr[1])

    # полноэкранная карточка T: въезжает справа, уезжает влево
    if tcard:
        im = png(f"{M}/tcard_{tcard[0]}.png")
        if im is not None:
            canvas.paste(im, (int(round(tcard[1] * W)), 0), im)
    return canvas


# ── режимы ──────────────────────────────────────────────────────────────────
def writer(out, n):
    return subprocess.Popen(
        [lib.FF, "-y", "-nostdin", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-frames:v", str(n),
         "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-color_range", "tv", "-fps_mode", "cfr", out],
        stdin=subprocess.PIPE)


def part(bi, f0, f1, out):
    t0 = time.time()
    head = Reader(HEAD, HW, HH, f0)
    scr = Reader(SCR, SW, SH, f0)
    wr = writer(out, f1 - f0)
    for f in range(f0, f1):
        im = render(f, head.read(), scr.read())
        wr.stdin.write(im.tobytes())
    wr.stdin.close()
    wr.wait()
    head.close()
    scr.close()
    for rd in _ins_readers.values():
        rd[0].close()
    dt = time.time() - t0
    print(f"{f1 - f0} {dt:.2f}", flush=True)
    if wr.returncode:
        raise SystemExit(wr.returncode)


def preview(times):
    d = os.path.join(WORK, "check")
    os.makedirs(d, exist_ok=True)
    for t in times:
        f = int(round(t * FPS))
        b = BLOCKS[block_at(t)]
        if not b.get("studio"):
            print(f"  {lib.ms(t)} — блок {b['m']} классический, смотри его после build")
            continue
        head = one_frame(HEAD, f / FPS, HW, HH)
        scr = one_frame(SCR, f / FPS, SW, SH)
        out = os.path.join(d, f"p_{t:08.2f}.jpg")
        render(f, head, scr).save(out, quality=88)
        print(f"  {lib.ms(t)} {b['m']:2s} → {out}")


def main():
    a = sys.argv[1:]
    if a and a[0] == "--part":
        return part(int(a[1]), int(a[2]), int(a[3]), a[4])
    if a and a[0] == "--preview":
        return preview([float(x) for x in a[1].split(",") if x.strip()])
    print(__doc__)


if __name__ == "__main__":
    main()
