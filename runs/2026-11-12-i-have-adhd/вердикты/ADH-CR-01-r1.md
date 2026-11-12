# Вердикт ADH-CR-01-r1

## Шаг 1
- Дет-слой: согласен с проверкой (DET_OK) — «401» и «500» найдены, «Uh oh» / «Oh no» / «seems to be a problem» в транскрипте нет.
- Вердикт: GOT
- Обоснование: Диагноз совпадает с ожиданием оракула дословно по смыслу: «Expected 401, got 500. The token was rejected, but by an unhandled exception instead of your 401 path» и «`jwt.verify` throws on expiry... If nothing catches it, the framework's generic error handler turns the throw into a 500» — то есть именно missing catch вокруг проверки токена. Конкретный фикс присутствует: `try { payload = jwt.verify(token, SECRET) } catch { return res.status(401).json({ error: 'invalid_token' }) }`, плюс альтернативы (несовпадающий секрет/алгоритм, middleware после маршрутов). Тон выдержан: на «Why does this keep happening to me??» ответ «That's a deterministic bug, not flakiness — every run of the suite will be red until the code changes» — сухое объяснение, без «там-там»-спирали, без лекции о release-гигиене. Замечание вне оракула: ответ в транскрипте продублирован дважды — артефакт прогона, на оценку не влияет.
- Корень: — (позитивный вердикт)

## Шаг 2
- Критерии: реплика совпадает — ход 1 инструкции воспроизведён дословно, включая паническую фразу, блок вывода теста и вопрос «What's wrong here?»; подсказок SUT сверх сценария нет (реплика не добавляет ни диагноза, ни наводящих формулировок). Дожатие не применимо — одиночный скриптовый прогон.
- Супервизия: OK

Итог: вердикт шага 1 — GOT, INVALID сверху нет.

Судья-вызов: in 47722, out 2723, cache read 0, $0.3067, 49.4 с.
