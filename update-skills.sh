#!/bin/bash
# update-skills.sh — обновление скиллов ПО ТВОЕЙ КОМАНДЕ (ничего молча).
#
#   ./update-skills.sh          — показать, что можно обновить (только чтение)
#   ./update-skills.sh --apply  — применить git-обновления (gstack + витрины) и пересобрать статус
#
# ВАЖНО про границы:
#  • gstack и витрины плагинов — это git-репозитории, их тянем безопасно (git pull).
#  • Сами плагины (superpowers и др.) переустанавливает Claude командой  /plugin  —
#    скрипт это НЕ делает за тебя, только подсказывает. gstack-скиллы правильно
#    обновляет скилл  gstack-upgrade.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || command -v python)"
GSTACK="$HOME/.claude/skills/gstack"
MARKETS="$HOME/.claude/plugins/marketplaces"
# Windows: UTF-8 вместо системной cp1251 (см. update.sh).
export PYTHONUTF8=1

echo "== Skill-Guide: обновления =="
"$PY" "$DIR/scripts/check-updates.py" || true

if [ "${1:-}" != "--apply" ]; then
  echo
  echo "Это был показ статуса. Чтобы применить git-обновления:  ./update-skills.sh --apply"
  echo "Плагины обновляй в Claude:  /plugin   ·  gstack-скиллы:  скилл gstack-upgrade"
  exit 0
fi

echo
echo "== Применяю git-обновления =="

if [ -d "$GSTACK/.git" ]; then
  echo "-> gstack: git pull"
  git -C "$GSTACK" pull --ff-only 2>&1 | sed 's/^/   /' || echo "   (пропущено; попробуй скилл gstack-upgrade)"
fi

if [ -d "$MARKETS" ]; then
  for mp in "$MARKETS"/*/; do
    [ -d "$mp/.git" ] || continue
    echo "-> витрина $(basename "$mp"): git pull"
    git -C "$mp" pull --ff-only 2>&1 | sed 's/^/   /' || echo "   (пропущено)"
  done
fi

echo
echo "== Пересобираю статус и каталог =="
"$PY" "$DIR/scripts/check-updates.py" || true
"$PY" "$DIR/scripts/generate.py"

echo
echo "Готово. Плагины (superpowers и др.) доустанови в Claude:  /plugin update <имя>"
echo "gstack-скиллы, если верхние копии не подхватились:  запусти скилл gstack-upgrade"
