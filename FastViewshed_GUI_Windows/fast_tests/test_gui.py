"""Offscreen Qt GUI test: real file selection metadata, worker and Shapefile."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import time
import faulthandler
import unittest
from unittest.mock import patch

import numpy as np

from osgeo import ogr
from PySide6 import QtCore, QtTest, QtWidgets

from fast_viewshed.gui import FastWindow
import test_engine as fixtures


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.data = fixtures.FastTerrainTests()
        self.data.setUp()
        self.window = FastWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        if self.window.thread is not None:
            self.window.cancel_analysis()
            self.wait_for_analysis(10000)
        self.window.close()
        self.app.processEvents()
        self.data.tearDown()
        faulthandler.cancel_dump_traceback_later()

    def wait_for_analysis(self, milliseconds=15000):
        # Use an actual Qt event loop, as the desktop app does. QTest.qWait
        # polling can hold the Python GIL and starve GDAL's Python callbacks.
        loop = QtCore.QEventLoop()
        poll = QtCore.QTimer()
        poll.setInterval(10)
        poll.timeout.connect(lambda: loop.quit() if self.window.thread is None else None)
        timeout = QtCore.QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        poll.start()
        timeout.start(milliseconds)
        loop.exec()
        poll.stop()
        timeout.stop()

    def test_gui_reads_fields_runs_real_analysis_and_shows_preview(self):
        faulthandler.dump_traceback_later(20)
        points, dem = self.data.inputs(ridge=True)
        window = self.window
        window.inputs["points"].setText(str(points))
        QtTest.QTest.mouseClick(window.read_fields, QtCore.Qt.LeftButton)
        self.assertEqual(window.inputs["start_field"].count(), 2)
        window.inputs["start_field"].setCurrentText("az_start")
        window.inputs["end_field"].setCurrentText("az_end")
        window.inputs["dem"].setText(str(dem))
        window.inputs["output_dir"].setText(str(self.data.root/"gui_results"))
        window.inputs["radius"].setValue(700)
        window.unit_boxes["radius_unit"].setCurrentIndex(window.unit_boxes["radius_unit"].findData("m"))
        window.inputs["cell_size"].setValue(10)
        window.inputs["observer"].setValue(2)
        window.inputs["receiver"].setValue(0)
        self.assertTrue(window.settings().auto_coarsen)
        self.assertEqual(window.settings().max_grid_mcells, 25)
        self.assertTrue(window.settings().curvature_enabled)
        window.curvature.setChecked(False)
        self.assertFalse(window.settings().curvature_enabled)
        self.assertFalse(window.inputs["atmospheric_factor"].isEnabled())
        window.curvature.setChecked(True)
        window.auto_coarsen.setChecked(False)
        window.inputs["max_grid_mcells"].setValue(40)
        self.assertFalse(window.settings().auto_coarsen)
        self.assertEqual(window.settings().max_grid_mcells, 40)
        QtTest.QTest.mouseClick(window.run_button, QtCore.Qt.LeftButton)
        self.wait_for_analysis()
        self.assertIsNone(window.thread, msg=window.log.toPlainText())
        self.assertIsNotNone(window.result_folder, msg=window.log.toPlainText())
        self.assertTrue((Path(window.result_folder)/"visibility.shp").exists())
        self.assertTrue((Path(window.result_folder)/"visible.shp").exists())
        self.assertEqual(window.preview_mode.currentData(), "visible")
        self.assertIn("visible.shp", window.preview_note.text())
        self.assertEqual(window.preview_selector.count(), 1)
        self.assertFalse(window.image.pixmap().isNull())
        self.assertEqual(window.progress_bar.value(), 100)
        self.assertTrue(window.run_button.isEnabled())
        screenshot = Path(__file__).resolve().parent.parent/"fast-test-results"/"FastViewshed_GUI.png"
        screenshot.parent.mkdir(exist_ok=True)
        window.grab().save(str(screenshot))
        first_result = window.result_folder
        # A second run in the same window exercises worker/thread retirement;
        # the first result must remain intact and the new target must be used.
        window.inputs["receiver"].setValue(300)
        QtTest.QTest.mouseClick(window.run_button, QtCore.Qt.LeftButton)
        self.wait_for_analysis()
        self.assertIsNone(window.thread, msg=window.log.toPlainText())
        self.assertNotEqual(first_result, window.result_folder)
        self.assertTrue((Path(first_result)/"visibility.shp").exists())
        self.assertEqual(self.data.statuses(Path(window.result_folder), 500755, 3950505), [1])
        self.assertEqual(window.preview_selector.count(), 1)
        faulthandler.cancel_dump_traceback_later()

    def test_changed_shape_requires_new_field_read_and_does_not_start_worker(self):
        points, _ = self.data.inputs()
        self.window.inputs["points"].setText(str(points))
        self.window.load_fields()
        self.window.inputs["points"].setText("other.shp")
        self.window.start_analysis()
        self.assertIsNone(self.window.thread)
        self.assertIn("ابتدا", self.window.log.toPlainText())

    def test_large_preview_reduces_array_before_allocating_color_buffers(self):
        # Broadcasted terrain occupies one byte, so this regression itself
        # does not need a large test allocation.
        classes = np.broadcast_to(np.uint8(1), (5725, 5725))
        with patch("fast_viewshed.gui.np.full", wraps=np.full) as allocate:
            self.window.receive_preview(0, classes, {"cell": 10})
        shape = allocate.call_args.args[0]
        self.assertLessEqual(max(shape[:2]), 1400)
        self.assertEqual(shape[2], 4)
        self.assertFalse(self.window.preview_images[0].isNull())
        self.assertFalse(self.window.visible_previews[0].isNull())
        self.assertEqual(self.window.preview_selector.count(), 1)

    def test_visible_preview_is_red_and_hidden_unknown_and_outside_are_transparent(self):
        self.window.receive_preview(0, np.array([[0, 1], [2, 255]], dtype=np.uint8), {"cell": 10})
        visible = self.window.visible_previews[0].toImage()
        for x, y in ((0, 0), (0, 1), (1, 1)):
            self.assertEqual(visible.pixelColor(x, y).alpha(), 0)
        color = visible.pixelColor(1, 0)
        self.assertGreater(color.alpha(), 0)
        self.assertGreater(color.red(), color.green())
        self.window.preview_mode.setCurrentIndex(1)
        self.assertIn("نامعلوم", self.window.preview_note.text())
        classes = self.window.preview_images[0].toImage()
        self.assertEqual(classes.pixelColor(0, 0).alpha(), 255)
        self.assertGreater(classes.pixelColor(1, 0).green(), classes.pixelColor(1, 0).red())

    def test_reference_button_maps_transmitter_receiver_k_fid_and_sea_policy(self):
        points, dem = self.data.inputs(extra=[(500855, "120", "250")])
        window = self.window
        window.inputs["points"].setText(str(points))
        window.load_fields()
        window.inputs["start_field"].setCurrentText("az_start")
        window.inputs["end_field"].setCurrentText("az_end")
        window.inputs["dem"].setText(str(dem))
        QtTest.QTest.mouseClick(window.reference_button, QtCore.Qt.LeftButton)
        cfg = window.settings()
        self.assertEqual(cfg.observer, 100)
        self.assertEqual(cfg.receiver, 2)
        self.assertEqual(cfg.radius_m, 100000)
        self.assertEqual(cfg.observer_fid, 1)
        self.assertEqual(cfg.nodata_policy, "sea_level")
        self.assertAlmostEqual(cfg.curvature_coefficient, .75, places=5)
        self.assertEqual(cfg.cell_size, 350)
        self.assertFalse(cfg.auto_coarsen)
        self.assertIn("تقریب", window.log.toPlainText())

    def test_form_fields_fit_their_viewport(self):
        self.app.processEvents()
        self.assertEqual(self.window.form_scroll.horizontalScrollBar().maximum(), 0)

    def test_attribute_height_modes_names_and_separate_files_run_through_gui(self):
        from test_per_point import add_attributes
        points, dem = self.data.inputs(extra=[(500155, "80", "100")])
        add_attributes(points, [("۱۰۰", "۲", "North"), ("۲۵", "۳", "South")])
        window = self.window
        window.inputs["points"].setText(str(points))
        window.load_fields()
        for key, value in (("start_field", "az_start"), ("end_field", "az_end"),
                           ("observer_field", "tx"), ("receiver_field", "rx")):
            window.inputs[key].setCurrentText(value)
        window.inputs["name_field"].setCurrentIndex(window.inputs["name_field"].findData("label"))
        for kind in ("observer", "receiver"):
            window.height_modes[kind].setChecked(True)
            self.assertFalse(window.inputs[kind].isEnabled())
            self.assertTrue(window.inputs[kind+"_field"].isEnabled())
        window.merge.setChecked(True)
        window.separate.setChecked(True)
        self.assertFalse(window.merge.isChecked())
        self.assertFalse(window.merge.isEnabled())
        self.assertIn("details", window.output_description.text())
        window.inputs["dem"].setText(str(dem))
        window.inputs["output_dir"].setText(str(self.data.root/"gui_separate"))
        window.inputs["radius"].setValue(700)
        window.unit_boxes["radius_unit"].setCurrentIndex(window.unit_boxes["radius_unit"].findData("m"))
        window.inputs["cell_size"].setValue(10)
        cfg = window.settings()
        self.assertEqual((cfg.observer_field, cfg.receiver_field, cfg.name_field), ("tx", "rx", "label"))
        QtTest.QTest.mouseClick(window.run_button, QtCore.Qt.LeftButton)
        self.wait_for_analysis()
        self.assertIsNone(window.thread, window.log.toPlainText())
        self.assertIsNotNone(window.result_folder, window.log.toPlainText())
        folder = Path(window.result_folder)
        self.assertTrue((folder/"points-North-100.shp").exists())
        self.assertTrue((folder/"points-South-25.shp").exists())
        self.assertEqual(len(list(folder.glob("*.shp"))), 2)
        self.assertEqual(window.preview_selector.count(), 2)
        self.assertIn("South", window.preview_selector.currentText())
        self.assertIn("مستقل", window.preview_note.text())
        self.assertFalse(window.inputs["observer"].isEnabled())
        self.assertFalse(window.merge.isEnabled())
        screenshots = Path(__file__).resolve().parent.parent/"fast-test-results"
        window.form_scroll.ensureWidgetVisible(window.height_modes["observer"])
        self.app.processEvents()
        window.grab().save(str(screenshots/"GUI_height_fields.png"))
        window.form_scroll.ensureWidgetVisible(window.separate)
        self.app.processEvents()
        window.grab().save(str(screenshots/"GUI_separate_outputs.png"))
        window.separate.setChecked(False)
        self.assertTrue(window.merge.isEnabled())
        self.assertIn("visible.shp", window.output_description.text())

    def test_checked_height_mode_requires_a_selected_column(self):
        points, dem = self.data.inputs()
        self.window.inputs["points"].setText(str(points))
        self.window.load_fields()
        self.window.inputs["start_field"].setCurrentText("az_start")
        self.window.inputs["end_field"].setCurrentText("az_end")
        self.window.inputs["dem"].setText(str(dem))
        self.window.height_modes["receiver"].setChecked(True)
        with self.assertRaisesRegex(ValueError, "ستون ارتفاع"):
            self.window.settings()

    def test_all_invalid_records_finish_gui_with_empty_shp_and_warning(self):
        points, dem = self.data.inputs(start="bad")
        window = self.window
        window.inputs["points"].setText(str(points))
        window.load_fields()
        window.inputs["start_field"].setCurrentText("az_start")
        window.inputs["end_field"].setCurrentText("az_end")
        window.inputs["dem"].setText(str(dem))
        window.inputs["output_dir"].setText(str(self.data.root/"gui_skips"))
        window.separate.setChecked(True)
        window.run_button.click()
        self.wait_for_analysis()
        self.assertIsNone(window.thread)
        self.assertIsNotNone(window.result_folder,msg=window.log.toPlainText())
        folder=Path(window.result_folder)
        ds=ogr.Open(str(folder/"visible.shp"))
        self.assertEqual(ds.GetLayer(0).GetFeatureCount(),0)
        self.assertEqual(window.preview_selector.count(),0)
        self.assertIn("هشدار",window.status.text())
        self.assertIn("FID=0",window.log.toPlainText())
        self.assertIn("skipped_records.csv",window.log.toPlainText())
        self.assertEqual(window.progress_bar.value(),100)
        self.assertTrue(window.open_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
