"""Qt desktop GUI. GDAL runs on a worker thread; there is no ArcPy import."""

import os
import json
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
from .engine import inspect_shape, run_fast, read_attribute_values, read_map_observers
from .basemap import OfflineBoundaryMap, application_asset


UNIT_LABELS = [("متر", "m"), ("کیلومتر", "km"), ("فوت", "ft"), ("مایل", "mi")]


def forward_form_wheel(widget, event):
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QtWidgets.QScrollArea):
            parent.wheelEvent(event)
            return
        parent = parent.parentWidget()
    event.ignore()


class ScrollComboBox(QtWidgets.QComboBox):
    def wheelEvent(self, event):
        forward_form_wheel(self, event)


class ScrollSpinBox(QtWidgets.QSpinBox):
    def wheelEvent(self, event):
        forward_form_wheel(self, event)


class ScrollDoubleSpinBox(QtWidgets.QDoubleSpinBox):
    def textFromValue(self, value):
        text = format(value, f'.{self.decimals()}f')
        return text.rstrip('0').rstrip('.') if '.' in text else text

    def wheelEvent(self, event):
        forward_form_wheel(self, event)


class SmoothScrollArea(QtWidgets.QScrollArea):
    def __init__(self):
        super().__init__()
        self.animation = QtCore.QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self.animation.setDuration(130)
        self.animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self.target = 0
        self.verticalScrollBar().setSingleStep(36)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        QtWidgets.QScroller.grabGesture(self.viewport(), QtWidgets.QScroller.TouchGesture)

    def wheelEvent(self, event):
        bar = self.verticalScrollBar()
        if not event.pixelDelta().isNull():
            self.animation.stop()
            bar.setValue(bar.value()-event.pixelDelta().y())
            self.target = bar.value()
        elif event.angleDelta().y():
            if self.animation.state() != QtCore.QAbstractAnimation.Running:
                self.target = bar.value()
            self.target = max(bar.minimum(), min(bar.maximum(), self.target-round(event.angleDelta().y()/120*85)))
            self.animation.stop()
            self.animation.setStartValue(bar.value())
            self.animation.setEndValue(self.target)
            self.animation.start()
        event.accept()

    def ensureWidgetVisible(self, widget, xmargin=0, ymargin=16):
        self.animation.stop()
        if isinstance(widget, QtWidgets.QGroupBox):
            self.verticalScrollBar().setValue(widget.mapTo(self.widget(), QtCore.QPoint(0,0)).y()-8)
        else:
            super().ensureWidgetVisible(widget, xmargin, ymargin)
        self.target = self.verticalScrollBar().value()


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
        self.setWindowTitle("Fast Sector Viewshed 3.3.0 | دیدپذیری قطاعی آفلاین")
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
        self.height_modes = {}
        self.output_hint = "visible.shp"
        self.build_ui()
        icon = application_asset("aircraft.ico")
        if icon:
            self.setWindowIcon(QtGui.QIcon(str(icon)))

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
        scroll = SmoothScrollArea()
        self.form_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(490)
        form_widget = QtWidgets.QWidget()
        self.form_widget = form_widget
        form = QtWidgets.QVBoxLayout(form_widget)
        scroll.setWidget(form_widget)
        form_panel = QtWidgets.QWidget()
        panel_layout = QtWidgets.QVBoxLayout(form_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        navigation = QtWidgets.QHBoxLayout()
        panel_layout.addLayout(navigation)
        panel_layout.addWidget(scroll)
        split.addWidget(form_panel)
        inputs, grid = self.group("داده‌های ورودی", form)
        inputs.setObjectName("inputSection")
        self.path_row(grid, 0, "points", "نقاط Shapefile / GeoJSON", self.choose_shape)
        self.read_fields = QtWidgets.QPushButton("خواندن ستون‌های اتریبیوت")
        self.read_fields.clicked.connect(self.load_fields)
        grid.addWidget(self.read_fields, 1, 1, 1, 2)
        self.shape_info = QtWidgets.QLabel("همهٔ نقاط فایل پردازش می‌شوند.")
        self.shape_info.setWordWrap(True)
        grid.addWidget(self.shape_info, 2, 0, 1, 3)
        for row, name, text in [(3, "start_field", "ستون آزیموت شروع"), (4, "end_field", "ستون آزیموت پایان")]:
            combo = ScrollComboBox()
            combo.setLayoutDirection(QtCore.Qt.LeftToRight)
            self.inputs[name] = combo
            grid.addWidget(QtWidgets.QLabel(text), row, 0)
            grid.addWidget(combo, row, 1, 1, 2)
        note = QtWidgets.QLabel("نمونه: ۳۵۰٫۵، 350:30:00 یا N45E\n۳۵۰ تا ۲۰ از شمال عبور می‌کند؛ شروع و پایان برابر یعنی دایرهٔ کامل.")
        note.setWordWrap(True)
        grid.addWidget(note, 5, 0, 1, 3)
        self.path_row(grid, 6, "dem", "DEM ارتفاعی", self.choose_dem)
        self.unit_row(grid, 7, "dem_z_unit", "واحد ارتفاع پیکسل‌های DEM", only_dem=True)
        fid = ScrollSpinBox()
        fid.setRange(-1, 2147483647)
        fid.setValue(-1)
        fid.setSpecialValueText("همهٔ نقاط")
        self.inputs["observer_fid"] = fid
        grid.addWidget(QtWidgets.QLabel("فقط FID؛ منفی یک = همه"), 8, 0)
        grid.addWidget(fid, 8, 1, 1, 2)
        self.reference_button = QtWidgets.QPushButton("اعمال تنظیمات تصویر Global Mapper برای FID=1")
        self.reference_button.clicked.connect(self.apply_reference_settings)
        grid.addWidget(self.reference_button, 9, 0, 1, 3)
        dimensions, grid = self.group("شعاع و ارتفاع‌های بالای زمین", form)
        dimensions.setObjectName("dimensionSection")
        self.number_row(grid, 0, "radius", "شعاع قطاع", 5, "radius_unit", "km")
        self.number_row(grid, 1, "observer", "فرستنده / ناظر در محل نقطه، بالای DEM", 100, "observer_unit")
        self.number_row(grid, 2, "receiver", "گیرنده روی سلول‌های اطراف، بالای DEM", 2, "receiver_unit")
        mapping_note = QtWidgets.QLabel("Transmitter Elevation → ارتفاع فرستنده در نقطه\nReceiver Elevation → ارتفاع گیرنده در هر سلول مقصد")
        mapping_note.setWordWrap(True)
        grid.addWidget(mapping_note, 3, 0, 1, 3)
        for row, kind, label in ((4, "observer", "فرستنده از ستون"), (5, "receiver", "گیرنده از ستون")):
            mode = QtWidgets.QCheckBox(label)
            combo = ScrollComboBox()
            combo.setLayoutDirection(QtCore.Qt.LeftToRight)
            combo.setEnabled(False)
            self.inputs[kind+"_field"] = combo
            self.height_modes[kind] = mode
            mode.toggled.connect(combo.setEnabled)
            mode.toggled.connect(self.inputs[kind].setDisabled)
            grid.addWidget(mode, row, 0)
            grid.addWidget(combo, row, 1, 1, 2)
        height_note = QtWidgets.QLabel("ستون ارتفاع می‌تواند عددی یا تکست باشد، مانند ۲، 2.5 یا 1e2. واحد ستون از کمبوباکس واحد همان ارتفاع گرفته می‌شود.")
        height_note.setWordWrap(True)
        grid.addWidget(height_note, 6, 0, 1, 3)
        accuracy, grid = self.group("سرعت و تفکیک مکانی", form)
        self.number_row(grid, 0, "cell_size", "اندازهٔ پیکسل، متر؛ صفر = خودکار", 0)
        self.inputs["cell_size"].setSpecialValueText("خودکار")
        self.resolution = ScrollComboBox()
        for label, factor in [("تفکیک اصلی DEM", 1), ("سریع: پیکسل ۲ برابر درشت‌تر", 2), ("سریع‌تر: پیکسل ۴ برابر درشت‌تر", 4)]:
            self.resolution.addItem(label, factor)
        grid.addWidget(QtWidgets.QLabel("حالت تفکیک"), 1, 0)
        grid.addWidget(self.resolution, 1, 1, 1, 2)
        self.number_row(grid, 2, "atmospheric_factor", "Atmospheric Correction (ضریب شعاع مؤثر k)", 1.33333)
        self.inputs["atmospheric_factor"].setDecimals(8)
        self.inputs["atmospheric_factor"].setRange(.000001, 1000)
        self.inputs["atmospheric_factor"].setValue(1.33333)
        epsg = ScrollSpinBox()
        epsg.setRange(0, 999999)
        epsg.setSpecialValueText("سیستم مختصات شیپ‌فایل ورودی")
        self.inputs["output_epsg"] = epsg
        grid.addWidget(QtWidgets.QLabel("EPSG خروجی؛ صفر = ورودی"), 3, 0)
        grid.addWidget(epsg, 3, 1, 1, 2)
        warning = QtWidgets.QLabel("پیکسل درشت‌تر سریع‌تر است و جزئیات کمتری نگه می‌دارد. نتیجهٔ موتور GDAL ممکن است با Esri یا Global Mapper تفاوت داشته باشد.")
        warning.setWordWrap(True)
        grid.addWidget(warning, 4, 0, 1, 3)
        self.auto_coarsen = QtWidgets.QCheckBox("پیکسل خودکار برای شبکهٔ بزرگ (کاهش جزئیات)")
        self.auto_coarsen.setChecked(True)
        grid.addWidget(self.auto_coarsen, 5, 0, 1, 3)
        limit = ScrollSpinBox()
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
        self.curvature.toggled.connect(self.inputs["atmospheric_factor"].setEnabled)
        grid.addWidget(self.curvature, 8, 0, 1, 3)
        curvature_note = QtWidgets.QLabel("۱٫۳۳۳۳۳ مستقیماً مانند تصویر وارد می‌شود؛ ضریب انحنای GDAL برابر ۱/k است. این مقدار با ضریب شکست ۰٫۱۳ فرق دارد.")
        curvature_note.setWordWrap(True)
        grid.addWidget(curvature_note, 9, 0, 1, 3)
        self.inputs["nodata_policy"] = ScrollComboBox()
        self.inputs["nodata_policy"].addItem("نامعلوم؛ مسیر خلأ DEM قابل‌دید محسوب نشود", "unknown")
        self.inputs["nodata_policy"].addItem("Treat Missing Elevations as Ocean — ارتفاع صفر", "sea_level")
        self.inputs["nodata_policy"].setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.inputs["nodata_policy"].setMinimumContentsLength(12)
        grid.addWidget(QtWidgets.QLabel("ارتفاع‌های ناموجود"), 10, 0)
        grid.addWidget(self.inputs["nodata_policy"], 10, 1, 1, 2)
        output, grid = self.group("خروجی", form)
        output.setObjectName("outputSection")
        self.path_row(grid, 0, "output_dir", "پوشهٔ ذخیره", self.choose_output)
        self.inputs["output_dir"].setText(str(Path.home()/"Documents"/"FastViewshedResults"))
        self.merge = QtWidgets.QCheckBox("تولید coverage.shp با ادغام پوشش نقاط (زمان بیشتر)")
        grid.addWidget(self.merge, 1, 0, 1, 3)
        description = QtWidgets.QLabel("خروجی اصلی: visible.shp، فقط محدودهٔ قابل‌دید\nvisibility.shp: هر سه کلاس دیدپذیری\nsectors.shp: فقط مرز تحلیل؛ برای نمایش ویوشد visible.shp را باز کنید.")
        self.output_description = description
        description.setWordWrap(True)
        grid.addWidget(description, 2, 0, 1, 3)
        self.inputs["name_field"] = ScrollComboBox()
        self.inputs["name_field"].addItem("نام پیش‌فرض از FID", "")
        grid.addWidget(QtWidgets.QLabel("ستون نام نقطه برای name"), 3, 0)
        grid.addWidget(self.inputs["name_field"], 3, 1, 1, 2)
        self.separate = QtWidgets.QCheckBox("برای هر نقطه یک شیپ‌فایل قابل‌دید مستقل")
        self.separate.toggled.connect(self.toggle_separate_outputs)
        grid.addWidget(self.separate, 4, 0, 1, 3)
        naming_note = QtWidgets.QLabel("بدون تیک: یک شیپ کلی با نام انتخابی شما\nبا تیک: نام فایل مرجع-نام نقطه-ارتفاع فرستنده.shp\nارتفاعِ نام فایل بر حسب متر است؛ نام تکراری با FID متمایز می‌شود. لایه‌های کمکی در details ذخیره می‌شوند.")
        naming_note.setWordWrap(True)
        grid.addWidget(naming_note, 5, 0, 1, 3)
        self.inputs["combined_name_field"] = ScrollComboBox()
        self.inputs["combined_name_field"].addItem("نام پیش‌فرض: visible.shp", "")
        self.inputs["combined_name_field"].currentIndexChanged.connect(self.load_combined_values)
        grid.addWidget(QtWidgets.QLabel("ستون نام فایل خروجی مشترک"), 6, 0)
        grid.addWidget(self.inputs["combined_name_field"], 6, 1, 1, 2)
        self.inputs["combined_name_value"] = ScrollComboBox()
        self.inputs["combined_name_value"].setEnabled(False)
        self.inputs["combined_name_value"].currentIndexChanged.connect(self.update_output_description)
        grid.addWidget(QtWidgets.QLabel("مقدار دلخواه برای نام فایل"), 7, 0)
        grid.addWidget(self.inputs["combined_name_value"], 7, 1, 1, 2)
        note = QtWidgets.QLabel("برای یک شیپ کلی، ابتدا ستون و سپس یکی از مقدارهای همان ستون را انتخاب کنید. این نام فایل است؛ نام نقاط در اتریبیوت‌ها جداگانه حفظ می‌شود.")
        note.setWordWrap(True)
        grid.addWidget(note, 8, 0, 1, 3)
        self.primary_groups = (inputs, dimensions, output)
        for group in self.primary_groups:
            group.setProperty("priority", True)
        form.removeWidget(output)
        form.insertWidget(2, output)
        self.advanced_button = QtWidgets.QPushButton("تنظیمات پیشرفته: سرعت، تفکیک و انحنای زمین ▾")
        self.advanced_button.setCheckable(True)
        self.advanced_button.toggled.connect(accuracy.setVisible)
        form.insertWidget(3, self.advanced_button)
        accuracy.setVisible(False)
        for title, group in (("ورودی‌ها", inputs), ("شعاع و ارتفاع", dimensions), ("خروجی", output)):
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(lambda checked=False, target=group: self.form_scroll.ensureWidgetVisible(target))
            navigation.addWidget(button)
        for combo in form_widget.findChildren(QtWidgets.QComboBox):
            combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(10)
        form.addStretch()
        # Long Persian labels must wrap instead of forcing the entire form
        # wider than its viewport and clipping field names and browse buttons.
        for group in form_widget.findChildren(QtWidgets.QGroupBox):
            layout = group.layout()
            for index in range(layout.count()):
                widget = layout.itemAt(index).widget()
                _, column, _, span = layout.getItemPosition(index)
                if isinstance(widget, QtWidgets.QLabel) and column == 0 and span == 1:
                    widget.setWordWrap(True)
                    widget.setMaximumWidth(155)

        tabs = QtWidgets.QTabWidget()
        split.addWidget(tabs)
        preview_tab = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout(preview_tab)
        self.preview_selector = ScrollComboBox()
        self.preview_selector.currentIndexChanged.connect(self.show_preview)
        preview_layout.addWidget(self.preview_selector)
        self.preview_mode = ScrollComboBox()
        self.preview_mode.addItem("فقط محدودهٔ قابل‌دید — قرمز", "visible")
        self.preview_mode.addItem("همهٔ کلاس‌ها — قابل‌دید، پنهان، نامعلوم", "classes")
        self.preview_mode.currentIndexChanged.connect(self.show_preview)
        preview_layout.addWidget(self.preview_mode)
        self.image = QtWidgets.QLabel("پیش‌نمایش هر نقطه پس از محاسبه نمایش داده می‌شود.")
        self.image.setAlignment(QtCore.Qt.AlignCenter)
        self.image.setMinimumSize(300, 300)
        self.image.setStyleSheet("background:#f3f6f8; border:1px solid #cad4df; border-radius:8px;")
        self.preview_stack = QtWidgets.QStackedWidget()
        map_panel = QtWidgets.QWidget()
        map_layout = QtWidgets.QVBoxLayout(map_panel)
        map_layout.setContentsMargins(0, 0, 0, 0)
        map_tools = QtWidgets.QHBoxLayout()
        self.map_view = OfflineBoundaryMap()
        for title, action in (("+", lambda: self.map_view.scale(1.4, 1.4)),
                              ("−", lambda: self.map_view.scale(1/1.4, 1/1.4)),
                              ("نمای نقاط", lambda: self.map_view.fit_observers(self.inputs["radius"].value()*{ "m": 1, "km": 1000, "ft": .3048, "mi": 1609.344 }[self.unit_boxes["radius_unit"].currentData()])),
                              ("نقشهٔ جهان", self.map_view.fit_world)):
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(action)
            map_tools.addWidget(button)
        map_layout.addLayout(map_tools)
        map_layout.addWidget(self.map_view, 1)
        attribution = QtWidgets.QLabel("© OpenStreetMap contributors · ODbL · نقشهٔ مرزی آفلاین")
        attribution.setObjectName("mapAttribution")
        map_layout.addWidget(attribution)
        self.preview_stack.addWidget(map_panel)
        self.preview_stack.addWidget(self.image)
        self.view_selector = ScrollComboBox()
        self.view_selector.addItems(["نقشهٔ مرزی OSM و موقعیت نقاط — آفلاین", "تصویر نتیجهٔ نقطهٔ انتخابی"])
        self.view_selector.currentIndexChanged.connect(self.preview_stack.setCurrentIndex)
        preview_layout.addWidget(self.view_selector)
        preview_layout.addWidget(self.preview_stack, 1)
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
            QGroupBox::title {subcontrol-origin:margin; padding:0 7px;}
            QGroupBox[priority="true"] {border-width:2px; font-weight:800; font-size:14px; padding-top:19px; margin-top:19px;}
            QGroupBox#inputSection {border-color:#287aa6; background:#f0f7fc;}
            QGroupBox#dimensionSection {border-color:#198f87; background:#eefaf7;}
            QGroupBox#outputSection {border-color:#7462aa; background:#f5f2fc;}
            QGroupBox#inputSection::title {color:#175e87; background:#e0edf8; border-radius:4px;}
            QGroupBox#dimensionSection::title {color:#0e776e; background:#d9f1eb; border-radius:4px;}
            QGroupBox#outputSection::title {color:#5c468d; background:#e9e2f6; border-radius:4px;}
            QScrollBar:vertical {background:#e0eaf0; width:15px; border-radius:7px; margin:0;}
            QScrollBar::handle:vertical {background:#719cae; min-height:38px; border-radius:7px;}
            QScrollBar::handle:vertical:hover {background:#33768e;}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height:0;}
            QLabel#mapAttribution {font-size:10px; color:#617c8d; padding:4px;}

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
        combo = ScrollComboBox()
        for text, key in UNIT_LABELS:
            if not only_dem or key in ("m", "ft"):
                combo.addItem(text, key)
        self.unit_boxes[name] = combo
        grid.addWidget(QtWidgets.QLabel(label), row, 0)
        grid.addWidget(combo, row, 1, 1, 2)

    def number_row(self, grid, row, name, label, default, unit_name=None, unit_default="m"):
        spin = ScrollDoubleSpinBox()
        spin.setDecimals(4)
        spin.setRange(0, 1000000)
        spin.setValue(default)
        spin.setLayoutDirection(QtCore.Qt.LeftToRight)
        spin.setLocale(QtCore.QLocale.c())
        spin.setGroupSeparatorShown(False)
        spin.setKeyboardTracking(False)
        self.inputs[name] = spin
        grid.addWidget(QtWidgets.QLabel(label), row, 0)
        grid.addWidget(spin, row, 1, 1, 1 if unit_name else 2)
        if unit_name:
            combo = ScrollComboBox()
            for text, key in UNIT_LABELS:
                combo.addItem(text, key)
            combo.setCurrentIndex(combo.findData(unit_default))
            self.unit_boxes[unit_name] = combo
            grid.addWidget(combo, row, 2)
            if name == 'radius':
                def update_radius_limit():
                    factor = {'m': 1, 'km': 1000, 'ft': 0.3048, 'mi': 1609.344}[combo.currentData()]
                    scale = 10 ** spin.decimals()
                    spin.setMaximum(int(5000000 / factor * scale) / scale)
                    spin.setToolTip('حداکثر شعاع: ۵۰۰۰ کیلومتر؛ عدد بر حسب واحد انتخاب‌شده است.')
                combo.currentIndexChanged.connect(update_radius_limit)
                update_radius_limit()

    def choose_shape(self):
        name, _ = QtWidgets.QFileDialog.getOpenFileName(self, "فایل نقاط", "", "Point files (*.shp *.geojson *.json);;Shapefile (*.shp);;GeoJSON (*.geojson *.json)")
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
        for key in ("start_field", "end_field", "observer_field", "receiver_field", "name_field"):
            self.inputs[key].clear()
        self.inputs["name_field"].addItem("نام پیش‌فرض از FID", "")
        self.inputs["combined_name_field"].blockSignals(True)
        self.inputs["combined_name_field"].clear()
        self.inputs["combined_name_field"].addItem("نام پیش‌فرض: visible.shp", "")
        self.inputs["combined_name_value"].clear()
        self.inputs["combined_name_value"].setEnabled(False)
        self.inputs["combined_name_field"].blockSignals(False)
        try:
            metadata = inspect_shape(path)
            for key in ("start_field", "end_field", "observer_field", "receiver_field"):
                self.inputs[key].addItems(metadata["fields"])
                self.inputs[key].setCurrentIndex(-1)
            for field in metadata["fields"]:
                self.inputs["name_field"].addItem(field, field)
                self.inputs["combined_name_field"].addItem(field, field)
            default_name = next((name for name in metadata["fields"] if name.casefold() in ("name", "نام")), "")
            self.inputs["name_field"].setCurrentIndex(self.inputs["name_field"].findData(default_name))
            self.loaded_shape = path
            self.shape_info.setText(f"{metadata['count']} نقطه | {metadata['crs']}")
            self.log.appendPlainText("ستون‌ها خوانده شدند: "+", ".join(metadata["fields"]))
            self.map_view.set_observers(read_map_observers(path))
            self.update_output_description()
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
                data[name] = widget.currentData() if name == "nodata_policy" else widget.currentText()
            else:
                data[name] = widget.value()
        data.update({name: widget.currentData() for name, widget in self.unit_boxes.items()})
        data["resolution_factor"] = self.resolution.currentData()
        data["merge_coverage"] = self.merge.isChecked()
        data["auto_coarsen"] = self.auto_coarsen.isChecked()
        data["curvature_enabled"] = self.curvature.isChecked()
        data["separate_outputs"] = self.separate.isChecked()
        data["name_field"] = self.inputs["name_field"].currentData() or ""
        for key in ("combined_name_field", "combined_name_value"):
            data[key] = self.inputs[key].currentData() or ""
        if data["separate_outputs"]:
            data["combined_name_field"] = data["combined_name_value"] = ""
        elif data["combined_name_field"] and not data["combined_name_value"]:
            raise ValueError("از فهرست مقدارهای ستون نام خروجی، یک مقدار انتخاب کنید.")
        for kind, mode in self.height_modes.items():
            field = self.inputs[kind+"_field"].currentText() if mode.isChecked() else ""
            if mode.isChecked() and not field:
                raise ValueError("ستون ارتفاع را انتخاب کنید: "+mode.text())
            data[kind+"_field"] = field
        config = FastSettings(**data)
        config.validate()
        return config

    def apply_reference_settings(self):
        """The supplied GM dialog's public parameters, without embedding data."""
        for mode in self.height_modes.values():
            mode.setChecked(False)
        for name, value in (("radius", 100), ("observer", 100), ("receiver", 2),
                            ("atmospheric_factor", 1.33333), ("cell_size", 350), ("observer_fid", 1)):
            self.inputs[name].setValue(value)
        for name, unit in (("radius_unit", "km"), ("observer_unit", "m"), ("receiver_unit", "m"), ("dem_z_unit", "m")):
            self.unit_boxes[name].setCurrentIndex(self.unit_boxes[name].findData(unit))
        for name, field in (("start_field", "AZFR"), ("end_field", "AZTO")):
            index = self.inputs[name].findText(field)
            if index >= 0:
                self.inputs[name].setCurrentIndex(index)
        self.resolution.setCurrentIndex(self.resolution.findData(1))
        self.curvature.setChecked(True)
        self.auto_coarsen.setChecked(False)
        self.inputs["nodata_policy"].setCurrentIndex(self.inputs["nodata_policy"].findData("sea_level"))
        self.log.appendPlainText("تنظیم مرجع: FID=1؛ فرستنده در نقطه 100m، گیرنده روی سلول‌ها 2m، شعاع 100km، k=1.33333، ارتفاع ناموجود=دریا. فاصلهٔ نمونه‌برداری 350m تقریب فاصلهٔ زاویه‌ای تصویر است؛ تطابق دقیق شبکه با Global Mapper تأیید نشده است.")

    def load_combined_values(self):
        field = self.inputs["combined_name_field"].currentData()
        combo = self.inputs["combined_name_value"]
        combo.clear()
        combo.setEnabled(bool(field) and not self.separate.isChecked())
        if field:
            try:
                for value in read_attribute_values(self.inputs["points"].text(), field):
                    combo.addItem(value, value)
                if not combo.count():
                    self.log.appendPlainText("ستون نام فایل خروجی، مقدار غیرخالی ندارد؛ ستون دیگری انتخاب کنید.")
            except Exception as exc:
                self.show_error(str(exc))
        self.update_output_description()

    def update_output_description(self):
        if self.separate.isChecked():
            text = "برای هر نقطهٔ موفق یک فایل نام‌گذاری‌شده؛ لایه‌های کمکی در details ذخیره می‌شوند."
        else:
            name = self.inputs["combined_name_value"].currentData() or "visible"
            text = f"یک شیپ کلی با نام انتخابی: {name}.shp\nvisibility.shp: همهٔ کلاس‌ها • sectors.shp: مرز تحلیل"
        self.output_description.setText(text)

    def toggle_separate_outputs(self, checked):
        if checked:
            self.merge.setChecked(False)
        self.merge.setEnabled(not checked)
        if "combined_name_field" in self.inputs:
            self.inputs["combined_name_field"].setEnabled(not checked)
            self.inputs["combined_name_value"].setEnabled(not checked and bool(self.inputs["combined_name_field"].currentData()))
        self.update_output_description()

    def start_analysis(self):
        if self.thread is not None:
            return
        try:
            config = self.settings()
        except Exception as exc:
            self.show_error(str(exc))
            return
        self.result_folder = None
        self.output_hint = "فایل مستقل هر نقطه" if config.separate_outputs else (config.combined_name_value or "visible")+".shp"
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
        self.map_view.clear_results()
        self.map_view.fit_observers(config.radius_m)
        self.view_selector.setCurrentIndex(0)
        self.log.appendPlainText("\n── تحلیل آفلاین با GDAL | نسخهٔ 3.3.0 ──")
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
        report = json.loads((Path(folder)/"run.json").read_text(encoding="utf-8"))
        self.output_hint = report["primary_output"] or "فایل مستقل هر نقطه"
        successful, skipped = report["succeeded_records"], report["skipped_count"]
        message = f"خروجی ذخیره شد؛ {successful} رکورد موفق، {skipped} رکورد ردشده."
        if not successful:
            message = f"هشدار: هیچ رکورد موفقی نیست؛ {report['primary_outputs'][0]} خالی ساخته شد."
        self.status.setText(message)
        self.log.appendPlainText(message+" گزارش: skipped_records.csv")
        self.show_preview()

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
        self.map_view.add_result(fid, classes, metadata, self.preview_mode.currentData() == "visible")
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
        label = metadata.get("name", f"نقطه {fid}")
        self.preview_selector.addItem(f"{label} | FID={fid} | پیکسل {metadata['cell']:.2f} متر", fid)
        self.preview_selector.setCurrentIndex(self.preview_selector.count()-1)
        self.show_preview()

    def show_preview(self, index=None):
        fid = self.preview_selector.currentData()
        if hasattr(self, "map_view"):
            self.map_view.set_visible_only(self.preview_mode.currentData() == "visible")
            self.map_view.highlight(fid)
        only_visible = self.preview_mode.currentData() == "visible"
        images = self.visible_previews if only_visible else self.preview_images
        self.preview_note.setText(f"قرمز: قابل‌دید • سفید: سایر نواحی • خروجی: {self.output_hint}" if only_visible else
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
    icon = application_asset("aircraft.ico")
    if icon:
        app.setWindowIcon(QtGui.QIcon(str(icon)))
    if os.name == "nt":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FastViewshed.Desktop")
        app._desktop_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "FastViewshed.Desktop.Running")
    window = FastWindow()
    window._fast_app_reference = app
    window.show()
    report_path = os.environ.get("FAST_VIEWSHED_SMOKE_REPORT")
    if report_path:
        def report_ready():
            report = dict(status="passed", executable=sys.executable, version="3.3.0", gui_visible=window.isVisible(),
                          icon_loaded=not window.windowIcon().isNull(), offline_map_countries=window.map_view.boundary_count,
                          highlighted_groups=len(window.primary_groups), combined_naming_controls=True)
            Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
            window.close()
        QtCore.QTimer.singleShot(1200, report_ready)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(fast_main())
