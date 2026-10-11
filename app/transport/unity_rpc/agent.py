# -*- coding: utf-8 -*-
"""Frida-агент Unity Mono: чтение и правка статических полей.

Модель (проверена на живой игре, `mono-2.0-bdwgc.dll`):

    mono_get_root_domain()                        -> MonoDomain*
    mono_image_get_table_info(img, 2)            -> таблица TYPEDEF
    mono_class_get(img, 0x02000000 | i)          -> MonoClass*
    mono_class_get_fields(kls, &iter)            -> MonoClassField* поля класса
    mono_field_get_parent(field)                 -> класс-владелец поля
    mono_class_vtable(domain, owner)             -> MonoVTable*
    mono_vtable_get_static_field_data(vt, field) -> void*  (адрес значения)

Три правила, каждое стоило реального падения — не нарушать:

1. **`NativeFunction` кэшируются.** Старый агент создавал их заново на
   каждый вызов; сборщик мусора Frida успевал убрать их посреди вызова,
   и `mono_class_vtable` падал с «system error» на КАЖДОМ классе. С
   кэшем полный обход сборки (210 классов, 1414 полей) идёт за ~5 мс и
   не падает ни разу.
2. **vtable берём у класса-владельца поля** (`mono_field_get_parent`), а
   не у класса, который перебираем, и не «по цепочке родителей» через
   угаданное смещение — vtable и поле из разных классов дают мусорный
   адрес.
3. **`mono_thread_attach` не нужен**: проверено, `mono_class_vtable`
   работает и без него. Но вызов остаётся в WANT и подстраховывается —
   дешевле, чем «system error».

Строки НЕ читаются и НЕ пишутся: в статических полях лежит текст игры,
а он наружу не отдаётся. Только примитивы и перечисления.

Наружу агент отдаёт только технические имена и числа — без игрового
текста.
"""

_HELPER_JS = r"""
(function () {
  var CANDIDATES = ['mono-2.0-bdwgc.dll', 'mono-2.0-sgen.dll', 'mono.dll'];
  var WANT = [
    // домен и сборки
    'mono_get_root_domain', 'mono_thread_attach', 'mono_thread_detach',
    'mono_assembly_foreach', 'mono_assembly_get_image', 'mono_image_get_name',
    'mono_image_get_table_info', 'mono_table_info_get_rows',
    // классы
    'mono_class_get', 'mono_class_from_name', 'mono_class_get_name',
    'mono_class_get_namespace', 'mono_class_get_fields', 'mono_class_vtable',
    'mono_class_get_parent',
    // поля
    'mono_class_get_field_from_name', 'mono_field_get_name',
    'mono_field_get_parent', 'mono_field_get_flags', 'mono_field_get_type',
    'mono_field_get_offset',
    'mono_type_get_name', 'mono_type_get_type',
    // enum -> базовый примитив
    'mono_class_from_mono_type', 'mono_class_is_enum',
    'mono_class_enum_basetype',
    // адрес значения
    'mono_vtable_get_static_field_data'
  ];

  var F = {};        // экспорты модуля
  var NF = {};       // кэш NativeFunction (обязателен, см. правило 1)
  var MODULE = null;
  var DOMAIN = null;
  var THREAD = null;
  var THREAD_TRIED = false;

  function findMono() {
    if (MODULE) return true;
    for (var i = 0; i < CANDIDATES.length; i++) {
      var m = Process.findModuleByName(CANDIDATES[i]);
      if (!m) continue;
      var picked = {};
      for (var k = 0; k < WANT.length; k++) {
        var a = m.findExportByName(WANT[k]);
        if (a) picked[WANT[k]] = a;
      }
      if (picked['mono_get_root_domain'] && picked['mono_class_vtable'] &&
          picked['mono_vtable_get_static_field_data']) {
        MODULE = m;
        F = picked;
        NF = {};
        return true;
      }
    }
    return false;
  }

  // КЭШИРОВАННАЯ обёртка. Никогда не создаём NativeFunction на лету.
  function fn(name, ret, args) {
    if (!F[name]) return null;
    var key = name + '|' + ret + '|' + args.join(',');
    if (!NF[key]) {
      try { NF[key] = new NativeFunction(F[name], ret, args); }
      catch (e) { return null; }
    }
    return NF[key];
  }

  function dom() {
    if (DOMAIN) return DOMAIN;
    if (!findMono()) return null;
    DOMAIN = fn('mono_get_root_domain', 'pointer', [])();
    return DOMAIN;
  }

  function ensureThread() {
    if (THREAD_TRIED) return;
    THREAD_TRIED = true;
    try {
      var f = fn('mono_thread_attach', 'pointer', ['pointer']);
      if (f) THREAD = f(dom());
    } catch (e) { THREAD = null; }
  }

  function cstr(p) {
    if (!p || p.isNull()) return '';
    try { return p.readCString(); } catch (e) { return ''; }
  }

  function eachAssembly(visit) {
    var f = fn('mono_assembly_foreach', 'void', ['pointer', 'pointer']);
    if (!f) return;
    var cb = new NativeCallback(function (asm, user) {
      try { visit(asm); } catch (e) { }
    return undefined; }, 'void', ['pointer', 'pointer']);
    f(cb, NULL);
  }

  function imageOf(assembly) {
    var found = null;
    eachAssembly(function (asm) {
      var gi = fn('mono_assembly_get_image', 'pointer', ['pointer']);
      var gn = fn('mono_image_get_name', 'pointer', ['pointer']);
      if (!gi || !gn) return;
      var img = gi(asm);
      if (cstr(gn(img)) === assembly) found = img;
    });
    return found;
  }

  function classOf(assembly, ns, name) {
    var img = imageOf(assembly);
    if (!img) return null;
    var cf = fn('mono_class_from_name', 'pointer',
                ['pointer', 'pointer', 'pointer']);
    if (!cf) return null;
    var k = cf(img, Memory.allocUtf8String(ns || ''),
               Memory.allocUtf8String(name || ''));
    return (k && !k.isNull()) ? k : null;
  }

  // классы сборки через таблицу метаданных (без готовых API на «список»)
  function classesOf(img) {
    var getTable = fn('mono_image_get_table_info', 'pointer',
                      ['pointer', 'int']);
    var getRows = fn('mono_table_info_get_rows', 'int', ['pointer']);
    var getK = fn('mono_class_get', 'pointer', ['pointer', 'uint32']);
    var gn = fn('mono_class_get_name', 'pointer', ['pointer']);
    var gns = fn('mono_class_get_namespace', 'pointer', ['pointer']);
    if (!getTable || !getRows || !getK || !gn || !gns) return [];
    var table = getTable(img, 2);          // MONO_TABLE_TYPEDEF
    if (!table || table.isNull()) return [];
    var rows = getRows(table);
    if (rows <= 0) return [];
    var limit = rows < 5000 ? rows : 5000;
    var out = [];
    for (var i = 1; i < limit; i++) {
      var k = getK(img, 0x02000000 | i);
      if (!k || k.isNull()) continue;
      var name = cstr(gn(k));
      if (!name) continue;
      out.push({ k: k, ns: cstr(gns(k)), name: name });
    }
    return out;
  }

  // собственные поля класса (без обхода родителей — см. правило 2)
  function ownFields(k) {
    var iterf = fn('mono_class_get_fields', 'pointer', ['pointer', 'pointer']);
    if (!iterf) return [];
    var iter = Memory.alloc(Process.pointerSize);
    iter.writePointer(NULL);
    var out = [];
    var f = iterf(k, iter);
    while (f && !f.isNull() && out.length < 500) {
      out.push(f);
      f = iterf(k, iter);
    }
    return out;
  }

  var IDENT = /^[A-Za-z_<][A-Za-z0-9_`<>]*$/;

  function fieldName(f) {
    var direct = null;
    try { direct = cstr(f.readPointer()); } catch (e) { direct = ''; }
    if (direct && IDENT.test(direct) && direct.length <= 128)
      return direct;
    var viaApi = fn('mono_field_get_name', 'pointer', ['pointer']);
    if (viaApi) {
      var n = cstr(viaApi(f));
      if (n && n.length <= 128) return n;
    }
    return direct || '';
  }

  function isStaticField(f) {
    var ff = fn('mono_field_get_flags', 'int', ['pointer']);
    if (!ff) return true;                 // не смогли — не прячем
    try { return (ff(f) & 0x0010) !== 0; } catch (e) { return true; }
  }

  // имя типа поля; enum -> имя базового примитива
  function fieldTypeName(f) {
    var ft = fn('mono_field_get_type', 'pointer', ['pointer']);
    var tn = fn('mono_type_get_name', 'pointer', ['pointer']);
    if (!ft || !tn) return '';
    var t = null;
    try { t = ft(f); } catch (e) { return ''; }
    if (!t || t.isNull()) return '';
    var name = cstr(tn(t));
    var isEnum = fn('mono_class_is_enum', 'int', ['pointer']);
    var cfmt = fn('mono_class_from_mono_type', 'pointer', ['pointer']);
    var base = fn('mono_class_enum_basetype', 'pointer', ['pointer']);
    if (name === 'System.Enum' || /Enum$/.test(name)) {
      if (isEnum && cfmt && base) {
        try {
          var tc = cfmt(t);
          if (tc && !tc.isNull() && isEnum(tc)) {
            var b = base(tc);
            if (b && !b.isNull()) name = cstr(tn(b));
          }
        } catch (e) { /* остаётся имя енума — значение не прочитаем */ }
      }
    }
    return name;
  }

  // адрес статического поля: vtable класса-владельца + смещение поля
  //
  // Проверено на живой игре: `mono_vtable_get_static_field_data` в этой
  // сборке Mono возвращает ТОЛЬКО базу статик-блока класса — для всех
  // полей класса адрес одинаковый. Смещение лежит отдельно, в
  // `mono_field_get_offset`, и для статик-блока выглядит как честная
  // раскладка подряд (0, 8, 16, 20, 24 ...). Поэтому адрес значения =
  // база + смещение. Без этого читался мусор: float `1.4e-45` — это
  // на самом деле int 1, прочитанный по чужому адресу.
  function staticAddr(f) {
    var d = dom();
    if (!d) return null;
    var owner = null;
    var fp = fn('mono_field_get_parent', 'pointer', ['pointer']);
    if (fp) {
      try { owner = fp(f); } catch (e) { owner = null; }
    }
    if (!owner || owner.isNull()) return null;
    var vtf = fn('mono_class_vtable', 'pointer', ['pointer', 'pointer']);
    var dataf = fn('mono_vtable_get_static_field_data', 'pointer',
                   ['pointer', 'pointer']);
    var offf = fn('mono_field_get_offset', 'int', ['pointer']);
    if (!vtf || !dataf || !offf) return null;
    var vt = vtf(d, owner);
    if (!vt || vt.isNull()) return null;
    var base = dataf(vt, f);
    if (!base || base.isNull()) return null;
    var off = 0;
    try { off = offf(f); } catch (e) { off = 0; }
    if (off < 0 || off > 0x1000000) return null;   // -1 = не инициализировано
    return base.add(off);
  }

  // ── значения ──────────────────────────────────────────────────────────
  // Строки игнорируются целиком: в них текст игры, он наружу не идёт.

  function readAt(p, tn) {
    if (!p || p.isNull()) return null;
    try {
      switch (tn) {
        case 'System.Boolean': return p.readU8() !== 0;
        case 'System.SByte': return p.readS8();
        case 'System.Byte': return p.readU8();
        case 'System.Int16': return p.readS16();
        case 'System.UInt16': return p.readU16();
        case 'System.Int32': return p.readS32();
        case 'System.UInt32': return p.readU32();
        case 'System.Int64': return p.readS64().toString();
        case 'System.UInt64': return p.readU64().toString();
        case 'System.Single': return p.readFloat();
        case 'System.Double': return p.readDouble();
        case 'System.Char': return p.readU16();
        default: return null;              // строки, объекты, массивы
      }
    } catch (e) { return null; }
  }

  function writeAt(p, tn, v) {
    if (!p || p.isNull()) return false;
    try {
      switch (tn) {
        case 'System.Boolean': p.writeU8(v ? 1 : 0); return true;
        case 'System.SByte': p.writeS8(v | 0); return true;
        case 'System.Byte': p.writeU8(v | 0); return true;
        case 'System.Int16': p.writeS16(v | 0); return true;
        case 'System.UInt16': p.writeU16(v | 0); return true;
        case 'System.Int32': p.writeS32(v | 0); return true;
        case 'System.UInt32': p.writeU32(v >>> 0); return true;
        case 'System.Int64': p.writeS64(Number(v)); return true;
        case 'System.UInt64': p.writeU64(Number(v)); return true;
        case 'System.Single': p.writeFloat(Number(v)); return true;
        case 'System.Double': p.writeDouble(Number(v)); return true;
        default: return false;
      }
    } catch (e) { return false; }
  }

  function findField(assembly, ns, name, field) {
    var k = classOf(assembly, ns, name);
    if (!k) return null;
    var ff = fn('mono_class_get_field_from_name', 'pointer',
                ['pointer', 'pointer']);
    if (!ff) return null;
    var f = ff(k, Memory.allocUtf8String(field || ''));
    return (f && !f.isNull()) ? f : null;
  }

  // ── сканер памяти (как в Cheat Engine) ─────────────────────────────────
  //
  // Списки статических полей и правка сейвов убраны: и то, и другое ломает
  // игру. Остался ровно один способ, который не вредят: пользователь сам
  // называет значение и находит его среди мусора, сужая список повторным
  // поиском. Мы даём «найти», «отфильтровать», «прочитать», «записать» —
  // и больше ничего не предполагаем о том, что значит тот или иной адрес.

  //: сколько совпадений ОТДАЁМ наружу. Каждое едет в Python отдельным
  //: объектом, и 2 миллиона записей — это десятки мегабайт по RPC:
  //: интерфейс зависал намертво. 50 000 — уже тысячи строк, хватает
  //: для сужения, а список остаётся лёгким.
  var SCAN_MAX = 50000;
  //: суммарный объём просматриваемой памяти, ~2 ГБ
  var SCAN_MAX_BYTES = 2 * 1024 * 1024 * 1024;
  //: модули и большие куски, где живут текстуры и код
  var SKIP_PROT = 'r-x';
  var SKIP_BASE = 0x10000;
  var SKIP_SIZE = 32 * 1024 * 1024;

  function kindSize(kind) {
    switch (kind) {
      case 'i8': case 'u8': return 1;
      case 'i16': case 'u16': return 2;
      case 'i32': case 'u32': case 'f32': return 4;
      case 'i64': case 'u64': case 'f64': return 8;
      default: return 0;
    }
  }

  // байты значения -> шаблон для Memory.scan (little endian)
  function patternOf(kind, v) {
    var size = kindSize(kind);
    if (!size) return null;
    var buf = new ArrayBuffer(8);
    var dv = new DataView(buf);
    var n = Number(v);
    if (!isFinite(n)) return null;
    switch (kind) {
      case 'i8': dv.setInt8(0, n | 0); break;
      case 'u8': dv.setUint8(0, n & 0xff); break;
      case 'i16': dv.setInt16(0, n | 0, true); break;
      case 'u16': dv.setUint16(0, n & 0xffff, true); break;
      case 'i32': dv.setInt32(0, n | 0, true); break;
      case 'u32': dv.setUint32(0, n >>> 0, true); break;
      case 'i64': case 'u64':
        dv.setInt32(0, n | 0, true);
        dv.setInt32(4, Math.floor(n / 4294967296), true);
        break;
      case 'f32': dv.setFloat32(0, n, true); break;
      case 'f64': dv.setFloat64(0, n, true); break;
      default: return null;
    }
    var bytes = new Uint8Array(buf, 0, size);
    var out = [];
    for (var i = 0; i < size; i++) {
      var b = bytes[i];
      out.push(('0' + b.toString(16)).slice(-2));
    }
    return out.join(' ');
  }

  // только то, во что можно писать: память процесса
  function rwRanges() {
    try {
      return Process.enumerateRanges({ protection: 'rw-', coalesce: true });
    } catch (e) {
      return [];
    }
  }

  function readKind(p, kind) {
    if (!p || p.isNull()) return null;
    try {
      switch (kind) {
        case 'i8': return p.readS8();
        case 'u8': return p.readU8();
        case 'i16': return p.readS16();
        case 'u16': return p.readU16();
        case 'i32': return p.readS32();
        case 'u32': return p.readU32();
        case 'i64': return p.readS64().toString();
        case 'u64': return p.readU64().toString();
        case 'f32': return p.readFloat();
        case 'f64': return p.readDouble();
        default: return null;
      }
    } catch (e) { return null; }
  }

  function writeKind(p, kind, v) {
    if (!p || p.isNull()) return false;
    try {
      switch (kind) {
        case 'i8': p.writeS8(v | 0); return true;
        case 'u8': p.writeU8(v & 0xff); return true;
        case 'i16': p.writeS16(v | 0); return true;
        case 'u16': p.writeU16(v & 0xffff); return true;
        case 'i32': p.writeS32(v | 0); return true;
        case 'u32': p.writeU32(v >>> 0); return true;
        case 'i64': p.writeS64(Number(v)); return true;
        case 'u64': p.writeU64(Number(v)); return true;
        case 'f32': p.writeFloat(Number(v)); return true;
        case 'f64': p.writeDouble(Number(v)); return true;
        default: return false;
      }
    } catch (e) { return false; }
  }

  // В ЭТОЙ сборке Frida `Memory.scan` — СТАРАЯ сигнатура (колбэки
  // onMatch/onComplete, возвращает undefined), и наш вызов падал на
  // каждом диапазоне: «cannot read property 'onMatch' of undefined».
  // Список оказывался пустым мгновенно — 350 МБ за 7 мс. Рабочий API
  // здесь `Memory.scanSync`; старый вариант оставлен запасным.
  function scanRange(base, size, pattern) {
    if (typeof Memory.scanSync === 'function') {
      try { return Memory.scanSync(base, size, pattern); } catch (e) { }
    }
    var hits = [];
    try {
      Memory.scan(base, size, pattern, {
        onMatch: function (addr) { hits.push({ address: addr }); },
        onComplete: function () { }
      });
    } catch (e) { return []; }
    return hits;
  }

  rpc.exports = {
    diagnose: function () {
      var ok = findMono();
      ensureThread();
      var d = ok ? dom() : null;
      return {
        pid: Process.id,
        hasMono: ok,
        module: ok ? MODULE.name : null,
        exports: ok ? Object.keys(F).length : 0,
        vtableData: ok ? !!F['mono_vtable_get_static_field_data'] : false,
        domain: !!(d && !d.isNull()),
        thread: !!(THREAD && !THREAD.isNull())
      };
    },

    assemblies: function () {
      if (!findMono()) return [];
      var found = {};
      eachAssembly(function (asm) {
        var gi = fn('mono_assembly_get_image', 'pointer', ['pointer']);
        var gn = fn('mono_image_get_name', 'pointer', ['pointer']);
        if (!gi || !gn) return;
        found[cstr(gn(gi(asm)))] = 1;
      });
      return Object.keys(found).sort();
    },

    classes: function (p) {
      if (!findMono()) return [];
      ensureThread();
      var img = imageOf((p && p.assembly) || "");
      if (!img) return [];
      var out = [];
      var list = classesOf(img);
      for (var i = 0; i < list.length; i++) {
        out.push({ name: list[i].name, ns: list[i].ns,
                   full: list[i].ns ? list[i].ns + '.' + list[i].name
                                    : list[i].name });
      }
      return out;
    },

    // ОДИН вызов на всю сборку: раньше на каждый класс шёл отдельный
    // round-trip (200 классов = 200 вызовов), сейчас обход целиком ~5 мс.
    statics: function (p) {
      if (!findMono()) return { error: 'no-mono' };
      ensureThread();
      var assembly = (p && p.assembly) || "";
      var img = imageOf(assembly);
      if (!img) return { error: 'no-image', assembly: assembly };
      var list = classesOf(img);
      var out = [];
      var total = 0;
      for (var i = 0; i < list.length; i++) {
        var k = list[i].k;
        var fields = ownFields(k);
        var rows = [];
        for (var j = 0; j < fields.length; j++) {
          var f = fields[j];
          if (!isStaticField(f)) continue;
          var addr = staticAddr(f);
          if (!addr) continue;
          var tn = fieldTypeName(f);
          if (!tn) continue;
          var value = readAt(addr, tn);
          if (value === null) continue;
          rows.push({ name: fieldName(f), type: tn, value: value });
          total++;
        }
        if (rows.length) {
          out.push({ assembly: assembly, ns: list[i].ns,
                     class: list[i].name, fields: rows });
        }
      }
      return { assembly: assembly, classes: list.length,
               count: total, data: out };
    },

    readStatic: function (p) {
      if (!findMono()) return { error: 'no-mono' };
      ensureThread();
      var f = findField((p && p.assembly) || "", (p && p.ns) || "",
                        (p && p.name) || "", (p && p.field) || "");
      if (!f) return { error: 'field-not-found' };
      var addr = staticAddr(f);
      if (!addr) return { error: 'not-static' };
      var tn = fieldTypeName(f);
      return { type: tn, value: readAt(addr, tn) };
    },

    writeStatic: function (p) {
      if (!findMono()) return { ok: false, error: 'no-mono' };
      ensureThread();
      var f = findField((p && p.assembly) || "", (p && p.ns) || "",
                        (p && p.name) || "", (p && p.field) || "");
      if (!f) return { ok: false, error: 'field-not-found' };
      var addr = staticAddr(f);
      if (!addr) return { ok: false, error: 'not-static' };
      var tn = fieldTypeName(f);
      if (!tn) return { ok: false, error: 'unknown-type' };
      return { ok: writeAt(addr, tn, p ? p.value : undefined), type: tn };
    },

    // что вообще есть в памяти процесса — диагностика сканера
    memoryInfo: function () {
      var out = { total: 0, ranges: 0, sizes: {} };
      var all = [];
      try { all = Process.enumerateRanges('r--'); } catch (e) { }
      try {
        all = all.concat(Process.enumerateRanges('rw-'));
      } catch (e) { }
      try {
        all = all.concat(Process.enumerateRanges('--x'));
      } catch (e) { }
      out.ranges = all.length;
      var byProt = {};
      for (var i = 0; i < all.length; i++) {
        var r = all[i];
        byProt[r.protection] = (byProt[r.protection] || 0) + r.size;
      }
      out.sizes = byProt;
      var rw = rwRanges();
      out.rw = rw.length;
      out.rwBytes = 0;
      for (var j = 0; j < rw.length; j++) out.rwBytes += rw[j].size;
      out.hasScan = (typeof Memory.scan);
      out.hasScanSync = (typeof Memory.scanSync);
      // пробный скан маленьким куском — покажет и API, и исключение
      try {
        var probe = Memory.scan(rw.length ? rw[0].base : NULL, 4096,
                                '02 00 00 00');
        out.probe = Array.isArray(probe) ? probe.length : -1;
      } catch (e) {
        out.probeError = String(e);
      }
      return out;
    },

    alive: function () { return true; },

    // СКАНЕР ПАМЯТИ. Один инструмент вместо списков полей: пользователь
    // сам называет число и находит его среди мусора.
    scan: function (p) {
      var kind = (p && p.kind) || 'i32';
      var size = kindSize(kind);
      if (!size) return { error: 'bad-kind' };
      var pattern = patternOf(kind, p ? p.value : 0);
      if (!pattern) return { error: 'bad-value' };
      var ranges = rwRanges();
      var out = [];
      var scannedBytes = 0;
      var skipped = 0;
      var total = 0;
      var truncated = false;
      var t0 = Date.now();
      for (var i = 0; i < ranges.length; i++) {
        var r = ranges[i];
        if (scannedBytes + r.size > SCAN_MAX_BYTES) { truncated = true; break; }
        scannedBytes += r.size;
        var isCode = (r.protection === SKIP_PROT && r.size >= SKIP_SIZE
                      && r.base.compare(ptr(SKIP_BASE)) >= 0);
        var hits = scanRange(r.base, r.size, pattern);
        for (var j = 0; j < hits.length; j++) {
          total++;
          if (isCode) { skipped++; continue; }   // текстуры и код: не наше
          if (out.length >= SCAN_MAX) { truncated = true; break; }
          var addr = hits[j].address;
          var val = readKind(addr, kind);
          if (val === null) continue;
          out.push({ addr: addr.toString(), value: val });
        }
        if (truncated) break;
      }
      return { count: out.length, ranges: ranges.length,
               bytes: scannedBytes, total: total, skipped: skipped,
               truncated: truncated, ms: Date.now() - t0, data: out };
    },

    // значения по списку адресов — для сужения результата
    readMany: function (p) {
      var kind = (p && p.kind) || 'i32';
      var addrs = (p && p.addrs) || [];
      var out = [];
      for (var i = 0; i < addrs.length; i++) {
        var a = null;
        try { a = ptr(String(addrs[i])); } catch (e) { continue; }
        if (a.isNull()) continue;
        var v = readKind(a, kind);
        if (v === null) continue;
        out.push({ addr: String(addrs[i]), value: v });
      }
      return { data: out };
    },

    // запись по адресу, который нашёл сам пользователь
    writeMem: function (p) {
      var kind = (p && p.kind) || 'i32';
      if (!kindSize(kind)) return { ok: false, error: 'bad-kind' };
      var a = null;
      try { a = ptr(String(p && p.addr)); } catch (e) {
        return { ok: false, error: 'bad-addr' };
      }
      var before = readKind(a, kind);
      if (before === null) return { ok: false, error: 'unreadable' };
      if (!writeKind(a, kind, p ? p.value : 0))
        return { ok: false, error: 'write-failed' };
      var after = readKind(a, kind);
      return { ok: true, before: before, value: after };
    }
  };
})();
"""

#: режим агента: только чтение по умолчанию, запись включается точечно.
#: Причина: правка чужой памяти дороже чтения, цена ошибки — вылет игры.
READONLY_HINT = (
    "Запись доступна только для числовых полей и перечислений. Строки и "
    "объекты агент не трогает: это чужой процесс, а не файл на диске."
)
