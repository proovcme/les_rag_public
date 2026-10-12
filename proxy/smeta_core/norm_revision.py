"""Read-only SQLite revision evidence; no source writes or persistent snapshots."""
from __future__ import annotations

import hashlib
import ctypes
import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

IDENTITY_SCHEMA = 'les.norm-revision.v1'
IDENTITY_FIELDS = ('schema', 'base_sha256', 'norm_id', 'norm_key', 'edition', 'base_type')


class NormRevisionConflict(ValueError):
    def __init__(self, expected: Mapping[str, Any] | None, actual: Mapping[str, Any] | None, reason: str):
        self.expected = dict(expected or {})
        self.actual = dict(actual or {})
        self.reason = reason
        super().__init__(reason)


class _FileBasicInfo(ctypes.Structure):
    # FILE_BASIC_INFO: four LARGE_INTEGER values followed by one DWORD.
    _fields_ = [('CreationTime', ctypes.c_int64), ('LastAccessTime', ctypes.c_int64),
        ('LastWriteTime', ctypes.c_int64), ('ChangeTime', ctypes.c_int64),
        ('FileAttributes', ctypes.c_uint32)]


@lru_cache(maxsize=1)
def _windows_file_api():
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    create.restype = ctypes.c_void_p
    query = kernel32.GetFileInformationByHandleEx
    query.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    query.restype = ctypes.c_int
    close = kernel32.CloseHandle
    close.argtypes = [ctypes.c_void_p]
    close.restype = ctypes.c_int
    return create, query, close


def _windows_change_time(path: Path) -> int:
    """NTFS ChangeTime changes on in-place writes/restored mtime; ctime is birth time.

    API contract: learn.microsoft.com/windows/win32/api/winbase/ns-winbase-file_basic_info
    """
    create, query, close = _windows_file_api()
    # FILE_READ_ATTRIBUTES, SHARE_READ|WRITE|DELETE, OPEN_EXISTING, ATTRIBUTE_NORMAL.
    handle = create(str(path), 0x80, 0x7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise NormRevisionConflict(None, None, 'normative_metadata_open_failed') from ctypes.WinError(ctypes.get_last_error())
    try:
        info = _FileBasicInfo()
        if not query(handle, 0, ctypes.byref(info), ctypes.sizeof(info)):  # FileBasicInfo = 0
            raise NormRevisionConflict(None, None, 'normative_metadata_query_failed') from ctypes.WinError(ctypes.get_last_error())
        return info.ChangeTime
    finally:
        if not close(handle):
            raise NormRevisionConflict(None, None, 'normative_metadata_close_failed') from ctypes.WinError(ctypes.get_last_error())


def revision_fingerprint(path: Path) -> tuple[int, int, int, int, int]:
    wal = path.with_name(path.name + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise NormRevisionConflict(None, None, 'normative_wal_pending')
    stat = path.stat()
    change_time = _windows_change_time(path) if os.name == 'nt' else stat.st_ctime_ns
    return stat.st_dev, stat.st_ino, change_time, stat.st_mtime_ns, stat.st_size


def revision_sha256(path: str, fingerprint: tuple[int, int, int, int, int]) -> str:
    """Hash current bytes; filesystem metadata is not a content identity.

    Fresh source reads pay a complete scan. Explicit retained snapshots avoid
    this scan, but current reads must not reuse a SHA after a metadata collision.
    """
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if revision_fingerprint(Path(path)) != fingerprint:
        raise NormRevisionConflict(None, None, 'normative_revision_changed_during_hash')
    return digest.hexdigest()


def _clear_revision_hash_cache() -> None:
    """Compatibility with callers that used to clear the metadata-keyed cache."""


revision_sha256.cache_clear = _clear_revision_hash_cache


def identity_for_row(row: Mapping[str, Any], base_sha256: str) -> dict[str, str]:
    return dict(schema=IDENTITY_SCHEMA, base_sha256=base_sha256,
        norm_id=str(row['norm_id']), norm_key=str(row['norm_key']),
        edition=str(row['edition']), base_type=str(row['base_type']))


class RevisionConnection(sqlite3.Connection):
    """Existing readers close in finally; failed validation cancels their return."""
    def close(self) -> None:
        try:
            path = getattr(self, '_revision_path', None)
            if path is not None:
                current = revision_fingerprint(path)
                current_sha = revision_sha256(str(path), current)
                if current != self._revision_fingerprint or current_sha != self.base_sha256:
                    raise NormRevisionConflict({'base_sha256': self.base_sha256},
                        {'base_sha256': current_sha}, 'normative_revision_changed_during_read')
        finally:
            self._revision_path = None
            super().close()


def readonly_revision_connection(path: Path) -> RevisionConnection:
    resolved = path.resolve()
    before = revision_fingerprint(resolved)
    conn = sqlite3.connect(f'{resolved.as_uri()}?mode=ro', uri=True, timeout=30.0,
        factory=RevisionConnection)
    try:
        conn.execute('BEGIN')
        conn.execute('SELECT rootpage FROM sqlite_master LIMIT 1').fetchall()
        # Acquire SQLite's read lock before signing bytes; SQL writers cannot
        # commit a new main-file revision between the hash and source queries.
        sha = revision_sha256(str(resolved), before)
        after = revision_fingerprint(resolved)
        if after != before:
            raise NormRevisionConflict({'base_sha256': sha},
                {'base_sha256': revision_sha256(str(resolved), after)}, 'normative_revision_changed_before_read')
        conn._revision_path = resolved
        conn._revision_fingerprint = before
        conn.base_sha256 = sha
        return conn
    except BaseException:
        conn.close()
        raise
