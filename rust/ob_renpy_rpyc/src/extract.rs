//! Слой 4 — обход AST и извлечение (`_walk_ast` + helpers).
//!
//! Порт `_walk_ast(stmts, labeled=True)`, `_string_parts`,
//! `_sl_text_value`, `_show_text_parts`, `_code_literals` из эталона:
//! те же kinds (`dialogue`, `speaker`, `choice`, `translated_string`,
//! `python[:hint]`, `screen`), тот же порядок, те же пропуски.
//!
//! Тонкости, повторённые в точности:
//! * метка `Label` действует только внутри своего блока (восстановление
//!   при выходе);
//! * посещённые объекты — по идентичности (как `id()`), циклы безопасны;
//! * `_string_parts` для списков даёт `""`-плейсхолдеры под PyExpr
//!   (как comprehension с `else ""` в эталоне) — фильтрация пустот дело
//!   вызывающего `extract`, здесь — как есть;
//! * пункты меню короче 2 символов пропускаются, реплики — нет;
//! * generic-хвост (`children`/`entries`/`block`/`body`) идёт и после
//!   сработавшей ветки (кроме `Label`, который возвращается раньше).

use crate::pickle::{Node, Ref, Store, Value, node_truthy};
use crate::text::{
    decode_rpy_literal, looks_like_text, str_search_first, try_eval_string,
};
use crate::{Entry, RpycError};
use std::collections::HashSet;

/// Обойти `stmts` и собрать `(kind, text, label)` (как
/// `_walk_ast(stmts, labeled=True)`).
pub fn walk_labeled(value: &Value) -> Vec<Entry> {
    let mut ctx = Ctx {
        store: &value.store,
        out: Vec::new(),
        visited: HashSet::new(),
        label: String::new(),
    };
    // Ошибка здесь — только внутренняя (память под временные узлы);
    // битый вход отсечён раньше, на unpickle.
    let _ = ctx.walk_any(value.root);
    ctx.out
        .into_iter()
        .map(|(kind, text, label)| Entry { kind, text, label })
        .collect()
}

struct Ctx<'a> {
    store: &'a Store,
    out: Vec<(String, String, String)>,
    visited: HashSet<Ref>,
    label: String,
}

impl<'a> Ctx<'a> {
    fn add(&mut self, kind: &str, text: String) {
        // Метка фиксируется в момент добавления (как в эталоне).
        self.out.push((kind.to_string(), text, self.label.clone()));
    }

    /// `walk(nodes)`: список/кортеж — по элементам, иначе — узел.
    fn walk_any(&mut self, r: Ref) -> Result<(), RpycError> {
        match self.store.nodes.get(r) {
            Some(Node::List(items)) | Some(Node::Tuple(items)) => {
                let items = items.clone();
                for x in items {
                    self.walk_any(x)?;
                }
                Ok(())
            }
            _ => self.walk_node(r),
        }
    }

    /// `walk` одиночного узла (с защитой от циклов по идентичности).
    fn walk_node(&mut self, r: Ref) -> Result<(), RpycError> {
        if !self.visited.insert(r) {
            return Ok(());
        }
        let (nt, base) = node_names(self.store, r);

        // `Label` ВЛАДЕЕТ блоком: метка восстанавливается при выходе.
        if nt == "Label" {
            let name = get_attr(self.store, r, "name")
                .and_then(|a| as_str(self.store, a))
                .unwrap_or_default();
            let prev = self.label.clone();
            if !name.is_empty() {
                self.label = name;
            }
            if let Some(b) = get_attr(self.store, r, "block") {
                if node_truthy(&self.store.nodes, b) {
                    self.walk_any(b)?;
                }
            }
            self.label = prev;
            return Ok(());
        }

        if nt == "Say" || nt == "TranslateSay" {
            if let Some(what) = get_attr(self.store, r, "what") {
                for part in string_parts(self.store, what) {
                    self.add("dialogue", part);
                }
            }
            if let Some(who) = get_attr(self.store, r, "who") {
                for part in string_parts(self.store, who) {
                    self.add("speaker", part);
                }
            }
        } else if nt == "Menu" {
            if let Some(items) = get_attr(self.store, r, "items") {
                if node_truthy(&self.store.nodes, items) {
                    for item in as_seq(self.store, items) {
                        self.walk_menu_item(item)?;
                    }
                }
            }
            for attr in ["caption", "prompt", "who"] {
                if let Some(v) = get_attr(self.store, r, attr) {
                    for part in string_parts(self.store, v) {
                        if part.chars().count() >= 2 {
                            self.add("choice", part);
                        }
                    }
                }
            }
        } else if nt == "Translate" {
            if let Some(b) = get_attr(self.store, r, "block") {
                if node_truthy(&self.store.nodes, b) {
                    self.walk_any(b)?;
                }
            }
        } else if nt == "TranslateString" {
            if let Some(old) = get_attr(self.store, r, "old") {
                if let Some(s) = as_str(self.store, old) {
                    if !s.is_empty() {
                        self.add("translated_string", s);
                    }
                }
            }
        } else if nt == "Define" {
            let code = get_attr(self.store, r, "code");
            for (s, hint) in code_literals(self.store, code) {
                self.add(&python_kind(&hint), s);
            }
        } else if nt == "Default" {
            let code = get_attr(self.store, r, "code")
                .filter(|c| node_truthy(&self.store.nodes, *c))
                .or_else(|| get_attr(self.store, r, "value"));
            for (s, hint) in code_literals(self.store, code) {
                self.add(&python_kind(&hint), s);
            }
        } else if nt == "Python" {
            let code = get_attr(self.store, r, "code");
            for (s, hint) in code_literals(self.store, code) {
                self.add(&python_kind(&hint), s);
            }
        } else if nt == "Screen" {
            if let Some(s) = get_attr(self.store, r, "screen") {
                if node_truthy(&self.store.nodes, s) {
                    self.walk_any(s)?;
                }
            }
        } else if base == "SLDisplayable" {
            self.walk_displayable(r)?;
        } else if base == "Show" || base == "Scene" {
            for attr in ["imspec", "text", "what"] {
                if let Some(v) = get_attr(self.store, r, attr) {
                    let mut seen = HashSet::new();
                    for s in show_text_parts(self.store, v, &mut seen) {
                        self.add("screen", s);
                    }
                }
            }
        } else if base == "SLPython" {
            let code = get_attr(self.store, r, "code");
            for (s, hint) in code_literals(self.store, code) {
                self.add(&python_kind(&hint), s);
            }
        }

        // Generic-хвост: дети, ветки, блоки (как в эталоне — всегда).
        if let Some(children) = get_attr(self.store, r, "children") {
            if node_truthy(&self.store.nodes, children) {
                self.walk_any(children)?;
            }
        }
        if let Some(entries) = get_attr(self.store, r, "entries") {
            if node_truthy(&self.store.nodes, entries) {
                for e in as_seq(self.store, entries) {
                    if let Some(second) = seq_index(self.store, e, 1) {
                        self.walk_any(second)?;
                    }
                }
            }
        }
        if let Some(block) = get_attr(self.store, r, "block") {
            if node_truthy(&self.store.nodes, block) {
                self.walk_any(block)?;
            }
        }
        if let Some(body) = get_attr(self.store, r, "body") {
            if node_truthy(&self.store.nodes, body) {
                self.walk_any(body)?;
            }
        }
        Ok(())
    }

    /// Пункт меню: подпись + рекурсия в блок (`item[1]`/`item[2]`).
    fn walk_menu_item(&mut self, item: Ref) -> Result<(), RpycError> {
        let seq = as_seq(self.store, item);
        let is_seq = matches!(
            self.store.nodes.get(item),
            Some(Node::List(_)) | Some(Node::Tuple(_))
        );
        if is_seq {
            if let Some(cap) = seq.first() {
                for part in string_parts(self.store, *cap) {
                    if part.chars().count() >= 2 {
                        self.add("choice", part);
                    }
                }
            }
            // 2-кортеж — блок в `item[1]`, длиннее — в `item[2]`.
            if seq.len() == 2 {
                self.walk_any(seq[1])?;
            } else if seq.len() > 2 {
                self.walk_any(seq[2])?;
            }
        }
        Ok(())
    }

    /// `SLDisplayable`: текст виджетов из белого списка.
    fn walk_displayable(&mut self, r: Ref) -> Result<(), RpycError> {
        let disp = get_attr(self.store, r, "displayable");
        let dname = disp
            .map(|d| displayable_name(self.store, d))
            .unwrap_or_default();
        let dbase = dname.strip_prefix("_mock_").unwrap_or(&dname);
        const VISIBLE: [&str; 8] = [
            "Text",
            "_textbutton",
            "Label",
            "Input",
            "Button",
            "_label",
            "_input",
            "_button",
        ];
        if VISIBLE.contains(&dbase) {
            if let Some(pos) = get_attr(self.store, r, "positional") {
                if node_truthy(&self.store.nodes, pos) {
                    for src in positional_raw(self.store, pos) {
                        if let Some(v) = sl_text_value_str(&src) {
                            if looks_like_text(&v) {
                                self.add("screen", v);
                            }
                        }
                    }
                }
            }
            // `keyword` или `keywords` (как в эталоне — по очереди).
            let kw = get_attr(self.store, r, "keyword")
                .or_else(|| get_attr(self.store, r, "keywords"));
            if let Some(k) = kw {
                if let Some(d) = self.store.nodes.get(k) {
                    if let Node::Dict(data) = d {
                        let data = data.clone();
                        for kk in ["default", "value"] {
                            for (key, val) in &data.items {
                                if as_str(self.store, *key).as_deref()
                                    == Some(kk)
                                {
                                    if let Some(v) =
                                        sl_text_value_node(self.store, *val)
                                    {
                                        if looks_like_text(&v) {
                                            self.add("screen", v);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        Ok(())
    }
}

/// Вид python-записи: `python` или `python:<подсказка>`.
fn python_kind(hint: &str) -> String {
    if hint.is_empty() {
        "python".to_string()
    } else {
        format!("python:{hint}")
    }
}

/// `(nt, base)`: точное имя класса и имя без одного префикса `_mock_`
/// (как `type(nodes).__name__` и `removeprefix` в эталоне).
fn node_names(store: &Store, r: Ref) -> (String, String) {
    match store.nodes.get(r) {
        Some(Node::Object { class, .. }) => {
            match store.classes.get(*class) {
                Some(c) => {
                    let nt = c.type_name.clone();
                    let base = nt
                        .strip_prefix("_mock_")
                        .unwrap_or(&nt)
                        .to_string();
                    (nt, base)
                }
                None => ("?".to_string(), "?".to_string()),
            }
        }
        // Класс как значение: в Python `type(cls)` — `type`.
        Some(Node::Class(_)) => ("type".to_string(), "type".to_string()),
        _ => ("?".to_string(), "?".to_string()),
    }
}

/// Атрибут mock-объекта (у остальных — ничего, как `getattr(..., None)`).
fn get_attr(store: &Store, obj: Ref, name: &str) -> Option<Ref> {
    match store.nodes.get(obj) {
        Some(Node::Object { attrs, .. }) => {
            attrs.iter().find(|(k, _)| k == name).map(|(_, v)| *v)
        }
        _ => None,
    }
}

/// Узел как строка (`str`, включая `str`-подкласс с флагом кода).
fn as_str(store: &Store, r: Ref) -> Option<String> {
    match store.nodes.get(r) {
        Some(Node::Str(s)) | Some(Node::PyStr(s)) => Some(s.clone()),
        _ => None,
    }
}

/// Элементы последовательности (только список/кортеж — как `walk`
/// в эталоне: остальное идёт одиночным путём, здесь — пусто, вызывающий
/// решает сам).
fn as_seq(store: &Store, r: Ref) -> Vec<Ref> {
    match store.nodes.get(r) {
        Some(Node::List(items)) | Some(Node::Tuple(items)) => items.clone(),
        _ => Vec::new(),
    }
}

/// `seq[i]` для списков/кортежей.
fn seq_index(store: &Store, r: Ref, i: usize) -> Option<Ref> {
    match store.nodes.get(r) {
        Some(Node::List(items)) | Some(Node::Tuple(items)) => {
            items.get(i).copied()
        }
        _ => None,
    }
}

/// `__name__` дисплейабла: у класса — имя, у объекта — атрибут.
fn displayable_name(store: &Store, d: Ref) -> String {
    match store.nodes.get(d) {
        Some(Node::Class(i)) => store
            .classes
            .get(*i)
            .map(|c| c.type_name.clone())
            .unwrap_or_default(),
        Some(Node::Object { .. }) => get_attr(store, d, "__name__")
            .and_then(|a| as_str(store, a))
            .unwrap_or_default(),
        _ => String::new(),
    }
}

// ── _string_parts ──

/// Строковые части `what`/`who`/пункта меню.
///
/// Список `[«Привет, », PyExpr, «!»]` даёт `[«Привет, », «», «!»]`:
/// вставка кода превращается в пустую строку (она отфильтруется позже,
/// здесь — как есть, один в один с comprehension эталона).
pub fn string_parts(store: &Store, r: Ref) -> Vec<String> {
    match store.nodes.get(r) {
        Some(Node::Str(s)) => {
            if s.is_empty() {
                Vec::new()
            } else {
                vec![s.clone()]
            }
        }
        // Флаг `_ob_py_expr`: python-код целиком — не текст.
        Some(Node::PyStr(_)) => Vec::new(),
        Some(Node::Bytes(b)) => {
            if b.is_empty() {
                Vec::new()
            } else {
                vec![String::from_utf8_lossy(b).into_owned()]
            }
        }
        Some(Node::List(items)) | Some(Node::Tuple(items)) => {
            let items = items.clone();
            let mut out = Vec::new();
            for t in items {
                match store.nodes.get(t) {
                    Some(Node::Str(s)) if !s.is_empty() => {
                        out.push(s.clone());
                    }
                    Some(Node::Bytes(b)) if !b.is_empty() => {
                        out.push(String::from_utf8_lossy(b).into_owned());
                    }
                    Some(Node::Str(_))
                    | Some(Node::Bytes(_))
                    | Some(Node::PyStr(_)) => {
                        // Пустые — пропуск по фильтру `if ... and t`,
                        // PyExpr — плейсхолдер `""` (см. модуль).
                        if matches!(
                            store.nodes.get(t),
                            Some(Node::PyStr(s)) if !s.is_empty()
                        ) {
                            out.push(String::new());
                        }
                    }
                    _ => {}
                }
            }
            out
        }
        _ => Vec::new(),
    }
}

// ── _sl_text_value ──

/// Строковый литерал из позиционного аргумента `text`/`textbutton`:
/// PyExpr-источник (`'"Играть"'`) через `literal_eval`, иначе первый
/// литерал regex'ом с декодированием.
fn sl_text_value_node(store: &Store, r: Ref) -> Option<String> {
    let src = sl_raw_str(store, r)?;
    sl_text_value_str(&src)
}

fn sl_text_value_str(src: &str) -> Option<String> {
    if src.is_empty() {
        return None;
    }
    let src = src.trim();
    if src.is_empty() {
        return None;
    }
    // `ast.literal_eval`: только строка — вернуть; иначе — regex.
    if let Some(v) = try_eval_string(src) {
        return Some(v);
    }
    let t = str_search_first(src)?;
    if t.is_empty() {
        return None;
    }
    Some(decode_rpy_literal(&t))
}

/// Сырые источники позиционных аргументов (значения строк / `.source`);
/// вычисление в литерал — один раз у вызывающего (`_sl_text_value`).
fn positional_raw(store: &Store, r: Ref) -> Vec<String> {
    match store.nodes.get(r) {
        Some(Node::List(items)) | Some(Node::Tuple(items)) => {
            let items = items.clone();
            items.into_iter().filter_map(|x| sl_raw_str(store, x)).collect()
        }
        Some(Node::Str(s)) | Some(Node::PyStr(s)) => {
            s.chars().map(|c| c.to_string()).collect()
        }
        _ => Vec::new(),
    }
}

/// Сырой источник для `_sl_text_value`: сама строка или `.source`.
fn sl_raw_str(store: &Store, r: Ref) -> Option<String> {
    match store.nodes.get(r) {
        Some(Node::Str(s)) | Some(Node::PyStr(s)) => Some(s.clone()),
        Some(Node::Object { .. }) => {
            get_attr(store, r, "source").and_then(|a| as_str(store, a))
        }
        _ => None,
    }
}

// ── _show_text_parts ──

/// Текст `show text` / `scene text`: рекурсия по словарям и спискам,
/// PyExpr-источники через `_sl_text_value`, голые ASCII-слова без пробелов
/// (имена изображений) — пропуск.
fn show_text_parts(
    store: &Store,
    r: Ref,
    seen: &mut HashSet<Ref>,
) -> Vec<String> {
    if !seen.insert(r) {
        return Vec::new();
    }
    match store.nodes.get(r) {
        Some(Node::Dict(d)) => {
            let vals: Vec<Ref> = d.items.iter().map(|(_, v)| *v).collect();
            let mut out = Vec::new();
            for v in vals {
                out.extend(show_text_parts(store, v, seen));
            }
            out
        }
        Some(Node::List(items)) | Some(Node::Tuple(items)) => {
            let items = items.clone();
            let mut out = Vec::new();
            for v in items {
                out.extend(show_text_parts(store, v, seen));
            }
            out
        }
        Some(Node::Str(s)) | Some(Node::PyStr(s)) => {
            let s = s.clone();
            let is_code =
                matches!(store.nodes.get(r), Some(Node::PyStr(_)));
            if let Some(t) = sl_text_value_str(&s) {
                if looks_like_text(&t) {
                    return vec![t];
                }
            }
            if is_code {
                return Vec::new();
            }
            let st = s.trim().to_string();
            if !st.is_empty()
                && looks_like_text(&st)
                && (st.contains(' ') || st.chars().any(|c| c > '\x7f'))
            {
                return vec![st];
            }
            Vec::new()
        }
        _ => {
            // Объект с `.source` (как `getattr(v, "source", None)`).
            let src = match store.nodes.get(r) {
                Some(Node::Object { .. }) => {
                    get_attr(store, r, "source").and_then(|a| as_str(store, a))
                }
                _ => None,
            };
            match src {
                Some(s) if !s.is_empty() => match sl_text_value_str(&s) {
                    Some(t) if looks_like_text(&t) => vec![t],
                    _ => Vec::new(),
                },
                _ => Vec::new(),
            }
        }
    }
}

// ── _code_literals ──

/// Строковые литералы python-узла: `PyCode.source`, PyExpr-значение
/// (флаг `_ob_py_expr`), иначе — ничего (`co_consts` в нашей модели
/// непредставимы: `code`-объекты через белый список не проходят).
fn code_literals(store: &Store, code: Option<Ref>) -> Vec<(String, String)> {
    let Some(c) = code else {
        return Vec::new();
    };
    // Атрибут `source` (как `getattr(code, "source", "")`).
    let src = match store.nodes.get(c) {
        Some(Node::Object { .. }) => {
            get_attr(store, c, "source").and_then(|a| as_str(store, a))
        }
        // Сам узел — PyExpr-строка (как `Default.value`).
        Some(Node::PyStr(s)) => Some(s.clone()),
        _ => None,
    };
    match src {
        Some(s) if !s.trim().is_empty() => {
            crate::pyparse::py_string_literals(&s)
        }
        _ => Vec::new(),
    }
}
