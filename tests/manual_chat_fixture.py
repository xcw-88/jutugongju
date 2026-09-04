"""Standalone, clearly marked scrollable desktop fixture; never real evidence."""
import sys
from evidence_capture.native import enable_dpi_awareness
enable_dpi_awareness()
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QScrollArea

app = QApplication(sys.argv)
window = QMainWindow()
window.setWindowTitle('模拟聊天窗口 - 软件测试专用')
window.setGeometry(250, 80, 1000, 850)
root = QWidget()
layout = QVBoxLayout(root)
header = QLabel('模拟聊天 / 软件测试专用 / 非真实证据')
header.setStyleSheet('font: bold 20px "Microsoft YaHei UI"; padding: 15px; color: #153858;')
layout.addWidget(header)
scroll = QScrollArea()
scroll.setWidgetResizable(True)
content = QWidget()
messages = QVBoxLayout(content)
messages.setSpacing(20)
for i in range(1, 61):
    label = QLabel(f'第 {i:03d} 条模拟消息\n本消息仅用于验证向上滚动、截图重叠和中文清晰度。\n测试内容，请勿作为案件证据。')
    label.setMinimumHeight(120)
    label.setStyleSheet('background: #e0eefb; border-radius: 10px; padding: 18px; font: 20px "Microsoft YaHei UI";')
    messages.addWidget(label)
    if i % 5 == 0:
        photo = QLabel('模拟图片等待加载…')
        photo.setFixedHeight(150)
        photo.setStyleSheet('background: #d4eee5; padding: 20px; font: 22px "Microsoft YaHei UI"; color: #245745;')
        messages.addWidget(photo)
        QTimer.singleShot(1800, lambda p=photo: p.setText('模拟图片已加载 / 绿色测试画面'))
scroll.setWidget(content)
layout.addWidget(scroll)
window.setCentralWidget(root)
window.show()
QTimer.singleShot(300, lambda: scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum()))
sys.exit(app.exec())
