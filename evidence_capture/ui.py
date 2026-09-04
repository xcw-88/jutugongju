from __future__ import annotations
import json
import logging
import sys
import threading
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QImageReader, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QDoubleSpinBox,
    QCheckBox, QComboBox, QFrame, QFileDialog, QMessageBox, QProgressBar, QListWidget,
    QListWidgetItem, QScrollArea, QDialog, QStyle)

from .capture import run_capture
from . import __version__
from .models import (Region, CaptureOptions, EvidenceInfo, atomic_json, config_path,
                     create_session, default_output, load_config)
from .native import monitors
from .pdf_export import export_pdf, numbered_images
from .selector import SelectionController
from .licensing import (LicenseError, install_license, license_summary, machine_code,
                        validate_installed_license)

STYLE = """
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 13px; color: #1d2b3e; }
QMainWindow, QDialog { background: #f0f3f7; }
QFrame#card { background: white; border: 1px solid #dde4ed; border-radius: 12px; }
QLabel#heading { font-size: 24px; font-weight: 700; color: #122b4d; }
QLabel#section { font-size: 16px; font-weight: 700; color: #17395f; }
QLabel#muted { color: #64748b; }
QLabel#badge { color: #176b57; background: #e1f4ed; border-radius: 6px; padding: 5px 10px; }
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
  background: #fbfcfe; border: 1px solid #cdd7e4; border-radius: 6px; padding: 7px;
  selection-background-color: #1e5d9c; }
QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #307dc1; }
QPushButton { background: #ffffff; border: 1px solid #c7d4e3; border-radius: 7px;
  padding: 8px 14px; font-weight: 600; }
QPushButton:hover { background: #eff5fc; border-color: #7da4cf; }
QPushButton#primary { background: #205e9f; border-color: #205e9f; color: white; }
QPushButton#primary:hover { background: #164d87; }
QPushButton#stop { color: #b03535; }
QPushButton:disabled { color: #9ba8b7; background: #eef1f5; border-color: #e0e5ec; }
QProgressBar { background: #e7edf5; border: none; border-radius: 5px; height: 10px; text-align: center; }
QProgressBar::chunk { background: #29987e; border-radius: 5px; }
QListWidget { background: #f9fbfd; border: 1px solid #e1e7ee; border-radius: 7px; }
QListWidget::item { padding: 5px; border-bottom: 1px solid #e8edf3; }
QListWidget::item:selected { background: #deecfa; color: #153858; }
QCheckBox { spacing: 8px; }
QScrollArea { border: none; background: transparent; }
"""


def app_icon():
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#205e9f"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(18, 12, 29, 40, 3, 3)
    p.setPen(QColor("#205e9f"))
    for y in (23, 31, 39):
        p.drawLine(24, y, 40, y)
    p.end()
    return QIcon(pix)


class ActivationDialog(QDialog):
    def __init__(self, message="", parent=None):
        super().__init__(parent)
        self.payload = None
        self.setWindowTitle("软件授权")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(700)
        layout = QVBoxLayout(self)
        heading = QLabel("聊天软件截屏助手 · 软件激活")
        heading.setObjectName("section")
        layout.addWidget(heading)
        help_text = QLabel("请将本机机器码发送给授权管理员，再粘贴授权码或导入 .license 文件。授权与本机绑定。")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        machine_row = QHBoxLayout()
        self.machine_edit = QLineEdit(machine_code())
        self.machine_edit.setReadOnly(True)
        self.machine_edit.setAccessibleName("本机机器码")
        machine_row.addWidget(self.machine_edit, 1)
        copy_machine = QPushButton("复制机器码")
        copy_machine.clicked.connect(lambda: QApplication.clipboard().setText(self.machine_edit.text()))
        machine_row.addWidget(copy_machine)
        layout.addWidget(QLabel("本机机器码"))
        layout.addLayout(machine_row)
        layout.addWidget(QLabel("授权码"))
        self.token_edit = QPlainTextEdit()
        self.token_edit.setAccessibleName("授权码")
        self.token_edit.setPlaceholderText("粘贴以 EVC1. 开头的授权码，或点击“导入授权文件”")
        self.token_edit.setFixedHeight(145)
        layout.addWidget(self.token_edit)
        self.status = QLabel(message or "尚未激活")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #a33131;")
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        import_button = QPushButton("导入授权文件")
        import_button.clicked.connect(self.import_file)
        buttons.addWidget(import_button)
        buttons.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(close_button)
        activate = QPushButton("激活")
        activate.setObjectName("primary")
        activate.clicked.connect(self.activate)
        buttons.addWidget(activate)
        layout.addLayout(buttons)

    def import_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "选择授权文件", "",
                                                   "授权文件 (*.license);;所有文件 (*)")
        if not filename:
            return
        try:
            self.token_edit.setPlainText(Path(filename).read_text(encoding="utf-8").strip())
            self.status.setText("授权文件已读取，请点击“激活”")
            self.status.setStyleSheet("color: #176b57;")
        except OSError as exc:
            self.status.setText(f"授权文件读取失败：{exc}")
            self.status.setStyleSheet("color: #a33131;")

    def activate(self):
        try:
            self.payload = install_license(self.token_edit.toPlainText())
        except (LicenseError, OSError) as exc:
            self.status.setText(str(exc))
            self.status.setStyleSheet("color: #a33131;")
            return
        self.status.setText("激活成功")
        self.status.setStyleSheet("color: #176b57;")
        self.accept()


def request_authorization(parent=None, initial_error=""):
    try:
        return validate_installed_license()
    except (LicenseError, OSError) as exc:
        dialog = ActivationDialog(initial_error or str(exc), parent)
        return dialog.payload if dialog.exec() == QDialog.DialogCode.Accepted else None


class Job(QThread):
    status = Signal(str)
    progress = Signal(dict)

    def __init__(self, kind, folder, info, region=None, options=None, reverse=True, parent=None):
        super().__init__(parent)
        self.kind, self.folder, self.info = kind, folder, info
        self.region, self.options, self.reverse = region, options, reverse
        self.stop = threading.Event()
        self.result = None
        self.error = ""

    def run(self):
        try:
            if self.kind == "capture":
                self.result = run_capture(self.folder, self.info, self.region, self.options,
                                          self.stop, self.status.emit, self.progress.emit)
            else:
                self.result = export_pdf(self.folder, self.info, self.reverse, self.status.emit)
        except Exception as exc:
            logging.exception("Background operation failed")
            self.error = str(exc)


class MainWindow(QMainWindow):
    def __init__(self, auto_select=True, license_info=None):
        super().__init__()
        self.setWindowTitle("聊天软件截屏助手")
        self.setWindowIcon(app_icon())
        self.resize(1080, 900)
        self.setMinimumSize(820, 630)
        self.config, config_warning = load_config()
        self.region = None
        self.region_layout = None
        self.folder = None
        self.pdf_path = None
        self.job = None
        self.closing = False
        self.active_info = None
        self.auto_pdf_for_job = False
        self.reverse_for_job = True
        self.license_info = license_info
        self.selector = SelectionController(self)
        self.selector.selected.connect(self.on_selected)
        self.selector.cancelled.connect(self.restore_window)
        self.selector.failed.connect(self.selection_failed)
        self.build_ui()
        self.restore_config()
        self.set_status(config_warning or "准备就绪 · 请按所选滚动方向定位聊天起点")
        if auto_select:
            QTimer.singleShot(400, self.select_region)

    def label(self, text, name=None):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        if name:
            label.setObjectName(name)
        return label

    def card(self, title):
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(self.label(title, "section"))
        return frame, layout

    def build_ui(self):
        outer = QWidget()
        root = QVBoxLayout(outer)
        root.setContentsMargins(26, 20, 26, 18)
        root.setSpacing(14)
        self.setCentralWidget(outer)
        header = QHBoxLayout()
        title = QVBoxLayout()
        heading = self.label("聊天软件截屏助手", "heading")
        heading.setWordWrap(False)
        title.addWidget(heading)
        title.addWidget(self.label("框选聊天 · 双向采集 · 编号归档 · A4 证据材料", "muted"))
        header.addLayout(title, 1)
        badge = self.label(f"V{__version__}  /  本地处理", "badge")
        badge.setFixedHeight(32)
        header.addWidget(badge)
        if self.license_info:
            badge.setToolTip(f"已授权给：{self.license_info['customer']}")
            license_button = QPushButton("授权信息")
            license_button.clicked.connect(self.show_license_info)
            header.addWidget(license_button)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("content")
        content.setStyleSheet("QWidget#content { background: #f0f3f7; }")
        stack = QVBoxLayout(content)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(14)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        top = QHBoxLayout()
        top.setSpacing(14)
        self.info_card, info_layout = self.card("01  证据说明")
        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.fields = {}
        for row, (key, label, placeholder) in enumerate([
            ("name", "证据名称 *", "例如：某项目与陈庆工作沟通"),
            ("material_title", "材料标题", "可自定义；留空则不显示标题"),
            ("subject", "对象", "填写聊天对象"),
            ("identity", "身份", "填写对象身份"),
            ("time_range", "时间范围", "例如：2026.08.01 至 2026.08.31"),
        ]):
            edit = QLineEdit()
            edit.setMaxLength(160)
            edit.setPlaceholderText(placeholder)
            edit.setAccessibleName(label)
            self.fields[key] = edit
            if key == "material_title":
                edit.setText("项目工作沟通记录")
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(edit, row, 1)
        self.purpose = QPlainTextEdit()
        self.purpose.setPlaceholderText("填写本组材料需要证明的事项（最多 3000 字）")
        self.purpose.setAccessibleName("证明目的")
        self.purpose.setFixedHeight(94)
        form.addWidget(QLabel("证明目的"), 5, 0, Qt.AlignmentFlag.AlignTop)
        form.addWidget(self.purpose, 5, 1)
        info_layout.addLayout(form)
        info_layout.addWidget(self.label("说明由你填写；完整保存选区截图，不筛选聊天内容。", "muted"))
        top.addWidget(self.info_card, 1)

        self.capture_card, capture_layout = self.card("02  采集设置")
        row = QHBoxLayout()
        self.region_label = self.label("尚未选择截图区域", "muted")
        row.addWidget(self.region_label, 1)
        self.select_button = QPushButton("框选区域")
        self.select_button.clicked.connect(self.select_region)
        row.addWidget(self.select_button)
        capture_layout.addLayout(row)
        direction_row = QHBoxLayout()
        direction_row.addWidget(QLabel("滚动方向"))
        self.direction = QComboBox()
        self.direction.setAccessibleName("滚动方向")
        self.direction.addItem("向上（查看较早记录）", "up")
        self.direction.addItem("向下（查看较新记录）", "down")
        direction_row.addWidget(self.direction, 1)
        capture_layout.addLayout(direction_row)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.wait_spin = QDoubleSpinBox()
        self.wait_spin.setRange(0.5, 120)
        self.wait_spin.setSingleStep(0.5)
        self.wait_spin.setValue(3)
        self.wait_spin.setSuffix(" 秒")
        self.scroll_spin = QSpinBox()
        self.scroll_spin.setRange(1, 20)
        self.scroll_spin.setValue(3)
        self.scroll_spin.setSuffix(" 格 / 次")
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 9999)
        self.count_spin.setValue(20)
        self.count_spin.setSuffix(" 张")
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(3, 30)
        self.delay_spin.setValue(5)
        self.delay_spin.setSuffix(" 秒")
        for index, (label, widget) in enumerate([
            ("加载等待", self.wait_spin), ("滚动幅度", self.scroll_spin),
            ("截图数量上限", self.count_spin), ("开始倒计时", self.delay_spin),
        ]):
            grid.addWidget(QLabel(label), index // 2 * 2, index % 2)
            grid.addWidget(widget, index // 2 * 2 + 1, index % 2)
            widget.setAccessibleName(label)
        capture_layout.addLayout(grid)
        self.order = QComboBox()
        self.order.addItems(["PDF：反向采集顺序（末张到首张）", "PDF：采集顺序（001、002、003…）"])
        capture_layout.addWidget(self.order)
        self.direction_hint = self.label("", "muted")
        capture_layout.addWidget(self.direction_hint)
        self.direction.currentIndexChanged.connect(self.direction_changed)
        self.direction_changed()
        self.auto_pdf = QCheckBox("采集结束后自动生成 PDF")
        self.auto_pdf.setChecked(True)
        capture_layout.addWidget(self.auto_pdf)
        self.stop_unchanged = QCheckBox("滚动后画面连续两次不变，自动结束并保存")
        self.stop_unchanged.setChecked(True)
        self.stop_unchanged.setToolTip("每次滚动后均等待设定的加载时间；可能到达顶部/底部或未能滚动。所有截图仍保留。")
        capture_layout.addWidget(self.stop_unchanged)
        capture_layout.addWidget(self.label("先用 3 张试采，确认相邻截图有重叠；图片未加载时增加等待。", "muted"))
        top.addWidget(self.capture_card, 1)
        stack.addLayout(top)

        self.output_card, output_layout = self.card("03  输出与检查")
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("保存位置"))
        self.output_edit = QLineEdit(str(default_output()))
        self.output_edit.setAccessibleName("保存位置")
        path_row.addWidget(self.output_edit, 1)
        self.browse_button = QPushButton("更改目录")
        self.browse_button.clicked.connect(self.choose_output)
        path_row.addWidget(self.browse_button)
        output_layout.addLayout(path_row)
        preview_row = QHBoxLayout()
        self.images = QListWidget()
        self.images.setIconSize(QSize(54, 54))
        self.images.setMinimumHeight(150)
        self.images.setMaximumHeight(180)
        self.images.itemDoubleClicked.connect(self.view_original)
        preview_row.addWidget(self.images, 1)
        actions = QVBoxLayout()
        self.summary = self.label("尚无截图\n\nPNG 原图保留全部像素\nPDF：A4 竖版，每页一张", "muted")
        actions.addWidget(self.summary)
        self.load_button = QPushButton("打开已有证据目录")
        self.load_button.clicked.connect(self.load_session)
        actions.addWidget(self.load_button)
        self.pdf_button = QPushButton("生成 PDF")
        self.pdf_button.clicked.connect(self.generate_pdf)
        self.pdf_button.setEnabled(False)
        actions.addWidget(self.pdf_button)
        self.open_button = QPushButton("打开输出文件夹")
        self.open_button.clicked.connect(self.open_folder)
        actions.addWidget(self.open_button)
        preview_row.addLayout(actions)
        output_layout.addLayout(preview_row)
        self.session_label = self.label("双击截图可按原始像素检查；导出后请预览 PDF 并试印一页。", "muted")
        self.session_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        output_layout.addWidget(self.session_label)
        stack.addWidget(self.output_card)

        self.status_label = self.label("准备就绪")
        root.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 20)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        root.addWidget(self.progress)
        bottom = QHBoxLayout()
        bottom.addWidget(self.label("采集时保持聊天窗口在前台 · 按 Esc 随时停止", "muted"), 1)
        self.stop_button = QPushButton("停止采集")
        self.stop_button.setObjectName("stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_capture)
        bottom.addWidget(self.stop_button)
        self.start_button = QPushButton("开始采集")
        self.start_button.setObjectName("primary")
        self.start_button.setMinimumWidth(150)
        self.start_button.clicked.connect(self.start_capture)
        bottom.addWidget(self.start_button)
        root.addLayout(bottom)

    def restore_config(self):
        try:
            if self.config.get("region"):
                region = Region(**self.config["region"])
                if self.config.get("monitor_layout") == monitors():
                    self.region = region
                    self.region_layout = self.config["monitor_layout"]
                    self.update_region_label()
            opts = CaptureOptions(**self.config.get("options", {}))
            self.wait_spin.setValue(opts.wait_seconds)
            self.scroll_spin.setValue(opts.scroll_clicks)
            self.count_spin.setValue(opts.count)
            self.delay_spin.setValue(opts.start_delay)
            self.stop_unchanged.setChecked(opts.stop_on_unchanged)
            self.fields["material_title"].setText(str(self.config.get("material_title", "项目工作沟通记录")))
            self.direction.setCurrentIndex(0 if opts.direction == "up" else 1)
            self.output_edit.setText(str(self.config.get("output", default_output())))
            self.order.setCurrentIndex(0 if self.config.get("reverse", opts.direction == "up") else 1)
            self.auto_pdf.setChecked(bool(self.config.get("auto_pdf", True)))
        except (TypeError, ValueError, OSError):
            logging.exception("Ignoring invalid saved configuration")

    def settings(self):
        return CaptureOptions(self.wait_spin.value(), self.scroll_spin.value(),
                              self.count_spin.value(), self.delay_spin.value(), self.direction.currentData(),
                              self.stop_unchanged.isChecked())

    def direction_changed(self, index=None):
        upward = self.direction.currentData() == "up"
        self.order.setCurrentIndex(0 if upward else 1)
        self.direction_hint.setText(
            "从较新记录开始；默认倒序排入 PDF，可手动改页序。" if upward else
            "从较早记录开始；默认按采集顺序排入 PDF，可手动改页序。")

    def info(self):
        result = EvidenceInfo(**{k: v.text().strip() for k, v in self.fields.items()},
                              purpose=self.purpose.toPlainText().strip())
        result.validate()
        return result

    def save_config(self):
        atomic_json(config_path(), dict(region=asdict(self.region) if self.region else None,
            monitor_layout=self.region_layout, options=asdict(self.settings()),
            output=self.output_edit.text(), reverse=self.order.currentIndex() == 0,
            auto_pdf=self.auto_pdf.isChecked(), material_title=self.fields["material_title"].text().strip()))

    def select_region(self):
        if self.job:
            return
        self.hide()
        QTimer.singleShot(350, self.selector.start)

    def on_selected(self, region, layout):
        self.region, self.region_layout = region, layout
        self.update_region_label()
        self.restore_window()
        try:
            self.save_config()
            self.set_status("截图区域已保存 · 填写说明后开始采集")
        except OSError as exc:
            self.show_error(f"区域已选定，但配置保存失败：{exc}")

    def update_region_label(self):
        if self.region:
            r = self.region
            self.region_label.setText(f"{r.width} × {r.height} px\n左 {r.left} · 上 {r.top}")

    def restore_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def selection_failed(self, message):
        self.restore_window()
        self.show_error(message)

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出根目录", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def set_status(self, message):
        self.status_label.setText(message)

    def show_error(self, message):
        self.set_status(message)
        QMessageBox.warning(self, "请检查", message)

    def check_authorization(self):
        try:
            self.license_info = validate_installed_license()
            return True
        except (LicenseError, OSError) as exc:
            renewed = request_authorization(self, str(exc))
            if renewed:
                self.license_info = renewed
                return True
            self.set_status(f"授权无效：{exc}")
            return False

    def show_license_info(self):
        if not self.check_authorization():
            return
        box = QMessageBox(self)
        box.setWindowTitle("授权信息")
        box.setText(license_summary(self.license_info))
        replace_button = box.addButton("更新授权", QMessageBox.ButtonRole.ActionRole)
        box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == replace_button:
            dialog = ActivationDialog(parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.license_info = dialog.payload

    def set_busy(self, busy, capture=False):
        for widget in (self.info_card, self.capture_card, self.output_edit, self.browse_button,
                       self.load_button, self.start_button):
            widget.setEnabled(not busy)
        self.pdf_button.setEnabled(not busy and self.folder is not None and self.images.count() > 0)
        self.images.setEnabled(not busy)
        self.stop_button.setEnabled(busy and capture)
        self.open_button.setEnabled(not busy)

    def start_capture(self):
        if self.job:
            return
        if not self.check_authorization():
            return
        try:
            info = self.info()
            if not self.region:
                raise ValueError("请先框选聊天截图区域")
            if monitors() != self.region_layout:
                raise ValueError("显示器布局发生变化，请重新框选区域")
            if not self.output_edit.text().strip():
                raise ValueError("请选择保存位置")
            options = self.settings()
            self.save_config()
            folder = create_session(Path(self.output_edit.text().strip()).resolve(), info.name)
        except (ValueError, OSError) as exc:
            self.show_error(str(exc))
            return
        self.folder, self.active_info, self.pdf_path = folder, info, None
        self.auto_pdf_for_job = self.auto_pdf.isChecked()
        self.reverse_for_job = self.order.currentIndex() == 0
        self.images.clear()
        self.progress.setRange(0, options.count)
        self.progress.setValue(0)
        self.session_label.setText(str(folder))
        self.set_busy(True, capture=True)
        self.job = Job("capture", folder, info, self.region, options, parent=self)
        self.connect_job()
        self.showMinimized()
        self.job.start()

    def connect_job(self):
        self.job.status.connect(self.set_status)
        self.job.progress.connect(self.add_capture)
        self.job.finished.connect(self.job_finished)

    def add_capture(self, record):
        self.add_image(self.folder / record["file"], record.get("same_as_previous", False))
        self.progress.setValue(self.images.count())
        self.summary.setText(f"已保存 {self.images.count()} 张\n\nPNG 原图完整保留\n双击查看原始像素")

    def add_image(self, path, duplicate=False):
        reader = QImageReader(str(path))
        size = reader.size()
        if size.isValid():
            reader.setScaledSize(size.scaled(54, 54, Qt.AspectRatioMode.KeepAspectRatio))
        icon = QIcon(QPixmap.fromImage(reader.read()))
        item = QListWidgetItem(icon, f"{path.name}    {size.width()} × {size.height()} px" +
                               ("    与上一张相同" if duplicate else ""))
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        self.images.addItem(item)

    def stop_capture(self):
        if self.job and self.job.kind == "capture":
            self.job.stop.set()
            self.set_status("正在停止，保留已保存截图…")
            self.stop_button.setEnabled(False)

    def job_finished(self):
        job = self.job
        self.job = None
        job.deleteLater()
        self.set_busy(False)
        if self.closing:
            self.close()
            return
        self.restore_window()
        if job.error:
            self.show_error(f"操作未完成：{job.error}\n已保存文件保留在：{job.folder}")
            return
        if job.kind == "pdf":
            self.pdf_path = job.result
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.set_status(f"PDF 已生成 · {self.images.count()} 张截图 · {self.pdf_path.name}")
            box = QMessageBox(self)
            box.setWindowTitle("PDF 已生成")
            box.setText(f"文件已保存：\n{self.pdf_path}\n\n请预览内容、页序与清晰度后打印。")
            open_pdf = box.addButton("打开 PDF", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() == open_pdf:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.pdf_path)))
            return
        result = job.result
        count = len(result["images"])
        state = {"completed": "采集完成", "stopped": "已停止采集", "error": "采集异常停止"}[result["status"]]
        if result.get("end_reason") == "unchanged":
            state = "画面连续未变化，已自动结束并保存"
        self.set_status(f"{state} · 已保留 {count} 张截图")
        if result["status"] == "error":
            self.show_error(result.get("message", state))
        elif result["warnings"]:
            boundary = "顶部" if result["capture_direction"] == "up" else "底部"
            self.summary.setText(f"已保存 {count} 张\n含 {len(result['warnings'])} 张重复画面\n请检查滚动及聊天{boundary}")
            self.set_status(f"{state} · 已保留 {count} 张，其中 {len(result['warnings'])} 张与上一张相同")
        if count and self.auto_pdf_for_job and result["status"] != "error":
            QTimer.singleShot(0, lambda: self.generate_pdf(self.active_info, self.reverse_for_job))

    def generate_pdf(self, fixed_info=None, fixed_reverse=None):
        if self.job or self.folder is None:
            return
        if not self.check_authorization():
            return
        try:
            info = fixed_info if isinstance(fixed_info, EvidenceInfo) else self.info()
            info.validate()
        except ValueError as exc:
            self.show_error(str(exc))
            return
        reverse = self.order.currentIndex() == 0 if fixed_reverse is None else fixed_reverse
        self.set_busy(True)
        self.progress.setRange(0, 0)
        self.job = Job("pdf", self.folder, info, reverse=reverse, parent=self)
        self.connect_job()
        self.job.start()

    def load_session(self):
        folder = QFileDialog.getExistingDirectory(self, "选择含 001.png 等原图的证据目录", self.output_edit.text())
        if not folder:
            return
        path = Path(folder)
        try:
            paths = numbered_images(path)
            if not paths:
                raise ValueError("该目录没有 001.png、002.png 形式的截图，请选择具体证据子目录")
            data = json.loads((path / "manifest.json").read_text(encoding="utf-8")) if (path / "manifest.json").exists() else {}
            exports = data.get("pdf_exports", [])
            last_info = exports[-1].get("evidence") if exports else None
            info = EvidenceInfo(**(last_info or data.get("evidence", {"name": path.name})))
            info.validate()
        except (OSError, ValueError, TypeError) as exc:
            self.show_error(str(exc))
            return
        self.folder, self.pdf_path = path, None
        for key, field in self.fields.items():
            field.setText(getattr(info, key))
        self.purpose.setPlainText(info.purpose)
        direction = data.get("capture_direction", "up")
        self.direction.setCurrentIndex(0 if direction == "up" else 1)
        # Loading an older session must use that session's page order, not the
        # direction selected for a different capture. V1 sessions were upward.
        exports = data.get("pdf_exports", [])
        reverse = exports[-1].get("order") == "reverse_capture" if exports else direction == "up"
        self.order.setCurrentIndex(0 if reverse else 1)
        self.images.clear()
        for image in paths:
            self.add_image(image)
        self.summary.setText(f"已载入 {len(paths)} 张\n\nPNG 原图完整保留\n双击查看原始像素")
        self.session_label.setText(str(path))
        self.set_busy(False)
        self.set_status("证据目录已载入 · 可补充说明并重新生成 PDF")

    def view_original(self, item):
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        dialog = QDialog(self)
        dialog.setWindowTitle(f"原图检查 · {path.name} · 100% 像素")
        dialog.resize(850, 700)
        layout = QVBoxLayout(dialog)
        layout.addWidget(self.label("原始像素预览 · 滚动查看全图；关闭后可继续整理", "muted"))
        scroll = QScrollArea()
        image = QLabel()
        pix = QPixmap(str(path))
        pix.setDevicePixelRatio(dialog.devicePixelRatioF())
        image.setPixmap(pix)
        image.resize(pix.deviceIndependentSize().toSize())
        scroll.setWidget(image)
        layout.addWidget(scroll)
        dialog.exec()

    def open_folder(self):
        path = self.folder or Path(self.output_edit.text())
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        else:
            self.show_error("目录尚未创建，请先采集或选择已有目录")

    def closeEvent(self, event):
        if self.job:
            self.closing = True
            if self.job.kind == "capture":
                self.job.stop.set()
            self.set_status("正在保存当前任务，完成后关闭…")
            event.ignore()
            return
        try:
            self.save_config()
        except OSError:
            logging.exception("Failed to save settings on exit")
        self.selector.close_all()
        event.accept()


def main():
    log_dir = config_path().parent
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=log_dir / "application.log", encoding="utf-8", level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
    except OSError:
        logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)
    app.setApplicationName("聊天软件截屏助手")
    app.setOrganizationName("EvidenceCapture")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)
    app.setWindowIcon(app_icon())
    license_info = request_authorization()
    if license_info is None:
        return 2
    # Startup overlay is the normal flow. This switch is useful for development/QA.
    window = MainWindow(auto_select="--no-auto-select" not in sys.argv,
                        license_info=license_info)
    window.show()
    return app.exec()
