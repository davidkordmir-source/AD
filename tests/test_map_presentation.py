"""Real user map labels and high-contrast observer rendering in the shipped GUI."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'FastViewshed_GUI_Windows'))
from PySide6 import QtCore, QtWidgets
from desktop_customization import Preferences, load_map_file
from license_dialog import ActivationDialog, enforce_runtime_license
from licensing import LicenseError

ROOT = Path(__file__).resolve().parents[1]/'FastViewshed_GUI_Windows'
APP = runpy.run_path(str(ROOT/'FastViewshed_GUI.py'), run_name='presentation_tests')


class PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        p = Path(self.temp.name)
        self.window = APP['FastWindow'](Preferences(p/'profile',p/'branding'))
        self.window.resize(1500, 1000)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_actual_user_shapefile_names_render_and_do_not_overlap(self):
        data = load_map_file(ROOT/'assets/default_map/area.shp')
        names = {label['text'] for label in data['labels']}
        self.assertIn('Iran', names)
        self.assertGreaterEqual(len(names), 200)
        view = self.window.map_view
        view.fit_world()
        self.app.processEvents()
        view.viewport().grab()
        labels = view.visible_country_labels
        self.assertGreater(len(labels), 10)
        for index, (_, box) in enumerate(labels):
            for _, other in labels[index+1:]:
                self.assertFalse(box.intersects(other))
        view.set_labels_visible(False)
        view.viewport().grab()
        self.assertEqual(view.visible_country_labels, [])

    def test_loading_point_shapefile_immediately_displays_bold_red_markers(self):
        self.window.inputs['points'].setText(str(ROOT/'demo_fast/demo_points.shp'))
        self.window.load_fields()
        self.assertTrue(self.window.loaded_shape)
        self.assertGreater(len(self.window.map_view.point_items), 0)
        for item in self.window.map_view.point_items:
            self.assertEqual(item.brush().color().name(), '#ff304d')
            self.assertGreaterEqual(item.rect().width(), 14)
            self.assertEqual(item.pen().color().name(), '#ffffff')
            self.assertTrue(item.childItems())

    def test_expired_running_application_cancels_processing_and_closes_on_rejection(self):
        class Expired:
            device = 'a'*64
            def check(self):
                raise LicenseError('Expired synthetic license')
        QtCore.QTimer.singleShot(100, lambda: QtWidgets.QApplication.activeModalWidget().reject())
        enforce_runtime_license(self.window, Expired())
        self.window.check_runtime_license()
        self.assertTrue(self.window.cancel_event.is_set())
        self.assertTrue(self.window._license_exit_requested)
        self.assertFalse(self.window.isVisible())


if __name__ == '__main__':
    unittest.main()
