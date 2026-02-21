from __future__ import annotations

import ctypes as C
import os
from ctypes import wintypes as W

FILE_MAP_READ = 0x0004
_IS_WINDOWS = os.name == "nt"

if _IS_WINDOWS:
    _kernel32 = C.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenFileMappingW.argtypes = [W.DWORD, W.BOOL, W.LPCWSTR]
    _kernel32.OpenFileMappingW.restype = W.HANDLE
    _kernel32.MapViewOfFile.argtypes = [W.HANDLE, W.DWORD, W.DWORD, W.DWORD, C.c_size_t]
    _kernel32.MapViewOfFile.restype = W.LPVOID
    _kernel32.UnmapViewOfFile.argtypes = [W.LPCVOID]
    _kernel32.UnmapViewOfFile.restype = W.BOOL
    _kernel32.CloseHandle.argtypes = [W.HANDLE]
    _kernel32.CloseHandle.restype = W.BOOL
else:
    _kernel32 = None


class MappedView:
    def __init__(self, handle: int, addr: int, size: int):
        self.handle = handle
        self.addr = addr
        self.size = size

    def close(self) -> None:
        if not _IS_WINDOWS or _kernel32 is None:
            self.handle = 0
            self.addr = 0
            return
        if self.addr:
            _kernel32.UnmapViewOfFile(C.c_void_p(self.addr))
            self.addr = 0
        if self.handle:
            _kernel32.CloseHandle(W.HANDLE(self.handle))
            self.handle = 0

    def __enter__(self) -> "MappedView":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def open_mmf_readonly(map_name: str, size: int) -> MappedView | None:
    if not _IS_WINDOWS or _kernel32 is None:
        raise RuntimeError("Shared-memory access is only supported on Windows.")

    handle = _kernel32.OpenFileMappingW(FILE_MAP_READ, False, map_name)
    if not handle:
        return None

    addr = _kernel32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, size)
    if not addr:
        _kernel32.CloseHandle(handle)
        return None

    return MappedView(int(handle), int(addr), size)


__all__ = ["FILE_MAP_READ", "MappedView", "open_mmf_readonly"]
