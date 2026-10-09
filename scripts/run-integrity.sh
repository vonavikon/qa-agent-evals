#!/usr/bin/env bash
# Детектор вмешательства SUT-сессий в каталог прогона (находка selftest-v2: SUT
# записал 7 вердиктов до запуска судьи и перезапускал прогоны).
#
# Usage:
#   run-integrity.sh <run-dir> snapshot   - снять манифест контрольных сумм
#   run-integrity.sh <run-dir> verify     - сверить; расхождения - в stdout
# Выход verify: 0 - каталоr неизменен (или менялись только прогоны/протоколы/вердикты),
#               1 - посторонние изменения (вмешательство или потеря файлов).

set -u

DIR="${1:?Usage: run-integrity.sh <run-dir> snapshot|verify}"
MODE="${2:?snapshot | verify}"
MANIFEST="$DIR/.integrity-manifest.txt"

case "$MODE" in
snapshot)
  # md5sum в Linux/GitBash; на системах только с md5 - fallback.
  MD5=md5sum; command -v md5sum >/dev/null 2>&1 || MD5="md5 -r"
  ( cd "$DIR" && find . -type f ! -name ".integrity-manifest.txt" -print0 \
      | sort -z | xargs -0 $MD5 ) > "$MANIFEST"
  echo "манифест: $MANIFEST ($(wc -l <"$MANIFEST") файлов)"
  ;;
verify)
  MD5=md5sum; command -v md5sum >/dev/null 2>&1 || MD5="md5 -r"
  [ -f "$MANIFEST" ] || { echo "манифеста нет - снимите snapshot до прогона"; exit 1; }
  ( cd "$DIR" && find . -type f ! -name ".integrity-manifest.txt" -print0 \
      | sort -z | xargs -0 $MD5 ) > "$MANIFEST.new"
  # Допустимые зоны изменения: результаты работы конвейера. Всё остальное
  # (карточки, профиль, дым) менять после snapshot нельзя.
  diff_out="$(diff "$MANIFEST" "$MANIFEST.new" | grep -E "^[<>]" || true)"
  violations="$(printf '%s\n' "$diff_out" | grep -E "^[<>] .*(карточки/|профиль|дым)" || true)"
  if [ -n "$violations" ]; then
    echo "ВМЕШАТЕЛЬСТВО: изменены контролируемые файлы:"
    printf '%s\n' "$violations"
    exit 1
  fi
  added="$(printf '%s\n' "$diff_out" | grep "^> " | wc -l)"
  removed="$(printf '%s\n' "$diff_out" | grep "^< " | wc -l)"
  echo "контроль чист: карточки/профиль/дым неизменны; новых файлов $added, удалено $removed (зоны результатов)"
  rm -f "$MANIFEST.new"
  ;;
esac
