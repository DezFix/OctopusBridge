//! Чтение `.pck` движка Godot 4 (форматы v2 и v3).
//!
//! Rust-порт чтения из `app/core/godot/pck.py` — эталона, сверенного с
//! `core/io/file_access_pack.cpp` движка. Формат НЕ переизобретается:
//! структура, порядок чтения и все отказы повторяют Python-версию один
//! в один. Запись/пересборка здесь НЕ портирована (отдельный этап).
//!
//! Отличия от Python-версии — только в подаче данных: Python читает из
//! открытого файла (и делает `locate` по имени файла), а здесь все функции
//! работают со срезом байтов `&[u8]`. Так проще тестировать и позже
//! оборачивать в PyO3 без лишнего копирования. Инварианты и тексты отказов
//! — те же, что в `pck.py`.

/// Магия пакета: `'GDPC'`.
pub const MAGIC: [u8; 4] = *b"GDPC";
/// Та же магия как u32 little-endian.
pub const MAGIC_U32: u32 = 0x4350_4447;

/// v2: 4 (magic) + 20 (version..pack_flags) + 8 (file_base) + 16*4
/// (reserved) + 4 (file_count) — до ПЕРВОЙ записи каталога.
pub const HEADER_SIZE: u64 = 100;
/// v3: 4 + 20 + 8 + 8 (dir_offset) — до поля `file_count`, которое лежит
/// по `dir_offset`, а не подряд (fap.cpp:307-319).
pub const HEADER_SIZE_V3: u64 = 40;
/// Размер записи каталога БЕЗ пути и БЕЗ path_len: ofs(8) + size(8) +
/// md5(16) + flags(4).
pub const ENTRY_FIXED: u64 = 36;
/// path_len(4) + путь + ENTRY_FIXED — полный размер записи каталога.
pub const ENTRY_OVERHEAD: u64 = 4 + ENTRY_FIXED;

/// `pack_flags` bit0: каталог зашифрован — ключа у нас нет.
pub const PACK_DIR_ENCRYPTED: u32 = 1 << 0;
/// `pack_flags` bit1: `file_base` относителен начала pck (v2).
pub const PACK_REL_FILEBASE: u32 = 1 << 1;
/// `pack_flags` bit2: блобы лежат ВНЕ пакета — читать нечего.
pub const PACK_SPARSE_BUNDLE: u32 = 1 << 2;
/// Флаг записи bit0: файл зашифрован.
pub const PACK_FILE_ENCRYPTED: u32 = 1 << 0;
/// Флаг записи bit1: файл удалён из пакета (fap.cpp:350-351), блоба нет.
pub const PACK_FILE_REMOVAL: u32 = 1 << 1;
/// Флаг записи bit2: дельта-патч (fap.cpp:353), не самостоятельный файл.
pub const PACK_FILE_DELTA: u32 = 1 << 2;

/// Godot 3.5 — другая раскладка заголовка (88 байт), не умеем.
pub const FORMAT_VERSION_3X: u32 = 1;
/// Godot 4.0-4.3.
pub const FORMAT_VERSION_4X: u32 = 2;
/// Godot 4.5+ (4.6).
pub const FORMAT_VERSION_46: u32 = 3;
/// Раскладки, которые умеем читать. Остальное — честный отказ.
pub const SUPPORTED_VERSIONS: (u32, u32) = (FORMAT_VERSION_4X, FORMAT_VERSION_46);
/// Знаем только раскладку движка 4.x...
pub const SUPPORTED_VER_MAJOR: u32 = 4;
/// ...не новее 4.6: пакет от более нового экспорта не трогаем.
pub const SUPPORTED_VER_MINOR: u32 = 6;

/// Самосохраняющийся трейлер self-contained: uint64 pck_size + 'GDPC'.
pub const TRAILER_SIZE: u64 = 12;

/// Предохранители против битого/чужого файла — чтобы не уйти в ООМ.
pub const MAX_PATH_LEN: u64 = 4096;
pub const MAX_FILE_COUNT: u64 = 1 << 20;
/// 256 МиБ на один файл.
pub const MAX_BLOB: u64 = 256 << 20;

/// Размер фиксированной части заголовка ПО ВЕРСИИ.
///
/// Для v2 это расстояние до первой записи каталога (`file_count` — последнее
/// поле). Для v3 — расстояние до поля `file_count`, которое читается не
/// подряд, а по `dir_offset`.
#[must_use]
pub const fn header_size(version: u32) -> u64 {
    if version == FORMAT_VERSION_46 {
        HEADER_SIZE_V3
    } else {
        HEADER_SIZE
    }
}

/// Ошибка разбора `.pck`. Повторяет иерархию `pck.py`:
/// `PckError` / `PckEncrypted` / `PckUnsupported` (с `reason`) /
/// `PckVersion` (с `version`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PckError {
    /// Файл не является разбираемым `.pck` (`PckError`).
    Error(String),
    /// `PACK_DIR_ENCRYPTED` / `PACK_FILE_ENCRYPTED` — ключа у нас нет.
    Encrypted(String),
    /// Формат разобран, но работать с ним мы не берёмся.
    /// `reason` — машинно-читаемый код для UI и счётчиков `scan()`.
    Unsupported { message: String, reason: String },
    /// Версия/раскладка пакета, которую модуль не умеет.
    /// Вызывающий обязан показать пользователю ЧИСЛО (`version`).
    Version { message: String, version: i64 },
}

impl PckError {
    /// Код причины для `Unsupported` (у остальных — фиксированные строки,
    /// как имена классов в Python-версии).
    #[must_use]
    pub fn reason(&self) -> &str {
        match self {
            PckError::Error(_) => "error:format",
            PckError::Encrypted(_) => "unsupported:encrypted",
            PckError::Unsupported { reason, .. } => reason,
            PckError::Version { .. } => "unsupported:version",
        }
    }

    /// Версия пакета для `Version` (в Python — `exc.version`).
    #[must_use]
    pub const fn version(&self) -> Option<i64> {
        match self {
            PckError::Version { version, .. } => Some(*version),
            _ => None,
        }
    }
}

impl std::fmt::Display for PckError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PckError::Error(m)
            | PckError::Encrypted(m)
            | PckError::Unsupported { message: m, .. }
            | PckError::Version { message: m, .. } => write!(f, "{m}"),
        }
    }
}

impl std::error::Error for PckError {}

/// Запись каталога `.pck`. `ofs` — АБСОЛЮТНЫЙ (`file_base` уже сложен).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PckEntry {
    pub path: String,
    pub ofs: u64,
    pub size: u64,
    pub md5: [u8; 16],
    pub flags: u32,
}

impl PckEntry {
    #[must_use]
    pub const fn encrypted(&self) -> bool {
        self.flags & PACK_FILE_ENCRYPTED != 0
    }
    /// `PACK_FILE_REMOVAL`: файл удалён, блоба за записью НЕТ.
    #[must_use]
    pub const fn removal(&self) -> bool {
        self.flags & PACK_FILE_REMOVAL != 0
    }
    /// `PACK_FILE_DELTA`: блоб — патч поверх другого файла, не сам файл.
    #[must_use]
    pub const fn delta(&self) -> bool {
        self.flags & PACK_FILE_DELTA != 0
    }
    /// Есть ли у записи вообще блоб, который можно прочитать.
    #[must_use]
    pub const fn has_blob(&self) -> bool {
        self.flags & (PACK_FILE_REMOVAL | PACK_FILE_ENCRYPTED) == 0
    }
}

/// Заголовок `.pck`. Все поля сохраняются дословно (нужны пересборке —
/// она портируется отдельным этапом, поэтому поля уже здесь).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PckHeader {
    pub version: u32,
    pub ver_major: u32,
    pub ver_minor: u32,
    pub ver_patch: u32,
    pub pack_flags: u32,
    pub file_base: u64,
    /// v2: 16 значений; v3: полей нет вообще — пустой список, а не нули.
    pub reserved: Vec<u32>,
    pub file_count: u32,
    /// Смещение начала pck внутри файла-контейнера.
    pub base: u64,
    /// Размер файла-контейнера.
    pub filesize: u64,
    /// pck приклеен к `.exe`.
    pub embedded: bool,
    /// v3: смещение каталога ОТ НАЧАЛА pck (fap.cpp:309).
    pub dir_offset: u64,
}

impl PckHeader {
    /// `file_base` в том виде, в каком его считает движок.
    ///
    /// fap.cpp:303-305: `pck_start_pos` (у нас `base`) прибавляется при v3
    /// БЕЗУСЛОВНО, при v2 — только с `PACK_REL_FILEBASE`. Схлопывать это в
    /// `file_base` нельзя: пакет по смещению читался бы с битых адресов.
    #[must_use]
    pub const fn file_base_abs(&self) -> u64 {
        if self.version == FORMAT_VERSION_46
            || (self.pack_flags & PACK_REL_FILEBASE) != 0
        {
            // Переполнение здесь невозможно: оба слагаемых — смещения
            // внутри реального файла, их сумма заведомо влазит в u64.
            // (Хоть `const fn` и не даёт checked_add с ветвлением под
            // старым MSRV — считаем напрямую, как и Python.)
            self.file_base + self.base
        } else {
            self.file_base
        }
    }

    #[must_use]
    pub const fn sparse(&self) -> bool {
        self.pack_flags & PACK_SPARSE_BUNDLE != 0
    }

    /// Абсолютное смещение поля `file_count`.
    ///
    /// v2 — сразу за `reserved[16]`; v3 — по `dir_offset + pck_start_pos`
    /// (fap.cpp:307-319). Смешивать эти два места нельзя.
    #[must_use]
    pub const fn count_pos(&self) -> u64 {
        if self.version == FORMAT_VERSION_46 {
            self.base + self.dir_offset
        } else {
            self.base + HEADER_SIZE - 4
        }
    }

    /// Смещение ПЕРВОЙ записи каталога (сразу за file_count).
    ///
    /// Конца каталога это НЕ даёт: он зависит от суммы длин путей и
    /// известен только после чтения всех записей (см. [`catalog_end`]).
    #[must_use]
    pub const fn dir_start(&self) -> u64 {
        // Переполнение невозможно по той же причине, что в file_base_abs:
        // оба слагаемых ограничены размером реального файла.
        if self.version == FORMAT_VERSION_46 {
            self.base + self.dir_offset + 4
        } else {
            self.base + HEADER_SIZE
        }
    }
}

/// Абсолютное смещение сразу ЗА каталогом — блобы лежат дальше.
#[must_use]
pub fn catalog_end(header: &PckHeader, entries: &[PckEntry]) -> u64 {
    // Сумма ограничена MAX_FILE_COUNT * (ENTRY_OVERHEAD + MAX_PATH_LEN)
    // (~4 ГиБ) — переполнение u64 невозможно, считаем напрямую.
    header.dir_start()
        + entries
            .iter()
            .map(|e| ENTRY_OVERHEAD + e.path.len() as u64)
            .sum::<u64>()
}

// ── разбор ──

fn read_u32_le(data: &[u8], pos: u64, what: &str) -> Result<u32, PckError> {
    let pos = pos as usize;
    let chunk = data.get(pos..pos + 4).ok_or_else(|| {
        PckError::Error(format!("обрезан {what}"))
    })?;
    Ok(u32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
}

fn read_u64_le(data: &[u8], pos: u64, what: &str) -> Result<u64, PckError> {
    let pos = pos as usize;
    let chunk = data.get(pos..pos + 8).ok_or_else(|| {
        PckError::Error(format!("обрезан {what}"))
    })?;
    Ok(u64::from_le_bytes([
        chunk[0], chunk[1], chunk[2], chunk[3], chunk[4], chunk[5], chunk[6],
        chunk[7],
    ]))
}

/// Шаг позиции каталога: конец текущей записи. Сумма шагов ограничена
/// `MAX_FILE_COUNT * (ENTRY_OVERHEAD + MAX_PATH_LEN)`, так что переполнение
/// здесь — признак битого входа, а не арифметики: честный отказ.
fn advance(tail_end: u128, i: u32) -> Result<u64, PckError> {
    u64::try_from(tail_end).map_err(|_| {
        PckError::Error(format!("обрезан каталог на записи {i}"))
    })
}

/// Найти начало pck: `(смещение, embedded)` либо `None`.
///
/// Порядок как в движке (fap.cpp:223-286): сначала магия по смещению 0,
/// затем трейлер в конце файла для self-contained exe.
#[must_use]
pub fn locate(data: &[u8]) -> Option<(u64, bool)> {
    let size = data.len() as u64;
    if size < HEADER_SIZE {
        return None;
    }
    if data.get(0..4) == Some(&MAGIC[..]) {
        return Some((0, false));
    }
    if size < TRAILER_SIZE {
        return None;
    }
    // Трейлер: uint64 pck_size + 'GDPC'. Магию трейлера, как и Python,
    // не проверяем — достаточно того, что по вычисленному смещению
    // стоит магия пакета.
    let raw = data.get(size as usize - TRAILER_SIZE as usize..size as usize - 4)?;
    let pck_size = u64::from_le_bytes([
        raw[0], raw[1], raw[2], raw[3], raw[4], raw[5], raw[6], raw[7],
    ]);
    let start = (size - TRAILER_SIZE).checked_sub(pck_size)?;
    if start < size - TRAILER_SIZE
        && data.get(start as usize..start as usize + 4) == Some(&MAGIC[..])
    {
        return Some((start, true));
    }
    None
}

/// Отказ на версии, раскладку которой мы не знаем.
///
/// Движок проверяет ровно то же (fap.cpp:294-295). У Godot 3.x (`version`
/// 1) НЕТ ни `pack_flags`, ни `file_base` (заголовок 88 байт), и читать
/// такой пакет нашей раскладкой — значит читать мусор.
pub fn check_version(
    version: u32,
    ver_major: u32,
    ver_minor: u32,
) -> Result<(), PckError> {
    if version == FORMAT_VERSION_3X {
        return Err(PckError::Version {
            message: format!(
                "unsupported:version {version} (движок {ver_major}.{ver_minor}): \
                 Godot 3.x — заголовок 88 байт, другая раскладка; модуль умеет \
                 только version {} и {}",
                SUPPORTED_VERSIONS.0, SUPPORTED_VERSIONS.1,
            ),
            version: version as i64,
        });
    }
    if version != SUPPORTED_VERSIONS.0 && version != SUPPORTED_VERSIONS.1 {
        return Err(PckError::Version {
            message: format!(
                "unsupported:version {version} (движок {ver_major}.{ver_minor}): \
                 модуль умеет version {} и {}",
                SUPPORTED_VERSIONS.0, SUPPORTED_VERSIONS.1,
            ),
            version: version as i64,
        });
    }
    if ver_major != SUPPORTED_VER_MAJOR {
        return Err(PckError::Version {
            message: format!(
                "unsupported:version {version} (движок {ver_major}.{ver_minor}): \
                 модуль знает только раскладку движка {SUPPORTED_VER_MAJOR}.x",
            ),
            version: version as i64,
        });
    }
    if ver_minor > SUPPORTED_VER_MINOR {
        return Err(PckError::Version {
            message: format!(
                "unsupported:version {version} (движок {ver_major}.{ver_minor}): \
                 пакет собран движком новее известного \
                 {SUPPORTED_VER_MAJOR}.{SUPPORTED_VER_MINOR}",
            ),
            version: version as i64,
        });
    }
    Ok(())
}

/// Разобрать заголовок из байтов пакета.
pub fn parse_header(data: &[u8]) -> Result<PckHeader, PckError> {
    let filesize = data.len() as u64;
    let Some((base, embedded)) = locate(data) else {
        return Err(PckError::Error(
            "нет магии GDPC ни в начале, ни в трейлере".to_string(),
        ));
    };
    if data.get(base as usize..base as usize + 4) != Some(&MAGIC[..]) {
        return Err(PckError::Error("магия GDPC не читается".to_string()));
    }
    let fixed = data
        .get(base as usize + 4..base as usize + 24)
        .ok_or_else(|| PckError::Error("обрезан заголовок".to_string()))?;
    let version = u32::from_le_bytes([fixed[0], fixed[1], fixed[2], fixed[3]]);
    let ver_major =
        u32::from_le_bytes([fixed[4], fixed[5], fixed[6], fixed[7]]);
    let ver_minor =
        u32::from_le_bytes([fixed[8], fixed[9], fixed[10], fixed[11]]);
    let ver_patch =
        u32::from_le_bytes([fixed[12], fixed[13], fixed[14], fixed[15]]);
    let pack_flags =
        u32::from_le_bytes([fixed[16], fixed[17], fixed[18], fixed[19]]);
    // Версию проверяем ДО чтения остатка заголовка: у v1 и у неизвестных
    // значений раскладка ДРУГАЯ, и дочитывать её нашими полями — значит
    // читать мусор. Движок отказывает на том же месте (fap.cpp:294).
    check_version(version, ver_major, ver_minor)?;
    let file_base = read_u64_le(data, base + 24, "file_base")?;
    let mut reserved: Vec<u32> = Vec::new();
    let mut dir_offset: u64 = 0;
    if version == FORMAT_VERSION_46 {
        // v3: reserved[16] НЕТ — вместо них смещение каталога (fap.cpp:309).
        dir_offset = read_u64_le(data, base + 32, "dir_offset")?;
        // Сумму считаем через u128: на битом входе вместо паники —
        // честный отказ «вне файла».
        if dir_offset < HEADER_SIZE_V3
            || base as u128 + dir_offset as u128 >= filesize as u128
        {
            return Err(PckError::Error(format!(
                "dir_offset={dir_offset} вне файла"
            )));
        }
    } else {
        for n in 0..16 {
            let pos = base + 32 + n * 4;
            reserved.push(read_u32_le(data, pos, "reserved[16]")?);
        }
    }
    let mut header = PckHeader {
        version,
        ver_major,
        ver_minor,
        ver_patch,
        pack_flags,
        file_base,
        reserved,
        file_count: 0,
        base,
        filesize,
        embedded,
        dir_offset,
    };
    if pack_flags & PACK_DIR_ENCRYPTED != 0 {
        return Err(PckError::Encrypted(
            "PACK_DIR_ENCRYPTED: каталог зашифрован".to_string(),
        ));
    }
    if header.sparse() {
        // Блобы лежат вне пакета (fap.cpp:513-517) — пакет не трогаем целиком.
        return Err(PckError::Unsupported {
            message: "PACK_SPARSE_BUNDLE: содержимое пакета лежит вне .pck"
                .to_string(),
            reason: "unsupported:sparse".to_string(),
        });
    }
    // v3: file_count читается ПОСЛЕ seek(dir_offset + pck_start_pos), а не
    // по текущей позиции (fap.cpp:307-319).
    let count_pos = header.count_pos();
    let file_count_64 = {
        let pos = usize::try_from(count_pos)
            .ok()
            .and_then(|p| data.get(p..p + 4))
            .ok_or_else(|| PckError::Error("обрезан file_count".to_string()))?;
        u32::from_le_bytes([pos[0], pos[1], pos[2], pos[3]]) as u64
    };
    if file_count_64 > MAX_FILE_COUNT {
        return Err(PckError::Error(format!(
            "невероятный file_count={file_count_64}"
        )));
    }
    header.file_count = file_count_64 as u32;
    Ok(header)
}

/// Каталог `.pck`. Проверяет инвариант смещений (см. модульный docstring
/// Python-версии: абсолютный `ofs` каждой записи указывает внутрь файла и
/// не НАКРЫВАЕТ каталог).
pub fn read_entries(
    data: &[u8],
    header: &PckHeader,
) -> Result<Vec<PckEntry>, PckError> {
    let mut entries: Vec<PckEntry> = Vec::new();
    let mut pos = header.dir_start();
    for i in 0..header.file_count {
        let path_len = read_u32_le(data, pos, &format!("каталог на записи {i}"))
            .map_err(|_| {
                PckError::Error(format!("обрезан каталог на записи {i}"))
            })? as u64;
        if path_len > MAX_PATH_LEN {
            return Err(PckError::Error(format!(
                "невероятный path_len={path_len} (запись {i})"
            )));
        }
        // Позицию двигаем через u128, чтобы битый вход давал отказ,
        // а не панику на переполнении.
        let path_start = pos as u128 + 4;
        let path_end = path_start + path_len as u128;
        let tail_start = path_end;
        let tail_end = tail_start + ENTRY_FIXED as u128;
        let raw = usize::try_from(path_start)
            .ok()
            .and_then(|s| usize::try_from(path_end).ok().map(|e| (s, e)))
            .and_then(|(s, e)| data.get(s..e))
            .ok_or_else(|| {
                PckError::Error(format!("обрезан путь записи {i}"))
            })?;
        let tail = usize::try_from(tail_start)
            .ok()
            .and_then(|s| usize::try_from(tail_end).ok().map(|e| (s, e)))
            .and_then(|(s, e)| data.get(s..e))
            .ok_or_else(|| {
                PckError::Error(format!("обрезана запись {i}"))
            })?;
        let rel_ofs = u64::from_le_bytes([
            tail[0], tail[1], tail[2], tail[3], tail[4], tail[5], tail[6],
            tail[7],
        ]);
        let size = u64::from_le_bytes([
            tail[8], tail[9], tail[10], tail[11], tail[12], tail[13], tail[14],
            tail[15],
        ]);
        let mut md5 = [0u8; 16];
        md5.copy_from_slice(&tail[16..32]);
        let flags = u32::from_le_bytes([tail[32], tail[33], tail[34], tail[35]]);
        // Записи пишутся с выравниванием длины NUL-байтами. Движок обрезает
        // путь по первому NUL (String::append_utf8, ustring.cpp) — и мы тоже.
        let cut = raw.iter().position(|&b| b == 0).unwrap_or(raw.len());
        let p = std::str::from_utf8(&raw[..cut])
            .map_err(|_| {
                PckError::Error(format!("путь записи {i} не utf-8"))
            })?
            .to_string();
        if p.is_empty() {
            return Err(PckError::Error(format!("путь записи {i} пустой")));
        }
        let ofs128 = header.file_base_abs() as u128 + rel_ofs as u128;
        let ofs = u64::try_from(ofs128).map_err(|_| {
            PckError::Error(format!(
                "смещение записи {i} вне файла (ofs={}, size={size}, \
                 filesize={})",
                u128::from(u64::MAX).max(ofs128),
                header.filesize,
            ))
        })?;
        let entry = PckEntry { path: p, ofs, size, md5, flags };
        // У PACK_FILE_REMOVAL блоба нет вовсе (fap.cpp:350-351): движок её
        // даже не открывает, а ofs/size в записи служебные.
        if entry.removal() {
            entries.push(entry);
            pos = advance(tail_end, i)?;
            continue;
        }
        if ofs128 + size as u128 > header.filesize as u128 {
            return Err(PckError::Error(format!(
                "смещение записи {i} вне файла (ofs={ofs}, size={size}, \
                 filesize={})",
                header.filesize,
            )));
        }
        entries.push(entry);
        pos = advance(tail_end, i)?;
    }
    // Блоб не может НАКРЫВАТЬ каталог — конец каталога известен только
    // сейчас, когда прочитан весь.
    let limit = catalog_end(header, &entries);
    for (i, e) in entries.iter().enumerate() {
        if e.removal() {
            continue;
        }
        if header.version == FORMAT_VERSION_46 {
            // v3: каталог адресуется через dir_offset и в реальных сборках
            // лежит В КОНЦЕ пакета, после всех блобов. Проверяем ровно то,
            // что запрещено: перекрытие.
            if (e.ofs as u128) < limit as u128
                && e.ofs as u128 + e.size as u128 > header.dir_start() as u128
            {
                return Err(PckError::Error(format!(
                    "блоб записи {i} перекрывается каталогом \
                     (ofs={}, size={}, каталог={}..{limit})",
                    e.ofs,
                    e.size,
                    header.dir_start(),
                )));
            }
        } else if (e.ofs as u128) < limit as u128 {
            // v2: каталог по построению идёт перед блобами.
            return Err(PckError::Error(format!(
                "смещение записи {i} попадает в каталог \
                 (ofs={}, конец каталога={limit})",
                e.ofs,
            )));
        }
    }
    Ok(entries)
}

/// Блоб одного файла из `.pck` (с проверкой, что он вообще влезает).
pub fn read_blob<'a>(
    data: &'a [u8],
    entry: &PckEntry,
) -> Result<&'a [u8], PckError> {
    if entry.encrypted() {
        return Err(PckError::Encrypted(
            "PACK_FILE_ENCRYPTED: файл зашифрован".to_string(),
        ));
    }
    if entry.removal() {
        return Err(PckError::Unsupported {
            message: "PACK_FILE_REMOVAL: файл удалён, блоба нет".to_string(),
            reason: "unsupported:removal".to_string(),
        });
    }
    if entry.delta() {
        // Блоб-патч читается не как файл, а через FileAccessPatched
        // (fap.cpp:363-371): отдавать его переводчику нельзя.
        return Err(PckError::Unsupported {
            message: "PACK_FILE_DELTA: блоб — патч, не файл".to_string(),
            reason: "unsupported:delta".to_string(),
        });
    }
    if entry.size > MAX_BLOB {
        return Err(PckError::Unsupported {
            message: format!("файл крупнее {MAX_BLOB} байт"),
            reason: "unsupported:format".to_string(),
        });
    }
    let start = entry.ofs as usize;
    let end = (entry.ofs as u128 + entry.size as u128) as usize;
    data.get(start..end).ok_or_else(|| {
        PckError::Error("файл обрезан: блоб короче size".to_string())
    })
}

#[cfg(test)]
mod tests;
