"""Build full Windows source distribution and the one-file 3.0 update."""

import hashlib
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT/"dist"
PREFIX = "FastViewshed_GUI_Windows/"
UPDATE = """به‌روزرسانی Fast Sector Viewshed به نسخهٔ ۳٫۰

۱. برنامه را ببندید.
۲. FastViewshed_GUI.py جدید را کنار همان Run_Fast_Viewshed.bat و runtime
   جایگزین کنید؛ فایل را داخل runtime نریزید.
۳. همان فایل اجرای قبلی را باز کنید. عنوان پنجره باید نسخهٔ 3.0 باشد.
نصب مجدد کتابخانه‌ها لازم نیست.

اصلاح محاسبه بر اساس تصویر تنظیمات Global Mapper:
- Transmitter Elevation: ارتفاع فرستنده/ناظر در محل نقطه، ۱۰۰ متر بالای DEM.
- Receiver Elevation: ارتفاع گیرنده روی سلول‌های مقصد، ۲ متر بالای DEM.
در نسخه‌های ۲.x برچسب‌ها باعث اعمال برعکس این دو ارتفاع می‌شدند.
- Atmospheric Correction=1.33333، با ضریب انحنای GDAL برابر 1/k.
- انتخاب رفتار ارتفاع ناموجود: نامعلوم یا دریا با ارتفاع صفر.
- انتخاب یک FID برای مقایسهٔ همان ناظر؛ منفی یک یعنی همه.
- ورودی Shapefile یا GeoJSON، آزیموت متنی با نمایش علمی نیز پشتیبانی می‌شود.

پس از انتخاب نقاط و DEM، دکمهٔ «اعمال تنظیمات تصویر Global Mapper برای FID=1»
را بزنید. این دکمه ۱۰۰ کیلومتر، فرستنده ۱۰۰ متر، گیرنده ۲ متر، k=1.33333،
انحنای روشن و ارتفاع ناموجود=دریا را تنظیم می‌کند و در صورت وجود، فیلدهای
AZFR و AZTO را انتخاب می‌کند. پایان آزیموت ۲۵۰ با شروع ۱۲۰ یعنی Sweep=130.
فاصلهٔ پیکسل ۳۵۰ متر تقریب فاصلهٔ زاویه‌ای تصویر است؛ یکسان بودن دقیق شبکه
یا روش نمونه‌برداری دو برنامه تأیید نشده است.

خروجی اصلی visible.shp است. درصد و مساحت کلاس‌ها و دورترین سلول قابل‌دید
در گزارش و run.json ذخیره می‌شوند. نتایج نسخهٔ قدیمی را برای مقایسهٔ اصلاح
با نتیجهٔ اجرای جدید اشتباه نگیرید. تطابق روی DEM واقعی کاربر هنوز به
دریافت آن DEM و مقایسه با خروجی مرجع نیاز دارد.
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
        z.writestr(PREFIX+"README.md", "# Fast Sector Viewshed 3.0\n\nPrimary output: visible.shp (visible cells only). visibility.shp contains all classes; sectors.shp contains analysis bounds.\n\nRead README_FAST_FA.md for installation, update and large-grid settings.\n\nInstall Miniforge if needed, then run Install_Fast_Viewshed.bat once and Run_Fast_Viewshed.bat to open the GUI.\n\nThis is a Python/Qt source GUI package. Windows installation is not yet verified on Windows. Numerical equivalence to Global Mapper on the user DEM is not established.\n")
        z.writestr(PREFIX+"UPDATE_FA.txt", UPDATE)
    full.with_suffix(".tmp").replace(full)
    patch = DIST/"FastViewshed_Update_v3.0.zip"
    with ZipFile(patch, "w", ZIP_DEFLATED) as z:
        z.write(ROOT/"FastViewshed_GUI.py", "FastViewshed_GUI.py")
        z.writestr("UPDATE_FA.txt", UPDATE)
    for path in (full, patch):
        with ZipFile(path) as z:
            assert z.testzip() is None
        print(path.name, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
