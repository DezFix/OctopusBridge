# TZ_new.md — Техническое задание (новые задачи)

Дата: 2026-07-31
Статус: в работе

---

## Задача 1: Замена emoji на SVG-иконки (Heroicons)

**Цель:** Убрать все emoji-символы из интерфейса и заменить их на SVG-иконки из набора [heroicons.com](https://heroicons.com).

**Требования:**
- Все emoji (▶, ⚡, ■, 🎨 и т.п.) в UI-текстах (i18n.py, вкладки, кнопки, статус-бар) заменяются на inline-SVG-иконки.
- Иконки рисуются через QIcon с SVG-строкой (QPixmap/SVG) — без внешних файлов, без QSvgWidget если возможно (или QSvgRenderer).
- Названия кнопок и заголовков вкладок сохраняют смысл.
- Не ломать существующие тесты (13 файлов зелёные).
- Составить карту: emoji → heroicon-имя (например ⚡ → bolt, ▶ → play).

**Heroicons (24x24, outline), кандидаты:**
- ⚡ Реалтайм → bolt
- ▶ Запуск → play
- ■ Стоп → stop / square-2-stack
- 🎨 Ресурсы → swatch / paint-brush
- 🗺 Карта → map
- 📜 Тексты → document-text
- ⚙ Настройки → cog-6-tooth
- 🔍 Поиск → magnifying-glass
- 📁 Проект/папки → folder
- ✎ Правка → pencil-square
- ➕ Добавить → plus
- 🗑 Удалить → trash
- ✓ Сохранено → check
- ✕ Ошибка → x-circle
- ! Предупреждение → exclamation-triangle
- 💬 Перевод → language
- 🔒 → lock-closed

**Файлы:**
- `app/ui/i18n.py` — строки с emoji
- `app/ui/*.py` — все вкладки, где есть emoji в UI
- Возможно `app/ui/theme.py` — стили/палитра

---

## Задача 2: Bing Translator + чередование Google/Bing

**Цель:** Добавить бесплатный провайдер Bing Translator (имитация браузера в bing.com/translator, динамические токены) и реализовать чередование Google/Bing для ускорения перевода.

**Требования:**
- Новый провайдер `bing` в `app/core/translate/engines.py`:
  - Запросы имитируют браузер (User-Agent, headers).
  - Получение динамических токенов (IG, IID, key, token) с главной страницы переводчика.
  - POST на `https://www.bing.com/ttranslatev3` (или актуальный эндпоинт).
  - Маппинг языков: ru, en, ja, zh, ko и др.
- Режим чередования `auto_rotate` / `rotate` (настройка в settings):
  - Поочерёдная отправка запросов на Google и Bing (round-robin).
  - При падении/ошибке одного — fallback на другой.
  - Настройка включается в Settings → перевод.
- PROVIDERS расширяется: `{argos, google_free, bing, ai}`.
- Тесты: `tests/test_providers.py` дополнить проверкой бинга (offline — проверка структуры, не сеть).

**Файлы:**
- `app/core/translate/engines.py`
- `app/core/translate/bing.py` (новый — клиент Bing)
- `app/ui/settings_tab.py` — UI настройки чередования
- `app/ui/i18n.py` — строки
- `app/ui/welcome_tab.py`, `app/ui/translate_tab.py` — выбор провайдера (если есть комбобокс)
- `tests/test_providers.py`

---

## Критерии приёмки (обе задачи)

1. `python run_tests.py` — все 13 файлов зелёные.
2. Приложение запускается (offscreen smoke).
3. В UI нет emoji-символов (кроме, возможно, декоративных, если найдётся в favicon/логах — уточнить).
4. Bing переводит реально (ручная проверка при наличии сети).
5. Чередование работает: лог показывает чередование провайдеров.
