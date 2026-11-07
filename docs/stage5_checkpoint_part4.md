# HealthTracker — контрольная точка после части 4 порции 4 этапа 5

**Историческая точка. Актуальная передача после части 5 — [stage5_checkpoint_final.md](stage5_checkpoint_final.md).**

## 1. Дата и назначение

05.11.2026. Главный документ передачи агенту с пустым контекстом. Прочитать [AGENTS.md](../AGENTS.md), [README](../README.md), [требования](requirements.md), [архитектуру](architecture.md), [план](development_plan.md), [handoff](handoff.md), [отчёт](stage5_report.md) и относящиеся исходники. Документы не заменяют проверку кода.

Исходная документальная контрольная точка частей 1–3 сохранена историческим разделом отчёта. Здесь описано состояние **после реализации постоянных настроек**. Эта задача завершена; автоматически начинать следующую нельзя.

## 2. Состояние проекта

Локальное приложение Python/PySide6, Qt WebEngine/WebChannel, локальный ECharts 6.0.0, SQLite через sqlite3, схема версии 1. Этапы 1–3 завершены. В этапе 4 реализованы порции 1–7 и техническая приёмка порции 8; ручная пользовательская приёмка и отключение монитора не заявлены пройденными.

В Обзоре работают реальные графики, панель и постоянные предпочтения. Экран «Аналитика» остаётся заглушкой. Семь форм и дневник не переделывались.

## 3. Завершённые части этапа 5

Порции 1–3: аудит, расчёты Domain/Application, типизированная асинхронная подготовка. Порция 4: части 1 — протокол WebChannel; 2 — реальная отрисовка ECharts; 3 — управление; 4 — постоянные предпочтения через существующее хранилище.

Периоды: сегодня, последние 7/10 дат включительно, текущий/предыдущий месяц, текущий год, произвольный включительный диапазон. Семь независимых рядов, сон, питание, зал, общий слой событий/специальных ответов; zoom/pan/reset. Питание/зал имеют только дату, сон — реальные UTC-интервалы, стресс — маркеры без непрерывной линии и дневной агрегации. Нули, специальные ответы, ID и версии сохраняются.

## 4. Результаты проверок: история и текущая часть

Исторический итог части 3: 915 passed, 7 warnings; 49 новых сценариев; Wayland 150/200% — по 57 passed. Это не новые проверки части 4.

**Часть 4:** 59 новых сценариев — 35 Application/Infrastructure и 24 UI. Полный прогон: **974 passed, 7 warnings, 66,98 с**. Окончательные выделенные Wayland-прогоны: **100% — 81 passed (36,71 с), 150% — 81 passed (39,54 с), 200% — 81 passed (38,86 с)**. Команды и подробности — актуальный раздел [stage5_report.md](stage5_report.md).

Проверки настоящего Wayland, локального WebEngine/ECharts/WebChannel выполнены через bwrap --unshare-net. Chromium sandbox не отключался; QTWEBENGINE_DISABLE_SANDBOX и QTWEBENGINE_CHROMIUM_FLAGS не заданы. Только искусственные базы и временные XDG-каталоги. compileall/pip check и архитектурные проверки — результаты в отчёте. Прежние Qt DeprecationWarning и сообщение завершения профиля не объявляются исправленными.

## 5. Архитектура графиков и согласованность

`domain/periods.py`: DateRange включает обе даты; QuickPeriod — DAY, SEVEN_DAYS, TEN_DAYS, MONTH, PREVIOUS_MONTH, YEAR. quick_period использует календарные границы; полные месяц/год не обрезаются будущими датами. Сутки могут иметь 23/25 часов.

`domain/charts.py`: ChartMode DAY/COMPACT/TIMELINE/DAILY; chart_mode выбирает DAY для одной даты, COMPACT/TIMELINE для 2–7, DAILY для более 7. Модели и правила сегментации не менялись. Analytics.load читает семь журналов одним снимком, закрывает сессию до вычислений. Проекция координат/текстов — Python; JS не считает статистику, индекс, календарь и сегменты.

ChartQuery находится в Application, ChartController/ChartPayload — в Presentation. ChartRequests использует UUID, отмену, очередь и SnapshotToken. Защита поздних результатов/ошибок не переписана. В существующий пул добавлена submit_operation для Application-операций предпочтений: отдельного пула/соединения, передаваемого из GUI, нет. Отмена графика не отменяет запись предпочтений.

Сохраняется eventual consistency: предварительный пакет не рисуется, received повторно проверяется Python, confirmed означает актуальность на момент проверки, не строгую атомарность фактического применения JS. Проверяются page/request/delivery ID, sequence, токен, база/поколение и пояс. Commit настроек тоже повышает поколение; после успешной записи активный график получает новый запрос, а не цикл повторного сохранения.

apply_if_current неблокирующий; доставка ограничена 5 секундами, без SQLite-сессии/замка в ожидании renderer. Reload меняет page ID, закрытие запрещает доставки. Полная регрессия проверяет прежние A/B-гонки, DST, режимы, reload и фактическую потерю renderer.

## 6. Ключевые файлы

Все пути относительно `src/healthtracker/`, кроме тестов:

| Файл | Назначение |
|---|---|
| domain/periods.py, charts.py, analytics.py | Прежние периоды, сегменты и расчёты |
| domain/chart_preferences.py | Новая frozen ChartPreferences и валидация |
| application/chart_preferences.py | Новый ChartPreferencesService.load/save, PreferencesError |
| application/session.py, storage.py | ApplicationSession.chart_preferences и порт SettingsRepository |
| application/charts.py, analytics.py, chart_projection.py | Прежние запросы, единый снимок, подготовка/проекция; не изменялись |
| application/chart_requests.py | Прежняя очередь графика + операции в том же пуле |
| infrastructure/sqlite/settings.py | Существующий репозиторий, расширенная валидация ключей/рядов |
| infrastructure/sqlite/database.py, connections.py, schema.py | Прежние сессии, транзакции, поколения, CHECK; не изменялись |
| presentation/chart_preferences.py | Новый PreferencesController: debounce, последовательность, flush и ошибки |
| presentation/chart_controls.py | Применение/выдача типизированных предпочтений без SQL |
| presentation/main_window.py | Начальная загрузка, ошибки/повтор, сохранение и закрытие |
| presentation/chart_controller.py | Прежние проверки + before_shutdown для финального сохранения |
| presentation/chart.py, chart_payload.py | Прежние transport и payload; не изменялись |
| bootstrap.py | Прежнее связывание ApplicationSession/окна, QSettings геометрии |
| resources/chart/index.html, chart.js, chart_render.js, chart.css | Прежние локальные ресурсы, протокол и ECharts-отрисовка |
| resources/chart/vendor/echarts.min.js | Локальный ECharts 6.0.0, без CDN |

Тесты: [хранение](../tests/integration/test_chart_preferences.py), [UI](../tests/ui/test_chart_preferences_ui.py). Актуализированы прежние tests/ui/test_navigation.py и test_chart_controls.py под асинхронное закрытие и постоянные предпочтения.

## 7. Реализация application_settings

Таблица существует с начальной схемы версии 1: key TEXT PRIMARY KEY NOT NULL с непустым trim; value TEXT NOT NULL CHECK(json_valid(value)); updated_at_utc TEXT NOT NULL с CHECK канонического UTC. Таблица STRICT. Ни DDL, ни миграции, ни CHECK этой частью не менялись.

Сериализация прежняя: json.dumps(value, ensure_ascii=False, allow_nan=False); чтение json.loads; время encode_time(Session.now), `YYYY-MM-DDTHH:MM:SS.ffffffZ`. SQL проверяет синтаксис JSON, репозиторий — семантику. Поля предпочтений не являются новой таблицей/колонками.

## 8. SQLite-репозиторий и типизированная модель

Точный путь репозитория — `src/healthtracker/infrastructure/sqlite/settings.py`, SettingsRepository; доступ через Session.settings в database.py. Модель — `src/healthtracker/domain/chart_preferences.py`, ChartPreferences (frozen, slots).

| Поле/ключ | Тип модели и сохраняемое значение | По умолчанию |
|---|---|---|
| visible_series | tuple[SeriesKind, ...] → JSON list уникальных строк cognitive/learning/application/speed/physical/mood/stress | cognitive, physical |
| compact_mode | bool → JSON boolean | True |
| line_gap_hours | конечное положительное int/float, не bool → JSON number | 3 |
| analytics_indicator | Indicator из cognitive/learning/application/speed → JSON string | cognitive |
| show_sleep, show_meals, show_gym, show_events | каждый строго bool → JSON boolean | все True |

Отсутствующие ключи получают defaults модели, старые четыре ряда читаются без преобразования смысла. False и [] сохраняются. Разный порядок старого списка рядов нормализуется только в модели, без записи при чтении. Другого источника defaults для панели нет: ChartControls использует ChartPreferences. ChartQuery не менялся.

Порог и analytics_indicator читаются/сохраняются как существующие предпочтения; новых редакторов этих полей нет. Периоды, zoom, ошибки, снимки, ID и временные данные не сохраняются. Незнакомые строки таблицы не удаляются и не интерпретируются как новые поля модели.

## 9. Точные интерфейсы, транзакции и ошибки

Существующие сигнатуры SettingsRepository без аннотаций: `__init__(self, session)`, `get(self, key)`, `set(self, key, value)`, `delete(self, key)`. get известного отсутствующего ключа возвращает None; неверный ключ/тип — DomainValidationError. set делает UPSERT в Session.operation/savepoint, без собственного commit. delete проверяет ключ через get.

Новый Application API: `ChartPreferencesService(storage)`, `load(self) -> ChartPreferences`, `save(self, preferences: ChartPreferences) -> None`; доступ `ApplicationSession.chart_preferences`. load читает восемь ключей одним read_snapshot. save предварительно проверяет прежние известные значения и атомарно записывает восемь ключей в одном Database.write. Повреждённые прежние значения не затираются defaults даже при попытке save.

ReadSession.settings описан Application-протоколом SettingsRepository; Presentation не импортирует Infrastructure и не обращается к ApplicationSession._storage. Настройки окна остаются в QSettings. SQLite-сессия/соединение создаётся в вызывающем worker, check_same_thread=True; после выхода сессия неактивна. GUI только опрашивает завершённый Future через QTimer.

ConstraintViolation/StorageBusy/StorageRecoveryRequired/StorageError остаются прежними исключениями хранилища. Ошибки декодирования и валидации преобразуются сценарием в безопасный PreferencesError без исходного JSON/SQL. UI также закрывает тексты неожиданных исключений. При ошибке чтения — явное предупреждение, defaults только в сеансе, автоматической записи нет. Повтор чтения не заменяет повреждённые строки. При ошибке записи выбор остаётся в панели, есть повтор; штатное закрытие отменяется. Исправление повреждённой строки не выполняется автоматически и не имеет отдельной формы восстановления в этой части.

## 10. Последовательность запуска

bootstrap.main создаёт QApplication → ApplicationSession(Database(default_database_path())) → open → QSettings (кроме smoke-test) → MainWindow → event loop. Стандартный путь XDG_DATA_HOME либо ~/.local/share/healthtracker/healthtracker.sqlite3: не использовать его в тестах.

MainWindow создаёт PreferencesController до ChartController (порядок обработчиков aboutToQuit), панель временно отключена. После связывания контроллера запускается Application load через ChartRequests.submit_operation. WebEngine параллельно загружает только локальные ECharts/скрипты и qrc WebChannel. Никакого нового синхронного SQL для предпочтений в GUI нет. Прежняя инициализация дневника этой частью не переделывалась; отзывчивость асинхронных предпочтений не является утверждением, что все старые сценарии приложения асинхронны.

## 11. Первый ChartQuery, изменения и закрытие

Первый запрос разрешён только после двух готовностей: предпочтения прочитаны/явно выбраны defaults при ошибке и WebChannel ready. apply_preferences устанавливает флажки с QSignalBlocker, затем обычные AnalysisContext → ChartControls.query → ChartController.request создают первый UUID. Проверка подтверждает ровно один начальный запрос с сохранёнными параметрами.

Изменение панели сразу создаёт обычный новый ChartQuery/UUID; типизированный снимок предпочтений получает debounce 200 мс. В работе только одна обычная запись; следующие изменения объединяются в последний desired. Результат старой записи обновляет persisted для своего снимка, затем сохраняется последний desired. При периоде/zoom, не изменивших предпочтения, записи нет. Последующий result_ready сам по себе ничего не сохраняет.

При закрытии bridge сразу закрывается, debounce сбрасывается, последняя запись дописывается через polling без блокировки GUI. При ошибке окно остаётся с предупреждением/повтором. Затем завершаются задачи графика и ApplicationSession.close. before_shutdown/aboutToQuit обеспечивают финальную последовательную операцию в том же пуле; существующий финальный shutdown ждёт worker после завершения event loop. При штатном закрытии ожидание происходит через event loop. Принудительное убийство процесса/отключение питания не является проверенным сценарием сохранения несостоявшегося commit.

## 12. Что отсутствует

Полноценная страница «Аналитика», backup/restore и экспорт не реализованы. Нет сохранения периода/zoom, новых редакторов порога/analytics_indicator и автоматического ремонта повреждённых настроек. Это не означает потерю ранее сохранённых корректных порога/индикатора. Финальная ручная пользовательская приёмка и нагрузочные гарантии не добавлялись.

## 13. Ограничения

Не менять схему версии 1, миграции, CHECK, формулы, шкалы, нормативное ТЗ; не обходить MigrationBackupRequired. Не использовать личную базу, сеть, новые зависимости/системные пакеты; не отключать Chromium sandbox. Не начинать этап 6, резервирование, восстановление, экспорт, редизайн семи форм/дневника. Git не инициализирован (пустая .git), коммитов нет; onedir не пересобирался. Историческая пробная сборка этапа 1 не отражает текущую версию.

## 14. Следующая граница

Работа остановлена после части 4. **Следующего разрешения на реализацию нет.** Полноценную страницу «Аналитика», следующие части и порцию 5 начинать только по отдельному заданию пользователя. Новый агент сначала сверяет эту контрольную точку с актуальными исходниками.

## 15. Проверка следующего разрешённого изменения

Сохранять реальные тесты load/save/restart, первого Query, coalescing/последней записи при закрытии, rollback/ошибок и отсутствия SQL предпочтений в GUI. Гонки управлять Event, без случайных sleep. Повторять защиту старых результатов/ошибок, токенов/поясов, WebChannel/reload/renderer, DST и режимов/слоёв. Проверять искусственные базы, настоящий Wayland 100/150/200%, сетевую изоляцию и sandbox; затем полную регрессию, compileall, pip check, архитектурные границы и контрольные суммы защищённых файлов. Записывать только фактически выполненные результаты отдельно от истории.
