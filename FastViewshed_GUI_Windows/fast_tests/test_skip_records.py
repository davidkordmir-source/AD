"""Real SHP files retain good rows and report bad rows without partial data."""
import csv
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from osgeo import ogr
from fast_viewshed import engine
from fast_viewshed.model import FastSettings, Cancelled
import test_engine as fixtures


class SkipRecordsTests(unittest.TestCase):
    def setUp(self):
        self.data = fixtures.FastTerrainTests()
        self.data.setUp()
        self.points, self.dem = self.data.inputs(extra=[(500155, "80", "100")]*3)
        self.cfg = FastSettings(str(self.points), str(self.dem), "az_start", "az_end", str(self.data.root/"outputs"),
                                radius=700, radius_unit="m", cell_size=10, observer=100, receiver=2)

    def tearDown(self):
        self.data.tearDown()

    def edit(self, fid, field=None, value=None, geometry=False):
        ds = ogr.Open(str(self.points), 1)
        layer = ds.GetLayer(0)
        f = layer.GetFeature(fid)
        if geometry:
            f.SetGeometry(None)
        elif value is None:
            f.SetFieldNull(field)
        else:
            f.SetField(field, value)
        layer.SetFeature(f)
        f = layer = ds = None

    def run_case(self, **changes):
        logs=[]
        folder=Path(engine.run_fast(replace(self.cfg, **changes), log=logs.append))
        report=json.loads((folder/"run.json").read_text(encoding="utf-8"))
        self.assertFalse((folder/"FAILED.txt").exists())
        with (folder/"skipped_records.csv").open(encoding="utf-8-sig", newline="") as stream:
            csv_rows=list(csv.DictReader(stream))
        self.assertEqual(len(csv_rows), report["skipped_count"])
        self.assertEqual(json.loads((folder/"skipped_records.json").read_text()),report["skipped_records"])
        return folder,report,logs

    def ids(self, path):
        ds=ogr.Open(str(path))
        self.assertIsNotNone(ds)
        return {f.GetField("src_id") for f in ds.GetLayer(0)}

    def assert_empty_shp(self, path, required_field="src_id"):
        for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            self.assertTrue(path.with_suffix(suffix).is_file())
        ds=ogr.Open(str(path))
        self.assertEqual(ds.GetLayer(0).GetFeatureCount(),0)
        self.assertIsNotNone(ds.GetLayer(0).GetSpatialRef())
        self.assertIn(required_field,[f.GetName() for f in ds.GetLayer(0).schema])

    def test_null_bad_text_and_empty_geometry_skip_but_later_point_survives(self):
        self.edit(0,"az_start",None)
        self.edit(1,"az_end","garbage")
        self.edit(2,geometry=True)
        for separate in (False,True):
            with self.subTest(separate=separate):
                folder,r,logs=self.run_case(separate_outputs=separate)
                self.assertEqual(r["selected_records"],4)
                self.assertEqual(r["succeeded_records"],1)
                self.assertEqual(r["skipped_count"],3)
                self.assertEqual(r["outcome"],"completed_with_skips")
                for name in r["primary_outputs"]:
                    self.assertEqual(self.ids(folder/name),{3})
                for fid in range(3):
                    self.assertTrue(any(f"FID={fid}" in line for line in logs))

    def test_all_rejected_have_readable_empty_shp_in_both_modes(self):
        for fid in range(4):
            self.edit(fid,"az_start",None)
        for separate,merge in ((False,False),(True,False),(False,True)):
            with self.subTest(separate=separate,merge=merge):
                folder,r,logs=self.run_case(separate_outputs=separate,merge_coverage=merge)
                self.assert_empty_shp(folder/"visible.shp")
                self.assertEqual(r["primary_outputs"],["visible.shp"])
                self.assertEqual(r["succeeded_records"],0)
                self.assertEqual(r["skipped_count"],4)
                self.assertTrue(r["empty_output"])
                self.assertEqual(r["outcome"],"no_valid_observers")
                self.assertEqual(r["observers"],[])
                if merge:
                    self.assert_empty_shp(folder/"coverage.shp", "name")

    def test_empty_input_creates_empty_outputs_without_division_by_zero(self):
        ds=ogr.Open(str(self.points),1)
        layer=ds.GetLayer(0)
        for fid in range(4):
            layer.DeleteFeature(fid)
        layer=ds=None
        folder,r,_=self.run_case(separate_outputs=True)
        self.assert_empty_shp(folder/"visible.shp")
        self.assertEqual(r["selected_records"],0)
        self.assertEqual(r["skipped_count"],0)

    def test_missing_selected_column_is_reported_for_every_point(self):
        folder,r,_=self.run_case(observer_field="missing_height")
        self.assert_empty_shp(folder/"visible.shp")
        self.assertEqual([row["src_id"] for row in r["skipped_records"]],list(range(4)))
        self.assertTrue(all(row["field"]=="missing_height" for row in r["skipped_records"]))

    def test_dem_failure_at_one_point_does_not_stop_next_point(self):
        # Far outside the real local DEM: native warp produces missing ground.
        ds=ogr.Open(str(self.points),1)
        layer=ds.GetLayer(0);f=layer.GetFeature(1)
        p=ogr.Geometry(ogr.wkbPoint);p.AddPoint_2D(800000,3950505)
        f.SetGeometry(p);layer.SetFeature(f)
        f=layer=ds=None
        folder,r,_=self.run_case()
        self.assertEqual([row["src_id"] for row in r["observers"]],[0,2,3])
        self.assertEqual(self.ids(folder/"visible.shp"),{0,2,3})
        self.assertEqual(r["skipped_records"][0]["stage"],"analysis")

    def test_write_failure_rolls_back_all_layers_and_continues(self):
        original=engine.write_feature
        def fail_after_appending(layer, geometry, values, written=None):
            original(layer,geometry,values,written)
            if values.get("src_id")==1 and layer.GetName()=="visibility":
                raise RuntimeError("Injected failure after partial record write")
        for separate in (False,True):
            with self.subTest(separate=separate), patch.object(engine,"write_feature",side_effect=fail_after_appending):
                folder,r,_=self.run_case(separate_outputs=separate)
                self.assertEqual([row["src_id"] for row in r["observers"]],[0,2,3])
                self.assertEqual(r["skipped_count"],1)
                details=folder/"details" if separate else folder
                self.assertEqual(self.ids(details/"visibility.shp"),{0,2,3})
                self.assertEqual(self.ids(details/"sectors.shp"),{0,2,3})
                self.assertFalse((folder/"points-FID_1-100.shp").exists())
                for filename in r["primary_outputs"]:
                    self.assertNotIn(1,self.ids(folder/filename))

    def test_cancellation_during_processing_remains_cancellation(self):
        with patch.object(engine,"prepare_record",side_effect=Cancelled()):
            with self.assertRaises(Cancelled):
                engine.run_fast(self.cfg,log=lambda _:None)
        folder=next(Path(self.cfg.output_dir).glob("fast_viewshed_*"))
        self.assertFalse((folder/"run.json").exists())
        self.assertTrue((folder/"FAILED.txt").exists())
