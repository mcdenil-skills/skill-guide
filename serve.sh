#!/bin/bash
# Запускает Skill-Guide в «живом режиме»: гид на localhost с рабочей кнопкой «Обновить всё».
# Просто: ./serve.sh   (или ./serve.sh 9000 для своего порта)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || command -v python)"
# Windows: UTF-8 (см. update.sh) — наследуется в подпроцессы generate.py/check-updates.py.
export PYTHONUTF8=1
exec "$PY" "$DIR/serve.py" "$@"
