"""Exercise shipped controls, real radius validation and bounded large grids."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import runpy
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'FastViewshed_GUI_Windows'
sys.path.insert(0, str(ROOT))
from PySide6 import QtCore, QtWidgets
from fast_viewshed.model import FastSettings
from fast_viewshed.engine import grid_plan
from osgeo import gdal, ogr, osr
from desktop_customization import Preferences

APP = runpy.run_path(str(ROOT / 'FastViewshed_GUI.py'), run_name='numeric_regression')


class RadiusNumericTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_shipped_controls_show_compact_unambiguous_numbers_and_keep_fractions(self):
        with tempfile.TemporaryDirectory() as folder:
            previous = QtCore.QLocale()
            QtCore.QLocale.setDefault(QtCore.QLocale('fa_IR'))
            window = None
            try:
                window = APP['FastWindow'](Preferences(Path(folder)/'profile', Path(folder)/'branding'))
                radius = window.inputs['radius']
                self.assertEqual(radius.text(), '5')
                self.assertEqual(window.unit_boxes['radius_unit'].currentData(), 'km')
                self.assertEqual(window.inputs['observer'].text(), '100')
                for value, expected in [(5000, '5000'), (5.25, '5.25'), (0.125, '0.125')]:
                    radius.setValue(value)
                    self.assertEqual(radius.text(), expected)
                    self.assertEqual(radius.value(), value)
                radius.lineEdit().setText('12.5')
                radius.interpretText()
                self.assertEqual(radius.value(), 12.5)
                for unit, factor in [('km', 1000), ('m', 1), ('ft', 0.3048), ('mi', 1609.344)]:
                    combo = window.unit_boxes['radius_unit']
                    combo.setCurrentIndex(combo.findData(unit))
                    self.assertLessEqual(radius.maximum() * factor, 5000000)
                    self.assertGreater(radius.maximum() * factor, 4999999)
                atmosphere = window.inputs['atmospheric_factor']
                atmosphere.setValue(1.33333)
                self.assertEqual(atmosphere.text(), '1.33333')
            finally:
                if window is not None:
                    window.close()
                QtCore.QLocale.setDefault(previous)

    def test_new_radius_boundary_is_consistent_in_library_and_shipped_engine(self):
        for model in [FastSettings, APP['FastSettings']]:
            for radius in [300, 301, 5000]:
                config = model('p','d','s','e','o', radius=radius, radius_unit='km')
                config.validate()
                self.assertEqual(config.radius_m, radius * 1000)
            for radius in [0, 5000.001]:
                with self.assertRaises(ValueError):
                    model('p','d','s','e','o',radius=radius).validate()

    def test_5000_km_grid_preserves_radius_and_respects_memory_budget(self):
        for planner in [grid_plan, APP['grid_plan']]:
            cell, n, side = planner(5000000, 10, 1000000, True, 0, lambda _: None)
            self.assertLessEqual(side * side, 1000000)
            self.assertGreaterEqual((n - 3) * cell, 5000000)
            with self.assertRaises(ValueError):
                planner(5000000, 10, 1000000, False, 0, lambda _: None)

    def test_shipped_engine_runs_a_real_5000_km_analysis_on_coarse_world_dem(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            sr = osr.SpatialReference()
            sr.ImportFromEPSG(4326)
            dem = gdal.GetDriverByName('GTiff').Create(str(folder/'world.tif'), 720, 360, 1, gdal.GDT_Int16)
            dem.SetProjection(sr.ExportToWkt())
            dem.SetGeoTransform((-180, 0.5, 0, 90, 0, -0.5))
            dem.GetRasterBand(1).Fill(100)
            dem = None
            ds = ogr.GetDriverByName('ESRI Shapefile').CreateDataSource(str(folder/'points.shp'))
            layer = ds.CreateLayer('points', srs=sr, geom_type=ogr.wkbPoint)
            for field in ['start', 'end']:
                layer.CreateField(ogr.FieldDefn(field, ogr.OFTInteger))
            feature = ogr.Feature(layer.GetLayerDefn())
            feature.SetField('start', 80)
            feature.SetField('end', 100)
            feature.SetGeometry(ogr.CreateGeometryFromWkt('POINT (0 0)'))
            layer.CreateFeature(feature)
            feature = layer = ds = None
            config = APP['FastSettings'](str(folder/'points.shp'), str(folder/'world.tif'), 'start', 'end',
                str(folder/'results'), radius=5000, cell_size=100000, max_grid_mcells=1, curvature_enabled=False)
            output = Path(APP['run_fast'](config, log=lambda _: None))
            ds = ogr.Open(str(output/'visibility.shp'))
            self.assertGreater(ds.GetLayer(0).GetFeatureCount(), 0)
            self.assertEqual({f.GetField('radius_m') for f in ds.GetLayer(0)}, {5000000})
            ds = None


if __name__ == '__main__':
    unittest.main()
