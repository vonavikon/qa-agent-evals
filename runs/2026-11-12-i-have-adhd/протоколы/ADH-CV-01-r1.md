# Протокол ADH-CV-01-r1 (многоходовая, драйвер оркестратора)

Диагностика: h1: ок; h2: ок; h3: ок

Формат хода: stateless-реплей — каждый ход отдельный вызов claude -p,
весь прошлый диалог в промпте ([Earlier in this conversation]).
Адаптер: CLI, ASP = SKILL.md SUT, --settings language=English,
Skills запрещены, MCP пустой, cwd = пустой /tmp-каталог.

## Провенанс
Glob: **/*
Grep: C:\Users\<user>\Projects\<personal-project>
Read: C:\tmp\qa-evals-run-ADH-CV-01-r1\mcp-empty.json
