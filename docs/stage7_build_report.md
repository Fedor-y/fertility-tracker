# Этап 7, часть 2 — рабочая Linux onedir

Цель — актуальная сборка для **Arch Linux x86_64**, Wayland и Chromium sandbox.
Система сборки прежняя: PyInstaller 6.22.3, Python 3.14.7, PySide6/Qt 6.12.0,
локальный ECharts 6.0.0. Ни зависимости, ни системный Python не устанавливались.

## Сборка и запуск

Из корня проекта:

```bash
.venv/bin/python -m PyInstaller --noconfirm \
  --distpath dist/stage7-part2 --workpath build/stage7-part2 \
  packaging/healthtracker.spec
./dist/stage7-part2/healthtracker/healthtracker
```

Готовая папка: **dist/stage7-part2/healthtracker/**. Исполняемый файл —
**healthtracker**, рядом обязательно сохранять весь **_internal/**.
Запуск не требует активации .venv, IDE или команды python. Папку можно переносить
целиком и запускать бинарник из другого рабочего каталога. Старые
**dist/healthtracker/** и **build/healthtracker/** сохранены, не заменялись.
Повторная команда с --noconfirm заменяет именно новый каталог stage7-part2;
для сохранения его при следующей сборке следует выбрать другой distpath/workpath.
Это onedir, не установщик. Ярлык меню в систему не устанавливался.

## Устройство и ресурсы

packaging/launcher.py при обычном запуске вызывает прежний bootstrap.main.
Spec по-прежнему использует Analysis/PYZ/EXE/COLLECT, exclude_binaries=True,
без onefile, UPX и strip. Пути сборки вычисляются относительно SPECPATH;
пользовательская база не включается. Дополнен pathex для проверочного модуля packaging.

Включены Python runtime и стандартная библиотека, sqlite3, PySide6/Shiboken,
Qt Widgets/Gui/Core, Network/WebChannel/WebEngine, Wayland и другие собранные
Qt-плагины. PyInstaller hooks включают QtWebEngineProcess (Chromium), icudtl.dat,
qtwebengine_resources*.pak, локали Chromium, Qt-библиотеки и переводы.
Локальные index.html, chart.css, chart.js, chart_render.js, ECharts и его лицензии,
три ui-*.svg новой темы включены прежним datas-каталогом chart.
Навигационные иконки рисуются Python/QPainter, отдельные файлы им не нужны.

ChartView и тема используют __file__, внутри onedir это путь под _internal.
Runtime hook PyInstaller настраивает QT_PLUGIN_PATH и qt.conf для перемещённой Qt.
Не добавлялись жёсткие пути этой машины или зависимость от рабочего каталога.
WebChannel, CSP, блокировка удалённых ресурсов и Chromium sandbox не ослаблялись.

## Пользовательские пути

- SQLite: $XDG_DATA_HOME/healthtracker/healthtracker.sqlite3;
  при отсутствии абсолютного XDG_DATA_HOME — ~/.local/share/healthtracker/healthtracker.sqlite3.
- QSettings: $XDG_CONFIG_HOME/HealthTracker/HealthTracker.conf;
  по умолчанию ~/.config/HealthTracker/HealthTracker.conf.
- Каталог копий по умолчанию — backups рядом с основной базой. Пользователь выбирает
  другой каталог прежним Qt-диалогом; путь сохраняется только в QSettings backup/directory.

Замена папки программы не переносит и не заменяет эти данные. Личная база при
сборке и проверках не открывалась. В папке поставки нет SQLite-базы или тестовых данных.

## Проверка функций собранной программы

Добавлен явный packaging-сценарий:

```bash
./dist/stage7-part2/healthtracker/healthtracker --check-bundle
```

Он создаёт TemporaryDirectory и переназначает XDG_DATA_HOME/XDG_CONFIG_HOME/
XDG_CACHE_HOME до создания QApplication/Database/QSettings. Использует искусственную
базу и те же ApplicationSession, MainWindow, SQLiteBackup/inspect_backup/SQLiteRestore.
При обычном запуске проверочный модуль не выполняется. pytest в поставку не добавлен.
Сценарий сам удаляет свои временные данные после завершения.

Проверяется:

1. Реальный Wayland, включённый sandbox, ресурсы из _internal и встроенный libpython.
2. Главное окно с чёрной темой, ECharts 6.0.0, подтверждённый актуальный delivery_id.
3. Семь форм открываются из MainWindow и сохраняют ответы через кнопку «Сохранить».
4. Обзор с искусственной историей и всеми семью рядами; Аналитика с числовой сводкой.
5. Навигация, дневник, Настройки и список проверенных копий.
6. Создание копии кнопкой; выбор каталога в проверке подменён искусственным путём,
   файловая работа и worker настоящие. inspect_backup повторно проверяет результат.
7. После добавления лишней записи — настоящее восстановление выбранной копии.
   Настоящий QMessageBox подтверждается программно; база только искусственная.
   Создаётся PRE_RESTORE-копия, выполняется замена и обязательное закрытие.
8. Новый процесс того же ELF открывает восстановленную базу: по 15 записей каждого
   из семи видов, настройки SQLite восстановлены, каталог копий и геометрия QSettings
   сохранились, оба пакета копий найдены и проверены. Новый процесс корректно закрывается.

Диагностические первые попытки выявили два несоответствия самого сценария: разбор
/proc/self/maps по пробелам и использование rowCount прямо у QTableView.
Они исправлены; исходники приложения из-за этих проверок не менялись.

## Независимость и sandbox

Копия всей onedir запущена из /tmp/healthtracker-independent-cwd, бинарник находился
в отдельном каталоге /tmp/HealthTracker verified (включая пробелы в пути).
В отдельном пространстве bwrap скрыты весь проект вместе с .venv и /usr/lib/python3.14,
/usr/bin/python3.14 заменён на false только внутри этого пространства.
Каталог самой программы дополнительно смонтирован только для чтения.
PATH=/nonexistent, VIRTUAL_ENV/PYTHONPATH/PYTHONHOME/LD_LIBRARY_PATH и внешние Qt-пути
сняты. Использован --unshare-net. Система и установленный Python не изменялись.

Приёмка завершилась status=ok: 7 форм сохранены; восстановлены [15,15,15,15,15,15,15];
backup_restore/reopen_settings/database_outside_bundle=true; loaded_from_venv=false.
libpython и Qt plugins фактически загружены из перемещённой _internal.
У настоящего Chromium renderer проверен Seccomp: 2; флага --no-sandbox нет,
QTWEBENGINE_DISABLE_SANDBOX не установлен. Sandbox/GPU-флаги не менялись.
Отдельно штатный --smoke-test из этого же изолированного окружения завершился
status=ok, Qt 6.12.0, ECharts 6.0.0, WebChannel python-js-python, код выхода 0.

## Системные библиотеки Arch Linux

ldd проверил **512 ELF-файлов**, неразрешённых зависимостей **0**.
С LD_LIBRARY_PATH на библиотеки _internal и Qt обнаружены внешние зависимости:

| Пакет Arch | Фактически используемые внешние библиотеки |
|---|---|
| glibc | libc, libdl, libm, libpthread, libresolv, ld-linux-x86-64 |
| libglvnd | libEGL, libGL, libGLX, libGLdispatch |
| libdrm | libdrm |
| wayland | libwayland-client, libwayland-cursor, libwayland-egl, libwayland-server |
| libxcb | libxcb, libxcb-dri3 |

Все файлы найдены; владельцы проверены через pacman -Qqo (только чтение).
Версии окружения: glibc 2.44+r50+g1848099f063e-1, libglvnd 1.7.0-3,
libdrm 2.4.134-1, wayland 1.26.0-1, libxcb 1.17.0-1.
Полный машинный список — build/stage7-part2/system-libraries.json.
Кроме библиотек требуется работающий пользовательский Wayland-сеанс и совместимый
графический драйвер. ldd не является проверкой всех динамически загружаемых драйверов;
фактическая проверка Qt/Chromium выполнена в текущем графическом окружении.

## Изменения и ограничения

Изменены packaging/healthtracker.spec, packaging/launcher.py; добавлен
packaging/bundle_check.py. Также обновлены README.md, handoff.md, development_plan.md,
AGENTS.md и этот отчёт; stage6_report.md содержит ссылку на актуальную сборку.
Приложение под src/healthtracker не менялось: Domain, формулы, SQLite-схема/миграции,
формы, WebChannel, актуальность запросов и backup/restore прежние.

Это рабочая onedir для проверенного Arch Linux x86_64, не обещание переносимости
между дистрибутивами, старыми glibc или любыми графическими драйверами.
Сборка около 639 MiB; оптимизация размера не выполнялась.
PyInstaller предупреждает об отсутствующем необязательном QML assetdownloader plugin;
используемые Qt Widgets/WebEngine сценарии прошли. Устанавливать пакеты для него
не потребовалось. Chromium сохраняет прежнее сообщение GBM → Vulkan.
Ручной выбор пути в нативном диалоге не проверялся человеком: проверка выбирала путь
программно. Установка ярлыка/пакета, другие дистрибутивы и физическое отключение
монитора не проверялись. Старые ограничения backup/restore остаются прежними.

Следующий этап не начинать без отдельного задания.


## Контроль комплектности

Все **11 файлов** локального chart-каталога совпали с актуальными исходниками по
SHA-256, включая новые SVG, CSS/JS и ECharts. В поставке нет *.sqlite3.
QtWebEngineProcess и libqwayland.so присутствуют. Исполняемый файл в готовой папке
и в проверенной перемещённой копии идентичен:

`4c88844e65cf7424da3f5ca013c54cc05d95d41a4ca12f247367ab4a7a5368b4` (SHA-256).

Снимки реальной упакованной программы на искусственных данных просмотрены агентом:
[Обзор](/tmp/healthtracker-bundle-evidence/frozen-overview.png),
[Аналитика](/tmp/healthtracker-bundle-evidence/frozen-analytics.png),
[Дневник](/tmp/healthtracker-bundle-evidence/frozen-diary.png),
[Копии](/tmp/healthtracker-bundle-evidence/frozen-backups.png).
Это временные файлы /tmp, не часть поставки.

compileall src/tests/packaging прошёл; pip check — No broken requirements found,
с прежним предупреждением недоступного pip-кеша. Новые зависимости не установлены.


## Заключительная регрессия

Полная существующая регрессия: **1174 passed, 7 прежних warnings, 75,30 с**.
Команда: bwrap --unshare-net --dev-bind / / -- timeout --signal=TERM 240s
.venv/bin/python -m pytest -q -o faulthandler_timeout=60.
Это проверки исходников в прежнем наборе, отдельно от приёмки frozen ELF.
Новых pytest-сценариев и зависимостей не добавлялось; один packaging-сценарий проверяет
всю onedir и настоящий повторный процесс. Прежнее сообщение завершения WebEngine
профиля в регрессии остаётся и не маскировалось.

Часть 2 завершена. Следующий этап не начинался.

Штатный --smoke-test итогового бинарника повторён без QT_QPA_PLATFORM: код выхода 0,
status=ok. QT_DEBUG_PLUGINS подтвердил загрузку libqwayland.so, xdg-shell,
wayland-egl, SVG image/icon plugins из перемещённой _internal. Каталог приложения
был только для чтения, источники/.venv/системный Python скрыты; обычный выбор Qt
платформы в текущем Wayland-сеансе работает без дополнительного параметра.
