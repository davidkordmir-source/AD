"""Package complete pinned runtime data and current app code for local private builds."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

OFFLINE_SHA256 = '07640d806a43a961b7134a661854cbba85317896ff4b3a707ab1b3242e25a404'
ARCHIVE_NAME = 'FastViewshed_Complete_Private_Kit_v3.5.1.zip'
PREFIX = 'FastViewshed_Private_Logo_Kit/'
ROOT = Path(__file__).resolve().parent.parent


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def package(offline_archive, compiler, output):
    if digest(offline_archive) != OFFLINE_SHA256:
        raise ValueError('Offline runtime ZIP SHA256 does not match the verified release.')
    if not (compiler / 'ISCC.exe').is_file():
        raise ValueError('The complete Inno Setup compiler folder is required.')
    output.mkdir(parents=True, exist_ok=True)
    target = output / ARCHIVE_NAME
    with tempfile.TemporaryDirectory(prefix='fv-private-payload-') as temporary:
        unpacked = Path(temporary)
        with zipfile.ZipFile(offline_archive) as archive:
            for item in archive.infolist():
                path = (unpacked / item.filename).resolve()
                if not path.is_relative_to(unpacked.resolve()):
                    raise ValueError('Invalid path in the pinned runtime ZIP.')
            archive.extractall(unpacked)
        payload = unpacked / 'FastViewshed_Offline_Windows_x64'
        if not (payload / 'runtime_win64.zip').is_file():
            raise ValueError('The complete offline runtime payload is missing.')
        app = ROOT / 'FastViewshed_GUI_Windows'
        replacements = ['FastViewshed_GUI.py', 'FastViewshed_GUI_COPY.txt', 'desktop_customization.py',
                        'Check_Offline.bat', '_Finalize_Offline.bat', 'README_FAST_FA.md',
                        'scripts/install_offline.ps1', 'scripts/check_offline.py', 'scripts/verify_runtime.py']
        for name in replacements:
            destination = payload / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = app / name
            if source.suffix == '.bat':
                destination.write_bytes(source.read_text(encoding='utf-8').replace('\n', '\r\n').encode('utf-8'))
            else:
                destination.write_bytes(source.read_bytes())
        for old in payload.glob('WINDOWS_*VALIDATION.json'):
            old.unlink()
        runtime_manifest = json.loads((payload / 'RUNTIME_MANIFEST.json').read_text(encoding='utf-8-sig'))
        if digest(payload / 'runtime_win64.zip') != runtime_manifest['sha256']:
            raise ValueError('The embedded runtime archive checksum does not match its manifest.')
        runtime_manifest['version'] = '3.5.0'
        (payload / 'RUNTIME_MANIFEST.json').write_text(json.dumps(runtime_manifest, indent=2), encoding='utf-8')
        files = {'Payload/' + source.relative_to(payload).as_posix(): source
                 for source in payload.rglob('*') if source.is_file()}
        for name in ['Build_Custom_Setup.bat', 'Build_Custom_Setup.ps1', 'PrivateLogo.iss',
                     'Embed_Logo.ps1', 'Short_Paths.ps1', 'OUTPUT_README_FA.txt', 'README_FA.txt', 'Logo_Input/README_FA.txt']:
            files[name] = ROOT / 'private_logo_kit' / name
        files['FastViewshedLauncher.cs'] = app / 'installer/FastViewshedLauncher.cs'
        for source in sorted(compiler.rglob('*')):
            if source.is_file() and not source.name.lower().startswith('unins'):
                files['Toolchain/' + source.relative_to(compiler).as_posix()] = source
        if not any('license' in name.lower() for name in files if name.startswith('Toolchain/')):
            raise ValueError('The compiler license must be included.')
        manifest = {'version': '3.5.1', 'files': []}
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            archive.mkdir(PREFIX)
            archive.mkdir(PREFIX + 'Logo_Input/')
            archive.mkdir(PREFIX + 'Output/')
            for name, source in sorted(files.items()):
                if source.suffix == '.bat':
                    content = source.read_text(encoding='utf-8').replace('\n', '\r\n').encode('utf-8')
                    archive.writestr(PREFIX + name, content)
                    checksum = hashlib.sha256(content).hexdigest()
                else:
                    archive.write(source, PREFIX + name,
                                  compress_type=zipfile.ZIP_STORED if name.endswith('runtime_win64.zip') else zipfile.ZIP_DEFLATED)
                    checksum = digest(source)
                manifest['files'].append({'path': name, 'sha256': checksum})
            archive.writestr(PREFIX + 'KIT_FILES_SHA256.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError('Kit ZIP integrity verification failed.')
        if any(name.lower().endswith('.png') for name in archive.namelist() if '/Logo_Input/' in name):
            raise ValueError('The public kit must not include a private input logo.')
        for item in manifest['files']:
            with archive.open(PREFIX + item['path']) as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != item['sha256']:
                    raise ValueError('Archived kit checksum mismatch: ' + item['path'])
    target.with_suffix('.zip.sha256').write_text(digest(target) + '  ' + ARCHIVE_NAME + '\n', encoding='ascii')
    print('Verified complete private kit:', target)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline-archive', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package(args.offline_archive, args.compiler, args.output)
