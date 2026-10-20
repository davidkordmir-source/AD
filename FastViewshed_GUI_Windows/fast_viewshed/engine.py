"""Compiled GDAL viewshed on local equidistant grids, exported as Shapefiles."""

from dataclasses import asdict
from datetime import datetime
import json
import math
from pathlib import Path
import time

import numpy as np
from osgeo import gdal, ogr, osr

from .model import FastSettings, Cancelled, azimuth, angle_ranges, UNITS


gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()

MAX_GRID_CELLS = 25_000_000
CLASS_NAMES = {0: "hidden", 1: "visible", 2: "unknown"}


def spatial_ref(definition):
    sr = osr.SpatialReference()
    sr.SetFromUserInput(str(definition))
    sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return sr


def inspect_shape(path):
    ds = ogr.Open(str(path), 0)
    if ds is None:
        raise ValueError("شیپ‌فایل باز نشد؛ فایل‌های SHP، SHX و DBF را بررسی کنید.")
    layer = ds.GetLayer(0)
    if ogr.GT_Flatten(layer.GetGeomType()) != ogr.wkbPoint:
        raise ValueError("ورودی باید شیپ‌فایل نقطه‌ای از نوع Point باشد.")
    sr = layer.GetSpatialRef()
    if sr is None:
        raise ValueError("شیپ‌فایل سیستم مختصات ندارد؛ فایل PRJ لازم است.")
    allowed = {ogr.OFTInteger, ogr.OFTInteger64, ogr.OFTReal, ogr.OFTString}
    definition = layer.GetLayerDefn()
    fields = [definition.GetFieldDefn(i).GetName() for i in range(definition.GetFieldCount())
              if definition.GetFieldDefn(i).GetType() in allowed]
    return {"fields": fields, "count": layer.GetFeatureCount(), "crs": sr.GetName()}


def load_observers(cfg):
    metadata = inspect_shape(cfg.points)
    if cfg.start_field not in metadata["fields"] or cfg.end_field not in metadata["fields"]:
        raise ValueError("فیلدهای آزیموت را دوباره انتخاب کنید.")
    ds = ogr.Open(cfg.points, 0)
    layer = ds.GetLayer(0)
    sr = layer.GetSpatialRef().Clone()
    sr.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    to_wgs = osr.CoordinateTransformation(sr, spatial_ref("EPSG:4326"))
    rows, errors = [], []
    for feature in layer:
        fid = feature.GetFID()
        try:
            geometry = feature.GetGeometryRef()
            if geometry is None or geometry.IsEmpty():
                raise ValueError("هندسهٔ خالی")
            lon, lat, _ = to_wgs.TransformPoint(geometry.GetX(), geometry.GetY())
            if not (math.isfinite(lon) and math.isfinite(lat) and -90 < lat < 90):
                raise ValueError("مختصات جغرافیایی نامعتبر")
            start = azimuth(feature.GetField(cfg.start_field))
            end = azimuth(feature.GetField(cfg.end_field))
            rows.append((fid, lon, lat, start, end))
        except (ValueError, RuntimeError) as exc:
            errors.append(f"FID={fid}: {exc}")
    if errors:
        raise ValueError("ردیف نامعتبر؛ هیچ ردیفی حذف نشد:\n"+"\n".join(errors[:30]))
    if not rows:
        raise ValueError("شیپ‌فایل خالی است.")
    return rows, sr


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
            field.SetWidth(32)
        if kind == ogr.OFTReal:
            field.SetWidth(24)
            field.SetPrecision(8)
        layer.CreateField(field)
    return ds, layer


def write_feature(layer, geometry, values):
    for polygon in polygon_parts(geometry):
        feature = ogr.Feature(layer.GetLayerDefn())
        for name, value in values.items():
            feature.SetField(name, value)
        feature.SetGeometry(polygon)
        layer.CreateFeature(feature)


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


def local_result(source, source_sr, row, cfg, log, progress, cancelled):
    fid, lon, lat, start, end = row
    local_sr = spatial_ref(f"+proj=aeqd +lat_0={lat:.12f} +lon_0={lon:.12f} +datum=WGS84 +units=m +no_defs")
    cell = (cfg.cell_size or local_resolution(source, source_sr, local_sr, lon, lat))*cfg.resolution_factor
    radius = cfg.radius_m
    if radius < 2*cell:
        raise ValueError(f"FID={fid}: شعاع باید حداقل دو پیکسل باشد؛ اندازهٔ پیکسل {cell:g} متر است.")
    n = int(math.ceil(radius/cell))+3
    size = 2*n+1
    if size*size > MAX_GRID_CELLS:
        raise ValueError(f"FID={fid}: شبکه {size}×{size} بیش از حد بزرگ است؛ شعاع را کم یا اندازهٔ پیکسل را بیشتر کنید.")
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
    if not valid[n, n]:
        raise ValueError(f"FID={fid}: محل نقطه فاقد ارتفاع DEM است.")
    input_band = source.GetRasterBand(1)
    scale = input_band.GetScale()
    offset = input_band.GetOffset()
    heights[valid] = ((heights[valid]*(1 if scale is None else scale)
                      +(0 if offset is None else offset))*UNITS[cfg.dem_z_unit])
    heights[~valid] = 0
    gt = warped.GetGeoTransform()
    projection = local_sr.ExportToWkt()
    terrain = raster_dataset(heights, gt, projection)
    # AEQD preserves radial distances and true bearings from its central observer.
    maximum = radius+2*cell
    log(f"نقطه {fid}: محاسبهٔ دیدپذیری با موتور GDAL")
    result = viewshed(terrain, cfg, maximum, cfg.receiver*UNITS[cfg.receiver_unit],
                      cfg.target*UNITS[cfg.target_unit], 1-cfg.refraction, callback(.25, .65))
    classes = result.GetRasterBand(1).ReadAsArray().astype(np.uint8)
    result_gt = result.GetGeoTransform()
    # GDAL does not propagate DEM gaps. A separate opaque-gap pass marks
    # downstream cells conservatively as unknown rather than falsely visible.
    if not valid.all():
        log(f"نقطه {fid}: بررسی مسیرهای عبوری از قسمت‌های فاقد DEM")
        gaps = raster_dataset(np.where(valid, 0.0, 1e9).astype(np.float32), gt, projection)
        certainty = viewshed(gaps, cfg, maximum, 0, 0, 0, callback(.65, .8))
        if certainty.GetGeoTransform() != result_gt or (certainty.RasterXSize, certainty.RasterYSize) != (result.RasterXSize, result.RasterYSize):
            raise RuntimeError("شبکهٔ کنترل NoData با نتیجه هم‌تراز نیست.")
        clear = certainty.GetRasterBand(1).ReadAsArray() == 1
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


def write_qml(path):
    colors = {0: "221,72,77,210", 1: "42,184,111,210", 2: "140,147,155,170"}
    symbols = "".join(f'<symbol name="{i}" type="fill"><layer class="SimpleFill"><Option type="Map"><Option name="color" value="{c}" type="QString"/><Option name="outline_style" value="no" type="QString"/></Option></layer></symbol>' for i, c in colors.items())
    categories = "".join(f'<category value="{i}" symbol="{i}" label="{CLASS_NAMES[i]}" render="true"/>' for i in colors)
    Path(path).with_suffix(".qml").write_text(f'<!DOCTYPE qgis><qgis version="3.40"><renderer-v2 type="categorizedSymbol" attr="status"><categories>{categories}</categories><symbols>{symbols}</symbols></renderer-v2></qgis>', encoding="utf-8")


def run_fast(cfg: FastSettings, log=print, progress=lambda fraction: None, cancelled=lambda: False, preview=lambda *args: None):
    cfg.validate()
    started = time.perf_counter()
    rows, input_sr = load_observers(cfg)
    output_sr = spatial_ref(f"EPSG:{cfg.output_epsg}") if cfg.output_epsg else input_sr
    source = gdal.OpenEx(cfg.dem, gdal.OF_RASTER | gdal.OF_READONLY)
    if source is None or source.RasterCount != 1:
        raise ValueError("DEM باید یک رستر ارتفاعی تک‌باند باشد.")
    if not source.GetProjection():
        raise ValueError("سیستم مختصات DEM مشخص نیست.")
    source_sr = spatial_ref(source.GetProjection())
    output = Path(cfg.output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    folder = output/("fast_viewshed_"+datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    folder.mkdir()
    fields = [("src_id", ogr.OFTInteger64), ("az_start", ogr.OFTReal), ("az_end", ogr.OFTReal),
              ("radius_m", ogr.OFTReal), ("recv_m", ogr.OFTReal), ("target_m", ogr.OFTReal), ("cell_m", ogr.OFTReal)]
    visibility_ds = sector_ds = None
    union_groups = {0: ogr.Geometry(ogr.wkbMultiPolygon), 1: ogr.Geometry(ogr.wkbMultiPolygon)}
    sector_union = ogr.Geometry(ogr.wkbMultiPolygon)
    summaries = []
    try:
        visibility_ds, visibility_layer = new_shape(folder/"visibility.shp", output_sr,
                                                   fields+[("status", ogr.OFTInteger), ("state", ogr.OFTString)])
        sector_ds, sector_layer = new_shape(folder/"sectors.shp", output_sr, fields)
        for index, row in enumerate(rows):
            if cancelled():
                raise Cancelled()
            fid, lon, lat, start, end = row
            log(f"پردازش نقطه {index+1}/{len(rows)}، شناسه {fid}")
            local_start = time.perf_counter()
            classes, gt, local_sr, sector, cell = local_result(
                source, source_sr, row, cfg, log,
                lambda f: progress((index+f)/len(rows)*.95), cancelled)
            transform = osr.CoordinateTransformation(local_sr, output_sr)
            output_sector = sector.Clone()
            output_sector.Transform(transform)
            if output_sr.IsGeographic():
                ring = output_sector.GetGeometryRef(0)
                if any(abs(ring.GetX(i)-ring.GetX(i-1)) > 180 for i in range(1, ring.GetPointCount())):
                    raise ValueError("قطاع از مرز ۱۸۰ درجه می‌گذرد؛ یک EPSG تصویرشدهٔ مناسب برای خروجی انتخاب کنید.")
            values = dict(src_id=fid, az_start=start, az_end=end, radius_m=cfg.radius_m,
                          recv_m=cfg.receiver*UNITS[cfg.receiver_unit], target_m=cfg.target*UNITS[cfg.target_unit], cell_m=cell)
            write_feature(sector_layer, output_sector, values)
            if cfg.merge_coverage:
                sector_union.AddGeometry(output_sector)
            raster = raster_dataset(classes, gt, local_sr.ExportToWkt(), 255)
            polygons = ogr.GetDriverByName("Memory").CreateDataSource("")
            layer = polygons.CreateLayer("classes", srs=local_sr, geom_type=ogr.wkbPolygon)
            layer.CreateField(ogr.FieldDefn("status", ogr.OFTInteger))
            log(f"نقطه {fid}: تبدیل نتیجه به پلی‌گون Shapefile")
            def polygon_progress(fraction, message, data):
                progress((index+.85+.15*fraction)/len(rows)*.95)
                return 0 if cancelled() else 1
            gdal.Polygonize(raster.GetRasterBand(1), raster.GetRasterBand(1).GetMaskBand(), layer, 0,
                            callback=polygon_progress)
            for feature in layer:
                status = feature.GetField("status")
                geometry = feature.GetGeometryRef().Intersection(sector)
                geometry.Transform(transform)
                write_feature(visibility_layer, geometry, {**values, "status": status, "state": CLASS_NAMES[status]})
                if cfg.merge_coverage and status in (0, 1):
                    for piece in polygon_parts(geometry):
                        union_groups[status].AddGeometry(piece)
            preview(fid, classes.copy(), dict(cell=cell, lon=lon, lat=lat))
            counts = {str(i): int(np.count_nonzero(classes == i)) for i in (0, 1, 2)}
            summaries.append(dict(src_id=fid, cell_m=cell, grid_shape=list(classes.shape), counts=counts,
                                  seconds=time.perf_counter()-local_start))
            visibility_layer.SyncToDisk()
            sector_layer.SyncToDisk()
        visibility_layer = sector_layer = None
        visibility_ds = sector_ds = None
        if cfg.merge_coverage:
            log("ادغام پوشش‌ها؛ قابل رؤیت بودن از یک نقطه اولویت دارد…")
            visible = union_groups[1].UnionCascaded() if union_groups[1].GetGeometryCount() else ogr.Geometry(ogr.wkbMultiPolygon)
            hidden = union_groups[0].UnionCascaded() if union_groups[0].GetGeometryCount() else ogr.Geometry(ogr.wkbMultiPolygon)
            hidden = hidden.Difference(visible) if not visible.IsEmpty() else hidden
            known = visible.Union(hidden)
            unknown = sector_union.UnionCascaded().Difference(known)
            coverage_ds, coverage_layer = new_shape(folder/"coverage.shp", output_sr,
                                                    [("status", ogr.OFTInteger), ("state", ogr.OFTString)])
            for status, geometry in ((0, hidden), (1, visible), (2, unknown)):
                if cancelled():
                    raise Cancelled()
                write_feature(coverage_layer, geometry, {"status": status, "state": CLASS_NAMES[status]})
            coverage_layer = coverage_ds = None
            write_qml(folder/"coverage.shp")
        write_qml(folder/"visibility.shp")
        report = dict(status="completed", engine=gdal.VersionInfo("--version"), method="GDAL GVM_Edge / Wang",
                      settings=asdict(cfg), observers=summaries, seconds=time.perf_counter()-started,
                      output_crs=output_sr.ExportToWkt(), classes=CLASS_NAMES,
                      notes=["Per-observer AEQD grids preserve radial distances and true bearings.",
                             "NoData paths are conservatively marked unknown using an opaque-gap pass.",
                             "Results are grid approximations; equivalence to Esri/Global Mapper is not established."])
        (folder/"run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        progress(1)
        log(f"پایان: {report['seconds']:.2f} ثانیه | {folder}")
        return str(folder)
    except Exception as exc:
        visibility_layer = sector_layer = None
        visibility_ds = sector_ds = None
        (folder/"FAILED.txt").write_text(str(exc) or "Cancelled; outputs may be partial.", encoding="utf-8")
        if cancelled():
            raise Cancelled() from exc
        raise
