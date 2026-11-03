"""Calendar corrections do not block valid licenses or restart their duration."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'FastViewshed_GUI_Windows'))
from licensing import LicenseGuard, LicenseError, canonical, protect
from license_dialog import license_summary

FIXTURE = json.loads((Path(__file__).parent/'fixtures/activation_license_samples.json').read_text())


class ClockCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.wall = 1800000000
        self.uptime = 10000
        self.boot = 'boot-one'
        self.guard = self.new_guard()

    def tearDown(self):
        self.temp.cleanup()

    def new_guard(self):
        return LicenseGuard(FIXTURE['public_key'], self.root/'profile', 'a'*64,
                            clock=lambda: self.wall, monotonic=lambda: self.uptime,
                            macs=['b'*64], boot_source=lambda: (self.boot, self.uptime))

    def file(self, name='ten_day'):
        p = self.root/(name+'.fvlicense')
        p.write_text(json.dumps(FIXTURE['licenses'][name]))
        return p

    def test_ntp_backward_correction_continues_counting_actual_elapsed_time(self):
        original = self.guard.activate(self.file())
        self.wall -= 6*3600
        self.uptime += 3600
        result = self.guard.check()
        self.assertEqual(result['expires_at'], original['expires_at'])
        self.assertEqual(result['display_expires_at']-self.wall, 9*86400+23*3600)
        self.assertEqual(self.guard.state()['last_seen'], original['activated_at']+3600)

    def test_restarting_application_during_same_boot_does_not_extend_time(self):
        original = self.guard.activate(self.file())
        self.wall -= 3*86400
        self.uptime += 2*86400
        restarted = self.new_guard()
        result = restarted.activate(self.file())
        self.assertEqual(result['activated_at'], original['activated_at'])
        self.assertEqual(result['display_expires_at']-self.wall, 8*86400)

    def test_forward_calendar_jump_does_not_prematurely_expire_active_session(self):
        original = self.guard.activate(self.file())
        self.wall += 100*86400
        self.uptime += 3600
        result = self.new_guard().check()
        self.assertEqual(result['expires_at'], original['expires_at'])
        self.assertEqual(result['display_expires_at']-self.wall, 864000-3600)

    def test_sleep_and_hibernate_time_counts_towards_expiration(self):
        self.guard.activate(self.file())
        self.wall -= 3600
        self.uptime += 864000
        with self.assertRaises(LicenseError) as caught:
            self.guard.check()
        self.assertEqual(caught.exception.code, 'expired')

    def test_reboot_with_correct_calendar_counts_powered_off_time(self):
        original = self.guard.activate(self.file())
        self.boot = 'boot-two'
        self.uptime = 20
        self.wall += 3*86400
        value = self.new_guard().check()
        self.assertEqual(value['display_expires_at']-self.wall, 7*86400)
        self.assertEqual(value['activated_at'], original['activated_at'])

    def test_backward_date_across_reboots_requires_new_signed_license(self):
        original = self.guard.activate(self.file())
        self.boot = 'boot-two'
        self.uptime = 20
        self.wall -= 86400
        restarted = self.new_guard()
        with self.assertRaises(LicenseError):
            restarted.activate(self.file())
        renewed = restarted.activate(self.file('renewal'))
        self.assertEqual(renewed['display_expires_at']-self.wall, 10*86400)
        self.assertEqual(restarted.state()['activations'][original['license_id']]['activated_at'], original['activated_at'])

    def test_old_future_timestamp_is_migrated_once_without_resetting_usage(self):
        initial = self.guard.activate(self.file())
        records = self.guard.state()['activations']
        high = initial['activated_at']+2*86400
        # Old 3.6.1 state had no boot-clock sample and could lock a corrected PC.
        old = dict(device_id=self.guard.device, key_id=self.guard.key_id,
                   last_seen=high, activations=records)
        self.guard.state_path.write_bytes(protect(canonical(old)))
        self.wall -= 5*86400
        restarted = self.new_guard()
        result = restarted.check()
        self.assertEqual(result['display_expires_at']-self.wall, 8*86400)
        self.assertEqual(result['activated_at'], initial['activated_at'])
        self.assertIsNotNone(restarted.state()['clock_sample'])
        self.uptime += 86400
        self.assertEqual(self.new_guard().check()['display_expires_at']-self.wall, 7*86400)

    def test_unlimited_license_is_not_blocked_by_a_time_only_restriction(self):
        self.guard.activate(self.file('unlimited'))
        self.boot = 'boot-two'
        self.uptime = 3
        self.wall -= 20*365*86400
        self.assertIsNone(self.new_guard().check()['expires_at'])

    def test_expired_license_stays_expired_after_migration_and_reimport(self):
        initial = self.guard.activate(self.file())
        old = dict(device_id=self.guard.device, key_id=self.guard.key_id,
                   last_seen=initial['expires_at'], activations=self.guard.state()['activations'])
        self.guard.state_path.write_bytes(protect(canonical(old)))
        self.wall -= 5*86400
        for operation in [self.new_guard().check, lambda: self.new_guard().activate(self.file())]:
            with self.assertRaises(LicenseError) as caught:
                operation()
            self.assertEqual(caught.exception.code, 'expired')


if __name__ == '__main__':
    unittest.main()
