"""Текст по видео для «Монтажёра» — куски HyperFrames (рендерит `montage.py gfx` основного скилла).

Модуль сам является «проектом» для gfx.py: в нём FPS, TAKES, GFX_FONTS и GFX.
`montazher.py texts` кладёт заглушку work/mz/texts/project.py, которая импортирует этот файл,
и гоняет gfx с GEK_PROJECT на эту папку → кадры в work/mz/texts/work/gfx/<id>/frame_*.png.

Строка TEXTS в edl.py:
    (id, дубль, с, до, позиция, строка1, строка2, extra)
позиции:
    wall  — слева у стены, рядом с головой (строка курсивом + капс)
    low   — нижняя треть
    title — заголовок главы: надстрочник с квадратиком + крупный капс
    win   — окошки инфографики рядом с головой (не на весь экран!)
строка2:
    "текст\\n*акцент*"           — капс, *звёздочки* = цветной акцент, \\n — перенос
    "COUNT:100000000:₽"          — счётчик; extra=dict(sub=("подпись", секунда_исходника))
    "LIST:пункт@сек|пункт@сек"   — пункты по слову (секунды исходника)
    "WIN:мелко/КРУПНО@сек|!мелко/КРУПНО@сек" — окошки по слову, «!» — горячее (градиент)
extra:
    "chain" — кусок держится до конца следующей строки; "cont" — строка-продолжение (не рисуется)
"""
import os
import re

from PIL import ImageFont

import mzlib as L

FPS = L.FPS
TAKES = []
_F = L.FONTS
ACCENT = tuple(int(L.ACCENT[i:i + 2], 16) for i in (1, 3, 5))   # gfx.py ждёт RGB
GFX_FONTS = dict(display=f"{_F}/Montserrat[wght].ttf", text=f"{_F}/Montserrat-Italic[wght].ttf",
                 text_bold=f"{_F}/Montserrat[wght].ttf", mono=f"{_F}/Montserrat[wght].ttf")
ALLOW = "data-layout-allow-overlap data-layout-allow-occlusion data-layout-allow-overflow"

CSS = """
.v2g{position:absolute;inset:0}
.v2g.wall,.v2g.win{background:linear-gradient(90deg,rgba(10,10,12,.62) 0,rgba(10,10,12,.40) 26%,rgba(10,10,12,0) 46%)}
.v2g.low{background:linear-gradient(0deg,rgba(8,8,10,.80) 0,rgba(8,8,10,.45) 22%,rgba(8,8,10,0) 42%)}
.v2g.title{background:linear-gradient(0deg,rgba(6,6,8,.82) 0,rgba(6,6,8,.40) 40%,rgba(6,6,8,0) 62%)}
.v2t{position:absolute;color:#fff;text-shadow:0 4px 26px rgba(0,0,0,.45)}
.v2t.wall{left:96px;top:50%;transform:translateY(-50%);max-width:640px}
.v2t.low{left:92px;bottom:96px;max-width:1240px}
.v2t.title{left:120px;bottom:150px;max-width:1500px}
.v2t.win{left:100px;top:50%;transform:translateY(-50%);width:660px}
.v2l1{font-family:"GEK Text";font-style:normal;font-weight:400;font-size:52px;white-space:nowrap;line-height:1.15;opacity:.95}
.v2l2{font-family:"GEK Display";font-weight:800;font-size:92px;line-height:.98;text-transform:uppercase;letter-spacing:-.01em;margin-top:10px}
.low .v2l2{font-size:72px}
.title .v2l2{font-size:112px}
.v2l2 .ln{display:block;width:max-content;max-width:100%}
.v2l2 b{color:ACC;font-weight:800}
.v2eb{display:flex;align-items:center;gap:14px;font-family:"GEK Display";font-weight:700;font-size:24px;letter-spacing:.22em;text-transform:uppercase;color:ACC}
.v2eb i{display:block;width:14px;height:14px;border-radius:3px;background:ACC}
.v2li{display:block;font-family:"GEK Display";font-weight:800;font-size:78px;line-height:1.02;text-transform:uppercase}
.v2li:first-child{color:ACC}
.wn{margin-top:22px;background:rgba(18,10,10,.82);border:1px solid rgba(255,255,255,.12);border-radius:30px;padding:24px 36px;
  box-shadow:0 30px 70px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,255,255,.06);display:flex;align-items:center;gap:26px}
.wn .n{font-family:"GEK Display";font-weight:900;font-size:40px;color:rgba(255,255,255,.35);width:46px}
.wn .s{font-family:"GEK Text";font-weight:300;font-size:32px;color:rgba(255,255,255,.78)}
.wn .b{font-family:"GEK Display";font-weight:900;font-size:56px;color:#fff;line-height:1.02;text-transform:uppercase}
.wn.hot{background:linear-gradient(95deg,#de0903,#f2a807);border-color:transparent}
.wn.hot .s,.wn.hot .n{color:rgba(255,255,255,.9)}
""".replace("ACC", L.ACCENT)

_FONT = ImageFont.truetype(f"{_F}/Montserrat[wght].ttf", 100)
try:
    _FONT.set_variation_by_axes([800])
except Exception:
    pass
WIDTH = dict(wall=(92, 600), low=(72, 1180), title=(112, 1500), win=(56, 480))
SHRUNK = []   # что пришлось ужать — печатает `montazher.py texts`


def _caps(s):
    """*слово* = акцент; акцент может переходить через перенос строки."""
    out, acc = [], False
    for ln in s.split("\n"):
        html = ""
        for tok in re.split(r"(\*)", ln):
            if tok == "*":
                acc = not acc
                continue
            if tok:
                html += f'<b {ALLOW}>{tok}</b>' if acc else tok
        out.append(f'<span class="ln" {ALLOW}>{html}</span>')
    return "".join(out)


def _fit(tid, l2, pos):
    """Кегль капса по реальной ширине самой длинной строки (Montserrat 800) — текст не вылезает из рамки."""
    base, width = WIDTH[pos]
    w = max(_FONT.getlength(re.sub(r"\*", "", ln).upper()) for ln in l2.split("\n"))
    fs = int(min(base, width * 100 / max(1, w * 0.99)))
    if fs < base * 0.55:
        SHRUNK.append(f"{tid}: «{l2}» ужат до {fs}px из {base} — сократи формулировку")
    return fs


def piece(tid, take, a, b, pos, l1, l2, extra, end_out=None):
    s2o = L.s2o
    t0 = s2o(take, a)
    t1 = end_out if end_out is not None else s2o(take, b)
    dur = round(max(0.8, t1 - t0), 3)
    R = lambda t: max(0.0, min(round(s2o(take, t) - t0, 3), dur - 0.4))   # секунда исходника → время куска
    js = 'tl.fromTo(".v2g",{opacity:0},{opacity:1,duration:.35,ease:"power2.out"},0);'
    if pos == "title":
        body = (f'<div class="v2eb" id="l1" {ALLOW}><i></i>{l1}</div>'
                f'<div class="v2l2" id="l2" {ALLOW} style="font-size:{_fit(tid, l2, pos)}px">{_caps(l2)}</div>')
    elif l2.startswith("COUNT:"):
        _, num, suf = l2.split(":")
        sub = extra.get("sub") if isinstance(extra, dict) else None
        at = extra.get("at", a + 0.3) if isinstance(extra, dict) else a + 0.3
        txt = f"{int(num):,} {suf}".replace(",", " ")
        body = (f'<div class="v2l1" id="l1" {ALLOW}>{l1}</div>'
                f'<div class="v2l2" id="l2" {ALLOW} style="font-size:{_fit(tid, txt, pos)}px;white-space:nowrap">'
                f'<span class="ln"><b id="num">0</b> {suf}</span></div>')
        if sub:
            body += f'<div class="v2l1" id="sb" {ALLOW} style="margin-top:18px;color:{L.ACCENT}">{sub[0]}</div>'
            js += f'tl.fromTo("#sb",{{opacity:0,y:20}},{{opacity:1,y:0,duration:.45,ease:"power3.out"}},{R(sub[1])});'
        js += f'HF.count(tl,"#num",0,{num},{R(at)},1.0,HF.num);'
        js += f'tl.set("#l2",{{opacity:0}},0);tl.set("#l2",{{opacity:1}},{max(0, R(at) - 0.1)});'
    elif l2.startswith("LIST:"):
        items = [x.rsplit("@", 1) for x in l2[5:].split("|")]
        fs = min(78 if pos == "wall" else 62, _fit(tid, "\n".join(w for w, _ in items), pos))
        lis = "".join(f'<span class="v2li" id="li{i}" {ALLOW} style="font-size:{fs}px">{w}</span>' for i, (w, _) in enumerate(items))
        body = f'<div class="v2l1" id="l1" {ALLOW}>{l1}</div><div style="margin-top:14px">{lis}</div>'
        for i, (_, at) in enumerate(items):
            js += f'tl.fromTo("#li{i}",{{opacity:0,x:-40}},{{opacity:1,x:0,duration:.45,ease:"power3.out"}},{R(float(at))});'
    elif l2.startswith("WIN:"):
        items = [x.rsplit("@", 1) for x in l2[4:].split("|")]
        body = f'<div class="v2l1" id="l1" {ALLOW}>{l1}</div>' if l1 else ""
        for i, (txt, at) in enumerate(items):
            hot = txt.startswith("!")
            small, big = txt.lstrip("!").split("/", 1)
            fs = _fit(tid, big, "win")
            num = "=" if hot else str(i + 1)
            body += (f'<div class="wn{" hot" if hot else ""}" id="wn{i}" {ALLOW}><div class="n">{num}</div>'
                     f'<div><div class="s">{small}</div><div class="b" style="font-size:{fs}px">{big}</div></div></div>')
            ease = "back.out(1.6)" if hot else "power3.out"
            js += f'tl.fromTo("#wn{i}",{{opacity:0,x:-80}},{{opacity:1,x:0,duration:.35,ease:"{ease}"}},{R(float(at))});'
        js += f'tl.to(".wn",{{opacity:0,x:-60,duration:.3,ease:"power2.in",stagger:.04}},{round(dur - 0.45, 3)});'
    else:
        body = (f'<div class="v2l1" id="l1" {ALLOW}>{l1}</div>'
                f'<div class="v2l2" id="l2" {ALLOW} style="font-size:{_fit(tid, l2, pos)}px">{_caps(l2)}</div>')
    js += ('tl.fromTo("#l1",{opacity:0,x:-28},{opacity:.95,x:0,duration:.45,ease:"power3.out"},0.05);'
           'tl.fromTo("#l2 .ln",{clipPath:"inset(0 100% 0 0)"},{clipPath:"inset(0 0% 0 0)",duration:.55,ease:"power3.out",stagger:.1},0.15);'
           f'tl.to([".v2t",".v2g"],{{opacity:0,duration:.25,ease:"power2.in"}},{round(dur - 0.3, 3)});')
    html = f'<div class="v2g {pos}"></div><div class="v2t {pos}" {ALLOW}>{body}</div>'
    return dict(id=tid, take=take, at=a, dur=dur, layer="fg", css=CSS, html=html, js=js, out_at=round(t0, 3))


def build():
    E = L.edl()
    T = list(getattr(E, "TEXTS", []))
    out = []
    for i, (tid, take, a, b, pos, l1, l2, extra) in enumerate(T):
        if extra == "cont":
            continue
        end = None
        if extra == "chain" and i + 1 < len(T):
            n = T[i + 1]
            end = L.s2o(n[1], n[3])
        out.append(piece(tid, take, a, b, pos, l1, l2, extra, end))
    return out


GFX = build() if os.environ.get("MZ_BUILD_GFX", "1") == "1" else []
