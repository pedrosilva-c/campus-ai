"""Per-user process guard, shared by GUI and CLI entry points."""
from pathlib import Path
import hashlib
import sys


class InstanceGuard:
    def __init__(self, directory: Path):
        self.directory = directory
        self.handle = None
        self.lock = None

    def acquire(self) -> bool:
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            api.CreateMutexW.restype = wintypes.HANDLE
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            name = hashlib.sha256(str(self.directory.resolve()).casefold().encode()).hexdigest()
            handle = api.CreateMutexW(None, False, 'Local\\CampusAI-' + name)
            error = ctypes.get_last_error()
            if not handle:
                raise OSError('Não foi possível proteger a instância do Campus AI.')
            if error == 183:  # ERROR_ALREADY_EXISTS
                api.CloseHandle(handle)
                return False
            self.handle, self.api = handle, api
            return True
        from PySide6.QtCore import QLockFile
        self.lock = QLockFile(str(self.directory / 'resident.lock'))
        self.lock.setStaleLockTime(0)
        return self.lock.tryLock(0)

    def release(self):
        if self.handle is not None:
            self.api.CloseHandle(self.handle)
            self.handle = None
        if self.lock is not None:
            self.lock.unlock()
            self.lock = None
