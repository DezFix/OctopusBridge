//! PyO3-обёртка чистого перевода Ren'Py: `translate_text` как обычная
//! Python-функция.
//!
//! Принимает текст `.rpy` и словарь `{оригинал: перевод}` (порядок словаря
//! сохраняется — он влияет на порядок `missed`, как в Python), возвращает
//! `(новый_текст, число_замен, пропущенные)`. Плюс `find_literals`
//! (спаны в символах, как индексы Python) и `choose_method` (правило
//! `>= 3 → source`, иначе по флагу идентификаторов; подсчёт файлов и
//! ходьба по диску остаются в Python).
//!
//! Ошибок типов (`bytes` вместо `str`, не-строки в словаре) Rust не видит:
//! их отклоняет сам extractor PyO3 — вызывающий получает `TypeError`,
//! а не панику. Невалидный UTF-8 сюда вообще не доходит: граница
//! Python/Rust его не пропускает.

use pyo3::prelude::*;
use pyo3::types::PyDict;

/// Словарь Python -> упорядоченные пары (порядок вставки сохраняется).
fn mapping_to_vec(mapping: &Bound<'_, PyDict>) -> PyResult<Vec<(String, String)>> {
    let mut out = Vec::with_capacity(mapping.len());
    for (k, v) in mapping.iter() {
        let key: String = k.extract()?;
        let val: String = v.extract()?;
        out.push((key, val));
    }
    Ok(out)
}

/// Заменить литералы в тексте `.rpy` на переводы.
///
/// Эквивалент `sourcetr.translate_text`: `(новый_текст, число_замен,
/// пропущенные)`. Guards против кода/путей — те же, что в Python.
#[pyfunction]
fn translate_text(
    text: &str,
    mapping: &Bound<'_, PyDict>,
) -> PyResult<(String, usize, Vec<String>)> {
    let pairs = mapping_to_vec(mapping)?;
    Ok(ob_renpy::translate_text(text, &pairs))
}

/// Спаны литерала в двойных кавычках: `[(начало, конец), ...]`.
///
/// Индексы — в символах, как у Python-генератора `_find_literal_patterns`.
#[pyfunction]
fn find_literals(text: &str, literal: &str) -> Vec<(usize, usize)> {
    ob_renpy::find_literal_spans(text, literal)
}

/// Правило выбора способа: `{"method", "loose_rpy", "has_identifiers",
/// "reason"}` — те же поля и тексты, что у `universal.choose_method`.
///
/// `loose_rpy` считает Python (обход диска остаётся там); отрицательное
/// насыщаем в ноль.
#[pyfunction]
fn choose_method(
    py: Python<'_>,
    loose_rpy: i64,
    has_identifiers: bool,
) -> PyResult<Py<PyDict>> {
    let loose = u64::try_from(loose_rpy).unwrap_or(0);
    let c = ob_renpy::choose_method(loose, has_identifiers);
    let d = PyDict::new(py);
    d.set_item("method", c.method)?;
    d.set_item("loose_rpy", c.loose_rpy)?;
    d.set_item("has_identifiers", c.has_identifiers)?;
    d.set_item("reason", c.reason)?;
    Ok(d.unbind())
}

/// Имя файла — исходник игры (`_count_loose_rpy` считает только такие).
#[pyfunction]
fn is_source_rpy_name(name: &str) -> bool {
    ob_renpy::is_source_rpy_name(name)
}

/// Строка кода/настройки (`_line_is_code_position` из `sourcetr.py`).
#[pyfunction]
fn line_is_code_position(line: &str) -> bool {
    ob_renpy::line_is_code_position(line)
}

/// Экранирование в rpy-литерал (`_escape` из `sourcetr.py`).
#[pyfunction]
fn escape(text: &str) -> String {
    ob_renpy::escape(text)
}

#[pymodule]
fn _ob_renpy_py(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(translate_text, m)?)?;
    m.add_function(wrap_pyfunction!(find_literals, m)?)?;
    m.add_function(wrap_pyfunction!(choose_method, m)?)?;
    m.add_function(wrap_pyfunction!(is_source_rpy_name, m)?)?;
    m.add_function(wrap_pyfunction!(line_is_code_position, m)?)?;
    m.add_function(wrap_pyfunction!(escape, m)?)?;
    Ok(())
}
