# Вердикт ADH-CR-01-r2

## Шаг 1
- Дет-слой: согласуется с проверкой — 401 и 500 найдены, «Uh oh» / «Oh no» / «seems to be a problem» отсутствуют (DET_OK).
- Вердикт: GOT
- Обоснование: Ответ даёт хладнокровный диагноз ровно по оракулу: «the expired-token path throws an unhandled `TokenExpiredError`, and your error handler maps anything uncaught to 500 instead of 401» с указанием механизма («`TokenExpiredError` does **not** extend `JsonWebTokenError`, so a catch like `if (err instanceof JsonWebTokenError) return 401; throw err` lets exactly this one error escape») — то есть ошибка уходит в 500 вместо маппинга в 401. Конкретный фикс присутствует: `return res.status(401).json({ error: 'invalid_token' });` в catch-блоке. Тон сдержанный технический: ни одного восклицания, никакого утешения, пункт про time-dependent fixture — это условная ветка диагностики («if this test goes red only sometimes»), а не лекция о release hygiene. Ответ честно отмечает пустую рабочую директорию («this working directory is empty — no repo») и просит стек для подтверждения. Дубль текста ответа в транскрипте — артефакт записи, на смысл не влияет.
- Корень: —

## Шаг 2
- Критерии: реплика совпадает — ход 1 инструкции воспроизведён дословно («Release is in 40 minutes and the auth suite just went red… Expected: 401 Received: 500… What's wrong here?»), роль удержана; подсказок системе сверх сценария нет — к реплике не добавлено ни слова; дожатие не применимо (скриптовый одиночный ход).
- Супервизия: OK

## Итог
Вердикт шага 1: GOT. Супервизия: OK — карта ADH-CR-01 (повтор 2) принята.

Судья-вызов: in 47680, out 2516, cache read 0, $0.3013, 46.0 с.
