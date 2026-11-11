"""Проверки Floating UI без изменения формы, данных и графика."""
import json
from PySide6.QtCore import Qt,QSettings,QPoint,QPointF,QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QMouseEvent
from test_chart_channel import channel,js
from test_smooth_chart import draw
from healthtracker.presentation.main_window import MainWindow


def test_icon_actions_and_menu_keep_existing_routes(channel,qtbot,monkeypatch):
    window,*_=channel
    calls=[]
    monkeypatch.setattr(window,'open_cognitive',lambda:calls.append('brain'))
    monkeypatch.setattr(window,'open_physical',lambda:calls.append('biceps'))
    for button in (window.cognitive_button,window.physical_button,window.add_button):
        assert button.text()=='' and not button.icon().isNull()
        assert button.width()==36 and button.height()==36
        assert button.toolTip() and button.accessibleName()
    qtbot.mouseClick(window.cognitive_button,Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.physical_button,Qt.MouseButton.LeftButton)
    assert calls==['brain','biceps']
    # InstantPopup использует вложенный цикл; закрываем его управляемым таймером.
    from PySide6.QtCore import QTimer
    opened=[]
    window.add_menu.aboutToShow.connect(lambda:opened.append(True))
    QTimer.singleShot(0,window.add_menu.close)
    window.add_button.showMenu()
    assert opened and len(window.add_actions)==6


def test_sidebar_preserves_graph_zoom_and_page_identity(channel,qtbot):
    window,_,controller,bridge,_=channel
    draw(channel,qtbot,'timeline')
    pages=[window.pages.widget(i) for i in range(window.pages.count())]
    delivery=bridge.pending.delivery_id
    js(qtbot,window,'window.healthtrackerChannel.zoom(20,65)')
    expression='JSON.stringify(echarts.getInstanceByDom(document.getElementById("chart")).getOption().dataZoom.map(z=>[z.start,z.end]))'
    zoom=js(qtbot,window,expression)
    window.sidebar_toggle.click()
    qtbot.waitUntil(lambda:window.sidebar.width()==56)
    assert window.sidebar.width()==56
    assert all(window.navigation.item(i).text()=='' and window.navigation.item(i).toolTip() for i in range(4))
    qtbot.waitUntil(lambda:js(qtbot,window,'window.healthtrackerChannel.rendering().width')>0)
    assert js(qtbot,window,expression)==zoom
    assert bridge.pending.delivery_id==delivery
    assert [window.pages.widget(i) for i in range(window.pages.count())]==pages
    window.sidebar_toggle.click()
    qtbot.waitUntil(lambda:window.sidebar.width()==176)
    assert window.sidebar.width()==176 and window.navigation.item(0).text()=='Обзор'


def test_sidebar_setting_reopens_and_navigation_keyboard(qtbot,tmp_path):
    settings=QSettings(str(tmp_path/'window.ini'),QSettings.Format.IniFormat)
    first=MainWindow(settings=settings,start_chart=False);qtbot.addWidget(first);first.show()
    first.sidebar_toggle.click();first.close()
    assert settings.value('window/sidebar_collapsed',False,type=bool)
    second=MainWindow(settings=settings,start_chart=False);qtbot.addWidget(second);second.show()
    assert second.sidebar_collapsed and second.sidebar.width()==56
    # Navigation remains keyboard accessible even without visible labels.
    second.navigation.setEnabled(True);second.navigation.setFocus()
    qtbot.keyClick(second.navigation,Qt.Key.Key_Down)
    assert second.navigation.currentRow()==1
    second.close()


def test_floating_popup_cards_keyboard_escape_and_mouse(channel,qtbot):
    window,*_=channel
    window.chart_settings_popup.show_for_anchor()
    combo=window.chart_controls.period
    combo.showPopup();qtbot.waitUntil(combo.view().isVisible)
    view=combo.view();view.setCurrentIndex(combo.model().index(0,0))
    image=view.grab().toImage();ratio=image.devicePixelRatio()
    # Между карточками чёрный промежуток, середина карточки темно-серая.
    gap=image.pixelColor(int(12*ratio),int(40*ratio))
    card=image.pixelColor(int(8*ratio),int(20*ratio))
    assert gap.red()<10 and card.red()>=17
    pos=view.visualRect(combo.model().index(1,0)).center()
    QApplication.sendEvent(view.viewport(),QMouseEvent(QEvent.Type.MouseMove,QPointF(pos),QPointF(view.viewport().mapToGlobal(pos)),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
    assert view.itemDelegate().hovered_row==1
    # Qt combo may move its current row on hover; keyboard phase starts explicitly at row 0.
    view.setCurrentIndex(combo.model().index(0,0))
    qtbot.keyClick(view,Qt.Key.Key_Down);qtbot.keyClick(view,Qt.Key.Key_Return)
    assert combo.currentIndex()==1 and not view.isVisible()
    combo.showPopup();qtbot.waitUntil(view.isVisible)
    qtbot.keyClick(view,Qt.Key.Key_Escape)
    assert not view.isVisible() and combo.currentIndex()==1
    combo.showPopup();qtbot.waitUntil(view.isVisible)
    target=combo.model().index(2,0)
    qtbot.mouseClick(view.viewport(),Qt.MouseButton.LeftButton,pos=view.visualRect(target).center())
    assert combo.currentIndex()==2
