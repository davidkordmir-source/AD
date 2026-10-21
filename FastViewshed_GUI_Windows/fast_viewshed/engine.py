"""Compiled GDAL viewshed on local equidistant grids, exported as Shapefiles."""

from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime
import json
import csv
import math
from pathlib import Path
import re
import time
import unicodedata

import numpy as np
from osgeo import gdal, ogr, osr

from .model import FastSettings, ObserverRecord, Cancelled, azimuth, angle_ranges, number, UNITS


gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()
gdal.SetConfigOption("PROJ_NETWORK", "OFF")
osr.SetPROJEnableNetwork(False)

CLASS_NAMES = {0: "hidden", 1: "visible", 2: "unknown"}


def spatial_ref(definition):
    sr = osr.SpatialReference()
    sr.SetFromUserInput(str(definition))
    sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return sr


def inspect_shape(path):
    if not Path(path).is_file():
        raise ValueError("فایل نقاط باید روی دستگاه موجود باشد؛ دریافت اینترنتی ورودی پشتیبانی نمی‌شود.")
    ds = gdal.OpenEx(str(path), gdal.OF_VECTOR | gdal.OF_READONLY,
                     allowed_drivers=["ESRI Shapefile", "GeoJSON"])
    if ds is None:
        raise ValueError("فایل نقاط باز نشد؛ برای Shapefile فایل‌های SHP، SHX و DBF را بررسی کنید.")
    layer = ds.GetLayer(0)
    sr = layer.GetSpatialRef()
    if sr is None:
        raise ValueError("شیپ‌فایل سیستم مختصات ندارد؛ فایل PRJ لازم است.")
    allowed = {ogr.OFTInteger, ogr.OFTInteger64, ogr.OFTReal, ogr.OFTString}
    definition = layer.GetLayerDefn()
    fields = [definition.GetFieldDefn(i).GetName() for i in range(definition.GetFieldCount())
              if definition.GetFieldDefn(i).GetType() in allowed]
    return {"fields": fields, "count": layer.GetFeatureCount(), "crs": sr.GetName()}


def reject_record(skipped, log, fid, name, stage, exc, field=""):
    item = dict(src_id=fid, name=name, stage=stage, field=field,
                error=str(exc) or type(exc).__name__, exception_type=type(exc).__name__)
    skipped.append(item)
    column = f"، ستون {field!r}" if field else ""
    log(f"رد شد — FID={fid}، نام {name!r}{column}: {item['error']}")


def save_skipped_records(folder, skipped):
    (folder/"skipped_records.json").write_text(json.dumps(skipped, ensure_ascii=False, indent=2), encoding="utf-8")
    with (folder/"skipped_records.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["src_id", "name", "stage", "field", "error", "exception_type"])
        writer.writeheader()
        writer.writerows(skipped)


def load_observer_records(cfg, skipped=None, log=lambda _: None, cancelled=lambda: False):
    skipped = [] if skipped is None else skipped
    metadata = inspect_shape(cfg.points)
    selected_fields = [cfg.start_field, cfg.end_field, cfg.observer_field, cfg.receiver_field, cfg.name_field]
    missing = [field for field in selected_fields if field and field not in metadata["fields"]]
    ds = gdal.OpenEx(cfg.points, gdal.OF_VECTOR | gdal.OF_READONLY,
                     allowed_drivers=["ESRI Shapefile", "GeoJSON"])
    layer = ds.GetLayer(0)
    sr = layer.GetSpatialRef().Clone()
    sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    to_wgs = osr.CoordinateTransformation(sr, spatial_ref("EPSG:4326"))
    rows, selected = [], 0
    for feature in layer:
        if cancelled():
            raise Cancelled()
        fid = feature.GetFID()
        if cfg.observer_fid >= 0 and fid != cfg.observer_fid:
            continue
        selected += 1
        name, field = f"FID_{fid}", ""
        try:
            if missing:
                field = missing[0]
                raise ValueError("ستون انتخاب‌شده موجود نیست یا نوع پشتیبانی‌نشده دارد: "+field)
            if cfg.name_field:
                field = cfg.name_field
                raw_name = feature.GetField(field)
                if raw_name is None or not str(raw_name).strip():
                    raise ValueError(f"ستون نام {field!r} خالی است.")
                name = str(raw_name).strip()
            if len(name.encode("utf-8")) > 254:
                raise ValueError("نام انتخابی بیش از ۲۵۴ بایت UTF-8 است و در ستون name جا نمی‌شود.")
            field = "geometry"
            geometry = feature.GetGeometryRef()
            if geometry is None or geometry.IsEmpty():
                raise ValueError("هندسهٔ خالی")
            if ogr.GT_Flatten(geometry.GetGeometryType()) != ogr.wkbPoint:
                raise ValueError("هندسهٔ رکورد باید Point باشد.")
            if not math.isfinite(geometry.GetX()) or not math.isfinite(geometry.GetY()):
                raise ValueError("مختصات نقطه نامتناهی یا نامعتبر است.")
            lon, lat, _ = to_wgs.TransformPoint(geometry.GetX(), geometry.GetY())
            if not (math.isfinite(lon) and math.isfinite(lat) and -90 < lat < 90):
                raise ValueError("مختصات جغرافیایی نامعتبر")
            field = cfg.start_field
            start = azimuth(feature.GetField(field))
            field = cfg.end_field
            end = azimuth(feature.GetField(field))
            heights = []
            for field, fallback, unit in ((cfg.observer_field, cfg.observer, cfg.observer_unit),
                                           (cfg.receiver_field, cfg.receiver, cfg.receiver_unit)):
                value = number(feature.GetField(field)) if field else fallback
                if value < 0 or not math.isfinite(value*UNITS[unit]):
                    raise ValueError("ارتفاع باید نامنفی و متناهی باشد.")
                heights.append(value)
            rows.append(ObserverRecord((fid, lon, lat, start, end), name, *heights, not cfg.name_field))
        except (Cancelled, MemoryError, OSError):
            raise
        except Exception as exc:
            reject_record(skipped, log, fid, name, "input", exc, field)
    if not selected and cfg.observer_fid >= 0:
        reject_record(skipped, log, cfg.observer_fid, f"FID_{cfg.observer_fid}", "selection",
                      ValueError("FID انتخاب‌شده در فایل نقاط پیدا نشد."))
    return rows, sr


def load_observers(cfg):
    """Keep the original coordinate-only API for consumers and diagnostics."""
    records, sr = load_observer_records(cfg)
    return [record.row for record in records], sr


def filename_component(value, maximum_bytes):
    text = unicodedata.normalize("NFC", str(value))
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .") or "unnamed"
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)}
    if text.split(".")[0].upper() in reserved:
        text = "_"+text
    return text.encode("utf-8")[:maximum_bytes].decode("utf-8", errors="ignore").rstrip(" .") or "unnamed"


def separate_filenames(cfg, records):
    source = filename_component(Path(cfg.points).stem, 40)
    bases = [f"{source}-{filename_component(record.name, 90)}-{record.observer*UNITS[cfg.observer_unit]:.12g}" for record in records]
    counts = Counter(base.casefold() for base in bases)
    used, names = set(), []
    for record, base in zip(records, bases):
        stem = f"{base}-FID_{record.row[0]}" if counts[base.casefold()] > 1 else base
        candidate, suffix = stem, 1
        while candidate.casefold() in used:
            candidate = f"{stem}-{suffix}"
            suffix += 1
        used.add(candidate.casefold())
        names.append(candidate+".shp")
    return names


def sector_polygon(start, end, radius, cell):
    ranges = angle_ranges(start, end)
    sweep = sum(b-a for a, b in ranges)
    first = ranges[0][0]
    step = min(1.0, math.degrees(2*math.acos(max(-1, 1-min(radius, cell/4)/radius))))
    count = max(1, int(math.ceil(sweep/max(step, 1e-5))))
    ring = ogr.Geometry(ogr.wkbLinearRing)
    full = ranges == [(0.0, 360.0)]
    if not full:
        ring.AddPoint_2D(0, 0)
    for i in range(count+1):
        angle = math.radians(first+sweep*i/count)
        ring.AddPoint_2D(radius*math.sin(angle), radius*math.cos(angle))
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
    ds = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(str(path))
    layer = ds.CreateLayer(Path(path).stem, srs=sr, geom_type=ogr.wkbPolygon, options=["ENCODING=UTF-8"])
    for name, kind in fields:
        field = ogr.FieldDefn(name, kind)
        if kind == ogr.OFTString:
            field.SetWidth(254 if name == "name" else 32)
        if kind == ogr.OFTReal:
            field.SetWidth(24)
            field.SetPrecision(8)
        layer.CreateField(field)
    return ds, layer


def write_feature(layer, geometry, values, written=None):
    for polygon in polygon_parts(geometry):
        feature = ogr.Feature(layer.GetLayerDefn())
        for name, value in values.items():
            feature.SetField(name, value)
        feature.SetGeometry(polygon)
        if layer.CreateFeature(feature) != ogr.OGRERR_NONE:
            raise RuntimeError("نوشتن هندسه در شیپ‌فایل ناموفق بود.")
        if written is not None:
            written.append(feature.GetFID())


def raster_dataset(array, transform, projection, nodata=None):
    dtype = gdal.GDT_Byte if array.dtype == np.uint8 else gdal.GDT_Float32
    ds = gdal.GetDriverByName("MEM").Create("", array.shape[1], array.shape[0], 1, dtype)
    ds.SetGeoTransform(transform)
    ds.SetProjection(projection)
    ds.GetRasterBand(1).WriteArray(array)
    if nodata is not None:
        ds.GetRasterBand(1).SetNoDataValue(nodata)
    return ds


def viewshed(dataset, cfg, radius, observer_height, target_height, curvature, callback):
    return gdal.ViewshedGenerate(
        srcBand=dataset.GetRasterBand(1), driverName="MEM", targetRasterName="",
        creationOptions=[], observerX=0, observerY=0,
        observerHeight=observer_height, targetHeight=target_height,
        visibleVal=1, invisibleVal=0, outOfRangeVal=255, noDataVal=255,
        dfCurvCoeff=curvature, mode=gdal.GVM_Edge, maxDistance=radius,
        callback=callback, heightMode=gdal.GVOT_NORMAL, options=[])


def local_resolution(source, source_sr, local_sr, lon, lat):
    from_wgs = osr.CoordinateTransformation(spatial_ref("EPSG:4326"), source_sr)
    to_local = osr.CoordinateTransformation(source_sr, local_sr)
    x, y, _ = from_wgs.TransformPoint(lon, lat)
    gt = source.GetGeoTransform()
    a = to_local.TransformPoint(x, y)
    b = to_local.TransformPoint(x+gt[1], y+gt[4])
    c = to_local.TransformPoint(x+gt[2], y+gt[5])
    size = max(math.hypot(b[0]-a[0], b[1]-a[1]), math.hypot(c[0]-a[0], c[1]-a[1]))
    if not math.isfinite(size) or size <= 0:
        raise ValueError("اندازهٔ پیکسل DEM قابل تعیین نیست؛ مقدار متری را دستی وارد کنید.")
    return size


def grid_plan(radius, requested_cell, max_cells, auto_coarsen, fid, log):
    """Bound the actual odd, padded grid; never alter the requested radius."""
    def dimensions(cell):
        n = int(math.ceil(radius/cell))+3
        return n, 2*n+1

    n, size = dimensions(requested_cell)
    if size*size <= max_cells:
        return requested_cell, n, size
    maximum_side = math.isqrt(max_cells)
    if maximum_side % 2 == 0:
        maximum_side -= 1
    radius_pixels = (maximum_side-1)//2-3
    if radius_pixels < 2:
        raise ValueError("سقف شبکه برای تحلیل کافی نیست.")
    minimum_cell = math.nextafter(radius/radius_pixels, math.inf)
    if not auto_coarsen:
        multiplier = minimum_cell/requested_cell
        raise ValueError(
            f"FID={fid}: شبکهٔ درخواستی {size}×{size} ({size*size/1e6:.2f} میلیون سلول) "
            f"از سقف {max_cells/1e6:g} میلیون بیشتر است. "
            f"اندازهٔ پیکسل نهایی باید حداقل {math.ceil(minimum_cell*1e6)/1e6:.6f} متر "
            f"({multiplier:.3f} برابر مقدار فعلی) باشد؛ تنظیم خودکار پیکسل را روشن کنید "
            "یا سقف شبکه را با توجه به RAM افزایش دهید.")
    cell = minimum_cell
    n, adjusted_size = dimensions(cell)
    # Account for rounding at integer boundaries on all supported platforms.
    while adjusted_size*adjusted_size > max_cells:
        cell = math.nextafter(cell, math.inf)
        n, adjusted_size = dimensions(cell)
    log(f"نقطه {fid}: تنظیم خودکار برای سقف {max_cells/1e6:g} میلیون سلول؛ "
        f"پیکسل از {requested_cell:.6g} به {cell:.6g} متر افزایش یافت "
        f"(کاهش جزئیات مکانی)؛ شبکه {size}×{size} → {adjusted_size}×{adjusted_size}. "
        "شعاع و آزیموت تغییر نکردند.")
    return cell, n, adjusted_size


def local_result(source, source_sr, row, cfg, log, progress, cancelled):
    fid, lon, lat, start, end = row
    local_sr = spatial_ref(f"+proj=aeqd +lat_0={lat:.12f} +lon_0={lon:.12f} +datum=WGS84 +units=m +no_defs")
    cell = (cfg.cell_size or local_resolution(source, source_sr, local_sr, lon, lat))*cfg.resolution_factor
    radius = cfg.radius_m
    if radius < 2*cell:
        raise ValueError(f"FID={fid}: شعاع باید حداقل دو پیکسل باشد؛ اندازهٔ پیکسل {cell:g} متر است.")
    cell, n, size = grid_plan(radius, cell, cfg.max_grid_mcells*1_000_000,
                              cfg.auto_coarsen, fid, log)
    edge = (n+0.5)*cell
    log(f"نقطه {fid}: پیکسل {cell:.3f} m | شبکه {size}×{size}")

    def callback(a, b):
        def update(fraction, message, data):
            if cancelled():
                return 0
            progress(a+(b-a)*fraction)
            return 1
        return update

    if cancelled():
        raise Cancelled()
    warped = gdal.Warp("", source, format="MEM", dstSRS=local_sr.ExportToWkt(),
                       outputBounds=(-edge, -edge, edge, edge), width=size, height=size,
                       outputType=gdal.GDT_Float32, dstNodata=-3.4028234663852886e38,
                       resampleAlg="bilinear", errorThreshold=0, multithread=True,
                       warpOptions=["NUM_THREADS=2"], callback=callback(0, .25))
    band = warped.GetRasterBand(1)
    heights = band.ReadAsArray()
    valid = (band.GetMaskBand().ReadAsArray() != 0) & np.isfinite(heights)
    if not valid[n, n] and cfg.nodata_policy == "unknown":
        raise ValueError(f"FID={fid}: محل نقطه فاقد ارتفاع DEM است.")
    input_band = source.GetRasterBand(1)
    scale = input_band.GetScale()
    offset = input_band.GetOffset()
    # Work in place and release native rasters as soon as possible. Large grids
    # otherwise retain several full copies across both visibility passes.
    np.multiply(heights, 1 if scale is None else scale, out=heights)
    np.add(heights, 0 if offset is None else offset, out=heights)
    np.multiply(heights, UNITS[cfg.dem_z_unit], out=heights)
    heights[~valid] = 0
    low = float(np.min(heights)) if cfg.nodata_policy == "sea_level" else float(np.min(heights, where=valid, initial=np.inf))
    high = float(np.max(heights)) if cfg.nodata_policy == "sea_level" else float(np.max(heights, where=valid, initial=-np.inf))
    log(f"نقطه {fid}: ارتفاع زمین در محل ناظر {heights[n, n]:.3f} متر؛ "
        f"بازهٔ ارتفاع DEM در پنجره {low:.3f} تا {high:.3f} متر؛ "
        f"فرستنده در نقطه {cfg.observer*UNITS[cfg.observer_unit]:g} و گیرنده روی سلول‌ها "
        f"{cfg.receiver*UNITS[cfg.receiver_unit]:g} متر بالای زمین")
    log(f"نقطه {fid}: ارتفاع نهایی فرستنده = DEM + ارتفاع فرستنده = "
        f"{float(heights[n, n])+cfg.observer*UNITS[cfg.observer_unit]:.3f} متر")
    if cfg.nodata_policy == "sea_level" and not valid.all():
        log(f"نقطه {fid}: طبق انتخاب کاربر ارتفاع‌های ناموجود، دریا با ارتفاع صفر فرض شدند.")
    gt = warped.GetGeoTransform()
    projection = local_sr.ExportToWkt()
    band = warped = None
    terrain = raster_dataset(heights, gt, projection)
    del heights
    # AEQD preserves radial distances and true bearings from its central observer.
    maximum = radius+2*cell
    log(f"نقطه {fid}: محاسبهٔ دیدپذیری با موتور GDAL")
    result = viewshed(terrain, cfg, maximum, cfg.observer*UNITS[cfg.observer_unit],
                      cfg.receiver*UNITS[cfg.receiver_unit],
                      cfg.curvature_coefficient, callback(.25, .65))
    terrain = None
    classes = result.GetRasterBand(1).ReadAsArray()
    result_gt = result.GetGeoTransform()
    result = None
    # GDAL does not propagate DEM gaps. A separate opaque-gap pass marks
    # downstream cells conservatively as unknown rather than falsely visible.
    if cfg.nodata_policy == "unknown" and not valid.all():
        log(f"نقطه {fid}: بررسی مسیرهای عبوری از قسمت‌های فاقد DEM")
        gap_heights = np.zeros(valid.shape, dtype=np.float32)
        gap_heights[~valid] = 1e9
        gaps = raster_dataset(gap_heights, gt, projection)
        del gap_heights
        certainty = viewshed(gaps, cfg, maximum, 0, 0, 0, callback(.65, .8))
        gaps = None
        if certainty.GetGeoTransform() != result_gt or (certainty.RasterXSize, certainty.RasterYSize) != (classes.shape[1], classes.shape[0]):
            raise RuntimeError("شبکهٔ کنترل NoData با نتیجه هم‌تراز نیست.")
        clear = certainty.GetRasterBand(1).ReadAsArray() == 1
        certainty = None
        off_col = int(round((result_gt[0]-gt[0])/cell))
        off_row = int(round((gt[3]-result_gt[3])/cell))
        valid_view = valid[off_row:off_row+classes.shape[0], off_col:off_col+classes.shape[1]]
        classes[(~clear | ~valid_view) & (classes != 255)] = 2
    sector = sector_polygon(start, end, radius, cell)
    vector = ogr.GetDriverByName("Memory").CreateDataSource("")
    vector_layer = vector.CreateLayer("sector", srs=local_sr, geom_type=ogr.wkbPolygon)
    write_feature(vector_layer, sector, {})
    mask = raster_dataset(np.zeros(classes.shape, dtype=np.uint8), result_gt, projection)
    gdal.RasterizeLayer(mask, [1], vector_layer, burn_values=[1])
    classes[mask.GetRasterBand(1).ReadAsArray() == 0] = 255
    if not np.any(classes != 255):
        raise ValueError(f"FID={fid}: قطاع در این تفکیک هیچ سلولی ندارد؛ اندازهٔ پیکسل را کم یا بازهٔ آزیموت را بیشتر کنید.")
    progress(.85)
    if cancelled():
        raise Cancelled()
    return classes, result_gt, local_sr, sector, cell


def write_qml(path, visible_only=False):
    colors = {1: "190,30,45,210"} if visible_only else {0: "221,72,77,210", 1: "42,184,111,210", 2: "140,147,155,170"}
    symbols = "".join(f'<symbol name="{i}" type="fill"><layer class="SimpleFill"><Option type="Map"><Option name="color" value="{c}" type="QString"/><Option name="outline_style" value="no" type="QString"/></Option></layer></symbol>' for i, c in colors.items())
    categories = "".join(f'<category value="{i}" symbol="{i}" label="{CLASS_NAMES[i]}" render="true"/>' for i in colors)
    Path(path).with_suffix(".qml").write_text(f'<!DOCTYPE qgis><qgis version="3.40"><renderer-v2 type="categorizedSymbol" attr="status"><categories>{categories}</categories><symbols>{symbols}</symbols></renderer-v2></qgis>', encoding="utf-8")


def visible_radius(classes, gt):
    """Farthest visible cell centre, without allocating a full distance grid."""
    farthest = 0.0
    for r, row in enumerate(classes):
        columns = np.flatnonzero(row == 1)
        if columns.size:
            y = gt[3]+(r+.5)*gt[5]
            for c in (columns[0], columns[-1]):
                x = gt[0]+(int(c)+.5)*gt[1]
                farthest = max(farthest, math.hypot(x, y))
    return farthest


def prepare_record(source, source_sr, record, cfg, output_sr, log, progress, cancelled):
    """Prepare one point in memory; failed geometry never reaches shared SHPs."""
    started = time.perf_counter()
    fid, lon, lat, start, end = record.row
    point_cfg = replace(cfg, observer=record.observer, receiver=record.receiver)
    classes, gt, local_sr, sector, cell = local_result(
        source, source_sr, record.row, point_cfg, log, lambda f: progress(f*.85), cancelled)
    transform = osr.CoordinateTransformation(local_sr, output_sr)
    output_sector = sector.Clone()
    if output_sector.Transform(transform) != ogr.OGRERR_NONE:
        raise ValueError("تبدیل مختصات قطاع ناموفق بود.")
    if output_sr.IsGeographic():
        ring = output_sector.GetGeometryRef(0)
        if any(abs(ring.GetX(i)-ring.GetX(i-1)) > 180 for i in range(1, ring.GetPointCount())):
            raise ValueError("قطاع از مرز ۱۸۰ درجه می‌گذرد؛ EPSG تصویرشدهٔ مناسب برای خروجی انتخاب کنید.")
    values = dict(src_id=fid, name=record.name, az_start=start, az_end=end, radius_m=cfg.radius_m,
                  obs_m=point_cfg.observer*UNITS[cfg.observer_unit],
                  recv_m=point_cfg.receiver*UNITS[cfg.receiver_unit], cell_m=cell)
    raster = raster_dataset(classes, gt, local_sr.ExportToWkt(), 255)
    polygons = ogr.GetDriverByName("Memory").CreateDataSource("")
    layer = polygons.CreateLayer("classes", srs=output_sr, geom_type=ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("status", ogr.OFTInteger))
    log(f"نقطه {fid}: تبدیل نتیجه به پلی‌گون Shapefile")
    def polygon_progress(fraction, message, data):
        progress(.85+.15*fraction)
        return 0 if cancelled() else 1
    gdal.Polygonize(raster.GetRasterBand(1), raster.GetRasterBand(1).GetMaskBand(), layer, 0,
                    callback=polygon_progress)
    areas = {str(i): 0.0 for i in (0, 1, 2)}
    for feature in layer:
        if cancelled():
            raise Cancelled()
        status = feature.GetField("status")
        geometry = feature.GetGeometryRef().Intersection(sector)
        if geometry is None:
            raise ValueError("برش هندسهٔ رکورد ناموفق بود.")
        areas[str(status)] += geometry.GetArea()
        if geometry.Transform(transform) != ogr.OGRERR_NONE:
            raise ValueError("تبدیل مختصات نتیجهٔ رکورد ناموفق بود.")
        feature.SetGeometry(geometry)
        layer.SetFeature(feature)
    layer.ResetReading()
    counts = {str(i): int(np.count_nonzero(classes == i)) for i in (0, 1, 2)}
    summary = dict(src_id=fid, name=record.name, observer_at_point_m=values["obs_m"],
                   receiver_on_cells_m=values["recv_m"], cell_m=cell, grid_shape=list(classes.shape),
                   counts=counts, areas_m2=areas, max_visible_distance_m=visible_radius(classes, gt),
                   seconds=time.perf_counter()-started)
    return polygons, output_sector, values, summary, classes


def rollback_features(layer, ids):
    for fid in ids:
        if layer.DeleteFeature(fid) != ogr.OGRERR_NONE:
            raise RuntimeError("حذف خروجی ناقص رکورد ناموفق بود؛ خروجی قابل اعتماد نیست.")


def run_fast(cfg: FastSettings, log=print, progress=lambda fraction: None, cancelled=lambda: False, preview=lambda *args: None):
    cfg.validate()
    started = time.perf_counter()
    skipped = []
    rows, input_sr = load_observer_records(cfg, skipped, log, cancelled)
    output_sr = spatial_ref(f"EPSG:{cfg.output_epsg}") if cfg.output_epsg else input_sr
    if not Path(cfg.dem).is_file():
        raise ValueError("DEM باید فایل محلی موجود باشد؛ برنامه DEM را از اینترنت دریافت نمی‌کند.")
    source = gdal.OpenEx(cfg.dem, gdal.OF_RASTER | gdal.OF_READONLY,
                         allowed_drivers=["GTiff", "HFA", "AAIGrid", "USGSDEM", "SRTMHGT", "EHdr", "ENVI", "XYZ"])
    if source is None or source.RasterCount != 1:
        raise ValueError("DEM باید یک رستر ارتفاعی تک‌باند باشد.")
    if not source.GetProjection():
        raise ValueError("سیستم مختصات DEM مشخص نیست.")
    source_sr = spatial_ref(source.GetProjection())
    output = Path(cfg.output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    folder = output/("fast_viewshed_"+datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    folder.mkdir()
    detail_folder = folder/"details" if cfg.separate_outputs else folder
    detail_folder.mkdir(exist_ok=True)
    save_skipped_records(folder, skipped)
    point_filenames = separate_filenames(cfg, rows) if cfg.separate_outputs else ["visible.shp"]*len(rows)
    primary_outputs = []
    fields = [("src_id", ogr.OFTInteger64), ("name", ogr.OFTString), ("az_start", ogr.OFTReal), ("az_end", ogr.OFTReal),
              ("radius_m", ogr.OFTReal), ("obs_m", ogr.OFTReal), ("recv_m", ogr.OFTReal), ("cell_m", ogr.OFTReal)]
    class_fields = fields+[("status", ogr.OFTInteger), ("state", ogr.OFTString)]
    visibility_ds = visible_ds = sector_ds = None
    visibility_layer = visible_layer = sector_layer = None
    union_groups = {0: ogr.Geometry(ogr.wkbMultiPolygon), 1: ogr.Geometry(ogr.wkbMultiPolygon)}
    sector_union = ogr.Geometry(ogr.wkbMultiPolygon)
    summaries = []
    try:
        visibility_ds, visibility_layer = new_shape(detail_folder/"visibility.shp", output_sr, class_fields)
        if not cfg.separate_outputs:
            visible_ds, visible_layer = new_shape(folder/"visible.shp", output_sr, class_fields)
            primary_outputs.append("visible.shp")
        sector_ds, sector_layer = new_shape(detail_folder/"sectors.shp", output_sr, fields)
        for index, record in enumerate(rows):
            if cancelled():
                raise Cancelled()
            fid, lon, lat, start, end = record.row
            log(f"پردازش نقطه {index+1}/{len(rows)}، شناسه {fid}، نام {record.name!r}")
            polygons = classes = point_layer = None
            written_visible, written_visibility, written_sector = [], [], []
            try:
                polygons, output_sector, values, summary, classes = prepare_record(
                    source, source_sr, record, cfg, output_sr, log,
                    lambda f: progress((index+f)/len(rows)*.95), cancelled)
                if cfg.separate_outputs:
                    visible_ds, visible_layer = new_shape(folder/point_filenames[index], output_sr, class_fields)
                point_layer = polygons.GetLayer(0)
                write_feature(sector_layer, output_sector, values, written_sector)
                for feature in point_layer:
                    if cancelled():
                        raise Cancelled()
                    status = feature.GetField("status")
                    geometry = feature.GetGeometryRef()
                    attributes = {**values, "status": status, "state": CLASS_NAMES[status]}
                    write_feature(visibility_layer, geometry, attributes, written_visibility)
                    if status == 1:
                        write_feature(visible_layer, geometry, attributes, written_visible)
            except (Cancelled, MemoryError, OSError):
                raise
            except Exception as exc:
                if cancelled():
                    raise Cancelled() from exc
                # Roll back every appended polygon belonging to this point.
                rollback_features(sector_layer, written_sector)
                rollback_features(visibility_layer, written_visibility)
                if visible_layer is not None:
                    rollback_features(visible_layer, written_visible)
                if cfg.separate_outputs:
                    visible_layer = visible_ds = None
                    if (folder/point_filenames[index]).exists():
                        if ogr.GetDriverByName("ESRI Shapefile").DeleteDataSource(str(folder/point_filenames[index])) != ogr.OGRERR_NONE:
                            raise RuntimeError("حذف فایل ناقص رکورد ناموفق بود.") from exc
                reject_record(skipped, log, fid, record.name, "analysis", exc)
                progress((index+1)/len(rows)*.95)
                continue
            else:
                if cfg.merge_coverage:
                    sector_union.AddGeometry(output_sector)
                    point_layer.ResetReading()
                    for feature in point_layer:
                        status = feature.GetField("status")
                        if status in (0, 1):
                            for piece in polygon_parts(feature.GetGeometryRef()):
                                union_groups[status].AddGeometry(piece)
                summary["output"] = point_filenames[index]
                summaries.append(summary)
                if cfg.separate_outputs:
                    primary_outputs.append(point_filenames[index])
                counts = summary["counts"]
                total = sum(counts.values())
                log(f"نقطه {fid}: قابل‌دید {counts['1']/total:.1%} | پنهان {counts['0']/total:.1%} | نامعلوم {counts['2']/total:.1%}؛ خروجی: {point_filenames[index]}")
                log(f"نقطه {fid}: دورترین سلول قابل‌دید {summary['max_visible_distance_m']/1000:.3f} کیلومتر؛ حد تحلیل {cfg.radius_m/1000:g} کیلومتر")
                if not counts["1"]:
                    log(f"نقطه {fid}: هیچ سلول قابل‌دیدی پیدا نشد؛ فایل اصلی این نقطه خالی است.")
                preview(fid, classes.copy(), dict(cell=values["cell_m"], lon=lon, lat=lat, name=record.name))
                visibility_layer.SyncToDisk()
                visible_layer.SyncToDisk()
                sector_layer.SyncToDisk()
            finally:
                point_layer = polygons = classes = None
                if cfg.separate_outputs:
                    visible_layer = visible_ds = None
        if not primary_outputs:
            # A readable empty SHP is still delivered when every point is bad,
            # including separate-output mode and an empty input layer.
            visible_ds, visible_layer = new_shape(folder/"visible.shp", output_sr, class_fields)
            primary_outputs.append("visible.shp")
        visibility_layer = visible_layer = sector_layer = None
        visibility_ds = visible_ds = sector_ds = None
        if cfg.merge_coverage:
            log("ادغام پوشش‌ها؛ قابل رؤیت بودن از یک نقطه اولویت دارد…")
            visible = union_groups[1].UnionCascaded() if union_groups[1].GetGeometryCount() else ogr.Geometry(ogr.wkbMultiPolygon)
            hidden = union_groups[0].UnionCascaded() if union_groups[0].GetGeometryCount() else ogr.Geometry(ogr.wkbMultiPolygon)
            hidden = hidden.Difference(visible) if not visible.IsEmpty() else hidden
            known = visible.Union(hidden)
            unknown = sector_union.UnionCascaded().Difference(known) if sector_union.GetGeometryCount() else ogr.Geometry(ogr.wkbMultiPolygon)
            coverage_ds, coverage_layer = new_shape(folder/"coverage.shp", output_sr,
                                                    [("name", ogr.OFTString), ("status", ogr.OFTInteger), ("state", ogr.OFTString)])
            for status, geometry in ((0, hidden), (1, visible), (2, unknown)):
                if cancelled():
                    raise Cancelled()
                write_feature(coverage_layer, geometry, {"name": "coverage_"+CLASS_NAMES[status], "status": status, "state": CLASS_NAMES[status]})
            coverage_layer = coverage_ds = None
            write_qml(folder/"coverage.shp")
        write_qml(detail_folder/"visibility.shp")
        for filename in primary_outputs:
            write_qml(folder/filename, visible_only=True)
        save_skipped_records(folder, skipped)
        (folder/"README_RESULTS_FA.txt").write_text(
            "فایل‌های اصلی قابل‌دید:\n"+"\n".join(primary_outputs)+"\n"
            "این لایه فقط پلی‌گون‌های status=1 را دارد؛ نواحی پنهان و نامعلوم داخل آن نیستند.\n"
            "رکوردهای نامعتبر با FID، نام، ستون و علت در skipped_records.csv و skipped_records.json ثبت می‌شوند.\n"
            "اگر همهٔ رکوردها رد شده‌اند یا ورودی خالی است، visible.shp خالی ولی قابل باز کردن ساخته می‌شود.\n"
            "در حالت خروجی جدا، لایه‌های کمکی visibility و sectors داخل details هستند.\n"
            "ستون name نام انتخابی نقطه است؛ بدون انتخاب ستون نام، FID استفاده می‌شود.\n"
            "عدد پایانی فایل مستقل، ارتفاع فرستنده/آبجکت در محل نقطه بر حسب متر است.\n"
            "visibility.shp هر سه کلاس را دارد: 1=قابل‌دید، 0=پنهان، 2=نامعلوم؛ sectors.shp فقط مرز تحلیل است.\n"
            "برای مقایسه با Global Mapper، DEM، موقعیت، ارتفاع‌ها، واحدها، شعاع، آزیموت، پیکسل و انحنا باید یکسان باشند.\n"
            "run.json تنظیمات، رکوردهای موفق و ردشده و شمارش و مساحت کلاس‌ها را نگه می‌دارد.\n",
            encoding="utf-8")
        outcome = "no_valid_observers" if not summaries else "completed_with_skips" if skipped else "completed"
        report = dict(status="completed", outcome=outcome, application_version="3.2.1", offline=True,
                      selected_records=len(rows)+sum(r["stage"] == "input" for r in skipped),
                      succeeded_records=len(summaries), skipped_count=len(skipped), skipped_records=skipped,
                      skipped_report="skipped_records.csv", empty_output=not any(row["counts"]["1"] for row in summaries),
                      engine=gdal.VersionInfo("--version"), method="GDAL GVM_Edge / Wang",
                      settings=asdict(cfg), observers=summaries, seconds=time.perf_counter()-started,
                      output_crs=output_sr.ExportToWkt(), classes=CLASS_NAMES,
                      primary_output=primary_outputs[0] if not cfg.separate_outputs or not summaries else None,
                      primary_outputs=primary_outputs, output_mode="per_observer" if cfg.separate_outputs else "combined",
                      height_mapping={"observer_at_point_m": None if cfg.observer_field else cfg.observer*UNITS[cfg.observer_unit],
                                      "receiver_on_cells_m": None if cfg.receiver_field else cfg.receiver*UNITS[cfg.receiver_unit],
                                      "observer_field": cfg.observer_field, "receiver_field": cfg.receiver_field,
                                      "curvature_coefficient": cfg.curvature_coefficient},
                      outputs={**{name: "visible cells only (status=1)" for name in primary_outputs},
                               (detail_folder/"visibility.shp").relative_to(folder).as_posix(): "all classes; requires class symbology or filtering",
                               (detail_folder/"sectors.shp").relative_to(folder).as_posix(): "analysis bounds, not visibility"},
                      notes=["Per-observer AEQD grids preserve radial distances and true bearings.",
                             "Invalid records are logged and skipped; no invalid point is given fabricated coverage.",
                             "NoData policy: "+cfg.nodata_policy,
                             "Results are grid approximations; equivalence to Esri/Global Mapper is not established."])
        (folder/"run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        progress(1)
        log(f"پایان: {len(summaries)} رکورد موفق، {len(skipped)} رکورد ردشده؛ گزارش: skipped_records.csv\n{folder}")
        if not summaries:
            log("هشدار: هیچ رکوردی با موفقیت تحلیل نشد؛ visible.shp خالی ساخته شد. گزارش رکوردهای ردشده را بخوانید.")
        return str(folder)
    except Exception as exc:
        visibility_layer = visible_layer = sector_layer = None
        visibility_ds = visible_ds = sector_ds = None
        save_skipped_records(folder, skipped)
        (folder/"FAILED.txt").write_text(str(exc) or "Cancelled; outputs may be partial.", encoding="utf-8")
        if cancelled():
            raise Cancelled() from exc
        raise
