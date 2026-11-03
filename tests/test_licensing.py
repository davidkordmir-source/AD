"""Signed fixtures exercise offline expiration and renewal without a signing key."""
import base64
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'FastViewshed_GUI_Windows'))
from licensing import LicenseError, LicenseGuard, verify_license

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/license_samples.json').read_text())
KEY = FIXTURE['public_key']
DEVICE = 'a' * 64
ISSUED = 2000000000


class LicensingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.now = ISSUED + 1
        self.guard = LicenseGuard(KEY, self.folder/'state', DEVICE,
                                  clock=lambda: self.now, monotonic=lambda: 0)

    def tearDown(self):
        self.temp.cleanup()

    def license_file(self, name):
        path = self.folder / (name + '.fvlicense')
        path.write_text(json.dumps(FIXTURE['licenses'][name]))
        return path

    def test_without_license_fails_closed_and_request_identifies_device_and_owner(self):
        with self.assertRaises(LicenseError):
            self.guard.check()
        self.assertEqual(self.guard.request()['device_id'], DEVICE)
        self.assertEqual(len(self.guard.request()['key_id']), 64)

    def test_ten_days_expires_at_exact_boundary_and_reimport_cannot_reset_it(self):
        path = self.license_file('ten_day')
        self.guard.activate(path)
        self.now = ISSUED + 864000 - 1
        self.assertEqual(self.guard.check()['expires_at'], ISSUED + 864000)
        self.now += 1
        with self.assertRaises(LicenseError):
            self.guard.check()
        with self.assertRaises(LicenseError):
            self.guard.activate(path)
        self.now -= 86400
        with self.assertRaises(LicenseError):
            self.guard.check()

    def test_unlimited_is_still_device_bound_and_valid_years_later(self):
        self.guard.activate(self.license_file('unlimited'))
        self.now += 100 * 365 * 86400
        self.assertIsNone(self.guard.check()['expires_at'])
        with self.assertRaises(LicenseError):
            verify_license(FIXTURE['licenses']['unlimited'], KEY, 'b'*64, self.now)

    def test_modified_duration_and_invalid_signature_or_key_are_rejected(self):
        doc = copy.deepcopy(FIXTURE['licenses']['ten_day'])
        payload = json.loads(base64.b64decode(doc['payload']))
        payload['expires_at'] = None
        doc['payload'] = base64.b64encode(json.dumps(payload).encode()).decode()
        with self.assertRaises(LicenseError):
            verify_license(doc, KEY, DEVICE, self.now)
        doc = copy.deepcopy(FIXTURE['licenses']['ten_day'])
        doc['signature'] = base64.b64encode(bytes(384)).decode()
        with self.assertRaises(LicenseError):
            verify_license(doc, KEY, DEVICE, self.now)
        key = dict(KEY, exponent='Aw==')
        with self.assertRaises(LicenseError):
            verify_license(FIXTURE['licenses']['ten_day'], key, DEVICE, self.now)

    def test_rejected_license_preserves_existing_activation(self):
        self.guard.activate(self.license_file('unlimited'))
        before = self.guard.active_path.read_bytes()
        path = self.folder/'damaged.fvlicense'
        path.write_text('{not a license')
        with self.assertRaises(LicenseError):
            self.guard.activate(path)
        self.assertEqual(self.guard.active_path.read_bytes(), before)

    def test_normal_clock_rollback_and_corrupt_clock_state_are_detected(self):
        self.guard.activate(self.license_file('ten_day'))
        self.now += 3600
        self.guard.check()
        self.now -= 1800
        with self.assertRaises(LicenseError):
            self.guard.check()
        self.guard.state_path.write_bytes(b'damaged state')
        with self.assertRaises(LicenseError):
            self.guard.check()

    def test_renewal_after_expiration_accepts_new_valid_license(self):
        self.guard.activate(self.license_file('ten_day'))
        self.now += 864000
        with self.assertRaises(LicenseError):
            self.guard.check()
        self.guard.activate(self.license_file('unlimited'))
        self.assertIsNone(self.guard.check()['expires_at'])

    def test_running_session_cannot_extend_expiry_by_rolling_clock_back(self):
        elapsed = [0]
        guard = LicenseGuard(KEY, self.folder/'other', DEVICE,
                             clock=lambda: self.now, monotonic=lambda: elapsed[0])
        guard.activate(self.license_file('ten_day'))
        elapsed[0] = 864001
        with self.assertRaises(LicenseError):
            guard.check()


if __name__ == '__main__':
    unittest.main()
