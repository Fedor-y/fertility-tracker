"""Одна панель над графиком; существующие ChartControls сохраняют значения и сигналы."""
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QLayout, QScrollArea, QVBoxLayout, QWidget


class ChartSettingsPopup(QFrame):
    def __init__(self, controls, anchor, parent):
        super().__init__(parent)
        self.setObjectName('chartSettingsPopup')
        self.setAccessibleName('Настройки графика')
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.controls, self.anchor = controls, anchor
        self._fit_pending = False
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(14,14,14,14)
        layout.setSpacing(10)
        title = QLabel('Настройки графика')
        title.setProperty('role','sectionTitle')
        layout.addWidget(title)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(controls)
        layout.addWidget(self.scroll,1)
        controls.changed.connect(self._schedule_fit)
        controls.details_button.toggled.connect(self._schedule_fit)
        controls.layout().setAlignment(Qt.AlignmentFlag.AlignTop)
        controls.installEventFilter(self)
        parent.installEventFilter(self)
        QApplication.instance().applicationStateChanged.connect(self._application_state_changed)
        self.hide()

    def paintEvent(self,event):
        # Явный фон не зависит от отрисовки QFrame стилем платформы.
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#292929'),1))
        painter.setBrush(QColor('#0b0b0b'))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),12,12)

    def _schedule_fit(self, *args):
        if self.isVisible() and not self._fit_pending:
            self._fit_pending = True
            QTimer.singleShot(0,self._fit)

    def _fit(self):
        self._fit_pending = False
        owner = self.parentWidget()
        screen = self.anchor.screen()
        screen_bounds = screen.geometry() if owner.isFullScreen() else screen.availableGeometry()
        bounds = screen_bounds.intersected(QRect(owner.mapToGlobal(QPoint(0,0)),owner.size()))
        width = min(max(380,self.controls.minimumSizeHint().width()+44),bounds.width()-16)
        self.controls.setFixedWidth(width-42)
        self.controls.layout().activate()
        height = min(self.controls.sizeHint().height()+66,bounds.height()-16)
        self.setMaximumSize(bounds.width()-16,bounds.height()-16)
        self.resize(width,height)
        point = self.anchor.mapToGlobal(QPoint(0,self.anchor.height()+6))
        if point.y()+height > bounds.bottom()-8:
            right = self.anchor.mapToGlobal(QPoint(self.anchor.width()+8,0)).x()
            left = self.anchor.mapToGlobal(QPoint(-width-8,0)).x()
            if right+width <= bounds.right()-8:point.setX(right)
            elif left >= bounds.left()+8:point.setX(left)
        global_point=QPoint(max(bounds.left()+8,min(point.x(),bounds.right()-width-7)),
                            max(bounds.top()+8,min(point.y(),bounds.bottom()-height-7)))
        self.move(owner.mapFromGlobal(global_point))

    def show_for_anchor(self):
        for widget in self.parentWidget().findChildren(QWidget):
            widget.installEventFilter(self)
        self._fit()
        self.show()
        self.raise_()
        self._fit()
        self.controls.period.setFocus(Qt.FocusReason.PopupFocusReason)

    def eventFilter(self, watched, event):
        if self.isVisible():
            if (watched is self.parentWidget() and event.type()==QEvent.Type.Resize
                    or watched is self.anchor and event.type()==QEvent.Type.Move):
                self._schedule_fit()
            elif watched is self.controls and event.type()==QEvent.Type.LayoutRequest:
                self._schedule_fit()
            elif event.type()==QEvent.Type.MouseButtonPress and isinstance(watched,QWidget):
                inside=self._belongs(watched) or watched is self.anchor
                nested=QApplication.activePopupWidget()
                if nested is not None and self._belongs(nested):inside=True
                if watched is self and not self.rect().contains(event.position().toPoint()):inside=False
                if not inside:self.hide()
        return super().eventFilter(watched,event)

    def _belongs(self, widget):
        while widget is not None:
            if widget is self:return True
            widget=widget.parent()
        return False

    def _application_state_changed(self, state):
        if state != Qt.ApplicationState.ApplicationActive:
            self.hide()

    def event(self,event):
        if event.type()==QEvent.Type.ShortcutOverride and event.key()==Qt.Key.Key_Escape:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:
            self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)

    def showEvent(self,event):
        with QSignalBlocker(self.anchor):self.anchor.setChecked(True)
        super().showEvent(event)

    def hideEvent(self,event):
        self.controls.period.hidePopup()
        self.controls.mode.hidePopup()
        with QSignalBlocker(self.anchor):self.anchor.setChecked(False)
        super().hideEvent(event)
