"""Signed durations start on the recipient and survive reimport and renewal."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'FastViewshed_GUI_Windows'))
from licensing import LicenseGuard, LicenseError, canonical, protect

SAMPLES = json.loads((Path(__file__).parent/'fixtures/activation_license_samples.json').read_text())
KEY = SAMPLES['public_key']


class ActivationDurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = 1800000000
        self.guard = self.new_guard()

    def tearDown(self):
        self.temp.cleanup()

    def new_guard(self, **extra):
        return LicenseGuard(KEY, self.root/'state', 'a'*64, clock=lambda: self.now,
                            monotonic=lambda: 0, macs=extra.get('macs', ['b'*64]))

    def license(self, name='ten_day'):
        path = self.root/(name+'.fvlicense')
        path.write_text(json.dumps(SAMPLES['licenses'][name]))
        return path

    def test_same_signed_file_starts_full_ten_days_on_any_first_activation_date(self):
        for now in [1000000000, 1800000000, 2500000000]:
            with self.subTest(recipient_date=now), tempfile.TemporaryDirectory() as folder:
                guard = LicenseGuard(KEY, Path(folder), 'a'*64, clock=lambda: now,
                                     monotonic=lambda: 0, macs=['b'*64])
                result = guard.activate(self.license())
                self.assertEqual(result['activated_at'], now)
                self.assertEqual(result['expires_at'], now+864000)
                claims = json.loads(base64.b64decode(SAMPLES['licenses']['ten_day']['payload']))
                self.assertNotIn('issued_at', claims)
                self.assertNotIn('expires_at', claims)

    def test_reimport_and_process_restart_preserve_the_first_activation(self):
        original = self.guard.activate(self.license())
        self.now += 3*86400
        restarted = self.new_guard()
        self.assertEqual(restarted.check()['expires_at'], original['expires_at'])
        self.assertEqual(restarted.activate(self.license())['activated_at'], original['activated_at'])
        self.now = original['expires_at']
        with self.assertRaises(LicenseError):
            restarted.check()
        with self.assertRaises(LicenseError):
            restarted.activate(self.license())

    def test_renewal_starts_new_days_but_old_file_cannot_be_restarted(self):
        original = self.guard.activate(self.license())
        self.now = original['expires_at']
        renewed = self.guard.activate(self.license('renewal'))
        self.assertEqual(renewed['expires_at'], self.now+864000)
        with self.assertRaises(LicenseError):
            self.guard.activate(self.license())
        self.assertEqual(self.guard.check()['license_id'], renewed['license_id'])
        self.assertEqual(len(self.guard.state()['activations']), 2)

    def test_unlimited_has_activation_record_without_a_deadline(self):
        value = self.guard.activate(self.license('unlimited'))
        self.assertIsNone(value['expires_at'])
        self.now += 100*365*86400
        self.assertIsNone(self.new_guard().check()['expires_at'])

    def test_correct_windows_identity_with_different_mac_is_rejected(self):
        for macs in [[], ['c'*64]]:
            with self.assertRaises(LicenseError):
                self.new_guard(macs=macs).activate(self.license())
        self.assertFalse(self.guard.active_path.exists())

    def test_wrong_device_and_modified_signed_duration_are_rejected(self):
        other = LicenseGuard(KEY, self.root/'other', 'd'*64, clock=lambda: self.now,
                             monotonic=lambda: 0, macs=['b'*64])
        with self.assertRaises(LicenseError):
            other.activate(self.license())
        document = dict(SAMPLES['licenses']['ten_day'])
        claims = json.loads(base64.b64decode(document['payload']))
        claims['duration_days'] = None
        document['payload'] = base64.b64encode(canonical(claims)).decode()
        damaged = self.root/'changed.fvlicense'
        damaged.write_text(json.dumps(document))
        with self.assertRaises(LicenseError):
            self.guard.activate(damaged)

    def test_clock_rollback_after_expiry_does_not_restore_validity(self):
        result = self.guard.activate(self.license())
        self.now = result['expires_at']
        with self.assertRaises(LicenseError):
            self.guard.check()
        self.now -= 86400
        with self.assertRaises(LicenseError):
            self.new_guard().activate(self.license())

    def test_legacy_clock_record_is_migrated_without_losing_high_water(self):
        self.guard.folder.mkdir(parents=True)
        old = dict(device_id=self.guard.device, key_id=self.guard.key_id, last_seen=self.now-5)
        self.guard.state_path.write_bytes(protect(canonical(old)))
        self.guard.activate(self.license())
        self.assertEqual(len(self.guard.state()['activations']), 1)
        self.assertEqual(self.guard.state()['last_seen'], self.now)

    def test_missing_history_on_check_does_not_silently_restart_active_license(self):
        self.guard.activate(self.license())
        self.guard.state_path.unlink()
        with self.assertRaises(LicenseError):
            self.guard.check()

    def test_parallel_activations_keep_both_license_histories(self):
        files = [self.license(), self.license('renewal')]
        errors = []
        def activate(path):
            try:
                self.new_guard().activate(path)
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=activate, args=(p,)) for p in files]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertFalse(errors)
        self.assertEqual(len(self.guard.state()['activations']), 2)


if __name__ == '__main__':
    unittest.main()
