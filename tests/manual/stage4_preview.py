"""Отрисовка этапа 4 и замер GUI на искусственных базах, без личных данных.

Запуск из корня в Wayland с QT_SCALE_FACTOR=1 / 1.5 / 2.
Снимки сохраняются только в /tmp/healthtracker-stage4-acceptance/<масштаб>.
Это инструмент визуального осмотра, не имитация ручной приёмки человеком.
"""
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
import json
import os
import runpy

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea

from healthtracker.application.session import ApplicationSession
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.diary import DiaryPage
from healthtracker.presentation.main_window import MainWindow

load = runpy.run_path(str(Path(__file__).resolve().parents[1]/'performance/diary_load.py'))
app = QApplication([])
assert app.platformName() == 'wayland', app.platformName()
scale = os.environ.get('QT_SCALE_FACTOR','1')
output = Path('/tmp/healthtracker-stage4-acceptance')/scale
output.mkdir(parents=True, exist_ok=True)
images = []


def capture(widget, name):
    QTest.qWait(150)
    picture = widget.grab()
    assert picture.save(str(output/(name+'.png')))
    images.append((name,picture.toImage()))


with TemporaryDirectory(prefix='healthtracker-gui-acceptance-') as directory:
    for days in (30,365,1096):
        database=Database(Path(directory)/f'{days}.sqlite3',clock=lambda:load['NOW'])
        database.initialize()
        load['populate'](database,days)
        application=ApplicationSession(database)
        assert application.open()
        start=perf_counter()
        page=DiaryPage(application.diary,zone_provider=lambda:load['UTC'])
        page.entry_date.setDate(QDate((load['NOW']-timedelta(days=1)).date()))
        page.show()
        app.processEvents()
        opened=(perf_counter()-start)*1000
        durations=[]
        for offset in (days,days//2,1):
            start=perf_counter()
            page.entry_date.setDate(QDate((load['NOW']-timedelta(days=offset)).date()))
            app.processEvents()
            durations.append(round((perf_counter()-start)*1000,2))
            assert page.records.topLevelItem(0).childCount()==8
            assert page.records.topLevelItem(1).childCount()==4
        print(json.dumps(dict(scale=scale,days=days,open_gui_ms=round(opened,2),switch_and_events_ms=durations)),flush=True)
        page.close()
        page.deleteLater()
        app.processEvents()
        if days!=1096:
            application.close()
    window=MainWindow(application)
    window.show()
    for _ in range(100):
        if window.chart.bridge.is_ready: break
        QTest.qWait(100)
    assert window.chart.bridge.is_ready
    capture(window,'overview')
    window.navigation.setCurrentRow(2)
    day=(load['NOW']-timedelta(days=1)).date()
    window.diary.entry_date.setDate(QDate(day))
    capture(window,'diary')
    window.resize(800,500)
    capture(window,'diary-small')
    for kind in ('cognitive','physical','stress','mood','sleep','meals','gym'):
        window._diary_add(kind,day)
        form=window.active_dialog
        if kind=='cognitive':
            for choice in form.answers: choice.set_value(7)
            form.context.setPlainText('Искусственный контекст проверки')
        elif kind in ('physical','stress','mood'): form.score.set_value(7)
        elif kind=='sleep':
            form.start.set_moment(load['NOW']-timedelta(days=1,hours=12))
            form.end.requested_time.setText('08:00')
        elif kind=='meals':
            form.category.setCurrentIndex(1)
            for i in range(3): form.add_item()
            for item in form.items: item.name.setText('Искусственная позиция')
        else:
            form.attended.setCurrentIndex(1)
            form.difficulty.set_value(7)
        capture(form,kind+'-top')
        scroll=form.findChild(QScrollArea)
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        capture(form,kind+'-bottom')
        assert form.buttons.isVisible()
        assert form.buttons.button(QDialogButtonBox.StandardButton.Save).isVisible()
        form.finish_setup()
        form.reject()
    window.close()
    app.processEvents()

# Контактный лист с подписями; исходные снимки остаются в полном разрешении.
cell_w,cell_h=600,560
sheet=QImage(cell_w*4,cell_h*((len(images)+3)//4),QImage.Format.Format_RGB32)
sheet.fill(Qt.GlobalColor.white)
painter=QPainter(sheet)
for index,(name,picture) in enumerate(images):
    x,y=(index%4)*cell_w,(index//4)*cell_h
    painter.setPen(Qt.GlobalColor.black)
    painter.drawText(x+8,y+20,name)
    thumb=picture.scaled(cell_w-12,cell_h-30,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
    thumb.setDevicePixelRatio(1)
    painter.drawImage(x+6,y+26,thumb)
painter.end()
assert sheet.save(str(output/'contact.png'))
print('Снимки: '+str(output),flush=True)
