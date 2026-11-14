#!/usr/bin/env bash
# CLI runner for single-turn acceptance cards (phase D).
# Runs obvious/critical/adversarial cards directly through the adapter
# (knowledge/adapters.md), N repeats, transcripts in runs/<date>-<sut>/прогоны/.
# Multi-turn convoluted cards are not run by the runner - a role-user subagent drives them.
#
# Usage: run-cards.sh <cards-dir> <sut-plugin-dir> <run-dir> [repeats=2] [max-turns=20] [skill-md]
#   skill-md - path to the tested skill's SKILL.md: enables guaranteed
#   activation (--append-system-prompt-file). Required for a skill SUT.
# Exit: 0 - every run produced a non-empty transcript; 1 - some were empty (raise max-turns).

set -u

# Git Bash converts POSIX arguments to Windows paths (/workspace -> X:/Git/workspace)
# and breaks container arguments; disable the conversion for this script
export MSYS_NO_PATHCONV=1

CARDS_DIR="${1:?Usage: run-cards.sh <cards-dir> <sut-plugin-dir> <run-dir> [repeats] [max-turns] [skill-md]}"
SUT_DIR="${2:?нет пути к плагину SUT}"
RUN_DIR="${3:?нет каталога прогона}"
REPEATS="${4:-2}"
MAX_TURNS="${5:-20}"
SKILL_MD="${6:-}"

# Absolute paths: the script cds into per-run working dirs, after which
# relative arguments break. Empty cd result = no such directory.
CARDS_DIR="$(cd "$CARDS_DIR" 2>/dev/null && pwd)" || true
SUT_DIR="$(cd "$SUT_DIR" 2>/dev/null && pwd)" || true
RUN_DIR="$(cd "$RUN_DIR" 2>/dev/null && pwd)" || true
[ -d "$CARDS_DIR" ] || { echo "нет каталога карточек: $1" >&2; exit 1; }
[ -d "$SUT_DIR" ] || { echo "нет каталога SUT: $2" >&2; exit 1; }
[ -d "$RUN_DIR" ] || { echo "нет каталога прогона: $3" >&2; exit 1; }
[ -n "$SKILL_MD" ] && SKILL_MD="$(cd "$(dirname "$SKILL_MD")" && pwd)/$(basename "$SKILL_MD")"

ASP=()
[ -n "$SKILL_MD" ] && ASP=(--append-system-prompt-file "$SKILL_MD")
# Invocation: "${ASP[@]+${ASP[@]}}" - safe expansion of an empty array under set -u.

# The run language is fixed per call (field run 2026-11-12: the host's global
# "language": "Russian" CLI setting leaked into the SUT session and it answered
# Russian to English cards). The flag beats the host config; QA_EVALS_LANG
# overrides the default English.
SUT_SETTINGS=(--settings "{\"language\":\"${QA_EVALS_LANG:-English}\"}")

OUT_DIR="$RUN_DIR/прогоны"
mkdir -p "$OUT_DIR"

# Isolation level (knowledge/sandbox.md): host - as before; docker -
# a container with one work dir per run (unique mktemp), a copy of the SUT
# and the CLI config inside, network off. Fail-closed: docker unavailable - stop.
SANDBOX="${QA_EVALS_SANDBOX:-host}"
SB="$(dirname "$0")/sandbox.py"
SBWORK=""
if [ "$SANDBOX" = "docker" ]; then
  python "$SB" verify docker || exit 1
  SBWORK=$(python "$SB" prepare docker "$SUT_DIR" "$RUN_DIR" | python -c "import json,sys; print(json.load(sys.stdin)['work'])")
  [ -n "$SBWORK" ] || { echo "sandbox prepare не дал work" >&2; exit 1; }
  if [ -n "$SKILL_MD" ]; then
    # ASP file goes into the ro SUT copy: /workspace is now tmpfs, sut is mounted ro
    cp "$SKILL_MD" "$SBWORK/sut/qa-eval-skill.md"; SKILL_MD_INSIDE="/workspace/sut/qa-eval-skill.md"
  else SKILL_MD_INSIDE=""; fi
  echo "изоляция: docker, work=$SBWORK (meta-sandbox.json в прогоне)"
fi

# Extract a field from a card: a second-level YAML field (scalar or literal block).
# The card format is fixed by the taxonomy - a simple parser is enough.
# A literal block holds blank lines inside it (field run 2026-11-12: CR-01's
# replica was cut to 96 bytes at the first blank line and re-issued); a
# non-indented line ends the block.
yaml_field() { # $1=file $2=field name
  awk -v key="$2" '
    $0 ~ "^"key":" {
      val = substr($0, index($0, ":") + 1)
      sub(/^[ \t]+/, "", val)
      if (val == "|" || val == ">") { block = 1; next }
      print val; exit
    }
    block && /^[ \t]+/ { print substr($0, 3); next }
    block && /^$/ { print ""; next }
    block { exit }
  ' "$1"
}

# Extract turn 1 from instruction (the «Ход 1: ...» line); if the turn structure
# is not found - the whole instruction is treated as a single-turn message.
first_turn() { # $1=instruction
  printf '%s\n' "$1" | awk '
    match($0, /Ход 1:/) {
      s = substr($0, RSTART + RLENGTH)
      gsub(/^[ «]+|[ »]+$/, "", s)
      print s; found = 1; exit
    }
    END { if (!found) print "NOTURNS" }
  '
}

empty=0
for card in "$CARDS_DIR"/*.yaml; do
  [ -e "$card" ] || { echo "нет карточек в $CARDS_DIR"; exit 1; }
  id="$(yaml_field "$card" id)"
  type="$(yaml_field "$card" type)"
  instr="$(yaml_field "$card" instruction)"
  turn="$(first_turn "$instr")"
  if [ "$turn" = "NOTURNS" ]; then
    turn="$instr"
  elif printf '%s\n' "$instr" | grep -q "Ход 2"; then
    echo "== $id ($type): SKIP - многоходовая, ведёт субагент role-user"
    continue
  fi
  echo "== $id ($type)"

  for r in $(seq 1 "$REPEATS"); do
    out="$OUT_DIR/$id-r$r.txt"
    if [ "$SANDBOX" = "docker" ]; then
      work="$SBWORK"
      rm -rf "$work/out"/* 2>/dev/null; mkdir -p "$work/out"
    else
      work="/tmp/qa-evals-run-$id-r$r"
      rm -rf "$work"; mkdir -p "$work"
    fi
    # docker: /workspace is tmpfs, put readable files into mounted locations
    if [ "$SANDBOX" = "docker" ]; then
      printf '{"mcpServers": {}}' > "$work/out/mcp-empty.json"
    else
      printf '{"mcpServers": {}}' > "$work/mcp-empty.json"
    fi
    # The user message goes to a separate file: the transcript stores only SUT
    # answers so grep markers do not match words from the message itself.
    printf '%s\n' "$turn" > "$OUT_DIR/$id-r$r.replica.txt"
    # Run log: the session event stream (tool calls with paths - answer provenance).
    # Env scrubbing for the SUT session (review P0-1): variable allowlist; the
    # tester's secrets (gateway keys, tokens) are not inherited. Off: QA_EVALS_SCRUB_ENV=0
    SCRUB=()
    if [ "${QA_EVALS_SCRUB_ENV:-1}" = "1" ]; then
      SCRUB=(env -i PATH="$PATH" HOME="$HOME" USERPROFILE="$USERPROFILE" \
             TEMP="$TEMP" TMP="$TMP" SYSTEMROOT="$SYSTEMROOT" SYSTEMDRIVE="$SYSTEMDRIVE" \
             COMSPEC="$COMSPEC" APPDATA="$APPDATA" LOCALAPPDATA="$LOCALAPPDATA")
    fi
    if [ "$SANDBOX" = "docker" ]; then
      ASPD=()
      [ -n "$SKILL_MD_INSIDE" ] && ASPD=(--append-system-prompt-file "$SKILL_MD_INSIDE")
      mapfile -t DCMD < <(python "$SB" wrap docker "$work" -- claude -p \
        --plugin-dir /workspace/sut --max-turns "$MAX_TURNS" \
        --disallowedTools Skill,WebFetch,WebSearch,webReader,webSearch --strict-mcp-config --mcp-config /workspace/out/mcp-empty.json \
        "${SUT_SETTINGS[@]}" ${ASPD[@]+"${ASPD[@]}"} --output-format stream-json --verbose | \
        python -c "import json,sys; [print(x) for x in json.load(sys.stdin)]" | tr -d '\r')
      # wall-time session limit (SEC-04): a stuck process gets cut off
      printf '%s\n' "$turn" | MSYS_NO_PATHCONV=1 timeout "${QA_EVALS_SUT_TIMEOUT:-900}" \
        "${DCMD[@]}" \
        > "$OUT_DIR/$id-r$r.events.jsonl" 2>"$OUT_DIR/$id-r$r.err"
    else
      ( cd "$work" && printf '%s\n' "$turn" | \
          "${SCRUB[@]}" claude -p --plugin-dir "$SUT_DIR" --max-turns "$MAX_TURNS" \
          --disallowedTools Skill --strict-mcp-config --mcp-config "$work/mcp-empty.json" \
          "${SUT_SETTINGS[@]}" ${ASP[@]+"${ASP[@]}"} --output-format stream-json --verbose \
          > "$OUT_DIR/$id-r$r.events.jsonl" 2>"$OUT_DIR/$id-r$r.err" )
    fi
    # Log parsing: scripts/parse-events.py writes .txt/.prov.txt/.diag.txt
    # (the path is passed POSIX-style by the script; the module converts /c/... to C:\... itself).
    python "$(dirname "$0")/parse-events.py" "$RUN_DIR" "$id" "r$r"
    # Move SUT artifacts from the work dir into the run (an artifact outside
    # the transcript is also evidence), then wipe the work dir and the CLI
    # session log: evidence lives in runs/, no copies stay in /tmp or the CLI profile.
    # docker: work is shared per run (SUT copy inside) - not touched between
    # repeats; no CLI session tails (container is --rm).
    arts="$OUT_DIR/$id-r$r.artifacts"
    if [ "$SANDBOX" = "docker" ]; then
      for f in "$work/out"/*; do
        [ -e "$f" ] || continue
        [ "$(basename "$f")" = "mcp-empty.json" ] && continue
        mkdir -p "$arts"
        cp -r "$f" "$arts/"
        echo "   r$r: артефакт SUT: $(basename "$f")"
      done
      rm -rf "$work/out"; mkdir -p "$work/out"
    else
      for f in "$work"/*; do
        [ -e "$f" ] || continue
        [ "$(basename "$f")" = "mcp-empty.json" ] && continue
        mkdir -p "$arts"
        cp -r "$f" "$arts/"
        echo "   r$r: артефакт SUT: $(basename "$f")"
      done
      rm -rf "$work"
      proj="$HOME/.claude/projects/$(cygpath -w "$work" | sed 's|[:\\.]|-|g')"
      [ -d "$proj" ] && rm -rf "$proj"
    fi
    if [ -s "$out" ]; then
      echo "   r$r: $(wc -c <"$out") байт"
    else
      echo "   r$r: ПУСТО (см. $OUT_DIR/$id-r$r.err - поднять max-turns?)"
      empty=1
    fi
  done
done

# docker: the single work dir lives until the end of the run - wiped after all cards
if [ "$SANDBOX" = "docker" ] && [ -n "$SBWORK" ]; then
  python "$SB" cleanup "$SBWORK"
fi

exit $empty
