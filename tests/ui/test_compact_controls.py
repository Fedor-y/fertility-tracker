"""Компактная группа не растягивается и переносится, текст помещается полностью."""
from datetime import date
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyle,QStyleOptionComboBox,QSizePolicy
from healthtracker.presentation.chart_controls import ChartControls,PERIODS,MODES
from healthtracker.presentation.theme import apply_theme


def test_compact_controls_keep_width_and_all_cyrillic_labels(qtbot):
    w=ChartControls(date(2026,11,1));apply_theme(w);qtbot.addWidget(w)
    w.resize(1100,260);w.show()
    widths=[x.width() for x in (w.period,w.mode,w.start,w.end,w.apply)]
    w.resize(1400,260)
    assert [x.width() for x in (w.period,w.mode,w.start,w.end,w.apply)]==widths
    for combo,texts in ((w.period,[t for _,t in PERIODS]),(w.mode,list(MODES.values()))):
        option=QStyleOptionComboBox();combo.initStyleOption(option)
        rect=combo.style().subControlRect(QStyle.ComplexControl.CC_ComboBox,option,QStyle.SubControl.SC_ComboBoxEditField,combo)
        assert all(combo.fontMetrics().horizontalAdvance(t)<=rect.width() for t in texts)
        assert combo.sizePolicy().horizontalPolicy()==QSizePolicy.Policy.Fixed
    assert w.details_button.text()=='' and w.details_button.toolTip()=='Ряды и слои'
    assert w.mode_group.geometry().right()<w.width()-200
    assert w.custom.isHidden()
    w.period.setCurrentIndex(w.period.findData('custom'))
    assert w.custom.isVisible()
    w.details_button.click();assert w.details.isVisible()
    w.period.setCurrentIndex(0);assert not w.custom.isVisible()


def test_narrow_controls_wrap_whole_groups_without_overlap(qtbot):
    w=ChartControls(date(2026,11,1));apply_theme(w);qtbot.addWidget(w)
    w.period.setCurrentIndex(w.period.findData('custom'))
    w.resize(300,500);w.show()
    qtbot.waitUntil(lambda:w.mode_group.y()>w.period.y())
    assert w.period.geometry().right()<w.width()
    assert w.mode_group.geometry().right()<w.width()
    groups=(*w.date_groups,w.apply)
    assert all(g.geometry().right()<w.custom.width() for g in groups)
    assert all(not a.geometry().intersects(b.geometry()) for i,a in enumerate(groups) for b in groups[i+1:])
