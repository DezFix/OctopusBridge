//! Тесты слоёв `ob_renpy_rpyc` — только синтетика, игр у нас нет.
//!
//! Каждый слой — свои тесты (фрейминг, pickle-VM, текст, мини-парсер),
//! сквозные сверки с Python — в `conform.py` (там же генератор AST,
//! фаззер мутаций и hostile-входы).

use super::*;
use crate::framing;
use crate::pickle;
use crate::pyparse;
use crate::text;

// ── слой 1: фрейминг ──

fn compress(data: &[u8]) -> Vec<u8> {
    // zlib-поток как `zlib.compress` (уровень 3 — как у Ren'Py).
    use flate2::Compression;
    use flate2::write::ZlibEncoder;
    use std::io::Write;
    let mut enc = ZlibEncoder::new(Vec::new(), Compression::new(3));
    enc.write_all(data).unwrap();
    enc.finish().unwrap()
}

fn rpc2(payload: &[u8]) -> Vec<u8> {
    let data = compress(payload);
    let mut out = b"RENPY RPC2".to_vec();
    out.extend_from_slice(&[0u8; 36]);
    let start = out.len() as u32;
    out.extend_from_slice(&data);
    let rec = [
        1u32.to_le_bytes(),
        start.to_le_bytes(),
        (data.len() as u32).to_le_bytes(),
    ]
    .concat();
    out[10..22].copy_from_slice(&rec);
    out
}

#[test]
fn framing_legacy_ok() {
    let payload = b"\x80\x02N.";
    let got = framing::unframe(&compress(payload)).unwrap();
    assert_eq!(got, payload);
}

#[test]
fn framing_rpc2_ok() {
    let payload = b"\x80\x02N.";
    let got = framing::unframe(&rpc2(payload)).unwrap();
    assert_eq!(got, payload);
}

#[test]
fn framing_second_slot_wins() {
    // Битый первый слот пропускается, годный второй — берётся
    // (как `except: pass` + продолжение цикла в Python).
    let payload = b"\x80\x02N.";
    let good = compress(payload);
    let mut out = b"RENPY RPC2".to_vec();
    out.extend_from_slice(&[0u8; 24]);
    let bad_pos = out.len();
    out.extend_from_slice(b"zzzzz");
    let good_pos = out.len();
    out.extend_from_slice(&good);
    let mut rec = |slot: u32, start: usize, len: usize, at: usize| {
        let r = [
            slot.to_le_bytes(),
            (start as u32).to_le_bytes(),
            (len as u32).to_le_bytes(),
        ]
        .concat();
        out[at..at + 12].copy_from_slice(&r);
    };
    rec(1, bad_pos, 5, 10);
    rec(1, good_pos, good.len(), 22);
    let got = framing::unframe(&out).unwrap();
    assert_eq!(got, payload);
}

#[test]
fn framing_rejects() {
    // Пусто, мусор, обрезанный заголовок, нулевой слот, OOB-слот.
    assert!(framing::unframe(b"").is_err());
    assert!(framing::unframe(b"not compressed at all").is_err());
    assert!(framing::unframe(b"RENPY RPC2").is_err());
    assert!(framing::unframe(b"RENPY RPC2\x00\x00\x00\x00\x00").is_err());
    let empty_slots = [b"RENPY RPC2".as_slice(), &[0u8; 12]].concat();
    assert!(framing::unframe(&empty_slots).is_err());
    // Слот за границами — пропуск, затем конец (slot 0) — отказ без паники.
    let mut oob = b"RENPY RPC2".to_vec();
    oob.extend_from_slice(&1u32.to_le_bytes());
    oob.extend_from_slice(&9999u32.to_le_bytes());
    oob.extend_from_slice(&9999u32.to_le_bytes());
    oob.extend_from_slice(&[0u8; 12]);
    assert!(framing::unframe(&oob).is_err());
}

// ── слой 2: pickle-VM ──

fn loads(data: &[u8]) -> pickle::Value {
    pickle::loads(data).expect("валидный pickle обязан разбираться")
}

fn loads_err(data: &[u8]) -> RpycError {
    pickle::loads(data).expect_err("битый pickle обязан давать Err")
}

fn str_of(v: &pickle::Value, r: pickle::Ref) -> Option<String> {
    match v.store.nodes.get(r) {
        Some(pickle::Node::Str(s)) | Some(pickle::Node::PyStr(s)) => {
            Some(s.clone())
        }
        _ => None,
    }
}

#[test]
fn pickle_scalars() {
    // INT: True/False, hex, legacy-octal, decimal с пробелами.
    assert_eq!(
        loads(b"I01\n.").store.nodes[loads(b"I01\n.").root],
        pickle::Node::Bool(true)
    );
    let v = loads(b"I00\n.");
    assert!(matches!(
        v.store.nodes[v.root],
        pickle::Node::Bool(false)
    ));
    let v = loads(b"I010\n.");
    assert!(matches!(
        v.store.nodes[v.root],
        pickle::Node::Int(pickle::IntVal::Small(8))
    ));
    // LONG с суффиксом и без, legacy-octal запрещён.
    let v = loads(b"L123L\n.");
    assert!(matches!(
        v.store.nodes[v.root],
        pickle::Node::Int(pickle::IntVal::Small(123))
    ));
    assert!(loads_err(b"L010\n.").to_string().contains("pickle"));
    // FLOAT.
    let v = loads(b"F2.5\n.");
    assert!(matches!(
        v.store.nodes[v.root],
        pickle::Node::Float(f) if f == 2.5
    ));
    assert!(loads_err(b"F1_0\n.").to_string().contains("pickle"));
    // BININT-семейство, BINFLOAT.
    let v = loads(b"J\xfb\xff\xff\xff.");
    assert!(matches!(
        v.store.nodes[v.root],
        pickle::Node::Int(pickle::IntVal::Small(-5))
    ));
    // NONE/NEWTRUE/NEWFALSE.
    assert!(matches!(
        loads(b"N.").store.nodes[0],
        pickle::Node::None
    ));
}

#[test]
fn pickle_strings() {
    // BINUNICODE с кириллицей.
    let v = loads("X\x0c\x00\x00\x00Привет.".as_bytes());
    assert_eq!(str_of(&v, v.root).as_deref(), Some("Привет"));
    // UNICODE raw-escape: только \u/\U.
    let v = loads(b"V\\u00e9t\\n\n.");
    assert_eq!(str_of(&v, v.root).as_deref(), Some("ét\\n"));
    // Сырой байт ≥ 0x80 — как latin-1 (как CPython).
    let raw = [b'V', 0xe9, b'\n', b'.'];
    let v = loads(&raw);
    assert_eq!(str_of(&v, v.root).as_deref(), Some("é"));
    // STRING с escape'ами.
    let v = loads(b"S'a\\x41\\101\\n'\n.");
    assert_eq!(str_of(&v, v.root).as_deref(), Some("aAA\n"));
    // Короткий \x — ошибка всего unpickle (как ValueError в Python).
    loads_err(b"S'a\\x4'.");
    // Не-ASCII в STRING/BINSTRING — ошибка.
    loads_err(b"S'\xe9'\n.");
    loads_err(b"T\x01\x00\x00\x00\xe9.");
    // BINSTRING — str (ASCII).
    let v = loads(b"T\x03\x00\x00\x00abc.");
    assert_eq!(str_of(&v, v.root).as_deref(), Some("abc"));
    // BINBYTES — bytes.
    assert!(matches!(
        loads(b"B\x02\x00\x00\x00hi.").store.nodes[0],
        pickle::Node::Bytes(_)
    ));
}

#[test]
fn pickle_containers_memo() {
    // [1, "a"] через MARK/APPENDS.
    let raw = b"\x80\x02]q\x00(K\x01X\x01\x00\x00\x00aq\x01e.";
    let v = loads(raw);
    match &v.store.nodes[v.root] {
        pickle::Node::List(items) => assert_eq!(items.len(), 2),
        _ => panic!("ожидался список"),
    }
    // APPEND одиночный: [1] (алиасинг — ниже, через цикл).
    let raw = b"\x80\x02]K\x01a.";
    let v = loads(raw);
    match &v.store.nodes[v.root] {
        pickle::Node::List(items) => assert_eq!(items.len(), 1),
        _ => panic!("ожидался список"),
    }
    // Цикл через мемои: l.append(l) — unpickle обязан завершиться.
    let raw = b"\x80\x02]q\x00h\x00a.";
    let v = loads(raw);
    match &v.store.nodes[v.root] {
        pickle::Node::List(items) => assert_eq!(items, &[v.root]),
        _ => panic!("ожидался цикл"),
    }
    // rozsyp без метки — отказ.
    loads_err(b"\x80\x02K\x01e.");
    loads_err(b"\x80\x02K\x01u.");
    loads_err(b"\x80\x02K\x01d.");
}

#[test]
fn pickle_global_whitelist() {
    // renpy.* — mock, copyreg — настоящий, чужое — отказ.
    let say = loads(b"crenpy.ast\nSay\n.");
    match &say.store.nodes[say.root] {
        pickle::Node::Class(i) => {
            assert_eq!(say.store.classes[*i].type_name, "Say");
        }
        _ => panic!("ожидался класс"),
    }
    let m = loads(b"crenpy.foo\nBar\n.");
    match &m.store.nodes[m.root] {
        pickle::Node::Class(i) => {
            assert_eq!(m.store.classes[*i].type_name, "_mock_Bar");
        }
        _ => panic!("ожидался mock"),
    }
    loads(&b"ccopyreg\n__newobj__\n.".to_vec());
    loads(&b"cbuiltins\nlist\n.".to_vec());
    let e = loads_err(b"cos\nsystem\n.");
    assert!(matches!(e, RpycError::Unsafe(_)));
    let e = loads_err(b"cbuiltins\neval\n.");
    assert!(matches!(e, RpycError::Unsafe(_)));
    // _codecs.encode — исключение (его испускает сам pickler для bytes).
    loads(&b"c_codecs\nencode\n.".to_vec());
    // STACK_GLOBAL требует ровно str (NONE — отказ).
    loads(b"X\x09\x00\x00\x00renpy.astX\x03\x00\x00\x00Say\x93.");
    loads_err(b"X\x09\x00\x00\x00renpy.astN\x93.");
}

#[test]
fn pickle_py2_names_like_eternal() {
    // py2-имена — ровно как `find_class` эталона на py3 (проверено зондом):
    // copy_reg.* — mock (иначе proto-0/1 графы из настоящего pickler
    // сыпались бы в отказ, а Python их разбирает).
    let v = loads(b"ccopy_reg\n_reconstructor\n.");
    match &v.store.nodes[v.root] {
        pickle::Node::Class(i) => {
            assert_eq!(
                v.store.classes[*i].type_name,
                "_mock_ext_copy_reg__reconstructor"
            );
        }
        _ => panic!("ожидался mock-класс"),
    }
    // __builtin__.<safe> — ВЕСЬ unpickle в отказ (базовый find_class
    // не импортирует __builtin__ на py3).
    let e = loads_err(b"c__builtin__\nset\n.");
    assert!(matches!(e, RpycError::Decode(_)));
    // __builtin__.object и builtins.object — mock (база _reconstructor
    // в proto 0/1 и `object()` — безвредны, эталон мокает).
    for raw in [
        &b"c__builtin__\nobject\n."[..],
        &b"cbuiltins\nobject\n."[..],
        &b"c__builtin__\nunicode\n."[..],
    ] {
        let v = loads(raw);
        assert!(
            matches!(v.store.nodes[v.root], pickle::Node::Class(_)),
            "ожидался mock-класс"
        );
    }
}

#[test]
fn pickle_reduce_builtin_containers() {
    // set([...]) через REDUCE — форма настоящего pickler (proto ≤ 3).
    let v = loads(b"\x80\x02cbuiltins\nset\n]q\x00(K\x01K\x02e\x85q\x01R.");
    match &v.store.nodes[v.root] {
        pickle::Node::Set(items) => assert_eq!(items.len(), 2),
        _ => panic!("ожидалось множество"),
    }
    // Пустой frozenset() — форма настоящего pickler.
    let v = loads(b"\x80\x02cbuiltins\nfrozenset\n)R.");
    assert!(matches!(
        v.store.nodes[v.root],
        pickle::Node::Set(_)
    ));
    // set от не-коллекции и с лишними аргументами — отказ.
    loads_err(b"\x80\x02cbuiltins\nset\nX\x01\x00\x00\x00a\x85R.");
    // bytearray(b'hi') через REDUCE.
    let v = loads(b"\x80\x02cbuiltins\nbytearray\nB\x02\x00\x00\x00hi\x85R.");
    match &v.store.nodes[v.root] {
        pickle::Node::Bytearray(b) => assert_eq!(b, b"hi"),
        _ => panic!("ожидался bytearray"),
    }
    // list через REDUCE pickler не пишет — отказ (как раньше).
    loads_err(b"\x80\x02cbuiltins\nlist\n]R.");
    // astsupport.PyExpr без аргументов: source "" (как `_PyExpr()`).
    let v = loads(b"\x80\x02crenpy.astsupport\nPyExpr\n)\x81.");
    match &v.store.nodes[v.root] {
        pickle::Node::Object { attrs, .. } => {
            assert!(attrs.iter().any(|(k, _)| k == "source"));
        }
        _ => panic!("ожидался объект"),
    }
}

#[test]
fn pickle_newobj_build() {
    // Say + BUILD(what=...): форма узла с атрибутами.
    let raw = b"\x80\x02crenpy.ast\nSay\n)\x81}(X\x04\x00\x00\x00whatX\x02\x00\x00\x00Hiub.";
    let v = loads(raw);
    match &v.store.nodes[v.root] {
        pickle::Node::Object { attrs, .. } => {
            assert!(attrs.iter().any(|(k, _)| k == "what"));
        }
        _ => panic!("ожидался объект"),
    }
    // PyCode: состояние-кортеж (ver, source, location, mode, py).
    let raw = b"\x80\x02crenpy.ast\nPyCode\n)\x81(K\x01X\x07\x00\x00\x00src = 1X\x04\x00\x00\x00s.pyK\x01\x86X\x04\x00\x00\x00execK\x03tb.";
    let v = loads(raw);
    match &v.store.nodes[v.root] {
        pickle::Node::Object { attrs, .. } => {
            let src = attrs.iter().find(|(k, _)| k == "source").unwrap().1;
            assert_eq!(str_of(&v, src).as_deref(), Some("src = 1"));
        }
        _ => panic!("ожидался PyCode"),
    }
    // NEWOBJ не от класса, REDUCE неизвестного — отказ.
    loads_err(b"N)\x81.");
    loads_err(b"X\x01\x00\x00\x00xR.");
}

#[test]
fn pickle_limits_no_panic() {
    // Гигантская длина без выделения.
    loads_err(b"X\xff\xff\xff\x7f.");
    // Глубокий стек.
    let mut deep = b"\x80\x02".to_vec();
    deep.extend_from_slice(&b"]".repeat(200_000));
    deep.push(b'.');
    assert!(pickle::loads(&deep).is_err());
}

// ── слой 3: текст ──

#[test]
fn text_filters() {
    assert!(text::looks_like_text("Привет, я ведьма."));
    assert!(text::looks_like_text("Идти "));
    assert!(!text::looks_like_text("q1"));
    assert!(!text::looks_like_text("quest_1"));
    assert!(!text::looks_like_text("empty_token_small"));
    assert!(!text::looks_like_text("images/logo.png"));
    assert!(!text::looks_like_text("https://example.com"));
    assert!(!text::looks_like_text("#ff8800"));
    assert!(!text::looks_like_text("42"));
    assert!(!text::looks_like_text("a"));
    // Короткое слово без цифр — ТЕКСТ для фильтра (отсекает его gate
    // пробел/не-ASCII в `_show_text_parts`, а не этот фильтр).
    assert!(text::looks_like_text("eileen"));
    assert!(text::looks_like_text("eileen happy"));
    assert!(!text::looks_like_text("sampler2D blur"));
    assert!(!text::looks_like_text("a;b\nc"));
    assert!(text::looks_like_text("Счёт: [score]"));
    assert_eq!(text::decode_rpy_literal("a\\n\\\"b\\u00e9"), "a\n\"bé");
    assert_eq!(text::decode_rpy_literal("\\N{LATIN SMALL LETTER A}"), "\u{fffd}");
    assert_eq!(
        text::dedent("    a\n\n    b\n"),
        "a\n\nb\n"
    );
    assert_eq!(
        text::regex_literals("x = \"a\" # 'b'"),
        vec!["a".to_string()]
    );
    // Апостроф внутри двойных — не литерал.
    assert_eq!(text::regex_literals("\"don't\""), vec!["don't".to_string()]);
    assert_eq!(text::str_search_first("x = \"a\" + b"), Some("a".to_string()));
    assert_eq!(text::try_eval_string("(\"a\" 'b')"), Some("ab".to_string()));
    assert_eq!(text::try_eval_string("f\"{x}\""), None);
}

// ── слой 3.5: мини-парсер ──

#[test]
fn pyparse_debug_dump() {
    // Временная диагностика для отладки блоков (печатаем токены/parse).
    let cases = [
        "if flag:\n    show_text = \"Показать текст\"",
        "if x:\n    pass",
        "if x:\n    y = \"a\"",
        "if x: y = \"a\"",
        "for i in x:\n    pass",
        "x = \"a\"\nif y:\n    z = \"b\"",
        "def f():\n    return None",
        "def f():\n    \"doc\"\n    return None",
    ];
    for src in cases {
        match pyparse::tokenize(&text::dedent(src)) {
            Ok(toks) => {
                let kinds: Vec<String> =
                    toks.iter().map(|t| format!("{:?}", t.kind)).collect();
                println!("TOKS {src:?} => {kinds:?}");
                match pyparse::parse_file(&text::dedent(src), toks) {
                    Ok(stmts) => println!("AST {src:?} => {stmts:?}"),
                    Err(()) => println!("PARSE-FAIL {src:?}"),
                }
            }
            Err(()) => println!("TOK-FAIL {src:?}"),
        }
        println!("OUT {src:?} => {:?}", pyparse::py_string_literals(src));
    }
}
