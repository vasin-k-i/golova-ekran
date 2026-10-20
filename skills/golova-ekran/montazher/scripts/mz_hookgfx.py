"""Слои текста хука и отбивки — «проект» для `montage.py gfx` (как mz_texts).

Стиль утверждён на арбитраже (референс ngtZYHGBdCU): подводка — тонкий курсив, слова всплывают
из размытия; ключ — сверхжирный курсив с градиентом и свечением, печатается маской по буквам
(у background-clip:text прозрачность детей не работает — поэтому clip-path шагами).
Курсив любой толщины (250 и 900) — свой @font-face «MI» на файл курсива, который gfx.py кладёт как
GEK_Text_400.ttf: у штатного «GEK Text» толщины 400/700 разными файлами.
Тайминги — work/mz/hook/plan.json (пишет `montazher.py hook plan`).
"""
import json
import os

import mzlib as L

FPS = L.FPS
TAKES = []
_F = L.FONTS
GFX_FONTS = dict(display=f"{_F}/Montserrat[wght].ttf", text=f"{_F}/Montserrat-Italic[wght].ttf",
                 text_bold=f"{_F}/Montserrat[wght].ttf", mono=f"{_F}/Montserrat[wght].ttf")
HOOK = getattr(L.C, "HOOK", {})
G1, G2, G3 = HOOK.get("gradient", ("#e80004", "#f25a05", "#ffd000"))
ALLOW = "data-layout-allow-overlap data-layout-allow-occlusion data-layout-allow-overflow"

CSS = f"""
@font-face{{font-family:"MI";src:url("fonts/GEK_Text_400.ttf") format("truetype");font-weight:100 900;font-style:normal}}
.wrap{{position:absolute;left:0;right:0;top:560px;display:flex;flex-direction:column;align-items:center;text-align:center}}
.lead{{font-family:"MI";font-weight:250;font-size:64px;color:#fff;letter-spacing:.005em;text-shadow:0 4px 30px rgba(0,0,0,.55)}}
.lead span{{display:inline-block;margin:0 .14em}}
.key{{font-family:"MI";font-weight:900;font-size:150px;line-height:1.0;margin-top:6px;white-space:nowrap;
  background:linear-gradient(95deg,{G1} 0%,{G2} 45%,{G3} 100%);-webkit-background-clip:text;background-clip:text;color:transparent;
  filter:drop-shadow(0 0 22px rgba(232,0,4,.55)) drop-shadow(0 6px 18px rgba(0,0,0,.5))}}
.shade{{position:absolute;left:0;right:0;top:420px;bottom:0;background:linear-gradient(0deg,rgba(0,0,0,.55),rgba(0,0,0,0))}}
.fill{{position:absolute;inset:0;background:linear-gradient(110deg,{G1} 0%,{G2} 50%,{G3} 100%)}}
.ttl{{position:absolute;left:0;right:0;top:390px;text-align:center}}
.ttl .e{{font-family:"MI";font-weight:400;font-size:38px;letter-spacing:.32em;color:rgba(20,6,0,.75);text-transform:uppercase}}
.ttl .t{{font-family:"MI";font-weight:900;font-size:230px;line-height:1;color:#140600;letter-spacing:-.02em}}
"""


def _lead(words, t0, step=0.11):
    ws = words.split()
    html = "".join(f'<span id="w{i}" {ALLOW}>{w}</span>' for i, w in enumerate(ws))
    js = "".join(f'tl.fromTo("#w{i}",{{opacity:0,filter:"blur(14px)",y:10}},{{opacity:1,filter:"blur(0px)",y:0,duration:.14,ease:"power2.out"}},{t0 + i * step:.3f});'
                 for i in range(len(ws)))
    return html, js


def _key(text, t0, cps=55):
    n = max(1, len(text))
    js = (f'tl.set(".key",{{clipPath:"inset(-60px 100% -60px -60px)"}},0);'
          f'tl.to(".key",{{clipPath:"inset(-60px -60px -60px -60px)",duration:{n / cps:.3f},ease:"steps({n})"}},{t0:.3f});'
          f'tl.fromTo(".key",{{scale:1.08}},{{scale:1,duration:.35,ease:"power3.out"}},{t0:.3f});')
    return text.replace(" ", "&nbsp;"), js


def phrase(pid, dur, lead, key, t_lead, t_key, size=150):
    lh, lj = _lead(lead, t_lead)
    kh, kj = _key(key, t_key)
    html = (f'<div class="shade" id="sh"></div><div class="wrap" {ALLOW}><div class="lead" {ALLOW}>{lh}</div>'
            f'<div class="key" {ALLOW} style="font-size:{size}px">{kh}</div></div>')
    js = ('tl.fromTo("#sh",{opacity:0},{opacity:1,duration:.25},0);' + lj + kj +
          f'tl.to(".wrap",{{opacity:0,filter:"blur(10px)",duration:.2}},{dur - 0.22:.3f});')
    return dict(id=pid, take="01", at=0, dur=round(dur, 3), layer="fg", css=CSS, html=html, js=js)


def sep(dur):
    eyebrow, title = HOOK.get("title", ("", ""))
    html = (f'<div class="fill" id="f" {ALLOW}></div><div class="ttl" id="tt" {ALLOW}>'
            f'<div class="e">{eyebrow}</div><div class="t">{title}</div></div>')
    js = ('tl.fromTo("#f",{clipPath:"inset(0 100% 0 0)"},{clipPath:"inset(0 0% 0 0)",duration:.3,ease:"power3.in"},0);'
          'tl.fromTo("#tt",{opacity:0,scale:1.15,filter:"blur(12px)"},{opacity:1,scale:1,filter:"blur(0px)",duration:.35,ease:"power3.out"},.28);'
          'tl.to("#tt",{scale:.97,duration:.6,ease:"none"},.63);'
          f'tl.to(["#f","#tt"],{{clipPath:"inset(0 0 0 100%)",duration:.32,ease:"power3.in"}},{dur - 0.34:.3f});')
    return dict(id="sep", take="01", at=0, dur=dur, layer="fg", css=CSS, html=html, js=js)


GFX = []
_plan = os.path.join(L.WORK, "hook", "plan.json")
if os.path.exists(_plan):
    with open(_plan, encoding="utf-8") as _fh:
        _P = json.load(_fh)
    for _p in _P["phrases"]:
        GFX.append(phrase(_p["id"], _p["dur"], _p["lead"], _p["key"], _p["t_lead"], _p["t_key"], _p.get("size", 150)))
    if _P.get("sep"):
        GFX.append(sep(_P["sep"]))
