#!/usr/bin/env bash
# CLI-раннер одноходовых карточек приёмки (фаза D).
# Прогоняет obvious/critical/adversarial-карточки напрямую через адаптер
# (knowledge/adapters.md), N повторов, транскрипты в runs/<дата>-<sut>/прогоны/.
# Многоходовые convoluted-карточки раннером не гоняются - их ведёт субагент role-user.
#
# Usage: run-cards.sh <cards-dir> <sut-plugin-dir> <run-dir> [repeats=2] [max-turns=20] [skill-md]
#   skill-md - путь к SKILL.md тестируемого скилла: включает гарантированную
#   активацию (--append-system-prompt-file). Для скилл-SUT обязателен.
# Выход: 0 - все прогоны дали непустой транскрипт; 1 - были пустые (поднять max-turns).

set -u

# Git Bash конвертирует POSIX-аргументы в Windows-пути (/workspace -> X:/Git/workspace)
# и ломает аргументы контейнера; для этого скрипта конверсию отключаем
export MSYS_NO_PATHCONV=1

CARDS_DIR="${1:?Usage: run-cards.sh <cards-dir> <sut-plugin-dir> <run-dir> [repeats] [max-turns] [skill-md]}"
SUT_DIR="${2:?нет пути к плагину SUT}"
RUN_DIR="${3:?нет каталога прогона}"
REPEATS="${4:-2}"
MAX_TURNS="${5:-20}"
SKILL_MD="${6:-}"

# Абсолютные пути: скрипт делает cd в рабочие папки прогонов -
# относительные аргументы после этого ломаются. Пустой результат cd = каталога нет.
CARDS_DIR="$(cd "$CARDS_DIR" 2>/dev/null && pwd)" || true
SUT_DIR="$(cd "$SUT_DIR" 2>/dev/null && pwd)" || true
RUN_DIR="$(cd "$RUN_DIR" 2>/dev/null && pwd)" || true
[ -d "$CARDS_DIR" ] || { echo "нет каталога карточек: $1" >&2; exit 1; }
[ -d "$SUT_DIR" ] || { echo "нет каталога SUT: $2" >&2; exit 1; }
[ -d "$RUN_DIR" ] || { echo "нет каталога прогона: $3" >&2; exit 1; }
[ -n "$SKILL_MD" ] && SKILL_MD="$(cd "$(dirname "$SKILL_MD")" && pwd)/$(basename "$SKILL_MD")"

ASP=()
[ -n "$SKILL_MD" ] && ASP=(--append-system-prompt-file "$SKILL_MD")
# Вызов: "${ASP[@]+${ASP[@]}}" - безопасное раскрытие пустого массива под set -u.

OUT_DIR="$RUN_DIR/прогоны"
mkdir -p "$OUT_DIR"

# Уровень изоляции (knowledge/sandbox.md): host - как раньше; docker -
# контейнер, единый work на прогон (уникальный mktemp), копия SUT и конфиг
# CLI внутри, сеть off. Fail-closed: docker недоступен - стоп.
SANDBOX="${QA_EVALS_SANDBOX:-host}"
SB="$(dirname "$0")/sandbox.py"
SBWORK=""
if [ "$SANDBOX" = "docker" ]; then
  python "$SB" verify docker || exit 1
  SBWORK=$(python "$SB" prepare docker "$SUT_DIR" "$RUN_DIR" | python -c "import json,sys; print(json.load(sys.stdin)['work'])")
  [ -n "$SBWORK" ] || { echo "sandbox prepare не дал work" >&2; exit 1; }
  if [ -n "$SKILL_MD" ]; then
    cp "$SKILL_MD" "$SBWORK/skill.md"; SKILL_MD_INSIDE="/workspace/skill.md"
  else SKILL_MD_INSIDE=""; fi
  echo "изоляция: docker, work=$SBWORK (meta-sandbox.json в прогоне)"
fi

# Извлечь поле из карточки: поле 2-го уровня YAML (скаляр или literal-блок).
# Формат карточек фиксирован таксономией - простого парсера достаточно.
yaml_field() { # $1=файл $2=имя поля
  awk -v key="$2" '
    $0 ~ "^"key":" {
      val = substr($0, index($0, ":") + 1)
      sub(/^[ \t]+/, "", val)
      if (val == "|" || val == ">") { block = 1; next }
      print val; exit
    }
    block && /^[ \t]+/ { print substr($0, 3); next }
    block { exit }
  ' "$1"
}

# Извлечь ход 1 из instruction (строка «Ход 1: «...»»); если структура ходов
# не найдена - вся инструкция считается одноходовой репликой.
first_turn() { # $1=инструкция
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
    printf '{"mcpServers": {}}' > "$work/mcp-empty.json"
    # Реплика - отдельным файлом: транскрипт хранит только ответы SUT,
    # чтобы grep-маркеры не ловили слова самой реплики.
    printf '%s\n' "$turn" > "$OUT_DIR/$id-r$r.replica.txt"
    # Лог прогона: поток событий сессии (tool-вызовы с путями - провенанс ответа).
    # Env-очистка SUT-сессии (review P0-1): белый список переменных; секреты
    # тестировщика (ключи шлюзов, токены) не наследуются. Выключить: QA_EVALS_SCRUB_ENV=0
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
        --disallowedTools Skill,WebFetch,WebSearch,webReader,webSearch --strict-mcp-config --mcp-config /workspace/mcp-empty.json \
        ${ASPD[@]+"${ASPD[@]}"} --output-format stream-json --verbose | \
        python -c "import json,sys; [print(x) for x in json.load(sys.stdin)]" | tr -d '\r')
      printf '%s\n' "$turn" | MSYS_NO_PATHCONV=1 "${DCMD[@]}" \
        > "$OUT_DIR/$id-r$r.events.jsonl" 2>"$OUT_DIR/$id-r$r.err"
    else
      ( cd "$work" && printf '%s\n' "$turn" | \
          "${SCRUB[@]}" claude -p --plugin-dir "$SUT_DIR" --max-turns "$MAX_TURNS" \
          --disallowedTools Skill --strict-mcp-config --mcp-config "$work/mcp-empty.json" \
          ${ASP[@]+"${ASP[@]}"} --output-format stream-json --verbose \
          > "$OUT_DIR/$id-r$r.events.jsonl" 2>"$OUT_DIR/$id-r$r.err" )
    fi
    # Разбор лога: модуль scripts/parse-events.py пишет .txt/.prov.txt/.diag.txt
    # (путь передаётся POSIX-скриптом, модуль сам конвертирует /c/... в C:\...).
    python "$(dirname "$0")/parse-events.py" "$RUN_DIR" "$id" "r$r"
    # Артефакты SUT из рабочей папки - в прогон (артефакт вне транскрипта -
    # тоже доказательство), затем рабочую папку и сессионный лог CLI затереть:
    # доказательства живут в runs/, в /tmp и профиле CLI копий не остаётся.
    # docker: work общий на прогон (копия SUT внутри) - между повторами не
    # трогаем, сессионных хвостов CLI нет (контейнер --rm).
    arts="$OUT_DIR/$id-r$r.artifacts"
    if [ "$SANDBOX" = "docker" ]; then
      for f in "$work/out"/*; do
        [ -e "$f" ] || continue
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

# docker: единый work живёт до конца прогона - затираем после всех карточек
if [ "$SANDBOX" = "docker" ] && [ -n "$SBWORK" ]; then
  python "$SB" cleanup "$SBWORK"
fi

exit $empty
