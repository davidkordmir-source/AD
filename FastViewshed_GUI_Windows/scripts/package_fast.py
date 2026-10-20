"""Build full Windows source distribution and the one-file 2.1 update."""

import hashlib
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT/"dist"
PREFIX = "FastViewshed_GUI_Windows/"
UPDATE = """به‌روزرسانی Fast Sector Viewshed به نسخهٔ ۲٫۱

۱. برنامه را ببندید.
۲. فایل FastViewshed_GUI.py داخل این ZIP را در همان پوشه‌ای کپی کنید که
   Run_Fast_Viewshed.bat و پوشهٔ runtime نسخهٔ نصب‌شده قرار دارند.
۳. جایگزینی فایل قبلی را تأیید کنید؛ فایل را داخل پوشهٔ runtime نریزید.
۴. همان Run_Fast_Viewshed.bat قبلی را باز کنید.
   عنوان پنجره باید Fast Sector Viewshed 2.1 باشد.

نصب دوبارهٔ کتابخانه‌ها لازم نیست.

اصلاح: شبکه‌های بزرگ به‌طور پیش‌فرض با افزایش خودکار پیکسل تا سقف
انتخابی تحلیل می‌شوند؛ این کار جزئیات مکانی را کاهش می‌دهد و ممکن است
دیدپذیری را تغییر دهد. شعاع، آزیموت و ارتفاع‌ها تغییر نمی‌کنند.
اندازهٔ واقعی پیکسل در گزارش، فیلد cell_m و run.json ثبت می‌شود.

برای شبکهٔ گزارش‌شدهٔ ۵۷۲۵×۵۷۲۵، اگر می‌خواهید اندازهٔ پیکسل حفظ شود،
گزینهٔ «شبکهٔ بزرگ: افزایش خودکار پیکسل...» را خاموش و
«سقف شبکهٔ هر نقطه، میلیون سلول» را ۴۰ بگذارید.
این حالت به حافظهٔ بیشتر نیاز دارد؛ سقف تعداد سلول سقف مصرف RAM نیست.

برای روش پیش‌فرض تنظیم خودکار، سقف ۲۵ میلیون را نگه دارید؛ شبکه به
۴۹۹۹×۴۹۹۹ محدود می‌شود. شبکه‌های کوچک تغییری نمی‌کنند.
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
        z.writestr(PREFIX+"README.md", "# Fast Sector Viewshed 2.1\n\nRead README_FAST_FA.md for installation, update and large-grid settings.\n\nInstall Miniforge if needed, then run Install_Fast_Viewshed.bat once and Run_Fast_Viewshed.bat to open the GUI.\n\nThis is a Python/Qt source GUI package. Windows installation is not yet verified on Windows.\n")
        z.writestr(PREFIX+"UPDATE_FA.txt", UPDATE)
    full.with_suffix(".tmp").replace(full)
    patch = DIST/"FastViewshed_Update_v2.1.zip"
    with ZipFile(patch, "w", ZIP_DEFLATED) as z:
        z.write(ROOT/"FastViewshed_GUI.py", "FastViewshed_GUI.py")
        z.writestr("UPDATE_FA.txt", UPDATE)
    for path in (full, patch):
        with ZipFile(path) as z:
            assert z.testzip() is None
        print(path.name, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
