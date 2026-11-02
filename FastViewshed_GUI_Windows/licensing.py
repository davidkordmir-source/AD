"""Device-bound signed offline licenses. No signing secrets ship with the app.

Signatures use RSA-3072/PKCS#1 v1.5 with SHA-256, produced by Windows .NET.
The runtime verifies the exact encoded message; no crypto package is required.
Offline clock checks detect normal rollback, not a hostile administrator who
rewrites the program, clones a VM, or removes every protected local record.
"""
import base64
import ctypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import re
import tempfile
import time
from app_resources import launcher_resource

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


def verify_license(document, key, device, now):
    """Verify signature before trusting customer, duration, or device fields."""
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
        if payload.get('version') != 1 or payload.get('product') != PRODUCT or payload.get('key_id') != public_key_id(key):
            raise LicenseError('این لایسنس متعلق به این نسخه از برنامه نیست.')
        if not isinstance(payload.get('device_id'), str) or not hmac.compare_digest(payload['device_id'], device):
            raise LicenseError('این لایسنس مخصوص دستگاه دیگری است.')
        if not re.fullmatch(r'[0-9a-f]{32}', payload.get('license_id', '')):
            raise LicenseError('شناسهٔ لایسنس معتبر نیست.')
        issued, expires = payload['issued_at'], payload['expires_at']
        if type(issued) is not int or (expires is not None and (type(expires) is not int or expires <= issued)):
            raise LicenseError('مدت لایسنس معتبر نیست.')
        if not isinstance(payload.get('customer'), str) or not 1 <= len(payload['customer']) <= 160:
            raise LicenseError('نام دریافت‌کنندهٔ لایسنس معتبر نیست.')
        if now + 120 < issued:
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


class LicenseGuard:
    def __init__(self, key=None, folder=None, device=None, clock=None, monotonic=None):
        try:
            self.key = key if key is not None else json.loads(launcher_resource(102))
            self.key_id = public_key_id(self.key)
        except (KeyError, ValueError, TypeError) as exc:
            raise LicenseError('کلید لایسنس داخل برنامه پیدا نشد؛ نسخهٔ کامل را دوباره نصب کنید.') from exc
        self.device = device or device_id()
        self.clock, self.monotonic = clock or time.time, monotonic or time.monotonic
        self.started_at, self.started_monotonic = self.clock(), self.monotonic()
        self.folder = Path(folder) if folder is not None else Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.local/share') / 'FastViewshed' / 'Licensing' / self.key_id
        self.active_path = self.folder / 'active.fvlicense'
        self.state_path = self.folder / 'clock.dat'
        self.registry_path = r'Software\FastViewshed\Licensing' + chr(92) + self.key_id
        self.use_registry = os.name == 'nt' and folder is None

    def request(self):
        return dict(version=1, product=PRODUCT, device_id=self.device, key_id=self.key_id)

    def state(self):
        copies = []
        try:
            if self.state_path.exists():
                copies.append(self.state_path.read_bytes())
            if self.use_registry:
                import winreg
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_path) as key:
                        copies.append(winreg.QueryValueEx(key, 'Clock')[0])
                except FileNotFoundError:
                    pass
            values = [json.loads(protect(b, decrypt=True)) for b in copies]
            for item in values:
                if item['device_id'] != self.device or item['key_id'] != self.key_id or type(item['last_seen']) is not int:
                    raise ValueError('Invalid protected clock record')
            return max((item['last_seen'] for item in values), default=0)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LicenseError('اطلاعات محافظت‌شدهٔ فعال‌سازی آسیب دیده است؛ با صادرکننده تماس بگیرید.') from exc

    def trusted_now(self):
        now = self.clock()
        expected = self.started_at + max(0, self.monotonic() - self.started_monotonic)
        high = self.state()
        if now + 120 < max(high, expected):
            raise LicenseError('عقب‌بردن ساعت سیستم شناسایی شد؛ تاریخ و ساعت صحیح را تنظیم کنید.')
        return max(now, expected, high)

    def remember(self, now):
        state = canonical(dict(device_id=self.device, key_id=self.key_id, last_seen=int(now)))
        encrypted = protect(state)
        atomic_write(self.state_path, encrypted)
        if self.use_registry:
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.registry_path) as key:
                winreg.SetValueEx(key, 'Clock', 0, winreg.REG_BINARY, encrypted)

    def activate(self, filename):
        path = Path(filename)
        if path.stat().st_size > MAX_LICENSE_BYTES:
            raise LicenseError('حجم فایل لایسنس معتبر نیست.')
        raw = path.read_bytes()
        try:
            document = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise LicenseError('فایل انتخاب‌شده لایسنس معتبر نیست.') from exc
        now = self.trusted_now()
        try:
            payload = verify_license(document, self.key, self.device, now)
        except LicenseError as exc:
            if exc.code == 'expired':
                self.remember(now)
            raise
        self.remember(now)
        atomic_write(self.active_path, canonical(document))
        return payload

    def check(self):
        try:
            if not self.active_path.exists():
                raise LicenseError('برنامه بدون لایسنس فعال اجرا نمی‌شود؛ فایل صادرشده برای همین دستگاه را انتخاب کنید.')
            if self.active_path.stat().st_size > MAX_LICENSE_BYTES:
                raise LicenseError('فایل فعال‌سازی آسیب دیده است.')
            now = self.trusted_now()
            try:
                payload = verify_license(json.loads(self.active_path.read_bytes()), self.key, self.device, now)
            except LicenseError as exc:
                if exc.code == 'expired':
                    self.remember(now)
                raise
            self.remember(now)
            return payload
        except (OSError, ValueError, TypeError) as exc:
            if isinstance(exc, LicenseError):
                raise
            raise LicenseError('فعال‌سازی خوانده نشد؛ فایل لایسنس معتبر را دوباره وارد کنید.') from exc
