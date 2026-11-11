# BLACK HOLE 2.0 — кнопки, типографика и границы дней

## Изменения

Кнопки получили фон #0B0B0B, текст #EDEDED, границу #252525 и радиус 8 px.
Основное действие имеет спокойный фон #1C1C1C вместо белой инверсии.
Hover — #191919, pressed — #252525; главное действие имеет собственные
согласованные hover/pressed. Фокус обозначается светлой границей, disabled —
приглушённым текстом. Высота обычных кнопок и комбобоксов около 36–38 логических px.
Меню «Добавить» также почти чёрное, с тонкой границей и компактными строками.
Функции и схема расположения сохранены; график остаётся главным объектом.

## Popup: конкретная причина полос

Одного изменения QComboBox QAbstractItemView оказалось недостаточно.
На настоящих снимках контейнера оставались две полосы сверху и снизу — нативные
области прокрутки меню popup Qt (menu-style combo). Теперь только у двух списков
ChartControls применяется локальный QProxyStyle с SH_ComboBox_Popup=false.
Используются обычные QListView и QStyledItemDelegate, maxVisibleItems=8,
равномерные строки, явный тёмный фон view/viewport и рамка контейнера.
Это стандартные Qt-виджеты; системные настройки и глобальный стиль не менялись.
После отключения menu-popup полосы исчезли на 100/150/200%.
Объект локального стиля принадлежит комбобоксу, отдельно не освобождается.

## Шрифты

QFontDatabase подтвердил наличие Noto Sans; Inter и DejaVu Sans в данном
Qt-окружении отсутствуют. Основной шрифт Noto Sans, 13 px, вес 500; заголовки 600.
Выбор Qt имеет fallback Inter/DejaVu Sans/sans-serif, QSS и ECharts/CSS используют
Noto Sans, Inter, sans-serif. Установки новых шрифтов нет. Кириллица проверена
на заголовках, кнопках, popup и легенде. Подписи осей намеренно спокойнее основного
текста. На другом компьютере применяется доступный fallback.

## Границы дней

Используется уже существующий массив view.axis.boundaries, подготовленный Python
из локальных календарных дат. В TIMELINE это реальные интервалы от начала периода
(с учётом DST), в COMPACT — прежняя компактная координата суток.
В renderer к первому существующему ряду добавляется silent markLine: #383838,
1 px, opacity=0.65, без маркеров и подписей. Повторные координаты исключаются,
начало и конец диапазона не рисуются. В DAY и DAILY разделителей нет:
между дневными медианами эти линии не добавляют полезной информации.

ECharts сам отображает только попавшие в окно zoom границы и перемещает их при
resize/pan. Ряды и сегменты не добавляются/не разделяются, точек не появляется.
Плавность 0.3/monotone x, fill, connectNulls=false и filterMode=none сохранены.
Полной горизонтальной/вертикальной сетки нет. Проверка перехода DST New York
31 октября–2 ноября 2026: границы TIMELINE 86400 и 176400 секунд,
COMPACT 86400 и 172800. Координаты не меняются после zoom.

## Визуальная проверка

Драйвер tests/manual/black_hole_2_preview.py создаёт временную искусственную базу,
QSettings и настоящее окно Wayland. Снимки до/после сделаны на 100%, 150%, 200%:
overview, hover, period, period-popup, mode, mode-popup, add-menu, three-days,
zoom, dst. Снимки просмотрены: белых полос нет, кнопки чёрные, границы дней
деликатные, кривая проходит через них без разрывов.

- [Обзор до](/tmp/healthtracker-black-hole-2/before/1/overview.png)
- [Обзор после](/tmp/healthtracker-black-hole-2/after/1/overview.png)
- [Popup до](/tmp/healthtracker-black-hole-2/before/1/period-popup.png)
- [Popup после](/tmp/healthtracker-black-hole-2/after/1/period-popup.png)
- [Три дня, 150%](/tmp/healthtracker-black-hole-2/after/1.5/three-days.png)
- [Zoom, 200%](/tmp/healthtracker-black-hole-2/after/2/zoom.png)
- [DST](/tmp/healthtracker-black-hole-2/after/1/dst.png)

Корень /tmp/healthtracker-black-hole-2/{before,after}/{1,1.5,2}/ временный.
Драйвер отправляет запросы контроллеру напрямую: исходный выбор «Сегодня» и
пункт режима до ручного обновления списка не отражают выбранный
запрос; фактический диапазон показан на графике. Обычные элементы управления
проверяются отдельными существующими UI-тестами. На 200% при небольшой физической
высоте сохраняется существующая прокрутка Обзора. Ручная приёмка пользователем
не заявляется выполненной. Wayland иногда предупреждает об отсутствии input grab
у программно открытого popup: скриншоты его видимого содержимого сохранены;
интерактивные сценарии покрыты UI-набором.

## Файлы

Production: presentation/theme.py, presentation/chart_controls.py,
resources/chart/chart.css, resources/chart/chart_render.js (в src/healthtracker).
Новые: tests/ui/test_black_hole_2.py, tests/manual/black_hole_2_preview.py,
этот отчёт. Обновлена прежняя проверка отсутствия разделителей в
 tests/ui/test_black_hole_ui.py: теперь они ожидаются только в многодневных
COMPACT/TIMELINE. Исходные Python-проекции, Domain, расчёты, схема, WebChannel,
формы и backup/restore не менялись. Документы handoff и development_plan обновлены.

## Результаты проверок и сборка

Добавлены три сценария: стандартный тёмный popup/состояния элементов и два
варианта COMPACT/TIMELINE на DST с сохранением координат после zoom.
Связанный набор: 17 passed (7.05 с). Полная регрессия: **1203 passed,
7 прежних warnings, 93.43 с**. Финальные три сценария отдельно прошли на 100%
(1.26 с), 150% (1.30 с), 200% (1.36 с). compileall/pip check успешны.

Существующие предупреждения deprecated setActiveWindow, WebEngineProfile при
завершении и GBM/Vulkan fallback не скрывались. PyInstaller оставляет прежнее
предупреждение отсутствующего необязательного QML assetdownloader. Ошибок
сборки или аварий во время приёмки не было. Сохранены по 10 исходных и итоговых
PNG на каждом масштабе (60 всего).

Новая onedir Arch Linux x86_64: **dist/stage7-black-hole-2/healthtracker/**.
Собрана прежним packaging/healthtracker.spec:

```bash
.venv/bin/python -m PyInstaller --noconfirm \
  --distpath dist/stage7-black-hole-2 --workpath build/stage7-black-hole-2 \
  packaging/healthtracker.spec
./dist/stage7-black-hole-2/healthtracker/healthtracker
```

Перемещённая копия `/tmp/HealthTracker black hole 2` прошла --check-bundle
из /tmp в настоящем Wayland со скрытыми исходниками, .venv и системным Python,
PATH=/nonexistent. Использован bundled libpython3.14.7, loaded_from_venv=false,
renderer Seccomp=2. Семь форм сохранили записи, графики/аналитика открылись,
backup/inspect/restore прошли; после нового процесса восстановлены по 15 записей
семи типов и QSettings. Пользовательская база вне программы. Все 11 ресурсов
совпадают с исходниками. Прежняя stage7-smooth и остальные сборки сохранены;
3381 защищённый файл из предыдущей контрольной сверки совпал по SHA-256.

Изменены также AGENTS.md и README в части актуальной контрольной точки/сборки.
Git-коммиты и публикация этого задания не выполнялись. Следующая работа не начата.
Оценка итогового дизайна пользователем остаётся отдельной; универсальная
переносимость onedir между дистрибутивами Linux не заявляется.
