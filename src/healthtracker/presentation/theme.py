"""Общая монохромная тема и небольшие компоненты Presentation. Без данных/расчётов."""
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPen, QPixmap, QTextCharFormat
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QListView, QStyledItemDelegate, QProxyStyle, QStyle, QToolButton, QVBoxLayout, QWidget, QMessageBox

CHART_ASSETS = Path(__file__).resolve().parents[1] / 'resources/chart'

STYLE = """
QWidget { color: #e7e7e7; font-family: "Noto Sans", "Inter", sans-serif; font-size: 13px; font-weight: 500;
    selection-background-color: #262626; selection-color: #ffffff; }
QMainWindow, QDialog, QWidget#appBody { background: #030303; }
QLabel { background: transparent; border: none; padding: 0; }
QLabel[role="clockDate"] { color: #f2f2f2; font-size: 14px; font-weight: 600; }
QLabel[role="clockTime"] { color: #f2f2f2; font-size: 18px; font-weight: 600; }
QLabel[role="pageTitle"] { font-size: 21px; font-weight: 600; color: #f5f5f5; }
QLabel[role="sectionTitle"] { font-size: 16px; font-weight: 600; color: #ebebeb; }
QLabel[role="fieldTitle"] { font-weight: 600; color: #dedede; padding-top: 5px; }
QTreeWidget#diaryFeed { background: #030303; border: none; }
QTreeWidget#diaryFeed::item { border: none; padding: 0; }
QLabel[role="eyebrow"] { font-size: 11px; font-weight: 600; color: #a4a4a4; }
QLabel[role="secondary"] { color: #929292; font-size: 12px; }
QLabel[role="metric"] { font-size: 24px; font-weight: 600; color: #f5f5f5; }
QLabel[role="notice"] { background: #101010; border: 1px solid #303030; border-radius: 8px; padding: 8px 10px; }
QLabel[role="status"] { color: #a5a5a5; padding: 3px 0; font-size: 12px; }
QFrame[role="panel"] { background: transparent; border: none; border-radius: 8px; }
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
QPushButton, QToolButton { background: #0b0b0b; color: #ededed; border: 1px solid #252525;
    border-radius: 8px; padding: 6px 10px; min-height: 20px; }
QPushButton:hover, QToolButton:hover { background: #191919; border-color: #383838; color: #ffffff; }
QPushButton:pressed, QToolButton:pressed { background: #252525; border-color: #555555; }
QPushButton:checked, QToolButton:checked { background: #383838; color: #ffffff; border-color: #ababab; }
QPushButton[kind="primary"] { background: #1c1c1c; color: #f2f2f2; border-color: #383838; font-weight: 600; }
QPushButton[kind="primary"]:hover { background: #252525; border-color: #555555; }
QPushButton[kind="primary"]:pressed { background: #303030; }
QPushButton:disabled, QToolButton:disabled { color: #717171; background: #090909; border-color: #1c1c1c; }
QPushButton:focus, QToolButton:focus { border-color: #f4f4f4; }
QLineEdit, QComboBox, QAbstractSpinBox, QTextEdit, QPlainTextEdit { background: #090909; color: #ececec;
    border: 1px solid #1c1c1c; border-radius: 8px; padding: 6px 8px; min-height: 18px; }
QTextEdit, QPlainTextEdit[readOnly="false"] { min-height: 36px; }
QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover { border-color: #707070; }
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus { border-color: #e9e9e9; }
QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled, QTextEdit:disabled { color: #797979; border-color: #1c1c1c; background: #090909; }
QAbstractSpinBox QLineEdit, QComboBox QLineEdit { border: none; background: transparent; padding: 0; min-height: 0; }
QComboBox { padding: 6px 28px 6px 10px; min-height: 20px; border-radius: 8px; background: #0b0b0b; border-color: #252525; }
QDateEdit::drop-down, QDateTimeEdit::drop-down { border: none; width: 24px; background: transparent; }
QDateEdit::down-arrow, QDateTimeEdit::down-arrow { image: url('@DOWN@'); width: 12px; height: 12px; }
QComboBox::drop-down { width: 25px; border: none; }
QComboBox::down-arrow { image: url('@DOWN@'); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: #090909; color: #ededed;
    selection-background-color: #202020; selection-color: #f2f2f2;
    border: 1px solid #252525; padding: 3px; outline: none; }
QComboBox QAbstractItemView::item { min-height: 22px; padding: 4px 10px; border: none; }
QComboBox QAbstractItemView::item:selected { background: #202020; color: #f2f2f2; }
QComboBox QAbstractItemView QWidget { background: #090909; }
QFrame#chartSettingsPopup { background: #0b0b0b; border: 1px solid #292929; border-radius: 12px; }
QFrame#comboPopup { background: #030303; border: none; padding: 0; }
QListView#floatingOptions { background: #030303; border: none; padding: 0; }
QListView#floatingOptions QWidget { background: #030303; }
QPushButton[kind="icon"], QToolButton[kind="icon"] { padding: 0; min-height: 34px; max-height: 34px; min-width: 34px; max-width: 34px; border-radius: 9px; }
QToolButton[kind="icon"]::menu-indicator { image: none; width: 0; }
QListWidget#navigation[collapsed="true"]::item { padding: 10px 7px; }

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
QGroupBox { background: transparent; border: none; border-top: 1px solid #242424; border-radius: 0; margin-top: 14px; padding: 14px 10px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #d6d6d6; padding: 0 5px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QTableView, QTreeView { background: #090909; alternate-background-color: #090909; color: #dedede;
    border: none; border-radius: 8px; gridline-color: #242424; outline: none; }
QTableView:focus, QTreeView:focus { border-color: #aaaaaa; }
QTableView::item, QTreeView::item { padding: 6px 8px; border-bottom: 1px solid #121212; }
QTableView::item:selected, QTreeView::item:selected { background: #202020; color: #ffffff; }
QTableView::item:hover, QTreeView::item:hover { background: #191919; }
QHeaderView::section { background: #030303; color: #929292; border: none; border-bottom: 1px solid #242424;
    padding: 9px 8px; font-size: 12px; font-weight: 600; }
QTableCornerButton::section { background: #121212; border: none; }
QTabWidget::pane { border: none; background: #030303; padding: 5px 0; }
QTabBar::tab { background: #030303; color: #a7a7a7; padding: 8px 12px; border: none;
    border-bottom: 2px solid transparent; margin-right: 3px; }
QTabBar::tab:selected { background: #101010; color: #f5f5f5; border-bottom-color: #dedede; }
QTabBar::tab:hover { color: #ffffff; background: #1c1c1c; }
QTabBar::tab:focus { border-color: #e9e9e9; }
QMenu { background: #090909; border: 1px solid #252525; border-radius: 8px; padding: 5px; }
QMenu::item { padding: 7px 22px; border-radius: 3px; }
QMenu::item:selected { background: #202020; color: #ffffff; }
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
QCalendarWidget QWidget { background: #0b0b0b; color: #eaeaea; }
QCalendarWidget QAbstractItemView { background: #0b0b0b; color: #e5e5e5; selection-background-color: #595959; }
QCalendarWidget QAbstractItemView::item { padding: 1px; border: none; }
QCalendarWidget QToolButton { border: none; padding: 4px; }
QSplitter::handle { background: #3c3c3c; }
"""


class ComboStyle(QProxyStyle):
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ComboBox_Popup:
            return 0
        return super().styleHint(hint, option, widget, returnData)


class FloatingOptionDelegate(QStyledItemDelegate):
    """Карточки рисует delegate; стандартный Qt сохраняет выбор/фокус/клавиатуру."""
    def __init__(self, view):
        super().__init__(view)
        self.hovered_row = -1
        view.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.Leave):
            self.hovered_row = (self.parent().indexAt(event.position().toPoint()).row()
                                if event.type() == QEvent.Type.MouseMove else -1)
            watched.update()
        return super().eventFilter(watched, event)

    def sizeHint(self, option, index):
        return QSize(super().sizeHint(option, index).width() + 24, 40)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = index.row() == self.hovered_row or bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        rect = QRectF(option.rect).adjusted(4, 3, -4, -3)
        painter.setPen(QPen(QColor('#666666'), 1) if focused else Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#2b2b2b' if selected else '#242424' if hovered else '#111111'))
        painter.drawRoundedRect(rect, 9, 9)
        painter.setPen(QColor('#ededed' if option.state & QStyle.StateFlag.State_Enabled else '#777777'))
        painter.setFont(option.font)
        text = option.fontMetrics.elidedText(str(index.data() or ''), Qt.TextElideMode.ElideRight, int(rect.width()-22))
        painter.drawText(rect.adjusted(11, 0, -11, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.restore()


def action_icon(name):
    path=str(CHART_ASSETS / ('ui-' + name + '.svg'))
    icon=QIcon(path)
    # Qt не должен подкрашивать выбранный SVG системным цветом Plasma.
    for mode in (QIcon.Mode.Active,QIcon.Mode.Selected):
        for state in (QIcon.State.Off,QIcon.State.On):icon.addFile(path,QSize(),mode,state)
    return icon


def compact_combo(combo):
    """Стандартный QListView вместо зависящего от платформы menu-delegate."""
    style = ComboStyle("Fusion")
    style.setParent(combo)
    combo.setStyle(style)
    view = QListView(combo)
    view.setObjectName("floatingOptions")
    view.setMouseTracking(True)
    view.viewport().setMouseTracking(True)
    view.setItemDelegate(FloatingOptionDelegate(view))
    view.setUniformItemSizes(True)
    combo.setView(view)
    combo.setMaxVisibleItems(8)
    view.window().setObjectName('comboPopup')


def apply_theme(widget):
    families = QFontDatabase.families()
    family = next((name for name in ('Noto Sans', 'Inter', 'DejaVu Sans') if name in families), 'sans-serif')
    font = QFont(family)
    font.setPixelSize(13)
    font.setWeight(QFont.Weight.Medium)
    widget.setFont(font)
    palette = QPalette()
    for name, color in {'Window':'#030303','WindowText':'#e7e7e7','Base':'#090909',
                        'AlternateBase':'#090909','Text':'#e7e7e7','Button':'#121212',
                        'ButtonText':'#e7e7e7','Highlight':'#3f3f3f','HighlightedText':'#ffffff',
                        'PlaceholderText':'#858585','ToolTipBase':'#2c2c2c','ToolTipText':'#f4f4f4','Link':'#e7e7e7'}.items():
        palette.setColor(getattr(QPalette.ColorRole,name), QColor(color))
    for name in ('Text','WindowText','ButtonText'):
        palette.setColor(QPalette.ColorGroup.Disabled,getattr(QPalette.ColorRole,name),QColor('#767676'))
    widget.setPalette(palette)
    style = STYLE.replace('@CHECK@',str(CHART_ASSETS/'ui-check.svg')).replace('@DOWN@',str(CHART_ASSETS/'ui-down.svg')).replace('@UP@',str(CHART_ASSETS/'ui-up.svg')).replace('@NOTICE@',str(CHART_ASSETS/'ui-notice.svg'))
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
    icon=QIcon(pixmap)
    for mode in (QIcon.Mode.Active,QIcon.Mode.Selected):
        icon.addPixmap(pixmap,mode)
    return icon


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


def icon_button(button, name, text):
    button.setText('')
    button.setProperty('kind','icon')
    button.setIcon(action_icon(name))
    button.setIconSize(QSize(20,20))
    button.setFixedSize(36,36)
    button.setToolTip(text)
    button.setAccessibleName(text)
    return button


def quiet_table(view):
    view.setShowGrid(False)
    view.setAlternatingRowColors(False)
    view.verticalHeader().hide()
    view.verticalHeader().setDefaultSectionSize(38)
    view.setWordWrap(False)


class Disclosure(QWidget):
    """Общие раскрываемые подробности без изменения содержимого и его сигналов."""
    def __init__(self, title, content, parent=None):
        super().__init__(parent)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(8)
        self.toggle=QToolButton()
        self.toggle.setText(title)
        self.toggle.setAccessibleName(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(self.toggle,0,Qt.AlignmentFlag.AlignLeft)
        self.content=content
        layout.addWidget(content)
        content.hide()
        self.toggle.toggled.connect(content.setVisible)
        self.toggle.toggled.connect(lambda opened:self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow))


def style_calendar(field):
    calendar=field.calendarWidget()
    if calendar is not None:
        weekend=QTextCharFormat()
        weekend.setForeground(QColor('#929292'))
        for day in (Qt.DayOfWeek.Saturday,Qt.DayOfWeek.Sunday):
            calendar.setWeekdayTextFormat(day,weekend)


def style_message_box(box):
    """Монохромное предупреждение; кнопки и выбранный default не меняются."""
    box.setIconPixmap(action_icon('notice').pixmap(28,28))
    for button in box.buttons():
        button.setIcon(QIcon())


def show_warning(parent,title,text):
    box=QMessageBox(QMessageBox.Icon.Warning,title,text,QMessageBox.StandardButton.Ok,parent)
    box.button(QMessageBox.StandardButton.Ok).setText('Закрыть')
    style_message_box(box)
    return box.exec()
