"""Verify the bundled interpreter, native GIS, Qt and a real local analysis.

Uses only the standard library until it loads the bundled application. This
script is run by the private interpreter with outbound access blocked in CI.
"""

import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    runtime = Path(args.runtime).resolve()
    if Path(sys.executable).resolve().parent != runtime:
        raise RuntimeError("The bundled Python interpreter must run this check.")
    os.environ["PROJ_NETWORK"] = "OFF"
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app_folder = Path(__file__).resolve().parent.parent
    application = runpy.run_path(str(app_folder/"FastViewshed_GUI.py"), run_name="offline_verification")
    import numpy as np
    from osgeo import gdal, ogr, osr
    from PySide6 import QtCore, QtWidgets

    if osr.GetPROJEnableNetwork():
        raise RuntimeError("PROJ network must be disabled.")
    sr = application["spatial_ref"]("EPSG:32639")
    with tempfile.TemporaryDirectory(prefix="fast_viewshed_offline_") as directory:
        root = Path(directory)
        dem = root/"terrain.tif"
        ds = gdal.GetDriverByName("GTiff").Create(str(dem), 100, 100, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((500000, 10, 0, 3951000, 0, -10))
        ds.SetProjection(sr.ExportToWkt())
        values = np.full((100, 100), 100, dtype=np.float32)
        values[:, 35] = 150
        ds.GetRasterBand(1).WriteArray(values)
        ds = None
        points = root/"points.shp"
        ds = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(str(points))
        layer = ds.CreateLayer("points", srs=sr, geom_type=ogr.wkbPoint, options=["ENCODING=UTF-8"])
        for field in ("AZFR", "AZTO", "tx", "rx", "name"):
            layer.CreateField(ogr.FieldDefn(field, ogr.OFTString))
        for i, (tx, rx) in enumerate((("100", "2"), ("2", "100"))):
            f = ogr.Feature(layer.GetLayerDefn())
            geom = ogr.Geometry(ogr.wkbPoint)
            geom.AddPoint_2D(500155, 3950505)
            f.SetGeometry(geom)
            for key, value in dict(AZFR="80", AZTO="100", tx=tx, rx=rx, name=f"Site{i}").items():
                f.SetField(key, value)
            layer.CreateFeature(f)
        f = layer = ds = None
        config = application["FastSettings"](str(points), str(dem), "AZFR", "AZTO", str(root/"results"),
                    radius=700, radius_unit="m", cell_size=10, observer_field="tx", receiver_field="rx",
                    name_field="name", separate_outputs=True)
        result = Path(application["run_fast"](config, log=lambda _: None))
        metadata = json.loads((result/"run.json").read_text(encoding="utf-8"))
        assert metadata["status"] == "completed" and metadata["offline"] is True
        assert len(metadata["primary_outputs"]) == 2
        target = ogr.Geometry(ogr.wkbPoint)
        target.AddPoint_2D(500755, 3950505)
        covered = []
        for filename in metadata["primary_outputs"]:
            ds = ogr.Open(str(result/filename))
            assert ds is not None
            covered.append(any(f.GetGeometryRef().Intersects(target) for f in ds.GetLayer(0)))
            ds = None
        assert covered == [True, False], covered

        from dataclasses import replace
        named = Path(application["run_fast"](replace(config, separate_outputs=False, combined_name_field="name", combined_name_value="Site1"), log=lambda _:None))
        named_report = json.loads((named/"run.json").read_text(encoding="utf-8"))
        assert named_report["primary_output"] == "Site1.shp"
        named_ds = ogr.Open(str(named/"Site1.shp"))
        assert {f.GetField("src_id") for f in named_ds.GetLayer(0)} == {0,1}
        named_ds = None
        # Exercise the shipped record-skipping behavior with real native SHPs.
        ds = ogr.Open(str(points), 1)
        layer = ds.GetLayer(0)
        feature = layer.GetFeature(0)
        feature.SetFieldNull("tx")
        layer.SetFeature(feature)
        feature = layer = ds = None
        mixed = Path(application["run_fast"](config, log=lambda _: None))
        mixed_report = json.loads((mixed/"run.json").read_text(encoding="utf-8"))
        assert mixed_report["succeeded_records"] == 1 and mixed_report["skipped_count"] == 1
        assert mixed_report["skipped_records"][0]["src_id"] == 0
        ds = ogr.Open(str(points), 1)
        layer = ds.GetLayer(0)
        feature = layer.GetFeature(1)
        feature.SetFieldNull("tx")
        layer.SetFeature(feature)
        feature = layer = ds = None
        from dataclasses import replace
        for separate in (False, True):
            empty = Path(application["run_fast"](replace(config, separate_outputs=separate), log=lambda _: None))
            empty_report = json.loads((empty/"run.json").read_text(encoding="utf-8"))
            assert empty_report["succeeded_records"] == 0 and empty_report["skipped_count"] == 2
            assert empty_report["outcome"] == "no_valid_observers"
            assert (empty/"skipped_records.csv").is_file()
            for extension in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
                assert (empty/("visible"+extension)).is_file()
            ds = ogr.Open(str(empty/"visible.shp"))
            assert ds.GetLayer(0).GetFeatureCount() == 0
            ds = None
        # Restore both good rows for the actual Qt worker check.
        ds = ogr.Open(str(points), 1)
        layer = ds.GetLayer(0)
        for fid, height in ((0, "100"), (1, "2")):
            feature = layer.GetFeature(fid)
            feature.SetField("tx", height)
            layer.SetFeature(feature)
        feature = layer = ds = None

        # Start the actual GUI, read fields and drive its real worker thread.
        qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        import desktop_customization as desktop
        preferences = desktop.Preferences(root/'profile')
        assert preferences.configured
        window = application['FastWindow'](preferences)
        window.inputs["points"].setText(str(points))
        window.load_fields()
        window.inputs["start_field"].setCurrentText("AZFR")
        window.inputs["end_field"].setCurrentText("AZTO")
        window.inputs["dem"].setText(str(dem))
        window.inputs["output_dir"].setText(str(root/"gui_results"))
        window.inputs["radius"].setValue(700)
        window.unit_boxes["radius_unit"].setCurrentIndex(window.unit_boxes["radius_unit"].findData("m"))
        window.inputs["cell_size"].setValue(10)
        for kind, field in (("observer", "tx"), ("receiver", "rx")):
            window.height_modes[kind].setChecked(True)
            window.inputs[kind+"_field"].setCurrentText(field)
        window.separate.setChecked(True)
        assert window.map_view.boundary_count >= 200
        assert not window.windowIcon().isNull()
        window.show()
        window.run_button.click()
        loop = QtCore.QEventLoop()
        poll = QtCore.QTimer()
        poll.setInterval(20)
        poll.timeout.connect(lambda: loop.quit() if window.thread is None else None)
        timeout = QtCore.QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        poll.start()
        timeout.start(60000)
        loop.exec()
        poll.stop()
        timeout.stop()
        if window.thread is not None:
            raise RuntimeError("GUI worker timed out during offline verification.")
        if not window.result_folder or window.preview_selector.count() != 2:
            raise RuntimeError(window.log.toPlainText())
        # Replace the shipped world map using a real projected SHP on the map worker.
        assert window.map_view.boundary_count == 4510
        window.start_map_load(str(points))
        map_loop = QtCore.QEventLoop()
        map_poll = QtCore.QTimer()
        map_poll.setInterval(20)
        map_poll.timeout.connect(lambda: map_loop.quit() if window.map_thread is None else None)
        map_timeout = QtCore.QTimer()
        map_timeout.setSingleShot(True)
        map_timeout.timeout.connect(map_loop.quit)
        map_poll.start()
        map_timeout.start(60000)
        map_loop.exec()
        map_poll.stop()
        map_timeout.stop()
        assert window.map_thread is None
        assert window.map_view.boundary_count == 2
        assert len(window.map_view.overlays) == 2
        saved_map = Path(preferences.data['map']['path'])
        assert saved_map.is_file() and saved_map.with_suffix('.prj').is_file()
        window.restore_background_map()
        assert window.map_view.boundary_count == 4510
        # Exercise local logo persistence, rendering and password verification offline.
        from PySide6 import QtGui
        logo = QtGui.QImage(100, 80, QtGui.QImage.Format_RGB32)
        logo.fill(QtGui.QColor('#e02070'))
        logo_file = root/'test_company_logo.png'
        assert logo.save(str(logo_file))
        copied = preferences.copy_logo(logo_file)
        preferences.data['ui'] = dict(logo=copied, title='Offline custom title', font_size=14, accent='#554488')
        preferences.save()
        logo_file.unlink()
        preferences.set_password('offline-test-admin')
        assert not preferences.verify('incorrect-password')
        assert preferences.verify('offline-test-admin')
        window.apply_personalization()
        assert window.heading.text() == 'Offline custom title'
        splash = desktop.create_splash(preferences)
        splash.show()
        qt.processEvents()
        assert splash.isVisible()
        assert splash.pixmap().toImage().pixelColor(310, 100).name() == '#e02070'
        splash.close()
        window.close()
        qt.processEvents()
    report = dict(status="passed", offline=True, python=sys.version, executable=str(Path(sys.executable)),
                  gdal=gdal.VersionInfo("RELEASE_NAME"), qt=QtCore.qVersion(), numpy=np.__version__,
                  proj_network=False, private_runtime=True, shapefile_round_trip=True,
                  transmitter_receiver_regression=True, gui_worker=True, previews=2, invalid_record_skipping=True,
                  all_invalid_empty_shapefile=True, skip_report_written=True, combined_attribute_filename=True, offline_osm_map=False, aircraft_icon=True, default_user_map_features=4510, custom_map_import=True, protected_personalization=True, custom_logo_splash=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Offline runtime verification passed: GDAL, NumPy, Qt, real viewshed and GUI.")


if __name__ == "__main__":
    main()
