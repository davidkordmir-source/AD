"""Package a verified base Setup and a local compiler; never include a user logo."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

BASE_SHA256 = '3cbda5270181774d6d13dca8409f1c3e9de4a0aa53aa878c408f2e97394dc3ab'
ARCHIVE_NAME = 'FastViewshed_Private_Logo_Kit_v3.4.0.zip'
PREFIX = 'FastViewshed_Private_Logo_Kit/'
ROOT = Path(__file__).resolve().parent.parent


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def package(base, compiler, output):
    if digest(base) != BASE_SHA256:
        raise ValueError('Base installer SHA256 does not match the verified 3.4 release.')
    with base.open('rb') as source:
        if source.read(2) != b'MZ':
            raise ValueError('The base installer is not a Windows executable.')
    if not (compiler / 'ISCC.exe').is_file():
        raise ValueError('The complete Inno Setup compiler folder is required.')
    # Preserve the compiler distribution and its licenses. Exclude only the
    # host machine's uninstaller; it is not part of the compiler toolchain.
    files = {'BaseSetup.exe': base}
    for source in sorted(compiler.rglob('*')):
        if source.is_file() and not source.name.lower().startswith('unins'):
            files['Toolchain/' + source.relative_to(compiler).as_posix()] = source
    for name in ('Build_Custom_Setup.bat', 'Build_Custom_Setup.ps1',
                 'PrivateLogo.iss', '_Verify_Branding.bat', 'README_FA.txt',
                 'Logo_Input/README_FA.txt'):
        files[name] = ROOT / 'private_logo_kit' / name
    app = ROOT / 'FastViewshed_GUI_Windows'
    files.update({'desktop_customization.py': app / 'desktop_customization.py',
                  'check_offline.py': app / 'scripts/check_offline.py',
                  'aircraft.ico': app / 'assets/aircraft.ico'})
    if not any('license' in name.lower() for name in files if name.startswith('Toolchain/')):
        raise ValueError('The compiler license must be included.')
    manifest = {'files': [{'path': name, 'sha256': digest(source)} for name, source in sorted(files.items())]}
    output.mkdir(parents=True, exist_ok=True)
    target = output / ARCHIVE_NAME
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        archive.mkdir(PREFIX)
        archive.mkdir(PREFIX + 'Logo_Input/')
        archive.mkdir(PREFIX + 'Output/')
        for name, source in files.items():
            if source.suffix.lower() == '.bat':
                # Windows cmd.exe requires normal CRLF command lines.
                content = source.read_text(encoding='utf-8').replace('\n', '\r\n')
                archive.writestr(PREFIX + name, content)
                # Hash the exact packaged bytes, not the source's LF form.
                for entry in manifest['files']:
                    if entry['path'] == name:
                        entry['sha256'] = hashlib.sha256(content.encode('utf-8')).hexdigest()
            else:
                archive.write(source, PREFIX + name,
                              compress_type=zipfile.ZIP_STORED if name == 'BaseSetup.exe' else zipfile.ZIP_DEFLATED)
        archive.writestr(PREFIX + 'KIT_FILES_SHA256.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError('Kit ZIP integrity verification failed.')
        if PREFIX + 'Logo_Input/logo.png' in archive.namelist():
            raise ValueError('The public kit must never contain a private logo.')
        for entry in manifest['files']:
            with archive.open(PREFIX + entry['path']) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
                    raise ValueError('Archived kit file checksum mismatch: ' + entry['path'])
    target.with_suffix('.zip.sha256').write_text(digest(target) + '  ' + target.name + '\n', encoding='ascii')
    print('Verified private logo kit:', target)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-setup', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package(args.base_setup, args.compiler, args.output)
