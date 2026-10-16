"""Visible native window controls with normal maximize/restore behavior."""

from PyQt5.QtCore import QEvent, QObject, Qt, QRectF, QRect
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QKeySequence
from PyQt5.QtWidgets import (
    QApplication, QHBoxLayout, QShortcut, QStyle, QToolButton, QWidget,
)


def control_icon(kind):
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#385356"), 1.4))
    if kind == QStyle.SP_TitleBarMinButton:
        painter.drawLine(4, 13, 16, 13)
    elif kind == QStyle.SP_TitleBarMaxButton:
        painter.drawRect(QRectF(4, 4, 12, 12))
    elif kind == QStyle.SP_TitleBarNormalButton:
        painter.drawRect(QRectF(7, 3, 10, 10))
        painter.setBrush(QColor("#f4f7f8"))
        painter.drawRect(QRectF(3, 7, 10, 10))
    else:
        painter.drawLine(5, 5, 15, 15)
        painter.drawLine(5, 15, 15, 5)
    painter.end()
    return QIcon(pixmap)


class WindowTitleBar(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.drag_offset = None
        self.before_fullscreen = None
        self.setFixedHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()
        self.minimize_button = self.button("最小化", QStyle.SP_TitleBarMinButton)
        self.maximize_button = self.button("最大化", QStyle.SP_TitleBarMaxButton)
        self.close_button = self.button("关闭", QStyle.SP_TitleBarCloseButton)
        self.close_button.setObjectName("windowClose")
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            layout.addWidget(button)
        self.minimize_button.clicked.connect(window.showMinimized)
        self.maximize_button.clicked.connect(self.toggle_maximize)
        self.close_button.clicked.connect(window.close)
        self.setStyleSheet(
            """
            QToolButton {border:none;border-radius:0;background:transparent;padding:0;}
            QToolButton:hover {background:#e4ebe9;}
            QToolButton#windowClose:hover {background:#e9b7ae;}
        """
        )
        window.installEventFilter(self)
        self.resize_controller = ResizeController(window)
        self.fullscreen_shortcut = QShortcut(QKeySequence("F11"), window)
        self.fullscreen_shortcut.activated.connect(self.toggle_fullscreen)
        self.escape_shortcut = QShortcut(QKeySequence("Esc"), window)
        self.escape_shortcut.activated.connect(self.exit_fullscreen)

    def button(self, text, icon):
        button = QToolButton(self)
        button.setFixedSize(46, 34)
        button.setToolTip(text)
        button.setAccessibleName(text)
        button.setIcon(control_icon(icon))
        return button

    def toggle_maximize(self):
        if self.owner.isFullScreen():
            self.exit_fullscreen()
        elif self.owner.isMaximized():
            self.owner.showNormal()
        else:
            self.owner.showMaximized()
        self.update_state()

    def toggle_fullscreen(self):
        if self.owner.isFullScreen():
            self.exit_fullscreen()
            return
        self.before_fullscreen = (
            self.owner.isMaximized(), QRect(self.owner.normalGeometry())
        )
        self.owner.showFullScreen()

    def exit_fullscreen(self):
        if not self.owner.isFullScreen():
            return
        maximized, geometry = self.before_fullscreen or (False, QRect())
        self.before_fullscreen = None
        if maximized:
            self.owner.showMaximized()
        else:
            self.owner.showNormal()
            if geometry.isValid():
                self.owner.setGeometry(geometry)

    def update_state(self):
        maximized = self.owner.isMaximized() or self.owner.isFullScreen()
        self.maximize_button.setIcon(
            control_icon(
                QStyle.SP_TitleBarNormalButton
                if maximized
                else QStyle.SP_TitleBarMaxButton
            )
        )
        text = "还原" if maximized else "最大化"
        self.maximize_button.setToolTip(text)
        self.maximize_button.setAccessibleName(text)

    def eventFilter(self, obj, event):
        if obj is self.owner and event.type() == QEvent.WindowStateChange:
            self.update_state()
        return super().eventFilter(obj, event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_maximize()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.owner.windowHandle()
            if not handle or not handle.startSystemMove():
                self.drag_offset = (
                    event.globalPos() - self.owner.frameGeometry().topLeft()
                )

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.owner.move(event.globalPos() - self.drag_offset)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None


class ResizeController(QObject):
    """Delegate edge dragging to the platform's window manager through Qt."""

    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() not in (QEvent.MouseMove, QEvent.MouseButtonPress):
            return False
        if (
            not isinstance(obj, QWidget)
            or obj.window() is not self.owner
            or self.owner.isMaximized()
            or self.owner.isFullScreen()
        ):
            return False
        point = self.owner.mapFromGlobal(event.globalPos())
        edges = Qt.Edges()
        if point.x() < 5:
            edges |= Qt.LeftEdge
        if point.x() >= self.owner.width() - 5:
            edges |= Qt.RightEdge
        if point.y() < 5:
            edges |= Qt.TopEdge
        if point.y() >= self.owner.height() - 5:
            edges |= Qt.BottomEdge
        if (
            event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.LeftButton
            and edges
        ):
            handle = self.owner.windowHandle()
            return bool(handle and handle.startSystemResize(edges))
        return False
