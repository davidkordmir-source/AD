"""Fast first-install prerequisite check; full analysis remains in check_offline.py."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    if Path(sys.executable).resolve().parent != Path(args.runtime).resolve():
        raise RuntimeError('Use the bundled Python interpreter.')
    os.environ['PROJ_NETWORK'] = 'OFF'
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    import numpy as np
    from osgeo import gdal, osr
    from PySide6 import QtCore, QtWidgets
    reference = osr.SpatialReference()
    if reference.ImportFromEPSG(4326) != 0:
        raise RuntimeError('The bundled PROJ database is unavailable.')
    raster = gdal.GetDriverByName('MEM').Create('', 2, 2, 1, gdal.GDT_Byte)
    raster.GetRasterBand(1).WriteArray(np.ones((2, 2), dtype=np.uint8))
    if int(raster.GetRasterBand(1).ReadAsArray().sum()) != 4:
        raise RuntimeError('Native GDAL/NumPy interoperability failed.')
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = QtWidgets.QWidget()
    widget.show()
    app.processEvents()
    if not widget.isVisible():
        raise RuntimeError('The bundled Qt plugin is unavailable.')
    widget.close()
    Path(args.report).write_text(json.dumps(dict(status='passed', runtime_prerequisites=True,
        gdal=gdal.VersionInfo('RELEASE_NAME'), qt=QtCore.qVersion(), numpy=np.__version__,
        full_analysis_test=False)), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
