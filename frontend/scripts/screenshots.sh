#!/usr/bin/env bash
# Снимает скриншоты для слайдов через headless Chrome. Нужен запущенный `npm run dev` (:5173).
# По умолчанию — id пресетов живого бэкенда. Для моков: bash scripts/screenshots.sh mock
set -euo pipefail
cd "$(dirname "$0")/.."
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
OUT=screenshots
PROFILE="$(mktemp -d)"
mkdir -p "$OUT"
shot() { # name query width height
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$PROFILE" \
    --window-size="$3,$4" --force-device-scale-factor=2 --virtual-time-budget=12000 \
    --screenshot="$OUT/$1.png" "http://localhost:5173/?static=1&$2" >/dev/null 2>&1
  echo "→ $OUT/$1.png"
}
if [[ "${1:-}" == "mock" ]]; then
  WALK=megasilkway_walk; WINTER=kids_khan_shatyr; NIGHT=night_nurzhol; MOB=megasilkway_walk
else
  WALK=megasilkway_walk; WINTER=winter_evening; NIGHT=night_unusual; MOB=winter_evening
fi
rm -f "$OUT"/*.png
shot 00-start-desktop    "lang=ru"                 1600 900
shot 01-walk-desktop     "preset=$WALK"            1600 900
shot 02-winter-desktop   "preset=$WINTER"          1600 900
shot 03-night-kz-desktop "lang=kk&preset=$NIGHT"   1600 900
# headless Chrome не уже ~500 px и плохо снимает прокрутку — мобильные кадры без прокрутки
shot 04-mobile-start     "lang=kk"                 500 1080
shot 05-mobile-results   "lang=kk&preset=$MOB"             500 2300
rm -rf "$PROFILE"
