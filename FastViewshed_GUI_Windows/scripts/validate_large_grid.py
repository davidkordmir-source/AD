"""Reproduce the reported 5725-square grid using the actual bundled program.

Creates a synthetic flat DEM and one observer, then checks both automatic
coarsening at 25 million cells and original-pixel processing at 40 million.
This is deliberately separate from the quick unit-test suite.
"""

import json
from pathlib import Path
import runpy
import time

from osgeo import gdal, ogr

ROOT = Path(__file__).resolve().parent.parent


def main():
    app = runpy.run_path(str(ROOT/"FastViewshed_GUI.py"), run_name="large_grid_validation")
    folder = ROOT/"fast-test-results"/"large_grid"
    folder.mkdir(parents=True, exist_ok=True)
    sr = app["spatial_ref"]("+proj=aeqd +lat_0=35 +lon_0=51 +datum=WGS84 +units=m +no_defs")
    dem = folder/"flat.tif"
    # The user reports a 100 km radius, 2 m receiver, 100 m target and a
    # 5725-square source grid. Use the matching synthetic configuration.
    size, radius = 5725, 100000
    cell = radius/2859
    ds = gdal.GetDriverByName("GTiff").Create(str(dem), size, size, 1, gdal.GDT_Float32,
                                               options=["TILED=YES", "COMPRESS=LZW"])
    edge = size*cell/2
    ds.SetGeoTransform((-edge, cell, 0, edge, 0, -cell))
    ds.SetProjection(sr.ExportToWkt())
    ds.GetRasterBand(1).Fill(100)
    ds = None
    points = folder/"observer.shp"
    driver = ogr.GetDriverByName("ESRI Shapefile")
    if points.exists():
        driver.DeleteDataSource(str(points))
    ds = driver.CreateDataSource(str(points))
    layer = ds.CreateLayer("observer", srs=sr, geom_type=ogr.wkbPoint)
    for name in ("az_start", "az_end"):
        layer.CreateField(ogr.FieldDefn(name, ogr.OFTReal))
    feature = ogr.Feature(layer.GetLayerDefn())
    point = ogr.Geometry(ogr.wkbPoint)
    point.AddPoint_2D(0, 0)
    feature.SetGeometry(point)
    feature.SetField("az_start", 30)
    feature.SetField("az_end", 150)
    layer.CreateFeature(feature)
    feature = layer = ds = None
    results = []
    for limit, automatic in ((25, True), (40, False)):
        config = app["FastSettings"](str(points), str(dem), "az_start", "az_end", str(folder/"results"),
                                      radius=radius, radius_unit="m", cell_size=cell,
                                      observer=100, receiver=2,
                                      max_grid_mcells=limit, auto_coarsen=automatic)
        started = time.perf_counter()
        output = Path(app["run_fast"](config, log=lambda text: print(text, flush=True)))
        report = json.loads((output/"run.json").read_text(encoding="utf-8"))
        assert report["status"] == "completed"
        observer = report["observers"][0]
        if automatic:
            assert cell < observer["cell_m"] < cell*1.15
        else:
            assert observer["cell_m"] == cell
        ds = ogr.Open(str(output/"sectors.shp"))
        layer = ds.GetLayer(0)
        assert layer.GetFeatureCount() == 1
        f = layer.GetNextFeature()
        assert f.GetField("radius_m") == radius
        f = layer = ds = None
        ds = ogr.Open(str(output/"visibility.shp"))
        assert ds.GetLayer(0).GetFeatureCount() > 0
        ds = None
        ds = ogr.Open(str(output/"visible.shp"))
        assert ds.GetLayer(0).GetFeatureCount() > 0
        assert all(f.GetField("status") == 1 for f in ds.GetLayer(0))
        ds = None
        results.append(dict(max_grid_mcells=limit, auto_coarsen=automatic,
                            actual_pixel_m=observer["cell_m"], radius_m=radius, observer_m=100, receiver_m=2,
                            counts=observer["counts"],
                            seconds=time.perf_counter()-started, status="completed"))
    (folder/"validation.json").write_text(json.dumps(dict(synthetic=True, requested_grid=[size, size],
        user_data_tested=False, cases=results), indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    main()
