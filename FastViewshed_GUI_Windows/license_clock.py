"""Boot identity and elapsed time that are independent of calendar corrections."""
import ctypes
import os
from pathlib import Path
import time


def boot_clock():
    """Return (boot UUID, seconds since boot including sleep), or None."""
    if os.name == 'nt':
        from ctypes import wintypes
        # SystemBootEnvironmentInformation starts with a GUID unique to this boot.
        ntdll = ctypes.WinDLL('ntdll')
        query = ntdll.NtQuerySystemInformation
        query.argtypes = [wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG,
                          ctypes.POINTER(wintypes.ULONG)]
        query.restype = ctypes.c_long
        class BootInformation(ctypes.Structure):
            _fields_ = [('identifier', ctypes.c_ubyte * 16),
                        ('firmware_type', wintypes.ULONG), ('flags', ctypes.c_ulonglong)]
        buffer = BootInformation()
        size = wintypes.ULONG()
        if query(90, ctypes.byref(buffer), ctypes.sizeof(buffer), ctypes.byref(size)) != 0:
            return None
        identifier = bytes(buffer.identifier)
        if not any(identifier):
            return None
        tick = ctypes.WinDLL('kernel32').GetTickCount64
        tick.argtypes = []
        tick.restype = ctypes.c_ulonglong
        return identifier.hex(), tick()/1000.0
    path = Path('/proc/sys/kernel/random/boot_id')
    if path.is_file() and hasattr(time, 'CLOCK_BOOTTIME'):
        return path.read_text().strip(), time.clock_gettime(time.CLOCK_BOOTTIME)
    return None
