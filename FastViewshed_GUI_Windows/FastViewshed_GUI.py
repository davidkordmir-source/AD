# -*- coding: utf-8 -*-
# Independent Qt GUI; requires GDAL, NumPy and PySide6, never ArcPy.
"""Startup logging before importing Qt or native GIS bindings."""
import faulthandler
import logging
import os
from pathlib import Path
import sys
import tempfile
import traceback
os.environ['PROJ_NETWORK'] = 'OFF'
_fast_log_stream = None
_fast_log_path = None

def enable_fast_logging():
    global _fast_log_stream, _fast_log_path
    if _fast_log_stream is not None:
        return _fast_log_path
    folder = Path(tempfile.gettempdir()) / 'FastViewshed_logs'
    folder.mkdir(exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='fast_', suffix='.log', dir=str(folder))
    _fast_log_path = Path(name)
    _fast_log_stream = os.fdopen(descriptor, 'a', encoding='utf-8', buffering=1)
    _fast_log_stream.write(f'Python: {sys.version}\nExecutable: {sys.executable}\n')
    faulthandler.enable(file=_fast_log_stream, all_threads=True)
    logger = logging.getLogger('fast_viewshed')
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(_fast_log_stream))
    if sys.stderr is None:
        sys.stderr = _fast_log_stream
    if sys.stdout is None:
        sys.stdout = _fast_log_stream
    return _fast_log_path

def fast_startup_error(exc):
    path = enable_fast_logging()
    detail = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logging.getLogger('fast_viewshed').error(detail)
    if sys.stderr is not None:
        sys.stderr.write(detail + '\nLog: ' + str(path) + '\n')
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f'{exc}\n\nLog: {path}', 'Fast Viewshed startup error', 16)
        except Exception:
            pass
try:
    if __name__ == '__main__':
        enable_fast_logging()
    import math
    import re
    from dataclasses import dataclass
    _TRANSLATE = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩−٫٬', '01234567890123456789-. ')
    UNITS = {'m': 1.0, 'km': 1000.0, 'ft': 0.3048, 'mi': 1609.344}
    COMPASS = {'N': 0, 'NE': 45, 'E': 90, 'SE': 135, 'S': 180, 'SW': 225, 'W': 270, 'NW': 315}

    def number(value):
        """Parse a finite number; a comma is a decimal mark, never a group mark."""
        if value is None or isinstance(value, bool):
            raise ValueError('مقدار عددی خالی یا نامعتبر است.')
        text = str(value).translate(_TRANSLATE).strip().replace(' ', '').replace(',', '.')
        try:
            result = float(text)
        except (ValueError, TypeError):
            raise ValueError(f'مقدار عددی نامعتبر: {value!r}') from None
        if not math.isfinite(result):
            raise ValueError('مقدار عددی باید متناهی باشد.')
        return result

    def _degrees(text):
        text = text.strip()
        match = re.fullmatch('([+-]?(?:\\d+(?:[.,]\\d*)?|[.,]\\d+)(?:e[+-]?\\d+)?)\\s*(?:°|deg)?', text, re.I)
        if match:
            return number(match[1])
        text = re.sub('deg|°|º|[′’\']|[″\\"]|:', ' ', text, flags=re.I)
        parts = text.split()
        if len(parts) not in (2, 3) or not all((re.fullmatch('[+-]?\\d+(?:[.,]\\d+)?', p) for p in parts)):
            raise ValueError('آزیموت باید عدد، D:M:S، یا جهت مانند N45E باشد.')
        d, m = (number(parts[0]), number(parts[1]))
        s = number(parts[2]) if len(parts) == 3 else 0.0
        if d != int(d) or not (0 <= m < 60 and 0 <= s < 60):
            raise ValueError('در DMS، درجه صحیح و دقیقه و ثانیه در بازهٔ صفر تا کمتر از ۶۰ باشند.')
        sign = -1 if parts[0].startswith('-') else 1
        return sign * (abs(d) + m / 60 + s / 3600)

    def azimuth(value):
        if value is None or isinstance(value, bool):
            raise ValueError('آزیموت خالی یا نامعتبر است.')
        if isinstance(value, (int, float)):
            result = number(value)
            if not 0 <= result <= 360:
                raise ValueError('آزیموت باید بین صفر و ۳۶۰ درجه باشد.')
            return result
        text = str(value).translate(_TRANSLATE).strip().upper()
        if text in COMPASS:
            return float(COMPASS[text])
        quadrant = re.fullmatch('([NS])\\s*(.+?)\\s*([EW])', text)
        if quadrant:
            angle = _degrees(quadrant[2])
            if not 0 <= angle <= 90:
                raise ValueError('زاویهٔ جهت ربع\u200cدایره\u200cای باید بین صفر و ۹۰ باشد.')
            north, east = (quadrant[1] == 'N', quadrant[3] == 'E')
            return ((angle if east else -angle) if north else 180 - angle if east else 180 + angle) % 360
        result = _degrees(text)
        if not 0 <= result <= 360:
            raise ValueError('آزیموت باید بین صفر و ۳۶۰ درجه باشد.')
        return result

    def angle_ranges(start, end):
        """Clockwise true-north angles. Equal endpoints mean a complete circle."""
        start, end = (azimuth(start) % 360, azimuth(end) % 360)
        if math.isclose(start, end, abs_tol=1e-10, rel_tol=0):
            return [(0.0, 360.0)]
        if start < end:
            return [(start, end)]
        return [(start, 360.0)] + ([(0.0, end)] if end else [])
    'Settings and bearing parsing shared by the standalone GUI and engine.'
    from dataclasses import dataclass
    import math

    class Cancelled(Exception):
        pass

    @dataclass(frozen=True)
    class ObserverRecord:
        row: tuple
        name: str
        observer: float
        receiver: float
        name_fallback: bool = False

    @dataclass(frozen=True)
    class FastSettings:
        points: str
        dem: str
        start_field: str
        end_field: str
        output_dir: str
        radius: float = 5
        radius_unit: str = 'km'
        observer: float = 100
        observer_unit: str = 'm'
        receiver: float = 2
        receiver_unit: str = 'm'
        dem_z_unit: str = 'm'
        cell_size: float = 0
        resolution_factor: int = 1
        output_epsg: int = 0
        atmospheric_factor: float = 1.33333
        merge_coverage: bool = False
        max_grid_mcells: int = 25
        auto_coarsen: bool = True
        curvature_enabled: bool = True
        nodata_policy: str = 'unknown'
        observer_fid: int = -1
        observer_field: str = ''
        receiver_field: str = ''
        name_field: str = ''
        separate_outputs: bool = False

        @property
        def radius_m(self):
            return self.radius * UNITS[self.radius_unit]

        @property
        def curvature_coefficient(self):
            return 1 / self.atmospheric_factor if self.curvature_enabled else 0.0

        def validate(self):
            for name in ('points', 'dem', 'start_field', 'end_field', 'output_dir'):
                if not str(getattr(self, name)).strip():
                    raise ValueError('ورودی الزامی خالی است: ' + name)
            for name in ('radius_unit', 'observer_unit', 'receiver_unit', 'dem_z_unit'):
                if getattr(self, name) not in UNITS:
                    raise ValueError('واحد نامعتبر: ' + name)
            for name in ('radius', 'observer', 'receiver', 'cell_size', 'atmospheric_factor'):
                value = getattr(self, name)
                if not math.isfinite(value) or value < 0:
                    raise ValueError('مقدار نامعتبر: ' + name)
            if not 0 < self.radius_m <= 300000:
                raise ValueError('شعاع باید بزرگ\u200cتر از صفر و حداکثر ۳۰۰ کیلومتر باشد.')
            if not 0 < self.atmospheric_factor <= 1000:
                raise ValueError('ضریب Atmospheric Correction باید مثبت و حداکثر ۱۰۰۰ باشد.')
            if self.resolution_factor not in (1, 2, 4):
                raise ValueError('ضریب تفکیک نامعتبر است.')
            if self.output_epsg < 0:
                raise ValueError('EPSG نامعتبر است.')
            if isinstance(self.max_grid_mcells, bool) or not isinstance(self.max_grid_mcells, int) or (not 1 <= self.max_grid_mcells <= 100):
                raise ValueError('سقف شبکه باید عدد صحیح از ۱ تا ۱۰۰ میلیون سلول باشد.')
            if not isinstance(self.auto_coarsen, bool):
                raise ValueError('تنظیم خودکار پیکسل باید روشن یا خاموش باشد.')
            if not isinstance(self.curvature_enabled, bool):
                raise ValueError('تنظیم انحنای زمین باید روشن یا خاموش باشد.')
            if self.nodata_policy not in ('unknown', 'sea_level'):
                raise ValueError('روش برخورد با ارتفاع ناموجود نامعتبر است.')
            if isinstance(self.observer_fid, bool) or not isinstance(self.observer_fid, int) or self.observer_fid < -1:
                raise ValueError('FID باید عدد صحیح از منفی یک به بالا باشد؛ منفی یک یعنی همهٔ نقاط.')
            for field in ('observer_field', 'receiver_field', 'name_field'):
                if not isinstance(getattr(self, field), str):
                    raise ValueError('نام ستون نامعتبر است: ' + field)
            if not isinstance(self.separate_outputs, bool):
                raise ValueError('حالت خروجی جداگانه نامعتبر است.')
            if self.separate_outputs and self.merge_coverage:
                raise ValueError('برای خروجی مستقل هر نقطه، گزینهٔ ادغام پوشش\u200cها را خاموش کنید.')
    'Compiled GDAL viewshed on local equidistant grids, exported as Shapefiles.'
    from collections import Counter
    from dataclasses import asdict, replace
    from datetime import datetime
    import json
    import math
    from pathlib import Path
    import re
    import time
    import unicodedata
    import numpy as np
    from osgeo import gdal, ogr, osr
    gdal.UseExceptions()
    ogr.UseExceptions()
    osr.UseExceptions()
    gdal.SetConfigOption('PROJ_NETWORK', 'OFF')
    osr.SetPROJEnableNetwork(False)
    CLASS_NAMES = {0: 'hidden', 1: 'visible', 2: 'unknown'}

    def spatial_ref(definition):
        sr = osr.SpatialReference()
        sr.SetFromUserInput(str(definition))
        sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        return sr

    def inspect_shape(path):
        if not Path(path).is_file():
            raise ValueError('فایل نقاط باید روی دستگاه موجود باشد؛ دریافت اینترنتی ورودی پشتیبانی نمی\u200cشود.')
        ds = gdal.OpenEx(str(path), gdal.OF_VECTOR | gdal.OF_READONLY, allowed_drivers=['ESRI Shapefile', 'GeoJSON'])
        if ds is None:
            raise ValueError('فایل نقاط باز نشد؛ برای Shapefile فایل\u200cهای SHP، SHX و DBF را بررسی کنید.')
        layer = ds.GetLayer(0)
        if ogr.GT_Flatten(layer.GetGeomType()) != ogr.wkbPoint:
            raise ValueError('ورودی باید شیپ\u200cفایل نقطه\u200cای از نوع Point باشد.')
        sr = layer.GetSpatialRef()
        if sr is None:
            raise ValueError('شیپ\u200cفایل سیستم مختصات ندارد؛ فایل PRJ لازم است.')
        allowed = {ogr.OFTInteger, ogr.OFTInteger64, ogr.OFTReal, ogr.OFTString}
        definition = layer.GetLayerDefn()
        fields = [definition.GetFieldDefn(i).GetName() for i in range(definition.GetFieldCount()) if definition.GetFieldDefn(i).GetType() in allowed]
        return {'fields': fields, 'count': layer.GetFeatureCount(), 'crs': sr.GetName()}

    def load_observer_records(cfg):
        metadata = inspect_shape(cfg.points)
        if cfg.start_field not in metadata['fields'] or cfg.end_field not in metadata['fields']:
            raise ValueError('فیلدهای آزیموت را دوباره انتخاب کنید.')
        for field in (cfg.observer_field, cfg.receiver_field, cfg.name_field):
            if field and field not in metadata['fields']:
                raise ValueError('ستون انتخاب\u200cشده در فایل نقاط وجود ندارد: ' + field)
        ds = gdal.OpenEx(cfg.points, gdal.OF_VECTOR | gdal.OF_READONLY, allowed_drivers=['ESRI Shapefile', 'GeoJSON'])
        layer = ds.GetLayer(0)
        sr = layer.GetSpatialRef().Clone()
        sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        to_wgs = osr.CoordinateTransformation(sr, spatial_ref('EPSG:4326'))
        rows, errors = ([], [])
        for feature in layer:
            fid = feature.GetFID()
            if cfg.observer_fid >= 0 and fid != cfg.observer_fid:
                continue
            try:
                geometry = feature.GetGeometryRef()
                if geometry is None or geometry.IsEmpty():
                    raise ValueError('هندسهٔ خالی')
                lon, lat, _ = to_wgs.TransformPoint(geometry.GetX(), geometry.GetY())
                if not (math.isfinite(lon) and math.isfinite(lat) and (-90 < lat < 90)):
                    raise ValueError('مختصات جغرافیایی نامعتبر')
                start = azimuth(feature.GetField(cfg.start_field))
                end = azimuth(feature.GetField(cfg.end_field))
                heights = []
                for field, fallback, unit in ((cfg.observer_field, cfg.observer, cfg.observer_unit), (cfg.receiver_field, cfg.receiver, cfg.receiver_unit)):
                    try:
                        value = number(feature.GetField(field)) if field else fallback
                        if value < 0 or not math.isfinite(value * UNITS[unit]):
                            raise ValueError('ارتفاع باید نامنفی و متناهی باشد.')
                    except ValueError as exc:
                        raise ValueError(f'ستون ارتفاع {field!r}: {exc}') from exc
                    heights.append(value)
                raw_name = feature.GetField(cfg.name_field) if cfg.name_field else None
                name = str(raw_name).strip() if raw_name is not None else ''
                fallback = not name
                if fallback:
                    name = f'FID_{fid}'
                if len(name.encode('utf-8')) > 254:
                    raise ValueError('نام انتخابی بیش از ۲۵۴ بایت UTF-8 است و در ستون name شیپ\u200cفایل جا نمی\u200cشود؛ ستون کوتاه\u200cتری انتخاب کنید.')
                rows.append(ObserverRecord((fid, lon, lat, start, end), name, *heights, fallback))
            except (ValueError, RuntimeError) as exc:
                errors.append(f'FID={fid}: {exc}')
        if errors:
            raise ValueError('ردیف نامعتبر؛ هیچ ردیفی حذف نشد:\n' + '\n'.join(errors[:30]))
        if not rows:
            if cfg.observer_fid >= 0:
                raise ValueError(f'FID={cfg.observer_fid} در فایل نقاط پیدا نشد.')
            raise ValueError('شیپ\u200cفایل خالی است.')
        return (rows, sr)

    def load_observers(cfg):
        """Keep the original coordinate-only API for consumers and diagnostics."""
        records, sr = load_observer_records(cfg)
        return ([record.row for record in records], sr)

    def filename_component(value, maximum_bytes):
        text = unicodedata.normalize('NFC', str(value))
        text = re.sub('[<>:"/\\\\|?*\\x00-\\x1f]', '_', text)
        text = re.sub('\\s+', ' ', text).strip(' .') or 'unnamed'
        reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{prefix}{i}' for prefix in ('COM', 'LPT') for i in range(1, 10)}
        if text.split('.')[0].upper() in reserved:
            text = '_' + text
        return text.encode('utf-8')[:maximum_bytes].decode('utf-8', errors='ignore').rstrip(' .') or 'unnamed'

    def separate_filenames(cfg, records):
        source = filename_component(Path(cfg.points).stem, 40)
        bases = [f'{source}-{filename_component(record.name, 90)}-{record.observer * UNITS[cfg.observer_unit]:.12g}' for record in records]
        counts = Counter((base.casefold() for base in bases))
        used, names = (set(), [])
        for record, base in zip(records, bases):
            stem = f'{base}-FID_{record.row[0]}' if counts[base.casefold()] > 1 else base
            candidate, suffix = (stem, 1)
            while candidate.casefold() in used:
                candidate = f'{stem}-{suffix}'
                suffix += 1
            used.add(candidate.casefold())
            names.append(candidate + '.shp')
        return names

    def sector_polygon(start, end, radius, cell):
        ranges = angle_ranges(start, end)
        sweep = sum((b - a for a, b in ranges))
        first = ranges[0][0]
        step = min(1.0, math.degrees(2 * math.acos(max(-1, 1 - min(radius, cell / 4) / radius))))
        count = max(1, int(math.ceil(sweep / max(step, 1e-05))))
        ring = ogr.Geometry(ogr.wkbLinearRing)
        full = ranges == [(0.0, 360.0)]
        if not full:
            ring.AddPoint_2D(0, 0)
        for i in range(count + 1):
            angle = math.radians(first + sweep * i / count)
            ring.AddPoint_2D(radius * math.sin(angle), radius * math.cos(angle))
        if not full:
            ring.AddPoint_2D(0, 0)
        ring.CloseRings()
        polygon = ogr.Geometry(ogr.wkbPolygon)
        polygon.AddGeometry(ring)
        return polygon

    def polygon_parts(geometry):
        if geometry is None or geometry.IsEmpty():
            return
        kind = ogr.GT_Flatten(geometry.GetGeometryType())
        if kind == ogr.wkbPolygon:
            yield geometry.Clone()
        elif kind in (ogr.wkbMultiPolygon, ogr.wkbGeometryCollection):
            for i in range(geometry.GetGeometryCount()):
                yield from polygon_parts(geometry.GetGeometryRef(i))

    def new_shape(path, sr, fields):
        ds = ogr.GetDriverByName('ESRI Shapefile').CreateDataSource(str(path))
        layer = ds.CreateLayer(Path(path).stem, srs=sr, geom_type=ogr.wkbPolygon, options=['ENCODING=UTF-8'])
        for name, kind in fields:
            field = ogr.FieldDefn(name, kind)
            if kind == ogr.OFTString:
                field.SetWidth(254 if name == 'name' else 32)
            if kind == ogr.OFTReal:
                field.SetWidth(24)
                field.SetPrecision(8)
            layer.CreateField(field)
        return (ds, layer)

    def write_feature(layer, geometry, values):
        for polygon in polygon_parts(geometry):
            feature = ogr.Feature(layer.GetLayerDefn())
            for name, value in values.items():
                feature.SetField(name, value)
            feature.SetGeometry(polygon)
            layer.CreateFeature(feature)

    def raster_dataset(array, transform, projection, nodata=None):
        dtype = gdal.GDT_Byte if array.dtype == np.uint8 else gdal.GDT_Float32
        ds = gdal.GetDriverByName('MEM').Create('', array.shape[1], array.shape[0], 1, dtype)
        ds.SetGeoTransform(transform)
        ds.SetProjection(projection)
        ds.GetRasterBand(1).WriteArray(array)
        if nodata is not None:
            ds.GetRasterBand(1).SetNoDataValue(nodata)
        return ds

    def viewshed(dataset, cfg, radius, observer_height, target_height, curvature, callback):
        return gdal.ViewshedGenerate(srcBand=dataset.GetRasterBand(1), driverName='MEM', targetRasterName='', creationOptions=[], observerX=0, observerY=0, observerHeight=observer_height, targetHeight=target_height, visibleVal=1, invisibleVal=0, outOfRangeVal=255, noDataVal=255, dfCurvCoeff=curvature, mode=gdal.GVM_Edge, maxDistance=radius, callback=callback, heightMode=gdal.GVOT_NORMAL, options=[])

    def local_resolution(source, source_sr, local_sr, lon, lat):
        from_wgs = osr.CoordinateTransformation(spatial_ref('EPSG:4326'), source_sr)
        to_local = osr.CoordinateTransformation(source_sr, local_sr)
        x, y, _ = from_wgs.TransformPoint(lon, lat)
        gt = source.GetGeoTransform()
        a = to_local.TransformPoint(x, y)
        b = to_local.TransformPoint(x + gt[1], y + gt[4])
        c = to_local.TransformPoint(x + gt[2], y + gt[5])
        size = max(math.hypot(b[0] - a[0], b[1] - a[1]), math.hypot(c[0] - a[0], c[1] - a[1]))
        if not math.isfinite(size) or size <= 0:
            raise ValueError('اندازهٔ پیکسل DEM قابل تعیین نیست؛ مقدار متری را دستی وارد کنید.')
        return size

    def grid_plan(radius, requested_cell, max_cells, auto_coarsen, fid, log):
        """Bound the actual odd, padded grid; never alter the requested radius."""

        def dimensions(cell):
            n = int(math.ceil(radius / cell)) + 3
            return (n, 2 * n + 1)
        n, size = dimensions(requested_cell)
        if size * size <= max_cells:
            return (requested_cell, n, size)
        maximum_side = math.isqrt(max_cells)
        if maximum_side % 2 == 0:
            maximum_side -= 1
        radius_pixels = (maximum_side - 1) // 2 - 3
        if radius_pixels < 2:
            raise ValueError('سقف شبکه برای تحلیل کافی نیست.')
        minimum_cell = math.nextafter(radius / radius_pixels, math.inf)
        if not auto_coarsen:
            multiplier = minimum_cell / requested_cell
            raise ValueError(f'FID={fid}: شبکهٔ درخواستی {size}×{size} ({size * size / 1000000.0:.2f} میلیون سلول) از سقف {max_cells / 1000000.0:g} میلیون بیشتر است. اندازهٔ پیکسل نهایی باید حداقل {math.ceil(minimum_cell * 1000000.0) / 1000000.0:.6f} متر ({multiplier:.3f} برابر مقدار فعلی) باشد؛ تنظیم خودکار پیکسل را روشن کنید یا سقف شبکه را با توجه به RAM افزایش دهید.')
        cell = minimum_cell
        n, adjusted_size = dimensions(cell)
        while adjusted_size * adjusted_size > max_cells:
            cell = math.nextafter(cell, math.inf)
            n, adjusted_size = dimensions(cell)
        log(f'نقطه {fid}: تنظیم خودکار برای سقف {max_cells / 1000000.0:g} میلیون سلول؛ پیکسل از {requested_cell:.6g} به {cell:.6g} متر افزایش یافت (کاهش جزئیات مکانی)؛ شبکه {size}×{size} → {adjusted_size}×{adjusted_size}. شعاع و آزیموت تغییر نکردند.')
        return (cell, n, adjusted_size)

    def local_result(source, source_sr, row, cfg, log, progress, cancelled):
        fid, lon, lat, start, end = row
        local_sr = spatial_ref(f'+proj=aeqd +lat_0={lat:.12f} +lon_0={lon:.12f} +datum=WGS84 +units=m +no_defs')
        cell = (cfg.cell_size or local_resolution(source, source_sr, local_sr, lon, lat)) * cfg.resolution_factor
        radius = cfg.radius_m
        if radius < 2 * cell:
            raise ValueError(f'FID={fid}: شعاع باید حداقل دو پیکسل باشد؛ اندازهٔ پیکسل {cell:g} متر است.')
        cell, n, size = grid_plan(radius, cell, cfg.max_grid_mcells * 1000000, cfg.auto_coarsen, fid, log)
        edge = (n + 0.5) * cell
        log(f'نقطه {fid}: پیکسل {cell:.3f} m | شبکه {size}×{size}')

        def callback(a, b):

            def update(fraction, message, data):
                if cancelled():
                    return 0
                progress(a + (b - a) * fraction)
                return 1
            return update
        if cancelled():
            raise Cancelled()
        warped = gdal.Warp('', source, format='MEM', dstSRS=local_sr.ExportToWkt(), outputBounds=(-edge, -edge, edge, edge), width=size, height=size, outputType=gdal.GDT_Float32, dstNodata=-3.4028234663852886e+38, resampleAlg='bilinear', errorThreshold=0, multithread=True, warpOptions=['NUM_THREADS=2'], callback=callback(0, 0.25))
        band = warped.GetRasterBand(1)
        heights = band.ReadAsArray()
        valid = (band.GetMaskBand().ReadAsArray() != 0) & np.isfinite(heights)
        if not valid[n, n] and cfg.nodata_policy == 'unknown':
            raise ValueError(f'FID={fid}: محل نقطه فاقد ارتفاع DEM است.')
        input_band = source.GetRasterBand(1)
        scale = input_band.GetScale()
        offset = input_band.GetOffset()
        np.multiply(heights, 1 if scale is None else scale, out=heights)
        np.add(heights, 0 if offset is None else offset, out=heights)
        np.multiply(heights, UNITS[cfg.dem_z_unit], out=heights)
        heights[~valid] = 0
        low = float(np.min(heights)) if cfg.nodata_policy == 'sea_level' else float(np.min(heights, where=valid, initial=np.inf))
        high = float(np.max(heights)) if cfg.nodata_policy == 'sea_level' else float(np.max(heights, where=valid, initial=-np.inf))
        log(f'نقطه {fid}: ارتفاع زمین در محل ناظر {heights[n, n]:.3f} متر؛ بازهٔ ارتفاع DEM در پنجره {low:.3f} تا {high:.3f} متر؛ فرستنده در نقطه {cfg.observer * UNITS[cfg.observer_unit]:g} و گیرنده روی سلول\u200cها {cfg.receiver * UNITS[cfg.receiver_unit]:g} متر بالای زمین')
        log(f'نقطه {fid}: ارتفاع نهایی فرستنده = DEM + ارتفاع فرستنده = {float(heights[n, n]) + cfg.observer * UNITS[cfg.observer_unit]:.3f} متر')
        if cfg.nodata_policy == 'sea_level' and (not valid.all()):
            log(f'نقطه {fid}: طبق انتخاب کاربر ارتفاع\u200cهای ناموجود، دریا با ارتفاع صفر فرض شدند.')
        gt = warped.GetGeoTransform()
        projection = local_sr.ExportToWkt()
        band = warped = None
        terrain = raster_dataset(heights, gt, projection)
        del heights
        maximum = radius + 2 * cell
        log(f'نقطه {fid}: محاسبهٔ دیدپذیری با موتور GDAL')
        result = viewshed(terrain, cfg, maximum, cfg.observer * UNITS[cfg.observer_unit], cfg.receiver * UNITS[cfg.receiver_unit], cfg.curvature_coefficient, callback(0.25, 0.65))
        terrain = None
        classes = result.GetRasterBand(1).ReadAsArray()
        result_gt = result.GetGeoTransform()
        result = None
        if cfg.nodata_policy == 'unknown' and (not valid.all()):
            log(f'نقطه {fid}: بررسی مسیرهای عبوری از قسمت\u200cهای فاقد DEM')
            gap_heights = np.zeros(valid.shape, dtype=np.float32)
            gap_heights[~valid] = 1000000000.0
            gaps = raster_dataset(gap_heights, gt, projection)
            del gap_heights
            certainty = viewshed(gaps, cfg, maximum, 0, 0, 0, callback(0.65, 0.8))
            gaps = None
            if certainty.GetGeoTransform() != result_gt or (certainty.RasterXSize, certainty.RasterYSize) != (classes.shape[1], classes.shape[0]):
                raise RuntimeError('شبکهٔ کنترل NoData با نتیجه هم\u200cتراز نیست.')
            clear = certainty.GetRasterBand(1).ReadAsArray() == 1
            certainty = None
            off_col = int(round((result_gt[0] - gt[0]) / cell))
            off_row = int(round((gt[3] - result_gt[3]) / cell))
            valid_view = valid[off_row:off_row + classes.shape[0], off_col:off_col + classes.shape[1]]
            classes[(~clear | ~valid_view) & (classes != 255)] = 2
        sector = sector_polygon(start, end, radius, cell)
        vector = ogr.GetDriverByName('Memory').CreateDataSource('')
        vector_layer = vector.CreateLayer('sector', srs=local_sr, geom_type=ogr.wkbPolygon)
        write_feature(vector_layer, sector, {})
        mask = raster_dataset(np.zeros(classes.shape, dtype=np.uint8), result_gt, projection)
        gdal.RasterizeLayer(mask, [1], vector_layer, burn_values=[1])
        classes[mask.GetRasterBand(1).ReadAsArray() == 0] = 255
        if not np.any(classes != 255):
            raise ValueError(f'FID={fid}: قطاع در این تفکیک هیچ سلولی ندارد؛ اندازهٔ پیکسل را کم یا بازهٔ آزیموت را بیشتر کنید.')
        progress(0.85)
        if cancelled():
            raise Cancelled()
        return (classes, result_gt, local_sr, sector, cell)

    def write_qml(path, visible_only=False):
        colors = {1: '190,30,45,210'} if visible_only else {0: '221,72,77,210', 1: '42,184,111,210', 2: '140,147,155,170'}
        symbols = ''.join((f'<symbol name="{i}" type="fill"><layer class="SimpleFill"><Option type="Map"><Option name="color" value="{c}" type="QString"/><Option name="outline_style" value="no" type="QString"/></Option></layer></symbol>' for i, c in colors.items()))
        categories = ''.join((f'<category value="{i}" symbol="{i}" label="{CLASS_NAMES[i]}" render="true"/>' for i in colors))
        Path(path).with_suffix('.qml').write_text(f'<!DOCTYPE qgis><qgis version="3.40"><renderer-v2 type="categorizedSymbol" attr="status"><categories>{categories}</categories><symbols>{symbols}</symbols></renderer-v2></qgis>', encoding='utf-8')

    def visible_radius(classes, gt):
        """Farthest visible cell centre, without allocating a full distance grid."""
        farthest = 0.0
        for r, row in enumerate(classes):
            columns = np.flatnonzero(row == 1)
            if columns.size:
                y = gt[3] + (r + 0.5) * gt[5]
                for c in (columns[0], columns[-1]):
                    x = gt[0] + (int(c) + 0.5) * gt[1]
                    farthest = max(farthest, math.hypot(x, y))
        return farthest

    def run_fast(cfg: FastSettings, log=print, progress=lambda fraction: None, cancelled=lambda: False, preview=lambda *args: None):
        cfg.validate()
        started = time.perf_counter()
        rows, input_sr = load_observer_records(cfg)
        output_sr = spatial_ref(f'EPSG:{cfg.output_epsg}') if cfg.output_epsg else input_sr
        if not Path(cfg.dem).is_file():
            raise ValueError('DEM باید فایل محلی موجود باشد؛ برنامه DEM را از اینترنت دریافت نمی\u200cکند.')
        source = gdal.OpenEx(cfg.dem, gdal.OF_RASTER | gdal.OF_READONLY, allowed_drivers=['GTiff', 'HFA', 'AAIGrid', 'USGSDEM', 'SRTMHGT', 'EHdr', 'ENVI', 'XYZ'])
        if source is None or source.RasterCount != 1:
            raise ValueError('DEM باید یک رستر ارتفاعی تک\u200cباند باشد.')
        if not source.GetProjection():
            raise ValueError('سیستم مختصات DEM مشخص نیست.')
        source_sr = spatial_ref(source.GetProjection())
        observer_source = f'ستون {cfg.observer_field!r} با واحد {cfg.observer_unit}' if cfg.observer_field else f'{cfg.observer * UNITS[cfg.observer_unit]:g} متر'
        receiver_source = f'ستون {cfg.receiver_field!r} با واحد {cfg.receiver_unit}' if cfg.receiver_field else f'{cfg.receiver * UNITS[cfg.receiver_unit]:g} متر'
        log(f"تنظیمات: شعاع {cfg.radius_m:g} متر؛ ارتفاع فرستنده/ناظر در نقطه {observer_source} بالای DEM؛ ارتفاع گیرنده روی سلول\u200cها {receiver_source} بالای DEM؛ انحنای زمین {('روشن' if cfg.curvature_enabled else 'خاموش')}؛ Atmospheric Correction={cfg.atmospheric_factor:g}؛ ضریب انحنای GDAL={cfg.curvature_coefficient:.8g}؛ واحد ارتفاع DEM: {cfg.dem_z_unit}؛ ارتفاع ناموجود: {cfg.nodata_policy}")
        output = Path(cfg.output_dir).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        folder = output / ('fast_viewshed_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        folder.mkdir()
        detail_folder = folder / 'details' if cfg.separate_outputs else folder
        detail_folder.mkdir(exist_ok=True)
        point_filenames = separate_filenames(cfg, rows) if cfg.separate_outputs else ['visible.shp'] * len(rows)
        primary_outputs = []
        fields = [('src_id', ogr.OFTInteger64), ('name', ogr.OFTString), ('az_start', ogr.OFTReal), ('az_end', ogr.OFTReal), ('radius_m', ogr.OFTReal), ('obs_m', ogr.OFTReal), ('recv_m', ogr.OFTReal), ('cell_m', ogr.OFTReal)]
        visibility_ds = visible_ds = sector_ds = None
        union_groups = {0: ogr.Geometry(ogr.wkbMultiPolygon), 1: ogr.Geometry(ogr.wkbMultiPolygon)}
        sector_union = ogr.Geometry(ogr.wkbMultiPolygon)
        summaries = []
        try:
            visibility_ds, visibility_layer = new_shape(detail_folder / 'visibility.shp', output_sr, fields + [('status', ogr.OFTInteger), ('state', ogr.OFTString)])
            if not cfg.separate_outputs:
                visible_ds, visible_layer = new_shape(folder / 'visible.shp', output_sr, fields + [('status', ogr.OFTInteger), ('state', ogr.OFTString)])
                primary_outputs.append('visible.shp')
            sector_ds, sector_layer = new_shape(detail_folder / 'sectors.shp', output_sr, fields)
            for index, record in enumerate(rows):
                if cancelled():
                    raise Cancelled()
                row = record.row
                point_cfg = replace(cfg, observer=record.observer, receiver=record.receiver)
                fid, lon, lat, start, end = row
                log(f'پردازش نقطه {index + 1}/{len(rows)}، شناسه {fid}، نام {record.name!r}')
                if cfg.name_field and record.name_fallback:
                    log(f'FID={fid}: ستون نام خالی بود؛ {record.name} استفاده شد.')
                local_start = time.perf_counter()
                classes, gt, local_sr, sector, cell = local_result(source, source_sr, row, point_cfg, log, lambda f: progress((index + f) / len(rows) * 0.95), cancelled)
                if cfg.separate_outputs:
                    visible_ds, visible_layer = new_shape(folder / point_filenames[index], output_sr, fields + [('status', ogr.OFTInteger), ('state', ogr.OFTString)])
                transform = osr.CoordinateTransformation(local_sr, output_sr)
                output_sector = sector.Clone()
                output_sector.Transform(transform)
                if output_sr.IsGeographic():
                    ring = output_sector.GetGeometryRef(0)
                    if any((abs(ring.GetX(i) - ring.GetX(i - 1)) > 180 for i in range(1, ring.GetPointCount()))):
                        raise ValueError('قطاع از مرز ۱۸۰ درجه می\u200cگذرد؛ یک EPSG تصویرشدهٔ مناسب برای خروجی انتخاب کنید.')
                values = dict(src_id=fid, name=record.name, az_start=start, az_end=end, radius_m=cfg.radius_m, obs_m=point_cfg.observer * UNITS[cfg.observer_unit], recv_m=point_cfg.receiver * UNITS[cfg.receiver_unit], cell_m=cell)
                write_feature(sector_layer, output_sector, values)
                if cfg.merge_coverage:
                    sector_union.AddGeometry(output_sector)
                raster = raster_dataset(classes, gt, local_sr.ExportToWkt(), 255)
                polygons = ogr.GetDriverByName('Memory').CreateDataSource('')
                layer = polygons.CreateLayer('classes', srs=local_sr, geom_type=ogr.wkbPolygon)
                layer.CreateField(ogr.FieldDefn('status', ogr.OFTInteger))
                log(f'نقطه {fid}: تبدیل نتیجه به پلی\u200cگون Shapefile')

                def polygon_progress(fraction, message, data):
                    progress((index + 0.85 + 0.15 * fraction) / len(rows) * 0.95)
                    return 0 if cancelled() else 1
                gdal.Polygonize(raster.GetRasterBand(1), raster.GetRasterBand(1).GetMaskBand(), layer, 0, callback=polygon_progress)
                areas = {str(i): 0.0 for i in (0, 1, 2)}
                for feature in layer:
                    status = feature.GetField('status')
                    geometry = feature.GetGeometryRef().Intersection(sector)
                    areas[str(status)] += geometry.GetArea()
                    geometry.Transform(transform)
                    write_feature(visibility_layer, geometry, {**values, 'status': status, 'state': CLASS_NAMES[status]})
                    if status == 1:
                        write_feature(visible_layer, geometry, {**values, 'status': 1, 'state': 'visible'})
                    if cfg.merge_coverage and status in (0, 1):
                        for piece in polygon_parts(geometry):
                            union_groups[status].AddGeometry(piece)
                preview(fid, classes.copy(), dict(cell=cell, lon=lon, lat=lat, name=record.name))
                counts = {str(i): int(np.count_nonzero(classes == i)) for i in (0, 1, 2)}
                total = sum(counts.values())
                farthest_visible = visible_radius(classes, gt)
                log(f"نقطه {fid}: قابل\u200cدید {counts['1'] / total:.1%} | پنهان {counts['0'] / total:.1%} | نامعلوم {counts['2'] / total:.1%}؛ خروجی قابل\u200cدید: {point_filenames[index]}")
                log(f'نقطه {fid}: دورترین سلول قابل\u200cدید {farthest_visible / 1000:.3f} کیلومتر؛ حد تحلیل {cfg.radius_m / 1000:g} کیلومتر')
                if not counts['1']:
                    log(f'نقطه {fid}: هیچ سلول قابل\u200cدیدی پیدا نشد؛ برای بررسی ارتفاع\u200cها، واحد DEM و تفکیک، run.json و گزارش را نگه دارید.')
                summaries.append(dict(src_id=fid, name=record.name, observer_at_point_m=values['obs_m'], receiver_on_cells_m=values['recv_m'], output=point_filenames[index], cell_m=cell, grid_shape=list(classes.shape), counts=counts, areas_m2=areas, max_visible_distance_m=farthest_visible, seconds=time.perf_counter() - local_start))
                visibility_layer.SyncToDisk()
                visible_layer.SyncToDisk()
                sector_layer.SyncToDisk()
                if cfg.separate_outputs:
                    visible_layer = visible_ds = None
                    primary_outputs.append(point_filenames[index])
                layer = polygons = raster = None
                del classes
            visibility_layer = visible_layer = sector_layer = None
            visibility_ds = visible_ds = sector_ds = None
            if cfg.merge_coverage:
                log('ادغام پوشش\u200cها؛ قابل رؤیت بودن از یک نقطه اولویت دارد…')
                visible = union_groups[1].UnionCascaded() if union_groups[1].GetGeometryCount() else ogr.Geometry(ogr.wkbMultiPolygon)
                hidden = union_groups[0].UnionCascaded() if union_groups[0].GetGeometryCount() else ogr.Geometry(ogr.wkbMultiPolygon)
                hidden = hidden.Difference(visible) if not visible.IsEmpty() else hidden
                known = visible.Union(hidden)
                unknown = sector_union.UnionCascaded().Difference(known)
                coverage_ds, coverage_layer = new_shape(folder / 'coverage.shp', output_sr, [('name', ogr.OFTString), ('status', ogr.OFTInteger), ('state', ogr.OFTString)])
                for status, geometry in ((0, hidden), (1, visible), (2, unknown)):
                    if cancelled():
                        raise Cancelled()
                    write_feature(coverage_layer, geometry, {'name': 'coverage_' + CLASS_NAMES[status], 'status': status, 'state': CLASS_NAMES[status]})
                coverage_layer = coverage_ds = None
                write_qml(folder / 'coverage.shp')
            write_qml(detail_folder / 'visibility.shp')
            for filename in primary_outputs:
                write_qml(folder / filename, visible_only=True)
            (folder / 'README_RESULTS_FA.txt').write_text('فایل\u200cهای اصلی قابل\u200cدید:\n' + '\n'.join(primary_outputs) + '\nاین لایه فقط پلی\u200cگون\u200cهای status=1 را دارد؛ نواحی پنهان و نامعلوم داخل آن نیستند.\nدر حالت خروجی جدا، لایه\u200cهای کمکی visibility و sectors داخل پوشهٔ details هستند.\nستون name نام انتخابی نقطه است؛ در صورت نبود نام، FID استفاده می\u200cشود.\nدر نام فایل\u200cهای مستقل، عدد پایانی ارتفاع فرستنده/آبجکت در محل نقطه، بر حسب متر است.\nدر ArcGIS Pro برای آن Fill قرمز و Outline دلخواه تنظیم کنید.\nsectors.shp فقط مرز شعاع و آزیموت تحلیل است.\nvisibility.shp هر سه کلاس را دارد: 1=قابل\u200cدید، 0=پنهان، 2=نامعلوم.\nنمایش همهٔ این کلاس\u200cها با یک نماد، شکل قطاع کامل را نشان می\u200cدهد.\nدر صورت وجود چند ناظر، برای مقایسهٔ یک ناظر با Global Mapper، src_id همان ناظر را فیلتر کنید.\nبرای مقایسهٔ محاسبه، DEM، موقعیت ناظر، ارتفاع فرستنده در نقطه و گیرنده روی سلول\u200cها، واحدها، شعاع، آزیموت، اندازهٔ واقعی پیکسل و تنظیم انحنا/شکست باید یکسان باشند.\nrun.json تنظیمات و شمارش و مساحت کلاس\u200cها را برای بررسی ذخیره می\u200cکند.\nمطابقت محاسبات با Global Mapper روی دادهٔ شما هنوز تأیید نشده است.\n', encoding='utf-8')
            report = dict(status='completed', application_version='3.2.0', offline=True, engine=gdal.VersionInfo('--version'), method='GDAL GVM_Edge / Wang', settings=asdict(cfg), observers=summaries, seconds=time.perf_counter() - started, output_crs=output_sr.ExportToWkt(), classes=CLASS_NAMES, primary_output=None if cfg.separate_outputs else 'visible.shp', primary_outputs=primary_outputs, output_mode='per_observer' if cfg.separate_outputs else 'combined', height_mapping={'observer_at_point_m': None if cfg.observer_field else cfg.observer * UNITS[cfg.observer_unit], 'receiver_on_cells_m': None if cfg.receiver_field else cfg.receiver * UNITS[cfg.receiver_unit], 'observer_field': cfg.observer_field, 'receiver_field': cfg.receiver_field, 'curvature_coefficient': cfg.curvature_coefficient}, outputs={**{name: 'visible cells only (status=1)' for name in primary_outputs}, (detail_folder / 'visibility.shp').relative_to(folder).as_posix(): 'all classes; requires class symbology or filtering', (detail_folder / 'sectors.shp').relative_to(folder).as_posix(): 'analysis bounds, not visibility'}, notes=['Per-observer AEQD grids preserve radial distances and true bearings.', 'NoData policy: ' + cfg.nodata_policy, 'Results are grid approximations; equivalence to Esri/Global Mapper is not established.'])
            (folder / 'run.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            progress(1)
            log(f"پایان: {report['seconds']:.2f} ثانیه | {folder}\nتعداد شیپ\u200cفایل اصلی قابل\u200cدید: {len(primary_outputs)}")
            return str(folder)
        except Exception as exc:
            visibility_layer = visible_layer = sector_layer = None
            visibility_ds = visible_ds = sector_ds = None
            (folder / 'FAILED.txt').write_text(str(exc) or 'Cancelled; outputs may be partial.', encoding='utf-8')
            if cancelled():
                raise Cancelled() from exc
            raise
    'Qt desktop GUI. GDAL runs on a worker thread; there is no ArcPy import.'
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
    UNIT_LABELS = [('متر', 'm'), ('کیلومتر', 'km'), ('فوت', 'ft'), ('مایل', 'mi')]

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
            percent = int(fraction * 100)
            now = time.monotonic()
            if percent != self.last_percent and (percent == 100 or now - self.last_progress_time >= 0.05):
                self.last_percent = percent
                self.last_progress_time = now
                self.progress.emit(percent)

        @QtCore.Slot()
        def run(self):
            try:
                folder = run_fast(self.config, self.message.emit, self.update_progress, self.cancel_event.is_set, self.preview.emit)
                self.result.emit(folder)
            except Cancelled:
                self.error.emit('عملیات لغو شد؛ خروجی نیمه\u200cتمام معتبر نیست.')
            except Exception:
                self.error.emit(traceback.format_exc())
            finally:
                self.stopped.emit()

    class FastWindow(QtWidgets.QMainWindow):

        def __init__(self):
            super().__init__()
            self.setWindowTitle('Fast Sector Viewshed 3.2 | دیدپذیری قطاعی آفلاین')
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
            self.output_hint = 'visible.shp'
            self.build_ui()

        def build_ui(self):
            root = QtWidgets.QWidget()
            outer = QtWidgets.QVBoxLayout(root)
            outer.setContentsMargins(18, 16, 18, 12)
            title = QtWidgets.QLabel('دیدپذیری قطاعی — ورودی و خروجی Shapefile')
            title.setObjectName('title')
            subtitle = QtWidgets.QLabel('برنامهٔ مستقل • آزیموت از شمال واقعی و ساعت\u200cگرد • خروجی سازگار با ArcGIS Pro و QGIS')
            outer.addWidget(title)
            outer.addWidget(subtitle)
            split = QtWidgets.QSplitter()
            outer.addWidget(split, 1)
            scroll = QtWidgets.QScrollArea()
            self.form_scroll = scroll
            scroll.setWidgetResizable(True)
            scroll.setMinimumWidth(490)
            form_widget = QtWidgets.QWidget()
            self.form_widget = form_widget
            form = QtWidgets.QVBoxLayout(form_widget)
            scroll.setWidget(form_widget)
            split.addWidget(scroll)
            inputs, grid = self.group('داده\u200cهای ورودی', form)
            self.path_row(grid, 0, 'points', 'نقاط Shapefile / GeoJSON', self.choose_shape)
            self.read_fields = QtWidgets.QPushButton('خواندن ستون\u200cهای اتریبیوت')
            self.read_fields.clicked.connect(self.load_fields)
            grid.addWidget(self.read_fields, 1, 1, 1, 2)
            self.shape_info = QtWidgets.QLabel('همهٔ نقاط فایل پردازش می\u200cشوند.')
            self.shape_info.setWordWrap(True)
            grid.addWidget(self.shape_info, 2, 0, 1, 3)
            for row, name, text in [(3, 'start_field', 'ستون آزیموت شروع'), (4, 'end_field', 'ستون آزیموت پایان')]:
                combo = QtWidgets.QComboBox()
                combo.setLayoutDirection(QtCore.Qt.LeftToRight)
                self.inputs[name] = combo
                grid.addWidget(QtWidgets.QLabel(text), row, 0)
                grid.addWidget(combo, row, 1, 1, 2)
            note = QtWidgets.QLabel('نمونه: ۳۵۰٫۵، 350:30:00 یا N45E\n۳۵۰ تا ۲۰ از شمال عبور می\u200cکند؛ شروع و پایان برابر یعنی دایرهٔ کامل.')
            note.setWordWrap(True)
            grid.addWidget(note, 5, 0, 1, 3)
            self.path_row(grid, 6, 'dem', 'DEM ارتفاعی', self.choose_dem)
            self.unit_row(grid, 7, 'dem_z_unit', 'واحد ارتفاع پیکسل\u200cهای DEM', only_dem=True)
            fid = QtWidgets.QSpinBox()
            fid.setRange(-1, 2147483647)
            fid.setValue(-1)
            fid.setSpecialValueText('همهٔ نقاط')
            self.inputs['observer_fid'] = fid
            grid.addWidget(QtWidgets.QLabel('فقط FID؛ منفی یک = همه'), 8, 0)
            grid.addWidget(fid, 8, 1, 1, 2)
            self.reference_button = QtWidgets.QPushButton('اعمال تنظیمات تصویر Global Mapper برای FID=1')
            self.reference_button.clicked.connect(self.apply_reference_settings)
            grid.addWidget(self.reference_button, 9, 0, 1, 3)
            dimensions, grid = self.group('شعاع و ارتفاع\u200cهای بالای زمین', form)
            self.number_row(grid, 0, 'radius', 'شعاع قطاع', 5, 'radius_unit', 'km')
            self.number_row(grid, 1, 'observer', 'فرستنده / ناظر در محل نقطه، بالای DEM', 100, 'observer_unit')
            self.number_row(grid, 2, 'receiver', 'گیرنده روی سلول\u200cهای اطراف، بالای DEM', 2, 'receiver_unit')
            mapping_note = QtWidgets.QLabel('Transmitter Elevation → ارتفاع فرستنده در نقطه\nReceiver Elevation → ارتفاع گیرنده در هر سلول مقصد')
            mapping_note.setWordWrap(True)
            grid.addWidget(mapping_note, 3, 0, 1, 3)
            for row, kind, label in ((4, 'observer', 'فرستنده از ستون'), (5, 'receiver', 'گیرنده از ستون')):
                mode = QtWidgets.QCheckBox(label)
                combo = QtWidgets.QComboBox()
                combo.setLayoutDirection(QtCore.Qt.LeftToRight)
                combo.setEnabled(False)
                self.inputs[kind + '_field'] = combo
                self.height_modes[kind] = mode
                mode.toggled.connect(combo.setEnabled)
                mode.toggled.connect(self.inputs[kind].setDisabled)
                grid.addWidget(mode, row, 0)
                grid.addWidget(combo, row, 1, 1, 2)
            height_note = QtWidgets.QLabel('ستون ارتفاع می\u200cتواند عددی یا تکست باشد، مانند ۲، 2.5 یا 1e2. واحد ستون از کمبوباکس واحد همان ارتفاع گرفته می\u200cشود.')
            height_note.setWordWrap(True)
            grid.addWidget(height_note, 6, 0, 1, 3)
            accuracy, grid = self.group('سرعت و تفکیک مکانی', form)
            self.number_row(grid, 0, 'cell_size', 'اندازهٔ پیکسل، متر؛ صفر = خودکار', 0)
            self.inputs['cell_size'].setSpecialValueText('خودکار')
            self.resolution = QtWidgets.QComboBox()
            for label, factor in [('تفکیک اصلی DEM', 1), ('سریع: پیکسل ۲ برابر درشت\u200cتر', 2), ('سریع\u200cتر: پیکسل ۴ برابر درشت\u200cتر', 4)]:
                self.resolution.addItem(label, factor)
            grid.addWidget(QtWidgets.QLabel('حالت تفکیک'), 1, 0)
            grid.addWidget(self.resolution, 1, 1, 1, 2)
            self.number_row(grid, 2, 'atmospheric_factor', 'Atmospheric Correction (ضریب شعاع مؤثر k)', 1.33333)
            self.inputs['atmospheric_factor'].setDecimals(8)
            self.inputs['atmospheric_factor'].setRange(1e-06, 1000)
            self.inputs['atmospheric_factor'].setValue(1.33333)
            epsg = QtWidgets.QSpinBox()
            epsg.setRange(0, 999999)
            epsg.setSpecialValueText('سیستم مختصات شیپ\u200cفایل ورودی')
            self.inputs['output_epsg'] = epsg
            grid.addWidget(QtWidgets.QLabel('EPSG خروجی؛ صفر = ورودی'), 3, 0)
            grid.addWidget(epsg, 3, 1, 1, 2)
            warning = QtWidgets.QLabel('پیکسل درشت\u200cتر سریع\u200cتر است و جزئیات کمتری نگه می\u200cدارد. نتیجهٔ موتور GDAL ممکن است با Esri یا Global Mapper تفاوت داشته باشد.')
            warning.setWordWrap(True)
            grid.addWidget(warning, 4, 0, 1, 3)
            self.auto_coarsen = QtWidgets.QCheckBox('پیکسل خودکار برای شبکهٔ بزرگ (کاهش جزئیات)')
            self.auto_coarsen.setChecked(True)
            grid.addWidget(self.auto_coarsen, 5, 0, 1, 3)
            limit = QtWidgets.QSpinBox()
            limit.setRange(1, 100)
            limit.setValue(25)
            self.inputs['max_grid_mcells'] = limit
            grid.addWidget(QtWidgets.QLabel('سقف شبکهٔ هر نقطه، میلیون سلول'), 6, 0)
            grid.addWidget(limit, 6, 1, 1, 2)
            memory_note = QtWidgets.QLabel('برای حفظ پیکسل درخواستی، تنظیم خودکار را خاموش و سقف را افزایش دهید. شبکهٔ بزرگ حافظه و زمان بیشتری مصرف می\u200cکند؛ این عدد سقف مصرف RAM نیست.')
            memory_note.setWordWrap(True)
            grid.addWidget(memory_note, 7, 0, 1, 3)
            self.curvature = QtWidgets.QCheckBox('محاسبهٔ انحنای زمین و شکست جوی')
            self.curvature.setChecked(True)
            self.curvature.toggled.connect(self.inputs['atmospheric_factor'].setEnabled)
            grid.addWidget(self.curvature, 8, 0, 1, 3)
            curvature_note = QtWidgets.QLabel('۱٫۳۳۳۳۳ مستقیماً مانند تصویر وارد می\u200cشود؛ ضریب انحنای GDAL برابر ۱/k است. این مقدار با ضریب شکست ۰٫۱۳ فرق دارد.')
            curvature_note.setWordWrap(True)
            grid.addWidget(curvature_note, 9, 0, 1, 3)
            self.inputs['nodata_policy'] = QtWidgets.QComboBox()
            self.inputs['nodata_policy'].addItem('نامعلوم؛ مسیر خلأ DEM قابل\u200cدید محسوب نشود', 'unknown')
            self.inputs['nodata_policy'].addItem('Treat Missing Elevations as Ocean — ارتفاع صفر', 'sea_level')
            self.inputs['nodata_policy'].setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            self.inputs['nodata_policy'].setMinimumContentsLength(12)
            grid.addWidget(QtWidgets.QLabel('ارتفاع\u200cهای ناموجود'), 10, 0)
            grid.addWidget(self.inputs['nodata_policy'], 10, 1, 1, 2)
            output, grid = self.group('خروجی', form)
            self.path_row(grid, 0, 'output_dir', 'پوشهٔ ذخیره', self.choose_output)
            self.inputs['output_dir'].setText(str(Path.home() / 'Documents' / 'FastViewshedResults'))
            self.merge = QtWidgets.QCheckBox('تولید coverage.shp با ادغام پوشش نقاط (زمان بیشتر)')
            grid.addWidget(self.merge, 1, 0, 1, 3)
            description = QtWidgets.QLabel('خروجی اصلی: visible.shp، فقط محدودهٔ قابل\u200cدید\nvisibility.shp: هر سه کلاس دیدپذیری\nsectors.shp: فقط مرز تحلیل؛ برای نمایش ویوشد visible.shp را باز کنید.')
            self.output_description = description
            description.setWordWrap(True)
            grid.addWidget(description, 2, 0, 1, 3)
            self.inputs['name_field'] = QtWidgets.QComboBox()
            self.inputs['name_field'].addItem('نام پیش\u200cفرض از FID', '')
            grid.addWidget(QtWidgets.QLabel('ستون نام نقطه برای name'), 3, 0)
            grid.addWidget(self.inputs['name_field'], 3, 1, 1, 2)
            self.separate = QtWidgets.QCheckBox('برای هر نقطه یک شیپ\u200cفایل قابل\u200cدید مستقل')
            self.separate.toggled.connect(self.toggle_separate_outputs)
            grid.addWidget(self.separate, 4, 0, 1, 3)
            naming_note = QtWidgets.QLabel('بدون تیک: همهٔ نقاط در visible.shp\nبا تیک: نام فایل مرجع-نام نقطه-ارتفاع فرستنده.shp\nارتفاعِ نام فایل بر حسب متر است؛ نام تکراری با FID متمایز می\u200cشود. لایه\u200cهای کمکی در details ذخیره می\u200cشوند.')
            naming_note.setWordWrap(True)
            grid.addWidget(naming_note, 5, 0, 1, 3)
            form.addStretch()
            for group in form_widget.findChildren(QtWidgets.QGroupBox):
                layout = group.layout()
                for index in range(layout.count()):
                    widget = layout.itemAt(index).widget()
                    _, column, _, span = layout.getItemPosition(index)
                    if isinstance(widget, QtWidgets.QLabel) and column == 0 and (span == 1):
                        widget.setWordWrap(True)
                        widget.setMaximumWidth(155)
            tabs = QtWidgets.QTabWidget()
            split.addWidget(tabs)
            preview_tab = QtWidgets.QWidget()
            preview_layout = QtWidgets.QVBoxLayout(preview_tab)
            self.preview_selector = QtWidgets.QComboBox()
            self.preview_selector.currentIndexChanged.connect(self.show_preview)
            preview_layout.addWidget(self.preview_selector)
            self.preview_mode = QtWidgets.QComboBox()
            self.preview_mode.addItem('فقط محدودهٔ قابل\u200cدید — قرمز', 'visible')
            self.preview_mode.addItem('همهٔ کلاس\u200cها — قابل\u200cدید، پنهان، نامعلوم', 'classes')
            self.preview_mode.currentIndexChanged.connect(self.show_preview)
            preview_layout.addWidget(self.preview_mode)
            self.image = QtWidgets.QLabel('پیش\u200cنمایش هر نقطه پس از محاسبه نمایش داده می\u200cشود.')
            self.image.setAlignment(QtCore.Qt.AlignCenter)
            self.image.setMinimumSize(300, 300)
            self.image.setStyleSheet('background:#f3f6f8; border:1px solid #cad4df; border-radius:8px;')
            preview_layout.addWidget(self.image, 1)
            self.preview_note = QtWidgets.QLabel('قرمز: قابل\u200cدید • سفید: سایر نواحی • خروجی: visible.shp')
            self.preview_note.setWordWrap(True)
            preview_layout.addWidget(self.preview_note)
            tabs.addTab(preview_tab, 'پیش\u200cنمایش دیدپذیری')
            self.log = QtWidgets.QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.setMaximumBlockCount(10000)
            tabs.addTab(self.log, 'گزارش اجرا')
            self.tabs = tabs
            split.setSizes([540, 680])
            actions = QtWidgets.QHBoxLayout()
            self.run_button = QtWidgets.QPushButton('محاسبه و تولید Shapefile')
            self.run_button.setObjectName('run')
            self.run_button.clicked.connect(self.start_analysis)
            self.cancel_button = QtWidgets.QPushButton('لغو')
            self.cancel_button.setEnabled(False)
            self.cancel_button.clicked.connect(self.cancel_analysis)
            self.open_button = QtWidgets.QPushButton('باز کردن پوشهٔ نتیجه')
            self.open_button.setEnabled(False)
            self.open_button.clicked.connect(self.open_results)
            save = QtWidgets.QPushButton('ذخیرهٔ گزارش')
            save.clicked.connect(self.save_log)
            for button in (self.run_button, self.cancel_button, self.open_button, save):
                actions.addWidget(button)
            outer.addLayout(actions)
            self.progress_bar = QtWidgets.QProgressBar()
            self.progress_bar.setRange(0, 100)
            outer.addWidget(self.progress_bar)
            self.status = QtWidgets.QLabel('آماده')
            self.status.setWordWrap(True)
            outer.addWidget(self.status)
            self.setCentralWidget(root)
            self.setStyleSheet('\n            QWidget {font-family: "Segoe UI", "Tahoma"; font-size: 12px; color:#17364b;}\n            QMainWindow {background:#eef3f7;}\n            QLabel#title {font-size:25px; font-weight:700; padding:6px 0;}\n            QGroupBox {font-weight:600; border:1px solid #cedae4; border-radius:8px; margin-top:14px; padding:15px 8px 8px; background:white;}\n            QGroupBox::title {subcontrol-origin:margin; padding:0 5px;}\n            QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox {padding:7px; border:1px solid #bbcbd7; border-radius:4px; background:white;}\n            QPushButton {padding:9px 12px; border:1px solid #b8cbd9; border-radius:5px; background:#edf4f8;}\n            QPushButton#run {background:#146e87; color:white; font-weight:700;}\n            QPushButton:disabled {color:#8997a2; background:#e6ebee;}\n            QProgressBar {border:1px solid #bbcbd7; border-radius:4px; text-align:center; height:17px;}\n            QProgressBar::chunk {background:#26a782;}\n            QPlainTextEdit {background:#142b3b; color:#e7eef5; font-family:Consolas;}\n        ')

        @staticmethod
        def group(title, parent):
            box = QtWidgets.QGroupBox(title)
            grid = QtWidgets.QGridLayout(box)
            grid.setColumnStretch(1, 1)
            parent.addWidget(box)
            return (box, grid)

        def path_row(self, grid, row, name, label, callback):
            widget = QtWidgets.QLineEdit()
            widget.setLayoutDirection(QtCore.Qt.LeftToRight)
            self.inputs[name] = widget
            button = QtWidgets.QPushButton('انتخاب…')
            button.clicked.connect(callback)
            grid.addWidget(QtWidgets.QLabel(label), row, 0)
            grid.addWidget(widget, row, 1)
            grid.addWidget(button, row, 2)

        def unit_row(self, grid, row, name, label, only_dem=False):
            combo = QtWidgets.QComboBox()
            for text, key in UNIT_LABELS:
                if not only_dem or key in ('m', 'ft'):
                    combo.addItem(text, key)
            self.unit_boxes[name] = combo
            grid.addWidget(QtWidgets.QLabel(label), row, 0)
            grid.addWidget(combo, row, 1, 1, 2)

        def number_row(self, grid, row, name, label, default, unit_name=None, unit_default='m'):
            spin = QtWidgets.QDoubleSpinBox()
            spin.setDecimals(4)
            spin.setRange(0, 1000000)
            spin.setValue(default)
            spin.setLayoutDirection(QtCore.Qt.LeftToRight)
            spin.setLocale(QtCore.QLocale('fa_IR'))
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
            name, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'فایل نقاط', '', 'Point files (*.shp *.geojson *.json);;Shapefile (*.shp);;GeoJSON (*.geojson *.json)')
            if name:
                self.inputs['points'].setText(name)
                self.load_fields()

        def choose_dem(self):
            name, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'DEM', '', 'Elevation (*.tif *.tiff *.img *.asc *.dem);;All files (*)')
            if name:
                self.inputs['dem'].setText(name)

        def choose_output(self):
            name = QtWidgets.QFileDialog.getExistingDirectory(self, 'پوشهٔ خروجی')
            if name:
                self.inputs['output_dir'].setText(name)

        def load_fields(self):
            path = self.inputs['points'].text().strip()
            self.loaded_shape = None
            for key in ('start_field', 'end_field', 'observer_field', 'receiver_field', 'name_field'):
                self.inputs[key].clear()
            self.inputs['name_field'].addItem('نام پیش\u200cفرض از FID', '')
            try:
                metadata = inspect_shape(path)
                for key in ('start_field', 'end_field', 'observer_field', 'receiver_field'):
                    self.inputs[key].addItems(metadata['fields'])
                    self.inputs[key].setCurrentIndex(-1)
                for field in metadata['fields']:
                    self.inputs['name_field'].addItem(field, field)
                default_name = next((name for name in metadata['fields'] if name.casefold() in ('name', 'نام')), '')
                self.inputs['name_field'].setCurrentIndex(self.inputs['name_field'].findData(default_name))
                self.loaded_shape = path
                self.shape_info.setText(f"{metadata['count']} نقطه | {metadata['crs']}")
                self.log.appendPlainText('ستون\u200cها خوانده شدند: ' + ', '.join(metadata['fields']))
            except Exception as exc:
                self.show_error(str(exc))

        def settings(self):
            if self.inputs['points'].text().strip() != self.loaded_shape:
                raise ValueError('ابتدا ستون\u200cهای شیپ\u200cفایل فعلی را بخوانید.')
            data = {}
            for name, widget in self.inputs.items():
                if isinstance(widget, QtWidgets.QLineEdit):
                    data[name] = widget.text().strip()
                elif isinstance(widget, QtWidgets.QComboBox):
                    data[name] = widget.currentData() if name == 'nodata_policy' else widget.currentText()
                else:
                    data[name] = widget.value()
            data.update({name: widget.currentData() for name, widget in self.unit_boxes.items()})
            data['resolution_factor'] = self.resolution.currentData()
            data['merge_coverage'] = self.merge.isChecked()
            data['auto_coarsen'] = self.auto_coarsen.isChecked()
            data['curvature_enabled'] = self.curvature.isChecked()
            data['separate_outputs'] = self.separate.isChecked()
            data['name_field'] = self.inputs['name_field'].currentData() or ''
            for kind, mode in self.height_modes.items():
                field = self.inputs[kind + '_field'].currentText() if mode.isChecked() else ''
                if mode.isChecked() and (not field):
                    raise ValueError('ستون ارتفاع را انتخاب کنید: ' + mode.text())
                data[kind + '_field'] = field
            config = FastSettings(**data)
            config.validate()
            return config

        def apply_reference_settings(self):
            """The supplied GM dialog's public parameters, without embedding data."""
            for mode in self.height_modes.values():
                mode.setChecked(False)
            for name, value in (('radius', 100), ('observer', 100), ('receiver', 2), ('atmospheric_factor', 1.33333), ('cell_size', 350), ('observer_fid', 1)):
                self.inputs[name].setValue(value)
            for name, unit in (('radius_unit', 'km'), ('observer_unit', 'm'), ('receiver_unit', 'm'), ('dem_z_unit', 'm')):
                self.unit_boxes[name].setCurrentIndex(self.unit_boxes[name].findData(unit))
            for name, field in (('start_field', 'AZFR'), ('end_field', 'AZTO')):
                index = self.inputs[name].findText(field)
                if index >= 0:
                    self.inputs[name].setCurrentIndex(index)
            self.resolution.setCurrentIndex(self.resolution.findData(1))
            self.curvature.setChecked(True)
            self.auto_coarsen.setChecked(False)
            self.inputs['nodata_policy'].setCurrentIndex(self.inputs['nodata_policy'].findData('sea_level'))
            self.log.appendPlainText('تنظیم مرجع: FID=1؛ فرستنده در نقطه 100m، گیرنده روی سلول\u200cها 2m، شعاع 100km، k=1.33333، ارتفاع ناموجود=دریا. فاصلهٔ نمونه\u200cبرداری 350m تقریب فاصلهٔ زاویه\u200cای تصویر است؛ تطابق دقیق شبکه با Global Mapper تأیید نشده است.')

        def toggle_separate_outputs(self, checked):
            if checked:
                self.merge.setChecked(False)
            self.merge.setEnabled(not checked)
            self.output_description.setText('خروجی اصلی: یک فایل نام\u200cگذاری\u200cشده برای هر نقطه\nلایه\u200cهای کمکی visibility.shp و sectors.shp داخل details قرار می\u200cگیرند.' if checked else 'خروجی اصلی: visible.shp، همهٔ نقاط در یک لایهٔ قابل\u200cدید\nvisibility.shp: همهٔ کلاس\u200cها • sectors.shp: فقط مرز تحلیل')

        def start_analysis(self):
            if self.thread is not None:
                return
            try:
                config = self.settings()
            except Exception as exc:
                self.show_error(str(exc))
                return
            self.result_folder = None
            self.output_hint = 'فایل مستقل هر نقطه' if config.separate_outputs else 'visible.shp'
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
            self.log.appendPlainText('\n── تحلیل آفلاین با GDAL | نسخهٔ 3.2 ──')
            self.status.setText('در حال پردازش…')
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
            self.status.setText('نتیجهٔ Shapefile ذخیره شد: ' + folder)

        @QtCore.Slot()
        def finished(self):
            thread = self.thread
            if thread is not None and (not thread.wait(100)):
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
            stride = max(1, (max(classes.shape) + 1399) // 1400)
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
            visible_image = QtGui.QImage(visible_rgba.data, visible_rgba.shape[1], visible_rgba.shape[0], visible_rgba.strides[0], QtGui.QImage.Format_RGBA8888).copy()
            self.visible_previews[fid] = QtGui.QPixmap.fromImage(visible_image)
            label = metadata.get('name', f'نقطه {fid}')
            self.preview_selector.addItem(f"{label} | FID={fid} | پیکسل {metadata['cell']:.2f} متر", fid)
            self.preview_selector.setCurrentIndex(self.preview_selector.count() - 1)
            self.show_preview()

        def show_preview(self, index=None):
            fid = self.preview_selector.currentData()
            only_visible = self.preview_mode.currentData() == 'visible'
            images = self.visible_previews if only_visible else self.preview_images
            self.preview_note.setText(f'قرمز: قابل\u200cدید • سفید: سایر نواحی • خروجی: {self.output_hint}' if only_visible else 'سبز: قابل\u200cدید • قرمز: پنهان • خاکستری: نامعلوم • سفید: بیرون قطاع')
            if fid in images:
                self.image.setPixmap(images[fid].scaled(self.image.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation))

        def resizeEvent(self, event):
            super().resizeEvent(event)
            if hasattr(self, 'preview_images'):
                self.show_preview()

        def cancel_analysis(self):
            self.cancel_event.set()
            self.status.setText('درخواست لغو ثبت شد؛ در نخستین نقطهٔ امن متوقف می\u200cشود…')
            self.cancel_button.setEnabled(False)

        def show_error(self, detail):
            logging.getLogger('fast_viewshed').error(detail)
            self.log.appendPlainText(detail)
            self.status.setText('عملیات کامل نشد؛ گزارش اجرا را بررسی کنید.')
            self.tabs.setCurrentIndex(1)

        def open_results(self):
            if self.result_folder:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.result_folder))

        def save_log(self):
            name, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'ذخیرهٔ گزارش', 'viewshed_log.txt', 'Text (*.txt)')
            if name:
                try:
                    Path(name).write_text(self.log.toPlainText(), encoding='utf-8')
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
        app.setApplicationName('FastSectorViewshed')
        app.setFont(QtGui.QFont('Segoe UI', 10))
        window = FastWindow()
        window._fast_app_reference = app
        window.show()
        return app.exec()
    if __name__ == '__main__':
        raise SystemExit(fast_main())
except Exception as _fast_startup_exception:
    if __name__ == '__main__':
        fast_startup_error(_fast_startup_exception)
        raise SystemExit(1)
    raise
