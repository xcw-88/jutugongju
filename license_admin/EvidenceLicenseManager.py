"""Private license issuer. Keep this program and its embedded key confidential."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QDateEdit, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from evidence_capture.licensing import LicenseError, issue_license, normalize_machine_code
from evidence_capture.models import safe_name


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


class Manager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("聊天软件截屏助手授权管理器（请勿外发）")
        self.setMinimumSize(820, 650)
        root = QWidget()
        layout = QVBoxLayout(root)
        warning = QLabel("私钥管理工具：只能由软件所有者保管。不要把本程序或 license_private.pem 发给客户。")
        warning.setWordWrap(True)
        warning.setStyleSheet("font-weight: bold; color: #a33131; background: #fff0f0; padding: 12px;")
        layout.addWidget(warning)
        form = QFormLayout()
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("例如：某某公司 / 张三")
        form.addRow("授权对象 *", self.customer)
        self.machine = QLineEdit()
        self.machine.setPlaceholderText("粘贴客户软件显示的机器码")
        form.addRow("客户机器码 *", self.machine)
        expiry_row = QHBoxLayout()
        self.perpetual = QCheckBox("永久授权")
        self.perpetual.setChecked(True)
        self.expires = QDateEdit(QDate.currentDate().addYears(1))
        self.expires.setCalendarPopup(True)
        self.expires.setDisplayFormat("yyyy-MM-dd")
        self.expires.setEnabled(False)
        self.perpetual.toggled.connect(lambda checked: self.expires.setEnabled(not checked))
        expiry_row.addWidget(self.perpetual)
        expiry_row.addWidget(self.expires)
        expiry_row.addStretch(1)
        form.addRow("有效期", expiry_row)
        layout.addLayout(form)
        create = QPushButton("生成授权")
        create.clicked.connect(self.create_license)
        layout.addWidget(create)
        self.token = QPlainTextEdit()
        self.token.setReadOnly(True)
        self.token.setPlaceholderText("生成后在此显示授权码")
        layout.addWidget(self.token, 1)
        self.status = QLabel("等待生成授权")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        copy = QPushButton("复制授权码")
        copy.clicked.connect(self.copy_token)
        buttons.addWidget(copy)
        save = QPushButton("保存 .license 文件")
        save.clicked.connect(self.save_token)
        buttons.addWidget(save)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.setCentralWidget(root)

    def values(self):
        customer = self.customer.text().strip()
        machine = normalize_machine_code(self.machine.text())
        expires = None
        if not self.perpetual.isChecked():
            qdate = self.expires.date()
            expires = date(qdate.year(), qdate.month(), qdate.day())
        return customer, machine, expires

    def create_license(self):
        try:
            customer, machine, expires = self.values()
            private_key = resource_path("license_private.pem").read_bytes()
            token = issue_license(private_key, customer, machine, expires)
        except (LicenseError, OSError) as exc:
            QMessageBox.warning(self, "无法生成授权", str(exc))
            return
        self.token.setPlainText(token)
        expiry = expires.isoformat() if expires else "永久"
        self.status.setText(f"已生成 · {customer} · {machine} · 有效期：{expiry}")

    def copy_token(self):
        token = self.token.toPlainText().strip()
        if token:
            QApplication.clipboard().setText(token)
            self.status.setText("授权码已复制；可发送授权码或 .license 文件给客户")

    def save_token(self):
        token = self.token.toPlainText().strip()
        if not token:
            QMessageBox.warning(self, "尚未生成", "请先生成授权")
            return
        default = safe_name(self.customer.text().strip() or "客户") + ".license"
        filename, _ = QFileDialog.getSaveFileName(self, "保存授权文件", default,
                                                   "授权文件 (*.license)")
        if not filename:
            return
        try:
            Path(filename).write_text(token + "\n", encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.status.setText(f"授权文件已保存：{filename}")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("聊天软件截屏助手授权管理器")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyle("Fusion")
    window = Manager()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
