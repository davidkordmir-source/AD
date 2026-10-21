"""Build the complete Windows x64 offline distribution on Windows.

The build machine downloads dependencies; the recipient only extracts local
files. Native packages, Python, Qt plugins, GDAL/PROJ data and licenses ship
inside a relocatable conda-pack payload. No pip/conda is run at the destination.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

VERSION = '3.2.1'
BUNDLE = 'FastViewshed_Offline_Windows_x64'
ROOT = Path(__file__).resolve().parent.parent


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise RuntimeError('Build with native Windows x64 dependencies on Windows.')
    import conda_pack
    runtime = Path(args.runtime).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    stage = output/'stage'/BUNDLE
    stage.mkdir(parents=True, exist_ok=True)
    files = ['FastViewshed_GUI.py', 'FastViewshed_GUI_COPY.txt', 'Run_Fast_Viewshed.bat',
             'Install_Fast_Viewshed.bat', 'Check_Offline.bat', '_Activate_Offline.bat',
             '_Finalize_Offline.bat', 'README_FAST_FA.md', 'environment-fast.yml',
             'scripts/install_offline.ps1', 'scripts/check_offline.py']
    for relative in files:
        target = stage/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/relative, target)
    shutil.copytree(ROOT/'demo_fast', stage/'demo_fast', dirs_exist_ok=True)
    packages = []
    license_root = stage/'THIRD_PARTY_LICENSES'
    for record in sorted((runtime/'conda-meta').glob('*.json')):
        info = json.loads(record.read_text(encoding='utf-8'))
        packages.append({key: info.get(key) for key in ('name', 'version', 'build', 'sha256', 'license', 'channel')})
        source = Path(info.get('link', {}).get('source', ''))
        licenses = source/'info'/'licenses'
        if licenses.is_dir():
            shutil.copytree(licenses, license_root/info['name'], dirs_exist_ok=True)
    # conda-pack's generated relocation scripts use its BSD license.
    tools_root = Path(sys.prefix)
    for candidate in tools_root.glob('Lib/site-packages/conda_pack-*.dist-info/licenses'):
        shutil.copytree(candidate, license_root/'conda-pack', dirs_exist_ok=True)
    (stage/'DEPENDENCIES.json').write_text(json.dumps(packages, indent=2), encoding='utf-8')
    archive = stage/'runtime_win64.zip'
    conda_pack.pack(prefix=str(runtime), output=str(archive), format='zip', force=True, verbose=True)
    with ZipFile(archive) as z:
        required = ['python.exe', 'pythonw.exe', 'Scripts/activate.bat', 'Scripts/conda-unpack-script.py',
                    'Library/share/proj/proj.db', 'Lib/site-packages/osgeo/gdal.py']
        for name in required:
            if name not in z.namelist():
                raise RuntimeError('Missing native runtime component: '+name)
        unpacked = sum(f.file_size for f in z.infolist())
    manifest = dict(version=VERSION, platform='win-64', runtime_archive=archive.name,
                    sha256=digest(archive), compressed_bytes=archive.stat().st_size,
                    uncompressed_bytes=unpacked, source_revision=args.revision,
                    dependencies=packages, internet_required=False)
    (stage/'RUNTIME_MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    destination = output/f'{BUNDLE}_v{VERSION}.zip'
    with ZipFile(destination, 'w', ZIP_DEFLATED) as z:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                z.write(path, str(path.relative_to(stage.parent)),
                        compress_type=ZIP_STORED if path == archive else ZIP_DEFLATED)
    shutil.copy2(stage/'RUNTIME_MANIFEST.json', output/'RUNTIME_MANIFEST.json')
    print(json.dumps(dict(archive=str(destination), bytes=destination.stat().st_size)))


if __name__ == '__main__':
    main()
