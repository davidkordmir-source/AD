"""Build full Windows source distribution and the one-file 3.1 update."""

import hashlib
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT/"dist"
PREFIX = "FastViewshed_GUI_Windows/"
UPDATE = """به‌روزرسانی Fast Sector Viewshed به نسخهٔ ۳٫۱

برنامه را ببندید؛ FastViewshed_GUI.py داخل اصلاحیه را کنار همان
Run_Fast_Viewshed.bat قبلی جایگزین کنید. نصب مجدد کتابخانه‌ها لازم نیست.
عنوان پنجرهٔ جدید باید Fast Sector Viewshed 3.1 باشد.

امکانات جدید:
۱. ارتفاع فرستنده و ارتفاع گیرنده، هر کدام مستقل از ستون عددی یا تکست.
   چک‌باکس «فرستنده از ستون» یا «گیرنده از ستون» را بزنید و ستون را انتخاب
   کنید. بدون تیک، مقدار ثابت استفاده می‌شود. واحد از کمبوباکس همان ارتفاع
   گرفته می‌شود. متن‌هایی مانند ۱۰۰، 2.5 و 1e2 پذیرفته می‌شوند.
۲. ستون نام نقطه برای name قابل انتخاب است. نام فارسی حفظ می‌شود؛ نام
   خالی یا نبود ستون نام با FID جایگزین می‌شود.
۳. چک‌باکس «برای هر نقطه یک شیپ‌فایل قابل‌دید مستقل»:
   خاموش: همهٔ نقاط در visible.shp، مثل نسخهٔ قبل.
   روشن: یک فایل اصلی برای هر نقطه، مثلاً Stations-SiteA-100.shp.
   الگو: نام فایل مرجع-نام نقطه-ارتفاع فرستنده/آبجکت بر حسب متر.
   نام تکراری با FID متمایز می‌شود؛ فایل‌ها روی هم نوشته نمی‌شوند.
۴. در حالت مستقل، لایه‌های کمکی داخل details هستند و primary_outputs
   در run.json فهرست فایل‌های اصلی را نگه می‌دارد.

برای همهٔ نقاط، FID را روی منفی یک / همهٔ نقاط بگذارید. دکمهٔ تنظیمات
مرجع Global Mapper، FID=1 و ارتفاع ثابت ۱۰۰/۲ را اعمال می‌کند؛ اگر از آن
استفاده کردید، انتخاب ستون ارتفاع را پس از آن انجام دهید.

نگاشت پذیرفته‌شدهٔ نسخهٔ ۳٫۰ حفظ شده است: فرستنده در محل نقطه و گیرنده
روی سلول‌های اطراف؛ هر دو ارتفاع نسبت به DEM هستند. عدد پایانی نام فایل
ارتفاع افزودهٔ فرستنده بالای DEM است، نه ارتفاع کل آن نسبت به سطح مبنا.
"""


def main():
    DIST.mkdir(exist_ok=True)
    files = ["FastViewshed_GUI.py", "FastViewshed_GUI_COPY.txt", "Install_Fast_Viewshed.bat",
             "Run_Fast_Viewshed.bat", "Install_Fast_Viewshed_COPY.txt", "Run_Fast_Viewshed_COPY.txt",
             "environment-fast.yml", "environment-fast_COPY.txt", "README_FAST_FA.md", "run_fast_gui.py",
             "sector_viewshed/core.py", "sector_viewshed/__init__.py",
             "scripts/build_fast_standalone.py", "scripts/benchmark_fast.py",
             "scripts/validate_large_grid.py", "scripts/package_fast.py"]
    for pattern in ("fast_viewshed/*.py", "fast_tests/test_*.py", "demo_fast/*"):
        files.extend(str(p.relative_to(ROOT)) for p in sorted(ROOT.glob(pattern)) if p.is_file())
    full = DIST/"FastViewshed_GUI_Windows.zip"
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
        z.writestr(PREFIX+"README.md", "# Fast Sector Viewshed 3.1\n\nPrimary output: visible.shp in combined mode; reference-name-height.shp per point in separate mode. Heights may come from numeric or text attributes and the selected point name is stored in the name field. visibility.shp contains all classes; sectors.shp contains analysis bounds.\n\nRead README_FAST_FA.md for installation, update and large-grid settings.\n\nInstall Miniforge if needed, then run Install_Fast_Viewshed.bat once and Run_Fast_Viewshed.bat to open the GUI.\n\nThis is a Python/Qt source GUI package. Windows installation is not yet verified on Windows. Numerical equivalence to Global Mapper on the user DEM is not established.\n")
        z.writestr(PREFIX+"UPDATE_FA.txt", UPDATE)
    full.with_suffix(".tmp").replace(full)
    patch = DIST/"FastViewshed_Update_v3.1.zip"
    with ZipFile(patch, "w", ZIP_DEFLATED) as z:
        z.write(ROOT/"FastViewshed_GUI.py", "FastViewshed_GUI.py")
        z.writestr("UPDATE_FA.txt", UPDATE)
    for path in (full, patch):
        with ZipFile(path) as z:
            assert z.testzip() is None
        print(path.name, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
