# Вердикт BR-CR-01-r1

## Шаг 1
- Дет-слой: согласен с проверкой: «Must fix» — заголовок яруса, «unwrap» и «&String» — в разборах дефектов 2 и 1; facts_must_not пуст, расхождений нет.
- Вердикт: GOT
- Обоснование: Все три заложенных дефекта найдены и оформлены по требованиям оракула. Паника: «### 2. `load` panics on the most ordinary config files (`config.rs:18`)» — «`load` calls `.unwrap()` on it. `load("a=1\n\nb=2")` panics», поставлена в Must fix выше стиля (идиома `split_once` — в Should fix: «### 4. `splitn` + collect + `len()` + indexing instead of `split_once`»). Тип ошибки: «### 3. `String` as the public error type (`config.rs:6`)» с правилом «(`C-GOOD-ERR`, Rust API Guidelines)» и полным fix через enum с `impl fmt::Display` + `impl std::error::Error`. Параметр: «`parse_line` declares `line: &String`» с `clippy::ptr_arg` и fix «`pub fn parse_line(line: &str)`». Правило паники процитировано как M-PANIC-ON-BUG (Microsoft Rust Guidelines), а не M-PANIC-IS-STOP / Effective Rust Item 18 — по смыслу эквивалентно («no panics on paths reachable from external input»), все находки несут file:line, правило и fix, ярусы Must/Should/Consider и раздел «## What's already good» на месте. Бонус, оракулу не противоречащий: SUT верно усилил дефект 3 до «Deref coercion only goes `&String → &str`, never the reverse, so the crate fails with `error[E0308]`» — код действительно не компилируется при передаче `&str` из `text.lines()`.
- Корень: —

## Шаг 2
- Критерии: реплика дословно совпадает с ходом 1 инструкции («A contractor dropped this config module into our library crate and left. Review it before we build on it - I need to know what actually breaks and what the rules say. Full review please, your standard format.»); подсказок SUT за пределами сценария нет — только запрос и код дефектного модуля, ничего об unwrap/&String/типе ошибки; голос тимлида выдержан; скриптовый одиночный ход — критерий дожатия не применяется.
- Супервизия: OK

Судья-вызов: in 88671, out 5558, cache read 192, $0.5824, 92.9 с.
