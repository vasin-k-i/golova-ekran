// помощники анимации — всё через один paused-таймлайн, без таймеров (HyperFrames
// сам перематывает таймлайн на каждый кадр). Вход ease-out 0,4–0,7 с, каскад
// 60–80 мс, выход быстрее входа.
window.HF = {
  inUp(tl, sel, t, o = {}) { return tl.fromTo(sel, { opacity: 0, y: o.y ?? 36 }, { opacity: 1, y: 0, duration: o.d ?? 0.55, ease: o.ease ?? "power3.out", stagger: o.st ?? 0.07 }, t); },
  inLeft(tl, sel, t, o = {}) { return tl.fromTo(sel, { opacity: 0, x: o.x ?? -60 }, { opacity: 1, x: 0, duration: o.d ?? 0.6, ease: "power3.out", stagger: o.st ?? 0.07 }, t); },
  pop(tl, sel, t, o = {}) { return tl.fromTo(sel, { opacity: 0, scale: o.s ?? 0.82 }, { opacity: 1, scale: 1, duration: o.d ?? 0.5, ease: "back.out(1.7)", stagger: o.st ?? 0.08 }, t); },
  out(tl, sel, t, o = {}) { return tl.to(sel, { opacity: 0, x: o.x ?? -40, y: o.y ?? 0, duration: o.d ?? 0.3, ease: "power2.in", stagger: o.st ?? 0 }, t); },
  fade(tl, sel, t, to = 0, d = 0.3) { return tl.to(sel, { opacity: to, duration: d, ease: "power2.inOut" }, t); },
  strike(tl, row, t) {
    tl.fromTo(row + " .strike", { scaleX: 0 }, { scaleX: 1, duration: 0.35, ease: "power2.inOut" }, t);
    return tl.to(row + " .txt", { color: "#5C6170", duration: 0.3 }, t + 0.1);
  },
  grow(tl, sel, t, d = 0.8, to = 1) { return tl.fromTo(sel, { scaleX: 0 }, { scaleX: to, duration: d, ease: "power3.out" }, t); },
  count(tl, el, from, to, t, d, fmt) {
    const node = document.querySelector(el), p = { v: from };
    node.textContent = fmt(from);
    return tl.to(p, { v: to, duration: d, ease: "power2.out", onUpdate: () => { node.textContent = fmt(p.v); } }, t);
  },
  num(n) { return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " "); },
};
