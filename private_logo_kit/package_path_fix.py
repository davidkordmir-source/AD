"""Build the small long-path fix for the existing complete private kit."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
NAME = 'FastViewshed_Long_Path_Fix_v3.5.1.zip'
INSTRUCTIONS = '''اصلاح خطای مسیر طولانی هنگام ساخت Output در ویندوز

نیازی به دانلود مجدد بستهٔ بزرگ 3.5.0 نیست.
۱. محتویات این ZIP را داخل پوشهٔ FastViewshed_Private_Logo_Kit قبلی کپی کنید؛
   همان‌جا که Build_Custom_Setup.bat، Payload و Logo_Input قرار دارند.
۲. Apply_Path_Fix.bat را اجرا کنید و منتظر پیام Fix applied بمانید.
۳. Build_Custom_Setup.bat را دوباره اجرا کنید و تا پیام Ready صبر کنید.

لوگوی قبلی در Logo_Input باقی می‌ماند. Output و فایل‌های قبلی شما حذف نمی‌شوند.
اگر Output قبلی وجود داشته باشد، هنگام ساخت خروجی جدید با نام یکتا حفظ می‌شود.
فقط Output ساخته‌شده پس از پیام Ready را به سیستم دیگر منتقل کنید.
پوشه‌های _Build_ مربوط به اجرای ناموفق قبلی جزو خروجی قابل انتقال نیستند.

ابزار از یک حرف درایو موقت و آزاد استفاده می‌کند و در پایان آن را آزاد می‌کند.
نیازی به اجرای Administrator، تغییر رجیستری یا تغییر نام پوشهٔ شخصی شما نیست.
لوگو جایی آپلود نمی‌شود. لوگو در فایل اجرایی نهایی قرار می‌گیرد.
'''


def content(name):
    source = ROOT / name
    if source.suffix == '.bat':
        return source.read_text(encoding='utf-8').replace('\n', '\r\n').encode('utf-8')
    return source.read_bytes()


def package(output):
    output.mkdir(parents=True, exist_ok=True)
    target = output / NAME
    names = ['Build_Custom_Setup.ps1', 'Short_Paths.ps1', 'PrivateLogo.iss', 'README_FA.txt']
    manifest = {'version': '3.5.1', 'files': [
        {'path': name, 'sha256': hashlib.sha256(content(name)).hexdigest()} for name in names]}
    with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
        for name in ('Apply_Path_Fix.bat', 'Apply_Path_Fix.ps1'):
            archive.writestr(name, content(name))
        archive.writestr('PATH_FIX_README_FA.txt', INSTRUCTIONS.encode('utf-8-sig'))
        archive.writestr('Path_Fix/FIX_FILES_SHA256.json', json.dumps(manifest, indent=2))
        for name in names:
            archive.writestr('Path_Fix/Files/' + name, content(name))
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        for entry in manifest['files']:
            assert hashlib.sha256(archive.read('Path_Fix/Files/' + entry['path'])).hexdigest() == entry['sha256']
    target.with_suffix('.zip.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest() + '  ' + NAME + '\n', encoding='ascii')
    print(target)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    package(parser.parse_args().output)
