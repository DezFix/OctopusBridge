//! Вспомогательный дамп каталога `.pck` для конформности с `pck.py`.
//!
//! Печатает заголовок и записи в простом построчном виде — без внешних
//! зависимостей (поэтому не JSON):
//!
//! ```text
//! version=2
//! ver_major=4
//! ...
//! file_count=2
//! entry <path> <ofs> <size> <md5hex> <flags>
//! ```
//!
//! Скрипт `conform.py` рядом сравнивает это с выходом Python-версии
//! один в один. В поставку движка бин не входит — только для проверки.

use std::io::Write;
use std::process::ExitCode;

fn md5hex(md5: &[u8; 16]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(32);
    for b in md5 {
        s.push(HEX[(b >> 4) as usize] as char);
        s.push(HEX[(b & 0xF) as usize] as char);
    }
    s
}

// Табуляция и перевод строки в путях ломают построчный формат — такие
// пакеты дампить отказываемся (встретить их в реальности нельзя: движок
// такие пути не пишет, а битый вход должен быть виден, а не молча склеен).
fn check_path(path: &str) -> Result<(), String> {
    if path.contains(['\t', '\n', '\r']) {
        return Err(format!("недопустимый путь в дампе: {path:?}"));
    }
    Ok(())
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 2 {
        eprintln!("usage: ob_pck_dump <file.pck>");
        return ExitCode::from(2);
    }
    let data = match std::fs::read(&args[1]) {
        Ok(data) => data,
        Err(e) => {
            eprintln!("read: {e}");
            return ExitCode::from(1);
        }
    };
    let header = match ob_pck::parse_header(&data) {
        Ok(header) => header,
        Err(e) => {
            eprintln!("parse_header: {e}");
            return ExitCode::from(1);
        }
    };
    let entries = match ob_pck::read_entries(&data, &header) {
        Ok(entries) => entries,
        Err(e) => {
            eprintln!("read_entries: {e}");
            return ExitCode::from(1);
        }
    };
    let mut out = String::new();
    out.push_str(&format!("version={}\n", header.version));
    out.push_str(&format!("ver_major={}\n", header.ver_major));
    out.push_str(&format!("ver_minor={}\n", header.ver_minor));
    out.push_str(&format!("ver_patch={}\n", header.ver_patch));
    out.push_str(&format!("pack_flags={}\n", header.pack_flags));
    out.push_str(&format!("file_base={}\n", header.file_base));
    out.push_str(&format!(
        "reserved={}\n",
        header
            .reserved
            .iter()
            .map(u32::to_string)
            .collect::<Vec<_>>()
            .join(",")
    ));
    out.push_str(&format!("file_count={}\n", header.file_count));
    out.push_str(&format!("base={}\n", header.base));
    out.push_str(&format!("filesize={}\n", header.filesize));
    out.push_str(&format!(
        "embedded={}\n",
        if header.embedded { 1 } else { 0 }
    ));
    out.push_str(&format!("dir_offset={}\n", header.dir_offset));
    for e in &entries {
        if let Err(msg) = check_path(&e.path) {
            eprintln!("{msg}");
            return ExitCode::from(1);
        }
        out.push_str(&format!(
            "entry\t{}\t{}\t{}\t{}\t{}\n",
            e.path,
            e.ofs,
            e.size,
            md5hex(&e.md5),
            e.flags
        ));
    }
    let stdout = std::io::stdout();
    let mut lock = stdout.lock();
    if lock.write_all(out.as_bytes()).is_err() {
        return ExitCode::from(1);
    }
    ExitCode::SUCCESS
}
