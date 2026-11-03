"""Device-bound signed offline licenses. No signing secrets ship with the app.

Signatures use RSA-3072/PKCS#1 v1.5 with SHA-256, produced by Windows .NET.
The runtime verifies the exact encoded message; no crypto package is required.
Offline clock checks detect normal rollback, not a hostile administrator who
rewrites the program, clones a VM, or removes every protected local record.
"""
import base64
import ctypes
from contextlib import contextmanager
from functools import wraps
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import platform
import re
import tempfile
import time
from app_resources import launcher_resource
from device_identity import hardware_mac_ids
from license_clock import boot_clock

LICENSING_REQUIRED = False  # Enabled only in the owner's locally built output.
PRODUCT = 'FastViewshed'
MAX_LICENSE_BYTES = 32768


class LicenseError(ValueError):
    def __init__(self, message, code='invalid'):
        super().__init__(message)
        self.code = code


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def device_id():
    if os.name == 'nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            identity = winreg.QueryValueEx(key, 'MachineGuid')[0].strip().lower()
    else:
        path = Path('/etc/machine-id')
        identity = path.read_text().strip() if path.exists() else platform.node()
    if not identity:
        raise LicenseError('شناسهٔ معتبر دستگاه خوانده نشد.')
    return hashlib.sha256((PRODUCT + ':device-v1:' + identity).encode()).hexdigest()


def public_key_id(key):
    return hashlib.sha256((key['modulus'] + ':' + key['exponent']).encode('ascii')).hexdigest()


def decode64(value):
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise LicenseError('ساختار فایل لایسنس معتبر نیست.') from exc


def verify_license(document, key, device, now, macs=()):
    """Verify signed claims. Version 2 expiry is resolved by LicenseGuard's ledger."""
    try:
        raw = decode64(document['payload'])
        signature = decode64(document['signature'])
        modulus = decode64(key['modulus'])
        exponent_bytes = decode64(key['exponent'])
        if len(modulus) != 384 or exponent_bytes != b'\x01\x00\x01':
            raise LicenseError('کلید عمومی این نسخه معتبر نیست.')
        number = int.from_bytes(modulus, 'big')
        if number.bit_length() != 3072 or len(signature) != 384 or int.from_bytes(signature, 'big') >= number:
            raise LicenseError('امضای لایسنس معتبر نیست.')
        digest_info = bytes.fromhex('3031300d060960864801650304020105000420') + hashlib.sha256(raw).digest()
        expected = b'\x00\x01' + b'\xff' * (384 - len(digest_info) - 3) + b'\x00' + digest_info
        actual = pow(int.from_bytes(signature, 'big'), 65537, number).to_bytes(384, 'big')
        if not hmac.compare_digest(actual, expected):
            raise LicenseError('امضای لایسنس معتبر نیست؛ فایل دست‌کاری شده یا صادرکننده متفاوت است.')
        payload = json.loads(raw)
        if type(payload.get('version')) is not int or payload['version'] not in (1, 2) or payload.get('product') != PRODUCT or payload.get('key_id') != public_key_id(key):
            raise LicenseError('این لایسنس متعلق به این نسخه از برنامه نیست.')
        if not isinstance(payload.get('device_id'), str) or not hmac.compare_digest(payload['device_id'], device):
            raise LicenseError('این لایسنس مخصوص دستگاه دیگری است.')
        if not re.fullmatch(r'[0-9a-f]{32}', payload.get('license_id', '')):
            raise LicenseError('شناسهٔ لایسنس معتبر نیست.')
        if not isinstance(payload.get('customer'), str) or not 1 <= len(payload['customer']) <= 160:
            raise LicenseError('نام دریافت‌کنندهٔ لایسنس معتبر نیست.')
        if payload['version'] == 2:
            days = payload['duration_days']
            if payload.get('activation_mode') != 'first_activation' or (days is not None and (type(days) is not int or not 1 <= days <= 36500)):
                raise LicenseError('مدت لایسنس معتبر نیست.')
            signed_macs = payload.get('mac_ids', [])
            if not isinstance(signed_macs, list) or len(signed_macs) > 64 or any(not isinstance(m, str) or not re.fullmatch('[0-9a-f]{64}', m) for m in signed_macs):
                raise LicenseError('شناسهٔ کارت شبکه معتبر نیست.')
            if signed_macs and not set(signed_macs).intersection(macs):
                raise LicenseError('کارت شبکهٔ ثبت‌شده برای این لایسنس شناسایی نشد؛ با صادرکننده تماس بگیرید.')
            return payload
        issued, expires = payload['issued_at'], payload['expires_at']
        if type(issued) is not int or (expires is not None and (type(expires) is not int or expires <= issued)):
            raise LicenseError('مدت لایسنس معتبر نیست.')
        if expires is not None and now + 120 < issued:
            raise LicenseError('تاریخ سیستم قبل از صدور لایسنس است؛ ساعت ویندوز را اصلاح کنید.')
        if expires is not None and now >= expires:
            raise LicenseError('مدت لایسنس تمام شده است؛ برای ادامه فایل جدید از صادرکننده بگیرید.', 'expired')
        return payload
    except LicenseError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise LicenseError('فایل لایسنس معتبر نیست.') from exc


def protect(data, decrypt=False):
    if os.name != 'nt':
        # Development/test platform only. Distributed licensed builds use DPAPI.
        return data
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    dll = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    if decrypt:
        dll.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        dll.CryptUnprotectData.restype = wintypes.BOOL
        ok = dll.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        dll.CryptProtectData.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        dll.CryptProtectData.restype = wintypes.BOOL
        ok = dll.CryptProtectData(ctypes.byref(source), 'FastViewshed licensing', None, None, None, 1, ctypes.byref(result))
    if not ok:
        raise LicenseError('اطلاعات فعال‌سازی این حساب ویندوز خوانده نشد؛ فایل لایسنس را دوباره وارد کنید.')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='license_', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        try:
            with self.locked():
                return method(self, *args, **kwargs)
        except OSError as exc:
            raise LicenseError('ذخیرهٔ فعال‌سازی ممکن نشد؛ دسترسی پوشه یا اجرای هم‌زمان را بررسی کنید.') from exc
    return call


class LicenseGuard:
    def __init__(self, key=None, folder=None, device=None, clock=None, monotonic=None, macs=None, boot_source=None):
        try:
            self.key = key if key is not None else json.loads(launcher_resource(102))
            self.key_id = public_key_id(self.key)
        except (KeyError, ValueError, TypeError) as exc:
            raise LicenseError('کلید لایسنس داخل برنامه پیدا نشد؛ نسخهٔ کامل را دوباره نصب کنید.') from exc
        self.device = device or device_id()
        self.macs = hardware_mac_ids() if macs is None else list(macs)
        self.clock, self.monotonic = clock or time.time, monotonic or time.monotonic
        # Explicit test clocks retain the strict legacy policy unless a boot
        # source is also supplied. Production uses Windows' sleep-aware uptime.
        self.boot_source = boot_source if boot_source is not None else (boot_clock if clock is None and monotonic is None else lambda: None)
        self._sample = None
        self.started_at, self.started_monotonic = self.clock(), self.monotonic()
        self.folder = Path(folder) if folder is not None else Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.local/share') / 'FastViewshed' / 'Licensing' / self.key_id
        self.active_path = self.folder / 'active.fvlicense'
        self.state_path = self.folder / 'clock.dat'
        self.registry_path = r'Software\FastViewshed\Licensing' + chr(92) + self.key_id
        self.use_registry = os.name == 'nt' and folder is None

    def request(self):
        return dict(version=2, product=PRODUCT, device_id=self.device, key_id=self.key_id,
                    activation_mode='first_activation', mac_ids=self.macs)

    @contextmanager
    def locked(self):
        """Keep two application instances from overwriting activation history."""
        self.folder.mkdir(parents=True, exist_ok=True)
        with (self.folder / '.license.lock').open('a+b') as stream:
            if os.name == 'nt':
                import msvcrt
                if stream.seek(0, 2) == 0:
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def state(self):
        copies = []
        try:
            if self.state_path.exists():
                if self.state_path.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError('Clock record is too large')
                copies.append(self.state_path.read_bytes())
            if self.use_registry:
                import winreg
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_path) as key:
                        copies.append(winreg.QueryValueEx(key, 'Clock')[0])
                except FileNotFoundError:
                    pass
            values = [json.loads(protect(b, decrypt=True)) for b in copies]
            activations = {}
            sample = None
            sample_high = -1
            for item in values:
                if item['device_id'] != self.device or item['key_id'] != self.key_id or type(item['last_seen']) is not int:
                    raise ValueError('Invalid protected clock record')
                record_clock = item.get('clock_sample')
                if record_clock is not None:
                    if not isinstance(record_clock, dict) or not isinstance(record_clock.get('boot'), str) or not 1 <= len(record_clock['boot']) <= 128:
                        raise ValueError('Invalid boot clock record')
                    for field in ('uptime', 'wall', 'effective'):
                        if type(record_clock.get(field)) not in (int, float) or not math.isfinite(record_clock[field]):
                            raise ValueError('Invalid clock sample')
                    if record_clock['uptime'] < 0:
                        raise ValueError('Invalid uptime')
                    if item['last_seen'] > sample_high:
                        sample = dict(record_clock)
                        sample_high = item['last_seen']
                records = item.get('activations', {})
                if not isinstance(records, dict) or len(records) > 10000:
                    raise ValueError('Invalid activation history')
                for identifier, record in records.items():
                    if not re.fullmatch('[0-9a-f]{32}', identifier) or not isinstance(record, dict) or type(record.get('activated_at')) is not int or not re.fullmatch('[0-9a-f]{64}', record.get('payload_sha256', '')):
                        raise ValueError('Invalid activation record')
                    if identifier in activations:
                        previous = activations[identifier]
                        if previous['payload_sha256'] != record['payload_sha256']:
                            raise ValueError('Conflicting activation records')
                        if record['activated_at'] >= previous['activated_at']:
                            continue
                    activations[identifier] = dict(record)
            return dict(last_seen=max((item['last_seen'] for item in values), default=0), activations=activations, clock_sample=sample)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LicenseError('اطلاعات محافظت‌شدهٔ فعال‌سازی آسیب دیده است؛ با صادرکننده تماس بگیرید.') from exc

    def trusted_now(self, state=None, unlimited=False, allow_rebase=False):
        now = self.clock()
        records = state if state is not None else self.state()
        high = records['last_seen']
        boot = self.boot_source()
        previous = records.get('clock_sample')
        if boot is not None:
            identifier, uptime = boot
            if previous is None:
                # One-time migration preserves all consumed time and every
                # activation start, including an old incorrectly future clock.
                effective = max(now, high)
            elif identifier == previous['boot'] and uptime >= previous['uptime']:
                effective = max(high, previous['effective'] + uptime - previous['uptime'])
            else:
                gap = now - previous['wall']
                if gap < -120 or (identifier == previous['boot'] and uptime < previous['uptime']):
                    if not (unlimited or allow_rebase):
                        raise LicenseError('ساعت ثبت‌شده با زمان پس از راه‌اندازی ویندوز سازگار نیست؛ ساعت را اصلاح کنید یا از صادرکننده لایسنس جدید بگیرید. سوابق فعال‌سازی را حذف نکنید.', 'clock')
                    # A newly signed license or an unlimited one can establish
                    # a new wall-clock anchor; old consumed time never decreases.
                    effective = max(high, previous['effective']) + uptime
                else:
                    effective = max(high, previous['effective'] + max(0, gap))
            self._sample = dict(boot=identifier, uptime=uptime, wall=now, effective=effective)
            return effective
        expected = self.started_at + max(0, self.monotonic() - self.started_monotonic)
        if now + 120 < max(high, expected) and not (unlimited or allow_rebase):
            raise LicenseError('عقب‌بردن ساعت سیستم شناسایی شد؛ تاریخ و ساعت صحیح را تنظیم کنید.', 'clock')
        return max(now, expected, high)

    def remember(self, now, state=None):
        records = state if state is not None else self.state()
        state = canonical(dict(device_id=self.device, key_id=self.key_id, last_seen=max(int(now), records['last_seen']),
                               activations=records['activations'], clock_sample=self._sample or records.get('clock_sample')))
        encrypted = protect(state)
        atomic_write(self.state_path, encrypted)
        if self.use_registry:
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.registry_path) as key:
                winreg.SetValueEx(key, 'Clock', 0, winreg.REG_BINARY, encrypted)

    def resolve(self, document, now, state, first_activation=False):
        payload = verify_license(document, self.key, self.device, now, self.macs)
        if payload['version'] == 1:
            return payload
        identifier = payload['license_id']
        digest = hashlib.sha256(decode64(document['payload'])).hexdigest()
        record = state['activations'].get(identifier)
        if record is None:
            if not first_activation:
                raise LicenseError('سابقهٔ فعال‌سازی این لایسنس پیدا نشد؛ فایل لایسنس را وارد کنید.')
            record = dict(activated_at=int(now), payload_sha256=digest)
            state['activations'][identifier] = record
        if record['payload_sha256'] != digest:
            raise LicenseError('شناسهٔ لایسنس با سابقهٔ فعال‌سازی سازگار نیست.')
        started = record['activated_at']
        expires = None if payload['duration_days'] is None else started + payload['duration_days'] * 86400
        if expires is not None and now >= expires:
            raise LicenseError('مدت لایسنس تمام شده است؛ برای ادامه فایل جدید از صادرکننده بگیرید.', 'expired')
        display = None if expires is None else int(self.clock()+max(0, expires-now))
        return dict(payload, activated_at=started, expires_at=expires, display_expires_at=display)

    def authenticated_time(self, document, state, activating=False):
        # Authenticate before allowing any clock exception. A signed unlimited
        # license has no temporal restriction but still enforces its device/MAC.
        claims = verify_license(document, self.key, self.device, self.clock(), self.macs)
        unlimited = (claims.get('duration_days') is None if claims['version'] == 2 else claims['expires_at'] is None)
        new_license = activating and claims['version'] == 2 and claims['license_id'] not in state['activations']
        return self.trusted_now(state, unlimited=unlimited, allow_rebase=new_license)

    @serialized
    def activate(self, filename):
        path = Path(filename)
        if path.stat().st_size > MAX_LICENSE_BYTES:
            raise LicenseError('حجم فایل لایسنس معتبر نیست.')
        raw = path.read_bytes()
        try:
            document = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise LicenseError('فایل انتخاب‌شده لایسنس معتبر نیست.') from exc
        state = self.state()
        now = self.authenticated_time(document, state, activating=True)
        try:
            payload = self.resolve(document, now, state, first_activation=True)
        except LicenseError as exc:
            if exc.code == 'expired':
                self.remember(now, state)
            raise
        self.remember(now, state)
        atomic_write(self.active_path, canonical(document))
        return payload

    @serialized
    def check(self):
        try:
            if not self.active_path.exists():
                raise LicenseError('برنامه بدون لایسنس فعال اجرا نمی‌شود؛ فایل صادرشده برای همین دستگاه را انتخاب کنید.')
            if self.active_path.stat().st_size > MAX_LICENSE_BYTES:
                raise LicenseError('فایل فعال‌سازی آسیب دیده است.')
            state = self.state()
            document = json.loads(self.active_path.read_bytes())
            now = self.authenticated_time(document, state)
            try:
                payload = self.resolve(document, now, state)
            except LicenseError as exc:
                if exc.code == 'expired':
                    self.remember(now, state)
                raise
            self.remember(now, state)
            return payload
        except (OSError, ValueError, TypeError) as exc:
            if isinstance(exc, LicenseError):
                raise
            raise LicenseError('فعال‌سازی خوانده نشد؛ فایل لایسنس معتبر را دوباره وارد کنید.') from exc
