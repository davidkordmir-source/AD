"""Make a small verified updater for users who already downloaded the full kit."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
NAME = 'FastViewshed_Logo_Builder_Fix_v2.zip'
INSTRUCTIONS = '''اصلاح ابزار تشخیص لوگو، بدون دانلود دوبارهٔ بستهٔ اصلی

۱. محتویات این ZIP را در پوشهٔ استخراج‌شدهٔ بستهٔ قبلی کپی کنید؛
   همان‌جا که Build_Custom_Setup.bat و BaseSetup.exe قرار دارند.
۲. Apply_Builder_Fix.bat را یک‌بار اجرا کنید و منتظر پیام Fix applied بمانید.
۳. Build_Custom_Setup.bat را اجرا کنید. اگر لوگو خودکار پیدا نشود، پنجرهٔ
   انتخاب فایل باز می‌شود؛ لوگوی PNG خود را از هر پوشهٔ سیستم انتخاب کنید.

دیگر نام دقیق logo.png لازم نیست. اگر فقط یک PNG داخل Logo_Input باشد،
خودکار انتخاب می‌شود. می‌توانید تصویر را روی فایل BAT نیز بکشید و رها کنید.
این اصلاحیه فایل لوگوی شما را تغییر نمی‌دهد و چیزی آپلود نمی‌کند.
فایل نصب نهایی در Output/FastViewshed_With_Logo_Setup.exe ساخته می‌شود.
'''


def content(name):
    source = ROOT / name
    if source.suffix == '.bat':
        return source.read_text(encoding='utf-8').replace('\n', '\r\n').encode('utf-8')
    return source.read_bytes()


def package(output):
    output.mkdir(parents=True, exist_ok=True)
    target = output / NAME
    files = ['Build_Custom_Setup.bat', 'Build_Custom_Setup.ps1', 'README_FA.txt', 'Logo_Input/README_FA.txt']
    manifest = {'files': [{'path': name, 'sha256': hashlib.sha256(content(name)).hexdigest()} for name in files]}
    with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
        for name in ('Apply_Builder_Fix.bat', 'Apply_Builder_Fix.ps1'):
            archive.writestr(name, content(name))
        archive.writestr('FIX_README_FA.txt', INSTRUCTIONS.encode('utf-8-sig'))
        archive.writestr('Builder_Fix/FIX_FILES_SHA256.json', json.dumps(manifest, indent=2))
        for name in files:
            archive.writestr('Builder_Fix/Files/' + name, content(name))
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        for entry in manifest['files']:
            assert hashlib.sha256(archive.read('Builder_Fix/Files/' + entry['path'])).hexdigest() == entry['sha256']
    target.with_suffix('.zip.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest() + '  ' + NAME + '\n', encoding='ascii')
    print(target)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    package(parser.parse_args().output)
