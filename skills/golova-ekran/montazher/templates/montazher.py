# Конфиг «Монтажёра» — лежит рядом с project.py основного пайплайна golova-ekran.
# Пути — относительно этой папки. Стиль и правила — GUIDE.md скилла.

HEAD = "work/head_cut.mp4"         # голова, нарезанная по речи (`montage.py cut`)
AUDIO = "work/master_audio.wav"    # звук мастера (`montazher.py audio`)
PLAN = "work/plan.json"            # карта вырезов (`montage.py plan`)
WORDS = "work/words.json"          # пословные таймкоды (`montazher.py words`)
FONTS = "fonts"                    # Montserrat[wght].ttf + Montserrat-Italic[wght].ttf (`montazher.py init`)
EDL = "edl.py"                     # монтажный лист: SHOTS, TEXTS, PROBE
OUT = "out/Ролик — монтаж.mp4"

# центр лица в кадре головы, px 1920×1080 (по контактному листу work/probe/*_head.jpg):
# от него считаются наезды, окно камеры в углу и голова сбоку
FACE = (960, 400)
ACCENT = "#FFD23F"                 # цвет акцентного слова в тексте по видео
GRADE = "eq=contrast=1.04:saturation=1.06:brightness=0.005"
# AUDIO_CHAIN = "highpass=f=75,acompressor=…,alimiter=…"   # своя цепочка звука, если мастер не −14 LUFS

# Хук — 6–10 ударных фраз встык. Каждую границу проверь расшифровкой клипа!
# (дубль, начало речи, конец речи, подводка мелко, КЛЮЧ крупно, когда ключ от начала фразы, кегль ключа)
HOOK = dict(
    phrases=[
        # ("01", 70.55, 72.38, "это", "самый простой бизнес", 0.05, 104),
    ],
    music=None,                    # "work/music/hook_bed.mp3" — подложка под хук (обрыв в конце)
    title=("Имя Фамилия", "ТЕМА"), # отбивка: надстрочник и титул
    # gradient=("#e80004", "#f25a05", "#ffd000"), circ=0.55, gap=0.03, sep=1.4, gain_db=-3.5, music_db=-16,
    # zoom=[1.0, 1.22, 1.0, 1.25],  # крупность фраз по кругу
    # sources={"01": "/путь/IMG_0001.MOV"},  # если дубля нет в project.py
)
