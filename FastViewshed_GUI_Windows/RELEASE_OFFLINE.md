# Fast Viewshed 3.2.1 — offline invalid-record fix

برای نصب آفلاین ۳٫۲ موجود، فقط FastViewshed_GUI.py داخل [اصلاحیهٔ کوچک](https://github.com/davidkordmir-source/AD/raw/refs/heads/fast-viewshed-gui/downloads/FastViewshed_Update_v3.2.1.zip) را کنار Run_Fast_Viewshed.bat قبلی جایگزین کنید. نصب کتابخانه لازم نیست.

رکورد نامعتبر با FID، ستون و علت در skipped_records.csv/json ثبت می‌شود؛ نقاط سالم ادامه دارند. اگر همه رد شوند، visible.shp خالی با CRS و فایل‌های جانبی ساخته می‌شود. GUI تعداد موفق و ردشده و هشدار خروجی خالی را نشان می‌دهد. نتیجهٔ ناقص رکورد خطادار از همهٔ لایه‌ها حذف می‌شود.

برای نصب تازه، ZIP کامل FastViewshed_Offline_Windows_x64_v3.2.1.zip همهٔ وابستگی‌ها را دارد؛ استخراج و Run_Fast_Viewshed.bat کافی است. نصب و اجرا دانلود ندارند. آزمون ویندوز با شبکهٔ پایتون مسدود، محاسبهٔ واقعی، GUI، رد رکورد نامعتبر و خروجی خالی را بررسی می‌کند. WINDOWS_OFFLINE_VALIDATION.json و SHA256SUMS.txt همراه انتشار هستند.
