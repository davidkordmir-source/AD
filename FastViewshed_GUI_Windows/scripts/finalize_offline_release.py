"""Embed Windows checks and checksum every final downloadable binary."""
import hashlib
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED
root=Path(sys.argv[1])
archive=next(root.glob('FastViewshed_Offline_Windows_x64_v*.zip'))
with ZipFile(archive,'a',ZIP_DEFLATED) as z:
    for name in ('WINDOWS_OFFLINE_VALIDATION.json','WINDOWS_INSTALLER_VALIDATION.json'):
        if (root/name).exists():z.write(root/name,'FastViewshed_Offline_Windows_x64/'+name)
checks=[]
for path in sorted([archive,*root.glob('FastViewshed_Setup_*.exe'),*root.glob('00_FastViewshed_Windows_Setup_v*.zip')]):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    checks.append(h.hexdigest()+'  '+path.name)
    print(path.name,path.stat().st_size,h.hexdigest())
(root/'SHA256SUMS.txt').write_text('\n'.join(checks)+'\n',encoding='ascii')
