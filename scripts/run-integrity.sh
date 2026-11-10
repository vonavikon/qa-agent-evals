#!/usr/bin/env bash
# Detector for SUT-session tampering with the run directory (selftest-v2 finding:
# the SUT wrote 7 verdicts before the judge ran and restarted runs).
#
# Usage:
#   run-integrity.sh <run-dir> snapshot   - take a checksum manifest
#   run-integrity.sh <run-dir> verify     - compare; mismatches go to stdout
# Exit verify: 0 - the directory is unchanged (or only прогоны/протоколы/вердикты
#              changed), 1 - foreign changes (tampering or lost files).

set -u

DIR="${1:?Usage: run-integrity.sh <run-dir> snapshot|verify}"
MODE="${2:?snapshot | verify}"
MANIFEST="$DIR/.integrity-manifest.txt"

case "$MODE" in
snapshot)
  # md5sum on Linux/GitBash; fallback to plain md5 where that is all there is.
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
  # Allowed change zones: pipeline outputs. Everything else
  # (карточки/, профиль, дым) must not change after the snapshot.
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
