from __future__ import annotations

import os
from pathlib import Path


def ensure_private_dir(path: Path) -> None:
    """Create/harden a Local Flight secret directory where POSIX modes apply."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            path.chmod(0o700)
    except OSError:
        pass


def ensure_private_file(path: Path) -> None:
    """Best-effort owner-only mode repair; Windows keeps its normal ACL model."""
    if os.name == "nt" or not path.exists():
        return
    try:
        path.chmod(0o600)
    except OSError:
        pass


def write_private_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Atomically write text with owner-only permissions where supported."""
    ensure_private_dir(path.parent)
    pending = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pending.write_text(text, encoding=encoding)
    ensure_private_file(pending)
    os.replace(pending, path)
    ensure_private_file(path)


__all__ = ["ensure_private_dir", "ensure_private_file", "write_private_text"]
