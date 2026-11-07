"""Общая монохромная тема и небольшие компоненты Presentation. Без данных/расчётов."""
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout

CHART_ASSETS = Path(__file__).resolve().parents[1] / 'resources/chart'

STYLE = """
QWidget { color: #e7e7e7; font-family: sans-serif; font-size: 13px;
    selection-background-color: #262626; selection-color: #ffffff; }
QMainWindow, QDialog, QWidget#appBody { background: #030303; }
QLabel { background: transparent; border: none; padding: 0; }
QLabel[role="pageTitle"] { font-size: 21px; font-weight: 600; color: #f5f5f5; }
QLabel[role="sectionTitle"] { font-size: 16px; font-weight: 600; color: #ebebeb; }
QLabel[role="eyebrow"] { font-size: 11px; font-weight: 600; color: #a4a4a4; }
QLabel[role="secondary"] { color: #a4a4a4; font-size: 12px; }
QLabel[role="metric"] { font-size: 24px; font-weight: 600; color: #f5f5f5; }
QLabel[role="notice"] { background: #090909; border: 1px solid #3b3b3b; border-radius: 5px; padding: 8px 10px; }
QLabel[role="status"] { color: #a5a5a5; padding: 3px 0; font-size: 12px; }
QFrame[role="panel"] { background: #090909; border: none; border-radius: 4px; }
QWidget#chartControls { background: transparent; border: none; }
QFrame#overviewSummary { background: transparent; border: none; }
QLabel[role="metric"]:disabled { color: #777777; }
QFrame[role="panel"]:disabled { background: #090909; border-color: #292929; }
QFrame#sideBar { background: #030303; border: 0; border-right: none; }
QLabel#brand { color: #f3f3f3; font-size: 16px; font-weight: 600; }
QLabel#brandCaption { color: #7d7d7d; font-size: 11px; }
QListWidget#navigation { background: transparent; border: 1px solid transparent; padding: 0; outline: none; }
QListWidget#navigation:focus { border-color: transparent; }
QListWidget#navigation::item:focus { background: #121212; border-left-color: #f2f2f2; }
QListWidget#navigation::item { padding: 11px 10px; margin: 3px 0; color: #afafaf;
    border-left: 2px solid transparent; border-radius: 4px; }
QListWidget#navigation::item:hover { color: #f2f2f2; background: #1e1e1e; }
QListWidget#navigation::item:selected { background: #121212; border-left-color: #e6e6e6; color: #ffffff; }
QPushButton, QToolButton { background: #121212; color: #e1e1e1; border: 1px solid #1c1c1c;
    border-radius: 5px; padding: 5px 10px; min-height: 16px; }
QPushButton:hover, QToolButton:hover { background: #2f2f2f; border-color: #6e6e6e; color: #ffffff; }
QPushButton:pressed, QToolButton:pressed { background: #3c3c3c; border-color: #9e9e9e; }
QPushButton:checked, QToolButton:checked { background: #383838; color: #ffffff; border-color: #ababab; }
QPushButton[kind="primary"] { background: #e7e7e7; color: #181818; border-color: #e7e7e7; font-weight: 600; }
QPushButton[kind="primary"]:hover { background: #ffffff; border-color: #ffffff; }
QPushButton[kind="primary"]:pressed { background: #c7c7c7; }
QPushButton:disabled, QToolButton:disabled { color: #717171; background: #090909; border-color: #1c1c1c; }
QPushButton:focus, QToolButton:focus { border-color: #f4f4f4; }
QLineEdit, QComboBox, QAbstractSpinBox, QTextEdit, QPlainTextEdit { background: #090909; color: #ececec;
    border: 1px solid #1c1c1c; border-radius: 4px; padding: 6px 8px; min-height: 18px; }
QTextEdit, QPlainTextEdit[readOnly="false"] { min-height: 36px; }
QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover { border-color: #707070; }
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus { border-color: #e9e9e9; }
QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled, QTextEdit:disabled { color: #797979; border-color: #1c1c1c; background: #090909; }
QAbstractSpinBox QLineEdit, QComboBox QLineEdit { border: none; background: transparent; padding: 0; min-height: 0; }
QComboBox { padding-right: 28px; }
QComboBox::drop-down { width: 25px; border: none; }
QComboBox::down-arrow { image: url('@DOWN@'); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: #121212; color: #ededed; selection-background-color: #3f3f3f;
    selection-color: #ffffff; border: 1px solid #585858; padding: 4px; outline: none; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { background: #282828; border: none; width: 20px; }
QAbstractSpinBox::up-arrow { image: url('@UP@'); width: 10px; height: 10px; }
QAbstractSpinBox::down-arrow { image: url('@DOWN@'); width: 10px; height: 10px; }
QCheckBox, QRadioButton { background: transparent; spacing: 7px; padding: 3px; border: 1px solid transparent; border-radius: 3px; }
QCheckBox:focus, QRadioButton:focus { border-color: #d1d1d1; background: #282828; }
QCheckBox::indicator, QRadioButton::indicator { width: 15px; height: 15px; border: 1px solid #818181; background: #090909; }
QCheckBox::indicator { border-radius: 3px; }
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:checked { background: #ebebeb; border-color: #ebebeb; image: url('@CHECK@'); }
QRadioButton::indicator:checked { background: #ebebeb; border: 4px solid #575757; }
QCheckBox:disabled, QRadioButton:disabled { color: #757575; }
QCheckBox::indicator:disabled { border-color: #454545; background: #272727; }
QGroupBox { background: #090909; border: 1px solid #1c1c1c; border-radius: 6px; margin-top: 14px; padding: 14px 10px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #d6d6d6; padding: 0 5px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QTableView, QTreeView { background: #090909; alternate-background-color: #090909; color: #dedede;
    border: 1px solid #1c1c1c; border-radius: 5px; gridline-color: #303030; outline: none; }
QTableView:focus, QTreeView:focus { border-color: #aaaaaa; }
QTableView::item, QTreeView::item { padding: 6px 8px; border-bottom: 1px solid #121212; }
QTableView::item:selected, QTreeView::item:selected { background: #3f3f3f; color: #ffffff; }
QTableView::item:hover, QTreeView::item:hover { background: #2f2f2f; }
QHeaderView::section { background: #121212; color: #b7b7b7; border: none; border-bottom: 1px solid #454545;
    padding: 9px 8px; font-size: 12px; font-weight: 600; }
QTableCornerButton::section { background: #121212; border: none; }
QTabWidget::pane { border: 1px solid #1c1c1c; border-radius: 5px; background: #090909; padding: 5px; }
QTabBar::tab { background: #121212; color: #a7a7a7; padding: 8px 12px; border: 1px solid #1c1c1c;
    border-bottom: 2px solid transparent; margin-right: 3px; }
QTabBar::tab:selected { background: #333333; color: #f5f5f5; border-bottom-color: #dedede; }
QTabBar::tab:hover { color: #ffffff; background: #1c1c1c; }
QTabBar::tab:focus { border-color: #e9e9e9; }
QMenu { background: #222222; border: 1px solid #565656; padding: 5px; }
QMenu::item { padding: 7px 22px; border-radius: 3px; }
QMenu::item:selected { background: #404040; color: #ffffff; }
QMenu::item:disabled { color: #767676; }
QMenu::separator { height: 1px; background: #262626; margin: 5px 8px; }
QToolTip { background: #2c2c2c; color: #f4f4f4; border: 1px solid #6a6a6a; padding: 7px; }
QProgressBar { background: #1e1e1e; border: 1px solid #474747; border-radius: 3px; min-height: 9px; color: #e5e5e5; text-align: center; }
QProgressBar::chunk { background: #c4c4c4; border-radius: 2px; }
QScrollBar:vertical { background: #090909; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #535353; min-height: 28px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #838383; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { background: #090909; height: 9px; margin: 0; }
QScrollBar::handle:horizontal { background: #535353; min-width: 28px; border-radius: 4px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QCalendarWidget QWidget { background: #212121; color: #eaeaea; }
QCalendarWidget QAbstractItemView { background: #1a1a1a; color: #e5e5e5; selection-background-color: #595959; }
QCalendarWidget QAbstractItemView::item { padding: 1px; border: none; }
QCalendarWidget QToolButton { border: none; padding: 4px; }
QSplitter::handle { background: #3c3c3c; }
"""


def apply_theme(widget):
    palette = QPalette()
    for name, color in {'Window':'#030303','WindowText':'#e7e7e7','Base':'#090909',
                        'AlternateBase':'#090909','Text':'#e7e7e7','Button':'#121212',
                        'ButtonText':'#e7e7e7','Highlight':'#3f3f3f','HighlightedText':'#ffffff',
                        'PlaceholderText':'#858585','ToolTipBase':'#2c2c2c','ToolTipText':'#f4f4f4','Link':'#e7e7e7'}.items():
        palette.setColor(getattr(QPalette.ColorRole,name), QColor(color))
    for name in ('Text','WindowText','ButtonText'):
        palette.setColor(QPalette.ColorGroup.Disabled,getattr(QPalette.ColorRole,name),QColor('#767676'))
    widget.setPalette(palette)
    style = STYLE.replace('@CHECK@',str(CHART_ASSETS/'ui-check.svg')).replace('@DOWN@',str(CHART_ASSETS/'ui-down.svg')).replace('@UP@',str(CHART_ASSETS/'ui-up.svg'))
    widget.setStyleSheet(style)


def role(widget, name):
    widget.setProperty('role', name)
    return widget


def navigation_icon(index):
    pixmap=QPixmap(40,40)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor('#d1d1d1'),1.5))
    if index==0:
        painter.drawLine(3,15,3,10);painter.drawLine(9,15,9,5);painter.drawLine(15,15,15,2)
    elif index==1:
        painter.drawPolyline([QPointF(2,14),QPointF(7,9),QPointF(11,11),QPointF(17,3)])
        painter.drawLine(12,3,17,3);painter.drawLine(17,3,17,8)
    elif index==2:
        painter.drawRoundedRect(QRectF(3,2,13,16),2,2)
        painter.drawLine(7,6,13,6);painter.drawLine(7,10,13,10);painter.drawLine(7,14,11,14)
    else:
        for y,x in ((4,7),(10,13),(16,6)):
            painter.drawLine(2,y,18,y)
            painter.setBrush(QColor('#030303'))
            painter.drawEllipse(QPointF(x,y),2.2,2.2)
    painter.end()
    return QIcon(pixmap)


class SummaryCards(QFrame):
    """Показывает только готовые строки AnalyticsView; новых расчётов нет."""
    def __init__(self, rows, parent=None):
        super().__init__(parent)
        grid=QGridLayout(self)
        grid.setContentsMargins(0,0,0,0)
        grid.setSpacing(8)
        for index,row in enumerate(rows):
            card=role(QFrame(),'panel')
            layout=QVBoxLayout(card)
            layout.setContentsMargins(12,10,12,10)
            layout.setSpacing(4)
            title=role(QLabel(row[0]),'secondary');title.setWordWrap(True)
            value=role(QLabel(row[1]),'metric')
            caption=role(QLabel('Медиана · '+row[7]),'secondary');caption.setWordWrap(True)
            for item in (title,value,caption):
                item.setTextFormat(Qt.TextFormat.PlainText)
                layout.addWidget(item)
            grid.addWidget(card,index//3,index%3)
        self.setAccessibleName('Карточки шести показателей')
