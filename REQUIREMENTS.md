# Что нужно, чтобы работало

## Обязательно

- **ffmpeg / ffprobe** — вся резка, композит и рендер.
  `brew install ffmpeg` · `sudo apt install ffmpeg`
- **python3** ≥ 3.9 с **pillow** и **numpy**.
  `pip3 install pillow numpy` · `sudo apt install python3-pil python3-numpy`

  ⚠️ На маке пакеты часто нужны **не в том python3, который первым в PATH**: homebrew-овский
  «externally managed» и на `pip3 install` отвечает отказом, а системный `/usr/bin/python3`
  обычно уже укомплектован. Пайплайн это учитывает — сам ищет интерпретатор, в котором
  pillow и numpy реально импортируются, и гоняет шаги через него. `montage.py check`
  печатает, какой выбран. Нужен конкретный — `export GEK_PYTHON=/путь/python3`.
  Ставить в системный: `/usr/bin/pip3 install --user pillow numpy`.
- **Шрифт с кириллицей.** На macOS берётся Arial, на Linux — DejaVu или Liberation.
  Свой: `export GEK_FONT_BOLD=/путь/Bold.ttf GEK_FONT_REGULAR=/путь/Regular.ttf`

## Для поиска повторов и оговорок

- **whisper.cpp** с бинарём `whisper-server`. `brew install whisper-cpp`
- **Модель** `ggml-large-v3.bin` в `~/.whisper-models/`:
  ```bash
  mkdir -p ~/.whisper-models && curl -L -o ~/.whisper-models/ggml-large-v3.bin \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin
  ```
  Модель весит ~3 ГБ. Можно взять `ggml-medium.bin` полегче — качество на коротких
  клипах заметно хуже, но для поиска повторов обычно хватает:
  `export WHISPER_MODEL=~/.whisper-models/ggml-medium.bin`

Работает, если есть хотя бы несколько гигабайт видеопамяти. Без неё считает на процессоре —
медленнее, но считает.

## Переменные окружения

| | зачем |
|---|---|
| `GEK_PROJECT` | папка проекта, если запускаешь не из неё |
| `GEK_PYTHON` | интерпретатор для шагов, если автопоиск выбрал не тот |
| `WHISPER_URL` | адрес whisper-server, по умолчанию `http://127.0.0.1:8178/inference` |
| `WHISPER_MODEL` | путь к модели |
| `GEK_FONT_BOLD` / `GEK_FONT_REGULAR` | свои шрифты |
| `FFMPEG` / `FFPROBE` | свои сборки ffmpeg |

## Сколько это считает

Девятиминутный ролик из пяти дублей: расшифровка ~2 минуты, резка ~2 минуты,
сборка кадра ~1,5 минуты, мастер ~20 секунд. Пересборка одного блока — секунды.
