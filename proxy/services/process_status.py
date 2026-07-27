"""Cross-platform process liveness checks without mutating the process.

On POSIX ``os.kill(pid, 0)`` is a harmless existence/permission probe. On
Windows ``os.kill`` is implemented through ``TerminateProcess`` for ordinary
signals, so it must never be used as a liveness check for background jobs.
"""

from __future__ import annotations

import os


def _windows_pid_running(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _posix_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def pid_running(pid: int, *, platform: str | None = None) -> bool:
    """Return whether *pid* is alive without terminating it on Windows."""
    if pid <= 0:
        return False
    active_platform = platform or os.name
    if active_platform == "nt":
        return _windows_pid_running(pid)
    return _posix_pid_running(pid)
