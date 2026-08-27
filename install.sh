#!/usr/bin/env bash
#
# Скилл «Голова + экран» — установка в Claude Code и/или Codex.
# Формат скиллов одинаковый, разница только в папке:
#   Claude Code → ~/.claude/skills/golova-ekran
#   Codex       → ~/.codex/skills/golova-ekran   (или $CODEX_HOME/skills)
#
#   curl -fsSL https://raw.githubusercontent.com/vasin-k-i/golova-ekran/main/install.sh | bash
#   bash install.sh --claude        # только в Claude Code
#   bash install.sh --codex         # только в Codex
#   bash install.sh --dest ПАПКА    # в произвольную папку скиллов
#
set -euo pipefail

TARBALL="${GEK_TARBALL:-https://github.com/vasin-k-i/golova-ekran/archive/refs/heads/main.tar.gz}"
SKILL="golova-ekran"

WANT_CLAUDE=0; WANT_CODEX=0; DEST=""
for a in "$@"; do
  case "$a" in
    --claude) WANT_CLAUDE=1 ;;
    --codex)  WANT_CODEX=1 ;;
    --all)    WANT_CLAUDE=1; WANT_CODEX=1 ;;
    --dest)   DEST="__next__" ;;
    --help|-h) sed -n '2,13p' "$0"; exit 0 ;;
    *) [ "${DEST}" = "__next__" ] && DEST="$a" ;;
  esac
done

if [ "${WANT_CLAUDE}" = "0" ] && [ "${WANT_CODEX}" = "0" ] && [ -z "${DEST}" ]; then
  [ -d "${HOME}/.claude" ] && WANT_CLAUDE=1
  [ -d "${CODEX_HOME:-${HOME}/.codex}" ] && WANT_CODEX=1
  [ "${WANT_CLAUDE}" = "0" ] && [ "${WANT_CODEX}" = "0" ] && WANT_CLAUDE=1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
if [ -f "${HERE}/skills/${SKILL}/SKILL.md" ]; then
  SRC="${HERE}/skills/${SKILL}"
  echo "Ставлю из локальной копии: ${SRC}"
else
  command -v curl >/dev/null 2>&1 || { echo "✗ нужен curl" >&2; exit 1; }
  command -v tar  >/dev/null 2>&1 || { echo "✗ нужен tar"  >&2; exit 1; }
  TMP="$(mktemp -d)"; trap 'rm -rf "${TMP}"' EXIT
  echo "Скачиваю скилл «Голова + экран»…"
  curl -fsSL "${TARBALL}" -o "${TMP}/gek.tar.gz"
  tar -xzf "${TMP}/gek.tar.gz" -C "${TMP}"
  SRC="$(find "${TMP}" -type d -path "*/skills/${SKILL}" | head -1)"
  [ -n "${SRC}" ] || { echo "✗ не нашёл скилл в архиве" >&2; exit 1; }
fi

put() {
  local dest="$1"
  mkdir -p "${dest}"
  rm -rf "${dest}/${SKILL}"
  cp -R "${SRC}" "${dest}/${SKILL}"
  chmod +x "${dest}/${SKILL}/scripts/"*.py "${dest}/${SKILL}/scripts/"*.sh 2>/dev/null || true
  echo "  ✓ ${dest}/${SKILL}"
}

echo "Устанавливаю:"
[ "${WANT_CLAUDE}" = "1" ] && put "${HOME}/.claude/skills"
[ "${WANT_CODEX}"  = "1" ] && put "${CODEX_HOME:-${HOME}/.codex}/skills"
[ -n "${DEST}" ] && [ "${DEST}" != "__next__" ] && put "${DEST}"

echo
echo "Проверяю, что нужно машине:"
bash "${SRC}/scripts/check_deps.sh" || true

cat <<'TXT'

Готово. Перезапусти агента и скажи, например:

    смонтируй ролик из папки ~/Movies/урок — там телефон и запись экрана

Дальше он сам: посмотрит файлы, синхронизирует дорожки, вырежет тишину,
найдёт повторы и покажет список до резки.
TXT
