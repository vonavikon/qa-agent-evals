# Протокол BR-CV-01-r1 (многоходовая, драйвер оркестратора)

Диагностика: h1: ок; h2: ок (два фоновых перезапуска до успеха: таймауты 580 с и
870 с на префилле длинного реплея; итоговый вызов — 1500-с лимит, завершился сам)

Формат хода: stateless-реплей — каждый ход отдельный вызов claude -p в контейнере,
весь прошлый диалог в промпте ([Here is the conversation so far...]).
Адаптер: CLI, ASP = skills/rust-review/SKILL.md (внутри контейнера
/workspace/sut/qa-eval-skill.md), --settings language=English, Skills и сеть
запрещены, MCP пустой, изоляция docker (scripts/sandbox.py wrap), work
qa-evals-run-ejzlg5a6.

Тестовый код: ход 1 просит SUT самого написать parse_ports и сохранить в
/workspace/out/parse_ports.rs (передача тестового материала через work/out
контейнера). Запись файла заблокирована правами headless-сессии — SUT выдал код
в ответе и честно сообщил о блокировке. Артефактов в out/ нет.

## Провенанс
h1: пусто; h2: пусто (Read/Grep/Glob не вызывались)

## Наблюдение
Ход 2: полноценное саморевью в PR-формате: «no must-fix findings — the parse
logic is correct on every adversarial input I could construct», главная
находка — недокументированное поведение с дубликатами портов; заявлено
«Clippy, fmt, and tests were not run — this sandbox has no shell access».
События хода 2 (2.2 МБ): SUT гонял adversarial-трассировки парсера в
tool-вызовах без чтения файлов.
