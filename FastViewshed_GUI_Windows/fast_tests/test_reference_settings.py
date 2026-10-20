"""Regression for GM dialog semantics using generated, public test data."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from fast_viewshed.engine import inspect_shape, load_observers, visible_radius
from fast_viewshed.model import FastSettings, azimuth


class ReferenceSettingsTests(unittest.TestCase):
    def test_k_factor_is_converted_to_gdal_curvature_not_used_as_refraction(self):
        cfg = FastSettings("p", "d", "s", "e", "o", atmospheric_factor=1.33333)
        self.assertAlmostEqual(cfg.curvature_coefficient, .750001875, places=9)
        cfg.validate()
        flat = FastSettings("p", "d", "s", "e", "o", atmospheric_factor=1.33333, curvature_enabled=False)
        self.assertEqual(flat.curvature_coefficient, 0)

    def test_geojson_text_scientific_angles_and_fid_are_supported(self):
        # Artificial coordinates; no uploaded user geometry is distributed.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"points.geojson"
            data = {"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {"Id": "0", "AZFR": a, "AZTO": b},
                 "geometry": {"type": "Point", "coordinates": [51+i*.01, 35]}}
                for i, (a, b) in enumerate((("0", "120"), ("1.20000000000e+02", "2.50000000000e+02")))]}
            path.write_text(json.dumps(data))
            self.assertEqual(inspect_shape(path)["count"], 2)
            rows, _ = load_observers(FastSettings(str(path), "d", "AZFR", "AZTO", directory, observer_fid=1))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], 1)
            self.assertEqual(rows[0][3:], (120, 250))
            self.assertEqual(rows[0][4]-rows[0][3], 130)

    def test_scientific_azimuths_are_finite_and_in_range(self):
        self.assertEqual(azimuth("1.20000000000e+02"), 120)
        for invalid in ("1e309", "-1e2", "3.61e2"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                azimuth(invalid)

    def test_visible_radius_measures_cell_centres_and_handles_empty_results(self):
        classes = np.full((3, 3), 255, dtype=np.uint8)
        gt = (-15, 10, 0, 15, 0, -10)
        self.assertEqual(visible_radius(classes, gt), 0)
        classes[1, 2] = 1
        self.assertEqual(visible_radius(classes, gt), 10)
