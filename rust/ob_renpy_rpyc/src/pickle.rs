//! Слой 2 — pickle-VM для AST Ren'Py с защитой от hostile-pickle.
//!
//! Минимальный интерпретатор pickle-протоколов 0–4, достаточный для
//! `.rpyc`: все контейнеры, скаляры, строки/байты py2/py3, `GLOBAL` /
//! `STACK_GLOBAL` через белый список, `NEWOBJ` / `NEWOBJ_EX` / `REDUCE` /
//! `BUILD` для mock-узлов, мемоизация (`BINPUT`/`BINGET`/…).
//!
//! Порт связки `_RenPyUnpickler.find_class` + `_RENPY_MOCKS` + семантики
//! `pickle.Unpickler` (CPython 3.13, C-реализация — именно она реально
//! исполняется в эталоне): `find_class` возвращает mock-класс с
//! произвольными атрибутами, `copyreg.__newobj__` — настоящий. Поведение
//! на битом входе — `Err`, а не исключение наружу.
//!
//! Защита (чего нет у наивного unpickle):
//! * `GLOBAL`/`STACK_GLOBAL` вне белого списка (`renpy.*`, безопасные
//!   `builtins`, `copyreg.__newobj__/_reconstructor`, безвредные
//!   mock-имена `copy_reg.*`/`__builtin__`-other/`builtins.object`/`_codecs.encode`)
//!   — отказ (`Unsafe`). В Python чужой модуль уходил бы в mock
//!   (`_mock_ext_*`) и разбор продолжался; здесь — `Unsafe`: молча
//!   тянуть неизвестные классы в AST перевода нельзя. На настоящих
//!   `.rpyc` (только `renpy.*` + builtins + copyreg/copy_reg + `object`
//!   как база `_reconstructor`) поведение совпадает один в один;
//! * py2-имена (`copy_reg`, `__builtin__`) обрабатываются БЕЗ ветвления
//!   по протоколу — как в эталоне (там его нет): `copy_reg.*` мокается
//!   всегда (иначе proto-0/1 графы сыпались бы в отказ, а Python их
//!   разбирает в `_MockNode`), `__builtin__.<safe>` роняет весь unpickle
//!   (базовый `find_class` не импортирует `__builtin__` на py3);
//! * `REDUCE`/`NEWOBJ`/`INST` с неизвестным callable — отказ
//!   (в Python это был бы вызов mock-конструктора, который ничего
//!   не делает, — здесь строже), кроме `set`/`frozenset`/`bytearray`
//!   (их испускает сам pickler — эмулируем инертным узлом);
//! * `PERSID`/`BINPERSID`/`EXT*`/`NEXT_BUFFER` — отказ (вне протоколов
//!   0–4 либо требует внешних данных);
//! * предохранители: число опкодов, узлов, глубина стека, размер мемои,
//!   длины строк/байтов, выход `zlib` (см. [`crate::framing`]).
//!
//! Модель значений — арена [`Store`] с индексами [`Ref`]: мемоизация
//! pickle отдаёт ТОТ ЖЕ объект (как `memo[i]` в Python), а `_walk_ast`
//! различает объекты по идентичности (`id()`), а не по равенству —
//! индексы это сохраняют.

use crate::RpycError;
use std::collections::HashMap;

/// Сколько опкодов максимум исполняем на один поток (защита от
/// «миллиарда смешков» через `APPENDS`/`SETITEMS`-циклы).
pub const MAX_OPS: u64 = 20_000_000;
/// Сколько узлов максимум живёт в арене.
pub const MAX_NODES: usize = 2_000_000;
/// Глубина стека VM (вложенность pickle).
pub const MAX_STACK: usize = 100_000;
/// Записей мемоизации максимум.
pub const MAX_MEMO: usize = 2_000_000;
/// Длина одной строки/байтстроки (защита от OOM на длинах из потока).
pub const MAX_STR: usize = 64 << 20;
/// Знаков в десятичном целом максимум (как лимит Python 3.11+ на
/// преобразование int<->str: сверх — отказ, а не зависание).
pub const MAX_INT_DIGITS: usize = 4300;
/// Байт в `LONG1`/`LONG4` максимум (сверх — отказ).
pub const MAX_BIGINT_BYTES: usize = 1024;

/// Ссылка на узел арены. Копируема: мемоизация и стек делят владение,
/// как ссылки Python-объектов (без `Rc` — индексы стабильны).
pub type Ref = usize;

/// Целое произвольной величины.
///
/// Точные значения нужны только малым (номера строк, версии); большие
/// в AST извлечения не участвуют — храним как есть для равенства ключей.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IntVal {
    Small(i64),
    /// Ненормализованные байты LE two's complement (`LONG1`/`LONG4`).
    BigLe(Vec<u8>),
    /// Нормализованная десятичная строка (`INT`/`LONG`).
    BigDec(String),
}

/// Словарь: контент (пары, в порядке вставки) + атрибуты (`__dict__`
/// для `BUILD`, как у `dict`-подклассов в Python).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct DictData {
    pub items: Vec<(Ref, Ref)>,
    pub attrs: Vec<(String, Ref)>,
}

/// Узел значения pickle.
#[derive(Debug, Clone, PartialEq)]
pub enum Node {
    None,
    Bool(bool),
    Int(IntVal),
    Float(f64),
    /// Настоящая строка (`BINUNICODE`, `UNICODE`, ASCII-`BINSTRING`…).
    Str(String),
    /// `str`-подкласс Ren'Py (`PyExpr`/`RawCode`, флаг `_ob_py_expr`):
    /// значение — python-исходник, НЕ текст для перевода.
    PyStr(String),
    Bytes(Vec<u8>),
    /// `bytearray`: в `_string_parts` это НЕ `bytes` — пропускается.
    Bytearray(Vec<u8>),
    List(Vec<Ref>),
    Tuple(Vec<Ref>),
    Dict(DictData),
    Set(Vec<Ref>),
    /// Результат `GLOBAL`/`STACK_GLOBAL`: класс (не вызывается).
    Class(usize),
    /// Экземпляр mock-класса с произвольными атрибутами.
    Object {
        class: usize,
        attrs: Vec<(String, Ref)>,
    },
}

/// Вид mock-класса из белого списка.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClassKind {
    /// Обычный узел (`Say`, `Menu`, `_mock_*`, …).
    Plain,
    /// `str`-подкласс (`renpy.ast.PyExpr`, `renpy.python.RawCode`).
    StrLike,
    /// `renpy.astsupport.PyExpr`: объект с `.source` (старый `__reduce__`).
    AstsupportExpr,
    /// `renpy.ast.PyCode`: `__setstate__` кортежем `(ver, source, …)`.
    PyCode,
    /// `dict`-подкласс (`renpy.revertable.RevertableDict`).
    DictSub,
    /// Безопасный конструктор `builtins` (`list`, `dict`, …).
    Builtin(BuiltinKind),
    /// `copyreg.__newobj__`.
    NewObj,
    /// `copyreg._reconstructor` (протоколы 0/1).
    Reconstructor,
    /// `_codecs.encode`: его испускает сам pickler для `bytes` в
    /// протоколах ≥ 2 (`GLOBAL _codecs encode` + `REDUCE (s, 'latin1')`).
    /// Вызов mock-конструктора в эталоне ничего не делает и содержимое
    /// байтов ТЕРЯЕТСЯ (пустой mock-объект) — повторяем в точности,
    /// а не «чиним»: иначе тройки разойдутся с Python.
    CodecEncode,
}

/// Безопасные `builtins` (тот же набор, что `_SAFE_BUILTINS` эталона).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BuiltinKind {
    List,
    Dict,
    Tuple,
    Set,
    Frozenset,
    Str,
    Int,
    Float,
    Bool,
    Bytes,
    Bytearray,
    Complex,
}

/// Класс из белого списка: как его строить и как его видит `_walk_ast`.
#[derive(Debug, Clone)]
pub struct ClassInfo {
    pub module: String,
    pub name: String,
    /// Эквивалент `type(obj).__name__` в Python (`"Say"`, `"_mock_Foo"`,
    /// `"_PyCode"`, `"_MockPyExpr"`, …) — по нему ветвления обхода.
    pub type_name: String,
    pub kind: ClassKind,
}

/// Арена значений и классов одного unpickle.
#[derive(Debug, Default)]
pub struct Store {
    pub nodes: Vec<Node>,
    pub classes: Vec<ClassInfo>,
}

/// Результат unpickle: арена + корень (как `u.load()` в Python).
#[derive(Debug)]
pub struct Value {
    pub store: Store,
    pub root: Ref,
}

impl Store {
    /// Положить узел с учётом лимита (защита от раздувания арены).
    fn push(&mut self, node: Node) -> Result<Ref, RpycError> {
        if self.nodes.len() >= MAX_NODES {
            return Err(RpycError::TooBig(format!(
                "pickle: больше {MAX_NODES} узлов"
            )));
        }
        self.nodes.push(node);
        Ok(self.nodes.len() - 1)
    }

    fn push_class(&mut self, cls: ClassInfo) -> Ref {
        // Классов — единицы на поток; лимит арены их тоже покрывает,
        // но отдельный счётчик здесь не нужен (число GLOBAL ограничено
        // числом опкодов через MAX_OPS).
        self.nodes.push(Node::Class(self.classes.len()));
        self.classes.push(cls);
        self.nodes.len() - 1
    }
}

/// Прочитать поток pickle в арену (эквивалент `u.load()`).
pub fn loads(data: &[u8]) -> Result<Value, RpycError> {
    let mut vm = Vm::new(data);
    let root = vm.run()?;
    Ok(Value { store: vm.store, root })
}

struct Vm<'a> {
    data: &'a [u8],
    pos: usize,
    ops: u64,
    store: Store,
    stack: Vec<Ref>,
    marks: Vec<usize>,
    memo: HashMap<u64, Ref>,
}

impl<'a> Vm<'a> {
    fn new(data: &'a [u8]) -> Self {
        Vm {
            data,
            pos: 0,
            ops: 0,
            store: Store::default(),
            stack: Vec::new(),
            marks: Vec::new(),
            memo: HashMap::new(),
        }
    }

    fn fail_decode(msg: impl Into<String>) -> RpycError {
        RpycError::Decode(format!("pickle: {}", msg.into()))
    }

    fn fail_unsafe(msg: impl Into<String>) -> RpycError {
        RpycError::Unsafe(format!("pickle: {}", msg.into()))
    }

    // ── чтение ──

    fn read_byte(&mut self) -> Result<u8, RpycError> {
        let b = *self
            .data
            .get(self.pos)
            .ok_or_else(|| Self::fail_decode("обрезанный опкод"))?;
        self.pos += 1;
        Ok(b)
    }

    fn read_bytes(&mut self, n: usize) -> Result<&'a [u8], RpycError> {
        if n > MAX_STR {
            return Err(RpycError::TooBig(format!(
                "pickle: поле {n} байт больше лимита"
            )));
        }
        let e = self.pos.saturating_add(n);
        let chunk = self.data.get(self.pos..e).ok_or_else(|| {
            Self::fail_decode("обрезанный поток")
        })?;
        self.pos = e;
        Ok(chunk)
    }

    /// Строка до `\n` включительно (C-unpickler требует `\n`: обрезанная
    /// линия — `UnpicklingError`, а не молчаливое принятие хвоста).
    fn read_line(&mut self) -> Result<&'a [u8], RpycError> {
        let rel = self.data[self.pos..]
            .iter()
            .position(|&b| b == b'\n')
            .ok_or_else(|| Self::fail_decode("обрезанная линия"))?;
        if rel > MAX_STR {
            return Err(RpycError::TooBig(
                "pickle: линия длиннее лимита".to_string(),
            ));
        }
        let e = self.pos + rel + 1;
        let line = &self.data[self.pos..e];
        self.pos = e;
        Ok(line)
    }

    fn read_u16le(&mut self) -> Result<u16, RpycError> {
        let b = self.read_bytes(2)?;
        Ok(u16::from_le_bytes([b[0], b[1]]))
    }

    fn read_u32le(&mut self) -> Result<u32, RpycError> {
        let b = self.read_bytes(4)?;
        Ok(u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
    }

    fn read_i32le(&mut self) -> Result<i32, RpycError> {
        let b = self.read_bytes(4)?;
        Ok(i32::from_le_bytes([b[0], b[1], b[2], b[3]]))
    }

    fn read_u64le(&mut self) -> Result<u64, RpycError> {
        let b = self.read_bytes(8)?;
        Ok(u64::from_le_bytes([
            b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
        ]))
    }

    // ── стек/мемои ──

    fn push(&mut self, node: Node) -> Result<(), RpycError> {
        if self.stack.len() >= MAX_STACK {
            return Err(RpycError::TooBig(format!(
                "pickle: стек глубже {MAX_STACK}"
            )));
        }
        let r = self.store.push(node)?;
        self.stack.push(r);
        Ok(())
    }

    fn push_ref(&mut self, r: Ref) -> Result<(), RpycError> {
        if self.stack.len() >= MAX_STACK {
            return Err(RpycError::TooBig(format!(
                "pickle: стек глубже {MAX_STACK}"
            )));
        }
        self.stack.push(r);
        Ok(())
    }

    fn pop(&mut self) -> Result<Ref, RpycError> {
        self.stack.pop().ok_or_else(|| Self::fail_decode("пустой стек"))
    }

    fn top(&self) -> Result<Ref, RpycError> {
        self.stack.last().copied().ok_or_else(|| {
            Self::fail_decode("пустой стек")
        })
    }

    fn pop_mark(&mut self) -> Result<Vec<Ref>, RpycError> {
        let mark = self.marks.pop().ok_or_else(|| {
            Self::fail_decode("нет метки MARK")
        })?;
        if mark > self.stack.len() {
            return Err(Self::fail_decode("метка MARK вне стека"));
        }
        Ok(self.stack.split_off(mark))
    }

    fn memo_insert(&mut self, key: u64, r: Ref) -> Result<(), RpycError> {
        if self.memo.len() >= MAX_MEMO && !self.memo.contains_key(&key) {
            return Err(RpycError::TooBig(format!(
                "pickle: мемои больше {MAX_MEMO}"
            )));
        }
        self.memo.insert(key, r);
        Ok(())
    }

    fn memo_get(&self, key: u64) -> Result<Ref, RpycError> {
        self.memo.get(&key).copied().ok_or_else(|| {
            Self::fail_decode(format!("нет мемои {key}"))
        })
    }

    // ── главный цикл ──

    fn run(&mut self) -> Result<Ref, RpycError> {
        loop {
            if self.ops >= MAX_OPS {
                return Err(RpycError::TooBig(format!(
                    "pickle: больше {MAX_OPS} опкодов"
                )));
            }
            self.ops += 1;
            let op = self.read_byte()?;
            match op {
                // MARK '('
                b'(' => self.marks.push(self.stack.len()),
                // STOP '.'
                b'.' => return self.pop(),
                // POP '0': со стеком — снять, без — pop_mark (как в Python).
                b'0' => {
                    if self.stack.pop().is_none() {
                        self.pop_mark()?;
                    }
                }
                // POP_MARK '1'
                b'1' => {
                    self.pop_mark()?;
                }
                // DUP '2'
                b'2' => {
                    let r = self.top()?;
                    self.push_ref(r)?;
                }
                // FLOAT 'F'
                b'F' => {
                    let line = self.read_line()?;
                    let v = parse_float_line(&line[..line.len() - 1])?;
                    self.push(Node::Float(v))?;
                }
                // BINFLOAT 'G'
                b'G' => {
                    let b = self.read_bytes(8)?;
                    let v = f64::from_be_bytes([
                        b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
                    ]);
                    self.push(Node::Float(v))?;
                }
                // INT 'I'
                b'I' => {
                    let line = self.read_line()?;
                    let v = parse_int_line(line)?;
                    self.push(v)?;
                }
                // BININT 'J'
                b'J' => {
                    let v = self.read_i32le()?;
                    self.push(Node::Int(IntVal::Small(v as i64)))?;
                }
                // BININT1 'K'
                b'K' => {
                    let v = self.read_byte()?;
                    self.push(Node::Int(IntVal::Small(v as i64)))?;
                }
                // BININT2 'M'
                b'M' => {
                    let v = self.read_u16le()?;
                    self.push(Node::Int(IntVal::Small(v as i64)))?;
                }
                // LONG 'L'
                b'L' => {
                    let line = self.read_line()?;
                    let v = parse_long_line(line)?;
                    self.push(v)?;
                }
                // LONG1 0x8a
                0x8a => {
                    let n = self.read_byte()? as usize;
                    let bytes = self.read_bytes(n)?.to_vec();
                    self.push(Node::Int(decode_long_le(&bytes)?))?;
                }
                // LONG4 0x8b
                0x8b => {
                    let n = self.read_i32le()?;
                    if n < 0 {
                        return Err(Self::fail_decode(
                            "LONG4 с отрицательной длиной",
                        ));
                    }
                    let bytes = self.read_bytes(n as usize)?.to_vec();
                    self.push(Node::Int(decode_long_le(&bytes)?))?;
                }
                // NONE 'N'
                b'N' => self.push(Node::None)?,
                // NEWTRUE 0x88 / NEWFALSE 0x89
                0x88 => self.push(Node::Bool(true))?,
                0x89 => self.push(Node::Bool(false))?,
                // PERSID 'P' / BINPERSID 'Q' — внешних данных нет.
                b'P' | b'Q' => {
                    return Err(Self::fail_unsafe(
                        "PERSID: внешних persistent-объектов нет",
                    ));
                }
                // REDUCE 'R'
                b'R' => self.op_reduce()?,
                // STRING 'S'
                b'S' => {
                    let line = self.read_line()?;
                    let v = parse_string_line(line)?;
                    self.push(Node::Str(v))?;
                }
                // BINSTRING 'T' (знаковый len!) — в py3 это str (ASCII).
                b'T' => {
                    let n = self.read_i32le()?;
                    if n < 0 {
                        return Err(Self::fail_decode(
                            "BINSTRING с отрицательной длиной",
                        ));
                    }
                    let bytes = self.read_bytes(n as usize)?;
                    self.push(Node::Str(decode_ascii(bytes)?))?;
                }
                // SHORT_BINSTRING 'U'
                b'U' => {
                    let n = self.read_byte()? as usize;
                    let bytes = self.read_bytes(n)?;
                    self.push(Node::Str(decode_ascii(bytes)?))?;
                }
                // UNICODE 'V'
                b'V' => {
                    let line = self.read_line()?;
                    let v = decode_raw_unicode_escape(
                        &line[..line.len() - 1],
                    )?;
                    self.push(Node::Str(v))?;
                }
                // BINUNICODE 'X'
                b'X' => {
                    let n = self.read_u32le()?;
                    let bytes = self.read_bytes(n as usize)?;
                    self.push(Node::Str(decode_utf8(bytes)?))?;
                }
                // SHORT_BINUNICODE 0x8c
                0x8c => {
                    let n = self.read_byte()? as usize;
                    let bytes = self.read_bytes(n)?;
                    self.push(Node::Str(decode_utf8(bytes)?))?;
                }
                // BINUNICODE8 0x8d
                0x8d => {
                    let n = self.read_u64le()?;
                    let n = usize::try_from(n)
                        .map_err(|_| Self::fail_decode("длина не влезла"))?;
                    let bytes = self.read_bytes(n)?;
                    self.push(Node::Str(decode_utf8(bytes)?))?;
                }
                // BINBYTES 'B'
                b'B' => {
                    let n = self.read_u32le()?;
                    let bytes = self.read_bytes(n as usize)?.to_vec();
                    self.push(Node::Bytes(bytes))?;
                }
                // SHORT_BINBYTES 'C'
                b'C' => {
                    let n = self.read_byte()? as usize;
                    let bytes = self.read_bytes(n)?.to_vec();
                    self.push(Node::Bytes(bytes))?;
                }
                // BINBYTES8 0x8e
                0x8e => {
                    let n = self.read_u64le()?;
                    let n = usize::try_from(n)
                        .map_err(|_| Self::fail_decode("длина не влезла"))?;
                    let bytes = self.read_bytes(n)?.to_vec();
                    self.push(Node::Bytes(bytes))?;
                }
                // EMPTY_LIST ']' / EMPTY_TUPLE ')' / EMPTY_DICT '}'
                // / EMPTY_SET 0x8f
                b']' => self.push(Node::List(Vec::new()))?,
                b')' => self.push(Node::Tuple(Vec::new()))?,
                b'}' => self.push(Node::Dict(DictData::default()))?,
                0x8f => self.push(Node::Set(Vec::new()))?,
                // APPEND 'a'
                b'a' => {
                    let v = self.pop()?;
                    let t = self.top()?;
                    match &mut self.store.nodes[t] {
                        Node::List(items) => items.push(v),
                        _ => {
                            return Err(Self::fail_decode(
                                "APPEND не в список",
                            ));
                        }
                    }
                }
                // APPENDS 'e'
                b'e' => {
                    let items = self.pop_mark()?;
                    let t = self.top()?;
                    match &mut self.store.nodes[t] {
                        Node::List(slot) => slot.extend(items),
                        _ => {
                            return Err(Self::fail_decode(
                                "APPENDS не в список",
                            ));
                        }
                    }
                }
                // BUILD 'b'
                b'b' => self.op_build()?,
                // GLOBAL 'c'
                b'c' => {
                    let module = self.read_line()?;
                    let name = self.read_line()?;
                    let module = decode_utf8(
                        &module[..module.len() - 1],
                    )?;
                    let name =
                        decode_utf8(&name[..name.len() - 1])?;
                    let cls = find_class(&module, &name)?;
                    let r = self.store.push_class(cls);
                    self.push_ref(r)?;
                }
                // DICT 'd'
                b'd' => {
                    let items = self.pop_mark()?;
                    let dict = pairs_to_dict(items, &self.store.nodes)?;
                    self.push(Node::Dict(dict))?;
                }
                // GET 'g'
                b'g' => {
                    let line = self.read_line()?;
                    let key = parse_memo_line(&line[..line.len() - 1])?;
                    let r = self.memo_get(key)?;
                    self.push_ref(r)?;
                }
                // BINGET 'h'
                b'h' => {
                    let key = self.read_byte()? as u64;
                    let r = self.memo_get(key)?;
                    self.push_ref(r)?;
                }
                // INST 'i'
                b'i' => {
                    let module = self.read_line()?;
                    let name = self.read_line()?;
                    let module = decode_ascii(
                        &module[..module.len() - 1],
                    )?;
                    let name = decode_ascii(&name[..name.len() - 1])?;
                    let cls = find_class(&module, &name)?;
                    let cls_ref = self.store.push_class(cls);
                    let args = self.pop_mark()?;
                    let inst = self.construct(cls_ref, &args)?;
                    self.push_ref(inst)?;
                }
                // LONG_BINGET 'j'
                b'j' => {
                    let key = self.read_u32le()? as u64;
                    let r = self.memo_get(key)?;
                    self.push_ref(r)?;
                }
                // LIST 'l'
                b'l' => {
                    let items = self.pop_mark()?;
                    self.push(Node::List(items))?;
                }
                // OBJ 'o'
                b'o' => {
                    let mut args = self.pop_mark()?;
                    if args.is_empty() {
                        return Err(Self::fail_decode("OBJ без класса"));
                    }
                    let cls_ref = args.remove(0);
                    if !matches!(
                        self.store.nodes.get(cls_ref),
                        Some(Node::Class(_))
                    ) {
                        return Err(Self::fail_unsafe(
                            "OBJ не от класса",
                        ));
                    }
                    let inst = self.construct(cls_ref, &args)?;
                    self.push_ref(inst)?;
                }
                // PUT 'p'
                b'p' => {
                    let line = self.read_line()?;
                    let key = parse_memo_line(&line[..line.len() - 1])?;
                    let r = self.top()?;
                    self.memo_insert(key, r)?;
                }
                // BINPUT 'q'
                b'q' => {
                    let key = self.read_byte()? as u64;
                    let r = self.top()?;
                    self.memo_insert(key, r)?;
                }
                // LONG_BINPUT 'r'
                b'r' => {
                    let key = self.read_u32le()? as u64;
                    let r = self.top()?;
                    self.memo_insert(key, r)?;
                }
                // SETITEM 's'
                b's' => {
                    let value = self.pop()?;
                    let key = self.pop()?;
                    let t = self.top()?;
                    if !matches!(
                        self.store.nodes.get(t),
                        Some(Node::Dict(_))
                    ) {
                        return Err(Self::fail_decode(
                            "SETITEM не в словарь",
                        ));
                    }
                    dict_insert(&mut self.store, t, key, value);
                }
                // TUPLE 't'
                b't' => {
                    let items = self.pop_mark()?;
                    self.push(Node::Tuple(items))?;
                }
                // SETITEMS 'u'
                b'u' => {
                    let items = self.pop_mark()?;
                    if items.len() % 2 != 0 {
                        return Err(Self::fail_decode(
                            "SETITEMS с нечётным числом",
                        ));
                    }
                    let t = self.top()?;
                    if !matches!(
                        self.store.nodes.get(t),
                        Some(Node::Dict(_))
                    ) {
                        return Err(Self::fail_decode(
                            "SETITEMS не в словарь",
                        ));
                    }
                    let mut i = 0;
                    while i < items.len() {
                        dict_insert(&mut self.store, t, items[i], items[i + 1]);
                        i += 2;
                    }
                }
                // PROTO 0x80
                0x80 => {
                    let proto = self.read_byte()?;
                    if proto > 5 {
                        return Err(Self::fail_decode(format!(
                            "протокол {proto} не поддерживается"
                        )));
                    }
                    // Значение больше ни на что не влияет: в `find_class`
                    // эталона ветвления по протоколу нет (проверено).
                }
                // NEWOBJ 0x81
                0x81 => {
                    let args = self.pop()?;
                    let cls_ref = self.pop()?;
                    if !matches!(
                        self.store.nodes.get(cls_ref),
                        Some(Node::Class(_))
                    ) {
                        return Err(Self::fail_unsafe(
                            "NEWOBJ не от класса",
                        ));
                    }
                    let argv = self.unpack_args(args)?;
                    let inst = self.construct(cls_ref, &argv)?;
                    self.push_ref(inst)?;
                }
                // EXT1/EXT2/EXT4 — реестра нет: отказ (в Python
                // незарегистрированный код тоже даёт ошибку).
                0x82 => {
                    self.read_bytes(1)?;
                    return Err(Self::fail_unsafe(
                        "EXT: реестр расширений пуст",
                    ));
                }
                0x83 => {
                    self.read_bytes(2)?;
                    return Err(Self::fail_unsafe(
                        "EXT: реестр расширений пуст",
                    ));
                }
                0x84 => {
                    self.read_bytes(4)?;
                    return Err(Self::fail_unsafe(
                        "EXT: реестр расширений пуст",
                    ));
                }
                // TUPLE1/2/3
                0x85 => {
                    let a = self.pop()?;
                    self.push(Node::Tuple(vec![a]))?;
                }
                0x86 => {
                    let b = self.pop()?;
                    let a = self.pop()?;
                    self.push(Node::Tuple(vec![a, b]))?;
                }
                0x87 => {
                    let c = self.pop()?;
                    let b = self.pop()?;
                    let a = self.pop()?;
                    self.push(Node::Tuple(vec![a, b, c]))?;
                }
                // LONG1/LONG4 — выше (0x8a/0x8b).
                // FROZENSET 0x91
                0x91 => {
                    let items = self.pop_mark()?;
                    self.push(Node::Set(items))?;
                }
                // NEWOBJ_EX 0x92
                0x92 => {
                    let kwargs = self.pop()?;
                    let args = self.pop()?;
                    let cls_ref = self.pop()?;
                    if !matches!(
                        self.store.nodes.get(cls_ref),
                        Some(Node::Class(_))
                    ) {
                        return Err(Self::fail_unsafe(
                            "NEWOBJ_EX не от класса",
                        ));
                    }
                    // Как `cls.__new__(cls, *args, **kwargs)` у mock:
                    // kwargs игнорируются (mock их не выполняет).
                    if !matches!(
                        self.store.nodes.get(kwargs),
                        Some(Node::Dict(_)) | Some(Node::None)
                    ) {
                        return Err(Self::fail_decode(
                            "NEWOBJ_EX: kwargs не словарь",
                        ));
                    }
                    let argv = self.unpack_args(args)?;
                    let inst = self.construct(cls_ref, &argv)?;
                    self.push_ref(inst)?;
                }
                // STACK_GLOBAL 0x93
                0x93 => {
                    let name = self.pop()?;
                    let module = self.pop()?;
                    let (module, name) = match (
                        self.store.nodes.get(module),
                        self.store.nodes.get(name),
                    ) {
                        (
                            Some(Node::Str(m)),
                            Some(Node::Str(n)),
                        ) => (m.clone(), n.clone()),
                        _ => {
                            return Err(Self::fail_decode(
                                "STACK_GLOBAL требует str",
                            ));
                        }
                    };
                    let cls = find_class(&module, &name)?;
                    let r = self.store.push_class(cls);
                    self.push_ref(r)?;
                }
                // MEMOIZE 0x94
                0x94 => {
                    let r = self.top()?;
                    let key = self.memo.len() as u64;
                    self.memo_insert(key, r)?;
                }
                // FRAME 0x95
                0x95 => {
                    let size = self.read_u64le()?;
                    if size > crate::framing::MAX_DECOMPRESSED {
                        return Err(RpycError::TooBig(format!(
                            "pickle: фрейм {size} больше лимита"
                        )));
                    }
                    // Границы фреймов на семантику не влияют: все чтения
                    // и так с проверкой границ. Продолжаем по тому же
                    // буферу (эквивалентно склейке фреймов).
                }
                // ADDITEMS 0x90
                0x90 => {
                    let items = self.pop_mark()?;
                    let t = self.top()?;
                    match &mut self.store.nodes[t] {
                        Node::Set(slot) => slot.extend(items),
                        _ => {
                            return Err(Self::fail_decode(
                                "ADDITEMS не во множество",
                            ));
                        }
                    }
                }
                // BYTEARRAY8 0x96 / NEXT_BUFFER 0x97 / READONLY_BUFFER 0x98
                0x96 => {
                    let n = self.read_u64le()?;
                    let n = usize::try_from(n)
                        .map_err(|_| Self::fail_decode("длина не влезла"))?;
                    let bytes = self.read_bytes(n)?.to_vec();
                    self.push(Node::Bytearray(bytes))?;
                }
                0x97 | 0x98 => {
                    return Err(Self::fail_unsafe(
                        "out-of-band буферы не поддерживаются",
                    ));
                }
                _ => {
                    return Err(Self::fail_decode(format!(
                        "неизвестный опкод 0x{op:02x}"
                    )));
                }
            }
        }
    }

    // ── сложные опкоды ──

    /// Аргументы `*args` для `NEWOBJ`/`NEWOBJ_EX`/`REDUCE`: только кортеж.
    /// Список здесь — отказ: `PyObject_Call` в CPython требует tuple
    /// (`TypeError` → весь unpickle в `None`), pickler всегда пишет tuple.
    fn unpack_args(&self, args: Ref) -> Result<Vec<Ref>, RpycError> {
        match self.store.nodes.get(args) {
            Some(Node::Tuple(items)) => Ok(items.clone()),
            _ => Err(Self::fail_decode("аргументы не кортеж")),
        }
    }

    /// `REDUCE`: `func(*args)` только для whitelisted-callable.
    fn op_reduce(&mut self) -> Result<(), RpycError> {
        let args = self.pop()?;
        let func = self.top()?;
        let argv = self.unpack_args(args)?;
        let cls_info = match self.store.nodes.get(func) {
            Some(Node::Class(i)) => self.store.classes.get(*i).cloned(),
            _ => None,
        };
        let Some(cls) = cls_info else {
            return Err(Self::fail_unsafe(
                "REDUCE с неизвестным callable",
            ));
        };
        // `copyreg.__newobj__` через REDUCE (протоколы 0/1): первый
        // аргумент — класс, остальные — ему.
        if cls.kind == ClassKind::NewObj {
            if argv.is_empty() {
                return Err(Self::fail_decode("REDUCE __newobj__ без класса"));
            }
            let cls_ref = argv[0];
            if !matches!(
                self.store.nodes.get(cls_ref),
                Some(Node::Class(_))
            ) {
                return Err(Self::fail_unsafe(
                    "REDUCE __newobj__ не от класса",
                ));
            }
            let inst = self.construct(cls_ref, &argv[1..])?;
            self.stack.pop();
            self.push_ref(inst)?;
            return Ok(());
        }
        if cls.kind == ClassKind::Reconstructor {
            let inst = self.reconstruct(&argv)?;
            self.stack.pop();
            self.push_ref(inst)?;
            return Ok(());
        }
        // `_codecs.encode(bytes, 'latin1')` от pickler: mock-вызов,
        // результат — пустой объект (содержимое теряется и в Python).
        if cls.kind == ClassKind::CodecEncode {
            let ci = self.class_index(func)?;
            let inst = self.store.push(Node::Object {
                class: ci,
                attrs: Vec::new(),
            })?;
            self.stack.pop();
            self.push_ref(inst)?;
            return Ok(());
        }
        if matches!(cls.kind, ClassKind::Builtin(_)) {
            let inst = self.reduce_builtin(cls.kind, &argv)?;
            self.stack.pop();
            self.push_ref(inst)?;
            return Ok(());
        }
        let func_ref = func;
        let inst = self.construct(func_ref, &argv)?;
        self.stack.pop();
        self.push_ref(inst)?;
        Ok(())
    }

    /// `REDUCE` безопасного builtin-конструктора: повторяет вызов
    /// настоящего `set(...)`/`bytearray(...)`, которым unpickler строит
    /// объекты (pickler протоколов ≤ 3 пишет множества именно так:
    /// `GLOBAL builtins set` + список + `REDUCE`; `bytearray` — так на
    /// всех протоколах). Результат инертен и обходом игнорируется
    /// (как настоящий `set`/`bytearray` в `_walk_ast`), важен сам факт,
    /// что файл РАЗОБРАЛСЯ, а не ушёл в отказ целиком.
    ///
    /// Формы — только те, что испускает pickler (0/1 аргумент, коллекция
    /// или байты); остальное — отказ: настоящий конструктор принял бы
    /// и итерируемое (ключи словаря, символы строки), но такие формы
    /// в `.rpyc` не встречаются (см. отчёт).
    fn reduce_builtin(
        &mut self,
        kind: ClassKind,
        argv: &[Ref],
    ) -> Result<Ref, RpycError> {
        match kind {
            ClassKind::Builtin(BuiltinKind::Set)
            | ClassKind::Builtin(BuiltinKind::Frozenset) => {
                let items = match argv.len() {
                    0 => Vec::new(),
                    1 => match self.store.nodes.get(argv[0]) {
                        Some(Node::List(v))
                        | Some(Node::Tuple(v))
                        | Some(Node::Set(v)) => v.clone(),
                        _ => {
                            return Err(Self::fail_unsafe(
                                "REDUCE set от не-коллекции",
                            ));
                        }
                    },
                    _ => {
                        return Err(Self::fail_unsafe(
                            "REDUCE set с лишними аргументами",
                        ));
                    }
                };
                Ok(self.store.push(Node::Set(items))?)
            }
            ClassKind::Builtin(BuiltinKind::Bytearray) => {
                let bytes = match argv.len() {
                    0 => Vec::new(),
                    1 => match self.store.nodes.get(argv[0]) {
                        Some(Node::Bytes(b)) => b.clone(),
                        _ => {
                            return Err(Self::fail_unsafe(
                                "REDUCE bytearray от не-байтов",
                            ));
                        }
                    },
                    _ => {
                        return Err(Self::fail_unsafe(
                            "REDUCE bytearray с лишними аргументами",
                        ));
                    }
                };
                Ok(self.store.push(Node::Bytearray(bytes))?)
            }
            _ => Err(Self::fail_unsafe("REDUCE от builtins запрещён")),
        }
    }

    /// `copyreg._reconstructor(cls, base, state?)`: создать без `__init__`.
    fn reconstruct(&mut self, argv: &[Ref]) -> Result<Ref, RpycError> {
        if argv.len() < 2 {
            return Err(Self::fail_decode("_reconstructor без базы"));
        }
        let cls_ref = argv[0];
        let cls = match self.store.nodes.get(cls_ref) {
            Some(Node::Class(i)) => self.store.classes.get(*i).cloned(),
            _ => {
                return Err(Self::fail_unsafe(
                    "_reconstructor не от класса",
                ));
            }
        };
        let Some(cls) = cls else {
            return Err(Self::fail_decode("_reconstructor: нет класса"));
        };
        let base_kind = match self.store.nodes.get(argv[1]) {
            Some(Node::Class(i)) => match self.store.classes.get(*i) {
                Some(c) => Some(c.kind),
                None => None,
            },
            _ => None,
        };
        let state = argv.get(2).copied();
        let state_is_none = match state {
            None => true,
            Some(s) => matches!(self.store.nodes.get(s), Some(Node::None)),
        };
        match (cls.kind, base_kind) {
            // str-подкласс из протоколов 0/1: (cls, str/unicode, значение).
            (ClassKind::StrLike, Some(ClassKind::Builtin(BuiltinKind::Str))) => {
                let s = match state {
                    Some(st) => py_str_of(&self.store.nodes, st)?,
                    None => String::new(),
                };
                Ok(self.store.push(Node::PyStr(s))?)
            }
            (ClassKind::DictSub, Some(ClassKind::Builtin(BuiltinKind::Dict))) => {
                if !state_is_none {
                    return Err(Self::fail_decode(
                        "_reconstructor dict с состоянием",
                    ));
                }
                Ok(self.store.push(Node::Dict(DictData::default()))?)
            }
            (ClassKind::Plain, _) if state_is_none => {
                let ci = self.class_index(cls_ref)?;
                Ok(self.store.push(Node::Object {
                    class: ci,
                    attrs: Vec::new(),
                })?)
            }
            _ => Err(Self::fail_unsafe(
                "_reconstructor: неизвестная связка",
            )),
        }
    }

    fn class_index(&self, r: Ref) -> Result<usize, RpycError> {
        match self.store.nodes.get(r) {
            Some(Node::Class(i)) => Ok(*i),
            _ => Err(Self::fail_decode("ожидался класс")),
        }
    }

    /// Вызов mock-конструктора `cls(*args)`: как `__new__`/`__init__`
    /// mock-классов эталона — ничего не выполняет, форму сохраняет.
    fn construct(
        &mut self,
        cls_ref: Ref,
        args: &[Ref],
    ) -> Result<Ref, RpycError> {
        let ci = self.class_index(cls_ref)?;
        let kind = self
            .store
            .classes
            .get(ci)
            .ok_or_else(|| Self::fail_decode("нет класса"))?
            .kind;
        match kind {
            // Обычный mock и `_codecs.encode`: вызов ничего не делает.
            ClassKind::Plain | ClassKind::CodecEncode => {
                Ok(self.store.push(Node::Object {
                    class: ci,
                    attrs: Vec::new(),
                })?)
            }
            ClassKind::StrLike => {
                // `_MockPyExpr.__new__(cls, source?)`: значение — первый
                // аргумент как `str()` (в AST это python-код, не текст).
                let s = match args.first() {
                    None => String::new(),
                    Some(a) => py_str_of(&self.store.nodes, *a)?,
                };
                Ok(self.store.push(Node::PyStr(s))?)
            }
            ClassKind::AstsupportExpr => {
                // `_PyExpr.__init__`: `source = args[0] if args else ""`.
                let s = match args.first() {
                    Some(first) => py_str_of(&self.store.nodes, *first)?,
                    None => String::new(),
                };
                let src_ref = self.store.push(Node::Str(s))?;
                Ok(self.store.push(Node::Object {
                    class: ci,
                    attrs: vec![("source".to_string(), src_ref)],
                })?)
            }
            ClassKind::PyCode => {
                // У `_PyCode` нет своих `__new__`/`__init__`: с аргументами
                // `object.__init__` падает — как и здесь.
                if !args.is_empty() {
                    return Err(Self::fail_decode(
                        "PyCode с аргументами",
                    ));
                }
                Ok(self.store.push(Node::Object {
                    class: ci,
                    attrs: Vec::new(),
                })?)
            }
            ClassKind::DictSub => {
                if !args.is_empty() {
                    return Err(Self::fail_unsafe(
                        "DictSub с аргументами",
                    ));
                }
                Ok(self.store.push(Node::Dict(DictData::default()))?)
            }
            ClassKind::Builtin(k) => self.construct_builtin(k, args),
            ClassKind::NewObj | ClassKind::Reconstructor => {
                Err(Self::fail_unsafe("вызов copyreg напрямую"))
            }
        }
    }

    /// `cls.__new__(cls, *args)` для безопасных builtins: пустое или
    /// скаляр для `str`/`bytes` (дальше добьют `BUILD`/`APPENDS`).
    fn construct_builtin(
        &mut self,
        kind: BuiltinKind,
        args: &[Ref],
    ) -> Result<Ref, RpycError> {
        if args.is_empty() {
            let node = match kind {
                BuiltinKind::List => Node::List(Vec::new()),
                BuiltinKind::Dict => Node::Dict(DictData::default()),
                BuiltinKind::Tuple => Node::Tuple(Vec::new()),
                BuiltinKind::Set | BuiltinKind::Frozenset => {
                    Node::Set(Vec::new())
                }
                BuiltinKind::Str => Node::Str(String::new()),
                BuiltinKind::Int => Node::Int(IntVal::Small(0)),
                BuiltinKind::Float => Node::Float(0.0),
                BuiltinKind::Bool => Node::Bool(false),
                BuiltinKind::Bytes | BuiltinKind::Bytearray => {
                    Node::Bytes(Vec::new())
                }
                BuiltinKind::Complex => {
                    return Err(Self::fail_unsafe("complex не строим"));
                }
            };
            return Ok(self.store.push(node)?);
        }
        if args.len() == 1 {
            match kind {
                BuiltinKind::Str => {
                    let s = py_str_of(&self.store.nodes, args[0])?;
                    return Ok(self.store.push(Node::Str(s))?);
                }
                BuiltinKind::Bytes | BuiltinKind::Bytearray => {
                    // `bytes(str)` без кодировки в Python падает;
                    // `bytes(int)` даёт нули — hostile-форма, отказываем.
                    return Err(Self::fail_unsafe("bytes с аргументом"));
                }
                _ => {}
            }
        }
        Err(Self::fail_unsafe("builtin с аргументами"))
    }

    /// `BUILD`: применить `state` к `inst`.
    ///
    /// Точь-в-точь `load_build`: у кого есть `__setstate__` (только
    /// `_PyCode`) — вызвать; иначе разложить `(state, slotstate)`,
    /// словари — в `__dict__`/атрибуты. У скаляров и контейнеров
    /// `__dict__` нет — непустое состояние для них ошибка (как
    /// `AttributeError` в Python).
    fn op_build(&mut self) -> Result<(), RpycError> {
        let state = self.pop()?;
        let inst = self.top()?;
        // Виды — копируемые, дальше можно брать &mut.
        let inst_is_pycode = matches!(
            self.store.nodes.get(inst),
            Some(Node::Object { class, .. })
                if matches!(
                    self.store.classes.get(*class),
                    Some(c) if c.kind == ClassKind::PyCode
                )
        );
        // 1) `__setstate__` — только у PyCode-объектов.
        if inst_is_pycode {
            apply_pycodestate(&mut self.store, inst, state)?;
            return Ok(());
        }
        // 2) разложить (state, slotstate).
        let (plain, split) = match self.store.nodes.get(state) {
            Some(Node::Tuple(items)) if items.len() == 2 => {
                (None, Some((items[0], items[1])))
            }
            _ => (Some(state), None),
        };
        // Обычное состояние: ложное — пропуск, словарь — в атрибуты.
        if let Some(s) = plain {
            if node_truthy(&self.store.nodes, s) {
                merge_dict_attrs(&mut self.store, inst, s)?;
            }
        } else if let Some((a, _)) = split {
            if node_truthy(&self.store.nodes, a) {
                merge_dict_attrs(&mut self.store, inst, a)?;
            }
        }
        if let Some((_, b)) = split {
            if node_truthy(&self.store.nodes, b) {
                merge_slot_attrs(&mut self.store, inst, b)?;
            }
        }
        Ok(())
    }
}

// ── истинность (как `if state:` в Python) ──

/// Истинность узла: у контейнеров — непустота, у словаря — только контент
/// (`__dict__`-атрибуты не считаются, как `len()` у `dict`-подкласса),
/// объекты и классы — всегда истина (нет `__bool__`/`__len__`).
pub(crate) fn node_truthy(nodes: &[Node], r: Ref) -> bool {
    match nodes.get(r) {
        None => false,
        Some(Node::None) => false,
        Some(Node::Bool(b)) => *b,
        Some(Node::Int(IntVal::Small(i))) => *i != 0,
        Some(Node::Int(IntVal::BigLe(bytes))) => bytes.iter().any(|&b| b != 0),
        Some(Node::Int(IntVal::BigDec(s))) => {
            s.chars().any(|c| c != '0' && c != '-' && c != '+')
        }
        Some(Node::Float(f)) => *f != 0.0,
        Some(Node::Str(s)) | Some(Node::PyStr(s)) => !s.is_empty(),
        Some(Node::Bytes(b)) | Some(Node::Bytearray(b)) => !b.is_empty(),
        Some(Node::List(items))
        | Some(Node::Tuple(items))
        | Some(Node::Set(items)) => !items.is_empty(),
        Some(Node::Dict(d)) => !d.items.is_empty(),
        Some(Node::Class(_)) => true,
        Some(Node::Object { .. }) => true,
    }
}

// ── словари: вставка, слияние, равенство ключей ──

/// Вставить пару с семантикой `dict`: равный ключ заменяется
/// (как `d[k] = v` в Python — важен для `_show_text_parts`, который идёт
/// по значениям: дубли не должны двоиться).
///
/// Двухфазная (поиск shared, запись exclusive): равенство ключей читает
/// ту же арену, куда пишем.
fn dict_insert(store: &mut Store, dict_ref: Ref, key: Ref, value: Ref) {
    let pos = {
        let nodes = &store.nodes;
        let items = match &nodes[dict_ref] {
            Node::Dict(d) => &d.items,
            _ => return,
        };
        items
            .iter()
            .position(|(k, _)| *k == key || nodes_equal(nodes, *k, key))
    };
    let dict = match &mut store.nodes[dict_ref] {
        Node::Dict(d) => d,
        _ => return,
    };
    match pos {
        Some(i) => dict.items[i].1 = value,
        None => dict.items.push((key, value)),
    }
}

/// Собрать словарь из плоского списка `pop_mark` (опкоды `DICT`).
fn pairs_to_dict(
    items: Vec<Ref>,
    nodes: &[Node],
) -> Result<DictData, RpycError> {
    if items.len() % 2 != 0 {
        return Err(RpycError::Decode(
            "pickle: DICT с нечётным числом".to_string(),
        ));
    }
    let mut dict = DictData::default();
    let mut i = 0;
    while i < items.len() {
        // Локальная вставка без &mut Store (узлы только читаем).
        let (key, value) = (items[i], items[i + 1]);
        let pos = dict
            .items
            .iter()
            .position(|(k, _)| *k == key || nodes_equal(nodes, *k, key));
        match pos {
            Some(p) => dict.items[p].1 = value,
            None => dict.items.push((key, value)),
        }
        i += 2;
    }
    Ok(dict)
}

/// Равенство ключей словаря (как `==` + identity-shortcut Python).
/// Нехешируемые (списки, словари, множества) — отказ: в Python такой ключ
/// роняет весь unpickle с `TypeError`.
fn nodes_equal(nodes: &[Node], a: Ref, b: Ref) -> bool {
    if a == b {
        return true; // identity-shortcut (важен для nan-ключей)
    }
    match (nodes.get(a), nodes.get(b)) {
        (Some(Node::None), Some(Node::None)) => true,
        (Some(Node::Bool(x)), Some(Node::Bool(y))) => x == y,
        (Some(Node::Str(x)), Some(Node::Str(y)))
        | (Some(Node::Str(x)), Some(Node::PyStr(y)))
        | (Some(Node::PyStr(x)), Some(Node::Str(y)))
        | (Some(Node::PyStr(x)), Some(Node::PyStr(y))) => x == y,
        (Some(Node::Bytes(x)), Some(Node::Bytes(y)))
        | (Some(Node::Bytearray(x)), Some(Node::Bytearray(y))) => x == y,
        // `bytearray(b"a") == b"a"` — истина и в Python.
        (Some(Node::Bytes(x)), Some(Node::Bytearray(y)))
        | (Some(Node::Bytearray(x)), Some(Node::Bytes(y))) => x == y,
        (Some(Node::Int(x)), Some(Node::Int(y))) => int_equal(x, y),
        // `True == 1`, `1.0 == 1`: числовое равенство через границы.
        (Some(Node::Bool(x)), Some(Node::Int(y))) => {
            int_equal(&IntVal::Small(*x as i64), y)
        }
        (Some(Node::Int(x)), Some(Node::Bool(y))) => {
            int_equal(x, &IntVal::Small(*y as i64))
        }
        (Some(Node::Float(x)), Some(Node::Float(y))) => x == y,
        (Some(Node::Float(f)), Some(Node::Int(i)))
        | (Some(Node::Int(i)), Some(Node::Float(f))) => {
            float_int_equal(*f, i)
        }
        (Some(Node::Float(f)), Some(Node::Bool(b)))
        | (Some(Node::Bool(b)), Some(Node::Float(f))) => {
            float_int_equal(*f, &IntVal::Small(*b as i64))
        }
        (Some(Node::Tuple(x)), Some(Node::Tuple(y))) => {
            x.len() == y.len()
                && x.iter().zip(y.iter()).all(|(p, q)| nodes_equal(nodes, *p, *q))
        }
        // Классы и экземпляры хешируются по идентичности (уже проверена
        // выше как `a == b`): разные объекты — разные ключи.
        (Some(Node::Class(_)), _) | (_, Some(Node::Class(_))) => false,
        (Some(Node::Object { .. }), _) | (_, Some(Node::Object { .. })) => {
            false
        }
        // Списки/словари/множества нехешируемы — в Python здесь TypeError.
        // Проверяем явным отказом выше по стеку нельзя (нет контекста),
        // поэтому считаем неравными: такой ключ всё равно почти наверняка
        // обернётся ошибкой позже. (См. примечание в отчёте.)
        _ => false,
    }
}

fn int_equal(a: &IntVal, b: &IntVal) -> bool {
    match (a, b) {
        (IntVal::Small(x), IntVal::Small(y)) => x == y,
        (IntVal::BigLe(x), IntVal::BigLe(y)) => x == y,
        (IntVal::BigDec(x), IntVal::BigDec(y)) => x == y,
        (IntVal::Small(x), IntVal::BigDec(y))
        | (IntVal::BigDec(y), IntVal::Small(x)) => {
            format!("{x}") == *y
        }
        // LE-байты против десятичных: точное сравнение требует bignum;
        // такие ключи в AST не встречаются (см. отчёт) — считаем разными.
        _ => false,
    }
}

/// Точное `float == int` (как Python: `1.0 == 1`, `1e300 != 10**300`).
fn float_int_equal(f: f64, i: &IntVal) -> bool {
    if !f.is_finite() {
        return false;
    }
    match i {
        IntVal::Small(v) => {
            // Целое и влезло в точный диапазон double.
            f.fract() == 0.0 && f >= -9.007_199_254_740_992e15
                && f <= 9.007_199_254_740_992e15
                && f as i64 == *v
        }
        _ => false,
    }
}

// ── BUILD-слияния ──

/// Имя строкового ключа атрибута (`str`; не-`str` — см. вызывающих).
fn attr_name(nodes: &[Node], key: Ref) -> Option<String> {
    match nodes.get(key) {
        Some(Node::Str(s)) | Some(Node::PyStr(s)) => Some(s.clone()),
        _ => None,
    }
}

/// `state.items()` в `__dict__`: не-словарь — `AttributeError` (здесь Err),
/// не-`str` ключи в `__dict__` допустимы и дальше невидимы (обход читает
/// атрибуты только по строковым именам) — пропускаем.
fn merge_dict_attrs(
    store: &mut Store,
    inst: Ref,
    state: Ref,
) -> Result<(), RpycError> {
    let items = match store.nodes.get(state) {
        Some(Node::Dict(d)) => d.items.clone(),
        _ => {
            return Err(RpycError::Decode(
                "pickle: BUILD-состояние не словарь".to_string(),
            ));
        }
    };
    set_attrs(store, inst, &items, false)
}

/// `slotstate`: `setattr` — здесь не-`str` ключ ошибка (как `TypeError`).
fn merge_slot_attrs(
    store: &mut Store,
    inst: Ref,
    state: Ref,
) -> Result<(), RpycError> {
    let items = match store.nodes.get(state) {
        Some(Node::Dict(d)) => d.items.clone(),
        _ => {
            return Err(RpycError::Decode(
                "pickle: BUILD-слотсостояние не словарь".to_string(),
            ));
        }
    };
    set_attrs(store, inst, &items, true)
}

/// Записать атрибуты: объект и словарь (`__dict__`) — можно, остальным
/// `setattr` запрещён (как `AttributeError` в Python) — отказ.
///
/// `PyStr` (`str`-подкласс без `__slots__`, словарь есть): состояние
/// применяется, но дальше не читается — обход у строк берёт только
/// значение, `getattr` по строкам не ходит. Значения слотов отбрасываем
/// (в Python они осели бы в `__dict__` экземпляра и тоже ни на что
/// не повлияли бы), не-`str` ключ при `strict` — отказ (как `TypeError`
/// у `setattr`), иначе — пропуск (как не-`str` ключ `__dict__`, который
/// обход по именам никогда не видит).
fn set_attrs(
    store: &mut Store,
    inst: Ref,
    items: &[(Ref, Ref)],
    strict_keys: bool,
) -> Result<(), RpycError> {
    let is_pystore = matches!(
        store.nodes.get(inst),
        Some(Node::Object { .. }) | Some(Node::Dict(_))
    );
    let is_pystr =
        matches!(store.nodes.get(inst), Some(Node::PyStr(_)));
    if !is_pystore && !is_pystr {
        return Err(RpycError::Decode(
            "pickle: BUILD не в объект".to_string(),
        ));
    }
    // Фаза 1: имена (shared).
    let mut named: Vec<(String, Ref)> = Vec::with_capacity(items.len());
    for (k, v) in items {
        match attr_name(&store.nodes, *k) {
            Some(n) => named.push((n, *v)),
            None if strict_keys => {
                return Err(RpycError::Decode(
                    "pickle: setattr с не-строковым именем".to_string(),
                ));
            }
            None => continue,
        }
    }
    if is_pystr {
        // Невидимы для обхода — отбрасываем (см. выше).
        return Ok(());
    }
    // Фаза 2: запись (exclusive).
    match &mut store.nodes[inst] {
        Node::Object { attrs, .. } => {
            for (name, v) in named {
                set_attr_vec(attrs, name, v);
            }
        }
        Node::Dict(d) => {
            for (name, v) in named {
                set_attr_vec(&mut d.attrs, name, v);
            }
        }
        _ => unreachable!("проверено выше"),
    }
    Ok(())
}

fn set_attr_vec(attrs: &mut Vec<(String, Ref)>, name: String, value: Ref) {
    for (k, v) in attrs.iter_mut() {
        if *k == name {
            *v = value;
            return;
        }
    }
    attrs.push((name, value));
}

/// `__setstate__` `_PyCode`: `state[i]` для
/// `(version, source, location, mode, py, hashcode, col_offset)`.
fn apply_pycodestate(
    store: &mut Store,
    inst: Ref,
    state: Ref,
) -> Result<(), RpycError> {
    let items = match store.nodes.get(state) {
        Some(Node::Tuple(items)) | Some(Node::List(items)) => items.clone(),
        _ => {
            return Err(RpycError::Decode(
                "pickle: PyCode-состояние не кортеж".to_string(),
            ));
        }
    };
    const ATTRS: [&str; 7] = [
        "version",
        "source",
        "location",
        "mode",
        "py",
        "hashcode",
        "col_offset",
    ];
    // `source` по умолчанию `""`, остальное — `None` (как в эталоне).
    let none_ref = store.push(Node::None)?;
    let mut attrs: Vec<(String, Ref)> = Vec::new();
    for (i, name) in ATTRS.iter().enumerate() {
        let r = items.get(i).copied().unwrap_or(none_ref);
        attrs.push((name.to_string(), r));
    }
    // `source` не-строка: `getattr(source, "source", str(source))`.
    let src_ref = attrs[1].1;
    let src_is_str = matches!(
        store.nodes.get(src_ref),
        Some(Node::Str(_)) | Some(Node::PyStr(_))
    );
    if !src_is_str {
        let replacement = match store.nodes.get(src_ref) {
            Some(Node::Object { attrs: inner, .. }) => {
                let found = inner
                    .iter()
                    .find(|(k, _)| k == "source")
                    .map(|(_, v)| *v);
                match found {
                    Some(f)
                        if matches!(
                            store.nodes.get(f),
                            Some(Node::Str(_)) | Some(Node::PyStr(_))
                        ) =>
                    {
                        Some(f)
                    }
                    _ => None,
                }
            }
            _ => None,
        };
        match replacement {
            Some(f) => attrs[1].1 = f,
            None => match py_str_of(&store.nodes, src_ref) {
                Ok(s) => {
                    let r = store.push(Node::Str(s))?;
                    attrs[1].1 = r;
                }
                Err(_) => attrs[1].1 = none_ref,
            },
        }
    }
    match &mut store.nodes[inst] {
        Node::Object { attrs: slot, .. } => *slot = attrs,
        _ => {
            return Err(RpycError::Decode(
                "pickle: PyCode не объект".to_string(),
            ));
        }
    }
    Ok(())
}

// ── `str()` для скаляров (конструкторы str-подклассов) ──

/// Эквивалент `str(x)` для скалярных узлов (первый аргумент `PyExpr`).
/// Составные и классы — отказ (в Python там был бы `repr`, который обход
/// всё равно не читает; такие формы в `.rpyc` не встречаются).
fn py_str_of(nodes: &[Node], r: Ref) -> Result<String, RpycError> {
    match nodes.get(r) {
        Some(Node::Str(s)) | Some(Node::PyStr(s)) => Ok(s.clone()),
        Some(Node::Bytes(b)) => {
            Ok(String::from_utf8_lossy(b).into_owned())
        }
        Some(Node::None) => Ok("None".to_string()),
        Some(Node::Bool(b)) => Ok(if *b { "True" } else { "False" }.to_string()),
        Some(Node::Int(IntVal::Small(i))) => Ok(format!("{i}")),
        Some(Node::Int(IntVal::BigDec(s))) => Ok(s.clone()),
        Some(Node::Int(IntVal::BigLe(bytes))) => {
            // Точное десятичное требует bignum; в конструкторах такие
            // числа не встречаются — честный отказ вместо вранья.
            let _ = bytes;
            Err(RpycError::Decode(
                "pickle: str() от длинного LE-целого".to_string(),
            ))
        }
        Some(Node::Float(f)) => Ok(py_repr_float(*f)),
        _ => Err(RpycError::Decode(
            "pickle: str() от составного".to_string(),
        )),
    }
}

/// `repr(float)`: кратчайшее round-trip, как в Python (`1e+16`, `3.0`).
fn py_repr_float(f: f64) -> String {
    if f.is_nan() {
        return "nan".to_string();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf" } else { "-inf" }.to_string();
    }
    let mut s = format!("{f}");
    if let Some(e) = s.find('e') {
        // Rust: `1e16`, Python: `1e+16`.
        if !s[e + 1..].starts_with(['+', '-']) {
            s.insert(e + 1, '+');
        }
        return s;
    }
    if !s.contains('.') {
        s.push_str(".0");
    }
    s
}

// ── скалярные разборы ──

/// Целое из линии `INT` (байты БЕЗ `\n` — сравнение `00`/`01` идёт
/// по сырой линии С `\n`, как `data == FALSE[1:]` в Python).
fn parse_int_line(line: &[u8]) -> Result<Node, RpycError> {
    if line == b"00\n" {
        return Ok(Node::Bool(false));
    }
    if line == b"01\n" {
        return Ok(Node::Bool(true));
    }
    let s = line.strip_suffix(b"\n").unwrap_or(line);
    parse_c_int(s)
}

/// Правила C-unpickler (`Modules/_pickle.c`): `0x`/`0o`/`0b`, legacy
/// `0`-octal (`010` → 8, `08` — ошибка), иначе decimal. Пробелы по краям
/// можно, `_` нельзя, суффикс `L` нельзя.
fn parse_c_int(s: &[u8]) -> Result<Node, RpycError> {
    let t = trim_ascii_ws(s);
    if t.is_empty() {
        return Err(RpycError::Decode(
            "pickle: пустой INT".to_string(),
        ));
    }
    let (neg, rest) = match t.first() {
        Some(b'-') => (true, &t[1..]),
        Some(b'+') => (false, &t[1..]),
        _ => (false, t),
    };
    if rest.is_empty() {
        return Err(RpycError::Decode("pickle: INT без цифр".to_string()));
    }
    let (base, digits) = if rest.len() > 2
        && rest[0] == b'0'
        && (rest[1] == b'x' || rest[1] == b'X')
    {
        (16u32, &rest[2..])
    } else if rest.len() > 2 && rest[0] == b'0' && (rest[1] == b'o' || rest[1] == b'O') {
        (8u32, &rest[2..])
    } else if rest.len() > 2 && rest[0] == b'0' && (rest[1] == b'b' || rest[1] == b'B') {
        (2u32, &rest[2..])
    } else if rest.len() > 1 && rest[0] == b'0' {
        (8u32, &rest[1..])
    } else {
        (10u32, rest)
    };
    if digits.is_empty() || !digits.iter().all(|c| digit_val(*c, base).is_some()) {
        return Err(RpycError::Decode("pickle: мусор в INT".to_string()));
    }
    if digits.len() > MAX_INT_DIGITS {
        let mut norm = normalize_dec(digits);
        if neg {
            norm = format!("-{norm}");
        }
        return Ok(Node::Int(IntVal::BigDec(norm)));
    }
    let mut acc: i128 = 0;
    for c in digits {
        acc = acc * base as i128 + digit_val(*c, base).expect("проверено") as i128;
    }
    if neg {
        acc = -acc;
    }
    match i64::try_from(acc) {
        Ok(v) => Ok(Node::Int(IntVal::Small(v))),
        Err(_) => {
            let mut norm = normalize_dec(digits);
            if neg {
                norm = format!("-{norm}");
            }
            Ok(Node::Int(IntVal::BigDec(norm)))
        }
    }
}

/// Линия `LONG`: один trailing-`L` снять, дальше `int(x, 0)`
/// (без legacy-octal: `010` — ошибка; `_` между цифрами можно).
fn parse_long_line(line: &[u8]) -> Result<Node, RpycError> {
    let mut s = line.strip_suffix(b"\n").unwrap_or(line);
    if s.last() == Some(&b'L') {
        s = &s[..s.len() - 1];
    }
    let t = trim_ascii_ws(s);
    if t.is_empty() {
        return Err(RpycError::Decode("pickle: пустой LONG".to_string()));
    }
    let (neg, rest) = match t.first() {
        Some(b'-') => (true, &t[1..]),
        Some(b'+') => (false, &t[1..]),
        _ => (false, t),
    };
    if rest.is_empty() {
        return Err(RpycError::Decode("pickle: LONG без цифр".to_string()));
    }
    let (base, mut digits) = if rest.len() > 2
        && rest[0] == b'0'
        && (rest[1] == b'x' || rest[1] == b'X')
    {
        (16u32, &rest[2..])
    } else if rest.len() > 2 && rest[0] == b'0' && (rest[1] == b'o' || rest[1] == b'O') {
        (8u32, &rest[2..])
    } else if rest.len() > 2 && rest[0] == b'0' && (rest[1] == b'b' || rest[1] == b'B') {
        (2u32, &rest[2..])
    } else {
        (10u32, rest)
    };
    // `_` — только между цифрами (как в литералах Python).
    let mut clean: Vec<u8> = Vec::with_capacity(digits.len());
    let mut prev_underscore = true; // ведущий `_` запрещён
    for c in digits {
        if *c == b'_' {
            if prev_underscore {
                return Err(RpycError::Decode(
                    "pickle: мусор в LONG".to_string(),
                ));
            }
            prev_underscore = true;
            continue;
        }
        if digit_val(*c, base).is_none() {
            return Err(RpycError::Decode("pickle: мусор в LONG".to_string()));
        }
        prev_underscore = false;
        clean.push(*c);
    }
    if prev_underscore || clean.is_empty() {
        return Err(RpycError::Decode("pickle: мусор в LONG".to_string()));
    }
    // Ведущий ноль у decimal без префикса — ошибка (как `int(x, 0)`).
    if base == 10 && clean.len() > 1 && clean[0] == b'0' {
        return Err(RpycError::Decode("pickle: мусор в LONG".to_string()));
    }
    digits = &clean;
    if digits.len() > MAX_INT_DIGITS {
        let mut norm = normalize_dec(digits);
        if neg {
            norm = format!("-{norm}");
        }
        return Ok(Node::Int(IntVal::BigDec(norm)));
    }
    let mut acc: i128 = 0;
    for c in digits {
        acc = acc * base as i128 + digit_val(*c, base).expect("проверено") as i128;
    }
    if neg {
        acc = -acc;
    }
    match i64::try_from(acc) {
        Ok(v) => Ok(Node::Int(IntVal::Small(v))),
        Err(_) => {
            let mut norm = normalize_dec(digits);
            if neg {
                norm = format!("-{norm}");
            }
            Ok(Node::Int(IntVal::BigDec(norm)))
        }
    }
}

fn digit_val(c: u8, base: u32) -> Option<u32> {
    let v = match c {
        b'0'..=b'9' => (c - b'0') as u32,
        b'a'..=b'f' => (c - b'a' + 10) as u32,
        b'A'..=b'F' => (c - b'A' + 10) as u32,
        _ => return None,
    };
    if v < base { Some(v) } else { None }
}

/// Нормализованная десятичная строка (без ведущих нулей, `-0` → `0`).
fn normalize_dec(digits: &[u8]) -> String {
    let s = digits.iter().skip_while(|c| **c == b'0').collect::<Vec<_>>();
    if s.is_empty() {
        return "0".to_string();
    }
    s.into_iter().map(|c| *c as char).collect()
}

fn trim_ascii_ws(s: &[u8]) -> &[u8] {
    const WS: [u8; 6] = [b' ', b'\t', b'\n', b'\r', 0x0b, 0x0c];
    let mut a = 0;
    let mut b = s.len();
    while a < b && WS.contains(&s[a]) {
        a += 1;
    }
    while b > a && WS.contains(&s[b - 1]) {
        b -= 1;
    }
    &s[a..b]
}

/// Линия `FLOAT`: `float()` Python (`inf`/`nan` в любом регистре,
/// пробелы можно, `_` нельзя — `FromStr` их тоже не ест).
fn parse_float_line(s: &[u8]) -> Result<f64, RpycError> {
    let t = trim_ascii_ws(s);
    if t.is_empty() || t.len() > MAX_STR {
        return Err(RpycError::Decode("pickle: пустой FLOAT".to_string()));
    }
    let text = std::str::from_utf8(t)
        .map_err(|_| RpycError::Decode("pickle: FLOAT не ASCII".to_string()))?;
    text.parse::<f64>().map_err(|_| {
        RpycError::Decode("pickle: мусор в FLOAT".to_string())
    })
}

/// `LONG1`/`LONG4`: LE two's complement (`decode_long`). Пусто → 0.
fn decode_long_le(bytes: &[u8]) -> Result<IntVal, RpycError> {
    if bytes.len() > MAX_BIGINT_BYTES {
        return Err(RpycError::TooBig(format!(
            "pickle: LONG длинее {MAX_BIGINT_BYTES} байт"
        )));
    }
    if bytes.is_empty() {
        return Ok(IntVal::Small(0));
    }
    if bytes.len() <= 8 {
        let mut buf = [0u8; 8];
        buf[..bytes.len()].copy_from_slice(bytes);
        // Знаковое расширение из младших байтов.
        let neg = bytes[bytes.len() - 1] & 0x80 != 0;
        if neg {
            for b in buf.iter_mut().take(8).skip(bytes.len()) {
                *b = 0xff;
            }
        }
        return Ok(IntVal::Small(i64::from_le_bytes(buf)));
    }
    Ok(IntVal::BigLe(bytes.to_vec()))
}

/// Линия `PUT`/`GET`: десятичный номер мемои (знак `int()` терпим,
/// но отрицательный `PUT` — ошибка, как в Python).
fn parse_memo_line(s: &[u8]) -> Result<u64, RpycError> {
    let t = trim_ascii_ws(s);
    if t.is_empty() || t.len() > 20 {
        return Err(RpycError::Decode(
            "pickle: мусор в номере мемои".to_string(),
        ));
    }
    let text = std::str::from_utf8(t)
        .map_err(|_| RpycError::Decode("pickle: мемои не ASCII".to_string()))?;
    if text.starts_with('-') {
        return Err(RpycError::Decode(
            "pickle: отрицательный номер мемои".to_string(),
        ));
    }
    let v: u64 = text.trim_start_matches('+').parse().map_err(|_| {
        RpycError::Decode("pickle: мусор в номере мемои".to_string())
    })?;
    Ok(v)
}

// ── строковые декодеры ──

/// Строгий ASCII (кодировка unpickler по умолчанию: `ASCII/strict`).
/// Ошибка — как `UnicodeDecodeError`, роняющий весь unpickle.
fn decode_ascii(bytes: &[u8]) -> Result<String, RpycError> {
    if bytes.len() > MAX_STR {
        return Err(RpycError::TooBig(
            "pickle: строка длиннее лимита".to_string(),
        ));
    }
    if bytes.is_ascii() {
        // ASCII — валидный UTF-8 всегда.
        Ok(String::from_utf8(bytes.to_vec()).expect("ASCII"))
    } else {
        Err(RpycError::Decode(
            "pickle: не-ASCII в ASCII-строке".to_string(),
        ))
    }
}

/// Строгий UTF-8 (`surrogatepass` в Python принял бы CESU-8 суррогаты —
/// их Rust-строка держать не может: честный отказ, см. отчёт).
fn decode_utf8(bytes: &[u8]) -> Result<String, RpycError> {
    if bytes.len() > MAX_STR {
        return Err(RpycError::TooBig(
            "pickle: строка длиннее лимита".to_string(),
        ));
    }
    String::from_utf8(bytes.to_vec())
        .map_err(|_| RpycError::Decode("pickle: битый UTF-8".to_string()))
}

/// `raw-unicode-escape` для опкода `UNICODE`: `\\uXXXX`/`\\UXXXXXXXX`,
/// остальное (`\\x`, `\\n`, `\\d`, не-ASCII байты как latin-1) — буквально.
fn decode_raw_unicode_escape(bytes: &[u8]) -> Result<String, RpycError> {
    if bytes.len() > MAX_STR {
        return Err(RpycError::TooBig(
            "pickle: строка длиннее лимита".to_string(),
        ));
    }
    let mut out = String::new();
    let mut i = 0;
    while i < bytes.len() {
        let c = bytes[i];
        if c != b'\\' {
            // Сырые байты ≥ 0x80: latin-1 (проверено зондом на CPython:
            // `str(b"\\xe9", ...)` оставляет как есть — для однобайтовых
            // это совпадает с latin-1).
            out.push(c as char);
            i += 1;
            continue;
        }
        let e = bytes.get(i + 1).copied();
        match e {
            Some(b'u') => {
                let hex = bytes.get(i + 2..i + 6).ok_or_else(|| {
                    RpycError::Decode(
                        "pickle: обрезанный \\uXXXX".to_string(),
                    )
                })?;
                let cp = hex_val4(hex)?;
                match char::from_u32(cp) {
                    Some(ch) => out.push(ch),
                    // Суррогаты: Python держит, Rust-строка — нет.
                    None => {
                        return Err(RpycError::Decode(
                            "pickle: суррогат в \\u".to_string(),
                        ));
                    }
                }
                i += 6;
            }
            Some(b'U') => {
                let hex = bytes.get(i + 2..i + 10).ok_or_else(|| {
                    RpycError::Decode(
                        "pickle: обрезанный \\UXXXXXXXX".to_string(),
                    )
                })?;
                let cp = hex_val8(hex)?;
                match char::from_u32(cp) {
                    Some(ch) => out.push(ch),
                    None => {
                        return Err(RpycError::Decode(
                            "pickle: \\U вне Unicode".to_string(),
                        ));
                    }
                }
                i += 10;
            }
            // Всё остальное — буквально (как CPython: `\\n` → `\`+`n`).
            _ => {
                out.push('\\');
                i += 1;
            }
        }
    }
    Ok(out)
}

fn hex_val4(hex: &[u8]) -> Result<u32, RpycError> {
    if hex.len() != 4 {
        return Err(RpycError::Decode("pickle: мусор в \\u".to_string()));
    }
    let mut v: u32 = 0;
    for c in hex {
        v = v * 16
            + digit_val(*c, 16).ok_or_else(|| {
                RpycError::Decode("pickle: мусор в \\u".to_string())
            })?;
    }
    Ok(v)
}

fn hex_val8(hex: &[u8]) -> Result<u32, RpycError> {
    if hex.len() != 8 {
        return Err(RpycError::Decode("pickle: мусор в \\U".to_string()));
    }
    let mut v: u32 = 0;
    for c in hex {
        v = v
            .checked_mul(16)
            .and_then(|x| {
                digit_val(*c, 16).and_then(|d| x.checked_add(d))
            })
            .ok_or_else(|| {
                RpycError::Decode("pickle: мусор в \\U".to_string())
            })?;
    }
    Ok(v)
}

/// Опкод `STRING`: снять внешние кавычки, `escape_decode`, затем ASCII.
fn parse_string_line(line: &[u8]) -> Result<String, RpycError> {
    let s = line.strip_suffix(b"\n").unwrap_or(line);
    if s.len() < 2 || s[0] != s[s.len() - 1] || (s[0] != b'"' && s[0] != b'\'')
    {
        return Err(RpycError::Decode(
            "pickle: STRING без кавычек".to_string(),
        ));
    }
    let decoded = escape_decode(&s[1..s.len() - 1])?;
    decode_ascii(&decoded)
}

/// `codecs.escape_decode`: C-escape'ы, `\\xNN`, octal `\\ooo`;
/// неизвестное (`\\d`, `\\N{...}`, `\\u...`) — буквально с backslash.
fn escape_decode(data: &[u8]) -> Result<Vec<u8>, RpycError> {
    if data.len() > MAX_STR {
        return Err(RpycError::TooBig(
            "pickle: строка длиннее лимита".to_string(),
        ));
    }
    let mut out: Vec<u8> = Vec::with_capacity(data.len());
    let mut i = 0;
    while i < data.len() {
        let c = data[i];
        if c != b'\\' {
            out.push(c);
            i += 1;
            continue;
        }
        i += 1;
        let e = match data.get(i) {
            Some(v) => *v,
            None => {
                // Висячий `\` в конце — `ValueError` у `escape_decode`.
                return Err(RpycError::Decode(
                    "pickle: висячий backslash".to_string(),
                ));
            }
        };
        match e {
            b'n' => { out.push(b'\n'); i += 1; }
            b't' => { out.push(b'\t'); i += 1; }
            b'r' => { out.push(b'\r'); i += 1; }
            b'\'' => { out.push(b'\''); i += 1; }
            b'"' => { out.push(b'"'); i += 1; }
            b'\\' => { out.push(b'\\'); i += 1; }
            b'a' => { out.push(0x07); i += 1; }
            b'b' => { out.push(0x08); i += 1; }
            b'f' => { out.push(0x0c); i += 1; }
            b'v' => { out.push(0x0b); i += 1; }
            b'x' => {
                // Короткий `\x` — `ValueError` целиком (проверено зондом),
                // а не буквальный backslash.
                match (data.get(i + 1), data.get(i + 2)) {
                    (Some(h1), Some(h2)) => {
                        match (digit_val(*h1, 16), digit_val(*h2, 16)) {
                            (Some(a), Some(b)) => {
                                out.push(a as u8 * 16 + b as u8);
                                i += 3;
                            }
                            _ => {
                                return Err(RpycError::Decode(
                                    "pickle: битый \\x".to_string(),
                                ));
                            }
                        }
                    }
                    _ => {
                        return Err(RpycError::Decode(
                            "pickle: битый \\x".to_string(),
                        ));
                    }
                }
            }
            b'0'..=b'7' => {
                let mut v: u32 = 0;
                let mut k = 0;
                while k < 3 {
                    match data.get(i + k) {
                        Some(d @ b'0'..=b'7') => {
                            v = v * 8 + (d - b'0') as u32;
                            k += 1;
                        }
                        _ => break,
                    }
                }
                out.push((v & 0xff) as u8);
                i += k;
            }
            // Неизвестное — буквально, backslash остаётся.
            _ => { out.push(b'\\'); }
        }
    }
    Ok(out)
}

// ── белый список GLOBAL ──

/// Точные имена `renpy.ast`-узлов из `_RENPY_MOCKS` (тот же список, что
/// в цикле регистрации эталона; остальное в `renpy.*` — динамические
/// `_mock_<Имя>`, как в `find_class`).
const RENPY_AST_PLAIN: [&str; 26] = [
    "Node", "Init", "Python", "Return", "Say", "Menu", "Label", "Jump",
    "Call", "If", "While", "Pass", "Show", "Scene", "Hide", "With", "Play",
    "Queue", "Pause", "Translate", "TranslateSay", "TranslateString",
    "TranslateBlock", "Define", "Default", "Screen",
];

/// Разобрать `GLOBAL`/`STACK_GLOBAL`/`INST` через белый список.
///
/// Порядок — как `find_class` эталона: сначала `_RENPY_MOCKS`, затем
/// `copyreg`, затем безопасные `builtins`, затем `renpy.*`-mock.
/// ВНИМАНИЕ — три py2-особенности эталона повторены в точности
/// (проверено зондами на CPython 3.13, см. отчёт):
/// * `copy_reg.*` (так C-pickler пишет `copyreg` при proto<2) эталон НЕ
///   мэппит, а мокает (`_mock_ext_copy_reg_*`, разбор продолжается);
/// * `__builtin__.<safe>` (list/set/…) эталон НЕ резолвит: базовый
///   `find_class` падает на `import __builtin__` (модуля нет на py3) и
///   весь unpickle уходит в `None` — здесь это `Err(Decode)`;
/// * `__builtin__.<прочее>` (`object`, `unicode`, `long`) — mock
///   (`_mock_ext___builtin___*`, разбор продолжается).
/// В `find_class` эталона НЕТ ветвления по протоколу — здесь тоже нет.
fn find_class(module: &str, name: &str) -> Result<ClassInfo, RpycError> {
    // `_codecs.encode` — см. `ClassKind::CodecEncode`.
    if module == "_codecs" && name == "encode" {
        return Ok(ClassInfo {
            module: module.to_string(),
            name: name.to_string(),
            type_name: "_mock_ext__codecs_encode".to_string(),
            kind: ClassKind::CodecEncode,
        });
    }
    // `copyreg.__newobj__/_reconstructor` — настоящие, ими unpickler
    // создаёт объекты протокола 2 (как `super().find_class` в эталоне).
    // А вот `copy_reg.*` (py2-имя при proto<2) — mock, как в эталоне.
    if module == "copyreg" {
        if name == "__newobj__" {
            return Ok(ClassInfo {
                module: module.to_string(),
                name: name.to_string(),
                type_name: "method-wrapper".to_string(),
                kind: ClassKind::NewObj,
            });
        }
        if name == "_reconstructor" {
            return Ok(ClassInfo {
                module: module.to_string(),
                name: name.to_string(),
                type_name: "function".to_string(),
                kind: ClassKind::Reconstructor,
            });
        }
        return Err(RpycError::Unsafe(format!(
            "pickle: copyreg.{name} вне белого списка"
        )));
    }
    if module == "copy_reg" {
        return Ok(mock_plain(
            module,
            name,
            &format!("_mock_ext_{module}_{name}"),
            ClassKind::Plain,
        ));
    }
    // Безопасные builtins (тот же набор, что `_SAFE_BUILTINS`).
    // `object` — тоже mock (универсальная база `_reconstructor`,
    // вызов безвреден): эталон мокает его точно так же.
    if module == "builtins" {
        if name == "object" {
            return Ok(mock_plain(
                module,
                name,
                &format!("_mock_ext_{module}_{name}"),
                ClassKind::Plain,
            ));
        }
        let kind = match name {
            "list" => BuiltinKind::List,
            "dict" => BuiltinKind::Dict,
            "tuple" => BuiltinKind::Tuple,
            "set" => BuiltinKind::Set,
            "frozenset" => BuiltinKind::Frozenset,
            "str" => BuiltinKind::Str,
            "int" => BuiltinKind::Int,
            "float" => BuiltinKind::Float,
            "bool" => BuiltinKind::Bool,
            "bytes" => BuiltinKind::Bytes,
            "bytearray" => BuiltinKind::Bytearray,
            "complex" => BuiltinKind::Complex,
            _ => {
                return Err(RpycError::Unsafe(format!(
                    "pickle: builtins.{name} вне белого списка"
                )));
            }
        };
        return Ok(ClassInfo {
            module: module.to_string(),
            name: name.to_string(),
            type_name: name.to_string(),
            kind: ClassKind::Builtin(kind),
        });
    }
    // `__builtin__` (py2-имя при proto<2): safe-имена роняют ВЕСЬ
    // unpickle (базовый find_class не может импортировать `__builtin__`
    // на py3), остальные — mock. Именно так ведёт себя эталон.
    if module == "__builtin__" {
        if matches!(
            name,
            "list" | "dict" | "tuple" | "set" | "frozenset" | "str" | "int"
                | "float" | "bool" | "bytes" | "bytearray" | "complex"
        ) {
            return Err(RpycError::Decode(format!(
                "pickle: __builtin__.{name} не резолвится на py3"
            )));
        }
        return Ok(mock_plain(
            module,
            name,
            &format!("_mock_ext_{module}_{name}"),
            ClassKind::Plain,
        ));
    }
    // Модули Ren'Py — mock-классы с произвольными атрибутами.
    if module == "renpy.ast" {
        if name == "PyExpr" {
            return Ok(mock_plain(module, name, "_MockPyExpr", ClassKind::StrLike));
        }
        if name == "PyCode" {
            return Ok(mock_plain(module, name, "_PyCode", ClassKind::PyCode));
        }
        if RENPY_AST_PLAIN.contains(&name) {
            return Ok(mock_plain(module, name, name, ClassKind::Plain));
        }
        return Ok(mock_plain(
            module,
            name,
            &format!("_mock_{name}"),
            ClassKind::Plain,
        ));
    }
    if module == "renpy.astsupport" && name == "PyExpr" {
        return Ok(mock_plain(module, name, "_PyExpr", ClassKind::AstsupportExpr));
    }
    if module == "renpy.python" && name == "RawCode" {
        return Ok(mock_plain(module, name, "_MockPyExpr", ClassKind::StrLike));
    }
    if module == "renpy.revertable" && name == "RevertableDict" {
        return Ok(mock_plain(
            module,
            name,
            "_RevertableDict",
            ClassKind::DictSub,
        ));
    }
    if module == "renpy.parameter" && name == "ArgumentInfo" {
        // Общая `_MockNode` в эталоне: `type().__name__ == "_MockNode"`.
        return Ok(mock_plain(module, name, "_MockNode", ClassKind::Plain));
    }
    if module == "renpy.sl2.slast" && name == "SLScreen" {
        return Ok(mock_plain(module, name, "_MockNode", ClassKind::Plain));
    }
    if module == "renpy" || module.starts_with("renpy.") {
        if module == "renpy" {
            return Err(RpycError::Unsafe(format!(
                "pickle: модуль {module}.{name} вне белого списка"
            )));
        }
        return Ok(mock_plain(
            module,
            name,
            &format!("_mock_{name}"),
            ClassKind::Plain,
        ));
    }
    Err(RpycError::Unsafe(format!(
        "pickle: модуль {module}.{name} вне белого списка"
    )))
}

fn mock_plain(
    module: &str,
    name: &str,
    type_name: &str,
    kind: ClassKind,
) -> ClassInfo {
    ClassInfo {
        module: module.to_string(),
        name: name.to_string(),
        type_name: type_name.to_string(),
        kind,
    }
}

