# Монтажёр

Вариация golova-ekran для длинного YouTube-ролика в стиле живого монтажёра: человек во
весь кадр, вставки на каждом смысловом шаге, текст по видео, хук с переходами-кругами,
полноэкранная отбивка.

- **[GUIDE.md](GUIDE.md)** — гайдлайн: кадр, вставки, текст, хук, звук, приватность, проверка.
- `scripts/montazher.py` — точка входа (`montazher.py help` — все команды).
- `templates/` — заготовки `montazher.py` (конфиг) и `edl.py` (монтажный лист), их кладёт `init`.
- `example/` — лист и конфиг настоящего 17-минутного ролика и кадры каждого типа плана.

Нужно: всё, что для golova-ekran (ffmpeg, python3 с numpy и Pillow, whisper-cli с моделью),
плюс HyperFrames (node ≥ 22) для текста и маски «за человеком».

Быстрый старт — в папке, где уже сделан `montage.py cut`:

```
python3 ~/.claude/skills/golova-ekran/montazher/scripts/montazher.py init
python3 …/montazher.py words && python3 …/montazher.py audio
# правишь edl.py по GUIDE.md
python3 …/montazher.py check && python3 …/montazher.py texts && python3 …/montazher.py render probe
```
