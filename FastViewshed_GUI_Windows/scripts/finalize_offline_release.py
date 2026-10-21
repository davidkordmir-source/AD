"""Embed the actual Windows firewall test report, then checksum final bytes."""
import hashlib
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED
root=Path(sys.argv[1])
archive=next(root.glob('FastViewshed_Offline_Windows_x64_v*.zip'))
with ZipFile(archive,'a',ZIP_DEFLATED) as z:
    z.write(root/'WINDOWS_OFFLINE_VALIDATION.json','FastViewshed_Offline_Windows_x64/WINDOWS_OFFLINE_VALIDATION.json')
h=hashlib.sha256()
with archive.open('rb') as f:
    for block in iter(lambda:f.read(8*1024*1024),b''):
        h.update(block)
(root/'SHA256SUMS.txt').write_text(h.hexdigest()+'  '+archive.name+'\n',encoding='ascii')
print(archive.name,archive.stat().st_size,h.hexdigest())
