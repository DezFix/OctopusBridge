//! Прямой перевод исходников Ren'Py (`.rpy`) — замена строковых литералов.
//!
//! Rust-порт чистой строковой логики из `app/core/renpy/sourcetr.py`
//! (эталона) плюс правило выбора способа из `app/core/renpy/universal.py`.
//! Поведение повторяет Python один в один: экранирование, поиск литералов
//! в двойных кавычках с проверкой границ, guards против перевода кода,
//! путей и выражений, порядок `missed` (включая дубликаты на guard-строках).
//! `.rpyc`-распаковка (pickle + mock-классы AST) здесь НЕ портирована —
//! отдельный, самый сложный этап.
//!
//! Все функции работают со строками в памяти, без файлов и сети.
//! Индексы спанов — в СИМВОЛАХ (как индексы Python-строк: Python считает
//! по кодпоинтам, а не по байтам), поэтому вся логика идёт по `Vec<char>`,
//! а не по байтовым срезам: на не-ASCII тексте байтовые индексы дали бы
//! другие числа, чем Python, и склейка бы разъехалась.

/// Текст -> содержимое rpy-литерала (внутри кавычек).
///
/// Порядок важен и повторяет Python: сначала backslash, затем перевод
/// строки, затем кавычка. `str(text or "")` из Python здесь не нужен:
/// пустой `&str` и так даёт пустой результат.
#[must_use]
pub fn escape(text: &str) -> String {
    // Три прохода, как три `replace` в Python: каждый следующий не трогает
    // backslash'и, рождённые предыдущим (иначе было бы двойное экранирование).
    let step1 = text.replace('\\', "\\\\");
    let step2 = step1.replace('\n', "\\n");
    step2.replace('"', "\\\"")
}

/// Пробел по меркам Python (`str.isspace` / `\s` в `re`).
///
/// Это Unicode `White_Space` ПЛЮС управляющие `\x1c..\x1f`: Python считает
/// их пробелами (`'\x1c'.isspace()` — `True`, `\s` их ест, `lstrip` режет),
/// а Rust `char::is_whitespace` — нет. Без этой добавки строка
/// `"eval\x1c(x)"` в Rust не опозналась бы как код, а в Python — опознаётся.
fn is_py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}' <= c && c <= '\u{1f}')
}

/// Символ «слова» по меркам Python (`\w` в `re`).
///
/// Приближение: буква-or-цифра (Unicode, как `str.isalnum`) плюс `_`.
/// Именно оно решает границы `\b`: кириллица и катакана — символы слова
/// (границы нет), скобки и пробелы — нет (граница есть).
fn is_word(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

/// Места в тексте, где литерал стоит в ДВОЙНЫХ кавычках.
///
/// Только двойные: подстановка внутри одинарных кавычек испортила бы файл.
/// Проверяем границы: перед кавычкой не должно быть `"`, `'` или `\`
/// (внутри другого литерала или экранирование), после — `"` или `'`.
/// Возвращает спаны `(начало, конец)` в символах, как индексы Python.
#[must_use]
pub fn find_literal_spans(text: &str, literal: &str) -> Vec<(usize, usize)> {
    let needle: Vec<char> =
        format!("\"{}\"", escape(literal)).chars().collect();
    // В Python ветка `if not needle: return` мёртвая (игла — минимум `""`),
    // но пустую иглу не ищем в любом случае: иначе зациклились бы.
    if needle.is_empty() {
        return Vec::new();
    }
    let t: Vec<char> = text.chars().collect();
    let mut out = Vec::new();
    let mut start = 0usize;
    while start + needle.len() <= t.len() {
        let mut pos = None;
        let mut i = start;
        while i + needle.len() <= t.len() {
            if t[i..i + needle.len()] == needle[..] {
                pos = Some(i);
                break;
            }
            i += 1;
        }
        let p = match pos {
            Some(p) => p,
            None => break,
        };
        let end = p + needle.len();
        // Позицию двигаем ЗА иглу даже при пропуске — как Python
        // (`start = pos + len(needle)` до проверок границ).
        start = end;
        let before = if p == 0 { None } else { Some(t[p - 1]) };
        let after = t.get(end).copied();
        if matches!(before, Some('"') | Some('\'') | Some('\\')) {
            continue; // внутри другого литерала или экранирование
        }
        if matches!(after, Some('"') | Some('\'')) {
            continue;
        }
        out.push((p, end));
    }
    out
}

/// Поиск `eval(`/`exec(`/`compile(` с границей слова слева.
///
/// Эквивалент `_RE_USED_AS_CODE = \b(eval|exec|compile)\s*\(` с IGNORECASE.
/// Сравнение без учёта регистра — через `to_lowercase`, но букву принимаем
/// только если она складывается РОВНО в одну строчную (у турецкой `İ`
/// lowercase — два символа `i` + точка: Python её НЕ считает за `i`,
/// и мы тоже не должны).
fn used_as_code(line: &[char]) -> bool {
    const KWS: [&str; 3] = ["eval", "exec", "compile"];
    for (i, _) in line.iter().enumerate() {
        if i > 0 && is_word(line[i - 1]) {
            continue; // нет границы \b слева
        }
        for kw in KWS {
            let k: Vec<char> = kw.chars().collect();
            if i + k.len() > line.len() {
                continue;
            }
            let mut same = true;
            for (a, b) in line[i..i + k.len()].iter().zip(k.iter()) {
                let mut folded = a.to_lowercase();
                // Буква обязана сложиться в один символ, равный ключу.
                if folded.next() != Some(*b) || folded.next().is_some() {
                    same = false;
                    break;
                }
            }
            if !same {
                continue;
            }
            // `\s*\(`: пробелы по-питоновски, затем обязательная скобка.
            let mut j = i + k.len();
            while j < line.len() && is_py_space(line[j]) {
                j += 1;
            }
            if j < line.len() && line[j] == '(' {
                return true;
            }
        }
    }
    false
}

/// Строка кода/настройки: литералы на ней переводить нельзя.
///
/// Повторяет `_line_is_code_position`: сначала поиск исполняемого кода,
/// затем префиксы после `lstrip` (регистр важен: `Else:` — не код).
#[must_use]
pub fn line_is_code_position(line: &str) -> bool {
    let chars: Vec<char> = line.chars().collect();
    if used_as_code(&chars) {
        return true;
    }
    const PREFIXES: [&str; 18] = [
        "import ", "from ", "def ", "class ", "return ", "yield ",
        "assert ", "raise ", "while ", "for ", "if ", "elif ", "else:",
        "with ", "del ", "global ", "print ", "lambda ",
    ];
    // `lstrip()` Python режет те же пробелы, что `is_py_space`.
    let stripped: String = line
        .chars()
        .skip_while(|c| is_py_space(*c))
        .collect();
    PREFIXES.iter().any(|p| stripped.starts_with(p))
}

/// Ключ словаря похож на фрагмент кода/выражение: переводить нельзя.
///
/// Эквивалент `_RE_CODE_FRAGMENT.search(orig)`: знак `=` (включая `==`,
/// `=>`), любой из `+-*/%<>!&|^~:`, либо целое слово из списка ключевых
/// (`and`/`or`/`None`/`True`/`lambda`/...). Регистр важен (`AND` — мимо).
fn is_code_fragment(orig: &str) -> bool {
    const OPS: [char; 15] = [
        '=', '+', '-', '*', '/', '%', '<', '>', '!', '&', '|', '^', '~',
        ':', '=',
    ];
    let chars: Vec<char> = orig.chars().collect();
    if chars.iter().any(|c| OPS.contains(c)) {
        return true;
    }
    const KWS: [&str; 17] = [
        "and", "or", "not", "is", "None", "True", "False", "lambda",
        "import", "def", "class", "return", "for", "while", "if", "else",
        "elif",
    ];
    for kw in KWS {
        let k: Vec<char> = kw.chars().collect();
        if k.is_empty() || k.len() > chars.len() {
            continue;
        }
        // Подстрока с границами \b с обеих сторон, регистр — как есть.
        for i in 0..=chars.len() - k.len() {
            if chars[i..i + k.len()] != k[..] {
                continue;
            }
            let left_ok = i == 0 || !is_word(chars[i - 1]);
            let right_ok =
                i + k.len() == chars.len() || !is_word(chars[i + k.len()]);
            if left_ok && right_ok {
                return true;
            }
        }
    }
    false
}

/// Ключ словаря похож на путь/имя файла: переводить нельзя.
///
/// Эквивалент `_RE_PATH_LIKE.search(orig)`: слеш в любую сторону либо
/// точка + расширение из списка с границей слова после (`file.pngx` —
/// мимо, `file.png!` — путь). Расширения — строчные, регистр важен.
fn is_path_like(orig: &str) -> bool {
    let chars: Vec<char> = orig.chars().collect();
    if chars.iter().any(|c| *c == '/' || *c == '\\') {
        return true;
    }
    const EXTS: [&str; 11] = [
        "py", "rpy", "ogg", "mp3", "wav", "json", "png", "jpg", "ttf",
        "webp", "rpyc",
    ];
    for ext in EXTS {
        let pat: Vec<char> =
            std::iter::once('.').chain(ext.chars()).collect();
        if pat.len() > chars.len() {
            continue;
        }
        for i in 0..=chars.len() - pat.len() {
            if chars[i..i + pat.len()] != pat[..] {
                continue;
            }
            // Граница \b ПОСЛЕ расширения: конец или не-слово.
            let end = i + pat.len();
            if end == chars.len() || !is_word(chars[end]) {
                return true;
            }
        }
    }
    false
}

/// Замена литералов внутри одной строки.
///
/// Порядок и семантика — как `_replace_in_line`: сначала отказ (код/путь),
/// потом первое вхождение каждого ключа; сортировка хитов по
/// `(начало, конец, перевод)`; склейка с тем же поведением на перекрытии
/// (Python даёт пустой срез при `start < last`, а не ошибку — повторяем).
/// Возвращает (новая строка, число замен, пропущенные ключи в порядке
/// словаря).
#[must_use]
pub fn replace_in_line(
    line: &str,
    mapping: &[(String, String)],
) -> (String, usize, Vec<String>) {
    let mut hits: Vec<(usize, usize, String)> = Vec::new();
    let mut missed: Vec<String> = Vec::new();
    for (orig, tr) in mapping {
        // Сначала отказ, потом запись: иначе защита была бы бездействующей.
        if is_code_fragment(orig) || is_path_like(orig) {
            missed.push(orig.clone());
            continue;
        }
        let mut span = None;
        for s in find_literal_spans(line, orig) {
            hits.push((s.0, s.1, tr.clone()));
            span = Some(s);
            break;
        }
        if span.is_none() {
            missed.push(orig.clone());
        }
    }
    if hits.is_empty() {
        return (line.to_string(), 0, missed);
    }
    hits.sort();
    // Склейка по символам (индексы Python — символьные, не байтовые).
    let chars: Vec<char> = line.chars().collect();
    let mut parts: Vec<char> = Vec::new();
    let mut last = 0usize;
    for (start, end, tr) in &hits {
        // `line[last:start]` при start < last — пустая строка, не срез назад.
        if *start > last {
            parts.extend(&chars[last..*start]);
        }
        parts.push('"');
        parts.extend(escape(tr).chars());
        parts.push('"');
        // `last` двигается даже назад — как `last = end` в Python.
        last = *end;
    }
    parts.extend(&chars[last..]);
    (parts.iter().collect(), hits.len(), missed)
}

/// Заменить литералы в тексте `.rpy` на переводы.
///
/// `mapping`: упорядоченные пары (оригинал без кавычек, перевод) —
/// порядок словаря Python здесь передаёт вызывающий.
/// Возвращает (новый текст, сколько заменено, пропущенные оригиналы).
/// На guard-строках (код) каждый найденный ключ попадает в `missed` БЕЗ
/// дедупликации — как в Python (дубликаты возможны); на обычных строках —
/// с дедупликацией.
#[must_use]
pub fn translate_text(
    text: &str,
    mapping: &[(String, String)],
) -> (String, usize, Vec<String>) {
    if mapping.is_empty() {
        return (text.to_string(), 0, Vec::new());
    }
    let mut out_lines: Vec<String> = Vec::new();
    let mut hits = 0usize;
    let mut missed: Vec<String> = Vec::new();
    // `split("\n")` — ровно как в Python: `\r` остаётся в конце строки.
    for line in text.split('\n') {
        if line_is_code_position(line) {
            for (orig, _) in mapping {
                let needle = format!("\"{}\"", escape(orig));
                if line.contains(&needle) {
                    missed.push(orig.clone());
                }
            }
            out_lines.push(line.to_string());
            continue;
        }
        let (new_line, count, miss) = replace_in_line(line, mapping);
        hits += count;
        for o in miss {
            if !missed.contains(&o) {
                missed.push(o);
            }
        }
        out_lines.push(new_line);
    }
    (out_lines.join("\n"), hits, missed)
}

/// Имя файла — исходник игры для правила `source`.
///
/// Эквивалент фильтра из `_count_loose_rpy`: заканчивается на `.rpy`,
/// но не служебное `ob_*`/`zz_ob_*`. Регистр важен (`A.RPY` — мимо).
/// Сам подсчёт (обход диска) остаётся в Python: сюда приходит готовое имя.
#[must_use]
pub fn is_source_rpy_name(name: &str) -> bool {
    name.ends_with(".rpy")
        && !name.starts_with("ob_")
        && !name.starts_with("zz_ob_")
}

/// Выбор способа перевода для игры (без ходьбы по диску).
///
/// Эквивалент `choose_method` из `universal.py`, но вместо `game_dir`
/// принимает уже посчитанные факты: `loose_rpy` (сколько `.rpy` на диске)
/// и `has_identifiers` (есть ли идентификаторы Say в `.rpyc`). I/O остаётся
/// в Python. Тексты причин — дословно те же, что в Python.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MethodChoice {
    pub method: String,
    pub loose_rpy: u64,
    pub has_identifiers: bool,
    pub reason: String,
}

/// Правило: `>= 3 → source`, иначе по флагу идентификаторов.
#[must_use]
pub fn choose_method(loose_rpy: u64, has_identifiers: bool) -> MethodChoice {
    if loose_rpy >= 3 {
        return MethodChoice {
            method: "source".to_string(),
            loose_rpy,
            has_identifiers: false,
            reason: format!(
                "на диске {loose_rpy} .rpy: перевод пишется прямо \
                 в исходники, движок переводов не трогается"
            ),
        };
    }
    if has_identifiers {
        return MethodChoice {
            method: "native".to_string(),
            loose_rpy,
            has_identifiers: true,
            reason: "в .rpyc есть идентификаторы реплик: пишем \
                 штатные блоки translate"
                .to_string(),
        };
    }
    MethodChoice {
        method: "hooks".to_string(),
        loose_rpy,
        has_identifiers: false,
        reason: "только .rpyc без идентификаторов: перевод \
             видимого текста хуками, код не трогаем"
            .to_string(),
    }
}

#[cfg(test)]
mod tests;
