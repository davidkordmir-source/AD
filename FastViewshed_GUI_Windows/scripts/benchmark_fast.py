"""Reproducible five-observer benchmark; not an Esri speed comparison."""

import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from osgeo import gdal, ogr
from fast_viewshed.engine import run_fast, spatial_ref
from fast_viewshed.model import FastSettings


def main():
    folder = ROOT/"fast-test-results"/"benchmark"
    folder.mkdir(parents=True, exist_ok=True)
    sr = spatial_ref("EPSG:32639")
    dem = folder/"terrain.tif"
    size, cell = 2400, 10
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    heights = (200+60*np.sin(xx/170)*np.cos(yy/230)
               +250*np.exp(-((xx-1300)/40)**2)
               +80*np.exp(-((xx-800)**2+(yy-1200)**2)/(250**2))).astype(np.float32)
    ds = gdal.GetDriverByName("GTiff").Create(str(dem), size, size, 1, gdal.GDT_Float32,
                                               options=["TILED=YES", "COMPRESS=LZW"])
    ds.SetGeoTransform((500000, cell, 0, 3974000, 0, -cell))
    ds.SetProjection(sr.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(heights)
    ds = None
    points = folder/"observers.shp"
    if points.exists():
        ogr.GetDriverByName("ESRI Shapefile").DeleteDataSource(str(points))
    ds = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(str(points))
    layer = ds.CreateLayer("observers", srs=sr, geom_type=ogr.wkbPoint, options=["ENCODING=UTF-8"])
    for name in ("az_start", "az_end"):
        field = ogr.FieldDefn(name, ogr.OFTString)
        field.SetWidth(20)
        layer.CreateField(field)
    for index, x in enumerate((508000, 510000, 512000, 514000, 516000)):
        f = ogr.Feature(layer.GetLayerDefn())
        p = ogr.Geometry(ogr.wkbPoint)
        p.AddPoint_2D(x, 3962000)
        f.SetGeometry(p)
        f.SetField("az_start", str((index*45+350) % 360))
        f.SetField("az_end", str((index*45+70) % 360))
        layer.CreateFeature(f)
    layer = ds = None
    results = []
    for factor in (1, 2, 4):
        start = time.perf_counter()
        output = run_fast(FastSettings(str(points), str(dem), "az_start", "az_end", str(folder/"results"),
                                      radius=5, radius_unit="km", cell_size=10,
                                      resolution_factor=factor), log=lambda message: None)
        report = json.loads((Path(output)/"run.json").read_text(encoding="utf-8"))
        item = dict(resolution_factor=factor, pixel_m=10*factor, wall_seconds=time.perf_counter()-start,
                    engine_seconds=report["seconds"], observers=5, radius_m=5000,
                    computed_grid_cells=sum(p["grid_shape"][0]*p["grid_shape"][1] for p in report["observers"]))
        results.append(item)
        print(json.dumps(item), flush=True)
    final = dict(synthetic=True, dem_shape=[size, size], source_pixel_m=10,
                 includes="DEM warp, visibility, gap handling, polygonization and Shapefile writes",
                 comparison_to_arcgis="Not performed; user data/hardware were unavailable.",
                 gdal=gdal.VersionInfo("--version"), results=results)
    (folder/"benchmark.json").write_text(json.dumps(final, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
