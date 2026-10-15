//! Слой 1 — фрейминг `.rpyc`: RPC2-заголовок и zlib-разжатие.
//!
//! Прямой порт фрейминга из `_unpickle_rpyc` (`app/core/renpy/parser.py`):
//! * без магии `RENPY RPC2` — legacy-формат Ren'Py < 7.1: весь файл —
//!   один zlib-поток с pickle внутри;
//! * с магией — записи `(slot, start, length)` по 12 байт с позиции 10:
//!   `slot == 0` — конец, `slot == 1` — zlib-поток по абсолютному смещению.
//!   Первый успешно разжатый слот побеждает, битый — пропускается
//!   (как `except: pass` + продолжение цикла в Python).
//!
//! Отличия только в подаче ошибок: там, где Python бросает исключение
//! наружу (`struct.unpack` на обрезанном заголовке) или возвращает `None`,
//! здесь — `Err` (требование «битый вход: Err, никогда паника»).

use crate::RpycError;
use flate2::Decompress;
use flate2::FlushDecompress;

/// Магия современных `.rpyc` (Ren'Py 7.1+/8.x).
pub const RPC2_MAGIC: &[u8; 10] = b"RENPY RPC2";
/// Длина магии — старт таблицы слотов.
pub const RPC2_HEAD: usize = 10;
/// Размер одной записи таблицы слотов: три u32 LE.
pub const RPC2_RECORD: usize = 12;
/// Предохранитель разжатия: один скрипт больше не бывает, а zlib-бомбу
/// так отсекаем до выделения памяти (inflate идёт чанками с проверкой).
pub const MAX_DECOMPRESSED: u64 = 256 << 20;

/// Разжать один zlib-поток (формат `zlib.compress`, каким Ren'Py пишет
/// `.rpyc`: заголовок 0x78.., данные deflate, трейлер adler32).
fn inflate_zlib(data: &[u8]) -> Result<Vec<u8>, RpycError> {
    let mut dec = Decompress::new(true);
    let mut out = Vec::new();
    // Чанками, чтобы враждебный поток не раздул память одним махом.
    let mut chunk = vec![0u8; 64 * 1024];
    let mut pos = 0usize;
    loop {
        let before_in = dec.total_in();
        let before_out = dec.total_out();
        let status = dec
            .decompress(&data[pos..], &mut chunk, FlushDecompress::Finish)
            .map_err(|e| RpycError::Decode(format!("zlib: {e}")))?;
        pos += (dec.total_in() - before_in) as usize;
        let produced = (dec.total_out() - before_out) as usize;
        if out.len() as u64 + produced as u64 > MAX_DECOMPRESSED {
            return Err(RpycError::TooBig(format!(
                "zlib: выход больше {MAX_DECOMPRESSED} байт"
            )));
        }
        out.extend_from_slice(&chunk[..produced]);
        use flate2::Status;
        match status {
            Status::StreamEnd => break,
            Status::Ok | Status::BufError => {
                // Кончился вход без конца потока — как обрезанный
                // `zlib.decompress` в Python: ошибка, не паника.
                if pos >= data.len() {
                    return Err(RpycError::Decode(
                        "zlib: обрезанный поток".to_string(),
                    ));
                }
            }
        }
    }
    Ok(out)
}

/// Вытащить сжатый pickle-поток из байтов `.rpyc` и разжать.
///
/// Возвращает байты pickle (вход для [`crate::pickle::loads`]).
pub fn unframe(data: &[u8]) -> Result<Vec<u8>, RpycError> {
    // Срез короче магии магией не является — сразу legacy-ветка
    // (в Python `rpyc_data[:10] != b"RENPY RPC2"` тоже верен на коротком).
    if data.len() < RPC2_MAGIC.len() || &data[..RPC2_MAGIC.len()] != RPC2_MAGIC
    {
        return inflate_zlib(data).map_err(|_| {
            RpycError::Decode("не RPC2 и не zlib-поток".to_string())
        });
    }
    let mut pos = RPC2_HEAD;
    loop {
        // Короткий срез `struct.unpack` в Python роняет с исключением —
        // здесь это честный `Err`, а не паника.
        let rec = data.get(pos..pos + RPC2_RECORD).ok_or_else(|| {
            RpycError::Decode("RPC2: обрезанная запись слотов".to_string())
        })?;
        let slot = u32::from_le_bytes([rec[0], rec[1], rec[2], rec[3]]);
        let start = u32::from_le_bytes([rec[4], rec[5], rec[6], rec[7]]);
        let length = u32::from_le_bytes([rec[8], rec[9], rec[10], rec[11]]);
        if slot == 0 {
            break;
        }
        if slot == 1 {
            // Срез за границами в Python молча ужимается (`a[x:y]`
            // никогда не падает) — разжатие ужaтого обычно падает, и цикл
            // идёт дальше. Повторяем в точности: кламп, попытка, пропуск.
            let s = (start as usize).min(data.len());
            let e = s.saturating_add(length as usize).min(data.len());
            if let Ok(payload) = inflate_zlib(&data[s..e]) {
                return Ok(payload);
            }
        }
        pos += RPC2_RECORD;
    }
    Err(RpycError::Decode("RPC2: нет годного слота 1".to_string()))
}
