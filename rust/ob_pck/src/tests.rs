//! Тесты чтения `.pck` — только синтетика, игр у нас нет.
//!
//! Синтетический пакет собирается здешним `build_pck` — зеркалом
//! `pack_files` из `pck.py` (та же раскладка: выравнивание на 4,
//! паддинг нулями, `stored = ofs - file_base`). md5 блобов здесь считать
//! нечем и незачем: `read_entries` md5 только переносит, а не проверяет,
//! поэтому пишем детерминированный мусор и сверяем перенос один в один.

use super::*;

fn align_up(v: u64) -> u64 {
    (v + 3) / 4 * 4
}

struct FileSpec {
    path: String,
    blob: Option<Vec<u8>>,
    flags: u32,
}

fn file(path: &str, blob: &[u8]) -> FileSpec {
    FileSpec { path: path.to_string(), blob: Some(blob.to_vec()), flags: 0 }
}

#[allow(clippy::too_many_arguments)]
fn build_pck(
    version: u32,
    ver_major: u32,
    ver_minor: u32,
    ver_patch: u32,
    pack_flags: u32,
    file_base: u64,
    reserved16: Option<[u32; 16]>,
    files: &[FileSpec],
) -> Vec<u8> {
    let dir_offset = if version == FORMAT_VERSION_46 {
        header_size(version)
    } else {
        0
    };
    // v2: каталог сразу за reserved[16] (смещение HEADER_SIZE);
    // v3: каталог по dir_offset (сразу за заголовком).
    let dir_start = if version == FORMAT_VERSION_46 {
        dir_offset + 4
    } else {
        HEADER_SIZE
    };
    let dir_size: u64 =
        files.iter().map(|f| ENTRY_OVERHEAD + f.path.len() as u64).sum();
    let head_end = dir_start + dir_size;
    let mut cursor = align_up(file_base + head_end);
    // (stored_ofs, size, md5, flags, blob|None)
    let mut plan: Vec<(u64, u64, [u8; 16], u32, Option<Vec<u8>>)> = Vec::new();
    for (n, f) in files.iter().enumerate() {
        let mut md5 = [0u8; 16];
        for (i, b) in md5.iter_mut().enumerate() {
            *b = (n as u8).wrapping_add(1).wrapping_add(i as u8);
        }
        match &f.blob {
            None => plan.push((0, 0, [0u8; 16], f.flags | PACK_FILE_REMOVAL, None)),
            Some(blob) => {
                let ofs = cursor;
                cursor = align_up(cursor + blob.len() as u64);
                plan.push((ofs, blob.len() as u64, md5, f.flags, Some(blob.clone())));
            }
        }
    }
    let first_blob = plan.iter().find_map(|(o, _, _, _, b)| {
        b.as_ref().map(|_| *o)
    });

    let mut out = Vec::new();
    out.extend_from_slice(&MAGIC);
    for v in [version, ver_major, ver_minor, ver_patch, pack_flags] {
        out.extend_from_slice(&v.to_le_bytes());
    }
    out.extend_from_slice(&file_base.to_le_bytes());
    if version == FORMAT_VERSION_46 {
        out.extend_from_slice(&dir_offset.to_le_bytes());
    } else {
        let r = reserved16.unwrap_or([0u32; 16]);
        for v in r {
            out.extend_from_slice(&v.to_le_bytes());
        }
    }
    out.extend_from_slice(&(files.len() as u32).to_le_bytes());
    for (spec, (ofs, size, md5, flags, _)) in files.iter().zip(plan.iter()) {
        let raw = spec.path.as_bytes();
        out.extend_from_slice(&(raw.len() as u32).to_le_bytes());
        out.extend_from_slice(raw);
        let stored = if spec.blob.is_none() { 0 } else { ofs - file_base };
        out.extend_from_slice(&stored.to_le_bytes());
        out.extend_from_slice(&size.to_le_bytes());
        out.extend_from_slice(md5);
        out.extend_from_slice(&flags.to_le_bytes());
    }
    if let Some(first) = first_blob {
        out.extend(vec![0u8; (first - head_end) as usize]);
    }
    for (_, _, _, _, blob) in plan.iter() {
        if let Some(blob) = blob {
            let ofs = out.len() as u64;
            out.extend_from_slice(blob);
            let pad = align_up(ofs + blob.len() as u64) - (ofs + blob.len() as u64);
            out.extend(vec![0u8; pad as usize]);
        }
    }
    out
}

fn put_u32(buf: &mut [u8], off: usize, v: u32) {
    buf[off..off + 4].copy_from_slice(&v.to_le_bytes());
}

fn put_u64(buf: &mut [u8], off: usize, v: u64) {
    buf[off..off + 8].copy_from_slice(&v.to_le_bytes());
}

fn std_files() -> Vec<FileSpec> {
    vec![
        file("res://a.txt", b"hello-pck"),
        file("res://data/x.bin", &(0u8..=255u8).collect::<Vec<u8>>()),
    ]
}

// ── v2 ──

#[test]
fn v2_roundtrip() {
    let data = build_pck(2, 4, 2, 1, 0, 4096, Some([7u32; 16]), &std_files());
    assert_eq!(locate(&data), Some((0, false)));
    let h = parse_header(&data).expect("v2 обязан разбираться");
    assert_eq!(h.version, 2);
    assert_eq!((h.ver_major, h.ver_minor, h.ver_patch), (4, 2, 1));
    assert_eq!(h.file_base, 4096);
    assert_eq!(h.reserved, vec![7u32; 16]);
    assert_eq!(h.file_count, 2);
    assert!(!h.embedded && h.base == 0 && h.dir_offset == 0);
    assert_eq!(h.file_base_abs(), 4096);
    assert_eq!(h.count_pos(), HEADER_SIZE - 4);
    assert_eq!(h.dir_start(), HEADER_SIZE);
    let entries = read_entries(&data, &h).expect("каталог v2 обязан читаться");
    assert_eq!(entries.len(), 2);
    assert_eq!(entries[0].path, "res://a.txt");
    assert_eq!(entries[1].path, "res://data/x.bin");
    // ofs абсолютный: file_base уже сложен.
    assert!(entries[0].ofs >= 4096 + HEADER_SIZE);
    assert_eq!(entries[0].size, 9);
    assert_eq!(entries[1].size, 256);
    assert_eq!(entries[0].flags, 0);
    assert!(!entries[0].encrypted() && !entries[0].removal() && !entries[0].delta());
    assert!(entries[0].has_blob());
    assert_eq!(read_blob(&data, &entries[0]).unwrap(), b"hello-pck");
    let bin: Vec<u8> = (0u8..=255u8).collect();
    assert_eq!(read_blob(&data, &entries[1]).unwrap(), bin.as_slice());
    // md5 переносится один в один (сборщик пишет детерминированный мусор:
    // запись n — байты n+1, n+2, ...).
    let expect0: [u8; 16] = core::array::from_fn(|i| 1 + i as u8);
    let expect1: [u8; 16] = core::array::from_fn(|i| 2 + i as u8);
    assert_eq!(entries[0].md5, expect0);
    assert_eq!(entries[1].md5, expect1);
    // Конец каталога — ровно начало паддинга перед первым блобом.
    let limit = catalog_end(&h, &entries);
    assert!(limit <= entries[0].ofs);
}

#[test]
fn v2_rel_filebase_adds_base() {
    // Embedded-пакет: без REL движок блобы не найдёт (fap.cpp:303-305),
    // поэтому такой пакет собирается только с REL — и base складывается.
    let data = build_pck(2, 4, 2, 0, PACK_REL_FILEBASE, 100, None, &std_files());
    let exe_head = b"MZ\x90\x00";
    let mut exe = Vec::new();
    exe.extend_from_slice(exe_head);
    let start = exe.len() as u64;
    exe.extend_from_slice(&data);
    exe.extend_from_slice(&(data.len() as u64).to_le_bytes());
    exe.extend_from_slice(&MAGIC);
    let h = parse_header(&exe).expect("embedded v2 обязан читаться");
    assert_eq!((h.base, h.embedded), (start, true));
    assert_eq!(h.file_base_abs(), 100 + start);
    let entries = read_entries(&exe, &h).unwrap();
    assert_eq!(read_blob(&exe, &entries[0]).unwrap(), b"hello-pck");
}

// ── v3 ──

fn std_v3() -> Vec<u8> {
    build_pck(
        FORMAT_VERSION_46,
        4,
        6,
        2,
        PACK_REL_FILEBASE,
        0,
        None,
        &std_files(),
    )
}

#[test]
fn v3_roundtrip() {
    let data = std_v3();
    assert_eq!(header_size(3), HEADER_SIZE_V3);
    assert_eq!(header_size(2), HEADER_SIZE);
    let h = parse_header(&data).expect("v3 обязан разбираться");
    assert_eq!(h.version, 3);
    assert_eq!((h.ver_major, h.ver_minor, h.ver_patch), (4, 6, 2));
    assert_eq!(h.dir_offset, HEADER_SIZE_V3);
    assert!(h.reserved.is_empty(), "у v3 полей reserved[16] НЕТ вообще");
    assert_eq!(h.file_count, 2);
    assert_eq!(h.count_pos(), HEADER_SIZE_V3);
    assert_eq!(h.dir_start(), HEADER_SIZE_V3 + 4);
    // Главное: file_count лежит ПО dir_offset, а не на месте v2.
    assert_ne!(u32::from_le_bytes(data[96..100].try_into().unwrap()), 2);
    let entries = read_entries(&data, &h).unwrap();
    assert_eq!(entries[0].path, "res://a.txt");
    assert_eq!(read_blob(&data, &entries[0]).unwrap(), b"hello-pck");
    // v3: file_base складывается с base БЕЗУСЛОВНО (здесь base == 0).
    assert_eq!(h.file_base_abs(), h.file_base + h.base);
}

/// Каталог v3 в КОНЦЕ пакета (как настоящая сборка Godot 4.6): блобы идут
/// подряд, каталог — после них. Проверка перекрытия не должна ложно
/// срабатывать, а настоящий наезд — обязан ловиться.
#[test]
fn v3_dir_at_end() {
    let mut data = std_v3();
    let h0 = parse_header(&data).unwrap();
    let e0 = read_entries(&data, &h0).unwrap();
    let dir_size: u64 =
        e0.iter().map(|e| ENTRY_OVERHEAD + e.path.len() as u64).sum();
    let cat_start = HEADER_SIZE_V3 as usize;
    let cat_end = cat_start + 4 + dir_size as usize;
    let catalog = data[cat_start..cat_end].to_vec();
    for b in &mut data[cat_start..cat_end] {
        *b = 0;
    }
    let new_dir = data.len() as u64;
    data.extend_from_slice(&catalog);
    put_u64(&mut data, 32, new_dir);
    let h = parse_header(&data).expect("v3 с каталогом в хвосте обязан читаться");
    assert_eq!(h.dir_offset, new_dir);
    let entries = read_entries(&data, &h).unwrap();
    assert_eq!(
        entries.iter().map(|e| &e.path).collect::<Vec<_>>(),
        e0.iter().map(|e| &e.path).collect::<Vec<_>>(),
    );
    assert_eq!(entries[0].ofs, e0[0].ofs);
    assert_eq!(read_blob(&data, &entries[0]).unwrap(), b"hello-pck");

    // А теперь настоящий наезд: двигаем первый блоб ВНУТРЬ каталога.
    // Правим байты (stored = ofs - file_base): read_entries проверяет
    // смещения из файла, а не из чужой структуры. Каталог уже в хвосте,
    // поэтому позицию первой записи берём из заголовка, а не «44».
    let mut bad = data.clone();
    let tmp = parse_header(&bad).unwrap();
    let ds = tmp.dir_start() as usize;
    let first_len =
        u32::from_le_bytes(bad[ds..ds + 4].try_into().unwrap()) as usize;
    put_u64(
        &mut bad,
        ds + 4 + first_len,
        tmp.dir_start() + 1 - tmp.file_base_abs(),
    );
    let h2 = parse_header(&bad).unwrap();
    let err = read_entries(&bad, &h2).unwrap_err();
    assert!(format!("{err}").contains("перекрывается каталогом"), "{err}");
}

// ── версии и отказы ──

#[test]
fn check_version_matrix() {
    check_version(2, 4, 0).unwrap();
    check_version(2, 4, 6).unwrap();
    check_version(3, 4, 0).unwrap();
    check_version(3, 4, 6).unwrap();
    for (v, maj, min) in
        [(1, 3, 5), (2, 3, 5), (2, 5, 0), (3, 5, 0), (3, 4, 7), (4, 5, 0), (99, 4, 0)]
    {
        let err = check_version(v, maj, min).unwrap_err();
        assert_eq!(err.version(), Some(v as i64), "{v}.{maj}.{min}");
        assert_eq!(err.reason(), "unsupported:version");
        assert!(format!("{err}").contains(&v.to_string()), "{err}");
    }
    assert_eq!(FORMAT_VERSION_3X, 1);
    assert_eq!(FORMAT_VERSION_4X, 2);
    assert_eq!(FORMAT_VERSION_46, 3);
    assert_eq!(SUPPORTED_VERSIONS, (2, 3));
}

#[test]
fn unknown_version_file_refuses_before_body() {
    let data = build_pck(99, 4, 0, 0, 0, 0, None, &std_files());
    let err = parse_header(&data).unwrap_err();
    assert_eq!(err.version(), Some(99));
}

#[test]
fn encrypted_dir_refuses() {
    let data =
        build_pck(2, 4, 2, 0, PACK_DIR_ENCRYPTED, 0, None, &std_files());
    let err = parse_header(&data).unwrap_err();
    assert_eq!(err, PckError::Encrypted("PACK_DIR_ENCRYPTED: каталог зашифрован".into()));
    assert_eq!(err.reason(), "unsupported:encrypted");
}

#[test]
fn sparse_refuses() {
    let data = build_pck(
        FORMAT_VERSION_46,
        4,
        6,
        0,
        PACK_SPARSE_BUNDLE,
        0,
        None,
        &std_files(),
    );
    let err = parse_header(&data).unwrap_err();
    match &err {
        PckError::Unsupported { reason, .. } => {
            assert_eq!(reason, "unsupported:sparse");
        }
        other => panic!("ожидался sparse-отказ, получено {other:?}"),
    }
}

#[test]
fn garbage_has_no_locate() {
    assert_eq!(locate(&vec![b'N'; 500]), None);
    assert_eq!(locate(&[]), None);
    assert_eq!(locate(&vec![0u8; 99]), None);
    let err = parse_header(&vec![b'N'; 500]).unwrap_err();
    assert_eq!(
        err,
        PckError::Error("нет магии GDPC ни в начале, ни в трейлере".into())
    );
}

/// Любое усечение — ошибка, а не паника.
#[test]
fn truncated_inputs_err_without_panic() {
    let full = build_pck(2, 4, 2, 0, 0, 0, None, &std_files());
    // Короче заголовка: даже locate молчит.
    for cut in [0, 1, 3, 4, 23, 24, 31, 32, 39, 40, 60, 96, 99] {
        let data = &full[..cut];
        assert_eq!(locate(data), None, "cut={cut}");
        assert!(parse_header(data).is_err(), "cut={cut}");
    }
    // Заголовок цел (100+ байт), каталог обрезан — честный отказ.
    for cut in [100, 101, 120, 150, 200, full.len() - 1] {
        let data = &full[..cut];
        let h = parse_header(data)
            .unwrap_or_else(|e| panic!("заголовок цел при cut={cut}, а получено {e}"));
        assert!(read_entries(data, &h).is_err(), "cut={cut}");
    }
    let v3 = std_v3();
    let cut = v3.len() - 1;
    let h = parse_header(&v3[..cut]).unwrap();
    assert!(read_entries(&v3[..cut], &h).is_err());

    // dir_offset за пределами файла — тоже отказ, а не паника.
    let mut bad = std_v3();
    put_u64(&mut bad, 32, 1 << 60);
    assert!(parse_header(&bad).is_err());
}

#[test]
fn bad_offsets_refuse() {
    // ofs за пределами файла.
    let mut data = build_pck(2, 4, 2, 0, 0, 0, None, &std_files());
    let first_len = u32::from_le_bytes(data[100..104].try_into().unwrap()) as usize;
    let beyond = data.len() as u64 + 1000;
    put_u64(&mut data, 100 + 4 + first_len, beyond);
    let h = parse_header(&data).unwrap();
    let err = read_entries(&data, &h).unwrap_err();
    assert!(format!("{err}").contains("вне файла"), "{err}");

    // v2: ofs внутри каталога.
    let mut data2 = build_pck(2, 4, 2, 0, 0, 0, None, &std_files());
    put_u64(&mut data2, 100 + 4 + first_len, 50);
    let h2 = parse_header(&data2).unwrap();
    let err2 = read_entries(&data2, &h2).unwrap_err();
    assert!(format!("{err2}").contains("каталог"), "{err2}");

    // Невероятные счётчики.
    let mut data3 = build_pck(2, 4, 2, 0, 0, 0, None, &std_files());
    put_u32(&mut data3, 96, MAX_FILE_COUNT as u32 + 1);
    assert!(parse_header(&data3).is_err());
    let mut data4 = build_pck(2, 4, 2, 0, 0, 0, None, &std_files());
    put_u32(&mut data4, 100, MAX_PATH_LEN as u32 + 1);
    let h4 = parse_header(&data4).unwrap();
    assert!(read_entries(&data4, &h4).is_err());
}

// ── пути и флаги записей ──

#[test]
fn nul_padded_path_trimmed_like_engine() {
    let files = vec![
        file("res://a.txt", b"x"),
        FileSpec {
            path: "res://data/padded.tscn\0\0\0".to_string(),
            blob: Some(b"y".to_vec()),
            flags: 0,
        },
    ];
    let data = build_pck(FORMAT_VERSION_46, 4, 6, 0, 0, 0, None, &files);
    let h = parse_header(&data).unwrap();
    let entries = read_entries(&data, &h).unwrap();
    assert_eq!(entries[1].path, "res://data/padded.tscn");
    assert!(!entries[1].path.contains('\0'));
    assert_eq!(read_blob(&data, &entries[1]).unwrap(), b"y");
}

#[test]
fn non_utf8_path_refuses() {
    let mut data = build_pck(2, 4, 2, 0, 0, 0, None, &std_files());
    // Портим первый байт пути первой записи.
    data[104] = 0xFF;
    let h = parse_header(&data).unwrap();
    let err = read_entries(&data, &h).unwrap_err();
    assert!(format!("{err}").contains("не utf-8"), "{err}");
}

#[test]
fn empty_path_refuses() {
    let mut data = build_pck(2, 4, 2, 0, 0, 0, None, &std_files());
    put_u32(&mut data, 100, 0);
    let h = parse_header(&data).unwrap();
    let err = read_entries(&data, &h).unwrap_err();
    assert!(format!("{err}").contains("пустой"), "{err}");
}

#[test]
fn removal_and_delta_blobs_refuse_with_reason() {
    let files = vec![
        file("res://a.txt", b"data"),
        FileSpec { path: "res://gone.tscn".to_string(), blob: None, flags: 0 },
        FileSpec {
            path: "res://patch.gdc".to_string(),
            blob: Some(b"delta-bytes".to_vec()),
            flags: PACK_FILE_DELTA,
        },
    ];
    let data = build_pck(FORMAT_VERSION_46, 4, 6, 0, 0, 0, None, &files);
    let h = parse_header(&data).unwrap();
    let entries = read_entries(&data, &h).unwrap();
    assert_eq!(entries.len(), 3);
    let gone = &entries[1];
    assert!(gone.removal() && !gone.has_blob());
    assert_eq!(gone.size, 0);
    let err = read_blob(&data, gone).unwrap_err();
    match &err {
        PckError::Unsupported { reason, .. } => {
            assert_eq!(reason, "unsupported:removal");
        }
        other => panic!("{other:?}"),
    }
    let delta = &entries[2];
    assert!(delta.delta() && delta.has_blob());
    let err = read_blob(&data, delta).unwrap_err();
    match &err {
        PckError::Unsupported { reason, .. } => {
            assert_eq!(reason, "unsupported:delta");
        }
        other => panic!("{other:?}"),
    }
    // Обычный блоб рядом читается как ни в чём не бывало.
    assert_eq!(read_blob(&data, &entries[0]).unwrap(), b"data");
}

#[test]
fn encrypted_file_blob_refuses() {
    let files = vec![FileSpec {
        path: "res://a.txt".to_string(),
        blob: Some(b"secret".to_vec()),
        flags: PACK_FILE_ENCRYPTED,
    }];
    let data = build_pck(2, 4, 2, 0, 0, 0, None, &files);
    let h = parse_header(&data).unwrap();
    let entries = read_entries(&data, &h).unwrap();
    assert!(entries[0].encrypted() && !entries[0].has_blob());
    let err = read_blob(&data, &entries[0]).unwrap_err();
    assert!(matches!(err, PckError::Encrypted(_)));
}

#[test]
fn oversized_blob_refuses() {
    let data = build_pck(2, 4, 2, 0, 0, 0, None, &std_files());
    let h = parse_header(&data).unwrap();
    let mut entries = read_entries(&data, &h).unwrap();
    entries[0].size = MAX_BLOB + 1;
    let err = read_blob(&data, &entries[0]).unwrap_err();
    assert!(matches!(err, PckError::Unsupported { .. }));
    // А обрезанный блоб (хвост за EOF, но размер в лимите) — PckError.
    entries[0].size = h.filesize + 1;
    entries[0].ofs = h.filesize.saturating_sub(1);
    let err = read_blob(&data, &entries[0]).unwrap_err();
    assert_eq!(err, PckError::Error("файл обрезан: блоб короче size".into()));
}

// ── embedded ──

#[test]
fn embedded_locate_and_v3_base_math() {
    let mut pck = build_pck(
        FORMAT_VERSION_46,
        4,
        6,
        0,
        PACK_REL_FILEBASE,
        0,
        None,
        &std_files(),
    );
    let exe_head = b"MZ\x90\x00fake-exe";
    let mut exe = Vec::new();
    exe.extend_from_slice(exe_head);
    let start = exe.len() as u64;
    exe.extend_from_slice(&pck);
    exe.extend_from_slice(&(pck.len() as u64).to_le_bytes());
    exe.extend_from_slice(&MAGIC);
    // Трейлер обязан указывать ровно на начало pck — иначе это не наш exe.
    assert_eq!(locate(&exe), Some((start, true)));
    let h = parse_header(&exe).unwrap();
    assert!(h.embedded && h.base == start);
    // fap.cpp:303-305 — при v3 pck_start_pos складывается БЕЗУСЛОВНО.
    assert_eq!(h.file_base_abs(), h.file_base + h.base);
    assert_eq!(h.count_pos(), start + h.dir_offset);
    let entries = read_entries(&exe, &h).unwrap();
    assert_eq!(entries.len(), 2);
    assert_eq!(read_blob(&exe, &entries[0]).unwrap(), b"hello-pck");
    // Битый трейлер (мусор вместо размера) — не наш формат.
    pck[0] = 0;
    let mut bad = Vec::new();
    bad.extend_from_slice(exe_head);
    bad.extend_from_slice(&pck);
    bad.extend_from_slice(&0xFFFFFFFFFFFFFFFFu64.to_le_bytes());
    bad.extend_from_slice(&MAGIC);
    assert_eq!(locate(&bad), None);
}
