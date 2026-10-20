"""Qt desktop GUI. GDAL runs on a worker thread; there is no ArcPy import."""

import os
import logging
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .model import FastSettings, Cancelled
from .engine import inspect_shape, run_fast


UNIT_LABELS = [("متر", "m"), ("کیلومتر", "km"), ("فوت", "ft"), ("مایل", "mi")]


class AnalysisWorker(QtCore.QObject):
    message = QtCore.Signal(str)
    progress = QtCore.Signal(int)
    preview = QtCore.Signal(int, object, object)
    result = QtCore.Signal(str)
    error = QtCore.Signal(str)
    stopped = QtCore.Signal()

    def __init__(self, config, cancel_event):
        super().__init__()
        self.config = config
        self.cancel_event = cancel_event
        self.last_percent = -1
        self.last_progress_time = 0.0

    def update_progress(self, fraction):
        percent = int(fraction*100)
        now = time.monotonic()
        if percent != self.last_percent and (percent == 100 or now-self.last_progress_time >= .05):
            self.last_percent = percent
            self.last_progress_time = now
            self.progress.emit(percent)

    @QtCore.Slot()
    def run(self):
        try:
            folder = run_fast(self.config, self.message.emit,
                              self.update_progress,
                              self.cancel_event.is_set, self.preview.emit)
            self.result.emit(folder)
        except Cancelled:
            self.error.emit("عملیات لغو شد؛ خروجی نیمه‌تمام معتبر نیست.")
        except Exception:
            self.error.emit(traceback.format_exc())
        finally:
            self.stopped.emit()


class FastWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fast Sector Viewshed 2.2 | دیدپذیری قطاعی مستقل")
        self.resize(1260, 860)
        self.setMinimumSize(940, 650)
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.thread = None
        self.worker = None
        self.cancel_event = threading.Event()
        self.loaded_shape = None
        self.result_folder = None
        self.preview_images = {}
        self.visible_previews = {}
        self.inputs = {}
        self.unit_boxes = {}
        self.build_ui()

    def build_ui(self):
        root = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(18, 16, 18, 12)
        title = QtWidgets.QLabel("دیدپذیری قطاعی — ورودی و خروجی Shapefile")
        title.setObjectName("title")
        subtitle = QtWidgets.QLabel("برنامهٔ مستقل • آزیموت از شمال واقعی و ساعت‌گرد • خروجی سازگار با ArcGIS Pro و QGIS")
        outer.addWidget(title)
        outer.addWidget(subtitle)
        split = QtWidgets.QSplitter()
        outer.addWidget(split, 1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(490)
        form_widget = QtWidgets.QWidget()
        self.form_widget = form_widget
        form = QtWidgets.QVBoxLayout(form_widget)
        scroll.setWidget(form_widget)
        split.addWidget(scroll)
        inputs, grid = self.group("داده‌های ورودی", form)
        self.path_row(grid, 0, "points", "شیپ‌فایل نقطه‌ای", self.choose_shape)
        self.read_fields = QtWidgets.QPushButton("خواندن ستون‌های اتریبیوت")
        self.read_fields.clicked.connect(self.load_fields)
        grid.addWidget(self.read_fields, 1, 1, 1, 2)
        self.shape_info = QtWidgets.QLabel("همهٔ نقاط فایل پردازش می‌شوند.")
        self.shape_info.setWordWrap(True)
        grid.addWidget(self.shape_info, 2, 0, 1, 3)
        for row, name, text in [(3, "start_field", "ستون آزیموت شروع"), (4, "end_field", "ستون آزیموت پایان")]:
            combo = QtWidgets.QComboBox()
            combo.setLayoutDirection(QtCore.Qt.LeftToRight)
            self.inputs[name] = combo
            grid.addWidget(QtWidgets.QLabel(text), row, 0)
            grid.addWidget(combo, row, 1, 1, 2)
        note = QtWidgets.QLabel("نمونه: ۳۵۰٫۵، 350:30:00 یا N45E\n۳۵۰ تا ۲۰ از شمال عبور می‌کند؛ شروع و پایان برابر یعنی دایرهٔ کامل.")
        note.setWordWrap(True)
        grid.addWidget(note, 5, 0, 1, 3)
        self.path_row(grid, 6, "dem", "DEM ارتفاعی", self.choose_dem)
        self.unit_row(grid, 7, "dem_z_unit", "واحد ارتفاع پیکسل‌های DEM", only_dem=True)
        dimensions, grid = self.group("شعاع و ارتفاع‌های بالای زمین", form)
        self.number_row(grid, 0, "radius", "شعاع قطاع", 5, "radius_unit", "km")
        self.number_row(grid, 1, "receiver", "ارتفاع گیرنده / ناظر", 2, "receiver_unit")
        self.number_row(grid, 2, "target", "ارتفاع آبجکت / هدف", 0, "target_unit")
        accuracy, grid = self.group("سرعت و تفکیک مکانی", form)
        self.number_row(grid, 0, "cell_size", "اندازهٔ پیکسل، متر؛ صفر = خودکار", 0)
        self.inputs["cell_size"].setSpecialValueText("خودکار")
        self.resolution = QtWidgets.QComboBox()
        for label, factor in [("تفکیک اصلی DEM", 1), ("سریع: پیکسل ۲ برابر درشت‌تر", 2), ("سریع‌تر: پیکسل ۴ برابر درشت‌تر", 4)]:
            self.resolution.addItem(label, factor)
        grid.addWidget(QtWidgets.QLabel("حالت تفکیک"), 1, 0)
        grid.addWidget(self.resolution, 1, 1, 1, 2)
        self.number_row(grid, 2, "refraction", "ضریب شکست نور جوی", .13)
        epsg = QtWidgets.QSpinBox()
        epsg.setRange(0, 999999)
        epsg.setSpecialValueText("سیستم مختصات شیپ‌فایل ورودی")
        self.inputs["output_epsg"] = epsg
        grid.addWidget(QtWidgets.QLabel("EPSG خروجی؛ صفر = ورودی"), 3, 0)
        grid.addWidget(epsg, 3, 1, 1, 2)
        warning = QtWidgets.QLabel("پیکسل درشت‌تر سریع‌تر است و جزئیات کمتری نگه می‌دارد. نتیجهٔ موتور GDAL ممکن است با Esri یا Global Mapper تفاوت داشته باشد.")
        warning.setWordWrap(True)
        grid.addWidget(warning, 4, 0, 1, 3)
        self.auto_coarsen = QtWidgets.QCheckBox("شبکهٔ بزرگ: افزایش خودکار پیکسل تا سقف انتخابی (کاهش جزئیات)")
        self.auto_coarsen.setChecked(True)
        grid.addWidget(self.auto_coarsen, 5, 0, 1, 3)
        limit = QtWidgets.QSpinBox()
        limit.setRange(1, 100)
        limit.setValue(25)
        self.inputs["max_grid_mcells"] = limit
        grid.addWidget(QtWidgets.QLabel("سقف شبکهٔ هر نقطه، میلیون سلول"), 6, 0)
        grid.addWidget(limit, 6, 1, 1, 2)
        memory_note = QtWidgets.QLabel("برای حفظ پیکسل درخواستی، تنظیم خودکار را خاموش و سقف را افزایش دهید. شبکهٔ بزرگ حافظه و زمان بیشتری مصرف می‌کند؛ این عدد سقف مصرف RAM نیست.")
        memory_note.setWordWrap(True)
        grid.addWidget(memory_note, 7, 0, 1, 3)
        self.curvature = QtWidgets.QCheckBox("محاسبهٔ انحنای زمین و شکست جوی")
        self.curvature.setChecked(True)
        self.curvature.toggled.connect(self.inputs["refraction"].setEnabled)
        grid.addWidget(self.curvature, 8, 0, 1, 3)
        curvature_note = QtWidgets.QLabel("برای مقایسه با Global Mapper، وضعیت انحنای زمین و ضریب شکست هر دو اجرا را یکسان کنید؛ اثر آن در شعاع ۱۰۰ کیلومتر زیاد است.")
        curvature_note.setWordWrap(True)
        grid.addWidget(curvature_note, 9, 0, 1, 3)
        output, grid = self.group("خروجی", form)
        self.path_row(grid, 0, "output_dir", "پوشهٔ ذخیره", self.choose_output)
        self.inputs["output_dir"].setText(str(Path.home()/"Documents"/"FastViewshedResults"))
        self.merge = QtWidgets.QCheckBox("تولید coverage.shp با ادغام پوشش نقاط (زمان بیشتر)")
        grid.addWidget(self.merge, 1, 0, 1, 3)
        description = QtWidgets.QLabel("خروجی اصلی: visible.shp، فقط محدودهٔ قابل‌دید\nvisibility.shp: هر سه کلاس دیدپذیری\nsectors.shp: فقط مرز تحلیل؛ برای نمایش ویوشد visible.shp را باز کنید.")
        description.setWordWrap(True)
        grid.addWidget(description, 2, 0, 1, 3)
        form.addStretch()

        tabs = QtWidgets.QTabWidget()
        split.addWidget(tabs)
        preview_tab = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout(preview_tab)
        self.preview_selector = QtWidgets.QComboBox()
        self.preview_selector.currentIndexChanged.connect(self.show_preview)
        preview_layout.addWidget(self.preview_selector)
        self.preview_mode = QtWidgets.QComboBox()
        self.preview_mode.addItem("فقط محدودهٔ قابل‌دید — قرمز", "visible")
        self.preview_mode.addItem("همهٔ کلاس‌ها — قابل‌دید، پنهان، نامعلوم", "classes")
        self.preview_mode.currentIndexChanged.connect(self.show_preview)
        preview_layout.addWidget(self.preview_mode)
        self.image = QtWidgets.QLabel("پیش‌نمایش هر نقطه پس از محاسبه نمایش داده می‌شود.")
        self.image.setAlignment(QtCore.Qt.AlignCenter)
        self.image.setMinimumSize(300, 300)
        self.image.setStyleSheet("background:#f3f6f8; border:1px solid #cad4df; border-radius:8px;")
        preview_layout.addWidget(self.image, 1)
        self.preview_note = QtWidgets.QLabel("قرمز: قابل‌دید • سفید: سایر نواحی • خروجی: visible.shp")
        self.preview_note.setWordWrap(True)
        preview_layout.addWidget(self.preview_note)
        tabs.addTab(preview_tab, "پیش‌نمایش دیدپذیری")
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(10000)
        tabs.addTab(self.log, "گزارش اجرا")
        self.tabs = tabs
        split.setSizes([540, 680])
        actions = QtWidgets.QHBoxLayout()
        self.run_button = QtWidgets.QPushButton("محاسبه و تولید Shapefile")
        self.run_button.setObjectName("run")
        self.run_button.clicked.connect(self.start_analysis)
        self.cancel_button = QtWidgets.QPushButton("لغو")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_analysis)
        self.open_button = QtWidgets.QPushButton("باز کردن پوشهٔ نتیجه")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_results)
        save = QtWidgets.QPushButton("ذخیرهٔ گزارش")
        save.clicked.connect(self.save_log)
        for button in (self.run_button, self.cancel_button, self.open_button, save):
            actions.addWidget(button)
        outer.addLayout(actions)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        outer.addWidget(self.progress_bar)
        self.status = QtWidgets.QLabel("آماده")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.setCentralWidget(root)
        self.setStyleSheet('''
            QWidget {font-family: "Segoe UI", "Tahoma"; font-size: 12px; color:#17364b;}
            QMainWindow {background:#eef3f7;}
            QLabel#title {font-size:25px; font-weight:700; padding:6px 0;}
            QGroupBox {font-weight:600; border:1px solid #cedae4; border-radius:8px; margin-top:14px; padding:15px 8px 8px; background:white;}
            QGroupBox::title {subcontrol-origin:margin; padding:0 5px;}
            QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox {padding:7px; border:1px solid #bbcbd7; border-radius:4px; background:white;}
            QPushButton {padding:9px 12px; border:1px solid #b8cbd9; border-radius:5px; background:#edf4f8;}
            QPushButton#run {background:#146e87; color:white; font-weight:700;}
            QPushButton:disabled {color:#8997a2; background:#e6ebee;}
            QProgressBar {border:1px solid #bbcbd7; border-radius:4px; text-align:center; height:17px;}
            QProgressBar::chunk {background:#26a782;}
            QPlainTextEdit {background:#142b3b; color:#e7eef5; font-family:Consolas;}
        ''')

    @staticmethod
    def group(title, parent):
        box = QtWidgets.QGroupBox(title)
        grid = QtWidgets.QGridLayout(box)
        grid.setColumnStretch(1, 1)
        parent.addWidget(box)
        return box, grid

    def path_row(self, grid, row, name, label, callback):
        widget = QtWidgets.QLineEdit()
        widget.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.inputs[name] = widget
        button = QtWidgets.QPushButton("انتخاب…")
        button.clicked.connect(callback)
        grid.addWidget(QtWidgets.QLabel(label), row, 0)
        grid.addWidget(widget, row, 1)
        grid.addWidget(button, row, 2)

    def unit_row(self, grid, row, name, label, only_dem=False):
        combo = QtWidgets.QComboBox()
        for text, key in UNIT_LABELS:
            if not only_dem or key in ("m", "ft"):
                combo.addItem(text, key)
        self.unit_boxes[name] = combo
        grid.addWidget(QtWidgets.QLabel(label), row, 0)
        grid.addWidget(combo, row, 1, 1, 2)

    def number_row(self, grid, row, name, label, default, unit_name=None, unit_default="m"):
        spin = QtWidgets.QDoubleSpinBox()
        spin.setDecimals(4)
        spin.setRange(0, 1000000)
        spin.setValue(default)
        spin.setLayoutDirection(QtCore.Qt.LeftToRight)
        spin.setLocale(QtCore.QLocale("fa_IR"))
        self.inputs[name] = spin
        grid.addWidget(QtWidgets.QLabel(label), row, 0)
        grid.addWidget(spin, row, 1, 1, 1 if unit_name else 2)
        if unit_name:
            combo = QtWidgets.QComboBox()
            for text, key in UNIT_LABELS:
                combo.addItem(text, key)
            combo.setCurrentIndex(combo.findData(unit_default))
            self.unit_boxes[unit_name] = combo
            grid.addWidget(combo, row, 2)

    def choose_shape(self):
        name, _ = QtWidgets.QFileDialog.getOpenFileName(self, "شیپ‌فایل نقطه‌ای", "", "Shapefile (*.shp)")
        if name:
            self.inputs["points"].setText(name)
            self.load_fields()

    def choose_dem(self):
        name, _ = QtWidgets.QFileDialog.getOpenFileName(self, "DEM", "", "Elevation (*.tif *.tiff *.img *.asc *.dem);;All files (*)")
        if name:
            self.inputs["dem"].setText(name)

    def choose_output(self):
        name = QtWidgets.QFileDialog.getExistingDirectory(self, "پوشهٔ خروجی")
        if name:
            self.inputs["output_dir"].setText(name)

    def load_fields(self):
        path = self.inputs["points"].text().strip()
        self.loaded_shape = None
        for key in ("start_field", "end_field"):
            self.inputs[key].clear()
        try:
            metadata = inspect_shape(path)
            for key in ("start_field", "end_field"):
                self.inputs[key].addItems(metadata["fields"])
                self.inputs[key].setCurrentIndex(-1)
            self.loaded_shape = path
            self.shape_info.setText(f"{metadata['count']} نقطه | {metadata['crs']}")
            self.log.appendPlainText("ستون‌ها خوانده شدند: "+", ".join(metadata["fields"]))
        except Exception as exc:
            self.show_error(str(exc))

    def settings(self):
        if self.inputs["points"].text().strip() != self.loaded_shape:
            raise ValueError("ابتدا ستون‌های شیپ‌فایل فعلی را بخوانید.")
        data = {}
        for name, widget in self.inputs.items():
            if isinstance(widget, QtWidgets.QLineEdit):
                data[name] = widget.text().strip()
            elif isinstance(widget, QtWidgets.QComboBox):
                data[name] = widget.currentText()
            else:
                data[name] = widget.value()
        data.update({name: widget.currentData() for name, widget in self.unit_boxes.items()})
        data["resolution_factor"] = self.resolution.currentData()
        data["merge_coverage"] = self.merge.isChecked()
        data["auto_coarsen"] = self.auto_coarsen.isChecked()
        data["curvature_enabled"] = self.curvature.isChecked()
        config = FastSettings(**data)
        config.validate()
        return config

    def start_analysis(self):
        if self.thread is not None:
            return
        try:
            config = self.settings()
        except Exception as exc:
            self.show_error(str(exc))
            return
        self.result_folder = None
        self.open_button.setEnabled(False)
        self.preview_selector.clear()
        self.preview_images.clear()
        self.visible_previews.clear()
        self.image.clear()
        self.progress_bar.setValue(0)
        self.run_button.setEnabled(False)
        self.form_widget.setEnabled(False)
        self.read_fields.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_event.clear()
        self.log.appendPlainText("\n── تحلیل جدید با GDAL | نسخهٔ 2.2 ──")
        self.status.setText("در حال پردازش…")
        self.thread = QtCore.QThread(self)
        self.worker = AnalysisWorker(config, self.cancel_event)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.message.connect(self.on_message)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.preview.connect(self.receive_preview)
        self.worker.result.connect(self.on_result)
        self.worker.error.connect(self.show_error)
        self.worker.stopped.connect(self.thread.quit, QtCore.Qt.DirectConnection)
        self.worker.stopped.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finished)
        self.thread.start()

    @QtCore.Slot(str)
    def on_message(self, message):
        self.log.appendPlainText(message)
        self.status.setText(message)

    @QtCore.Slot(str)
    def on_result(self, folder):
        self.result_folder = folder
        self.open_button.setEnabled(True)
        self.status.setText("نتیجهٔ Shapefile ذخیره شد: "+folder)

    @QtCore.Slot()
    def finished(self):
        # QThread.finished precedes completion of native thread-local cleanup.
        # Retain the Python wrappers until wait succeeds; destroying the thread
        # while that cleanup needs the GIL can otherwise deadlock PySide/Python.
        thread = self.thread
        if thread is not None and not thread.wait(100):
            QtCore.QTimer.singleShot(20, self.finished)
            return
        if thread is not None:
            thread.deleteLater()
        self.thread = None
        self.worker = None
        self.run_button.setEnabled(True)
        self.form_widget.setEnabled(True)
        self.read_fields.setEnabled(True)
        self.cancel_button.setEnabled(False)

    @QtCore.Slot(int, object, object)
    def receive_preview(self, fid, classes, metadata):
        # Reduce the categorical array before allocating RGBA/QImage buffers.
        # Otherwise a 40-million-cell result needs several extra 160 MB copies
        # on the GUI thread merely to build a small preview.
        stride = max(1, (max(classes.shape)+1399)//1400)
        classes = classes[::stride, ::stride]
        rgba = np.full((*classes.shape, 4), 255, dtype=np.uint8)
        rgba[classes == 0] = (221, 72, 77, 255)
        rgba[classes == 1] = (42, 184, 111, 255)
        rgba[classes == 2] = (140, 147, 155, 255)
        image = QtGui.QImage(rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0], QtGui.QImage.Format_RGBA8888).copy()
        pixmap = QtGui.QPixmap.fromImage(image)
        if pixmap.width() > 1400 or pixmap.height() > 1400:
            pixmap = pixmap.scaled(1400, 1400, QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation)
        self.preview_images[fid] = pixmap
        visible_rgba = np.zeros((*classes.shape, 4), dtype=np.uint8)
        visible_rgba[classes == 1] = (190, 30, 45, 235)
        visible_image = QtGui.QImage(visible_rgba.data, visible_rgba.shape[1], visible_rgba.shape[0],
                                     visible_rgba.strides[0], QtGui.QImage.Format_RGBA8888).copy()
        self.visible_previews[fid] = QtGui.QPixmap.fromImage(visible_image)
        self.preview_selector.addItem(f"نقطه {fid} | اندازهٔ پیکسل {metadata['cell']:.2f} متر", fid)
        self.preview_selector.setCurrentIndex(self.preview_selector.count()-1)
        self.show_preview()

    def show_preview(self, index=None):
        fid = self.preview_selector.currentData()
        only_visible = self.preview_mode.currentData() == "visible"
        images = self.visible_previews if only_visible else self.preview_images
        self.preview_note.setText("قرمز: قابل‌دید • سفید: سایر نواحی • خروجی: visible.shp" if only_visible else
                                  "سبز: قابل‌دید • قرمز: پنهان • خاکستری: نامعلوم • سفید: بیرون قطاع")
        if fid in images:
            self.image.setPixmap(images[fid].scaled(self.image.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "preview_images"):
            self.show_preview()

    def cancel_analysis(self):
        self.cancel_event.set()
        self.status.setText("درخواست لغو ثبت شد؛ در نخستین نقطهٔ امن متوقف می‌شود…")
        self.cancel_button.setEnabled(False)

    def show_error(self, detail):
        logging.getLogger("fast_viewshed").error(detail)
        self.log.appendPlainText(detail)
        self.status.setText("عملیات کامل نشد؛ گزارش اجرا را بررسی کنید.")
        self.tabs.setCurrentIndex(1)

    def open_results(self):
        if self.result_folder:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.result_folder))

    def save_log(self):
        name, _ = QtWidgets.QFileDialog.getSaveFileName(self, "ذخیرهٔ گزارش", "viewshed_log.txt", "Text (*.txt)")
        if name:
            try:
                Path(name).write_text(self.log.toPlainText(), encoding="utf-8")
            except OSError as exc:
                self.show_error(str(exc))

    def closeEvent(self, event):
        if self.thread is not None:
            self.cancel_analysis()
            event.ignore()
        else:
            event.accept()


def fast_main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName("FastSectorViewshed")
    app.setFont(QtGui.QFont("Segoe UI", 10))
    window = FastWindow()
    window._fast_app_reference = app
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(fast_main())
