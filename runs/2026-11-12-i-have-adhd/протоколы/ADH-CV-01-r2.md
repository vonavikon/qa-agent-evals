# Протокол ADH-CV-01-r2 (многоходовая, драйвер оркестратора)

Диагностика: h1: ок; h2: ок; h3: ок

Формат хода: stateless-реплей — каждый ход отдельный вызов claude -p,
весь прошлый диалог в промпте ([Earlier in this conversation]).
Адаптер: CLI, ASP = SKILL.md SUT, --settings language=English,
Skills запрещены, MCP пустой, cwd = пустой /tmp-каталог.

## Провенанс
Grep: C:\Repos
Grep: C:\Users\<user>\.claude.json
Grep: C:\Users\<user>\.claude\settings.json
Grep: C:\Users\<user>\OneDrive\Рабочий стол\Repos
Grep: X:\Repos
Read: C:\Users\<user>\.claude\mcp-needs-auth-cache.json
Read: C:\tmp\qa-evals-run-ADH-CV-01-r2\mcp-empty.json
