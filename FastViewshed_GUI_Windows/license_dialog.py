"""Activation UI and periodic enforcement for the licensed Windows application."""
from datetime import datetime
import json
from pathlib import Path
from PySide6 import QtCore, QtWidgets
from licensing import LicenseError
from professional_ui import STYLE


def license_summary(payload):
    expires = payload['expires_at']
    duration = 'نامحدود' if expires is None else 'تا ' + datetime.fromtimestamp(expires).strftime('%Y-%m-%d %H:%M')
    return payload['customer'] + ' — ' + duration


class ActivationDialog(QtWidgets.QDialog):
    def __init__(self, guard, message='', parent=None):
        super().__init__(parent)
        self.guard = guard
        self.setWindowTitle('فعال‌سازی Fast Viewshed')
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.setStyleSheet(STYLE)
        self.resize(620, 360)
        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel('فعال‌سازی برای این دستگاه')
        title.setObjectName('title')
        layout.addWidget(title)
        text = QtWidgets.QLabel('فایل درخواست را برای صادرکننده بفرستید و فایل لایسنس دریافتی را وارد کنید.\nلایسنس این دستگاه روی رایانهٔ دیگر فعال نمی‌شود.')
        text.setWordWrap(True)
        layout.addWidget(text)
        identity = QtWidgets.QLineEdit(guard.device)
        identity.setReadOnly(True)
        identity.setLayoutDirection(QtCore.Qt.LeftToRight)
        layout.addWidget(identity)
        self.message = QtWidgets.QLabel(message)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        save = QtWidgets.QPushButton('ذخیرهٔ درخواست فعال‌سازی…')
        save.clicked.connect(self.save_request)
        layout.addWidget(save)
        copy = QtWidgets.QPushButton('کپی شناسهٔ دستگاه')
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(guard.device))
        layout.addWidget(copy)
        activate = QtWidgets.QPushButton('انتخاب فایل لایسنس و فعال‌سازی…')
        activate.setObjectName('run')
        activate.clicked.connect(self.choose_license)
        layout.addWidget(activate)
        close = QtWidgets.QPushButton('خروج')
        close.clicked.connect(self.reject)
        layout.addWidget(close)

    def save_request(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'ذخیرهٔ درخواست', 'FastViewshed.fvrequest', 'Activation request (*.fvrequest)')
        if filename:
            try:
                Path(filename).write_text(json.dumps(self.guard.request(), indent=2), encoding='utf-8')
                self.message.setText('درخواست ذخیره شد؛ همین فایل را برای صادرکننده بفرستید.')
            except OSError as exc:
                self.message.setText(str(exc))

    def choose_license(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'فایل لایسنس', '', 'Fast Viewshed license (*.fvlicense)')
        if filename:
            self.import_license(filename)

    def import_license(self, filename):
        try:
            payload = self.guard.activate(filename)
            self.message.setText('فعال شد: ' + license_summary(payload))
            self.accept()
            return True
        except (OSError, LicenseError) as exc:
            self.message.setText(str(exc))
            return False


def enforce_runtime_license(window, guard):
    window.license_guard = guard
    window._license_exit_requested = False
    window._license_check_busy = False
    timer = QtCore.QTimer(window)
    timer.setInterval(15000)

    def check():
        if window._license_check_busy:
            return
        try:
            guard.check()
            return
        except LicenseError as exc:
            message = str(exc)
        window._license_check_busy = True
        window.cancel_event.set()
        window.centralWidget().setEnabled(False)
        dialog = ActivationDialog(guard, message, window)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            window.centralWidget().setEnabled(True)
            window.license_label.setText('لایسنس فعال: ' + license_summary(guard.check()))
        else:
            timer.stop()
            window._license_exit_requested = True
            if window.thread is None:
                window.close()
        window._license_check_busy = False

    timer.timeout.connect(check)
    timer.start()
    window._license_timer = timer
    window.check_runtime_license = check
