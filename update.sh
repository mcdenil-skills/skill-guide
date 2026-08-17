#!/bin/bash
# update.sh — пересобрать каталог скиллов вручную.
# Просто: ./update.sh   (или дёргается launchd-агентом автоматически)
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || command -v python)"
# Windows: системная кодировка (cp1251) ломает чтение overrides.json и вывод в консоль.
# Одна переменная включает UTF-8 во всех дочерних python-скриптах.
# Если запускать scripts/*.py напрямую, минуя эту обёртку, переменную нужно задать самому.
export PYTHONUTF8=1
# счётчики использования — локальный скан логов (быстро, без сети)
"$PY" "$DIR/scripts/usage-scan.py" >/dev/null 2>&1 || true
# пересборка каталога (подмешивает usage/updates/links, если есть)
"$PY" "$DIR/scripts/generate.py"
echo "[skill-guide] каталог обновлён: $(date '+%Y-%m-%d %H:%M:%S')"
echo "[skill-guide] проверить обновления скиллов:  ./update-skills.sh"
