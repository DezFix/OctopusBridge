//! Слой 3 — строковые фильтры и литералы python-узлов.
//!
//! Порт из `app/core/renpy/parser.py`: `_looks_like_text`,
//! `_decode_rpy_literal`, `_strip_py_comments`, `_regex_literals`,
//! `_py_string_literals` (включая обход `ast` через собственный
//! мини-парсер подмножества Python — полный `ast.parse` сюда не влезет),
//! `_sl_text_value`-вспомогательное (`try_eval_string`, поиск `_STR`).

/// Пробел по меркам Python (`str.strip` / `\s`): Unicode-пробел плюс
/// управляющие `\x1c..\x1f` (как `is_py_space` в `ob_renpy`).
fn is_py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}' <= c && c <= '\u{1f}')
}

/// Символ «слова» по меркам Python (`\w`): буква-or-цифра плюс `_`
/// (как `is_word` в `ob_renpy`).
fn is_word(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

/// Десятичная цифра по меркам `\d` (только `Nd`; приближение через
/// `is_numeric` — не-ASCII цифры в корпусе не встречаются, см. отчёт).
fn is_dec_digit(c: char) -> bool {
    c.is_ascii_digit() || c.is_numeric()
}

// ── _looks_like_text ──

/// Является ли строковый литерал текстом для перевода, а не именем файла,
/// URL, цветом, числом или ключом-«пустышкой». Один в один
/// `_looks_like_text` (порядок проверок тот же; часть правил после
/// `isalpha` технически недостижима, но оставлена как в эталоне).
#[must_use]
pub fn looks_like_text(s: &str) -> bool {
    let len = s.chars().count();
    if len < 2 || len > 20000 {
        return false;
    }
    if !s.chars().any(|c| c.is_alphabetic()) {
        return false;
    }
    if s.contains("://") || s.starts_with("file:") {
        return false;
    }
    if has_file_ext(s) {
        return false;
    }
    if is_hex_color(s) {
        return false;
    }
    if is_number_like(s) {
        return false;
    }
    if !s.chars().any(is_word) {
        return false;
    }
    // Идентификатор с цифрами (`q1`, `quest_1`) — флаг/ключ, не текст.
    if s.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
        && s.chars().any(|c| c.is_ascii_digit())
    {
        return false;
    }
    // Длинное snake_case/camelCase-имя (`empty_token_small`) — токен.
    if is_ident(s) && (len >= 12 || (s.contains('_') && len >= 8)) {
        return false;
    }
    // GLSL-шейдеры и прочий код.
    if has_word_any(s, &["sampler2D", "uniform", "varying", "attribute"]) {
        return false;
    }
    if s.contains(';') && s.contains('\n') {
        return false;
    }
    true
}

/// `RE_PY_FILE_EXT`: точка + расширение + хвостовые пробелы, регистр
/// не важен. Расширения — те же, что в эталоне.
fn has_file_ext(s: &str) -> bool {
    const EXTS: [&str; 36] = [
        "png", "jpg", "jpeg", "gif", "webp", "bmp", "ogg", "mp3", "wav",
        "flac", "mp4", "webm", "avi", "mov", "ttf", "otf", "woff", "rpy",
        "rpyc", "rpa", "rpe", "json", "txt", "zip", "rar", "7z", "xml",
        "html", "htm", "css", "js", "dat", "sav", "exe", "dll", "py",
    ];
    let t = s.trim_end_matches(is_py_space);
    let Some(dot) = t.rfind('.') else {
        return false;
    };
    let ext = &t[dot + 1..];
    EXTS.iter().any(|e| ext.eq_ignore_ascii_case(e))
}

/// `#[0-9a-fA-F]{3,8}` целиком.
fn is_hex_color(s: &str) -> bool {
    let b = s.strip_prefix('#').unwrap_or("");
    (3..=8).contains(&b.chars().count())
        && !b.is_empty()
        && b.chars().all(|c| c.is_ascii_hexdigit())
}

/// `\d+(?:[.,]\d+)*` целиком.
fn is_number_like(s: &str) -> bool {
    let chars: Vec<char> = s.chars().collect();
    if chars.is_empty() || !is_dec_digit(chars[0]) {
        return false;
    }
    let mut i = 0;
    // Первый блок цифр.
    while i < chars.len() && is_dec_digit(chars[i]) {
        i += 1;
    }
    // Хвосты `[.,]\d+`.
    while i < chars.len() {
        if (chars[i] == '.' || chars[i] == ',')
            && i + 1 < chars.len()
            && is_dec_digit(chars[i + 1])
        {
            i += 2;
            while i < chars.len() && is_dec_digit(chars[i]) {
                i += 1;
            }
        } else {
            return false;
        }
    }
    true
}

/// `[A-Za-z_][A-Za-z0-9_]*` целиком.
fn is_ident(s: &str) -> bool {
    let mut it = s.chars();
    match it.next() {
        Some(c) if c.is_ascii_alphabetic() || c == '_' => {}
        _ => return false,
    }
    it.all(|c| c.is_ascii_alphanumeric() || c == '_')
}

/// Поиск слов с границами `\b` с обеих сторон (регистр важен).
fn has_word_any(hay: &str, words: &[&str]) -> bool {
    let h: Vec<char> = hay.chars().collect();
    for w in words {
        let w: Vec<char> = w.chars().collect();
        if w.is_empty() || w.len() > h.len() {
            continue;
        }
        for i in 0..=h.len() - w.len() {
            if h[i..i + w.len()] != w[..] {
                continue;
            }
            let left_ok = i == 0 || !is_word(h[i - 1]);
            let right_ok =
                i + w.len() == h.len() || !is_word(h[i + w.len()]);
            if left_ok && right_ok {
                return true;
            }
        }
    }
    false
}

// ── _decode_rpy_literal ──

/// Декодирует escape-последовательности строкового литерала `.rpy`
/// (обратное `_escape`, плюс `\xNN`, `\uXXXX`, `\UXXXXXXXX`, `\N{...}`).
/// Набор — ровно `_RE_LIT_ESCAPE` эталона: `n t r " ' \` + hex/unicode.
/// Всё остальное (`\a`, `\b`, `\f`, `\v`, восьмеричные `\101`, `\q`…)
/// остаётся КАК ЕСТЬ (regex их не матчит, sub не трогает).
/// `\N{...}` без таблицы имён — `\ufffd` (как `unicodedata.lookup`
/// с ошибкой в эталоне; ВАЛИДНЫЕ имена Python резолвит по-настоящему,
/// здесь таблицы нет — остаточное расхождение, см. отчёт).
#[must_use]
pub fn decode_rpy_literal(text: &str) -> String {
    if !text.contains('\\') {
        return text.to_string();
    }
    let chars: Vec<char> = text.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] != '\\' || i + 1 >= chars.len() {
            out.push(chars[i]);
            i += 1;
            continue;
        }
        let e = chars[i + 1];
        match e {
            'n' => { out.push('\n'); i += 2; }
            't' => { out.push('\t'); i += 2; }
            'r' => { out.push('\r'); i += 2; }
            '"' => { out.push('"'); i += 2; }
            '\'' => { out.push('\''); i += 2; }
            '\\' => { out.push('\\'); i += 2; }
            'x' => {
                if let Some(ch) = hex_chars(&chars, i + 2, 2).and_then(char::from_u32) {
                    out.push(ch);
                    i += 4;
                } else {
                    out.push('\\');
                    i += 1;
                }
            }
            'u' => {
                if let Some(ch) = hex_chars(&chars, i + 2, 4).and_then(char::from_u32) {
                    out.push(ch);
                    i += 6;
                } else {
                    out.push('\\');
                    i += 1;
                }
            }
            'U' => {
                match hex_chars(&chars, i + 2, 8) {
                    Some(cp) => {
                        out.push(char::from_u32(cp).unwrap_or('\u{fffd}'));
                        i += 10;
                    }
                    None => { out.push('\\'); i += 1; }
                }
            }
            'N' => {
                // `\N{имя}`: ищем `}` без перевода строки внутри.
                if chars.get(i + 2) == Some(&'{') {
                    let mut j = i + 3;
                    while j < chars.len() && chars[j] != '}' && chars[j] != '\n' {
                        j += 1;
                    }
                    if j < chars.len() && chars[j] == '}' {
                        // Таблицы имён нет — как ошибка `lookup`.
                        out.push('\u{fffd}');
                        i = j + 1;
                    } else {
                        out.push('\\');
                        i += 1;
                    }
                } else {
                    out.push('\\');
                    i += 1;
                }
            }
            _ => { out.push('\\'); i += 1; }
        }
    }
    out
}

fn hex_chars(chars: &[char], start: usize, count: usize) -> Option<u32> {
    if start + count > chars.len() {
        return None;
    }
    let mut v: u32 = 0;
    for c in &chars[start..start + count] {
        v = v.checked_mul(16)? + c.to_digit(16)?;
    }
    Some(v)
}

// ── _strip_py_comments / _regex_literals ──

/// Убрать `#`-комментарии, не задевая `#` внутри строковых литералов.
/// Тройные кавычки специально НЕ обрабатываются (как в эталоне).
#[must_use]
pub fn strip_py_comments(src: &str) -> String {
    let chars: Vec<char> = src.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c == '#' {
            break;
        }
        if c == '"' || c == '\'' {
            let q = c;
            out.push(c);
            i += 1;
            while i < chars.len() {
                let c2 = chars[i];
                out.push(c2);
                if c2 == '\\' {
                    i += 1;
                    if i < chars.len() {
                        out.push(chars[i]);
                    }
                    i += 1;
                    continue;
                }
                if c2 == q {
                    i += 1;
                    break;
                }
                i += 1;
            }
            continue;
        }
        out.push(c);
        i += 1;
    }
    out
}

/// Строковые литералы регулярками (fallback для py2-синтаксиса и f-строк):
/// сначала двойные, затем одинарные на замаскированном тексте (чтобы
/// апостроф внутри `"don't"` не дал ложный литерал). Возвращает СЫРОЕ
/// содержимое (без декодирования), как `re.findall` в эталоне.
#[must_use]
pub fn regex_literals(src: &str) -> Vec<String> {
    let s = strip_py_comments(src);
    if s.is_empty() {
        return Vec::new();
    }
    let chars: Vec<char> = s.chars().collect();
    // Двойные: `"((?:[^"\\\n]|\\.)*)"`, где `.` ≠ `\n`.
    let mut spans: Vec<(usize, usize, String)> = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] != '"' {
            i += 1;
            continue;
        }
        let mut j = i + 1;
        let mut content = String::new();
        let mut ok = false;
        while j < chars.len() {
            let c = chars[j];
            if c == '\\' {
                if j + 1 < chars.len() && chars[j + 1] != '\n' {
                    content.push(c);
                    content.push(chars[j + 1]);
                    j += 2;
                } else {
                    break;
                }
            } else if c == '"' {
                ok = true;
                break;
            } else if c == '\n' {
                break;
            } else {
                content.push(c);
                j += 1;
            }
        }
        if ok {
            spans.push((i, j + 1, content));
            i = j + 1;
        } else {
            i += 1;
        }
    }
    let mut masked = chars.clone();
    for (a, b, _) in &spans {
        for k in *a..*b {
            masked[k] = ' ';
        }
    }
    let mut out: Vec<String> = spans.into_iter().map(|(_, _, c)| c).collect();
    // Одинарные — на замаскированном.
    let mut i = 0;
    while i < masked.len() {
        if masked[i] != '\'' {
            i += 1;
            continue;
        }
        let mut j = i + 1;
        let mut content = String::new();
        let mut ok = false;
        while j < masked.len() {
            let c = masked[j];
            if c == '\\' {
                if j + 1 < masked.len() && masked[j + 1] != '\n' {
                    content.push(c);
                    content.push(masked[j + 1]);
                    j += 2;
                } else {
                    break;
                }
            } else if c == '\'' {
                ok = true;
                break;
            } else if c == '\n' {
                break;
            } else {
                content.push(c);
                j += 1;
            }
        }
        if ok {
            out.push(content);
            i = j + 1;
        } else {
            i += 1;
        }
    }
    out
}

// ── textwrap.dedent ──

/// `textwrap.dedent` один в один: сначала whitespace-only строки
/// (только пробелы/табы) в `""`, затем общий префикс из пробелов/табов,
/// затем срезать его в началах строк.
#[must_use]
pub fn dedent(src: &str) -> String {
    // `_whitespace_only_re.sub('', text)`: `^[ \t]+$` (re.M).
    let mut lines: Vec<String> = src.split('\n').map(str::to_string).collect();
    for line in lines.iter_mut() {
        if !line.is_empty() && line.chars().all(|c| c == ' ' || c == '\t') {
            line.clear();
        }
    }
    // `_leading_whitespace_re`: `(^[ \t]*)(?:[^ \t\n])`.
    let mut margin: Option<String> = None;
    for line in &lines {
        let mut indent = String::new();
        let mut has_content = false;
        for c in line.chars() {
            if (c == ' ' || c == '\t') && !has_content {
                indent.push(c);
            } else if c == ' ' || c == '\t' {
                // Пробел после контента — уже не отступ, но строка
                // содержательная (пробел ≠ \n).
                has_content = true;
            } else {
                has_content = true;
                break;
            }
        }
        if !has_content {
            continue;
        }
        // Нестрого: строка из одних пробелов уже очищена выше.
        margin = Some(match margin {
            None => indent,
            Some(m) => common_margin(&m, &indent),
        });
    }
    let margin = margin.unwrap_or_default();
    if margin.is_empty() {
        return lines.join("\n");
    }
    for line in lines.iter_mut() {
        if line.starts_with(&margin) {
            line.drain(..margin.len());
        }
    }
    lines.join("\n")
}

/// Наибольший общий префикс по правилам `dedent` (побайтово — отступы
/// только из ASCII-пробелов/табов, символы = байты).
fn common_margin(a: &str, b: &str) -> String {
    // Логика цикла эталона: startswith-сохранение, иначе урезание
    // до первого расхождения.
    if b.starts_with(a) {
        return a.to_string();
    }
    if a.starts_with(b) {
        return b.to_string();
    }
    let mut i = 0;
    let ab = a.as_bytes();
    let bb = b.as_bytes();
    while i < ab.len() && i < bb.len() && ab[i] == bb[i] {
        i += 1;
    }
    a[..i].to_string()
}

// ── _STR-поиск (для _sl_text_value) ──

/// Первое вхождение `_STR` (`"..."` или `'...'`), сырое содержимое.
/// Многострочность разрешена (`[^"\\]` ест `\n`), `\\.` — нет.
/// Возвращает содержимое (группу 1 или 2, как `_m_text`).
pub fn str_search_first(src: &str) -> Option<String> {
    let chars: Vec<char> = src.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        let q = chars[i];
        if q != '"' && q != '\'' {
            i += 1;
            continue;
        }
        let mut j = i + 1;
        let mut content = String::new();
        let mut ok = false;
        while j < chars.len() {
            let c = chars[j];
            if c == '\\' {
                if j + 1 < chars.len() && chars[j + 1] != '\n' {
                    content.push(c);
                    content.push(chars[j + 1]);
                    j += 2;
                } else {
                    break;
                }
            } else if c == q {
                ok = true;
                break;
            } else {
                content.push(c);
                j += 1;
            }
        }
        if ok {
            return Some(content);
        }
        i += 1;
    }
    None
}

/// `ast.literal_eval`, суженный до строк: `Some(декодированная)` если весь
/// исходник — строковый литерал (со склейкой соседних и скобками),
/// иначе `None` (в эталоне дальше идёт regex-fallback и для `NonStr`,
/// и для `Fail` — исход один, различать не нужно).
pub fn try_eval_string(src: &str) -> Option<String> {
    use crate::pyparse::{TKind, decode_py_literal, tokenize};
    let toks = tokenize(src).ok()?;
    // Допустимы: скобки вокруг + подряд идущие строковые литералы.
    let mut depth = 0usize;
    // Ссылки на токены-строки (тип — из `pyparse`, чтобы не тащить).
    let mut parts: Vec<&crate::pyparse::STok> = Vec::new();
    let mut closed = false;
    for t in &toks {
        match &t.kind {
            TKind::LParen => {
                if closed {
                    return None;
                }
                depth += 1;
            }
            TKind::RParen => {
                if depth == 0 || !closed {
                    return None;
                }
                depth -= 1;
            }
            TKind::Str(_) => {
                closed = true;
                parts.push(t);
            }
            TKind::Ws | TKind::Comment | TKind::Newline | TKind::Indent | TKind::Dedent => {}
            _ => return None,
        }
    }
    if depth != 0 || parts.is_empty() {
        return None;
    }
    let mut out = String::new();
    for t in parts {
        match &t.kind {
            TKind::Str(lit) => {
                out.push_str(&decode_py_literal(lit)?);
            }
            _ => return None,
        }
    }
    Some(out)
}
