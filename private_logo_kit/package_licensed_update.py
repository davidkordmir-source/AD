"""Small verified 3.6 upgrade; reuse the existing compiler and native runtime."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
ROOT = Path(__file__).resolve().parent
NAME = 'FastViewshed_Licensed_Update_v3.6.1.zip'
FILES = ['Build_Custom_Setup.ps1', 'Embed_Logo.ps1', 'PrivateLogo.iss', 'Short_Paths.ps1', 'README_FA.txt', 'OUTPUT_README_FA.txt', 'LICENSE_GUIDE_FA.md', 'License_Owner/Owner_Licensing.ps1', 'License_Owner/Issue_License.bat', 'Payload/FastViewshed_GUI.py', 'Payload/FastViewshed_GUI_COPY.txt', 'Payload/desktop_customization.py', 'Payload/professional_ui.py', 'Payload/app_resources.py', 'Payload/licensing.py', 'Payload/license_dialog.py', 'Payload/device_identity.py', 'Payload/scripts/check_offline.py']

def content(name):
    path = ROOT.parent / 'FastViewshed_GUI_Windows' / name[len('Payload/'):] if name.startswith('Payload/') else ROOT / name
    if path.suffix == '.bat':
        return path.read_text(encoding='utf-8').replace('\n','\r\n').encode('utf-8')
    return path.read_bytes()

def package(output):
    output.mkdir(parents=True,exist_ok=True)
    target=output/NAME
    manifest={'version':'3.6.1','files':[{'path':n,'sha256':hashlib.sha256(content(n)).hexdigest()} for n in FILES]}
    with ZipFile(target,'w',ZIP_DEFLATED) as z:
        for n in ['Apply_3_6_Update.bat','Apply_3_6_Update.ps1']:
            z.writestr(n,content(n))
        z.writestr('UPDATE_3_6_README_FA.md',content('UPDATE_3_6_README_FA.md'))
        z.writestr('Update_3_6/FIX_FILES_SHA256.json',json.dumps(manifest,indent=2))
        for n in FILES:z.writestr('Update_3_6/Files/'+n,content(n))
    with ZipFile(target) as z:
        assert z.testzip() is None
        for e in manifest['files']:
            assert hashlib.sha256(z.read('Update_3_6/Files/'+e['path'])).hexdigest()==e['sha256']
    target.with_suffix('.zip.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest()+'  '+NAME+'\n',encoding='ascii')
    print(target)
    return target

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    package(p.parse_args().output)
