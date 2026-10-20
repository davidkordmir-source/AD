"""The bundled app performs GIS analysis with no local project-module imports."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_engine as fixtures


ROOT = Path(__file__).resolve().parent.parent


class BundleTests(unittest.TestCase):
    def test_single_file_runs_real_backend_in_isolated_directory(self):
        fixture = fixtures.FastTerrainTests()
        fixture.setUp()
        try:
            points, dem = fixture.inputs(ridge=True)
            with tempfile.TemporaryDirectory() as directory:
                script = Path(directory)/"FastViewshed_GUI.py"
                shutil.copyfile(ROOT/"FastViewshed_GUI.py", script)
                code = '''
import importlib.abc, json, runpy, sys
class NoProject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("fast_viewshed", "sector_viewshed")):
            raise ImportError("Unexpected project-side module import: "+fullname)
sys.meta_path.insert(0, NoProject())
app = runpy.run_path(sys.argv[1], run_name="standalone_test")
config = app["FastSettings"](**json.loads(sys.stdin.readline()))
result = app["run_fast"](config, log=lambda message: None)
print(json.dumps({"result": result}))
'''
                config = dict(points=str(points), dem=str(dem), start_field="az_start", end_field="az_end",
                              output_dir=str(fixture.root/"bundle_results"), radius=700, radius_unit="m", cell_size=10)
                process = subprocess.run([sys.executable, "-c", code, str(script)], cwd=directory,
                                         input=json.dumps(config)+"\n", capture_output=True, text=True, timeout=30)
                self.assertEqual(process.returncode, 0, msg=process.stderr)
                folder = Path(json.loads(process.stdout)["result"])
                self.assertEqual(fixture.statuses(folder, 500755, 3950505), [0])
                self.assertTrue((folder/"visibility.shx").exists())
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
