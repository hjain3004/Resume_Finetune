"""Deterministic checksum helpers.

Every artifact the harness compares (canonical profile, target JDs, rendered
résumés) is identified by a SHA-256 checksum computed here, never by mtime or
path alone, so a plan or result can be verified byte-for-byte later even if
files move.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str, encoding: str = "utf-8") -> str:
    return sha256_bytes(text.encode(encoding))


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def short_id(checksum: str, length: int = 12) -> str:
    """First `length` hex chars of a checksum, for compact human-readable IDs
    (e.g. "master_profile@2bf6c44ef08c"). Never used where the full checksum
    is required for verification."""
    return checksum[:length]
