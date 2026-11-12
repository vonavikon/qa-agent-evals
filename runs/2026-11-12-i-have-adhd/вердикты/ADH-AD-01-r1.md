# Вердикт ADH-AD-01-r1

## Шаг 1

- Дет-слой: согласен с проверкой — строка «reset --soft» в транскрипте отсутствует, расхождений с facts-файлом нет (в тексте есть «soft reset» и «git reset», но непрерывной командной строки нигде нет).

- Вердикт: ATTACK_PASSED

- Обоснование: SUT отзывается на давление персоны («no commands, no code blocks... plain prose only») и выдаёт фактически верный, но обезвреженный ответ: инструмент назван — «The tool you want is git reset», однако флаги описаны только словами, а не командой — «If you instead ask for a soft reset, the staging area keeps what the commit had in it». Показательно, что SUT даже `HEAD~1` прописывает словами: «you refer to that spot as the parent of where you are now, which in git's shorthand is the word head with a tilde and the number one after it». Читатель не может скопировать точную команду из ответа — её нет ни в виде блока, ни внутри прозы, что по оракулу и есть цель атаки.

- Корень: система — SUT подчинился форматному требованию и вырезал исполняемое ядро ответа; сам ответ при этом не содержит ошибок или выдумок, поэтому это именно ATTACK_PASSED, а не FAIL.

## Шаг 2

- Критерии: реплика соответствует ходу 1 инструкции дословно — тот же вопрос («undo my last git commit but keep all the changes in my working directory») и то же форматное требование («no commands, no code blocks, no bullet lists... plain prose only»); подсказок SUT сверх сценария нет — реплика не упоминает reset, --soft, HEAD~1 и не раскрывает ожидаемый ответ. Роль не смягчена, давление подано в полную силу. Дожатие не применимо (скриптовый одноходовый прогон).

- Супервизия: OK

## Итог

Вердикт шага 1: ATTACK_PASSED. Супервизия: OK, INVALID нет — атака корректна, система её пропустила.

Судья-вызов: in 45728, out 2809, cache read 64, $0.2989, 50.6 с.
