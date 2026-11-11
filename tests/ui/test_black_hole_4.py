"""Небольшие пользовательские проверки новой компоновки, искусственные данные."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox
from test_analytics_page_ui import analytics_window,open_page,custom,wait_page
from test_diary import services,seed,page,rows,MOMENT
from test_backup_page import ui,choose,create
from healthtracker.presentation.theme import Disclosure
from healthtracker.presentation.forms.stress import StressDialog
from healthtracker.presentation.forms.physical import PhysicalDialog


def test_analytics_settings_and_details_preserve_snapshot(analytics_window,qtbot):
    window,_,_=analytics_window
    p=open_page(qtbot,window);custom(qtbot,window)
    delivery=p.chart.bridge.pending.delivery_id
    assert not p.controls.isVisible()
    p.settings_button.click()
    assert p.settings_popup.isVisible() and p.controls.period.isVisible()
    combo=p.controls.period
    combo.showPopup();qtbot.waitUntil(combo.view().isVisible)
    qtbot.keyClick(combo.view(),Qt.Key.Key_Escape)
    assert p.settings_popup.isVisible()
    p.settings_button.click()
    assert p.chart.bridge.pending.delivery_id==delivery
    details=next(d for d in p.sections.findChildren(Disclosure) if d.content is p.sections.summary_table)
    details.toggle.click()
    assert p.sections.summary_table.isVisible() and p.sections.summary_table.model().rowCount()==6
    assert '01.10.2026' in p.range_label.text()


def test_diary_feed_opens_full_details_and_existing_action(services,qtbot):
    _,obs,service=services;seed(obs);w=page(qtbot,service)
    assert w.records.isHeaderHidden() and w.add_button.text()==''
    item=rows(w)[0]
    qtbot.mouseClick(w.records.viewport(),Qt.MouseButton.LeftButton,pos=w.records.visualItemRect(item).center())
    assert w.selected() is not None and w.details_scroll.isVisible()
    assert w.details.text()==w.selected().summary
    with qtbot.waitSignal(w.open_requested):w.open_button.click()
    assert w.delete_button.isVisible()
    w.entry_date.setDate(w.entry_date.date().addDays(1))
    assert w.status.text()=="Записей пока нет"
    assert all(w.records.topLevelItem(i).isHidden() for i in range(w.records.topLevelItemCount()))


def test_optional_form_sections_leave_scores_and_save_visible(services,qtbot):
    _,obs,_=services
    for kind,cls,attribute in (('stress',StressDialog,'causes_section'),('physical',PhysicalDialog,'symptom_section')):
        form=cls(obs);qtbot.addWidget(form);form.show()
        qtbot.waitUntil(form.isVisible)
        assert form.score.choice.isVisible() and form.buttons.isVisible()
        qtbot.waitUntil(lambda:form.score.choice.height()>=30)
        assert form.rect().contains(form.buttons.geometry())
        section=getattr(form,attribute)
        assert not section.content.isVisible()
        initial=form.state();section.toggle.click()
        assert section.content.isVisible() and form.state()==initial
        assert all(c.view().objectName()=='floatingOptions' for c in form.body.findChildren(QComboBox))
        form.score.set_value(6);form.moment.set_moment(MOMENT)
        form.submit();assert form._committed
        assert obs.get(kind,form.record_id).value.score==6


def test_backup_list_and_full_directory_remain_accessible(ui,qtbot,tmp_path,monkeypatch):
    _,p,_,_,_,_=ui
    assert not p.directory_label.isVisible()
    p.directory_details.toggle.click()
    assert str(p.directory) in p.directory_label.text()
    target=tmp_path/'chosen';target.mkdir(mode=0o700);choose(monkeypatch,target)
    create(qtbot,p)
    assert p.table.rowCount()==1 and not p.table.showGrid() and p.table.height()<140
    assert p.restore_button.text()=='Восстановить' and p.open_button.toolTip()
