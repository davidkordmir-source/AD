"""Offscreen Qt GUI test: real file selection metadata, worker and Shapefile."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import time
import faulthandler
import unittest

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
        QtTest.QTest.mouseClick(window.run_button, QtCore.Qt.LeftButton)
        self.wait_for_analysis()
        self.assertIsNone(window.thread, msg=window.log.toPlainText())
        self.assertIsNotNone(window.result_folder, msg=window.log.toPlainText())
        self.assertTrue((Path(window.result_folder)/"visibility.shp").exists())
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
        window.inputs["target"].setValue(300)
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


if __name__ == "__main__":
    unittest.main()
