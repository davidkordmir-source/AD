"""Local hardware identifiers; MACs are hashed and require no network access."""
import ctypes
import hashlib
import os
import uuid


def hardware_mac_ids():
    addresses = []
    if os.name == 'nt':
        from ctypes import wintypes
        class Guid(ctypes.Structure):
            _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD),
                        ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]
        class InterfacePrefix(ctypes.Structure):
            # Documented prefix of MIB_IF_ROW2 through PermanentPhysicalAddress.
            _fields_ = [('Luid', ctypes.c_ulonglong), ('Index', wintypes.ULONG),
                        ('Guid', Guid), ('Alias', ctypes.c_wchar * 257),
                        ('Description', ctypes.c_wchar * 257), ('AddressLength', wintypes.ULONG),
                        ('Address', ctypes.c_ubyte * 32), ('Permanent', ctypes.c_ubyte * 32)]
        library = ctypes.WinDLL('iphlpapi')
        permanent = library.GetIfEntry2
        permanent.argtypes = [ctypes.c_void_p]
        permanent.restype = wintypes.ULONG
        def stable_address(adapter):
            # Reserve more than the full fixed MIB_IF_ROW2, including counters.
            row = ctypes.create_string_buffer(4096)
            prefix = ctypes.cast(row, ctypes.POINTER(InterfacePrefix)).contents
            prefix.Index = adapter.IfIndex
            if permanent(row) == 0 and prefix.AddressLength == 6:
                raw = bytes(prefix.Permanent[:6])
                if any(raw) and not raw[0] & 3:
                    return raw
            return bytes(adapter.PhysicalAddress[:6])
        class Adapter(ctypes.Structure):
            pass
        Adapter._fields_ = [
            ('Length', wintypes.ULONG), ('IfIndex', wintypes.DWORD),
            ('Next', ctypes.POINTER(Adapter)), ('AdapterName', ctypes.c_char_p),
            ('FirstUnicast', ctypes.c_void_p), ('FirstAnycast', ctypes.c_void_p),
            ('FirstMulticast', ctypes.c_void_p), ('FirstDnsServer', ctypes.c_void_p),
            ('DnsSuffix', wintypes.LPWSTR), ('Description', wintypes.LPWSTR),
            ('FriendlyName', wintypes.LPWSTR), ('PhysicalAddress', ctypes.c_ubyte * 8),
            ('PhysicalAddressLength', wintypes.ULONG), ('Flags', wintypes.DWORD),
            ('Mtu', wintypes.ULONG), ('IfType', wintypes.DWORD)]
        function = library.GetAdaptersAddresses
        function.argtypes = [wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG)]
        function.restype = wintypes.ULONG
        size = wintypes.ULONG(16384)
        for _ in range(3):
            if size.value > 1024 * 1024:
                break
            buffer = ctypes.create_string_buffer(size.value)
            status = function(0, 15, None, buffer, ctypes.byref(size))
            if status == 111:  # ERROR_BUFFER_OVERFLOW: resize and retry.
                continue
            if status != 0:
                break
            current = ctypes.cast(buffer, ctypes.POINTER(Adapter))
            for _ in range(1024):
                if not current:
                    break
                adapter = current.contents
                if adapter.Length < Adapter.IfType.offset + 4:
                    break
                if adapter.IfType in (6, 71) and adapter.PhysicalAddressLength == 6:
                    addresses.append(stable_address(adapter))
                current = adapter.Next
            break
    else:
        addresses.append(uuid.getnode().to_bytes(6, 'big'))
    # Ignore random/local-administration addresses and multicast/empty adapters.
    # The stable Windows installation identity remains available if none qualify.
    return sorted({hashlib.sha256(b'FastViewshed:mac-v1:' + raw).hexdigest()
                   for raw in addresses if len(raw) == 6 and any(raw) and not raw[0] & 3})[:64]
