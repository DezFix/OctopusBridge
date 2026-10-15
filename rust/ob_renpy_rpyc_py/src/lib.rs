//! PyO3-обёртка распаковки `.rpyc`: `extract_rpyc` как обычная
//! Python-функция.
//!
//! Принимает байты `.rpyc`, возвращает список `(kind, text, label)`
//! (порядок `_walk_ast` с `labeled=True`). Битый/враждебный вход —
//! `ValueError`, а не падение интерпретатора: ядро возвращает `Err`,
//! здесь он превращается в исключение.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Распаковать `.rpyc` и извлечь строки.
///
/// Эквивалент связки `_unpickle_rpyc` + `_walk_ast(stmts, labeled=True)`.
#[pyfunction]
fn extract_rpyc(data: &[u8]) -> PyResult<Vec<(String, String, String)>> {
    ob_renpy_rpyc::extract_rpyc(data).map(|entries| {
        entries
            .into_iter()
            .map(|e| (e.kind, e.text, e.label))
            .collect()
    }).map_err(|e| PyValueError::new_err(e.to_string()))
}

#[pymodule]
fn _ob_renpy_rpyc_py(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(extract_rpyc, m)?)?;
    Ok(())
}
