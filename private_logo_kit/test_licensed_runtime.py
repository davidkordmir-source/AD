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
    from licensing import LICENSING_REQUIRED, LicenseGuard, LicenseError, verify_license, canonical, protect, atomic_write
    from license_clock import boot_clock
    assert LICENSING_REQUIRED
    assert boot_clock() is not None, 'Windows boot identity and sleep-aware uptime unavailable.'
    guard = LicenseGuard()
    assert guard.macs, 'The Windows runner Ethernet MAC was not enumerated.'
    try:
        guard.check()
    except LicenseError:
        pass
    else:
        raise AssertionError('Fresh private build started with an existing activation.')
    # Simulate the older protected format to prove migration keeps existing keys.
    legacy = protect(canonical(dict(device_id=guard.device, key_id=guard.key_id, last_seen=int(time.time())-5)))
    atomic_write(guard.state_path, legacy)
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, guard.registry_path) as key:
        winreg.SetValueEx(key, 'Clock', 0, winreg.REG_BINARY, legacy)

    def gui(name, expected):
        report = args.output / name
        result = subprocess.run([str(args.app/'FastViewshed.exe'), '--smoke-test', str(report)], timeout=60)
        assert result.returncode == expected, (name, result.returncode)
        return json.loads(report.read_text())

    # Cancelling activation is a clean exit, without the launcher's error box.
    blocked = gui('GUI_WITHOUT_LICENSE.json', 0)
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
    assert payload['expires_at']-payload['activated_at'] == 864000
    assert payload['version'] == 2 and payload['duration_days'] == 10
    doc = json.loads(ten.read_text())
    signed = json.loads(base64.b64decode(doc['payload']))
    assert 'issued_at' not in signed and 'expires_at' not in signed
    try:
        verify_license(doc, guard.key, '0'*64, time.time(), guard.macs)
    except LicenseError:
        pass
    else:
        raise AssertionError('License was accepted on another device.')
    with tempfile.TemporaryDirectory() as folder:
        clock = [time.time()]
        temporary = LicenseGuard(guard.key, Path(folder), guard.device, clock=lambda: clock[0], monotonic=lambda: 0, macs=guard.macs)
        activated = temporary.activate(ten)
        clock[0] += 3 * 86400
        restarted = LicenseGuard(guard.key, Path(folder), guard.device, clock=lambda: clock[0], monotonic=lambda: 0, macs=guard.macs)
        assert restarted.activate(ten)['activated_at'] == activated['activated_at']
        clock[0] = activated['expires_at']
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
    content['duration_days'] = None
    changed['payload'] = base64.b64encode(json.dumps(content).encode()).decode()
    try:
        verify_license(changed, guard.key, guard.device, time.time(), guard.macs)
    except LicenseError:
        pass
    else:
        raise AssertionError('Modified license duration was accepted.')
    for offset in (-20*365*86400, 20*365*86400):
        with tempfile.TemporaryDirectory() as folder:
            date = int(time.time()) + offset
            skewed = LicenseGuard(guard.key, Path(folder), guard.device, clock=lambda: date, monotonic=lambda: 0, macs=guard.macs)
            first = skewed.activate(ten)
            assert first['expires_at'] - first['activated_at'] == 864000
    if guard.macs:
        try:
            verify_license(doc, guard.key, guard.device, time.time(), ['0'*64])
        except LicenseError:
            pass
        else:
            raise AssertionError('License accepted a different MAC address.')
    unlimited = issue('unlimited.fvlicense', '-Unlimited')
    assert guard.activate(unlimited)['expires_at'] is None
    assert guard.check()['expires_at'] is None
    with tempfile.TemporaryDirectory() as folder:
        wall, ticks, boot = [time.time()], [10000], ['native-test-boot-one']
        def test_guard():
            return LicenseGuard(guard.key, Path(folder), guard.device, clock=lambda: wall[0],
                                monotonic=lambda: ticks[0], macs=guard.macs,
                                boot_source=lambda: (boot[0], ticks[0]))
        timer_guard = test_guard()
        activated = timer_guard.activate(ten)
        wall[0] -= 6*3600
        ticks[0] += 3600
        corrected = test_guard().check()
        assert abs(corrected['display_expires_at']-wall[0]-(864000-3600)) < 1.1
        assert corrected['activated_at'] == activated['activated_at']
        ticks[0] += 864000
        try:
            test_guard().check()
        except LicenseError as exc:
            assert exc.code == 'expired'
        else:
            raise AssertionError('Calendar correction extended a timed license.')
        # Unlimited licenses keep hardware/signature checks but have no clock expiry.
        unbounded = test_guard().activate(unlimited)
        boot[0], ticks[0] = 'native-test-boot-two', 10
        wall[0] -= 10*365*86400
        assert test_guard().check()['expires_at'] is None
    with tempfile.TemporaryDirectory() as folder:
        wall, ticks = [time.time()], [1000]
        migration = LicenseGuard(guard.key, Path(folder), guard.device, clock=lambda: wall[0],
                                 monotonic=lambda: ticks[0], macs=guard.macs,
                                 boot_source=lambda: ('migration-boot', ticks[0]))
        original = migration.activate(ten)
        old_record = dict(device_id=guard.device, key_id=guard.key_id,
                          last_seen=original['activated_at']+2*86400,
                          activations=migration.state()['activations'])
        atomic_write(migration.state_path, protect(canonical(old_record)))
        wall[0] -= 5*86400
        repaired = migration.check()
        assert abs(repaired['display_expires_at']-wall[0]-8*86400) < 1.1
        assert repaired['activated_at'] == original['activated_at']
    owner_gui_path = args.output/'OWNER_GUI_SMOKE.json'
    owner_gui = subprocess.run([powershell, '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', str(args.owner),
                                '-DataDirectory', str(args.owner_data), '-SmokeReport', str(owner_gui_path)],
                               capture_output=True, text=True, timeout=60)
    assert owner_gui.returncode == 0, owner_gui.stdout + owner_gui.stderr
    issuer_ui = json.loads(owner_gui_path.read_text())
    assert issuer_ui['form_visible'] and issuer_ui['default_days'] == 10 and issuer_ui['unlimited_disables_days']
    # Recover the DPAPI-protected high-water record from its registry mirror.
    guard.state_path.unlink()
    guard.check()
    assert guard.state_path.is_file()
    assert payload['license_id'] in guard.state()['activations']
    assert len(guard.state()['activations']) == 2
    active = gui('LICENSED_GUI_SMOKE.json', 0)
    assert active['license_required'] and active['license_active'] and active['gui_visible']
    assert active['country_labels'] >= 200 and active['visible_country_labels'] > 0 and active['professional_theme']
    report = dict(status='passed', embedded_public_key=True, signed_ten_day_license=True,
                  unlimited_license=True, missing_license_blocks_gui=True, wrong_device_rejected=True,
                  wrong_owner_request_rejected=True, modified_duration_rejected=True,
                  expiry_and_reimport_rejected=True, fallback_clock_rollback_rejected=True,
                  dpapi_registry_mirror_recovered=True, activation_history_recovered=True,
                  issuer_clock_not_in_license=True, full_days_from_first_activation=True, legacy_clock_record_migrated=True,
                  restart_and_reimport_preserve_start=True, recipient_dates_20_years_apart=True,
                  mac_identifiers_checked=bool(guard.macs), owner_issuer_gui=issuer_ui, renewed_gui=active)
    report.update(windows_boot_clock=True, backward_ntp_correction_accepted=True,
                  correction_does_not_extend_duration=True, unlimited_not_time_blocked=True,
                  future_legacy_clock_migrated_without_reset=True)
    (args.output/'LICENSE_VALIDATION_v3.6.2.json').write_text(json.dumps(report, indent=2))
    print('PASS: real Windows issuer, DPAPI, signed duration, binding, expiry, renewal and licensed GUI.')


if __name__ == '__main__':
    main()
