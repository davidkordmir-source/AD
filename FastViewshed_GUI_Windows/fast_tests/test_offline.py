"""Offline mode rejects network-capable inputs before opening them."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from osgeo import gdal, osr
from fast_viewshed.engine import inspect_shape, run_fast
from fast_viewshed.model import FastSettings

ROOT = Path(__file__).resolve().parent.parent


class OfflineTests(unittest.TestCase):
    def test_online_coordinate_grid_fetching_is_disabled(self):
        self.assertFalse(osr.GetPROJEnableNetwork())

    def test_remote_points_rejected_without_native_open(self):
        with patch('fast_viewshed.engine.gdal.OpenEx') as opening:
            with self.assertRaises(ValueError):
                inspect_shape('https://example.org/stations.geojson')
            opening.assert_not_called()

    def test_remote_dem_rejected_without_native_open(self):
        with tempfile.TemporaryDirectory() as output:
            config = FastSettings(str(ROOT/'demo_fast/demo_points.shp'),
                                  '/vsicurl/https://example.org/elevation.tif',
                                  'AZFR', 'AZTO', output)
            with patch('fast_viewshed.engine.gdal.OpenEx', wraps=gdal.OpenEx) as opening:
                with self.assertRaises(ValueError):
                    run_fast(config, log=lambda _: None)
                self.assertTrue(opening.called)
                self.assertTrue(all('example.org' not in str(call.args[0]) for call in opening.call_args_list))

    def test_virtual_raster_cannot_fetch_online_source(self):
        with tempfile.TemporaryDirectory() as output:
            path=Path(output)/'remote.vrt'
            path.write_text('''<VRTDataset rasterXSize="1" rasterYSize="1">
<VRTRasterBand dataType="Float32" band="1"><SimpleSource>
<SourceFilename>/vsicurl/https://example.org/terrain.tif</SourceFilename>
<SourceBand>1</SourceBand></SimpleSource></VRTRasterBand></VRTDataset>''')
            config=FastSettings(str(ROOT/'demo_fast/demo_points.shp'), str(path), 'AZFR','AZTO',output)
            with self.assertRaisesRegex(RuntimeError, 'not recognized|not supported|unsupported'):
                run_fast(config, log=lambda _:None)
            self.assertFalse(any(Path(output).glob('fast_viewshed_*')))
