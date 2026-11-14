# Вердикт BR-CR-02-r1

## Шаг 1

- Дет-слой: согласуется с проверкой — все три строки facts_must найдены в транскрипте («Must fix» — заголовок раздела, «PartialEq» — находка 1, «get_celsius» — находка 4); facts_must_not пуст, расхождений с собственным grep нет.

- Вердикт: PARTIAL

- Обоснование: Основная часть оракула выполнена: несогласованность трейтов стоит в Must fix находкой 1 — «`impl Eq for Reading {}` promises `a == a` for every `Reading`» и «Even without NaN, the impls contradict each other twice: `-0.0 == 0.0` via derived `PartialEq`, but `total_cmp` orders `-0.0 < 0.0`... Both violate the documented consistency invariant». Порядок выдержан: трейт-дефект выше нейминга — `get_celsius` помечен «**Rule:** C-GETTER (Rust API Guidelines) — Rust never prefixes getters with `get_`» (находка 4, Should fix), `alert: bool` — «no bare `bool` parameters in public signatures» (находка 5, Should fix). Цитаты как file:line есть (`src/...:16`, `src/...:11`, `src/...:31`), фиксы даны кодом, ярусы сохранены, раздел «What's already good» присутствует. Но ведущий компонент оракула — рукописный `Ord` только по `celsius` против derived `PartialEq` по обоим полям с порчей sort/BTreeMap/dedup — в Must fix не попал: он вынесен в самый нижний ярус и объявлен допустимым — «### 7. `Ord` ignores `recorded_at`... Legal if "ordered by temperature only" is the intent... fine for `sort`». Предложенный в находке 1 фикс (запрет NaN, нормализация −0.0) эту часть несогласованности не устраняет — находка 7 остаётся в силе и после фикса, то есть ревью частично легализует ровно тот дефект, который оракул требует ловить как must fix.

- Корень: система

## Шаг 2

- Критерии: реплика совпадает с ходом 1 инструкции дословно («This sensor module ships tomorrow in our monitoring library. Give it a real review - I care about correctness first, naming second. Standard format with your tiers») плюс код сценария — это и есть материал проверки; подсказок SUT за пределами сценария нет — текст реплики не называет ни `Ord`/`Eq`/NaN, ни `get_`-префикс, ни `bool`-параметр, дефекты сидят только в коде; роль выдержана (голос разработчика перед релизом); дожатие не применимо — scripted single-turn прогон.

- Супервизия: OK

Судья-вызов: in 88189, out 7463, cache read 64, $0.6276, 123.6 с.
