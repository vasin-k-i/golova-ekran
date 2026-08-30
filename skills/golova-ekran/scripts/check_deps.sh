#!/usr/bin/env bash
# Что нужно пайплайну и что из этого есть на машине.
set -u
ok=0; bad=0
say() { printf "  %-22s %s\n" "$1" "$2"; }
have() { command -v "$1" >/dev/null 2>&1; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# python из PATH и python, которым пайплайн будет работать, — часто разные:
# в homebrew-овском нет pillow и numpy и не будет (externally managed).
PY="$(PYTHONPATH="$HERE" python3 -c 'import lib; print(lib.pick_python() or "")' 2>/dev/null)"
[ -n "$PY" ] || PY=python3

echo "Обязательное"
for c in ffmpeg ffprobe; do
  if have "$c"; then say "$c" "✓ $(command -v $c)"; ok=$((ok+1))
  else say "$c" "✗ нет"; bad=$((bad+1)); fi
done
if have python3; then say "python3" "✓ $PY"; ok=$((ok+1))
else say "python3" "✗ нет"; bad=$((bad+1)); fi
if $PY -c "import PIL" 2>/dev/null; then say "python: pillow" "✓"; ok=$((ok+1))
else say "python: pillow" "✗ нет → /usr/bin/pip3 install --user pillow"; bad=$((bad+1)); fi
if $PY -c "import numpy" 2>/dev/null; then say "python: numpy" "✓"; ok=$((ok+1))
else say "python: numpy" "✗ нет → /usr/bin/pip3 install --user numpy"; bad=$((bad+1)); fi

echo
echo "Для поиска повторов и оговорок"
if have whisper-server; then say "whisper-server" "✓ $(command -v whisper-server)"
else say "whisper-server" "✗ нет → brew install whisper-cpp"; fi
MODEL="${WHISPER_MODEL:-$HOME/.whisper-models/ggml-large-v3.bin}"
if [ -f "$MODEL" ]; then say "модель whisper" "✓ $MODEL"
else say "модель whisper" "✗ нет $MODEL"; fi

echo
echo "Шрифты для инфографики"
PYTHONPATH="$HERE" $PY -c "
import lib
print('  %-22s OK  %s' % ('жирный', lib.font_path(True)))
print('  %-22s OK  %s' % ('обычный', lib.font_path(False)))
fb = lib.fallback_for('₽')
print('  %-22s %s' % ('знак рубля', ('OK  ' + fb[0]) if fb else '— нет ни в одном шрифте, ₽ не рисуй'))
" 2>/dev/null || echo "  ✗ шрифтов не нашёл → поставь fonts-dejavu или задай GEK_FONT_BOLD/GEK_FONT_REGULAR"

echo
if [ "$bad" -gt 0 ]; then
  echo "Не хватает обязательного: $bad. Поставь и запусти снова."
  echo "  macOS: brew install ffmpeg whisper-cpp && /usr/bin/pip3 install --user pillow numpy"
  echo "  Debian/Ubuntu: sudo apt install ffmpeg fonts-dejavu python3-pil python3-numpy"
  echo "  Пакеты есть, но в другом python — укажи его: export GEK_PYTHON=/путь/python3"
  exit 1
fi
echo "Обязательное на месте. Шаги пайплайна пойдут через $PY"
