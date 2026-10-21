# Fast Viewshed 3.2.0 — complete offline Windows x64

دانلود اصلی: **FastViewshed_Offline_Windows_x64_v3.2.0.zip**

ZIP را کامل استخراج و Run_Fast_Viewshed.bat را اجرا کنید. Python، GDAL، NumPy، Qt، DLLها و داده‌های مختصات داخل بسته هستند؛ نصب و اجرا به اینترنت، ArcGIS، Miniforge یا Python قبلی نیاز ندارند. اینترنت را می‌توانید پیش از اولین اجرا قطع کنید.

نصب‌کننده فقط فایل همراه را بررسی و استخراج می‌کند و هیچ مسیر نصب اینترنتی ندارد. داده‌های آنلاین PROJ غیرفعال‌اند. امکانات ارتفاع از ستون عددی/متنی، انتخاب نام و خروجی مستقل هر نقطه حفظ شده‌اند.

Windows build verification installs the archived runtime into a path containing spaces, blocks outbound traffic for its private python.exe and pythonw.exe with Windows Firewall, and runs native GDAL viewshed, shapefile round-trip, height-mapping regression, and the actual Qt GUI worker. See WINDOWS_OFFLINE_VALIDATION.json. SHA256SUMS.txt checks the complete download; RUNTIME_MANIFEST.json lists bundled native dependency versions and runtime size.

Target: Windows 10/11 x64. Full source and third-party licenses accompany the runtime. The older small source/update ZIPs do not contain this runtime.
