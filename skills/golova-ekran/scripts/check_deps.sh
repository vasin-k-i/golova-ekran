#!/usr/bin/env bash
# Что нужно пайплайну и что из этого есть на машине.
set -u
ok=0; bad=0
say() { printf "  %-22s %s\n" "$1" "$2"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "Обязательное"
for c in ffmpeg ffprobe python3; do
  if have "$c"; then say "$c" "✓ $(command -v $c)"; ok=$((ok+1))
  else say "$c" "✗ нет"; bad=$((bad+1)); fi
done
if python3 -c "import PIL" 2>/dev/null; then say "python: pillow" "✓"; ok=$((ok+1))
else say "python: pillow" "✗ нет → pip3 install pillow"; bad=$((bad+1)); fi
if python3 -c "import numpy" 2>/dev/null; then say "python: numpy" "✓"; ok=$((ok+1))
else say "python: numpy" "✗ нет → pip3 install numpy"; bad=$((bad+1)); fi

echo
echo "Для поиска повторов и оговорок"
if have whisper-server; then say "whisper-server" "✓ $(command -v whisper-server)"
else say "whisper-server" "✗ нет → brew install whisper-cpp"; fi
MODEL="${WHISPER_MODEL:-$HOME/.whisper-models/ggml-large-v3.bin}"
if [ -f "$MODEL" ]; then say "модель whisper" "✓ $MODEL"
else say "модель whisper" "✗ нет $MODEL"; fi

echo
echo "Шрифты для инфографики"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PYTHONPATH="$HERE" python3 -c "
import lib
print('  %-22s OK  %s' % ('жирный', lib.font_path(True)))
print('  %-22s OK  %s' % ('обычный', lib.font_path(False)))
fb = lib.fallback_for('₽')
print('  %-22s %s' % ('знак рубля', ('OK  ' + fb[0]) if fb else '— нет ни в одном шрифте, ₽ не рисуй'))
" 2>/dev/null || echo "  ✗ шрифтов не нашёл → поставь fonts-dejavu или задай GEK_FONT_BOLD/GEK_FONT_REGULAR"

echo
if [ "$bad" -gt 0 ]; then
  echo "Не хватает обязательного: $bad. Поставь и запусти снова."
  echo "  macOS: brew install ffmpeg whisper-cpp && pip3 install pillow numpy"
  echo "  Debian/Ubuntu: sudo apt install ffmpeg fonts-dejavu python3-pil python3-numpy"
  exit 1
fi
echo "Обязательное на месте."
