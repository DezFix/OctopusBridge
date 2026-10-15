//! Распаковка `.rpyc` Ren'Py и извлечение строк для перевода.
//!
//! Rust-порт `.rpyc`-ветки из `app/core/renpy/parser.py` (эталона):
//! `_unpickle_rpyc` (фрейминг), `_RenPyUnpickler.find_class` + mock-классы
//! (pickle-VM), `_walk_ast` + `_string_parts` / `_sl_text_value` /
//! `_show_text_parts` / `_looks_like_text` / `_py_string_literals`
//! (обход AST и извлечение). Поведение повторяет Python один в один:
//! те же kinds, тот же порядок, те же пропуски. `.rpy`-разбор
//! (`_extract_line`) здесь НЕ портирован — только `.rpyc`-тракт.
//!
//! Слои:
//! * [`framing`] — RPC2-заголовок и zlib-разжатие (`_unpickle_rpyc`);
//! * [`pickle`] — минимальный интерпретатор pickle-протоколов 0–4,
//!   достаточный для AST Ren'Py, с защитой от hostile-pickle;
//! * [`extract`] — обход AST и извлечение (Say/Menu/Screen/Define/...);
//! * [`text`] — строковые фильтры и литералы python-узлов.
//!
//! Битый и враждебный вход даёт `Err`, никогда панику.

pub mod extract;
pub mod framing;
pub mod pickle;
pub mod pyparse;
pub mod text;

use std::fmt;

/// Ошибка распаковки/разбора `.rpyc`.
///
/// Все варианты — честный отказ без паники: так же, как Python возвращает
/// `None` из `_unpickle_rpyc` (а вызывающий `extract` молча пропускает файл).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RpycError {
    /// Битый фрейминг или сжатые данные (`Decode`).
    Decode(String),
    /// Враждебный pickle: запрещённый GLOBAL/REDUCE, PERSID, EXT и т.п.
    Unsafe(String),
    /// Превышен предохранитель (размер, глубина, число узлов).
    TooBig(String),
}

impl fmt::Display for RpycError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RpycError::Decode(m)
            | RpycError::Unsafe(m)
            | RpycError::TooBig(m) => write!(f, "{m}"),
        }
    }
}

impl std::error::Error for RpycError {}

/// Извлечённая строка: вид узла, текст и метка (`label`, `""` — вне метки).
///
/// Порядок — порядок `_walk_ast` с `labeled=True`. Дедупликации нет
/// (её делает вызывающий `extract`, как в Python).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    pub kind: String,
    pub text: String,
    pub label: String,
}

/// Распаковать байты `.rpyc` и извлечь `(kind, text, label)`.
///
/// Эквивалент связки `_unpickle_rpyc` + `_walk_ast(stmts, labeled=True)`:
/// фрейминг (RPC2 или legacy-зlib), unpickle mock-AST, обход. Верх объекта
/// обязан быть кортежем длины ≥ 2 (как `(data, stmts)` у Ren'Py), иначе —
/// `Err` (Python в этом случае молча берёт следующий слот / `None`).
pub fn extract_rpyc(data: &[u8]) -> Result<Vec<Entry>, RpycError> {
    let payload = framing::unframe(data)?;
    let root = pickle::loads(&payload)?;
    let stmts = match root.store.nodes.get(root.root) {
        Some(pickle::Node::Tuple(items)) if items.len() >= 2 => items[1],
        _ => {
            return Err(RpycError::Decode(
                "unpickle: верх обязан быть (data, stmts)".to_string(),
            ));
        }
    };
    let sub = pickle::Value { store: root.store, root: stmts };
    Ok(extract::walk_labeled(&sub))
}

#[cfg(test)]
mod tests;
