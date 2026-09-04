from __future__ import annotations
from PySide6.QtCore import QObject, Qt, QRect, QPoint, Signal, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QPixmap, QImage, QFont
from PySide6.QtWidgets import QApplication, QWidget
from .models import Region
from .native import monitors


def region_from_drag(start, end, logical_width, logical_height, monitor):
    """Convert local Qt DIP coordinates using this monitor's physical bounds."""
    x0, x1 = sorted((start.x(), end.x()))
    y0, y1 = sorted((start.y(), end.y()))
    left = round(max(0, x0) * monitor["width"] / logical_width)
    top = round(max(0, y0) * monitor["height"] / logical_height)
    right = round(min(logical_width, x1) * monitor["width"] / logical_width)
    bottom = round(min(logical_height, y1) * monitor["height"] / logical_height)
    return Region(monitor["left"] + left, monitor["top"] + top, right - left, bottom - top)


class Overlay(QWidget):
    selected = Signal(object)
    cancelled = Signal()

    def __init__(self, screen, monitor, background):
        super().__init__()
        self.monitor = monitor
        self.background = background
        self.start = None
        self.end = None
        self.tip = "拖动框选聊天区域 · 松开确认 · Esc / 右键取消（每次限一块屏幕）"
        self.setWindowTitle("框选聊天截图区域")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(screen.geometry())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.start = event.position().toPoint()
            self.end = self.start
            self.update()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            point = event.position().toPoint()
            self.end = QPoint(max(0, min(self.width(), point.x())), max(0, min(self.height(), point.y())))
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.start is None:
            return
        self.mouseMoveEvent(event)
        try:
            region = region_from_drag(self.start, self.end, self.width(), self.height(), self.monitor)
            self.selected.emit(region)
        except ValueError as exc:
            self.tip = str(exc) + " · 请重新拖动"
            self.start = None
            self.end = None
            self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.background)
        painter.fillRect(self.rect(), QColor(9, 20, 38, 120))
        if self.start is not None and self.end is not None:
            rect = QRect(self.start, self.end).normalized()
            painter.save()
            painter.setClipRect(rect)
            painter.drawPixmap(self.rect(), self.background)
            painter.restore()
            painter.setPen(QPen(QColor("#50d7be"), 2))
            painter.drawRect(rect)
            self.draw_tip(painter, f"{round(rect.width() * self.monitor['width'] / self.width())} × "
                          f"{round(rect.height() * self.monitor['height'] / self.height())} px", 60)
        self.draw_tip(painter, self.tip, 18)

    def draw_tip(self, painter, text, y):
        painter.setFont(QFont("Microsoft YaHei UI", 11))
        metrics = painter.fontMetrics()
        rect = QRect(20, y, min(self.width() - 40, metrics.horizontalAdvance(text) + 28), 34)
        painter.fillRect(rect, QColor(15, 26, 43, 235))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(rect.adjusted(12, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, text)


class SelectionController(QObject):
    selected = Signal(object, object)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.overlays = []
        self.layout = []

    def start(self):
        try:
            import mss
            self.layout = monitors()
            prepared = []
            with mss.mss() as sct:
                for screen in QApplication.screens():
                    geometry = screen.geometry()
                    ratio = screen.devicePixelRatio()
                    # Qt 6.11 can expose a friendly display name instead of \\.\DISPLAYn.
                    # On Windows Qt retains native screen origins, scaling only sizes.
                    candidates = [m for m in self.layout if
                        m["left"] == geometry.x() and m["top"] == geometry.y()
                        and abs(m["width"] - round(geometry.width() * ratio)) <= 1
                        and abs(m["height"] - round(geometry.height() * ratio)) <= 1]
                    match = candidates[0] if len(candidates) == 1 else None
                    if match is None:
                        raise RuntimeError("无法匹配显示器物理坐标，请检查显示器配置")
                    shot = sct.grab({k: match[k] for k in ("left", "top", "width", "height")})
                    img = QImage(shot.rgb, shot.width, shot.height, shot.width * 3, QImage.Format.Format_RGB888).copy()
                    prepared.append((screen, match, QPixmap.fromImage(img)))
            for screen, monitor, pixmap in prepared:
                overlay = Overlay(screen, monitor, pixmap)
                overlay.selected.connect(self.finish)
                overlay.cancelled.connect(self.cancel)
                self.overlays.append(overlay)
                overlay.show()
            if self.overlays:
                self.overlays[0].activateWindow()
                self.overlays[0].setFocus()
        except Exception as exc:
            self.close_all()
            self.failed.emit(str(exc))

    def close_all(self):
        for overlay in self.overlays:
            overlay.close()
        self.overlays.clear()

    def finish(self, region):
        self.close_all()
        self.selected.emit(region, self.layout)

    def cancel(self):
        self.close_all()
        self.cancelled.emit()
