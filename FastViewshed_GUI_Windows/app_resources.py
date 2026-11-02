"""Read immutable data resources from the native desktop launcher."""
from functools import lru_cache
import os
from pathlib import Path


@lru_cache(maxsize=4)
def launcher_resource(identifier):
    if os.name != 'nt':
        return b''
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    kernel.LoadLibraryExW.restype = wintypes.HMODULE
    kernel.FindResourceW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
    kernel.FindResourceW.restype = ctypes.c_void_p
    kernel.SizeofResource.argtypes = [wintypes.HMODULE, ctypes.c_void_p]
    kernel.SizeofResource.restype = wintypes.DWORD
    kernel.LoadResource.argtypes = [wintypes.HMODULE, ctypes.c_void_p]
    kernel.LoadResource.restype = ctypes.c_void_p
    kernel.LockResource.argtypes = [ctypes.c_void_p]
    kernel.LockResource.restype = ctypes.c_void_p
    kernel.FreeLibrary.argtypes = [wintypes.HMODULE]
    executable = Path(__file__).resolve().parent / 'FastViewshed.exe'
    module = kernel.LoadLibraryExW(str(executable), None, 0x22)
    if not module:
        return b''
    try:
        resource = kernel.FindResourceW(module, ctypes.c_void_p(identifier), ctypes.c_void_p(10))
        if not resource:
            return b''
        size = kernel.SizeofResource(module, resource)
        address = kernel.LockResource(kernel.LoadResource(module, resource))
        if not address or not 0 < size <= 32 * 1024 * 1024:
            raise ValueError('Invalid launcher resource.')
        return ctypes.string_at(address, size)
    finally:
        kernel.FreeLibrary(module)
