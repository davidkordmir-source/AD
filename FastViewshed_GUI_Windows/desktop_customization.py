"""Offline map import, local administrator preferences and branded startup UI."""
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import tempfile
import time
import uuid

import numpy as np
from osgeo import gdal, ogr, osr
from PySide6 import QtCore, QtGui, QtWidgets

DEFAULTS = dict(title='دیدپذیری قطاعی — ورودی و خروجی Shapefile', font_size=12,
                accent='#146e87', map_line='#7c97a6', map_fill='#fafcfd',
                map_background='#eaf2f6', logo='')


class Preferences:
    """Per-user local settings. Passwords are never stored as plaintext."""
    def __init__(self, folder=None):
        self.folder = Path(folder or os.environ.get('FAST_VIEWSHED_PROFILE') or
                           (Path(QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.GenericDataLocation)) / 'FastViewshed'))
        self.path = self.folder / 'desktop_settings.json'
        self.data = {}
        if self.path.exists():
            # Do not treat damaged password settings as an unconfigured account.
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(self.data, dict):
                raise ValueError('فایل تنظیمات شخصی معتبر نیست.')
        default_admin = Path(__file__).parent / 'assets' / 'admin_default.json'
        if not self.configured and default_admin.is_file():
            self.data['admin'] = json.loads(default_admin.read_text(encoding='utf-8'))
            self.save()
        self.failures = 0
        self.locked_until = 0

    def save(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='settings_', suffix='.tmp', dir=self.folder)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as out:
                json.dump(self.data, out, ensure_ascii=False, indent=2)
            os.chmod(name, 0o600)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @property
    def configured(self):
        return 'admin' in self.data

    def set_password(self, password):
        if len(password) < 5:
            raise ValueError('رمز حداقل ۵ نویسه داشته باشد.')
        salt = secrets.token_bytes(32)
        self.data['admin'] = dict(salt=salt.hex(), iterations=600000,
                                  hash=hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000).hex())
        self.save()

    def verify(self, password):
        if time.monotonic() < self.locked_until:
            raise ValueError('تلاش‌های ناموفق زیاد است؛ پس از ۳۰ ثانیه دوباره امتحان کنید.')
        record = self.data.get('admin')
        if not record:
            return False
        calculated = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(record['salt']), record['iterations']).hex()
        matched = hmac.compare_digest(calculated, record['hash'])
        if matched:
            self.failures = 0
        else:
            self.failures += 1
            if self.failures >= 5:
                self.locked_until = time.monotonic() + 30
                self.failures = 0
        return matched

    @property
    def ui(self):
        return {**DEFAULTS, **self.data.get('ui', {})}

    def copy_logo(self, filename):
        image = QtGui.QImage(str(filename))
        if image.isNull():
            raise ValueError('لوگو باید تصویر معتبر PNG، JPG، BMP یا ICO باشد.')
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.folder / ('logo_' + uuid.uuid4().hex + '.png')
        if not image.save(str(target), 'PNG'):
            raise ValueError('ذخیرهٔ لوگو ممکن نشد.')
        return str(target)


def traditional(reference):
    reference.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return reference


def map_layers(filename):
    ds = ogr.Open(str(filename))
    if ds is None:
        return []
    return [(ds.GetLayer(i).GetName(), ds.GetLayer(i).GetSpatialRef() is not None)
            for i in range(ds.GetLayerCount())]


def load_map_file(filename, layer_name=None, source_epsg=None):
    """Read local vectors without simplification, or a bounded raster preview."""
    filename = Path(filename)
    if not filename.is_file():
        raise ValueError('فایل نقشه پیدا نشد: ' + str(filename))
    if filename.suffix.lower() in ('.tif', '.tiff', '.vrt'):
        return load_raster_map(filename, source_epsg)
    ds = ogr.Open(str(filename))
    if ds is None:
        raise ValueError('نقشهٔ برداری خوانده نشد؛ فایل‌های همراه Shapefile را هم بررسی کنید.')
    layer = ds.GetLayerByName(layer_name) if layer_name else ds.GetLayer(0)
    if layer is None:
        raise ValueError('لایهٔ انتخاب‌شده در فایل موجود نیست.')
    source = layer.GetSpatialRef()
    if source_epsg:
        source = osr.SpatialReference()
        source.ImportFromEPSG(int(source_epsg))
    if source is None:
        raise ValueError('سیستم مختصات نقشه مشخص نیست؛ کد EPSG صحیح را وارد کنید.')
    source = traditional(source.Clone())
    target = osr.SpatialReference()
    target.ImportFromEPSG(3857)
    geographic = osr.SpatialReference()
    geographic.ImportFromEPSG(4326)
    traditional(geographic)
    to_geographic = osr.CoordinateTransformation(source, geographic)
    transform = osr.CoordinateTransformation(geographic, traditional(target))
    paths, count, vertices = [], 0, 0
    bounds = None

    def add_geometry(geom, label):
        nonlocal bounds, vertices
        kind = ogr.GT_Flatten(geom.GetGeometryType())
        if kind not in (ogr.wkbPoint, ogr.wkbLineString, ogr.wkbLinearRing, ogr.wkbPolygon):
            for i in range(geom.GetGeometryCount()):
                add_geometry(geom.GetGeometryRef(i), label)
            return
        if kind == ogr.wkbPoint:
            x, y, *_ = geom.GetPoint()
            if math.isfinite(x) and math.isfinite(y):
                paths.append(('point', (x, -y), label))
                rect = QtCore.QRectF(x, -y, 0.001, 0.001)
                bounds = rect if bounds is None else bounds.united(rect)
            return
        path = QtGui.QPainterPath()
        path.setFillRule(QtCore.Qt.OddEvenFill)
        rings = [geom.GetGeometryRef(i) for i in range(geom.GetGeometryCount())] if kind == ogr.wkbPolygon else [geom]
        for ring in rings:
            previous = None
            for i in range(ring.GetPointCount()):
                vertices += 1
                if vertices > 5000000:
                    raise ValueError('نقشه بیش از ۵ میلیون رأس دارد؛ یک لایهٔ کوچک‌تر برای پیش‌نمایش انتخاب کنید.')
                x, y, *_ = ring.GetPoint(i)
                if not (math.isfinite(x) and math.isfinite(y)):
                    raise ValueError('مختصات نامعتبر پس از تبدیل سیستم مختصات نقشه.')
                if previous is None or abs(x - previous) > 20037508.35:
                    path.moveTo(x, -y)
                else:
                    path.lineTo(x, -y)
                previous = x
        if not path.isEmpty():
            paths.append(('polygon' if kind == ogr.wkbPolygon else 'line', path, label))
            rect = path.boundingRect()
            bounds = rect if bounds is None else bounds.united(rect)

    def clamp_latitudes(geometry):
        for i in range(geometry.GetPointCount()):
            x, y, *_ = geometry.GetPoint(i)
            geometry.SetPoint_2D(i, x, max(-85.05112878, min(85.05112878, y)))
        for i in range(geometry.GetGeometryCount()):
            clamp_latitudes(geometry.GetGeometryRef(i))

    name_field = next((name for name in ('NAME', 'name', 'NAME_LONG') if layer.GetLayerDefn().GetFieldIndex(name) >= 0), None)
    for feature in layer:
        geometry = feature.GetGeometryRef()
        if geometry is None or geometry.IsEmpty():
            continue
        geometry = geometry.Clone()
        if geometry.Transform(to_geographic) != 0:
            raise ValueError(f'تبدیل مختصات عارضهٔ {feature.GetFID()} ممکن نشد.')
        clamp_latitudes(geometry)
        if geometry.Transform(transform) != 0:
            raise ValueError(f'تبدیل مختصات عارضهٔ {feature.GetFID()} ممکن نشد.')
        label = str(feature.GetField(name_field) or '') if name_field else ''
        add_geometry(geometry, label or f'{layer.GetName()} | FID={feature.GetFID()}')
        count += 1
        if count > 250000:
            raise ValueError('نقشه بیش از ۲۵۰ هزار عارضه دارد؛ لایهٔ کوچک‌تری انتخاب کنید.')
    if not paths:
        raise ValueError('نقشه هیچ هندسهٔ قابل‌نمایشی ندارد.')
    return dict(kind='vector', paths=paths, bounds=bounds, count=count,
                filename=str(filename), layer=layer.GetName(), source_epsg=source_epsg)


def load_raster_map(filename, source_epsg=None):
    source = gdal.Open(str(filename))
    if source is None or source.RasterCount < 1:
        raise ValueError('نقشهٔ رستری خوانده نشد.')
    if not source.GetProjection() and not source_epsg:
        raise ValueError('رستر سیستم مختصات ندارد؛ کد EPSG آن را مشخص کنید.')
    options = dict(format='MEM', dstSRS='EPSG:3857', resampleAlg='bilinear', dstAlpha=True,
                   width=1400 if source.RasterXSize >= source.RasterYSize else 0,
                   height=1400 if source.RasterYSize > source.RasterXSize else 0)
    if source_epsg:
        options['srcSRS'] = f'EPSG:{source_epsg}'
    warped = gdal.Warp('', source, **options)
    if warped is None or max(warped.RasterXSize, warped.RasterYSize) > 4096:
        raise ValueError('تولید پیش‌نمایش رستر با این محدوده ممکن نشد.')
    channels = []
    rgb = source.RasterCount >= 3
    for index in (1, 2, 3) if rgb else (1,):
        band = warped.GetRasterBand(index)
        data = band.ReadAsArray()
        if band.DataType != gdal.GDT_Byte:
            valid = data[np.isfinite(data)]
            low, high = np.percentile(valid, [2, 98]) if valid.size else (0, 1)
            data = np.nan_to_num(np.clip((data - low) * 255 / max(float(high - low), 1e-12), 0, 255)).astype(np.uint8)
        channels.append(data.astype(np.uint8))
    if not rgb:
        channels *= 3
    channels.append(warped.GetRasterBand(warped.RasterCount).ReadAsArray().astype(np.uint8))
    rgba = np.ascontiguousarray(np.stack(channels, axis=2))
    height, width = rgba.shape[:2]
    image = QtGui.QImage(rgba.data, width, height, width * 4, QtGui.QImage.Format_RGBA8888).copy()
    gt = warped.GetGeoTransform()
    bounds = QtCore.QRectF(gt[0], -gt[3], width * gt[1], -height * gt[5])
    return dict(kind='raster', image=image, transform=gt, bounds=bounds, count=1,
                filename=str(filename), layer=None, source_epsg=source_epsg)


def copy_map_files(filename, folder):
    """Keep an offline private copy, including shapefile sidecars."""
    filename, folder = Path(filename), Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / ('map_' + uuid.uuid4().hex)
    destination.mkdir()
    try:
        if filename.suffix.lower() == '.shp':
            for suffix in ('.shp', '.shx', '.dbf'):
                if not any(p.stem.lower() == filename.stem.lower() and p.suffix.lower() == suffix for p in filename.parent.iterdir()):
                    raise ValueError('فایل همراه Shapefile موجود نیست: ' + suffix)
            files = [p for p in filename.parent.iterdir() if p.is_file() and
                     ((p.stem.lower() == filename.stem.lower() and p.suffix.lower() in {'.shp', '.shx', '.dbf', '.prj', '.cpg', '.qpj', '.sbn', '.sbx'}) or p.name.lower() == filename.name.lower() + '.xml')]
        else:
            files = [filename]
        for path in files:
            shutil.copy2(path, destination / path.name)
        return str(destination / filename.name)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


class MapLoader(QtCore.QObject):
    ready = QtCore.Signal(object, object)
    failed = QtCore.Signal(str)
    finished = QtCore.Signal()

    def __init__(self, filename, layer, epsg, destination=None):
        super().__init__()
        self.filename, self.layer, self.epsg, self.destination = filename, layer, epsg, destination

    @QtCore.Slot()
    def run(self):
        try:
            data = load_map_file(self.filename, self.layer, self.epsg)
            path = copy_map_files(self.filename, self.destination) if self.destination else self.filename
            self.ready.emit(data, dict(path=str(path), layer=self.layer, source_epsg=self.epsg))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class PersonalizationDialog(QtWidgets.QDialog):
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.preferences = preferences
        self.setWindowTitle('شخصی‌سازی رابط — مدیر')
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.resize(500, 400)
        form = QtWidgets.QFormLayout(self)
        ui = preferences.ui
        self.title = QtWidgets.QLineEdit(ui['title'])
        self.font_size = QtWidgets.QSpinBox()
        self.font_size.setRange(11, 20)
        self.font_size.setValue(ui['font_size'])
        form.addRow('عنوان برنامه', self.title)
        form.addRow('اندازهٔ متن', self.font_size)
        self.colors = {}
        for key, label in [('accent', 'رنگ اصلی'), ('map_line', 'رنگ خطوط نقشه'),
                           ('map_fill', 'رنگ داخل محدوده‌ها'), ('map_background', 'رنگ پس‌زمینهٔ نقشه')]:
            button = QtWidgets.QPushButton(ui[key])
            button.clicked.connect(lambda checked=False, k=key: self.choose_color(k))
            self.colors[key] = button
            form.addRow(label, button)
        self.logo_path = ui['logo']
        self.new_logo = None
        self.logo_label = QtWidgets.QLabel(Path(self.logo_path).name if self.logo_path else 'لوگوی همراه برنامه')
        form.addRow('لوگوی شروع', self.logo_label)
        logo = QtWidgets.QPushButton('انتخاب لوگوی اختصاصی…')
        logo.clicked.connect(self.choose_logo)
        form.addRow(logo)
        self.new_password = QtWidgets.QLineEdit()
        self.new_password.setEchoMode(QtWidgets.QLineEdit.Password)
        self.new_password.setPlaceholderText('برای حفظ رمز فعلی خالی بگذارید')
        self.confirm_password = QtWidgets.QLineEdit()
        self.confirm_password.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addRow('رمز جدید مدیر (حداقل ۵ نویسه)', self.new_password)
        form.addRow('تکرار رمز جدید', self.confirm_password)
        note = QtWidgets.QLabel('نقشه و لوگو محلی‌اند. لوگوی انتخابی از اجرای بعد در صفحهٔ شروع دیده می‌شود.')
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def choose_color(self, key):
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.colors[key].text()), self)
        if color.isValid():
            self.colors[key].setText(color.name())

    def choose_logo(self):
        name, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'لوگوی اختصاصی', '', 'Images (*.png *.jpg *.jpeg *.bmp *.ico)')
        if name:
            if QtGui.QImage(name).isNull():
                QtWidgets.QMessageBox.warning(self, 'لوگو', 'این تصویر قابل‌خواندن نیست.')
                return
            self.new_logo = name
            self.logo_label.setText(Path(name).name)

    def accept(self):
        password = self.new_password.text()
        if password and (len(password) < 5 or password != self.confirm_password.text()):
            QtWidgets.QMessageBox.warning(self, 'رمز مدیر', 'رمز حداقل ۵ نویسه باشد و تکرار آن یکسان باشد.')
            return
        try:
            logo = self.preferences.copy_logo(self.new_logo) if self.new_logo else self.logo_path
            self.preferences.data['ui'] = dict(title=self.title.text().strip() or DEFAULTS['title'],
                font_size=self.font_size.value(), logo=logo, **{k: b.text() for k, b in self.colors.items()})
            if password:
                self.preferences.set_password(password)
            else:
                self.preferences.save()
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, 'ذخیرهٔ تنظیمات', str(exc))
            return
        super().accept()


def create_splash(preferences, default_logo=None):
    image = QtGui.QPixmap(620, 370)
    image.fill(QtGui.QColor('#102b40'))
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    logo = preferences.ui['logo'] or default_logo
    if logo and Path(logo).is_file():
        pixmap = QtGui.QPixmap(str(logo))
        pixmap = pixmap.scaled(250, 230, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        painter.drawPixmap((620 - pixmap.width()) // 2, 18 + (230 - pixmap.height()) // 2, pixmap)
    painter.setPen(QtGui.QColor('white'))
    painter.setFont(QtGui.QFont('Segoe UI', 21, QtGui.QFont.Bold))
    painter.drawText(QtCore.QRect(15, 245, 590, 45), QtCore.Qt.AlignCenter, 'Fast Viewshed 3.4')
    painter.setFont(QtGui.QFont('Tahoma', 11))
    painter.drawText(QtCore.QRect(15, 300, 590, 40), QtCore.Qt.AlignCenter, 'در حال آماده‌سازی برنامه…')
    painter.end()
    splash = QtWidgets.QSplashScreen(image)
    splash.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint)
    return splash
