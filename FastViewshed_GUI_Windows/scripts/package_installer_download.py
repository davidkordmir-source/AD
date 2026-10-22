"""Wrap the already verified Windows installer in an unmistakable Setup ZIP."""

import argparse
import hashlib
from pathlib import Path
import shutil
import urllib.request
import zipfile

INSTALLER_SHA256 = "eb282d59f589dba7396fe03f131b2f220034b09f8e6a59b7c95793b7a909cc5a"
INSTALLER_URL = (
    "https://github.com/davidkordmir-source/AD/releases/download/v3.3.0-installer/"
    "FastViewshed_Setup_v3.3.0_Windows_x64.exe"
)
ARCHIVE_NAME = "00_FastViewshed_Windows_Setup_v3.3.0.zip"

INSTRUCTIONS_FA = """نصب Fast Viewshed 3.3.0 روی ویندوز ۱۰ و ۱۱، نسخهٔ ۶۴ بیتی

۱. روی فایل ZIP راست‌کلیک کنید و Extract All را بزنید.
۲. وارد پوشهٔ استخراج‌شده شوید و فایل Setup.exe را اجرا کنید.
۳. Next و سپس Install را بزنید.
۴. گزینهٔ Create a desktop shortcut را روشن نگه دارید.
۵. پس از Finish، برنامه را از آیکون هواپیما با نام Fast Viewshed روی دسکتاپ باز کنید.

این فایل، نصب‌کنندهٔ کامل برنامه است. پایتون، GDAL، Qt و نقشهٔ آفلاین همراه آن‌اند.
نصب و اجرای برنامه هیچ دانلودی ندارند. حدود ۴ گیگابایت فضای خالی داشته باشید.
محل نصب پیش‌فرض: %LOCALAPPDATA%\\Programs\\FastViewshed
حذف برنامه: Settings > Apps > Fast Viewshed > Uninstall
"""
INSTRUCTIONS_EN = """Fast Viewshed 3.3.0 - Windows 10/11 x64 OFFLINE INSTALLER

1. Right-click the ZIP and choose Extract All.
2. Open the extracted folder and double-click Setup.exe.
3. Click Next, then Install.
4. Leave 'Create a desktop shortcut' enabled.
5. Click Finish. Open Fast Viewshed using the aircraft icon on your desktop.

This is the complete Windows installer, including Python, GDAL, Qt and map data.
No internet connection or separate Python installation is needed. Allow 4 GB free.
Default destination: %LOCALAPPDATA%\\Programs\\FastViewshed
Uninstall through Windows Settings > Apps > Fast Viewshed.
"""


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    installer = args.installer
    if installer is None:
        installer = args.output / "verified-installer.exe"
        with urllib.request.urlopen(INSTALLER_URL, timeout=90) as source:
            with installer.open("wb") as target:
                shutil.copyfileobj(source, target)
    if digest(installer) != INSTALLER_SHA256:
        raise ValueError("Installer SHA256 does not match the verified release.")
    with installer.open("rb") as source:
        if source.read(2) != b"MZ":
            raise ValueError("Installer is not a Windows executable.")
    archive = args.output / ARCHIVE_NAME
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as package:
        package.write(installer, "Setup.exe")
        package.writestr("INSTALL_FA.txt", INSTRUCTIONS_FA.encode("utf-8-sig"))
        package.writestr("INSTALL_EN.txt", INSTRUCTIONS_EN)
        package.writestr("SETUP_SHA256.txt", INSTALLER_SHA256 + "  Setup.exe\n")
    with zipfile.ZipFile(archive) as package:
        if package.testzip() is not None:
            raise ValueError("ZIP integrity check failed.")
        with package.open("Setup.exe") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != INSTALLER_SHA256:
                raise ValueError("Archived Setup.exe differs from the verified installer.")
    checksum = args.output / "WINDOWS_SETUP_ZIP_SHA256.txt"
    checksum.write_text(digest(archive) + "  " + archive.name + "\n", encoding="ascii")
    print(f"Verified installer ZIP: {archive} ({archive.stat().st_size:,} bytes)")
    print(checksum.read_text(), end="")


if __name__ == "__main__":
    main()
