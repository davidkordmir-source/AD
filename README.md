# برنامهٔ GUI دیدپذیری قطاعی — نسخهٔ ۲٫۱

[**دریافت بستهٔ کامل ویندوز (ZIP)**](https://github.com/davidkordmir-source/AD/raw/refs/heads/fast-viewshed-gui/downloads/FastViewshed_GUI_Windows.zip)

[**دریافت اصلاحیهٔ ۲٫۱ برای نصب قبلی (فقط ۱۶ کیلوبایت)**](https://github.com/davidkordmir-source/AD/raw/refs/heads/fast-viewshed-gui/downloads/FastViewshed_Update_v2.1.zip)

برای به‌روزرسانی، برنامه را ببندید و فقط `FastViewshed_GUI.py` داخل اصلاحیه را کنار همان `Run_Fast_Viewshed.bat` قبلی جایگزین کنید. نصب دوبارهٔ کتابخانه‌ها لازم نیست. عنوان پنجره باید **Fast Sector Viewshed 2.1** باشد.

خطای شبکهٔ بیش از ۲۵ میلیون سلول اصلاح شده است: تنظیم خودکار روشن، در صورت نیاز پیکسل را درشت‌تر می‌کند و جزئیات را کاهش می‌دهد. برای حفظ اندازهٔ پیکسل شبکهٔ گزارش‌شدهٔ ۵۷۲۵×۵۷۲۵، تنظیم خودکار را خاموش و سقف شبکه را ۴۰ میلیون بگذارید؛ RAM بیشتری لازم است. هر دو حالت روی دادهٔ مصنوعی با همین اندازهٔ شبکه و خروجی Shapefile آزموده شده‌اند.

بسته در شاخهٔ `fast-viewshed-gui` و پوشهٔ `downloads` قرار دارد. در صفحهٔ فایل ZIP، دکمهٔ **Download raw file** نیز آن را دریافت می‌کند.

۱. فایل ZIP را کاملاً استخراج کنید.
۲. اگر Miniforge یا Miniconda ندارید، [Miniforge ویندوز x86-64](https://github.com/conda-forge/miniforge/releases) را نصب کنید.
۳. ابتدا `Install_Fast_Viewshed.bat` را اجرا کنید؛ نصب وابستگی‌ها به اینترنت نیاز دارد.
۴. پس از نصب موفق، `Run_Fast_Viewshed.bat` را اجرا کنید تا پنجرهٔ GUI باز شود.

[راهنمای کامل فارسی](FastViewshed_GUI_Windows/README_FAST_FA.md) · [کد برنامه](FastViewshed_GUI_Windows/FastViewshed_GUI.py) · [تصویر پنجره](FastViewshed_GUI_Windows/GUI.png)

برنامه مستقل از ArcGIS Pro است و ورودی و خروجی Shapefile دارد. نصب‌کنندهٔ ویندوز در محیط ویندوز آزمایش نشده است؛ موتور و GUI در محیط توسعه بررسی شده‌اند. تطابق کامل نتایج با Global Mapper تضمین نشده است.
