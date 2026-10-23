"""Exercise shipped code with real projected SHPs, Qt events and local profiles."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1] / 'FastViewshed_GUI_Windows'
sys.path.insert(0, str(ROOT))
from PySide6 import QtCore, QtGui, QtWidgets
from osgeo import gdal, ogr, osr
import desktop_customization as desktop
APP = runpy.run_path(str(ROOT / 'FastViewshed_GUI.py'), run_name='test_shipped_app')


class DesktopCustomizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prefs = desktop.Preferences(self.root / 'profile', self.root / 'app' / 'Branding')
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.close()
        self.qt.processEvents()
        self.tmp.cleanup()

    def shape(self, crs=True):
        filename = self.root / 'my_boundaries.shp'
        sr = osr.SpatialReference()
        sr.ImportFromEPSG(32639)
        ds = ogr.GetDriverByName('ESRI Shapefile').CreateDataSource(str(filename))
        layer = ds.CreateLayer('my_boundaries', srs=sr if crs else None, geom_type=ogr.wkbPolygon)
        f = ogr.Feature(layer.GetLayerDefn())
        g = ogr.CreateGeometryFromWkt('POLYGON ((500000 3950000,501000 3950000,501000 3951000,500000 3951000,500000 3950000))')
        f.SetGeometry(g)
        layer.CreateFeature(f)
        f = layer = ds = None
        return filename

    def window(self):
        w = APP['FastWindow'](self.prefs)
        self.windows.append(w)
        return w

    def wait_map(self, w):
        loop = QtCore.QEventLoop()
        poll = QtCore.QTimer()
        poll.setInterval(10)
        poll.timeout.connect(lambda: loop.quit() if w.map_thread is None else None)
        QtCore.QTimer.singleShot(15000, loop.quit)
        poll.start()
        loop.exec()
        poll.stop()
        self.assertIsNone(w.map_thread)

    def test_projected_shapefile_is_transformed_to_same_location_as_observer(self):
        path = self.shape()
        data = desktop.load_map_file(path)
        self.assertEqual(data['count'], 1)
        source = desktop.traditional(osr.SpatialReference())
        source.ImportFromEPSG(32639)
        target = desktop.traditional(osr.SpatialReference())
        target.ImportFromEPSG(4326)
        lon, lat, _ = osr.CoordinateTransformation(source, target).TransformPoint(500500, 3950500)
        center = APP['mercator_point'](lon, lat)
        self.assertTrue(data['bounds'].contains(center))
        # Original five vertices remain present: no approximation of supplied boundaries.
        self.assertEqual(data['paths'][0][1].elementCount(), 5)

    def test_missing_crs_is_rejected_and_can_be_explicitly_supplied(self):
        path = self.shape(crs=False)
        with self.assertRaisesRegex(ValueError, 'EPSG'):
            desktop.load_map_file(path)
        self.assertEqual(desktop.load_map_file(path, source_epsg=32639)['count'], 1)

    def test_background_replacement_preserves_observers_and_result_overlays(self):
        w = self.window()
        w.map_view.set_observers([(1, 51, 35)])
        marker = w.map_view.point_items[0]
        overlay = w.map_view.scene().addRect(0, 0, 2, 2)
        w.map_view.overlays[1] = overlay
        data = desktop.load_map_file(self.shape())
        w.map_view.replace_background(data)
        self.assertEqual(w.map_view.boundary_count, 1)
        self.assertEqual(len(w.map_view.background_items), 1)
        self.assertIs(marker.scene(), w.map_view.scene())
        self.assertIs(overlay.scene(), w.map_view.scene())
        w.map_view.restore_default_background()
        self.assertGreaterEqual(w.map_view.boundary_count, 200)
        self.assertIs(overlay.scene(), w.map_view.scene())

    def test_async_import_copies_sidecars_and_restores_from_private_profile(self):
        path = self.shape()
        w = self.window()
        w.start_map_load(str(path))
        self.wait_map(w)
        saved = self.prefs.data['map']
        self.assertNotEqual(saved['path'], str(path))
        for extension in ('.shp', '.shx', '.dbf', '.prj'):
            self.assertTrue(Path(saved['path']).with_suffix(extension).is_file())
        for source in path.parent.glob('my_boundaries.*'):
            source.unlink()
        w2 = self.window()
        self.qt.processEvents()
        if w2.map_thread is not None:
            self.wait_map(w2)
        self.assertEqual(w2.map_view.boundary_count, 1)
        self.assertNotIn('OpenStreetMap', w2.map_attribution.text())

    def test_failed_import_retains_previous_map_and_saved_selection(self):
        w = self.window()
        w.map_view.replace_background(desktop.load_map_file(self.shape()))
        old = list(w.map_view.background_items)
        with patch.object(QtWidgets.QMessageBox, 'warning') as warning:
            w.start_map_load(str(self.root / 'absent.shp'))
            self.wait_map(w)
            self.assertTrue(warning.called)
        self.assertEqual(w.map_view.background_items, old)
        self.assertNotIn('map', self.prefs.data)

    def test_raster_is_local_georeferenced_and_preview_has_bounded_dimensions(self):
        path = self.root / 'map.tif'
        sr = osr.SpatialReference()
        sr.ImportFromEPSG(32639)
        raster = gdal.GetDriverByName('GTiff').Create(str(path), 40, 20, 1, gdal.GDT_Byte)
        raster.SetProjection(sr.ExportToWkt())
        raster.SetGeoTransform((500000, 20, 0, 3951000, 0, -20))
        raster.GetRasterBand(1).Fill(120)
        raster = None
        data = desktop.load_map_file(path)
        self.assertEqual(data['kind'], 'raster')
        self.assertFalse(data['image'].isNull())
        self.assertLessEqual(max(data['image'].width(), data['image'].height()), 4096)
        w = self.window()
        w.map_view.replace_background(data)
        self.assertIsInstance(w.map_view.background_items[0], QtWidgets.QGraphicsPixmapItem)

    def test_password_is_salted_hashed_persistent_and_never_plaintext(self):
        self.prefs.set_password('my-own-password')
        self.assertNotIn('my-own-password', self.prefs.path.read_text())
        fresh = desktop.Preferences(self.prefs.folder)
        self.assertTrue(fresh.configured)
        self.assertFalse(fresh.verify('wrong'))
        self.assertTrue(fresh.verify('my-own-password'))
        old = fresh.data['admin']['salt']
        fresh.set_password('different-password')
        self.assertNotEqual(old, fresh.data['admin']['salt'])
        self.assertFalse(fresh.verify('my-own-password'))
        self.assertTrue(fresh.verify('different-password'))

    def test_repeated_wrong_password_temporarily_locks_access(self):
        self.prefs.set_password('some-password')
        for _ in range(5):
            self.assertFalse(self.prefs.verify('wrong-password'))
        with self.assertRaisesRegex(ValueError, '۳۰'):
            self.prefs.verify('some-password')

    def test_wrong_password_or_cancel_does_not_open_personalization(self):
        self.prefs.set_password('some-password')
        w = self.window()
        with patch.object(QtWidgets.QInputDialog, 'getText', return_value=('wrong', True)), \
             patch.object(QtWidgets.QMessageBox, 'warning'), \
             patch.dict(APP['FastWindow'].open_personalization.__globals__, {'PersonalizationDialog': lambda *args: self.fail('Unauthorized settings dialog')}):
            w.open_personalization()

    def test_settings_apply_only_after_save_and_logo_is_copied_for_offline_startup(self):
        original = self.root / 'company-logo.png'
        image = QtGui.QImage(100, 60, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor('#e02070'))
        image.save(str(original))
        dialog = desktop.PersonalizationDialog(self.prefs)
        dialog.title.setText('لوگوی شرکت من')
        dialog.font_size.setValue(15)
        dialog.new_logo = str(original)
        dialog.colors['accent'].setText('#8844bb')
        dialog.accept()
        original.unlink()
        self.assertTrue(Path(self.prefs.ui['logo']).exists())
        w = self.window()
        self.assertEqual(w.heading.text(), 'لوگوی شرکت من')
        self.assertIn('#8844bb', w.styleSheet())
        splash = desktop.create_splash(self.prefs)
        self.assertEqual(splash.pixmap().toImage().pixelColor(310, 100).name(), '#e02070')
        splash.show()
        self.qt.processEvents()
        self.assertTrue(splash.isVisible())
        splash.close()

    def test_portable_logo_survives_move_and_fresh_machine_profile(self):
        original = self.root / 'original.jpg'
        image = QtGui.QImage(100, 60, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor('#e02070'))
        self.assertTrue(image.save(str(original)))
        expected_color = QtGui.QImage(str(original)).pixelColor(50, 30).name()
        self.prefs.install_brand_logo(original)
        original.unlink()
        relocated = self.root / 'other computer' / 'Branding'
        shutil.move(str(self.prefs.branding_folder), str(relocated))
        fresh = desktop.Preferences(self.root / 'new-profile', relocated)
        self.assertTrue(fresh.verify('72381'))
        self.assertFalse(fresh.verify('wrong'))
        splash = desktop.create_splash(fresh, ROOT / 'assets' / 'aircraft.png')
        self.assertEqual(splash.pixmap().toImage().pixelColor(310, 100).name(), expected_color)
        splash.close()

    def test_dropped_logo_overrides_old_user_logo_and_invalid_file_falls_back(self):
        self.prefs.branding_folder.mkdir(parents=True)
        old = self.root / 'old.png'
        image = QtGui.QImage(100, 60, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor('#112233'))
        image.save(str(old))
        self.prefs.data['ui'] = {'logo': str(old)}
        dropped = self.prefs.branding_folder / 'logo.jpg'
        image.fill(QtGui.QColor('#ee7722'))
        image.save(str(dropped))
        self.assertEqual(self.prefs.ui['logo'], str(dropped))
        (self.prefs.branding_folder / 'logo.png').write_bytes(b'not an image')
        self.assertEqual(self.prefs.ui['logo'], str(dropped))
        dropped.unlink()
        self.assertEqual(self.prefs.ui['logo'], str(old))

    def test_bad_replacement_leaves_portable_logo_intact(self):
        image = QtGui.QImage(20, 20, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor('red'))
        original = self.root / 'red.png'
        image.save(str(original))
        installed = Path(self.prefs.install_brand_logo(original))
        before = installed.read_bytes()
        with self.assertRaises(ValueError):
            self.prefs.install_brand_logo(self.root / 'missing.png')
        self.assertEqual(installed.read_bytes(), before)
        with patch.object(desktop.os, 'replace', side_effect=PermissionError('read only')):
            with self.assertRaises(PermissionError):
                self.prefs.install_brand_logo(original)
        self.assertEqual(installed.read_bytes(), before)
        self.assertEqual(list(self.prefs.branding_folder.glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
