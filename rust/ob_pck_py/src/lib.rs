//! PyO3-обёртка чтения `.pck`: `parse_pck` как обычная Python-функция.
//!
//! Принимает байты пакета, возвращает `(header_dict, [entry_dict, ...])`
//! с теми же полями, что `PckHeader`/`PckEntry` в `ob_pck` (и те же имена,
//! что атрибуты `pck.py`). Ошибки `ob_pck::PckError` превращаются в
//! `ValueError` с тем же текстом — Python-сторона видит те же отказы.
//!
//! Запись/пересборка не оборачиваются: в этом этапе портировано только
//! чтение, и обёртка покрывает ровно его.

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};

fn err_to_py(e: ob_pck::PckError) -> PyErr {
    pyo3::exceptions::PyValueError::new_err(e.to_string())
}

fn header_to_dict<'py>(
    py: Python<'py>,
    h: &ob_pck::PckHeader,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("version", h.version)?;
    d.set_item("ver_major", h.ver_major)?;
    d.set_item("ver_minor", h.ver_minor)?;
    d.set_item("ver_patch", h.ver_patch)?;
    d.set_item("pack_flags", h.pack_flags)?;
    d.set_item("file_base", h.file_base)?;
    d.set_item("reserved", h.reserved.clone())?;
    d.set_item("file_count", h.file_count)?;
    d.set_item("base", h.base)?;
    d.set_item("filesize", h.filesize)?;
    d.set_item("embedded", h.embedded)?;
    d.set_item("dir_offset", h.dir_offset)?;
    Ok(d)
}

fn entry_to_dict<'py>(
    py: Python<'py>,
    e: &ob_pck::PckEntry,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("path", &e.path)?;
    d.set_item("ofs", e.ofs)?;
    d.set_item("size", e.size)?;
    d.set_item("md5", PyBytes::new(py, &e.md5))?;
    d.set_item("flags", e.flags)?;
    Ok(d)
}

/// Разобрать байты `.pck`: `(header, entries)`.
///
/// Эквивалент связки `pck.read_header` + `pck.read_entries` (Python-версия
/// читает с диска, а сюда байты передаёт вызывающий — так обёртка годится
/// и для пакета, уже лежащего в памяти).
#[pyfunction]
fn parse_pck(py: Python<'_>, data: &[u8]) -> PyResult<(Py<PyDict>, Py<PyList>)> {
    let header = ob_pck::parse_header(data).map_err(err_to_py)?;
    let entries = ob_pck::read_entries(data, &header).map_err(err_to_py)?;
    let h = header_to_dict(py, &header)?;
    let list = PyList::empty(py);
    for e in &entries {
        list.append(entry_to_dict(py, e)?)?;
    }
    Ok((h.unbind(), list.unbind()))
}

/// Прочитать блоб записи по её `ofs`/`size`/`flags` (эквивалент
/// `pck.read_blob`: те же отказы на шифрованных/удалённых/дельта-записях).
#[pyfunction]
#[pyo3(signature = (data, ofs, size, flags = 0))]
fn read_blob(
    py: Python<'_>,
    data: &[u8],
    ofs: u64,
    size: u64,
    flags: u32,
) -> PyResult<Py<PyBytes>> {
    let entry = ob_pck::PckEntry {
        path: String::new(),
        ofs,
        size,
        md5: [0u8; 16],
        flags,
    };
    let blob = ob_pck::read_blob(data, &entry).map_err(err_to_py)?;
    Ok(PyBytes::new(py, blob).unbind())
}

#[pymodule]
fn _ob_pck_py(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse_pck, m)?)?;
    m.add_function(wrap_pyfunction!(read_blob, m)?)?;
    Ok(())
}
