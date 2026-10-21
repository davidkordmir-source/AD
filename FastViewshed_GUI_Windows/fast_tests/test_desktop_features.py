"""Native GIS naming plus GUI map, styling and wheel behavior."""
import json
from pathlib import Path
import unittest
from dataclasses import replace
from unittest.mock import patch

from osgeo import ogr
from PySide6 import QtCore, QtGui, QtWidgets, QtTest

from fast_viewshed.engine import run_fast, read_attribute_values
from fast_viewshed.model import FastSettings
from fast_viewshed.gui import FastWindow
import test_engine as fixtures


class DesktopFeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.data=fixtures.FastTerrainTests();self.data.setUp()
        self.points,self.dem=self.data.inputs(extra=[(500155,"80","100")])
        ds=ogr.Open(str(self.points),1);layer=ds.GetLayer(0)
        field=ogr.FieldDefn("site",ogr.OFTString);field.SetWidth(100);layer.CreateField(field)
        for f,text in zip(layer,["گروه شمال", "Group/B"]):
            f.SetField("site",text);layer.SetFeature(f)
        f=layer=ds=None
        self.cfg=FastSettings(str(self.points),str(self.dem),"az_start","az_end",str(self.data.root/"named"),radius=700,radius_unit="m",cell_size=10,combined_name_field="site",combined_name_value="گروه شمال")
        self.window=None

    def tearDown(self):
        if self.window is not None:self.window.close();self.qt.processEvents()
        self.data.tearDown()

    def test_chosen_attribute_value_names_one_shared_shp_with_both_observers(self):
        self.assertEqual(read_attribute_values(str(self.points),"site"),["گروه شمال","Group/B"])
        result=Path(run_fast(self.cfg,log=lambda _:None))
        r=json.loads((result/"run.json").read_text())
        self.assertEqual(r["primary_outputs"],["گروه شمال.shp"])
        self.assertFalse((result/"visible.shp").exists())
        ds=ogr.Open(str(result/r["primary_output"]))
        self.assertEqual({f.GetField("src_id") for f in ds.GetLayer(0)},{0,1})
        self.assertEqual([x["output"] for x in r["observers"]],["گروه شمال.shp"]*2)

    def test_selected_name_is_windows_safe_and_does_not_overwrite_auxiliary(self):
        result=Path(run_fast(replace(self.cfg,combined_name_value="Group/B"),log=lambda _:None))
        self.assertTrue((result/"Group_B.shp").is_file())
        ds=ogr.Open(str(self.points),1);layer=ds.GetLayer(0);f=layer.GetFeature(0)
        f.SetField("site","visibility");layer.SetFeature(f);f=layer=ds=None
        result=Path(run_fast(replace(self.cfg,combined_name_value="visibility"),log=lambda _:None))
        self.assertTrue((result/"visibility_visible.shp").exists())
        self.assertTrue((result/"visibility.shp").exists())

    def test_all_invalid_still_creates_the_chosen_shared_filename(self):
        ds=ogr.Open(str(self.points),1);layer=ds.GetLayer(0)
        for f in layer:f.SetFieldNull("az_start");layer.SetFeature(f)
        f=layer=ds=None
        result=Path(run_fast(self.cfg,log=lambda _:None))
        r=json.loads((result/"run.json").read_text());self.assertEqual(r["skipped_count"],2)
        ds=ogr.Open(str(result/"گروه شمال.shp"));self.assertEqual(ds.GetLayer(0).GetFeatureCount(),0)

    def test_gui_lists_values_map_and_three_highlighted_sections_offline(self):
        self.window=FastWindow();w=self.window
        w.show();self.qt.processEvents()
        w.inputs["points"].setText(str(self.points));w.load_fields()
        field=w.inputs["combined_name_field"];field.setCurrentIndex(field.findData("site"))
        value=w.inputs["combined_name_value"];self.assertEqual(value.count(),2)
        value.setCurrentIndex(value.findData("Group/B"))
        self.assertEqual(value.currentData(),"Group/B")
        self.assertGreaterEqual(w.map_view.boundary_count,200)
        self.assertEqual(len(w.map_view.observers),2)
        self.assertTrue(all(g.property("priority") for g in w.primary_groups))
        self.assertFalse(w.windowIcon().isNull())
        w.separate.setChecked(True);self.assertFalse(field.isEnabled());self.assertFalse(value.isEnabled())
        w.separate.setChecked(False);self.assertTrue(field.isEnabled())
        w.form_scroll.ensureWidgetVisible(w.primary_groups[-1]);self.qt.processEvents()
        root=Path(__file__).resolve().parent.parent/"fast-test-results"
        w.grab().save(str(root/"GUI_desktop_map.png"))

    def test_wheel_over_spin_scrolls_form_without_changing_radius(self):
        self.window=FastWindow();w=self.window;w.show();self.qt.processEvents()
        spin=w.inputs["radius"];w.form_scroll.ensureWidgetVisible(spin);self.qt.processEvents()
        value=spin.value();bar=w.form_scroll.verticalScrollBar();old=bar.value()
        position=spin.rect().center()
        event=QtGui.QWheelEvent(QtCore.QPointF(position),QtCore.QPointF(spin.mapToGlobal(position)),QtCore.QPoint(0,0),QtCore.QPoint(0,-120),QtCore.Qt.NoButton,QtCore.Qt.NoModifier,QtCore.Qt.NoScrollPhase,False)
        QtWidgets.QApplication.sendEvent(spin,event)
        QtTest.QTest.qWait(250)
        self.assertEqual(spin.value(),value)
        self.assertGreater(bar.value(),old)

    def test_map_preview_is_georeferenced_and_present_during_processing(self):
        self.window=FastWindow();w=self.window
        w.inputs["points"].setText(str(self.points));w.load_fields()
        self.assertGreater(w.map_view.boundary_count,200)
        previews=[]
        run_fast(self.cfg,log=lambda _:None,preview=lambda *args:previews.append(args))
        for fid,classes,metadata in previews:w.receive_preview(fid,classes,metadata)
        self.assertEqual(len(w.map_view.overlays),2)
        self.assertTrue(all(item.boundingRect().width()>0 for item in w.map_view.overlays.values()))
        w.preview_mode.setCurrentIndex(w.preview_mode.findData("classes"));self.qt.processEvents()
        self.assertFalse(w.map_view.visible_only)
