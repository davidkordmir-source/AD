"""Real SHP output tests for attribute heights, names and independent files."""

from dataclasses import replace
import json
from pathlib import Path
import runpy
import unittest

from osgeo import gdal, ogr

from fast_viewshed.engine import run_fast
from fast_viewshed.model import FastSettings
import test_engine as fixtures


def add_attributes(points, rows, numeric=False):
    ds = ogr.Open(str(points), 1)
    layer = ds.GetLayer(0)
    for name in ("tx", "rx", "label"):
        kind = ogr.OFTReal if numeric and name != "label" else ogr.OFTString
        field = ogr.FieldDefn(name, kind)
        if kind == ogr.OFTString:
            field.SetWidth(254)
        layer.CreateField(field)
    for feature, values in zip(layer, rows):
        for field, value in zip(("tx", "rx", "label"), values):
            if value is None:
                feature.SetFieldNull(field)
            else:
                feature.SetField(field, value)
        layer.SetFeature(feature)
    layer = ds = None


class PerPointTests(unittest.TestCase):
    def setUp(self):
        self.data = fixtures.FastTerrainTests()
        self.data.setUp()
        self.points, self.dem = self.data.inputs(extra=[(500155, "80", "100")])
        add_attributes(self.points, [("۱۰۰", "۲", "North"), ("۲", "1e2", "South")])
        ds = gdal.Open(str(self.dem), gdal.GA_Update)
        heights = ds.GetRasterBand(1).ReadAsArray()
        heights[:, 35] = 150
        ds.GetRasterBand(1).WriteArray(heights)
        ds = None
        self.cfg = FastSettings(str(self.points), str(self.dem), "az_start", "az_end", str(self.data.root/"points_results"),
                                radius=700, radius_unit="m", cell_size=10, observer=999, receiver=888,
                                observer_field="tx", receiver_field="rx", name_field="label")

    def tearDown(self):
        self.data.tearDown()

    def run_case(self, **changes):
        folder = Path(run_fast(replace(self.cfg, **changes), log=lambda _: None))
        return folder, json.loads((folder/"run.json").read_text(encoding="utf-8"))

    def test_combined_output_uses_each_rows_heights_and_source_name(self):
        folder, report = self.run_case()
        self.assertEqual(report["primary_outputs"], ["visible.shp"])
        self.assertEqual(report["output_mode"], "combined")
        self.assertEqual(self.data.statuses(folder, 500755, 3950505, "visible"), [1])
        self.assertIsNone(report["height_mapping"]["observer_at_point_m"])
        self.assertEqual([r["observer_at_point_m"] for r in report["observers"]], [100, 2])
        self.assertEqual([r["receiver_on_cells_m"] for r in report["observers"]], [2, 100])
        ds = ogr.Open(str(folder/"sectors.shp"))
        values = [(f.GetField("src_id"), f.GetField("name"), f.GetField("obs_m"), f.GetField("recv_m")) for f in ds.GetLayer(0)]
        self.assertEqual(values, [(0, "North", 100, 2), (1, "South", 2, 100)])

    def test_separate_mode_creates_one_named_primary_shapefile_per_point(self):
        folder, report = self.run_case(separate_outputs=True)
        expected = ["points-North-100.shp", "points-South-2.shp"]
        self.assertEqual(report["primary_outputs"], expected)
        self.assertIsNone(report["primary_output"])
        self.assertEqual(sorted(p.name for p in folder.glob("*.shp")), sorted(expected))
        self.assertTrue((folder/"details/visibility.shp").exists())
        self.assertTrue((folder/"details/sectors.shp").exists())
        for i, name in enumerate(expected):
            for extension in (".shp", ".dbf", ".shx", ".prj", ".cpg", ".qml"):
                self.assertTrue((folder/name).with_suffix(extension).exists())
            ds = ogr.Open(str(folder/name))
            features = list(ds.GetLayer(0))
            self.assertTrue(features)
            self.assertEqual({f.GetField("src_id") for f in features}, {i})
            self.assertEqual({f.GetField("name") for f in features}, {("North", "South")[i]})

    def test_ten_points_produce_exactly_ten_primary_files(self):
        points, dem = self.data.inputs(extra=[(500155, "80", "100")]*9)
        add_attributes(points, [("100", "2", f"Site{i}") for i in range(10)])
        folder, report = self.run_case()
        # The same source is reused; the explicit mode change is the only
        # difference in output layout, with ten source records in both cases.
        self.assertEqual(len(report["observers"]), 10)
        separate, manifest = self.run_case(separate_outputs=True)
        self.assertEqual(len(manifest["primary_outputs"]), 10)
        self.assertEqual(len(list(separate.glob("*.shp"))), 10)
        self.assertTrue((folder/"visible.shp").exists())
        for i, filename in enumerate(manifest["primary_outputs"]):
            self.assertEqual(filename, f"points-Site{i}-100.shp")
            ds = ogr.Open(str(separate/filename))
            self.assertEqual({f.GetField("src_id") for f in ds.GetLayer(0)}, {i})

    def test_sanitized_duplicate_names_do_not_overwrite_each_other(self):
        ds = ogr.Open(str(self.points), 1)
        layer = ds.GetLayer(0)
        for i, label in enumerate(("A/B", "A\\B")):
            f = layer.GetFeature(i)
            f.SetField("label", label)
            f.SetField("tx", "100")
            layer.SetFeature(f)
        layer = ds = None
        folder, report = self.run_case(separate_outputs=True)
        self.assertEqual(report["primary_outputs"], ["points-A_B-100-FID_0.shp", "points-A_B-100-FID_1.shp"])
        for name in report["primary_outputs"]:
            self.assertTrue((folder/name).exists())
        ds = ogr.Open(str(folder/"details/sectors.shp"))
        self.assertEqual([f.GetField("name") for f in ds.GetLayer(0)], ["A/B", "A\\B"])

    def test_persian_names_survive_in_dbf_and_filenames(self):
        ds = ogr.Open(str(self.points), 1)
        layer = ds.GetLayer(0)
        names = ["ایستگاه شمال", "دکل"*35]
        for i, name in enumerate(names):
            f = layer.GetFeature(i)
            f.SetField("label", name)
            layer.SetFeature(f)
        layer = ds = None
        folder, report = self.run_case(separate_outputs=True)
        self.assertEqual(report["primary_outputs"][0], "points-ایستگاه شمال-100.shp")
        for i, filename in enumerate(report["primary_outputs"]):
            self.assertLessEqual(len(filename.encode("utf-8")), 255)
            ds = ogr.Open(str(folder/filename))
            self.assertEqual({f.GetField("name") for f in ds.GetLayer(0)}, {names[i]})

    def test_invalid_text_height_skips_only_bad_row_and_reports_fid_and_field(self):
        for bad in (None, "", "oops", "-1", "1e309"):
            with self.subTest(value=bad):
                ds = ogr.Open(str(self.points), 1)
                layer = ds.GetLayer(0)
                f = layer.GetFeature(1)
                f.SetFieldNull("rx") if bad is None else f.SetField("rx", bad)
                layer.SetFeature(f)
                f = layer = ds = None
                folder, report = self.run_case()
                self.assertEqual([r["src_id"] for r in report["observers"]], [0])
                self.assertEqual(report["skipped_count"], 1)
                self.assertEqual(report["skipped_records"][0]["src_id"], 1)
                self.assertEqual(report["skipped_records"][0]["field"], "rx")
                ds = ogr.Open(str(folder/"visibility.shp"))
                self.assertEqual({f.GetField("src_id") for f in ds.GetLayer(0)}, {0})

    def test_selected_fid_ignores_invalid_height_in_other_rows(self):
        ds = ogr.Open(str(self.points), 1)
        layer = ds.GetLayer(0)
        f = layer.GetFeature(1)
        f.SetField("tx", "bad")
        layer.SetFeature(f)
        f = layer = ds = None
        _, report = self.run_case(observer_fid=0)
        self.assertEqual(len(report["observers"]), 1)

    def test_field_heights_use_selected_units_and_filename_height_is_metres(self):
        _, report = self.run_case(observer_unit="ft", separate_outputs=True)
        self.assertEqual(report["primary_outputs"][0], "points-North-30.48.shp")
        self.assertAlmostEqual(report["observers"][0]["observer_at_point_m"], 30.48)

    def test_selected_blank_name_is_logged_and_skipped(self):
        ds = ogr.Open(str(self.points), 1)
        layer = ds.GetLayer(0)
        f = layer.GetFeature(0)
        f.SetFieldNull("label")
        layer.SetFeature(f)
        f = layer = ds = None
        _, report = self.run_case(separate_outputs=True)
        self.assertEqual(report["primary_outputs"], ["points-South-2.shp"])
        self.assertEqual(report["skipped_records"][0]["src_id"], 0)
        self.assertEqual(report["skipped_records"][0]["field"], "label")

    def test_numeric_height_columns_are_accepted(self):
        points, dem = self.data.inputs(extra=[(500155, "80", "100")])
        add_attributes(points, [(100, 2.5, "A"), (25, 3, "B")], numeric=True)
        _, report = self.run_case()
        self.assertEqual([r["receiver_on_cells_m"] for r in report["observers"]], [2.5, 3])

    def test_standalone_bundle_handles_named_independent_outputs(self):
        script = Path(__file__).resolve().parent.parent/"FastViewshed_GUI.py"
        app = runpy.run_path(str(script), run_name="per_point_bundle_test")
        cfg = app["FastSettings"](**{**self.cfg.__dict__, "separate_outputs": True})
        folder = Path(app["run_fast"](cfg, log=lambda _: None))
        report = json.loads((folder/"run.json").read_text(encoding="utf-8"))
        self.assertEqual(report["primary_outputs"], ["points-North-100.shp", "points-South-2.shp"])

    def test_merge_and_separate_modes_are_not_accidentally_combined(self):
        with self.assertRaisesRegex(ValueError, "ادغام"):
            replace(self.cfg, separate_outputs=True, merge_coverage=True).validate()
