//! Мини-парсер подмножества Python для `_py_string_literals`.
//!
//! Эталон разбирает python-исходники настоящим `ast.parse` и обходит
//! дерево (`_collect`): строковые константы с подсказками (имена
//! переменных, `key=` ключей словарей, строки кода), пропуск docstring,
//! f-строки целиком по срезу исходника. Полный парсер Python сюда не
//! влезет, поэтому здесь — достаточное подмножество: выражения
//! (литералы, вызовы, индексы, операции, тернарники, лямбды,
//! генераторы), присваивания, `def`/`class`/`if`/`for`/`while`/`with`/
//! `try`/`match`, docstring'и.
//!
//! Правило «всё или ничего», как `ast.parse`: любая непонятная
//! конструкция — ошибка всего файла, вызывающий уходит в regex-fallback
//! (`_regex_literals`), ровно как Python при `SyntaxError`. Декораторы
//! пропускаются (эталон их не обходит).

use crate::text::{looks_like_text, regex_literals};

/// Строковый литерал: префикс, тройная ли кавычка, сырое тело.
#[derive(Debug, Clone)]
pub struct StrLit {
    pub prefix: String,
    pub triple: bool,
    pub quote: char,
    pub body: String,
}

impl StrLit {
    fn is_bytes(&self) -> bool {
        self.prefix.chars().any(|c| c == 'b' || c == 'B')
    }
    fn is_fstring(&self) -> bool {
        self.prefix.chars().any(|c| c == 'f' || c == 'F')
    }
    fn is_raw(&self) -> bool {
        self.prefix.chars().any(|c| c == 'r' || c == 'R')
    }
}

/// Токен с байтовыми смещениями (нужны срезы f-строк, как `_node_slice`).
#[derive(Debug, Clone)]
pub struct STok {
    pub kind: TKind,
    pub start: usize,
    pub end: usize,
}

#[derive(Debug, Clone)]
pub enum TKind {
    Ws,
    Newline,
    Comment,
    Indent,
    Dedent,
    Name(String),
    Num,
    Str(StrLit),
    FStr,
    LParen,
    RParen,
    LBracket,
    RBracket,
    LBrace,
    RBrace,
    Comma,
    Colon,
    Semi,
    Dot,
    Eq,
    Op(String),
}

/// Проверка комбинации префикса (`rb`, `f`, `R` — да; `fb`, `rr` — нет,
/// тогда весь файл — в fallback, как `SyntaxError` в Python).
fn valid_prefix(p: &str) -> bool {
    let l = p.to_ascii_lowercase();
    if l.is_empty() || l.len() > 3 {
        return l.is_empty();
    }
    if !l.chars().all(|c| matches!(c, 'r' | 'b' | 'u' | 'f')) {
        return false;
    }
    let (mut r, mut b, mut u, mut f) = (0, 0, 0, 0);
    for c in l.chars() {
        match c {
            'r' => r += 1,
            'b' => b += 1,
            'u' => u += 1,
            'f' => f += 1,
            _ => {}
        }
    }
    if r > 1 || b > 1 || u > 1 || f > 1 {
        return false;
    }
    if b == 1 && (u == 1 || f == 1) {
        return false;
    }
    if u == 1 && f == 1 {
        return false;
    }
    true
}

/// Токенизировать исходник (после `dedent` у вызывающего).
pub fn tokenize(src: &str) -> Result<Vec<STok>, ()> {
    let b = src.as_bytes();
    let n = b.len();
    let mut toks: Vec<STok> = Vec::new();
    let mut i = 0usize;
    let mut at_line_start = true;
    let mut indent_stack: Vec<String> = vec![String::new()];
    let mut bracket: i32 = 0;
    // Отступ текущей строки (накапливаем до первого не-пробела).
    let mut cur_indent = String::new();

    // Вспомогательное: оформить отступ при первом содержательном токене.
    macro_rules! indent_done {
        () => {
            if at_line_start {
                at_line_start = false;
                let top =
                    indent_stack.last().map(String::as_str).unwrap_or("");
                if bracket == 0 {
                    if cur_indent != top {
                        if cur_indent.starts_with(top)
                            && cur_indent.len() > top.len()
                        {
                            indent_stack.push(cur_indent.clone());
                            toks.push(STok {
                                kind: TKind::Indent,
                                start: i,
                                end: i,
                            });
                        } else {
                            let mut ok = false;
                            while indent_stack.len() > 1 {
                                indent_stack.pop();
                                toks.push(STok {
                                    kind: TKind::Dedent,
                                    start: i,
                                    end: i,
                                });
                                if indent_stack
                                    .last()
                                    .map(String::as_str)
                                    .unwrap_or("")
                                    == cur_indent
                                {
                                    ok = true;
                                    break;
                                }
                            }
                            if !ok {
                                return Err(());
                            }
                        }
                    }
                }
                cur_indent.clear();
            }
        };
    }

    while i < n {
        let c = b[i];
        // Продолжение строки `\` + перевод.
        if c == b'\\' && i + 1 < n && (b[i + 1] == b'\n' || b[i + 1] == b'\r')
        {
            if b[i + 1] == b'\r' && i + 2 < n && b[i + 2] == b'\n' {
                i += 3;
            } else {
                i += 2;
            }
            // Вне скобок перевод всё равно съеден (как в Python).
            continue;
        }
        // Переводы строк: внутри скобок — невидимы (как в Python).
        if c == b'\n' || c == b'\r' {
            if c == b'\r' && i + 1 < n && b[i + 1] == b'\n' {
                i += 1;
            }
            i += 1;
            if bracket == 0 {
                toks.push(STok { kind: TKind::Newline, start: i, end: i });
                at_line_start = true;
                cur_indent.clear();
            } else {
                toks.push(STok { kind: TKind::Ws, start: i, end: i });
            }
            continue;
        }
        // Пробелы/табы.
        if c == b' ' || c == b'\t' {
            if at_line_start && bracket == 0 {
                cur_indent.push(c as char);
            } else {
                toks.push(STok { kind: TKind::Ws, start: i, end: i + 1 });
            }
            i += 1;
            continue;
        }
        // Комментарий. Строка только из комментария на отступы не
        // влияет (как в Python: INDENT по таким строкам не ставится).
        if c == b'#' {
            if !(at_line_start && bracket == 0) {
                indent_done!();
            }
            while i < n && b[i] != b'\n' && b[i] != b'\r' {
                i += 1;
            }
            toks.push(STok { kind: TKind::Comment, start: i, end: i });
            continue;
        }
        // Число (грубо: цифры/буквы/точки/подчёркивания подряд).
        if c.is_ascii_digit() {
            indent_done!();
            let s = i;
            while i < n
                && (b[i].is_ascii_alphanumeric()
                    || b[i] == b'_'
                    || b[i] == b'.')
            {
                i += 1;
            }
            toks.push(STok { kind: TKind::Num, start: s, end: i });
            continue;
        }
        // Имя или префикс строки.
        if c.is_ascii_alphabetic() || c == b'_' {
            let s = i;
            while i < n && (b[i].is_ascii_alphanumeric() || b[i] == b'_') {
                i += 1;
            }
            let word = &src[s..i];
            // Строка? Сразу за словом кавычка.
            if i < n && (b[i] == b'"' || b[i] == b'\'') && is_quote_prefix(word) {
                if !valid_prefix(word) {
                    return Err(());
                }
                indent_done!();
                let (kind, end) = scan_string(b, i, word)?;
                toks.push(STok { kind, start: s, end });
                i = end;
                continue;
            }
            indent_done!();
            toks.push(STok {
                kind: TKind::Name(word.to_string()),
                start: s,
                end: i,
            });
            continue;
        }
        // Голая кавычка — строка без префикса.
        if c == b'"' || c == b'\'' {
            indent_done!();
            let (kind, end) = scan_string(b, i, "")?;
            toks.push(STok { kind, start: i, end });
            i = end;
            continue;
        }
        // Скобки.
        match c {
            b'(' => {
                indent_done!();
                bracket += 1;
                toks.push(STok { kind: TKind::LParen, start: i, end: i + 1 });
                i += 1;
                continue;
            }
            b')' => {
                indent_done!();
                bracket -= 1;
                if bracket < 0 {
                    return Err(());
                }
                toks.push(STok { kind: TKind::RParen, start: i, end: i + 1 });
                i += 1;
                continue;
            }
            b'[' => {
                indent_done!();
                bracket += 1;
                toks.push(STok { kind: TKind::LBracket, start: i, end: i + 1 });
                i += 1;
                continue;
            }
            b']' => {
                indent_done!();
                bracket -= 1;
                if bracket < 0 {
                    return Err(());
                }
                toks.push(STok { kind: TKind::RBracket, start: i, end: i + 1 });
                i += 1;
                continue;
            }
            b'{' => {
                indent_done!();
                bracket += 1;
                toks.push(STok { kind: TKind::LBrace, start: i, end: i + 1 });
                i += 1;
                continue;
            }
            b'}' => {
                indent_done!();
                bracket -= 1;
                if bracket < 0 {
                    return Err(());
                }
                toks.push(STok { kind: TKind::RBrace, start: i, end: i + 1 });
                i += 1;
                continue;
            }
            _ => {}
        }
        // Пунктуация и операторы.
        indent_done!();
        let rest = &b[i..];
        // Трёхсимвольные.
        if rest.len() >= 3 {
            let t3 = &rest[..3];
            if t3 == b"<<=" || t3 == b">>=" || t3 == b"**=" || t3 == b"//=" {
                toks.push(STok {
                    kind: TKind::Op(src[i..i + 3].to_string()),
                    start: i,
                    end: i + 3,
                });
                i += 3;
                continue;
            }
            if t3 == b"..." {
                toks.push(STok {
                    kind: TKind::Op("...".to_string()),
                    start: i,
                    end: i + 3,
                });
                i += 3;
                continue;
            }
        }
        if rest.len() >= 2 {
            let t2 = &rest[..2];
            if t2 == b"=="
                || t2 == b"!="
                || t2 == b"<="
                || t2 == b">="
                || t2 == b"<<"
                || t2 == b">>"
                || t2 == b"**"
                || t2 == b"//"
                || t2 == b"+="
                || t2 == b"-="
                || t2 == b"*="
                || t2 == b"/="
                || t2 == b"%="
                || t2 == b"&="
                || t2 == b"|="
                || t2 == b"^="
                || t2 == b"@="
                || t2 == b":="
                || t2 == b"->"
            {
                toks.push(STok {
                    kind: TKind::Op(src[i..i + 2].to_string()),
                    start: i,
                    end: i + 2,
                });
                i += 2;
                continue;
            }
        }
        match c {
            b',' => toks.push(STok { kind: TKind::Comma, start: i, end: i + 1 }),
            b':' => toks.push(STok { kind: TKind::Colon, start: i, end: i + 1 }),
            b';' => toks.push(STok { kind: TKind::Semi, start: i, end: i + 1 }),
            b'.' => toks.push(STok { kind: TKind::Dot, start: i, end: i + 1 }),
            b'=' => toks.push(STok { kind: TKind::Eq, start: i, end: i + 1 }),
            b'+' | b'-' | b'*' | b'/' | b'%' | b'<' | b'>' | b'&' | b'|'
            | b'^' | b'~' | b'@' | b'!' | b'?' | b'`' | b'$' => {
                toks.push(STok {
                    kind: TKind::Op((c as char).to_string()),
                    start: i,
                    end: i + 1,
                });
            }
            _ => {
                // Не-ASCII вне строк/комментариев (идентификаторы с
                // юникодом, странные байты): Python либо примет
                // (юникод-имена), либо упадёт. Считаем именем, если буква.
                let ch = src[i..].chars().next().ok_or(())?;
                if ch.is_alphabetic() || ch == '_' {
                    let s = i;
                    while i < n {
                        match src[i..].chars().next() {
                            Some(q)
                                if q.is_alphanumeric() || q == '_' =>
                            {
                                i += q.len_utf8();
                            }
                            _ => break,
                        }
                    }
                    toks.push(STok {
                        kind: TKind::Name(src[s..i].to_string()),
                        start: s,
                        end: i,
                    });
                    continue;
                }
                return Err(());
            }
        }
        i += 1;
    }
    // Закрыть висячие отступы (как DEDENT в конце файла у Python).
    while indent_stack.len() > 1 {
        indent_stack.pop();
        toks.push(STok { kind: TKind::Dedent, start: n, end: n });
    }
    Ok(toks)
}

/// Слово может быть префиксом строки (только буквы r/b/u/f в любом
/// регистре; валидность — отдельно в `valid_prefix`).
fn is_quote_prefix(word: &str) -> bool {
    !word.is_empty()
        && word.chars().all(|c| matches!(c, 'r' | 'R' | 'b' | 'B' | 'u' | 'U' | 'f' | 'F'))
}

/// Отсканировать строку с позиции кавычки: вернуть токен и конец.
/// Байтовые смещения; f-строки — с учётом вложенных скобок.
fn scan_string(b: &[u8], qpos: usize, prefix: &str) -> Result<(TKind, usize), ()> {
    let n = b.len();
    let q = b[qpos];
    let triple = qpos + 2 < n && b[qpos + 1] == q && b[qpos + 2] == q;
    let is_f = prefix.chars().any(|c| c == 'f' || c == 'F');
    let mut i = qpos + if triple { 3 } else { 1 };
    if is_f {
        // f-строка: отслеживаем глубину `{...}` и строки внутри.
        let mut depth = 0i32;
        while i < n {
            let c = b[i];
            if c == b'\\' {
                i += 2;
                continue;
            }
            if triple {
                if c == q
                    && i + 2 < n
                    && b[i + 1] == q
                    && b[i + 2] == q
                    && depth == 0
                {
                    return Ok((TKind::FStr, i + 3));
                }
            } else if c == b'\n' || c == b'\r' {
                if depth == 0 {
                    return Err(());
                }
                i += 1;
                continue;
            }
            if depth == 0 {
                if !triple && c == q {
                    return Ok((TKind::FStr, i + 1));
                }
                if c == b'{' {
                    if i + 1 < n && b[i + 1] == b'{' {
                        i += 2;
                        continue;
                    }
                    depth += 1;
                    i += 1;
                    continue;
                }
                if c == b'}' {
                    if i + 1 < n && b[i + 1] == b'}' {
                        i += 2;
                        continue;
                    }
                    return Err(());
                }
                i += 1;
            } else if c == b'"' || c == b'\'' {
                // Вложенная строка внутри `{...}`: пропустить целиком.
                let (_, end) = scan_simple(b, i)?;
                i = end;
            } else if c == b'{' {
                depth += 1;
                i += 1;
            } else if c == b'}' {
                depth -= 1;
                i += 1;
            } else {
                i += 1;
            }
        }
        return Err(());
    }
    let (body_end, end) = scan_simple_from(b, qpos, triple)?;
    let body = String::from_utf8_lossy(
        &b[qpos + if triple { 3 } else { 1 }..body_end],
    )
    .into_owned();
    Ok((
        TKind::Str(StrLit {
            prefix: prefix.to_string(),
            triple,
            quote: q as char,
            body,
        }),
        end,
    ))
}

/// Простая (не-f) строка: вернуть (конец тела, конец после кавычек).
fn scan_simple(b: &[u8], qpos: usize) -> Result<(usize, usize), ()> {
    let triple = qpos + 2 < b.len() && b[qpos + 1] == b[qpos] && b[qpos + 2] == b[qpos];
    scan_simple_from(b, qpos, triple).map(|(a, c)| (a, c))
}

fn scan_simple_from(
    b: &[u8],
    qpos: usize,
    triple: bool,
) -> Result<(usize, usize), ()> {
    let n = b.len();
    let q = b[qpos];
    let mut i = qpos + if triple { 3 } else { 1 };
    while i < n {
        let c = b[i];
        if c == b'\\' {
            // `\` + перевод в одинарной — продолжение (как в Python).
            if i + 1 < n && (b[i + 1] == b'\n' || b[i + 1] == b'\r') {
                i += 2;
                if b[i - 1] == b'\r' && i < n && b[i] == b'\n' {
                    i += 1;
                }
                continue;
            }
            i += 2;
            continue;
        }
        if triple {
            if c == q && i + 2 < n && b[i + 1] == q && b[i + 2] == q {
                return Ok((i, i + 3));
            }
            i += 1;
        } else {
            if c == b'\n' || c == b'\r' {
                return Err(());
            }
            if c == q {
                return Ok((i, i + 1));
            }
            i += 1;
        }
    }
    Err(())
}

// ── AST (порядок полей — как `ast._fields`, его видит `_collect`) ──

#[derive(Debug, Clone)]
pub enum Expr {
    /// Склейка соседних литералов (`"a" "b"` — одна константа в `ast`).
    /// f-строка в склейке превращает всё в `FStr` (как `JoinedStr`).
    Str(Vec<StrLit>, u32),
    FStr(usize, usize, u32),
    Other,
    /// Имя с текстом (нужен для подсказок `Assign`: `names[0]`).
    Name(String),
    Tuple(Vec<Expr>),
    List(Vec<Expr>),
    Set(Vec<Expr>),
    Dict(Vec<(Option<Expr>, Expr)>),
    /// Dict-comprehension (`{k: v for ...}`): в отличие от показа-словаря
    /// ключ ОБХОДИТСЯ как выражение (generic-ветка `_collect` по полям
    /// `DictComp(key, value, generators)` выводит и ключ тоже — проверено:
    /// `g = {"k": v for ...}` даёт `("k", "g")`, а не только hint).
    DictComp { key: Box<Expr>, value: Box<Expr>, gens: Vec<Expr> },
    /// Карта-паттерн `match` (`{"k": p, **rest}`): порядок
    /// `MatchMapping(keys, patterns, rest)` — СНАЧАЛА все ключи, затем
    /// все суб-паттерны, затем rest (не зипом, как показать-словарь!).
    MapPat { pairs: Vec<(Expr, Expr)>, rest: Option<Box<Expr>> },
    Call {
        func: Box<Expr>,
        args: Vec<Expr>,
        keywords: Vec<Expr>,
    },
    Attr(Box<Expr>),
    Sub {
        value: Box<Expr>,
        slice: Box<Expr>,
    },
    Starred(Box<Expr>),
    BoolOp(Vec<Expr>),
    BinOp(Box<Expr>, Box<Expr>),
    Unary(Box<Expr>),
    IfExp {
        test: Box<Expr>,
        body: Box<Expr>,
        orelse: Box<Expr>,
    },
    Compare(Box<Expr>, Vec<Expr>),
    Named {
        target: Box<Expr>,
        value: Box<Expr>,
    },
    Lambda {
        defaults: Vec<Expr>,
        body: Box<Expr>,
    },
    YieldOpt(Option<Box<Expr>>),
    Await(Box<Expr>),
}

#[derive(Debug, Clone)]
pub enum Stmt {
    Expr(Expr, u32),
    Assign {
        targets: Vec<Expr>,
        value: Expr,
        line: u32,
    },
    AnnAssign {
        target: Expr,
        annotation: Option<Expr>,
        value: Option<Expr>,
    },
    AugAssign {
        target: Expr,
        value: Expr,
    },
    Def {
        body: Vec<Stmt>,
    },
    Class {
        body: Vec<Stmt>,
    },
    If {
        test: Expr,
        body: Vec<Stmt>,
        orelse: Vec<Stmt>,
    },
    For {
        target: Expr,
        iter: Expr,
        body: Vec<Stmt>,
        orelse: Vec<Stmt>,
    },
    While {
        test: Expr,
        body: Vec<Stmt>,
        orelse: Vec<Stmt>,
    },
    With {
        items: Vec<(Expr, Option<Expr>)>,
        body: Vec<Stmt>,
    },
    Try {
        body: Vec<Stmt>,
        handlers: Vec<(Option<Expr>, Vec<Stmt>)>,
        orelse: Vec<Stmt>,
        finalbody: Vec<Stmt>,
    },
    Return(Option<Expr>),
    /// `assert x, "msg"`, `del`, `raise ...`: обход выражений по порядку
    /// (как generic-ветка `_collect` через `iter_fields`).
    Generic(Vec<Expr>),
    /// Плоский список стейтментов (тело `match`: subject, паттерны,
    /// guard'ы и тела в порядке полей `Match`/`match_case`).
    Flat(Vec<Stmt>),
    Pass,
}

// ── парсер ──

struct P<'a> {
    toks: Vec<STok>,
    pos: usize,
    src: &'a str,
}

impl<'a> P<'a> {
    fn peek(&self) -> Option<&STok> {
        let mut i = self.pos;
        while i < self.toks.len() {
            match self.toks[i].kind {
                TKind::Ws | TKind::Comment => i += 1,
                _ => return Some(&self.toks[i]),
            }
        }
        None
    }

    fn peek_kind(&self) -> Option<TKind> {
        self.peek().map(|t| t.kind.clone())
    }

    fn next(&mut self) -> Option<STok> {
        while self.pos < self.toks.len() {
            let t = self.toks[self.pos].clone();
            self.pos += 1;
            match t.kind {
                TKind::Ws | TKind::Comment => continue,
                _ => return Some(t),
            }
        }
        None
    }

    fn line_of(&self, byte_off: usize) -> u32 {
        line_at(self.src, byte_off)
    }
}

/// Номер строки символа по исходнику (1-based, как `lineno` в `ast`).
fn line_at(src: &str, byte_off: usize) -> u32 {
    src.as_bytes()[..byte_off.min(src.len())]
        .iter()
        .filter(|c| **c == b'\n')
        .count() as u32
        + 1
}

/// Разобрать файл в список стейтментов верхнего уровня.
pub fn parse_file(src: &str, toks: Vec<STok>) -> Result<Vec<Stmt>, ()> {
    let mut p = P { toks, pos: 0, src };
    parse_block(&mut p)
}

/// Блок стейтментов до `Dedent`/конца.
fn parse_block(p: &mut P) -> Result<Vec<Stmt>, ()> {
    let mut out = Vec::new();
    loop {
        match p.peek_kind() {
            None => break,
            Some(TKind::Dedent) => {
                p.next();
                break;
            }
            Some(TKind::Newline) => {
                p.next();
            }
            Some(TKind::Indent) => {
                // Отступ там, где блок не ждали — как `IndentationError`.
                return Err(());
            }
            _ => {
                // Составной стейтмент — самодостаточен; простой —
                // целой логической строкой (см. parse_simple_line).
                match p.peek() {
                    Some(STok { kind: TKind::Name(w), .. })
                        if matches!(
                            w.as_str(),
                            "def" | "async" | "class" | "if" | "for"
                                | "while" | "with" | "try" | "match"
                        ) =>
                    {
                        out.push(parse_stmt(p)?);
                    }
                    // Декоратор `@...` перед `def`/`class`.
                    Some(STok { kind: TKind::Op(o), .. }) if o == "@" => {
                        out.push(parse_stmt(p)?);
                    }
                    _ => {
                        out.extend(parse_simple_line(p)?);
                    }
                }
            }
        }
    }
    Ok(out)
}

/// Простая логическая строка (для блоков и однострочных тел).
fn parse_simple_line(p: &mut P) -> Result<Vec<Stmt>, ()> {
    let mut out = vec![parse_small(p)?];
    while matches!(p.peek_kind(), Some(TKind::Semi)) {
        p.next();
        // Висячая `;` в конце валидна (`a = b;` — `ast` её съедает).
        match p.peek_kind() {
            Some(TKind::Newline) | Some(TKind::Dedent) | None => break,
            _ => out.push(parse_small(p)?),
        }
    }
    // Конец логической строки: перевод, конец блока (Dedent идёт
    // вместо перевода у последней строки) или конец файла (последняя
    // строка без `\n` валидна, как в `ast.parse`).
    match p.peek_kind() {
        Some(TKind::Newline) => {
            p.next();
        }
        Some(TKind::Dedent) | None => {}
        _ => return Err(()),
    }
    Ok(out)
}

/// Один стейтмент (составной — целиком; вызывается только там, где
/// составной допустим: начало логической строки).
fn parse_stmt(p: &mut P) -> Result<Stmt, ()> {
    // Декораторы — пропустить целиком (эталон их не обходит).
    while matches!(p.peek_kind(), Some(TKind::Op(ref o)) if o == "@") {
        loop {
            match p.next() {
                Some(t) if matches!(t.kind, TKind::Newline) => break,
                Some(_) => continue,
                None => break,
            }
        }
    }
    let kw = match p.peek() {
        Some(STok { kind: TKind::Name(w), .. }) => w.clone(),
        _ => String::new(),
    };
    match kw.as_str() {
        "def" | "async" => parse_def(p),
        "class" => parse_class(p),
        "if" => parse_if(p),
        "for" => parse_for(p),
        "while" => parse_while(p),
        "with" => parse_with(p),
        "try" => parse_try(p),
        "match" => parse_match(p),
        _ => parse_simple(p),
    }
}

fn parse_def(p: &mut P) -> Result<Stmt, ()> {
    // `async def name(...)` / `def name(...)` — сигнатуру пропускаем
    // (дефолты и декораторы эталон не обходит), тело — разбираем.
    if matches!(p.peek_kind(), Some(TKind::Name(ref w)) if w == "async") {
        p.next();
    }
    expect_name(p, "def")?;
    match p.next() {
        Some(t) if matches!(t.kind, TKind::Name(_)) => {}
        _ => return Err(()),
    }
    skip_balanced(p)?; // параметры (со значениями по умолчанию)
    // Возможный `-> ...`.
    if matches!(p.peek_kind(), Some(TKind::Op(ref o)) if o == "->") {
        p.next();
        // Тип — до `:` (без вложенных лямбд — грубо, но сигнатуры простые;
        // иначе fallback).
        let mut depth = 0;
        loop {
            match p.next() {
                Some(t) => match t.kind {
                    TKind::LParen | TKind::LBracket | TKind::LBrace => {
                        depth += 1
                    }
                    TKind::RParen | TKind::RBracket | TKind::RBrace => {
                        depth -= 1
                    }
                    TKind::Colon if depth == 0 => break,
                    TKind::Newline => return Err(()),
                    _ => {}
                },
                None => return Err(()),
            }
        }
        let body = parse_body_after_colon(p)?;
        return Ok(Stmt::Def { body });
    }
    match p.next() {
        Some(t) if matches!(t.kind, TKind::Colon) => {}
        _ => return Err(()),
    }
    Ok(Stmt::Def { body: parse_body_after_colon(p)? })
}

fn parse_class(p: &mut P) -> Result<Stmt, ()> {
    expect_name(p, "class")?;
    match p.next() {
        Some(t) if matches!(t.kind, TKind::Name(_)) => {}
        _ => return Err(()),
    }
    // Базы/ключевые — до `:`.
    let mut depth = 0;
    loop {
        match p.next() {
            Some(t) => match t.kind {
                TKind::LParen | TKind::LBracket | TKind::LBrace => depth += 1,
                TKind::RParen | TKind::RBracket | TKind::RBrace => {
                    depth -= 1
                }
                TKind::Colon if depth == 0 => break,
                TKind::Newline => return Err(()),
                _ => {}
            },
            None => return Err(()),
        }
    }
    Ok(Stmt::Class { body: parse_body_after_colon(p)? })
}

/// Тело после `:`: либо блок с новой строки, либо простые стейтменты
/// в той же строке (`if x: "a"`).
fn parse_body_after_colon(p: &mut P) -> Result<Vec<Stmt>, ()> {
    match p.peek_kind() {
        Some(TKind::Newline) => {
            p.next();
            match p.peek_kind() {
                Some(TKind::Indent) => {
                    p.next();
                    parse_block(p)
                }
                // Пустое тело быть не может (`pass` обязателен) —
                // иначе это ошибка разбора.
                _ => Err(()),
            }
        }
        _ => {
            // Однострочник: `if x: y = "a"`.
            parse_simple_line(p)
        }
    }
}

fn parse_if(p: &mut P) -> Result<Stmt, ()> {
    expect_name(p, "if")?;
    let test = parse_expr(p)?;
    expect_colon(p)?;
    let body = parse_body_after_colon(p)?;
    // `elif` — вложенный `if` в `orelse`, как узлы `ast`.
    let orelse = parse_elif_else(p)?;
    Ok(Stmt::If { test, body, orelse })
}

/// Хвост `elif.../else` после тела `if`.
fn parse_elif_else(p: &mut P) -> Result<Vec<Stmt>, ()> {
    match p.peek() {
        Some(STok { kind: TKind::Name(w), .. }) if w == "elif" => {
            p.next();
            let test = parse_expr(p)?;
            expect_colon(p)?;
            let body = parse_body_after_colon(p)?;
            let orelse = parse_elif_else(p)?;
            Ok(vec![Stmt::If { test, body, orelse }])
        }
        Some(STok { kind: TKind::Name(w), .. }) if w == "else" => {
            p.next();
            expect_colon(p)?;
            parse_body_after_colon(p)
        }
        _ => Ok(Vec::new()),
    }
}

fn parse_for(p: &mut P) -> Result<Stmt, ()> {
    if matches!(p.peek_kind(), Some(TKind::Name(ref w)) if w == "async") {
        p.next();
    }
    expect_name(p, "for")?;
    // Цель — до первого `in` на глубине 0 (иначе `in` съестся сравнением,
    // как `i in x`). Вложенные `in` в цели невозможны (там нет лямбд
    // и сравнений в валидном коде).
    let target = parse_for_target(p)?;
    expect_name(p, "in")?;
    let iter = parse_expr(p)?;
    expect_colon(p)?;
    let body = parse_body_after_colon(p)?;
    let orelse = parse_else_only(p)?;
    Ok(Stmt::For { target, iter, body, orelse })
}

/// Цель `for`: токены до `in` на глубине 0 — подпарсером.
fn parse_for_target(p: &mut P) -> Result<Expr, ()> {
    let mut j = p.pos;
    let mut depth = 0i32;
    let mut end: Option<usize> = None;
    while j < p.toks.len() {
        match &p.toks[j].kind {
            TKind::LParen | TKind::LBracket | TKind::LBrace => depth += 1,
            TKind::RParen | TKind::RBracket | TKind::RBrace => depth -= 1,
            TKind::Name(w) if depth == 0 && w == "in" => {
                end = Some(j);
                break;
            }
            TKind::Newline | TKind::Indent | TKind::Dedent => break,
            _ => {}
        }
        j += 1;
    }
    let end = end.ok_or(())?;
    let slice = p.toks[p.pos..end].to_vec();
    // Кортеж целей (`for a, b in ...`): режем по запятым глубины 0.
    let mut parts: Vec<Vec<STok>> = vec![Vec::new()];
    let mut depth = 0i32;
    for t in slice {
        match t.kind {
            TKind::LParen | TKind::LBracket | TKind::LBrace => {
                depth += 1;
                parts.last_mut().expect("часть").push(t);
            }
            TKind::RParen | TKind::RBracket | TKind::RBrace => {
                depth -= 1;
                parts.last_mut().expect("часть").push(t);
            }
            TKind::Comma if depth == 0 => parts.push(Vec::new()),
            _ => parts.last_mut().expect("часть").push(t),
        }
    }
    let mut exprs = Vec::new();
    for part in parts {
        let mut sub = P { toks: part, pos: 0, src: p.src };
        let e = parse_expr_or_lambda(&mut sub)?;
        if sub.next().is_some() {
            return Err(());
        }
        if !is_target(&e) {
            return Err(());
        }
        exprs.push(e);
    }
    let target = if exprs.len() == 1 {
        exprs.pop().expect("один")
    } else {
        Expr::Tuple(exprs)
    };
    p.pos = end;
    Ok(target)
}

/// Только `else` (для `for`/`while`: `elif` там — ошибка).
fn parse_else_only(p: &mut P) -> Result<Vec<Stmt>, ()> {
    match p.peek() {
        Some(STok { kind: TKind::Name(w), .. }) if w == "else" => {
            p.next();
            expect_colon(p)?;
            parse_body_after_colon(p)
        }
        _ => Ok(Vec::new()),
    }
}

fn parse_while(p: &mut P) -> Result<Stmt, ()> {
    expect_name(p, "while")?;
    let test = parse_expr(p)?;
    expect_colon(p)?;
    let body = parse_body_after_colon(p)?;
    let orelse = parse_else_only(p)?;
    Ok(Stmt::While { test, body, orelse })
}

fn parse_with(p: &mut P) -> Result<Stmt, ()> {
    if matches!(p.peek_kind(), Some(TKind::Name(ref w)) if w == "async") {
        p.next();
    }
    expect_name(p, "with")?;
    let mut items = Vec::new();
    loop {
        let ctx = parse_expr(p)?;
        let vars = match p.peek() {
            Some(STok { kind: TKind::Name(w), .. }) if w == "as" => {
                p.next();
                Some(parse_expr(p)?)
            }
            _ => None,
        };
        items.push((ctx, vars));
        match p.peek_kind() {
            Some(TKind::Comma) => {
                p.next();
            }
            _ => break,
        }
    }
    expect_colon(p)?;
    let body = parse_body_after_colon(p)?;
    Ok(Stmt::With { items, body })
}

fn parse_try(p: &mut P) -> Result<Stmt, ()> {
    expect_name(p, "try")?;
    expect_colon(p)?;
    let body = parse_body_after_colon(p)?;
    let mut handlers = Vec::new();
    loop {
        match p.peek() {
            Some(STok { kind: TKind::Name(w), .. }) if w == "except" => {
                p.next();
                let typ = match p.peek_kind() {
                    Some(TKind::Colon) => None,
                    _ => {
                        let t = parse_expr(p)?;
                        // `except E as name:` — имя пропускаем.
                        if matches!(
                            p.peek(),
                            Some(STok { kind: TKind::Name(w), .. }) if w == "as"
                        ) {
                            p.next();
                            match p.next() {
                                Some(t)
                                    if matches!(
                                        t.kind,
                                        TKind::Name(_)
                                    ) => {}
                                _ => return Err(()),
                            }
                        }
                        Some(t)
                    }
                };
                expect_colon(p)?;
                let hbody = parse_body_after_colon(p)?;
                handlers.push((typ, hbody));
            }
            _ => break,
        }
    }
    let orelse = parse_else_only(p)?;
    let mut finalbody = Vec::new();
    if matches!(p.peek(), Some(STok { kind: TKind::Name(w), .. }) if w == "finally")
    {
        p.next();
        expect_colon(p)?;
        finalbody = parse_body_after_colon(p)?;
    }
    if handlers.is_empty() && finalbody.is_empty() {
        return Err(());
    }
    Ok(Stmt::Try { body, handlers, orelse, finalbody })
}

/// `match subject: case ...` — структурный pattern matching (Python 3.10+).
/// Паттерны отображаем в узлы выражений с тем же порядком обхода, что
/// generic-ветка `_collect` по полям `Match`/`match_case`: subject,
/// затем для каждого case — паттерн, guard, тело.
fn parse_match(p: &mut P) -> Result<Stmt, ()> {
    expect_name(p, "match")?;
    let subject = parse_expr(p)?;
    expect_colon(p)?;
    // Тело match — блок из `case`-веток.
    let mut cases: Vec<Stmt> = Vec::new();
    match p.peek_kind() {
        Some(TKind::Newline) => {
            p.next();
            match p.peek_kind() {
                Some(TKind::Indent) => {
                    p.next();
                }
                _ => return Err(()),
            }
        }
        _ => return Err(()),
    }
    loop {
        match p.peek_kind() {
            None => break,
            Some(TKind::Dedent) => {
                p.next();
                break;
            }
            Some(TKind::Newline) => {
                p.next();
            }
            _ => {
                // `case pattern [if guard]:`
                match p.peek() {
                    Some(STok { kind: TKind::Name(w), .. }) if w == "case" => {
                        p.next();
                    }
                    _ => return Err(()),
                }
                let pattern = parse_pattern(p)?;
                let guard = if matches!(
                    p.peek(),
                    Some(STok { kind: TKind::Name(w), .. }) if w == "if"
                ) {
                    p.next();
                    Some(parse_expr(p)?)
                } else {
                    None
                };
                expect_colon(p)?;
                let body = parse_body_after_colon(p)?;
                // Порядок `match_case(pattern, guard, body)`.
                cases.push(Stmt::Generic(vec![pattern]));
                if let Some(g) = guard {
                    cases.push(Stmt::Generic(vec![g]));
                }
                cases.extend(body);
            }
        }
    }
    // Subject — первым (как поле `Match.subject`).
    let mut all = vec![Stmt::Generic(vec![subject])];
    all.extend(cases);
    Ok(Stmt::Flat(all))
}

/// Паттерн `case`: OR → `|`-цепочка (как `BinOp` для обхода: обе стороны
/// видны), `as`/`*` — обёртки, литералы/имена/классы/карты — как
/// выражения (строки внутри извлекаются, как generic-веткой `ast`).
fn parse_pattern(p: &mut P) -> Result<Expr, ()> {
    let mut left = parse_as_pattern(p)?;
    while matches!(p.peek(), Some(STok { kind: TKind::Op(o), .. }) if o == "|")
    {
        p.next();
        let right = parse_as_pattern(p)?;
        left = Expr::BinOp(Box::new(left), Box::new(right));
    }
    Ok(left)
}

fn parse_as_pattern(p: &mut P) -> Result<Expr, ()> {
    // `*rest` — захват последовательности.
    if matches!(p.peek(), Some(STok { kind: TKind::Op(o), .. }) if o == "*") {
        p.next();
        let inner = parse_as_pattern(p)?;
        return Ok(Expr::Starred(Box::new(inner)));
    }
    let e = parse_primary_pattern(p)?;
    // `... as name` — имя привязки строк не несёт.
    if matches!(p.peek(), Some(STok { kind: TKind::Name(w), .. }) if w == "as") {
        p.next();
        match p.next() {
            Some(t) if matches!(t.kind, TKind::Name(_)) => {}
            _ => return Err(()),
        }
    }
    Ok(e)
}

fn parse_primary_pattern(p: &mut P) -> Result<Expr, ()> {
    match p.peek() {
        Some(STok { kind: TKind::Name(w), .. }) if w == "_" => {
            p.next();
            return Ok(Expr::Other);
        }
        _ => {}
    }
    // Литерал/имя/скобки — как атом выражения (строки извлекаются).
    // Отличие: вызов-класс `C(...)` и точечные имена — тоже выражения.
    let t = p.next().ok_or(())?;
    match t.kind {
        TKind::Str(lit) => Ok(Expr::Str(vec![lit], p.line_of(t.start))),
        TKind::FStr => Ok(Expr::FStr(t.start, t.end, p.line_of(t.start))),
        TKind::Num => Ok(Expr::Other),
        TKind::Name(w) => {
            // Точечное имя (`Color.RED`) — цепочка атрибутов.
            let mut e = Expr::Name(w);
            while matches!(p.peek_kind(), Some(TKind::Dot)) {
                p.next();
                match p.next() {
                    Some(nt) if matches!(nt.kind, TKind::Name(_)) => {}
                    _ => return Err(()),
                }
                e = Expr::Attr(Box::new(e));
            }
            // Класс-паттерн `C(...)` — как вызов.
            if matches!(p.peek_kind(), Some(TKind::LParen)) {
                p.next();
                let (args, keywords) = parse_pattern_call_args(p)?;
                e = Expr::Call { func: Box::new(e), args, keywords };
            }
            Ok(e)
        }
        TKind::LParen => {
            // Кортеж-паттерн `(a, b)`.
            if matches!(p.peek_kind(), Some(TKind::RParen)) {
                p.next();
                return Ok(Expr::Tuple(Vec::new()));
            }
            let first = parse_pattern(p)?;
            let mut parts = vec![first];
            while matches!(p.peek_kind(), Some(TKind::Comma)) {
                p.next();
                if matches!(p.peek_kind(), Some(TKind::RParen)) {
                    break;
                }
                parts.push(parse_pattern(p)?);
            }
            expect_rparen(p)?;
            if parts.len() == 1 {
                Ok(parts.pop().expect("один"))
            } else {
                Ok(Expr::Tuple(parts))
            }
        }
        TKind::LBracket => {
            // Список-паттерн `[a, b]`.
            let mut parts = Vec::new();
            if matches!(p.peek_kind(), Some(TKind::RBracket)) {
                p.next();
                return Ok(Expr::List(parts));
            }
            loop {
                if matches!(p.peek(), Some(STok { kind: TKind::Op(o), .. }) if o == "*")
                {
                    p.next();
                    let v = parse_pattern(p)?;
                    parts.push(Expr::Starred(Box::new(v)));
                } else {
                    parts.push(parse_pattern(p)?);
                }
                match p.peek_kind() {
                    Some(TKind::Comma) => {
                        p.next();
                        if matches!(p.peek_kind(), Some(TKind::RBracket)) {
                            p.next();
                            break;
                        }
                    }
                    Some(TKind::RBracket) => {
                        p.next();
                        break;
                    }
                    _ => return Err(()),
                }
            }
            Ok(Expr::List(parts))
        }
        TKind::LBrace => {
            // Карта-паттерн `{"k": v, **rest}` — порядок MatchMapping:
            // ключи, затем суб-паттерны, затем rest (см. `MapPat`).
            let mut pairs: Vec<(Expr, Expr)> = Vec::new();
            let mut rest: Option<Expr> = None;
            if matches!(p.peek_kind(), Some(TKind::RBrace)) {
                p.next();
                return Ok(Expr::MapPat { pairs, rest: None });
            }
            loop {
                if matches!(p.peek(), Some(STok { kind: TKind::Op(o), .. }) if o == "**")
                {
                    p.next();
                    // `**` в паттерне — только последним (как в грамматике).
                    rest = Some(parse_pattern(p)?);
                    match p.peek_kind() {
                        Some(TKind::Comma) => {
                            p.next();
                        }
                        _ => {}
                    }
                    match p.next() {
                        Some(t) if matches!(t.kind, TKind::RBrace) => {}
                        _ => return Err(()),
                    }
                    break;
                }
                // Ключ — литерал/атом (как выражение).
                let k = parse_expr_or_lambda(p)?;
                match p.peek_kind() {
                    Some(TKind::Colon) => {
                        p.next();
                    }
                    _ => return Err(()),
                }
                let v = parse_pattern(p)?;
                pairs.push((k, v));
                match p.peek_kind() {
                    Some(TKind::Comma) => {
                        p.next();
                        if matches!(p.peek_kind(), Some(TKind::RBrace)) {
                            p.next();
                            break;
                        }
                    }
                    Some(TKind::RBrace) => {
                        p.next();
                        break;
                    }
                    _ => return Err(()),
                }
            }
            Ok(Expr::MapPat { pairs, rest: rest.map(Box::new) })
        }
        TKind::Op(ref o) if o == "-" => {
            // Отрицательный литерал `-1`.
            p.next();
            match p.next() {
                Some(nt) if matches!(nt.kind, TKind::Num) => Ok(Expr::Other),
                _ => Err(()),
            }
        }
        _ => Err(()),
    }
}

/// Аргументы класс-паттерна: позиционные + `name=pattern`.
fn parse_pattern_call_args(p: &mut P) -> Result<(Vec<Expr>, Vec<Expr>), ()> {
    let mut args = Vec::new();
    let mut keywords = Vec::new();
    if matches!(p.peek_kind(), Some(TKind::RParen)) {
        p.next();
        return Ok((args, keywords));
    }
    loop {
        if matches!(p.peek(), Some(STok { kind: TKind::Op(o), .. }) if o == "*")
        {
            p.next();
            let v = parse_pattern(p)?;
            args.push(Expr::Starred(Box::new(v)));
        } else if is_name_eq_ahead(p) {
            p.next();
            p.next();
            keywords.push(parse_pattern(p)?);
        } else {
            args.push(parse_pattern(p)?);
        }
        match p.peek_kind() {
            Some(TKind::Comma) => {
                p.next();
                if matches!(p.peek_kind(), Some(TKind::RParen)) {
                    p.next();
                    break;
                }
            }
            Some(TKind::RParen) => {
                p.next();
                break;
            }
            _ => return Err(()),
        }
    }
    Ok((args, keywords))
}

// ── простые стейтменты ──

/// Простая строка: `a = "x"; f("y")`. Возвращает ОДИН stmt (точка
/// с запятой разбирается вызывающим в несколько).
fn parse_simple(p: &mut P) -> Result<Stmt, ()> {
    parse_small(p)
}

fn parse_small(p: &mut P) -> Result<Stmt, ()> {
    // Ключевые слова без выражений.
    match p.peek() {
        Some(STok { kind: TKind::Name(w), .. })
            if w == "pass" || w == "break" || w == "continue" =>
        {
            p.next();
            return Ok(Stmt::Pass);
        }
        Some(STok { kind: TKind::Name(w), .. })
            if w == "global" || w == "nonlocal" =>
        {
            // Имена, не строки, — нечего извлекать.
            loop {
                match p.next() {
                    Some(t)
                        if matches!(t.kind, TKind::Newline | TKind::Semi) =>
                    {
                        break;
                    }
                    Some(t)
                        if matches!(
                            t.kind,
                            TKind::Name(_) | TKind::Comma
                        ) => {}
                    _ => return Err(()),
                }
            }
            return Ok(Stmt::Pass);
        }
        Some(STok { kind: TKind::Name(w), .. }) if w == "del" => {
            p.next();
            let mut exprs = vec![parse_expr(p)?];
            while matches!(p.peek_kind(), Some(TKind::Comma)) {
                p.next();
                exprs.push(parse_expr(p)?);
            }
            return Ok(Stmt::Generic(exprs));
        }
        Some(STok { kind: TKind::Name(w), .. }) if w == "yield" => {
            // Голый yield-стейтмент (строгая позиция).
            p.next();
            let v = parse_yield_after(p)?;
            return Ok(Stmt::Expr(v, 0));
        }
        Some(STok { kind: TKind::Name(w), .. })
            if w == "return" || w == "assert" || w == "raise" =>
        {
            let kw = w.clone();
            p.next();
            // Конец строки/разделитель — без выражений.
            match p.peek_kind() {
                Some(TKind::Newline) | Some(TKind::Semi) | None => {
                    return Ok(if kw == "return" {
                        Stmt::Return(None)
                    } else {
                        Stmt::Generic(Vec::new())
                    });
                }
                _ => {}
            }
            let first = parse_expr(p)?;
            let mut exprs = vec![first];
            while matches!(p.peek_kind(), Some(TKind::Comma)) {
                p.next();
                // Висячая запятая в конце — как кортеж.
                match p.peek_kind() {
                    Some(TKind::Newline) | Some(TKind::Semi) | None => break,
                    _ => exprs.push(parse_expr(p)?),
                }
            }
            return Ok(if kw == "return" && exprs.len() == 1 {
                Stmt::Return(Some(exprs.into_iter().next().expect("один")))
            } else {
                Stmt::Generic(exprs)
            });
        }
        Some(STok { kind: TKind::Name(w), .. })
            if w == "import" || w == "from" =>
        {
            // Импорты строк не несут — пропускаем до конца строки.
            loop {
                match p.next() {
                    Some(t)
                        if matches!(t.kind, TKind::Newline | TKind::Semi) => {
                            break;
                        }
                    Some(_) => continue,
                    None => break,
                }
            }
            return Ok(Stmt::Pass);
        }
        _ => {}
    }
    // Иначе — выражение с возможным присваиванием (списком через
    // запятую: `a, b = 1, 2`, голый кортеж `"a", "b"`).
    let first = parse_exprlist(p)?;
    if first.len() == 1 {
        let first = first.into_iter().next().expect("один");
        return small_single(p, first);
    }
    // Несколько: только присваивание (`a, b = ...`) или голый кортеж.
    if matches!(p.peek_kind(), Some(TKind::Eq))
        && first.iter().all(is_target)
    {
        p.next();
        // Yield как значение — строгая позиция (финальная).
        if is_yield_ahead(p) {
            p.next();
            let value = parse_yield_after(p)?;
            return Ok(Stmt::Assign { targets: first, value, line: 0 });
        }
        let value = parse_assign_value(p)?;
        return Ok(Stmt::Assign { targets: first, value, line: 0 });
    }
    // Голый кортеж-стейтмент (как `Expr(Tuple)` в `ast`).
    Ok(Stmt::Expr(Expr::Tuple(first), 0))
}

/// Список выражений через запятую на этом уровне (`a, b = 1, 2`,
/// голый кортеж). Висячая запятая перед концом (`a, = b`, `x = 1,`)
/// допустима, как кортеж в Python.
fn parse_exprlist(p: &mut P) -> Result<Vec<Expr>, ()> {
    let mut out = vec![parse_expr_or_lambda(p)?];
    loop {
        if !matches!(p.peek_kind(), Some(TKind::Comma)) {
            break;
        }
        if is_exprlist_end_ahead(p) {
            p.next();
            break;
        }
        p.next();
        out.push(parse_expr_or_lambda(p)?);
    }
    Ok(out)
}

/// За запятой — конец списка (`=`, `:`, конец строки/блока/файла,
/// закрывающая скобка): запятая висячая.
fn is_exprlist_end_ahead(p: &P) -> bool {
    // Подсмотреть второй токен: первый — Comma (проверен вызывающим).
    let mut i = p.pos;
    // Пропустить первую запятую уже подразумевается; ищем СЛЕДУЮЩИЙ.
    let mut seen_comma = false;
    while i < p.toks.len() {
        match &p.toks[i].kind {
            TKind::Ws | TKind::Comment => i += 1,
            TKind::Comma if !seen_comma => {
                seen_comma = true;
                i += 1;
            }
            other => {
                return matches!(
                    other,
                    TKind::Eq
                        | TKind::Colon
                        | TKind::Newline
                        | TKind::Semi
                        | TKind::RParen
                        | TKind::RBracket
                        | TKind::RBrace
                        | TKind::Dedent
                        | TKind::Indent
                );
            }
        }
    }
    true // конец файла после запятой — тоже висячая
}

/// Значение присваивания: список в кортеж (`x = 1, 2` — `Tuple`).
fn parse_assign_value(p: &mut P) -> Result<Expr, ()> {
    let mut vals = parse_exprlist(p)?;
    if vals.len() == 1 {
        Ok(vals.pop().expect("один"))
    } else {
        Ok(Expr::Tuple(vals))
    }
}

/// Одно выражение с возможным `=`/`:`/augassign (без запятых).
fn small_single(p: &mut P, first: Expr) -> Result<Stmt, ()> {
    match p.peek_kind() {
        Some(TKind::Eq) => {
            // Присваивание: цель обязана быть целью (иначе SyntaxError).
            // Цепочка `a = b = v`, значение — список в кортеж.
            if !is_target(&first) {
                return Err(());
            }
            let mut targets = vec![first];
            loop {
                p.next(); // съесть `=`
                // `a =` в конце — ошибка.
                match p.peek_kind() {
                    Some(TKind::Newline)
                    | Some(TKind::Semi)
                    | Some(TKind::Dedent)
                    | None => {
                        return Err(());
                    }
                    _ => {}
                }
                // Yield-значение — финальное (цепочка дальше не идёт).
                if is_yield_ahead(p) {
                    p.next();
                    let value = parse_yield_after(p)?;
                    return Ok(Stmt::Assign { targets, value, line: 0 });
                }
                let e = parse_expr_or_lambda(p)?;
                if matches!(p.peek_kind(), Some(TKind::Eq)) {
                    // Промежуточное звено цепочки — тоже цель.
                    if !is_target(&e) {
                        return Err(());
                    }
                    targets.push(e);
                    continue;
                }
                // Значение: дальше могут быть `, ...` в кортеж.
                let mut vals = vec![e];
                loop {
                    if !matches!(p.peek_kind(), Some(TKind::Comma)) {
                        break;
                    }
                    if is_exprlist_end_ahead(p) {
                        p.next();
                        break;
                    }
                    p.next();
                    vals.push(parse_expr_or_lambda(p)?);
                }
                let value = if vals.len() == 1 {
                    vals.pop().expect("один")
                } else {
                    Expr::Tuple(vals)
                };
                return Ok(Stmt::Assign { targets, value, line: 0 });
            }
        }
        Some(TKind::Colon) => {
            // Аннотация `x: T [= v]` (значение — тоже список в кортеж).
            if !is_target(&first) {
                return Err(());
            }
            p.next();
            let annotation = parse_expr(p)?;
            let value = if matches!(p.peek_kind(), Some(TKind::Eq)) {
                p.next();
                // Yield-значение — строгая позиция.
                if is_yield_ahead(p) {
                    p.next();
                    Some(parse_yield_after(p)?)
                } else {
                    Some(parse_assign_value(p)?)
                }
            } else {
                None
            };
            return Ok(Stmt::AnnAssign {
                target: first,
                annotation: Some(annotation),
                value,
            });
        }
        Some(TKind::Op(ref o))
            if matches!(
                o.as_str(),
                "+=" | "-=" | "*=" | "/=" | "%=" | "&=" | "|=" | "^=" | "<<="
                    | ">>=" | "**=" | "//=" | "@="
            ) =>
        {
            if !is_target(&first) {
                return Err(());
            }
            p.next();
            // Значение augassign — тоже список в кортеж (`x += 1, 2`).
            // Yield-значение — строгая позиция.
            let value = if is_yield_ahead(p) {
                p.next();
                parse_yield_after(p)?
            } else {
                parse_assign_value(p)?
            };
            return Ok(Stmt::AugAssign { target: first, value });
        }
        _ => {}
    }
    Ok(Stmt::Expr(first, 0))
}

/// Может ли выражение быть целью присваивания.
fn is_target(e: &Expr) -> bool {
    matches!(
        e,
        Expr::Name(_)
            | Expr::Tuple(_)
            | Expr::List(_)
            | Expr::Starred(_)
            | Expr::Attr(_)
            | Expr::Sub { .. }
    )
}

fn expect_name(p: &mut P, w: &str) -> Result<(), ()> {
    match p.next() {
        Some(t) if matches!(t.kind, TKind::Name(ref n) if n == w) => Ok(()),
        _ => Err(()),
    }
}

fn expect_colon(p: &mut P) -> Result<(), ()> {
    match p.next() {
        Some(t) if matches!(t.kind, TKind::Colon) => Ok(()),
        _ => Err(()),
    }
}

/// Пропустить сбалансированную скобочную группу (параметры `def`).
fn skip_balanced(p: &mut P) -> Result<(), ()> {
    let mut depth = 0;
    loop {
        match p.next() {
            Some(t) => match t.kind {
                TKind::LParen | TKind::LBracket | TKind::LBrace => {
                    depth += 1
                }
                TKind::RParen | TKind::RBracket | TKind::RBrace => {
                    depth -= 1;
                    if depth == 0 {
                        return Ok(());
                    }
                    if depth < 0 {
                        return Err(());
                    }
                }
                TKind::Newline => return Err(()),
                _ => {}
            },
            None => return Err(()),
        }
    }
}

// ── выражения (приоритеты Python) ──

fn parse_expr(p: &mut P) -> Result<Expr, ()> {
    parse_named(p)
}

fn parse_named(p: &mut P) -> Result<Expr, ()> {
    let e = parse_ifexp(p)?;
    // Walrus `:=`: только с именем слева (иначе SyntaxError).
    if matches!(p.peek_kind(), Some(TKind::Op(ref o)) if o == ":=") {
        if !matches!(e, Expr::Name(_)) {
            return Err(());
        }
        p.next();
        let v = parse_named(p)?;
        return Ok(Expr::Named { target: Box::new(e), value: Box::new(v) });
    }
    Ok(e)
}

fn parse_ifexp(p: &mut P) -> Result<Expr, ()> {
    let body = parse_or(p)?;
    if matches!(p.peek(), Some(STok { kind: TKind::Name(w), .. }) if w == "if")
    {
        p.next();
        let test = parse_or(p)?;
        match p.peek() {
            Some(STok { kind: TKind::Name(w), .. }) if w == "else" => {
                p.next();
            }
            _ => return Err(()),
        }
        let orelse = parse_ifexp(p)?;
        return Ok(Expr::IfExp {
            test: Box::new(test),
            body: Box::new(body),
            orelse: Box::new(orelse),
        });
    }
    Ok(body)
}

fn parse_or(p: &mut P) -> Result<Expr, ()> {
    let mut vals = vec![parse_and(p)?];
    while matches!(p.peek(), Some(STok { kind: TKind::Name(w), .. }) if w == "or")
    {
        p.next();
        vals.push(parse_and(p)?);
    }
    Ok(one_or_bool(vals))
}

fn parse_and(p: &mut P) -> Result<Expr, ()> {
    let mut vals = vec![parse_not(p)?];
    while matches!(p.peek(), Some(STok { kind: TKind::Name(w), .. }) if w == "and")
    {
        p.next();
        vals.push(parse_not(p)?);
    }
    Ok(one_or_bool(vals))
}

fn one_or_bool(mut vals: Vec<Expr>) -> Expr {
    if vals.len() == 1 {
        vals.pop().expect("один")
    } else {
        Expr::BoolOp(vals)
    }
}

fn parse_not(p: &mut P) -> Result<Expr, ()> {
    if matches!(p.peek(), Some(STok { kind: TKind::Name(w), .. }) if w == "not")
    {
        p.next();
        let e = parse_not(p)?;
        return Ok(Expr::Unary(Box::new(e)));
    }
    parse_compare(p)
}

fn parse_compare(p: &mut P) -> Result<Expr, ()> {
    let left = parse_bitor(p)?;
    let mut rights = Vec::new();
    loop {
        let is_cmp = match p.peek() {
            Some(STok { kind: TKind::Op(o), .. })
                if matches!(
                    o.as_str(),
                    "==" | "!=" | "<=" | ">=" | "<" | ">"
                ) =>
            {
                true
            }
            Some(STok { kind: TKind::Name(w), .. })
                if w == "in" || w == "is" =>
            {
                true
            }
            Some(STok { kind: TKind::Name(w), .. }) if w == "not" => {
                // `not in` — заглянуть дальше без потребления нельзя
                // дёшево: потребляем и проверяем `in`.
                p.next();
                match p.peek() {
                    Some(STok { kind: TKind::Name(w2), .. }) if w2 == "in" => {
                        p.next();
                        rights.push(parse_bitor(p)?);
                        continue;
                    }
                    _ => return Err(()),
                }
            }
            _ => false,
        };
        if !is_cmp {
            break;
        }
        // `in`/`is`/`is not` уже частично съедены выше; простые операторы —
        // здесь.
        match p.peek() {
            Some(STok { kind: TKind::Name(_), .. }) => {
                p.next();
                // Возможный `not` после `is`.
                if matches!(
                    p.peek(),
                    Some(STok { kind: TKind::Name(w), .. }) if w == "not"
                ) {
                    p.next();
                }
            }
            _ => {
                p.next();
            }
        }
        rights.push(parse_bitor(p)?);
    }
    if rights.is_empty() {
        Ok(left)
    } else {
        Ok(Expr::Compare(Box::new(left), rights))
    }
}

fn parse_bitor(p: &mut P) -> Result<Expr, ()> {
    parse_bin_left(p, &["|"], parse_bitxor)
}
fn parse_bitxor(p: &mut P) -> Result<Expr, ()> {
    parse_bin_left(p, &["^"], parse_bitand)
}
fn parse_bitand(p: &mut P) -> Result<Expr, ()> {
    parse_bin_left(p, &["&"], parse_shift)
}
fn parse_shift(p: &mut P) -> Result<Expr, ()> {
    parse_bin_left(p, &["<<", ">>"], parse_add)
}
fn parse_add(p: &mut P) -> Result<Expr, ()> {
    parse_bin_left(p, &["+", "-"], parse_mul)
}
fn parse_mul(p: &mut P) -> Result<Expr, ()> {
    parse_bin_left(p, &["*", "/", "//", "%", "@"], parse_unary)
}

fn parse_bin_left(
    p: &mut P,
    ops: &[&str],
    sub: fn(&mut P) -> Result<Expr, ()>,
) -> Result<Expr, ()> {
    let mut left = sub(p)?;
    loop {
        let hit = match p.peek() {
            Some(STok { kind: TKind::Op(o), .. }) if ops.contains(&o.as_str()) => {
                true
            }
            _ => false,
        };
        if !hit {
            break;
        }
        p.next();
        let right = sub(p)?;
        left = Expr::BinOp(Box::new(left), Box::new(right));
    }
    Ok(left)
}

fn parse_unary(p: &mut P) -> Result<Expr, ()> {
    match p.peek() {
        Some(STok { kind: TKind::Op(o), .. })
            if matches!(o.as_str(), "+" | "-" | "~") =>
        {
            p.next();
            Ok(Expr::Unary(Box::new(parse_unary(p)?)))
        }
        _ => parse_power(p),
    }
}

fn parse_power(p: &mut P) -> Result<Expr, ()> {
    let base = parse_await(p)?;
    if matches!(p.peek(), Some(STok { kind: TKind::Op(o), .. }) if o == "**")
    {
        p.next();
        // Справа — унарный (включая `-2**2` семантику разбора, значение
        // не важно — строк там нет, кроме как внутри операндов).
        let exp = parse_unary(p)?;
        return Ok(Expr::BinOp(Box::new(base), Box::new(exp)));
    }
    Ok(base)
}

fn parse_await(p: &mut P) -> Result<Expr, ()> {
    if matches!(p.peek(), Some(STok { kind: TKind::Name(w), .. }) if w == "await")
    {
        p.next();
        return Ok(Expr::Await(Box::new(parse_await(p)?)));
    }
    parse_primary(p)
}

/// Первичные: атом + цепочки вызовов/атрибутов/индексов.
fn parse_primary(p: &mut P) -> Result<Expr, ()> {
    let mut e = parse_atom(p)?;
    loop {
        match p.peek_kind() {
            Some(TKind::Dot) => {
                p.next();
                match p.next() {
                    Some(t) if matches!(t.kind, TKind::Name(_)) => {}
                    _ => return Err(()),
                }
                e = Expr::Attr(Box::new(e));
            }
            Some(TKind::LParen) => {
                p.next();
                let (args, keywords) = parse_call_args(p)?;
                e = Expr::Call {
                    func: Box::new(e),
                    args,
                    keywords,
                };
            }
            Some(TKind::LBracket) => {
                p.next();
                let slice = parse_sub_slice(p)?;
                e = Expr::Sub {
                    value: Box::new(e),
                    slice: Box::new(slice),
                };
            }
            _ => break,
        }
    }
    Ok(e)
}

/// Срез индекса: `expr` / `a:b` / `a:b:c` / кортеж (порядок полей
/// `Subscript(value, slice)` — важен только сам факт обхода).
fn parse_sub_slice(p: &mut P) -> Result<Expr, ()> {
    // Пустой срез `[:]` — без строк.
    if matches!(p.peek_kind(), Some(TKind::RBracket)) {
        p.next();
        return Ok(Expr::Other);
    }
    // Первый компонент или `:`.
    let mut parts: Vec<Option<Expr>> = Vec::new();
    if matches!(p.peek_kind(), Some(TKind::Colon)) {
        parts.push(None);
    } else {
        parts.push(Some(parse_ifexp(p)?));
    }
    let mut is_slice = false;
    while matches!(p.peek_kind(), Some(TKind::Colon)) {
        is_slice = true;
        p.next();
        match p.peek_kind() {
            Some(TKind::Colon) | Some(TKind::RBracket) | Some(TKind::Comma) => {
                parts.push(None);
            }
            _ => parts.push(Some(parse_ifexp(p)?)),
        }
    }
    // Кортеж срезов `a[1, 2]`.
    let mut extra = Vec::new();
    while matches!(p.peek_kind(), Some(TKind::Comma)) {
        p.next();
        if matches!(p.peek_kind(), Some(TKind::RBracket)) {
            break;
        }
        extra.push(parse_sub_slice(p)?);
    }
    match p.next() {
        Some(t) if matches!(t.kind, TKind::RBracket) => {}
        _ => return Err(()),
    }
    let mut all: Vec<Expr> = parts
        .into_iter()
        .filter_map(|x| x)
        .chain(extra.into_iter())
        .collect();
    if all.is_empty() {
        return Ok(Expr::Other);
    }
    if all.len() == 1 && !is_slice {
        return Ok(all.pop().expect("один"));
    }
    Ok(Expr::Tuple(all))
}

fn parse_call_args(p: &mut P) -> Result<(Vec<Expr>, Vec<Expr>), ()> {
    let mut args = Vec::new();
    let mut keywords = Vec::new();
    if matches!(p.peek_kind(), Some(TKind::RParen)) {
        p.next();
        return Ok((args, keywords));
    }
    loop {
        // `*args`, `**kw`.
        if matches!(p.peek(), Some(STok { kind: TKind::Op(o), .. }) if o == "**")
        {
            p.next();
            let v = parse_expr(p)?;
            keywords.push(v);
        } else if matches!(p.peek(), Some(STok { kind: TKind::Op(o), .. }) if o == "*")
        {
            p.next();
            let v = parse_expr(p)?;
            args.push(Expr::Starred(Box::new(v)));
        } else {
            // `name = value` — ключевой; иначе позиционный. Имя смотрим
            // без потребления: следующий токен `Eq`.
            let is_kw = match (p.peek(), ) {
                _ => is_name_eq_ahead(p),
            };
            if is_kw {
                let name_tok = p.next().expect("имя");
                p.next(); // `=`
                let v = parse_expr(p)?;
                let _ = name_tok;
                keywords.push(v);
            } else {
                // Лямбда как аргумент: `f(lambda x: x)` — `:` внутри
                // вызова относится к лямбде, разбираем выражением.
                args.push(parse_expr_or_lambda(p)?);
            }
        }
        match p.peek_kind() {
            Some(TKind::Comma) => {
                p.next();
                if matches!(p.peek_kind(), Some(TKind::RParen)) {
                    p.next();
                    break;
                }
            }
            Some(TKind::RParen) => {
                p.next();
                break;
            }
            _ => return Err(()),
        }
    }
    Ok((args, keywords))
}

/// Впереди `Name Eq` (но не `==`)?
fn is_name_eq_ahead(p: &P) -> bool {
    let mut i = p.pos;
    // Пропустить Ws/Comment.
    let mut first: Option<STok> = None;
    let mut second: Option<STok> = None;
    while i < p.toks.len() {
        match p.toks[i].kind {
            TKind::Ws | TKind::Comment => i += 1,
            _ => {
                first = Some(p.toks[i].clone());
                break;
            }
        }
    }
    let mut j = match first {
        Some(ref t) if matches!(t.kind, TKind::Name(_)) => {
            // найти индекс
            let mut k = p.pos;
            while k < p.toks.len() {
                match p.toks[k].kind {
                    TKind::Ws | TKind::Comment => k += 1,
                    _ => break,
                }
            }
            k + 1
        }
        _ => return false,
    };
    while j < p.toks.len() {
        match p.toks[j].kind {
            TKind::Ws | TKind::Comment => j += 1,
            _ => {
                second = Some(p.toks[j].clone());
                break;
            }
        }
    }
    matches!(second, Some(STok { kind: TKind::Eq, .. }))
}

/// Выражение или лямбда (в аргументах вызова и везде, где `:` — не срез).
fn parse_expr_or_lambda(p: &mut P) -> Result<Expr, ()> {
    if matches!(p.peek(), Some(STok { kind: TKind::Name(w), .. }) if w == "lambda")
    {
        return parse_lambda(p);
    }
    parse_expr(p)
}

fn parse_lambda(p: &mut P) -> Result<Expr, ()> {
    p.next(); // `lambda`
    parse_lambda_rest(p)
}

/// Хвост лямбды после уже съеденного `lambda` (параметры до `:` на
/// глубине 0, затем тело).
fn parse_lambda_rest(p: &mut P) -> Result<Expr, ()> {
    // Параметры — до `:` (со значениями; строки в дефолтах обходятся
    // generic-веткой, поэтому собираем их выражениями).
    let mut depth = 0;
    // Грубо: всё до `:` на глубине 0 — параметры; разбирать их не нужно,
    // кроме дефолтов после `=`. Упрощение: ищем `=` на глубине 0 и
    // разбираем дефолт выражением.
    let mut prelim: Vec<STok> = Vec::new();
    loop {
        match p.next() {
            Some(t) => match t.kind {
                TKind::LParen | TKind::LBracket | TKind::LBrace => {
                    depth += 1;
                    prelim.push(t);
                }
                TKind::RParen | TKind::RBracket | TKind::RBrace => {
                    depth -= 1;
                    prelim.push(t);
                }
                TKind::Colon if depth == 0 => break,
                TKind::Newline => return Err(()),
                _ => prelim.push(t),
            },
            None => return Err(()),
        }
    }
    // Дефолты из prelim: после `=` до `,` на глубине 0 — переразобрать
    // токенами нельзя дёшево; вместо этого разбираем заново подпарсером.
    // (Дефолты лямбд со строками — редкость; ниже — честный разбор.)
    let defaults = parse_lambda_defaults(p.src, prelim)?;
    let body = parse_expr_or_lambda(p)?;
    Ok(Expr::Lambda { defaults, body: Box::new(body) })
}

/// Дефолты параметров лямбды из сырых токенов: режем по `,`/`=` на
/// глубине 0 и разбираем значения подпарсером.
fn parse_lambda_defaults(src: &str, prelim: Vec<STok>) -> Result<Vec<Expr>, ()> {
    let mut out = Vec::new();
    let mut i = 0;
    while i < prelim.len() {
        // Найти `=` на глубине 0.
        let mut eq: Option<usize> = None;
        let mut j = i;
        let mut d = 0;
        while j < prelim.len() {
            match prelim[j].kind {
                TKind::LParen | TKind::LBracket | TKind::LBrace => d += 1,
                TKind::RParen | TKind::RBracket | TKind::RBrace => d -= 1,
                TKind::Eq if d == 0 => {
                    eq = Some(j);
                    break;
                }
                TKind::Comma if d == 0 => break,
                _ => {}
            }
            j += 1;
        }
        match eq {
            None => {
                // До следующей запятой на глубине 0 — без дефолта.
                let mut d = 0;
                while i < prelim.len() {
                    match prelim[i].kind {
                        TKind::LParen | TKind::LBracket | TKind::LBrace => {
                            d += 1
                        }
                        TKind::RParen | TKind::RBracket | TKind::RBrace => {
                            d -= 1
                        }
                        TKind::Comma if d == 0 => {
                            i += 1;
                            break;
                        }
                        _ => {}
                    }
                    i += 1;
                }
            }
            Some(e) => {
                // Значение — до запятой на глубине 0.
                let mut k = e + 1;
                let mut d2 = 0;
                while k < prelim.len() {
                    match prelim[k].kind {
                        TKind::LParen | TKind::LBracket | TKind::LBrace => {
                            d2 += 1
                        }
                        TKind::RParen | TKind::RBracket | TKind::RBrace => {
                            d2 -= 1
                        }
                        TKind::Comma if d2 == 0 => break,
                        _ => {}
                    }
                    k += 1;
                }
                let slice = prelim[e + 1..k].to_vec();
                let mut sub = P { toks: slice, pos: 0, src };
                out.push(parse_expr(&mut sub)?);
                i = k + if k < prelim.len() { 1 } else { 0 };
            }
        }
    }
    Ok(out)
}

/// Атом: литерал, имя, скобки, коллекции, comprehensions.
fn parse_atom(p: &mut P) -> Result<Expr, ()> {
    let t = p.next().ok_or(())?;
    match t.kind {
        TKind::Str(lit) => {
            let line = p.line_of(t.start);
            // Склейка соседних литералов (`"a" "b"` — одна константа).
            let mut bodies = vec![lit];
            let mut end = t.end;
            loop {
                match p.peek() {
                    Some(STok { kind: TKind::Str(_), .. }) => {
                        let nt = p.next().expect("строка");
                        match nt.kind {
                            TKind::Str(l) => {
                                end = nt.end;
                                bodies.push(l);
                            }
                            _ => unreachable!(),
                        }
                    }
                    _ => break,
                }
            }
            // f-строка среди соседей — вся склейка становится JoinedStr
            // (как в `ast`): обходится срезом исходника.
            if bodies.iter().any(|l| l.is_fstring()) {
                return Ok(Expr::FStr(t.start, end, line));
            }
            Ok(Expr::Str(bodies, line))
        }
        TKind::FStr => {
            let line = p.line_of(t.start);
            Ok(Expr::FStr(t.start, t.end, line))
        }
        TKind::Num => Ok(Expr::Other),
        TKind::Name(w) => {
            if w == "lambda" {
                return parse_lambda_rest(p);
            }
            Ok(Expr::Name(w))
        }
        TKind::LParen => parse_paren(p),
        TKind::LBracket => parse_bracket(p),
        TKind::LBrace => parse_brace(p),
        TKind::Op(ref o) if o == "..." => Ok(Expr::Other),
        TKind::Op(ref o) if o == "*" => {
            let v = parse_expr(p)?;
            Ok(Expr::Starred(Box::new(v)))
        }
        // `yield` вне строгих позиций (`x = yield ...`, `(yield)`,
        // голый стейтмент) — SyntaxError, здесь тоже отказ.
        _ => Err(()),
    }
}

/// Впереди `yield` (строгая позиция значения)?
fn is_yield_ahead(p: &P) -> bool {
    matches!(p.peek(), Some(STok { kind: TKind::Name(w), .. }) if w == "yield")
}

/// Впереди `from` (для `yield from`)?
fn is_from_ahead(p: &P) -> bool {
    matches!(p.peek(), Some(STok { kind: TKind::Name(w), .. }) if w == "from")
}

/// Полная yield-форма после уже съеденного `yield`: `from X` (одиночный),
/// голый (терминатор) или значение-список в кортеж. `Yield`/`YieldFrom`
/// обходятся одинаково (значение), поэтому узел один.
fn parse_yield_after(p: &mut P) -> Result<Expr, ()> {
    if is_from_ahead(p) {
        p.next();
        let v = parse_expr_or_lambda(p)?;
        // `yield from a, b` — ошибка (значение одиночное).
        if matches!(p.peek_kind(), Some(TKind::Comma)) {
            return Err(());
        }
        return Ok(Expr::YieldOpt(Some(Box::new(v))));
    }
    match p.peek_kind() {
        Some(TKind::Newline)
        | Some(TKind::Semi)
        | Some(TKind::Dedent)
        | Some(TKind::RParen)
        | Some(TKind::RBracket)
        | Some(TKind::RBrace)
        | None => Ok(Expr::YieldOpt(None)),
        _ => {
            let v = parse_assign_value(p)?;
            Ok(Expr::YieldOpt(Some(Box::new(v))))
        }
    }
}

/// `(...)`: пусто / выражение / кортеж / генератор.
fn parse_paren(p: &mut P) -> Result<Expr, ()> {
    if matches!(p.peek_kind(), Some(TKind::RParen)) {
        p.next();
        return Ok(Expr::Tuple(Vec::new()));
    }
    // `yield [from] x` внутри скобок (строгая позиция).
    if is_yield_ahead(p) {
        p.next();
        let v = parse_yield_after(p)?;
        expect_rparen(p)?;
        return Ok(v);
    }
    let first = parse_expr_or_lambda(p)?;
    // Генератор `(x for ...)` — содержимое обходим (elt + генераторы).
    if is_comp_for_ahead(p) {
        let mut parts = vec![first];
        parts.extend(parse_comp_generators(p)?);
        expect_rparen(p)?;
        return Ok(Expr::Tuple(parts));
    }
    // Кортеж.
    if matches!(p.peek_kind(), Some(TKind::Comma)) {
        let mut parts = vec![first];
        while matches!(p.peek_kind(), Some(TKind::Comma)) {
            p.next();
            if matches!(p.peek_kind(), Some(TKind::RParen)) {
                break;
            }
            parts.push(parse_expr_or_lambda(p)?);
        }
        expect_rparen(p)?;
        return Ok(Expr::Tuple(parts));
    }
    expect_rparen(p)?;
    Ok(first)
}

fn expect_rparen(p: &mut P) -> Result<(), ()> {
    match p.next() {
        Some(t) if matches!(t.kind, TKind::RParen) => Ok(()),
        _ => Err(()),
    }
}

/// `[...]`: список или list-comprehension.
fn parse_bracket(p: &mut P) -> Result<Expr, ()> {
    if matches!(p.peek_kind(), Some(TKind::RBracket)) {
        p.next();
        return Ok(Expr::List(Vec::new()));
    }
    let mut parts = Vec::new();
    loop {
        if matches!(p.peek(), Some(STok { kind: TKind::Op(o), .. }) if o == "*")
        {
            p.next();
            let v = parse_expr_or_lambda(p)?;
            parts.push(Expr::Starred(Box::new(v)));
        } else {
            let e = parse_expr_or_lambda(p)?;
            if is_comp_for_ahead(p) {
                parts.push(e);
                parts.extend(parse_comp_generators(p)?);
                match p.next() {
                    Some(t) if matches!(t.kind, TKind::RBracket) => {}
                    _ => return Err(()),
                }
                return Ok(Expr::List(parts));
            }
            parts.push(e);
        }
        match p.peek_kind() {
            Some(TKind::Comma) => {
                p.next();
                if matches!(p.peek_kind(), Some(TKind::RBracket)) {
                    p.next();
                    break;
                }
            }
            Some(TKind::RBracket) => {
                p.next();
                break;
            }
            _ => return Err(()),
        }
    }
    Ok(Expr::List(parts))
}

/// `{...}`: словарь, множество или comprehensions.
fn parse_brace(p: &mut P) -> Result<Expr, ()> {
    if matches!(p.peek_kind(), Some(TKind::RBrace)) {
        p.next();
        return Ok(Expr::Dict(Vec::new()));
    }
    if matches!(p.peek(), Some(STok { kind: TKind::Op(o), .. }) if o == "**") {
        return parse_dict_rest(p, Vec::new());
    }
    let first = parse_expr_or_lambda(p)?;
    if matches!(p.peek_kind(), Some(TKind::Colon)) {
        p.next();
        let val = parse_expr_or_lambda(p)?;
        // Comprehension (`{k: v for ...}`) — отдельный узел: ключ
        // выводится (см. `DictComp`), а не уходит в hint.
        if is_comp_for_ahead(p) {
            let gens = parse_comp_generators(p)?;
            match p.next() {
                Some(t) if matches!(t.kind, TKind::RBrace) => {}
                _ => return Err(()),
            }
            return Ok(Expr::DictComp {
                key: Box::new(first),
                value: Box::new(val),
                gens,
            });
        }
        let pairs = vec![(Some(first), val)];
        return parse_dict_rest(p, pairs);
    }
    let mut parts = vec![first];
    if is_comp_for_ahead(p) {
        parts.extend(parse_comp_generators(p)?);
        match p.next() {
            Some(t) if matches!(t.kind, TKind::RBrace) => {}
            _ => return Err(()),
        }
        return Ok(Expr::Set(parts));
    }
    loop {
        match p.peek_kind() {
            Some(TKind::Comma) => {
                p.next();
                if matches!(p.peek_kind(), Some(TKind::RBrace)) {
                    p.next();
                    break;
                }
                if matches!(p.peek(), Some(STok { kind: TKind::Op(o), .. }) if o == "*")
                {
                    p.next();
                    let v = parse_expr_or_lambda(p)?;
                    parts.push(Expr::Starred(Box::new(v)));
                } else {
                    parts.push(parse_expr_or_lambda(p)?);
                }
            }
            Some(TKind::RBrace) => {
                p.next();
                break;
            }
            _ => return Err(()),
        }
    }
    Ok(Expr::Set(parts))
}

/// Хвост словаря после первой пары: `, k: v` / `, **x`.
fn parse_dict_rest(
    p: &mut P,
    mut pairs: Vec<(Option<Expr>, Expr)>,
) -> Result<Expr, ()> {
    loop {
        match p.peek_kind() {
            Some(TKind::Comma) => {
                p.next();
                if matches!(p.peek_kind(), Some(TKind::RBrace)) {
                    p.next();
                    break;
                }
                if matches!(p.peek(), Some(STok { kind: TKind::Op(o), .. }) if o == "**")
                {
                    p.next();
                    let v = parse_expr_or_lambda(p)?;
                    pairs.push((None, v));
                } else {
                    let k = parse_expr_or_lambda(p)?;
                    match p.peek_kind() {
                        Some(TKind::Colon) => {
                            p.next();
                        }
                        _ => return Err(()),
                    }
                    let v = parse_expr_or_lambda(p)?;
                    pairs.push((Some(k), v));
                }
            }
            Some(TKind::RBrace) => {
                p.next();
                break;
            }
            _ => return Err(()),
        }
    }
    Ok(Expr::Dict(pairs))
}

fn is_comp_for_ahead(p: &P) -> bool {
    // Впереди `for`/`async for` на том же уровне (comprehension).
    let mut i = p.pos;
    let mut depth = 0i32;
    while i < p.toks.len() {
        match &p.toks[i].kind {
            TKind::Ws | TKind::Comment | TKind::Newline => i += 1,
            TKind::LParen | TKind::LBracket | TKind::LBrace => {
                depth += 1;
                i += 1;
            }
            TKind::RParen | TKind::RBracket | TKind::RBrace => {
                if depth == 0 {
                    return false;
                }
                depth -= 1;
                i += 1;
            }
            TKind::Name(w) if depth == 0 && (w == "for" || w == "async") => {
                return true;
            }
            TKind::Comma if depth == 0 => return false,
            _ => i += 1,
        }
    }
    false
}

/// Генераторы comprehension-хвоста: `for ... in ... [if ...]*`.
fn parse_comp_generators(p: &mut P) -> Result<Vec<Expr>, ()> {
    let mut out = Vec::new();
    loop {
        if matches!(p.peek(), Some(STok { kind: TKind::Name(w), .. }) if w == "async")
        {
            p.next();
        }
        match p.peek() {
            Some(STok { kind: TKind::Name(w), .. }) if w == "for" => {
                p.next();
            }
            _ => break,
        }
        // Цель — targetlist до `in` (как у statement-`for`): `parse_expr`
        // здесь нельзя — сравнение съело бы сам `in` (`for x in y`
        // разбиралось бы как `x in y` и роняло весь файл).
        let target = parse_for_target(p)?;
        expect_name(p, "in")?;
        let iter = parse_expr_or_lambda(p)?;
        out.push(target);
        out.push(iter);
        while matches!(p.peek(), Some(STok { kind: TKind::Name(w), .. }) if w == "if")
        {
            p.next();
            out.push(parse_expr_or_lambda(p)?);
        }
    }
    if out.is_empty() {
        return Err(());
    }
    Ok(out)
}

// ── декодер литерала и обход (`_collect`) ──

/// Декодировать один строковый литерал в runtime-строку (`None` — байты
/// (`b"..."`), неудача (`\\N{...}` без таблицы, кривой escape) или
/// f-строка: вызывающий решает (пропуск / срез), как `ast.literal_eval`.
pub fn decode_py_literal(lit: &StrLit) -> Option<String> {
    if lit.is_bytes() || lit.is_fstring() {
        return None;
    }
    let raw = lit.is_raw();
    let chars: Vec<char> = lit.body.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c != '\\' {
            out.push(c);
            i += 1;
            continue;
        }
        if raw {
            // В raw-строке backslash буквален, но для СКАНИРОВАНИЯ конца
            // кавычка после него не закрывает (токенизатор уже учёл).
            out.push('\\');
            i += 1;
            continue;
        }
        if i + 1 >= chars.len() {
            // Висячий backslash в конце — токенизатор такого не даёт
            // (кроме `\\\n`-продолжения, которое он съел).
            return None;
        }
        let e = chars[i + 1];
        match e {
            'n' => { out.push('\n'); i += 2; }
            't' => { out.push('\t'); i += 2; }
            'r' => { out.push('\r'); i += 2; }
            '\'' => { out.push('\''); i += 2; }
            '"' => { out.push('"'); i += 2; }
            '\\' => { out.push('\\'); i += 2; }
            'a' => { out.push('\x07'); i += 2; }
            'b' => { out.push('\x08'); i += 2; }
            'f' => { out.push('\x0c'); i += 2; }
            'v' => { out.push('\x0b'); i += 2; }
            '\n' => { i += 2; } // продолжение строки
            'x' => {
                let v = hex_n(&chars, i + 2, 2)?;
                out.push(char::from_u32(v)?);
                i += 4;
            }
            'u' => {
                let v = hex_n(&chars, i + 2, 4)?;
                out.push(char::from_u32(v)?);
                i += 6;
            }
            'U' => {
                let v = hex_n(&chars, i + 2, 8)?;
                out.push(char::from_u32(v)?);
                i += 10;
            }
            'N' => {
                // Без таблицы имён — только отказ (см. модуль text).
                return None;
            }
            '0'..='7' => {
                let mut v: u32 = 0;
                let mut k = 0;
                while k < 3 {
                    match chars.get(i + 1 + k) {
                        Some(d @ '0'..='7') => {
                            v = v * 8 + (*d as u32 - '0' as u32);
                            k += 1;
                        }
                        _ => break,
                    }
                }
                if k == 0 {
                    return None;
                }
                out.push(char::from_u32(v & 0xff)?);
                i += 1 + k;
            }
            // Неизвестный escape в литералах Python остаётся как есть.
            _ => {
                out.push('\\');
                out.push(e);
                i += 2;
            }
        }
    }
    Some(out)
}

fn hex_n(chars: &[char], start: usize, count: usize) -> Option<u32> {
    if start + count > chars.len() {
        return None;
    }
    let mut v: u32 = 0;
    for c in &chars[start..start + count] {
        v = v.checked_mul(16)?.checked_add(c.to_digit(16)?)?;
    }
    Some(v)
}

/// Строки `splitlines(keepends=True)` один в один: границы `\n`, `\r`,
/// `\r\n`, `\v`, `\f`, `\x1c..\x1e`, `\x85`, `\u2028`, `\u2029`.
/// Нужны и `_line_hint` (`splitlines()[lineno-1]`), и `_node_slice`
/// (суммы `len()` строк до узла).
fn splitlines_keepends(src: &str) -> Vec<&str> {
    let mut lines = Vec::new();
    let mut start = 0usize;
    let mut it = src.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        let w = match c {
            '\n' => 1usize,
            '\r' => {
                if matches!(it.peek(), Some((_, '\n'))) {
                    it.next();
                    2
                } else {
                    1
                }
            }
            '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{85}'
            | '\u{2028}' | '\u{2029}' => c.len_utf8(),
            _ => continue,
        };
        lines.push(&src[start..i + w]);
        start = i + w;
    }
    lines.push(&src[start..]);
    lines
}

/// Подсказка-строка исходника для узла (`_line_hint`): обрезанная
/// stripped-строка с номером `line` (1-based), первые 60 символов
/// (срез `[:60]` — по символам, как в Python).
fn line_hint_of(src: &str, line: u32) -> String {
    let idx = line.saturating_sub(1) as usize;
    let lines = splitlines_keepends(src);
    let raw = lines.get(idx).copied().unwrap_or("");
    raw.trim_matches(is_py_space_local).chars().take(60).collect()
}

fn is_py_space_local(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}' <= c && c <= '\u{1f}')
}

/// Срез исходника f-строки — точная реплика `_node_slice`, ВКЛЮЧАЯ его
/// особенность: `sum(len(x) ...)` считает СИМВОЛЫ строк, а `col_offset`
/// — БАЙТЫ UTF-8, и сумма используется как символьный индекс в `src`.
/// На чистом ASCII это обычный срез; на не-ASCII до/внутри f-строки
/// Python режет со сдвигом (часто вообще ничего не находит) — повторяем
/// в точности, иначе тройки разойдутся (проверено зондом на CPython:
/// `счёт = f"итого {v}"` даёт `[]`, а не `итого {v}`).
fn fstr_slice(src: &str, start: usize, end: usize) -> String {
    let lines = splitlines_keepends(src);
    // Байтовые и символьные старты строк.
    let mut byte_base: Vec<usize> = Vec::with_capacity(lines.len() + 1);
    let mut char_base: Vec<usize> = Vec::with_capacity(lines.len() + 1);
    let mut bb = 0usize;
    let mut cb = 0usize;
    for l in &lines {
        byte_base.push(bb);
        char_base.push(cb);
        bb += l.len();
        cb += l.chars().count();
    }
    byte_base.push(bb);
    char_base.push(cb);
    // Строка байтового смещения (как `lineno`: первая строка, чей конец
    // past-the-offset; конец файла — последняя).
    let line_of = |p: usize| -> usize {
        let p = p.min(bb);
        let mut k = 0usize;
        while k + 1 < byte_base.len() && byte_base[k + 1] <= p {
            k += 1;
        }
        k.min(lines.len().saturating_sub(1))
    };
    let sl = line_of(start);
    let el = line_of(end);
    // Смешанная арифметика эталона: символьная база + БАЙТОВЫЙ col.
    let s = char_base[sl] + start.saturating_sub(byte_base[sl]);
    let e = char_base[el] + end.saturating_sub(byte_base[el]);
    let chars: Vec<char> = src.chars().collect();
    let n = chars.len();
    let (s, e) = (s.min(n), e.min(n));
    if s >= e {
        return String::new();
    }
    chars[s..e].iter().collect()
}

/// Обход с подсказками — эквивалент `_collect(node, hint)`.
/// Возвращает `None` при переполнении глубины (вызывающий уходит
/// в regex-fallback, как при `RecursionError` в эталоне).
struct Walker<'a> {
    src: &'a str,
    out: Vec<(String, String)>,
    depth: usize,
}

impl<'a> Walker<'a> {
    fn expr(&mut self, e: &Expr, hint: &str) -> Option<()> {
        self.depth += 1;
        if self.depth > 300 {
            return None;
        }
        let r = self.expr_inner(e, hint);
        self.depth -= 1;
        r
    }

    fn expr_inner(&mut self, e: &Expr, hint: &str) -> Option<()> {
        match e {
            Expr::Str(lits, line) => {
                // Склейка декодируется целиком; неудача части роняет всё
                // (как `literal_eval`, где `\N{BAD}` валит константу).
                // b-строки — не строки (как `isinstance(..., str)`).
                if lits.iter().any(|l| l.is_bytes()) {
                    return Some(());
                }
                let mut s = String::new();
                for l in lits {
                    s.push_str(&decode_py_literal(l)?);
                }
                let h = if hint.is_empty() {
                    line_hint_of(self.src, *line)
                } else {
                    hint.to_string()
                };
                self.out.push((s, h));
                Some(())
            }
            Expr::FStr(start, end, line) => {
                let s = fstr_slice(self.src, *start, *end);
                let h = if hint.is_empty() {
                    line_hint_of(self.src, *line)
                } else {
                    hint.to_string()
                };
                for t in regex_literals(&s) {
                    if looks_like_text(&t) {
                        self.out.push((t, h.clone()));
                    }
                }
                Some(())
            }
            Expr::Dict(pairs) => {
                for (k, v) in pairs {
                    match k {
                        Some(Expr::Str(lits, _)) => {
                            // Ключ — строковая константа: `key=<значение>`.
                            if lits.iter().any(|l| l.is_bytes()) {
                                self.expr(v, hint)?;
                            } else {
                                let mut ks = String::new();
                                let mut ok = true;
                                for l in lits {
                                    match decode_py_literal(l) {
                                        Some(d) => ks.push_str(&d),
                                        None => {
                                            ok = false;
                                            break;
                                        }
                                    }
                                }
                                if ok {
                                    self.expr(v, &format!("key={ks}"))?;
                                } else {
                                    self.expr(v, hint)?;
                                }
                            }
                        }
                        Some(kk) => {
                            // Сложный ключ (f-строка, вызов...): значение
                            // обходится, ключ — тоже (как generic-ветка
                            // по полям `keys`/`values` в `_collect`? Нет:
                            // `_collect` для Dict идёт по zip и ключ
                            // отдельно НЕ обходит — только значение!).
                            // Внимание: ключ здесь НЕ обходится.
                            let _ = kk;
                            self.expr(v, hint)?;
                        }
                        None => self.expr(v, hint)?, // `**x`
                    }
                }
                Some(())
            }
            Expr::DictComp { key, value, gens } => {
                // Порядок полей `DictComp(key, value, generators)`.
                self.expr(key, hint)?;
                self.expr(value, hint)?;
                for g in gens {
                    self.expr(g, hint)?;
                }
                Some(())
            }
            Expr::MapPat { pairs, rest } => {
                // Порядок `MatchMapping(keys, patterns, rest)`.
                for (k, _) in pairs {
                    self.expr(k, hint)?;
                }
                for (_, v) in pairs {
                    self.expr(v, hint)?;
                }
                if let Some(r) = rest {
                    self.expr(r, hint)?;
                }
                Some(())
            }
            Expr::Lambda { defaults, body } => {
                for d in defaults {
                    self.expr(d, hint)?;
                }
                self.expr(body, hint)
            }
            Expr::Named { target: _, value } => self.expr(value, hint),
            Expr::YieldOpt(v) => {
                if let Some(x) = v {
                    self.expr(x, hint)?;
                }
                Some(())
            }
            Expr::Await(x) | Expr::Unary(x) | Expr::Starred(x) | Expr::Attr(x) => {
                self.expr(x, hint)
            }
            Expr::BinOp(a, b) => {
                self.expr(a, hint)?;
                self.expr(b, hint)
            }
            Expr::BoolOp(vals) => {
                for v in vals {
                    self.expr(v, hint)?;
                }
                Some(())
            }
            Expr::IfExp { test, body, orelse } => {
                // Порядок полей `IfExp(test, body, orelse)`.
                self.expr(test, hint)?;
                self.expr(body, hint)?;
                self.expr(orelse, hint)
            }
            Expr::Compare(left, rights) => {
                self.expr(left, hint)?;
                for r in rights {
                    self.expr(r, hint)?;
                }
                Some(())
            }
            Expr::Call { func, args, keywords } => {
                self.expr(func, hint)?;
                for a in args {
                    self.expr(a, hint)?;
                }
                for k in keywords {
                    self.expr(k, hint)?;
                }
                Some(())
            }
            Expr::Sub { value, slice } => {
                self.expr(value, hint)?;
                self.expr(slice, hint)
            }
            Expr::Tuple(items)
            | Expr::List(items)
            | Expr::Set(items) => {
                for x in items {
                    self.expr(x, hint)?;
                }
                Some(())
            }
            Expr::Name(_) | Expr::Other => Some(()),
        }
    }

    fn stmt(&mut self, s: &Stmt, hint: &str) -> Option<()> {
        self.depth += 1;
        if self.depth > 300 {
            return None;
        }
        let r = self.stmt_inner(s, hint);
        self.depth -= 1;
        r
    }

    fn stmt_inner(&mut self, s: &Stmt, hint: &str) -> Option<()> {
        match s {
            Stmt::Expr(e, _) => self.expr(e, hint),
            Stmt::Return(v) => {
                if let Some(x) = v {
                    self.expr(x, hint)?;
                }
                Some(())
            }
            Stmt::Generic(exprs) => {
                for e in exprs {
                    self.expr(e, hint)?;
                }
                Some(())
            }
            Stmt::Flat(stmts) => {
                for st in stmts {
                    self.stmt(st, hint)?;
                }
                Some(())
            }
            Stmt::Assign { targets, value, .. } => {
                // Подсказка — первое имя цели (`names[0]` в эталоне:
                // имена собираются только из голых Name-целей).
                let mut name = String::new();
                for t in targets {
                    if let Expr::Name(id) = t {
                        if !id.is_empty() {
                            name = id.clone();
                            break;
                        }
                    }
                }
                let h = if hint.is_empty() { name } else { hint.to_string() };
                // Пустая подсказка — как `hint or ""`: линия НЕ
                // подставляется (в отличие от констант!).
                self.expr(value, &h)
            }
            Stmt::AnnAssign { target, annotation, value } => {
                // Generic-порядок полей `(target, annotation, value)`.
                self.expr(target, hint)?;
                if let Some(a) = annotation {
                    self.expr(a, hint)?;
                }
                if let Some(v) = value {
                    self.expr(v, hint)?;
                }
                Some(())
            }
            Stmt::AugAssign { target, value } => {
                self.expr(target, hint)?;
                self.expr(value, hint)
            }
            Stmt::Def { body } | Stmt::Class { body } => {
                // Docstring — первый голый СТРОКОВЫЙ стейтмент — пропуск.
                // (Только Constant-str: f-строка и b-строка в `ast`
                // docstring'ами не считаются и обходятся.)
                let mut body = body.as_slice();
                if let Some((Stmt::Expr(Expr::Str(lits, _), _), rest)) =
                    body.split_first()
                {
                    if lits.iter().all(|l| !l.is_bytes()) {
                        body = rest;
                    }
                }
                for st in body {
                    self.stmt(st, hint)?;
                }
                Some(())
            }
            Stmt::If { test, body, orelse } => {
                self.expr(test, hint)?;
                for st in body {
                    self.stmt(st, hint)?;
                }
                for st in orelse {
                    self.stmt(st, hint)?;
                }
                Some(())
            }
            Stmt::For { target, iter, body, orelse } => {
                self.expr(target, hint)?;
                self.expr(iter, hint)?;
                for st in body {
                    self.stmt(st, hint)?;
                }
                for st in orelse {
                    self.stmt(st, hint)?;
                }
                Some(())
            }
            Stmt::While { test, body, orelse } => {
                self.expr(test, hint)?;
                for st in body {
                    self.stmt(st, hint)?;
                }
                for st in orelse {
                    self.stmt(st, hint)?;
                }
                Some(())
            }
            Stmt::With { items, body } => {
                for (ctx, vars) in items {
                    self.expr(ctx, hint)?;
                    if let Some(v) = vars {
                        self.expr(v, hint)?;
                    }
                }
                for st in body {
                    self.stmt(st, hint)?;
                }
                Some(())
            }
            Stmt::Try { body, handlers, orelse, finalbody } => {
                for st in body {
                    self.stmt(st, hint)?;
                }
                for (typ, hbody) in handlers {
                    if let Some(t) = typ {
                        self.expr(t, hint)?;
                    }
                    for st in hbody {
                        self.stmt(st, hint)?;
                    }
                }
                for st in orelse {
                    self.stmt(st, hint)?;
                }
                for st in finalbody {
                    self.stmt(st, hint)?;
                }
                Some(())
            }
            Stmt::Pass => Some(()),
        }
    }
}

/// Строковые литералы из python-исходника — эквивалент
/// `_py_string_literals`: `(текст, подсказка)` с фильтром
/// `_looks_like_text` в конце. Пустой вход — пусто; ошибка разбора —
/// regex-fallback (как `SyntaxError` → `_regex_literals` в эталоне).
pub fn py_string_literals(src: &str) -> Vec<(String, String)> {
    use crate::text::dedent;
    if src.trim().is_empty() {
        return Vec::new();
    }
    let src = dedent(src);
    let toks = match tokenize(&src) {
        Ok(t) => t,
        Err(()) => return regex_fallback(&src),
    };
    let stmts = match parse_file(&src, toks) {
        Ok(s) => s,
        Err(()) => return regex_fallback(&src),
    };
    let mut w = Walker { src: &src, out: Vec::new(), depth: 0 };
    // Module-docstring: первый голый строковый стейтмент — пропуск,
    // только если за ним есть код (как `len(body) > 1` в эталоне).
    let mut body = stmts.as_slice();
    if body.len() > 1 {
        if let Some((Stmt::Expr(Expr::Str(lits, _), _), rest)) =
            body.split_first()
        {
            // b-строка — не docstring (в `ast` это Constant-bytes).
            if lits.iter().all(|l| !l.is_bytes()) {
                body = rest;
            }
        }
    }
    for st in body {
        if w.stmt(st, "").is_none() {
            return regex_fallback(&src);
        }
    }
    w.out.into_iter().filter(|(t, _)| looks_like_text(t)).collect()
}

/// Regex-fallback (`_regex_literals` + фильтр, подсказка `""`).
fn regex_fallback(src: &str) -> Vec<(String, String)> {
    regex_literals(src)
        .into_iter()
        .filter(|t| looks_like_text(t))
        .map(|t| (t, String::new()))
        .collect()
}

