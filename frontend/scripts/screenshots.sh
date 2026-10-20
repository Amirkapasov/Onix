#!/usr/bin/env bash
# Снимает скриншоты для слайдов через headless Chrome. Нужен запущенный `npm run dev` (:5173).
# Использование: bash scripts/screenshots.sh [preset_desktop] [preset_night] [preset_kids] [preset_airport]
set -euo pipefail
cd "$(dirname "$0")/.."
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
OUT=screenshots
PROFILE="$(mktemp -d)"
mkdir -p "$OUT"
shot() { # name url width height
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$PROFILE" \
    --window-size="$3,$4" --force-device-scale-factor=2 --virtual-time-budget=9000 \
    --screenshot="$OUT/$1.png" "$2" >/dev/null 2>&1
  echo "→ $OUT/$1.png"
}
B=http://localhost:5173
shot 01-walk-desktop   "$B/?static=1&preset=${1:-megasilkway_walk}" 1600 900
shot 02-night-desktop  "$B/?static=1&preset=${2:-night_nurzhol}" 1600 900
shot 03-kids-mobile      "$B/?static=1&preset=${3:-kids_khan_shatyr}" 500 2400
shot 04-airport-kz     "$B/?static=1&lang=kk&preset=${4:-airport_2h}" 1600 900
rm -rf "$PROFILE"
