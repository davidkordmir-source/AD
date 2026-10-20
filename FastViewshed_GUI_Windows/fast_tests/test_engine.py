"""Real GDAL analyses on synthetic terrain and real Shapefile round trips."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from osgeo import gdal, ogr

from fast_viewshed.engine import run_fast, spatial_ref
from fast_viewshed.model import FastSettings, Cancelled


class FastTerrainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fast_viewshed_test_")
        self.root = Path(self.temp.name)
        self.sr = spatial_ref("EPSG:32639")

    def tearDown(self):
        self.temp.cleanup()

    def inputs(self, ridge=False, gap=False, start="۸۰", end="۱۰۰", x=500155, extra=None, feet=False):
        dem = self.root/"dem.tif"
        ds = gdal.GetDriverByName("GTiff").Create(str(dem), 100, 100, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((500000, 10, 0, 3951000, 0, -10))
        ds.SetProjection(self.sr.ExportToWkt())
        values = np.full((100, 100), 100, dtype=np.float32)
        if ridge:
            values[:, 50] = 200
        if gap:
            values[:, 50:52] = -9999
        ds.GetRasterBand(1).SetNoDataValue(-9999)
        ds.GetRasterBand(1).WriteArray(values)
        ds = None
        points = self.root/"points.shp"
        ds = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(str(points))
        layer = ds.CreateLayer("points", srs=self.sr, geom_type=ogr.wkbPoint, options=["ENCODING=UTF-8"])
        for name in ("az_start", "az_end"):
            field = ogr.FieldDefn(name, ogr.OFTString)
            field.SetWidth(40)
            layer.CreateField(field)
        for px, a, b in [(x, start, end)]+(extra or []):
            f = ogr.Feature(layer.GetLayerDefn())
            p = ogr.Geometry(ogr.wkbPoint)
            p.AddPoint_2D(px, 3950505)
            f.SetGeometry(p)
            f.SetField("az_start", a)
            f.SetField("az_end", b)
            layer.CreateFeature(f)
        layer = ds = None
        return points, dem

    def run_case(self, inputs, **changes):
        points, dem = inputs
        kwargs = dict(points=str(points), dem=str(dem), start_field="az_start", end_field="az_end",
                      output_dir=str(self.root/"results"), radius=700, radius_unit="m", cell_size=10)
        kwargs.update(changes)
        folder = Path(run_fast(FastSettings(**kwargs), log=lambda message: None))
        report = json.loads((folder/"run.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "completed")
        for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            self.assertTrue((folder/("visibility"+suffix)).exists())
            self.assertTrue((folder/("visible"+suffix)).exists())
        self.assertEqual(report["primary_output"], "visible.shp")
        return folder, report

    def statuses(self, folder, x, y, name="visibility"):
        ds = ogr.Open(str(folder/(name+".shp")))
        point = ogr.Geometry(ogr.wkbPoint)
        point.AddPoint_2D(x, y)
        states = []
        for f in ds.GetLayer(0):
            geom = f.GetGeometryRef()
            if geom.Intersects(point):
                self.assertTrue(geom.IsValid())
                states.append(f.GetField("status"))
        return states

    def test_flat_ground_visible_and_outside_sector_absent(self):
        folder, report = self.run_case(self.inputs())
        self.assertEqual(self.statuses(folder, 500355, 3950505), [1])
        self.assertEqual(self.statuses(folder, 500755, 3950505), [1])
        self.assertEqual(self.statuses(folder, 500155, 3950805), [])
        self.assertGreater(report["observers"][0]["counts"]["1"], 0)

    def test_ridge_blocks_target(self):
        folder, _ = self.run_case(self.inputs(ridge=True))
        self.assertEqual(self.statuses(folder, 500355, 3950505), [1])
        self.assertEqual(self.statuses(folder, 500755, 3950505), [0])
        self.assertEqual(self.statuses(folder, 500355, 3950505, "visible"), [1])
        self.assertEqual(self.statuses(folder, 500755, 3950505, "visible"), [])

    def test_tall_target_visible_over_ridge(self):
        folder, _ = self.run_case(self.inputs(ridge=True), target=300)
        self.assertEqual(self.statuses(folder, 500755, 3950505), [1])

    def test_nodata_path_is_unknown_not_hidden_or_visible(self):
        folder, _ = self.run_case(self.inputs(gap=True))
        self.assertEqual(self.statuses(folder, 500355, 3950505), [1])
        self.assertEqual(self.statuses(folder, 500755, 3950505), [2])
        self.assertEqual(self.statuses(folder, 500755, 3950505, "visible"), [])

    def test_wrap_across_north(self):
        folder, _ = self.run_case(self.inputs(start="۳۵۰", end="۱۰", x=500505), radius=400)
        self.assertEqual(self.statuses(folder, 500505, 3950805), [1])
        self.assertEqual(self.statuses(folder, 500805, 3950505), [])

    def test_dem_vertical_feet_independent_of_xy_metres(self):
        folder, _ = self.run_case(self.inputs(ridge=True), dem_z_unit="ft", target=60)
        self.assertEqual(self.statuses(folder, 500755, 3950505), [1])

    def test_merged_visibility_wins_in_overlap(self):
        folder, report = self.run_case(self.inputs(ridge=True, extra=[(500855, "260", "280")]), merge_coverage=True)
        self.assertEqual(len(report["observers"]), 2)
        self.assertEqual(sorted(self.statuses(folder, 500755, 3950505)), [0, 1])
        self.assertEqual(self.statuses(folder, 500755, 3950505, "coverage"), [1])

    def test_full_circle_has_west_and_south_coverage(self):
        folder, _ = self.run_case(self.inputs(start="0", end="360", x=500505), radius=400)
        self.assertEqual(self.statuses(folder, 500205, 3950505), [1])
        self.assertEqual(self.statuses(folder, 500505, 3950205), [1])

    def test_raster_scale_and_offset_are_applied(self):
        points, dem = self.inputs(ridge=True)
        ds = gdal.Open(str(dem), gdal.GA_Update)
        ds.GetRasterBand(1).SetScale(.1)
        ds.GetRasterBand(1).SetOffset(200)
        ds = None
        folder, _ = self.run_case((points, dem), target=20)
        self.assertEqual(self.statuses(folder, 500755, 3950505), [1])

    def test_geographic_dem_and_observers_with_projected_output(self):
        points, dem = self.inputs()
        geo_dem = self.root/"geographic.tif"
        gdal.Warp(str(geo_dem), str(dem), dstSRS="EPSG:4326").FlushCache()
        geo_points = self.root/"geographic.shp"
        from osgeo import osr
        sr = spatial_ref("EPSG:4326")
        transform = osr.CoordinateTransformation(self.sr, sr)
        source = ogr.Open(str(points))
        ds = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(str(geo_points))
        layer = ds.CreateLayer("geographic", srs=sr, geom_type=ogr.wkbPoint, options=["ENCODING=UTF-8"])
        for name in ("az_start", "az_end"):
            layer.CreateField(ogr.FieldDefn(name, ogr.OFTString))
        for f in source.GetLayer(0):
            geometry = f.GetGeometryRef().Clone()
            geometry.Transform(transform)
            out = ogr.Feature(layer.GetLayerDefn())
            out.SetGeometry(geometry)
            out.SetField("az_start", "80")
            out.SetField("az_end", "100")
            layer.CreateFeature(out)
        layer = ds = source = None
        folder, _ = self.run_case((geo_points, geo_dem), output_epsg=32639)
        self.assertEqual(self.statuses(folder, 500355, 3950505), [1])

    def test_bad_text_reports_feature_id_and_no_result(self):
        points, dem = self.inputs(start="bad")
        with self.assertRaisesRegex(ValueError, "FID=0"):
            run_fast(FastSettings(str(points), str(dem), "az_start", "az_end", str(self.root/"results")))
        self.assertFalse((self.root/"results").exists())

    def test_unsampled_thin_sector_does_not_report_empty_output_as_success(self):
        points, dem = self.inputs(start="45.123456", end="45.123457")
        with self.assertRaisesRegex(ValueError, "هیچ سلولی"):
            run_fast(FastSettings(str(points), str(dem), "az_start", "az_end", str(self.root/"results"),
                                  radius=700, radius_unit="m", cell_size=10), log=lambda message: None)
        result = next((self.root/"results").glob("fast_viewshed_*"))
        self.assertFalse((result/"run.json").exists())

    def test_cancelled_analysis_does_not_claim_completion(self):
        points, dem = self.inputs()
        with self.assertRaises(Cancelled):
            run_fast(FastSettings(str(points), str(dem), "az_start", "az_end", str(self.root/"results")), cancelled=lambda: True)
        folders = list((self.root/"results").glob("fast_viewshed_*"))
        self.assertTrue((folders[0]/"FAILED.txt").exists())
        self.assertFalse((folders[0]/"run.json").exists())

    def test_oversized_grid_auto_adjusts_and_writes_actual_pixel_size(self):
        folder, report = self.run_case(self.inputs(), cell_size=1, max_grid_mcells=1)
        actual_cell = report["observers"][0]["cell_m"]
        self.assertGreater(actual_cell, 1)
        self.assertLess(actual_cell, 2)
        self.assertEqual(report["settings"]["cell_size"], 1)
        self.assertTrue(report["settings"]["auto_coarsen"])
        self.assertEqual(self.statuses(folder, 500355, 3950505), [1])
        ds = ogr.Open(str(folder/"sectors.shp"))
        f = ds.GetLayer(0).GetNextFeature()
        self.assertAlmostEqual(f.GetField("radius_m"), 700)
        self.assertAlmostEqual(f.GetField("cell_m"), actual_cell, places=7)

    def test_large_grid_preserves_requested_pixel_when_auto_is_off(self):
        folder, report = self.run_case(self.inputs(), cell_size=1, max_grid_mcells=2, auto_coarsen=False)
        self.assertEqual(report["observers"][0]["cell_m"], 1)
        self.assertEqual(self.statuses(folder, 500355, 3950505), [1])

    def test_visible_shapefile_matches_only_visible_class_not_whole_sector(self):
        folder, report = self.run_case(self.inputs(ridge=True))
        visible_ds = ogr.Open(str(folder/"visible.shp"))
        all_ds = ogr.Open(str(folder/"visibility.shp"))
        visible_layer = visible_ds.GetLayer(0)
        self.assertGreater(visible_layer.GetFeatureCount(), 0)
        for f in visible_layer:
            self.assertEqual(f.GetField("status"), 1)
            self.assertEqual(f.GetField("state"), "visible")
            self.assertEqual(f.GetField("src_id"), 0)
        def combined(layer, status):
            geometry = ogr.Geometry(ogr.wkbMultiPolygon)
            layer.ResetReading()
            for f in layer:
                if f.GetField("status") == status:
                    geometry.AddGeometry(f.GetGeometryRef())
            return geometry.UnionCascaded()
        actual = combined(visible_layer, 1)
        expected = combined(all_ds.GetLayer(0), 1)
        hidden = combined(all_ds.GetLayer(0), 0)
        self.assertAlmostEqual(actual.SymmetricDifference(expected).GetArea(), 0, places=6)
        self.assertAlmostEqual(actual.Intersection(hidden).GetArea(), 0, places=6)
        self.assertGreater(hidden.GetArea(), 0)
        self.assertGreater(report["observers"][0]["areas_m2"]["0"], 0)
        self.assertTrue((folder/"README_RESULTS_FA.txt").exists())
        self.assertIn('value="1"', (folder/"visible.qml").read_text())

    def test_visible_output_retains_per_observer_identifiers_in_overlap(self):
        folder, _ = self.run_case(self.inputs(ridge=True, extra=[(500855, "260", "280")]))
        ds = ogr.Open(str(folder/"visible.shp"))
        point = ogr.Geometry(ogr.wkbPoint)
        point.AddPoint_2D(500755, 3950505)
        ids = [f.GetField("src_id") for f in ds.GetLayer(0) if f.GetGeometryRef().Intersects(point)]
        self.assertEqual(ids, [1])


if __name__ == "__main__":
    unittest.main()
