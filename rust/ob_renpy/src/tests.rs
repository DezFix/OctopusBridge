//! Тесты прямой замены в `.rpy` — только синтетика, игр у нас нет.
//!
//! Каждый тест зеркалит поведение Python-эталона (`sourcetr.py` /
//! `universal.py`) на тех же примерах: базовые замены из временного
//! `sourcetr_test.py`, guards против перевода кода/путей, правило выбора.
//! Строки примеров — выдуманные маркеры, не текст игр.

use super::*;

fn pair(orig: &str, tr: &str) -> (String, String) {
    (orig.to_string(), tr.to_string())
}

// ── экранирование ──

#[test]
fn escape_basics() {
    assert_eq!(escape(""), "");
    assert_eq!(escape("a"), "a");
    assert_eq!(escape("a\nb"), "a\\nb");
    assert_eq!(escape("a\\b"), "a\\\\b");
    assert_eq!(escape("сказал \"мяу\""), "сказал \\\"мяу\\\"");
    // Порядок: backslash рождает экраны, которые кавычка/перевод строки
    // повторно не трогают.
    assert_eq!(escape("a\\\n\"b"), "a\\\\\\n\\\"b");
    // Не-ASCII проходит как есть.
    assert_eq!(escape("日本語"), "日本語");
}

// ── поиск литералов ──

#[test]
fn find_literal_basic() {
    assert_eq!(find_literal_spans("e \"A\" B", "A"), vec![(2, 5)]);
    // Подстрока шире иглы — мимо.
    assert_eq!(find_literal_spans("\"AA\"", "A"), Vec::new());
    // Одинарные кавычки не трогаем никогда.
    assert_eq!(find_literal_spans("'A'", "A"), Vec::new());
    // Экранированная кавычка перед иглой — пропуск.
    assert_eq!(find_literal_spans("e \\\"A\\\"", "A"), Vec::new());
    // Обычный символ перед иглой — не граница-отказ.
    assert_eq!(find_literal_spans("x\"A\"", "A"), vec![(1, 4)]);
    assert_eq!(find_literal_spans("\"A\"x", "A"), vec![(0, 3)]);
    // Кавычка сразу после — внутри другого литерала, пропуск.
    assert_eq!(find_literal_spans("\"A\"'x", "A"), Vec::new());
    // Слипшиеся литералы: первая игла упирается в кавычку, вторая —
    // начинается с кавычки. Обе пропускаются, замен ноль.
    assert_eq!(find_literal_spans("\"a\"\"a\"", "a"), Vec::new());
}

#[test]
fn find_literal_char_offsets() {
    // Индексы — в символах, как у Python (не в байтах UTF-8).
    assert_eq!(
        find_literal_spans("е \"Привет\" да", "Привет"),
        vec![(2, 10)]
    );
    assert_eq!(find_literal_spans("е\"A\"", "A"), vec![(1, 4)]);
    assert_eq!(find_literal_spans("\"A\"е", "A"), vec![(0, 3)]);
}

#[test]
fn find_literal_empty_key() {
    // Пустой ключ ищет `""` — как Python (мёртвая ветка `if not needle`
    // в эталоне никогда не срабатывает, игла — минимум две кавычки).
    assert_eq!(find_literal_spans("\"\"", ""), vec![(0, 2)]);
    assert_eq!(find_literal_spans("e \"A\"", ""), Vec::new());
}

#[test]
fn find_literal_escaped_needle() {
    // Ключ с кавычкой/переносом ищется по экранированной игле.
    assert_eq!(find_literal_spans("e \"a\\\"b\"", "a\"b"), vec![(2, 8)]);
    assert_eq!(find_literal_spans("e \"a\\nb\"", "a\nb"), vec![(2, 8)]);
}

// ── guard-строки ──

#[test]
fn code_position_prefixes() {
    for line in [
        "import os",
        "  from x import y",
        "else:",
        "  return 5",
        "yield x",
        "assert x",
        "raise E",
        "while 1",
        "for i in x",
        "if x",
        "elif y",
        "with open",
        "del x",
        "global g",
        "print x",
        "lambda x: x",
    ] {
        assert!(line_is_code_position(line), "{line:?}");
    }
    // Регистр важен: `Else:` — не код.
    assert!(!line_is_code_position("  Else:"));
    assert!(!line_is_code_position("e \"Hello\""));
    assert!(!line_is_code_position("define x = \"A\""));
}

#[test]
fn code_position_used_as_code() {
    for line in [
        "x = eval(\"A\")",
        "EVAL (\"A\")",
        "exec\t(x)",
        "compile (x)",
        "x.eval(y)",
        "eval\t(x)",
        "((eval((y))))",
        "EXEC(x)",
        "Compile(x)",
    ] {
        assert!(line_is_code_position(line), "{line:?}");
    }
    for line in [
        "myeval(\"A\")",
        "Preload evalx(",
        "evalx(y)",
        "_eval(y)",
        "9eval(y)",
        "xcompile(y)",
        "recompile(x)",
        "еval(x)",
        "exſc(x)",
        "complİle(x)",
    ] {
        assert!(!line_is_code_position(line), "{line:?}");
    }
}

#[test]
fn code_position_py_spaces() {
    // Python считает пробелами NBSP, ideographic space и даже \x1c;
    // ZWSP — не пробел. Повторяем точь-в-точь.
    assert!(line_is_code_position("eval (x)"));
    assert!(line_is_code_position("eval　(x)"));
    assert!(line_is_code_position("eval\u{1c}(x)"));
    assert!(!line_is_code_position("eval\u{200b}(x)"));
    assert!(line_is_code_position(" import x"));
    assert!(!line_is_code_position("import x"));
}

// ── translate_text ──

#[test]
fn translate_basic() {
    // Базовые замены из временного sourcetr_test.py.
    let cases = [
        ("e \"Hello\"", vec![pair("Hello", "Privet")], "e \"Privet\""),
        ("\"Yes\"", vec![pair("Yes", "Da")], "\"Da\""),
        (
            "x \"A\" y \"B\"",
            vec![pair("A", "A2")],
            "x \"A2\" y \"B\"",
        ),
        // Не тот паттерн — не трогаем.
        ("e 'Hello'", vec![pair("Hello", "Privet")], "e 'Hello'"),
        // Совпадение подстроки не срабатывает.
        (
            "\"Hello world\"",
            vec![pair("Hello", "Privet")],
            "\"Hello world\"",
        ),
    ];
    for (src, map, want) in cases {
        let (out, _, _) = translate_text(src, &map);
        assert_eq!(out, want, "{src:?}");
    }
}

#[test]
fn translate_empty_translation_replaces() {
    // Пустой перевод — Python ЗАМЕНЯЕТ на `""` (счётчик 1), а не пропускает.
    // Повторяем, а не «чиним»: эталон важнее интуиции.
    let (out, n, miss) = translate_text("e \"A\"", &[pair("A", "")]);
    assert_eq!((out.as_str(), n, miss.len()), ("e \"\"", 1, 0));
}

#[test]
fn translate_escapes_output() {
    let (out, n, _) =
        translate_text("e \"A\"\n", &[pair("A", "skazal \"myau\"")]);
    assert_eq!(n, 1);
    assert!(out.contains("\\\"myau\\\""), "{out:?}");
    let (out, _, _) =
        translate_text("e \"A\"\n", &[pair("A", "stroka1\nstroka2")]);
    assert!(out.contains("\\n"), "{out:?}");
    // Настоящих переводов строк внутри литерала нет (хвост — стык строк).
    assert!(!out.trim_end().contains('\n'), "{out:?}");
}

#[test]
fn translate_multi_line_file() {
    let src = "label start:\n    e \"Hello there\"\n    menu:\n        \"Yes\":\n            pass\n        \"No\":\n            pass\n";
    let map = [
        pair("Hello there", "Privet tam"),
        pair("Yes", "Da"),
        pair("No", "Net"),
    ];
    let (out, n, miss) = translate_text(src, &map);
    assert_eq!(n, 3);
    // missed НЕ пуст: строка `menu:` не содержит ни одной иглы, и все три
    // ключа попадают в missed в порядке словаря — как в Python.
    assert_eq!(
        miss,
        vec![
            "Hello there".to_string(),
            "Yes".to_string(),
            "No".to_string()
        ]
    );
    assert!(out.contains("\"Privet tam\""));
    assert!(out.contains("\"Da\""));
    assert!(out.contains("\"Net\""));
}

#[test]
fn translate_guards_keep_code() {
    // Строка с eval/import — код: литерал не трогаем, ключ — в missed.
    let (out, n, miss) =
        translate_text("x = eval(\"A\")", &[pair("A", "B")]);
    assert_eq!((out.as_str(), n), ("x = eval(\"A\")", 0));
    assert_eq!(miss, vec!["A".to_string()]);
    // Дубликаты на guard-строках НЕ схлопываются — как в Python.
    let (_, _, miss) =
        translate_text("import \"A\"\nimport \"A\"", &[pair("A", "B")]);
    assert_eq!(miss, vec!["A".to_string(), "A".to_string()]);
    // Похожее на код/путь в КЛЮЧЕ — тоже отказ, даже на обычной строке.
    for key in [
        "a=b", "a:b", "x and y", "None!", "file.png", "a/b", "a\\b",
        "100% sure",
    ] {
        let line = format!("e \"{key}\"");
        let (_, n, miss) = translate_text(&line, &[pair(key, "X")]);
        assert_eq!(n, 0, "{key:?}");
        assert_eq!(miss, vec![key.to_string()], "{key:?}");
    }
}

#[test]
fn translate_guard_word_boundaries() {
    // Целые слова-ключи — код; те же буквы внутри слова — обычный текст.
    let (_, n, _) =
        translate_text("e \"x_or_y\"", &[pair("x_or_y", "X")]);
    assert_eq!(n, 1);
    let (_, n, _) = translate_text("e \"XAnd\"", &[pair("XAnd", "X")]);
    assert_eq!(n, 1);
    let (_, n, _) = translate_text("e \"false\"", &[pair("false", "X")]);
    assert_eq!(n, 1);
    // А настоящие фрагменты — отказ.
    let (_, n, miss) =
        translate_text("e \"x and y\"", &[pair("x and y", "X")]);
    assert_eq!((n, miss.len()), (0, 1));
    let (_, n, _) =
        translate_text("e \"file.pngx\"", &[pair("file.pngx", "X")]);
    assert_eq!(n, 1); // `.pngx` — не путь (нет границы после расширения)
}

#[test]
fn translate_missed_order_and_counts() {
    // Порядок missed — порядок словаря; счётчик — число хитов.
    let (out, n, miss) = translate_text(
        "\"b\" \"a\"",
        &[pair("a", "X"), pair("b", "Y"), pair("z", "Z")],
    );
    assert_eq!(out, "\"Y\" \"X\"");
    assert_eq!(n, 2);
    assert_eq!(miss, vec!["z".to_string()]);
    // Второе вхождение того же ключа не трогаем (только первое).
    let (out, n, miss) =
        translate_text("\"a\" \"a\"", &[pair("a", "X")]);
    assert_eq!((out.as_str(), n, miss.len()), ("\"X\" \"a\"", 1, 0));
    // Пустой словарь — текст как был, нули.
    let (out, n, miss) = translate_text("e \"A\"", &[]);
    assert_eq!((out.as_str(), n, miss.len()), ("e \"A\"", 0, 0));
}

#[test]
fn translate_empty_key_mirrors_python() {
    // Пустой ключ ищет `""`: есть — замена, нет — missed. Без паники.
    let (out, n, _) =
        translate_text("e \"A\" \"\"", &[pair("", "X")]);
    assert_eq!((out.as_str(), n), ("e \"A\" \"X\"", 1));
    let (_, n, miss) = translate_text("e \"A\"", &[pair("", "X")]);
    assert_eq!(n, 0);
    assert_eq!(miss, vec![String::new()]);
}

// ── правило выбора ──

#[test]
fn choose_method_rule() {
    // >= 3 .rpy — source, идентификаторы даже не смотрятся (False).
    let c = choose_method(3, true);
    assert_eq!(c.method, "source");
    assert_eq!(c.loose_rpy, 3);
    assert!(!c.has_identifiers);
    assert_eq!(
        c.reason,
        "на диске 3 .rpy: перевод пишется прямо \
         в исходники, движок переводов не трогается"
    );
    // Меньше трёх без идентификаторов — hooks.
    let c = choose_method(0, false);
    assert_eq!(c.method, "hooks");
    assert!(!c.has_identifiers);
    assert_eq!(
        c.reason,
        "только .rpyc без идентификаторов: перевод \
         видимого текста хуками, код не трогаем"
    );
    // Меньше трёх с идентификаторами — native.
    let c = choose_method(2, true);
    assert_eq!(c.method, "native");
    assert!(c.has_identifiers);
    assert_eq!(
        c.reason,
        "в .rpyc есть идентификаторы реплик: пишем штатные блоки translate"
    );
    // Граница 2/3.
    assert_eq!(choose_method(2, false).method, "hooks");
    assert_eq!(choose_method(3, false).method, "source");
}

#[test]
fn source_rpy_name_filter() {
    assert!(is_source_rpy_name("script.rpy"));
    assert!(is_source_rpy_name("a/b/c.rpy"));
    assert!(!is_source_rpy_name("ob_x.rpy"));
    assert!(!is_source_rpy_name("zz_ob_lang.rpy"));
    assert!(!is_source_rpy_name("x.rpyc"));
    assert!(!is_source_rpy_name("A.RPY"));
    assert!(!is_source_rpy_name("ob_.rpyc"));
}

// ── битый вход без паники ──

#[test]
fn bad_inputs_no_panic() {
    // Пустые строки, огромные строки, ключи-мусор — ошибка/пусто, не паника.
    let big = "x".repeat(1 << 20);
    let (out, n, _) = translate_text(&big, &[pair("q", "w")]);
    assert_eq!(n, 0);
    assert_eq!(out, big);
    let (_, n, miss) = translate_text("", &[pair("", "")]);
    // В пустой строке иглы `""` нет: отказ без паники.
    assert_eq!(n, 0);
    assert_eq!(miss, vec![String::new()]);
    // Перекрывающиеся хиты разных ключей не роняют склейку.
    let (out, n, _) = translate_text(
        "\"ab\"",
        &[pair("ab", "X"), pair("b", "Y")],
    );
    assert_eq!(out, "\"X\"");
    assert_eq!(n, 1);
    // Ключ с экранированием и юникодом.
    let (out, n, _) = translate_text(
        "е \"П\\nр\"",
        &[pair("П\nр", "R")],
    );
    assert_eq!((out.as_str(), n), ("е \"R\"", 1));
}
