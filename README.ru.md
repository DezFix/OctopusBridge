<p align="center">
  <a href="https://github.com/DezFix/OctopusBridge/blob/main/assets/ico.ico">
    <img src="https://github.com/DezFix/OctopusBridge/raw/main/assets/ico.ico" width="96" alt="Логотип OctopusBridge">
  </a>
</p>

<h1 align="center">OctopusBridge</h1>

<p align="center">
  <b>Инструмент перевода и модификации игр на Twine, Ren'Py, RPG Maker и Tyrano</b>
</p>

<p align="center">
  <a href="https://github.com/DezFix/OctopusBridge/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-GPL--3.0-blue.svg" alt="Лицензия">
  </a>
  <a href="https://github.com/DezFix/OctopusBridge/releases">
    <img src="https://img.shields.io/github/v/release/DezFix/OctopusBridge?color=blue" alt="Релизы">
  </a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-blue" alt="Платформа">
  <img src="https://img.shields.io/badge/lang-RU%20%7C%20EN-lightgrey" alt="Языки">
  <a href="https://ko-fi.com/k_k">
    <img src="https://img.shields.io/badge/Ko--fi-support-FF5E5B?logo=ko-fi&logoColor=white" alt="Ko-fi">
  </a>
</p>

<p align="center">
  <a href="https://github.com/DezFix/OctopusBridge/blob/main/README.md">English version</a>
</p>

<!-- 🖼️ Лучшее, что можно сделать — GIF или скриншот приложения: открыли проект → извлекли текст → перевели → применили, 5–10 секунд, по кругу.
     ![demo](docs/demo.gif) -->

> **⚠️ В разработке.** OctopusBridge активно дорабатывается. Возможны баги, падения и повреждённые переводы, особенно для движка **Twine**. Перед переводом всегда делайте резервную копию игры и сообщайте о найденных проблемах.

---

## Оглавление

- [Что это](#что-это)
- [Возможности](#возможности)
- [Скриншоты](#скриншоты)
- [Поддерживаемые движки](#поддерживаемые-движки)
- [Требования](#требования)
- [Установка](#установка)
- [Быстрый старт](#быстрый-старт)
- [Примечания](#примечания)
- [Лицензия](#лицензия)

---

## Что это

OctopusBridge переводит и модифицирует игры на ПК. Перевод **пакетный**: текст извлекается из файлов игры, переводится и записывается обратно до запуска игры — без ручного копирования и правки исходников игры.

---

## Возможности

|  |  |
|---|---|
| ⚡ **Быстрый пакетный перевод** | До 100 строк в пакете, несколько пакетов параллельно — ~28 600 строк/мин на бесплатных endpoints Google. |
| 🤖 **AI и бесплатные варианты** | Без ключей и регистрации (бесплатные endpoints Google/Bing). Для больших объёмов — любой OpenAI-совместимый API. |
| 🎮 **Читы и инструменты в игре** | Переменные, золото, телепорт, редактор карт, редактор сейвов, просмотр ресурсов, патч шрифта — в зависимости от движка. |
| 📚 **Глоссарий и память переводов** | Общая база SQLite для всех проектов, автоматическое маскирование игровых кодов (`\C[8]`, `<center>`, …). |
| 🧠 **AI-корректор** | Полирует переводы с учётом глоссария и контекста, показывает дифф для проверки перед применением. |
| 🌙 **Аккуратный интерфейс** | Тёмная тема, русский/английский, системный трей, drag-and-drop, встроенный чейнджлог. |

---

## Скриншоты

![Список проектов](assets/screenshots/home.png)
![Перевод](assets/screenshots/translate.png)
![Главное окно](assets/screenshots/main.png)
![Читы RPG Maker](assets/screenshots/Cheats-rpg.png)
![Редактор карт](assets/screenshots/Map-rpg.png)
![Просмотр ресурсов](assets/screenshots/Resource.png)
![Редактор сейвов (Twine)](assets/screenshots/Save%20editor%20Tvine.png)

---

## Поддерживаемые движки

| Движок | Статус |
|---|---|
| RPG Maker MV / MZ | ✅ Стабильно (в т. ч. Electron-сборки с `app.asar`) |
| Ren'Py | ✅ Стабильно |
| TyranoScript / TyranoBuilder | ✅ Поддерживается |
| Twine (SugarCube) | 🧪 Экспериментально |

---

## Требования

- Windows 10/11 (64-бит)
- ~500 МБ свободного места на диске

---

## Установка

1. Скачайте `OctopusBridge.exe` со [страницы релизов](https://github.com/DezFix/OctopusBridge/releases) и запустите.

> EXE не подписан — Windows SmartScreen может показать предупреждение. Нажмите **«Подробнее» → «Выполнить в любом случае»**.

---

## Быстрый старт

1. **Откройте игру** — перетащите папку игры или `Game.exe` в окно приложения (или используйте вкладку «Проекты»).
2. **Переведите** — вкладка «Перевод файлов»: извлеките текст, нажмите **«Перевод»**, затем **«Применить»**, чтобы записать его обратно в игру.
3. **Читы / карты / сейвы** — доступны во вкладках движка после открытия проекта. Читы и карты работают с запущенной игрой, редактор сейвов — напрямую с файлами сохранений.

---

## Примечания

- Google/Bing — неофициальные бесплатные endpoints: ключи не нужны, но объём может быть ограничен. Для больших проектов подключите AI-провайдера в настройках.
- Инъекции изменяют процесс игры в памяти — используйте инструмент только на играх, которые вам принадлежат или которые вам разрешено модифицировать.
- Полный чейнджлог: [CHANGELOG.md](https://github.com/DezFix/OctopusBridge/blob/main/CHANGELOG.md)

---

## Лицензия

GPL-3.0 — см. [LICENSE](https://github.com/DezFix/OctopusBridge/blob/main/LICENSE). Проекты, которые вы создаёте в приложении, остаются вашими.

---

<p align="center">
  ⭐ Если OctopusBridge вам помог — поставьте звёздочку репозиторию, это помогает другим его найти.<br>
  Нашли баг? <a href="https://github.com/DezFix/OctopusBridge/issues">Откройте issue</a> ·
  Хотите поддержать разработку? <a href="https://ko-fi.com/k_k">Кофе на Ko-fi</a>
</p>