"""Use the real owner issuer, embedded key, DPAPI and GUI on Windows."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    for name in ('app', 'owner', 'owner-data', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.app))
    from licensing import LICENSING_REQUIRED, LicenseGuard, LicenseError, verify_license
    assert LICENSING_REQUIRED
    guard = LicenseGuard()
    try:
        guard.check()
    except LicenseError:
        pass
    else:
        raise AssertionError('Fresh private build started with an existing activation.')

    def gui(name, expected):
        report = args.output / name
        result = subprocess.run([str(args.app/'FastViewshed.exe'), '--smoke-test', str(report)], timeout=60)
        assert result.returncode == expected, (name, result.returncode)
        return json.loads(report.read_text())

    blocked = gui('GUI_WITHOUT_LICENSE.json', 2)
    assert blocked['status'] == 'license_required' and not blocked['gui_visible']
    request = args.output/'synthetic.fvrequest'
    request.write_text(json.dumps(guard.request()))
    powershell = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'

    def issue(name, *options, request_file=request, expected=0):
        target = args.output/name
        command = [powershell, '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', str(args.owner),
                   '-DataDirectory', str(args.owner_data), '-RequestFile', str(request_file),
                   '-Customer', 'Synthetic Windows customer', '-OutputFile', str(target), *options]
        result = subprocess.run(command, capture_output=True, text=True)
        with (args.output/'LICENSE_ISSUER.log').open('a', encoding='utf-8') as out:
            out.write(result.stdout + result.stderr)
        assert result.returncode == expected, result.stdout + result.stderr
        return target

    wrong_request = args.output/'wrong-owner.fvrequest'
    wrong_request.write_text(json.dumps({**guard.request(), 'key_id': '0'*64}))
    issue('should-not-exist.fvlicense', request_file=wrong_request, expected=1)
    assert not (args.output/'should-not-exist.fvlicense').exists()
    ten = issue('ten-day.fvlicense', '-Days', '10')
    payload = guard.activate(ten)
    assert payload['expires_at']-payload['issued_at'] == 864000
    doc = json.loads(ten.read_text())
    try:
        verify_license(doc, guard.key, '0'*64, time.time())
    except LicenseError:
        pass
    else:
        raise AssertionError('License was accepted on another device.')
    with tempfile.TemporaryDirectory() as folder:
        clock = [time.time()]
        temporary = LicenseGuard(guard.key, Path(folder), guard.device, clock=lambda: clock[0], monotonic=lambda: 0)
        temporary.activate(ten)
        clock[0] = payload['expires_at']
        for operation in (temporary.check, lambda: temporary.activate(ten)):
            try:
                operation()
            except LicenseError:
                pass
            else:
                raise AssertionError('Expired license or expired reimport was accepted.')
        clock[0] -= 86400
        try:
            temporary.check()
        except LicenseError:
            pass
        else:
            raise AssertionError('Clock rollback was accepted.')
    changed = dict(doc)
    content = json.loads(base64.b64decode(doc['payload']))
    content['expires_at'] = None
    changed['payload'] = base64.b64encode(json.dumps(content).encode()).decode()
    try:
        verify_license(changed, guard.key, guard.device, time.time())
    except LicenseError:
        pass
    else:
        raise AssertionError('Modified license duration was accepted.')
    unlimited = issue('unlimited.fvlicense', '-Unlimited')
    assert guard.activate(unlimited)['expires_at'] is None
    assert guard.check()['expires_at'] is None
    # Recover the DPAPI-protected high-water record from its registry mirror.
    guard.state_path.unlink()
    guard.check()
    assert guard.state_path.is_file()
    active = gui('LICENSED_GUI_SMOKE.json', 0)
    assert active['license_required'] and active['license_active'] and active['gui_visible']
    assert active['country_labels'] >= 200 and active['visible_country_labels'] > 0 and active['professional_theme']
    report = dict(status='passed', embedded_public_key=True, signed_ten_day_license=True,
                  unlimited_license=True, missing_license_blocks_gui=True, wrong_device_rejected=True,
                  wrong_owner_request_rejected=True, modified_duration_rejected=True,
                  expiry_and_reimport_rejected=True, normal_clock_rollback_rejected=True,
                  dpapi_registry_mirror_recovered=True, renewed_gui=active)
    (args.output/'LICENSE_VALIDATION_v3.6.0.json').write_text(json.dumps(report, indent=2))
    print('PASS: real Windows issuer, DPAPI, signed duration, binding, expiry, renewal and licensed GUI.')


if __name__ == '__main__':
    main()
