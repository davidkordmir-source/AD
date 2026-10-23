"""Build SOURCE-ONLY archives; complete offline runtime is built on Windows.

Use build_offline_windows.py / the Windows GitHub workflow for the runnable
offline package. These source archives deliberately do not bundle native DLLs.
"""

import hashlib
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT/"dist"
PREFIX = "FastViewshed_GUI_Windows/"
UPDATE = """Fast Sector Viewshed 3.3 — SOURCE ONLY

This small update contains application source, not Python/GDAL/Qt binaries.
An existing working runtime is required. To install on an offline computer,
use FastViewshed_Offline_Windows_x64_v3.3.0.zip from the GitHub release.

The complete offline bundle includes Python and native dependencies and uses
only local extraction at the destination. Do not use an older online installer.
"""


def main():
    DIST.mkdir(exist_ok=True)
    files = ["FastViewshed_GUI.py", "FastViewshed_GUI_COPY.txt", "desktop_customization.py", "Install_Fast_Viewshed.bat",
             "Run_Fast_Viewshed.bat", "Install_Fast_Viewshed_COPY.txt", "Run_Fast_Viewshed_COPY.txt",
             "environment-fast.yml", "environment-fast_COPY.txt", "README_FAST_FA.md", "BRANDING_UPDATE_FA.txt", "run_fast_gui.py",
             "sector_viewshed/core.py", "sector_viewshed/__init__.py",
             "scripts/build_fast_standalone.py", "scripts/benchmark_fast.py",
             "scripts/validate_large_grid.py", "scripts/package_fast.py",
             "Check_Offline.bat", "_Activate_Offline.bat", "_Finalize_Offline.bat", "RELEASE_OFFLINE.md",
             "scripts/install_offline.ps1", "scripts/check_offline.py", "scripts/build_offline_windows.py",
             "scripts/test_offline_windows.ps1", "scripts/finalize_offline_release.py", "scripts/build_windows_installer.ps1", "scripts/test_windows_installer.ps1"]
    for pattern in ("fast_viewshed/*.py", "fast_tests/test_*.py", "demo_fast/*", "assets/*", "installer/*", "Branding/*"):
        files.extend(str(p.relative_to(ROOT)) for p in sorted(ROOT.glob(pattern)) if p.is_file())
    full = DIST/"FastViewshed_Source_v3.3.0.zip"
    with ZipFile(full.with_suffix(".tmp"), "w", ZIP_DEFLATED) as z:
        for name in files:
            if name.endswith(".bat"):
                # Preserve Windows CRLF line endings for the launchers.
                z.writestr(PREFIX+name, (ROOT/name).read_text(encoding="utf-8").replace("\n", "\r\n"))
            else:
                z.write(ROOT/name, PREFIX+name)
        z.write(DIST/"FastViewshed_VALIDATION.json", PREFIX+"VALIDATION.json")
        z.write(ROOT/"fast-test-results/FastViewshed_GUI.png", PREFIX+"GUI.png")
        for screenshot in ("GUI_height_fields.png", "GUI_separate_outputs.png"):
            path = ROOT/"fast-test-results"/screenshot
            if path.exists():
                z.write(path, PREFIX+screenshot)
        z.writestr(PREFIX+"README.md", "# Fast Sector Viewshed 3.3.0 — SOURCE ONLY\n\nThis archive contains source code and synthetic demo data. It does not contain a Python runtime or native dependencies and is NOT the complete offline installation.\n\nFor a self-contained offline installation, download FastViewshed_Offline_Windows_x64_v3.3.0.zip from https://github.com/davidkordmir-source/AD/releases/tag/v3.3.0-installer .\n\nOffline builds are produced by scripts/build_offline_windows.py on Windows and verified with Windows Firewall blocking the bundled interpreter.\n")
        z.writestr(PREFIX+"UPDATE_FA.txt", UPDATE)
    full.with_suffix(".tmp").replace(full)
    patch = DIST/"FastViewshed_Source_Update_v3.3.0.zip"
    with ZipFile(patch, "w", ZIP_DEFLATED) as z:
        z.write(ROOT/"FastViewshed_GUI.py", "FastViewshed_GUI.py")
        z.writestr("UPDATE_FA.txt", UPDATE)
        for asset in sorted((ROOT/"assets").glob("*")):
            z.write(asset, "assets/"+asset.name)
    for path in (full, patch):
        with ZipFile(path) as z:
            assert z.testzip() is None
        print(path.name, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
