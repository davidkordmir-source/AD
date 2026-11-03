"""Package all committed project sources, resources and build tools in one ZIP."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
NAME = 'FastViewshed_Complete_Source_v3.6.2.zip'
PREFIX = 'FastViewshed_Complete_Source_v3.6.2/'


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args]).decode().strip()


def package(output, revision='HEAD'):
    commit = git('rev-parse', '--verify', revision + '^{commit}')
    timestamp = datetime.fromtimestamp(int(git('show', '-s', '--format=%ct', commit)), timezone.utc)
    stamp = tuple(timestamp.timetuple()[:6])
    output.mkdir(parents=True, exist_ok=True)
    target = output / NAME
    temporary = target.with_suffix('.zip.tmp')
    manifest = {'source_revision': commit, 'source_branch': 'fast-viewshed-gui',
                'package_version': '3.6.2', 'native_runtime_included': False,
                'excluded_paths': ['downloads/'], 'files': []}

    def write(archive, name, content, mode=0o100644):
        info = ZipInfo(PREFIX + name, date_time=stamp)
        info.create_system = 3
        info.external_attr = mode << 16
        archive.writestr(info, content, compress_type=ZIP_DEFLATED, compresslevel=9)

    try:
        with tempfile.TemporaryFile() as stream:
            subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=tar', commit],
                           stdout=stream, check=True)
            stream.seek(0)
            with tarfile.open(fileobj=stream) as source, ZipFile(temporary, 'w') as archive:
                for member in sorted(source.getmembers(), key=lambda m: m.name):
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or '..' in path.parts:
                        raise ValueError('Invalid archive path: ' + member.name)
                    if path.parts[0] == 'downloads' or member.isdir():
                        continue
                    if not member.isfile():
                        raise ValueError('Unsupported source entry: ' + member.name)
                    with source.extractfile(member) as file:
                        content = file.read()
                    write(archive, member.name, content, 0o100000 | member.mode)
                    manifest['files'].append({'path': member.name, 'bytes': len(content),
                                              'sha256': hashlib.sha256(content).hexdigest()})
                write(archive, 'SOURCE_MANIFEST.json',
                      (json.dumps(manifest, indent=2, ensure_ascii=False) + '\n').encode())
        with ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError('Source ZIP failed CRC verification.')
            for entry in manifest['files']:
                content = archive.read(PREFIX + entry['path'])
                if hashlib.sha256(content).hexdigest() != entry['sha256']:
                    raise ValueError('Source checksum mismatch: ' + entry['path'])
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    with target.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    target.with_suffix('.zip.sha256').write_text(checksum + '  ' + NAME + '\n', encoding='ascii')
    print(json.dumps({'archive': str(target), 'source_revision': commit,
                      'files': len(manifest['files']), 'bytes': target.stat().st_size,
                      'sha256': checksum}))
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--revision', default='HEAD')
    args = parser.parse_args()
    package(args.output, args.revision)
