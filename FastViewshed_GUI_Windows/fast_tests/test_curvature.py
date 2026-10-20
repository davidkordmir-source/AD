"""Physical sanity check at the user's 100 km / 2 m / 100 m settings."""

import unittest

import numpy as np

from fast_viewshed.engine import local_result, raster_dataset, spatial_ref
from fast_viewshed.model import FastSettings


class CurvatureTests(unittest.TestCase):
    def test_flat_terrain_100km_distinguishes_curved_and_flat_earth(self):
        sr = spatial_ref("+proj=aeqd +lat_0=35 +lon_0=51 +datum=WGS84 +units=m +no_defs")
        size, cell = 407, 500
        source = raster_dataset(np.full((size, size), 100, dtype=np.float32),
                                (-size*cell/2, cell, 0, size*cell/2, 0, -cell), sr.ExportToWkt())
        results = {}
        for curved in (True, False):
            cfg = FastSettings("p", "d", "s", "e", "o", radius=100, radius_unit="km",
                               receiver=2, target=100, cell_size=cell, curvature_enabled=curved)
            classes, gt, _, _, _ = local_result(source, sr, (0, 51, 35, 0, 360), cfg,
                                                lambda _: None, lambda _: None, lambda: False)
            def sample(distance):
                row = int((0-gt[3])/gt[5])
                col = int((distance-gt[0])/gt[1])
                return classes[row, col]
            self.assertEqual(sample(20000), 1)
            results[curved] = sample(70000)
        # With standard refraction, the flat-terrain horizon for these two
        # heights is about 44 km. Disabling curvature removes this limit.
        self.assertEqual(results[True], 0)
        self.assertEqual(results[False], 1)


if __name__ == "__main__":
    unittest.main()
