"""Apple Mail .emlx helpers."""

from __future__ import annotations

from pathlib import Path


def emlx_to_eml_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    first_newline = data.find(b"\n")
    if first_newline <= 0:
        return data
    try:
        byte_count = int(data[:first_newline].strip())
    except ValueError:
        return data
    start = first_newline + 1
    end = start + max(0, byte_count)
    if end <= len(data):
        return data[start:end]
    return data[start:]


def read_email_message_bytes(path: Path) -> bytes:
    if path.suffix.lower() == ".emlx":
        return emlx_to_eml_bytes(path)
    return path.read_bytes()
