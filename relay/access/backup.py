from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import struct
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .models import AccessConfigurationError, InvalidChallenge


_MAGIC = b"LFRA-SQLITE-BACKUP-1\n"
_HEADER_SIZE = struct.Struct(">I")
_MAX_HEADER_BYTES = 16_384


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _backup_key(secret: str) -> bytes:
    value = (secret or "").encode("utf-8")
    if len(value) < 24:
        raise AccessConfigurationError("Relay Access backup secret must contain at least 24 bytes")
    return hashlib.sha256(b"localflight-access-backup-v1\x00" + value).digest()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class BackupInspection:
    path: Path
    created_at: str
    key_id: str
    database_sha256: str
    plaintext_bytes: int


class AccessBackupManager:
    """WAL-consistent encrypted SQLite backups with tiered retention."""

    def __init__(
        self,
        *,
        database_path: Path,
        backup_directory: Path,
        active_key_id: str,
        active_secret: str,
        historical_secrets: dict[str, str] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.backup_directory = Path(backup_directory)
        self.active_key_id = (active_key_id or "").strip()
        if not self.active_key_id or len(self.active_key_id) > 32:
            raise AccessConfigurationError("Relay Access backup key ID is invalid")
        self._keys = {
            str(key_id).strip(): _backup_key(secret)
            for key_id, secret in (historical_secrets or {}).items()
            if str(key_id).strip()
        }
        self._keys[self.active_key_id] = _backup_key(active_secret)

    @staticmethod
    def _integrity_check(path: Path) -> None:
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if not row or str(row[0]).strip().lower() != "ok":
                raise InvalidChallenge("SQLite backup integrity verification failed")
        finally:
            conn.close()

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
            delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _snapshot_bytes(self) -> bytes:
        if not self.database_path.is_file():
            raise AccessConfigurationError("Relay Access database does not exist")
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".relay-access-snapshot-",
            suffix=".sqlite",
            dir=str(self.backup_directory),
            delete=False,
        ) as handle:
            snapshot_path = Path(handle.name)
        try:
            source = sqlite3.connect(str(self.database_path))
            destination = sqlite3.connect(str(snapshot_path))
            try:
                source.execute("PRAGMA busy_timeout=5000")
                source.backup(destination)
                destination.commit()
            finally:
                destination.close()
                source.close()
            self._integrity_check(snapshot_path)
            return snapshot_path.read_bytes()
        finally:
            snapshot_path.unlink(missing_ok=True)

    def create_backup(self, *, now: datetime | None = None) -> BackupInspection:
        created = (now or _utc_now()).astimezone(timezone.utc)
        plaintext = self._snapshot_bytes()
        nonce = os.urandom(12)
        database_hash = hashlib.sha256(plaintext).hexdigest()
        header = json.dumps(
            {
                "format": 1,
                "created_at": created.isoformat(),
                "key_id": self.active_key_id,
                "nonce": base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("="),
                "database_sha256": database_hash,
                "plaintext_bytes": len(plaintext),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        ciphertext = AESGCM(self._keys[self.active_key_id]).encrypt(
            nonce,
            plaintext,
            _MAGIC + header,
        )
        stamp = created.strftime("%Y%m%dT%H%M%SZ")
        destination = self.backup_directory / f"relay-access-{stamp}-{uuid.uuid4().hex[:8]}.lfrbak"
        self._write_atomic(destination, _MAGIC + _HEADER_SIZE.pack(len(header)) + header + ciphertext)
        inspection = self.inspect(destination, verify_database=True)
        self.prune(now=created)
        return inspection

    def _decrypt(self, path: Path) -> tuple[dict[str, Any], bytes]:
        raw = Path(path).read_bytes()
        if not raw.startswith(_MAGIC) or len(raw) < len(_MAGIC) + _HEADER_SIZE.size:
            raise InvalidChallenge("Relay Access backup format is invalid")
        offset = len(_MAGIC)
        (header_length,) = _HEADER_SIZE.unpack(raw[offset:offset + _HEADER_SIZE.size])
        offset += _HEADER_SIZE.size
        if header_length <= 0 or header_length > _MAX_HEADER_BYTES:
            raise InvalidChallenge("Relay Access backup header is invalid")
        header_raw = raw[offset:offset + header_length]
        ciphertext = raw[offset + header_length:]
        try:
            header = json.loads(header_raw.decode("utf-8"))
            key_id = str(header["key_id"])
            nonce_text = str(header["nonce"])
            nonce = base64.urlsafe_b64decode(nonce_text + "=" * (-len(nonce_text) % 4))
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidChallenge("Relay Access backup header is invalid") from exc
        key = self._keys.get(key_id)
        if key is None:
            raise AccessConfigurationError(f"Relay Access backup key {key_id} is not available")
        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, _MAGIC + header_raw)
        except Exception as exc:
            raise InvalidChallenge("Relay Access backup authentication failed") from exc
        if not hmac.compare_digest(
            hashlib.sha256(plaintext).hexdigest(),
            str(header.get("database_sha256") or ""),
        ):
            raise InvalidChallenge("Relay Access backup checksum does not match")
        if len(plaintext) != int(header.get("plaintext_bytes") or -1):
            raise InvalidChallenge("Relay Access backup length does not match")
        return header, plaintext

    def inspect(
        self,
        path: Path,
        *,
        verify_database: bool = False,
        database_validator: Callable[[Path], None] | None = None,
    ) -> BackupInspection:
        header, plaintext = self._decrypt(Path(path))
        if verify_database or database_validator is not None:
            with tempfile.NamedTemporaryFile(
                prefix=".relay-access-verify-",
                suffix=".sqlite",
                dir=str(self.backup_directory),
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(plaintext)
            try:
                self._integrity_check(temporary)
                if database_validator is not None:
                    database_validator(temporary)
            finally:
                temporary.unlink(missing_ok=True)
        return BackupInspection(
            path=Path(path),
            created_at=str(header.get("created_at") or ""),
            key_id=str(header.get("key_id") or ""),
            database_sha256=str(header.get("database_sha256") or ""),
            plaintext_bytes=len(plaintext),
        )

    def restore(
        self,
        path: Path,
        destination: Path,
        *,
        replace: bool = False,
        database_validator: Callable[[Path], None] | None = None,
    ) -> BackupInspection:
        source_path = Path(path)
        target = Path(destination)
        if target.exists() and not replace:
            raise InvalidChallenge("Restore destination already exists")
        header, plaintext = self._decrypt(source_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.name}.restore-",
            suffix=".sqlite",
            dir=str(target.parent),
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(plaintext)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            self._integrity_check(temporary)
            if database_validator is not None:
                database_validator(temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return BackupInspection(
            path=source_path,
            created_at=str(header.get("created_at") or ""),
            key_id=str(header.get("key_id") or ""),
            database_sha256=str(header.get("database_sha256") or ""),
            plaintext_bytes=len(plaintext),
        )

    def latest_backup(self) -> Path | None:
        candidates = sorted(
            self.backup_directory.glob("relay-access-*.lfrbak"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ) if self.backup_directory.is_dir() else []
        return candidates[0] if candidates else None

    def verify_keyring_references(self) -> list[str]:
        referenced: set[str] = set()
        if not self.backup_directory.is_dir():
            return []
        for path in self.backup_directory.glob("relay-access-*.lfrbak"):
            raw = path.read_bytes()
            if not raw.startswith(_MAGIC) or len(raw) < len(_MAGIC) + _HEADER_SIZE.size:
                raise InvalidChallenge(f"Encrypted backup {path.name} has an invalid format")
            offset = len(_MAGIC)
            (header_length,) = _HEADER_SIZE.unpack(raw[offset:offset + _HEADER_SIZE.size])
            offset += _HEADER_SIZE.size
            if header_length <= 0 or header_length > _MAX_HEADER_BYTES:
                raise InvalidChallenge(f"Encrypted backup {path.name} has an invalid header")
            try:
                header = json.loads(raw[offset:offset + header_length].decode("utf-8"))
                key_id = str(header["key_id"])
            except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise InvalidChallenge(f"Encrypted backup {path.name} has an invalid header") from exc
            referenced.add(key_id)
        missing = sorted(key_id for key_id in referenced if key_id not in self._keys)
        if missing:
            raise AccessConfigurationError(
                "Encrypted backups reference unavailable key IDs: " + ", ".join(missing)
            )
        return sorted(referenced)

    def backup_due(self, *, now: datetime | None = None) -> bool:
        current = (now or _utc_now()).astimezone(timezone.utc)
        latest = self.latest_backup()
        if latest is None:
            return True
        try:
            created = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
        except Exception:
            return True
        return current - created >= timedelta(hours=1)

    def prune(self, *, now: datetime | None = None) -> list[Path]:
        current = (now or _utc_now()).astimezone(timezone.utc)
        candidates: list[tuple[Path, datetime]] = []
        for path in self.backup_directory.glob("relay-access-*.lfrbak"):
            try:
                candidates.append((path, _parse_time(self.inspect(path).created_at)))
            except Exception:
                # Never delete an unreadable artifact automatically; surface it
                # to the operator/backup-health check instead.
                continue
        candidates.sort(key=lambda item: item[1], reverse=True)
        retained_buckets: set[tuple[str, str]] = set()
        removed: list[Path] = []
        for path, created in candidates:
            age = current - created
            if age < timedelta(0):
                keep = True
            elif age <= timedelta(days=7):
                bucket = ("hour", created.strftime("%Y-%m-%dT%H"))
                keep = bucket not in retained_buckets
                retained_buckets.add(bucket)
            elif age <= timedelta(days=90):
                bucket = ("day", created.strftime("%Y-%m-%d"))
                keep = bucket not in retained_buckets
                retained_buckets.add(bucket)
            elif age <= timedelta(days=366):
                bucket = ("month", created.strftime("%Y-%m"))
                keep = bucket not in retained_buckets
                retained_buckets.add(bucket)
            else:
                keep = False
            if not keep:
                path.unlink(missing_ok=True)
                removed.append(path)
        return removed


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Create, verify, or restore an encrypted Relay Access backup")
    parser.add_argument("operation", choices=("create", "verify", "restore"))
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--backup-directory", required=True, type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--restore-to", type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--key-id", default=os.environ.get("RELAY_ACCESS_BACKUP_KEY_ID", "v1"))
    args = parser.parse_args()
    secret = os.environ.get("RELAY_ACCESS_BACKUP_SECRET", "")
    try:
        historical = json.loads(os.environ.get("RELAY_ACCESS_HISTORICAL_BACKUP_SECRETS_JSON", "{}"))
    except json.JSONDecodeError as exc:
        raise SystemExit("Historical backup keyring is not valid JSON") from exc
    manager = AccessBackupManager(
        database_path=args.database,
        backup_directory=args.backup_directory,
        active_key_id=args.key_id,
        active_secret=secret,
        historical_secrets=historical,
    )

    def access_keyring_validator(path: Path) -> None:
        from .service import LicenseService

        def parsed_keyring(name: str) -> dict[str, str]:
            try:
                value = json.loads(os.environ.get(name, "{}"))
            except json.JSONDecodeError as exc:
                raise AccessConfigurationError(f"{name} is not valid JSON") from exc
            if not isinstance(value, dict):
                raise AccessConfigurationError(f"{name} must be a JSON object")
            return {str(key): str(secret) for key, secret in value.items()}

        def connect() -> sqlite3.Connection:
            conn = sqlite3.connect(str(path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            return conn

        service = LicenseService(
            connect,
            hash_secret=os.environ.get("RELAY_ACCESS_HASH_SECRET", ""),
            key_secret=os.environ.get("RELAY_ACCESS_KEY_SECRET", ""),
            encryption_secret=os.environ.get("RELAY_ACCESS_ENCRYPTION_SECRET", ""),
            hash_secret_id=os.environ.get("RELAY_ACCESS_HASH_SECRET_ID", "v1"),
            key_secret_id=os.environ.get("RELAY_ACCESS_KEY_SECRET_ID", "v1"),
            encryption_secret_id=os.environ.get("RELAY_ACCESS_ENCRYPTION_SECRET_ID", "v1"),
            historical_hash_secrets=parsed_keyring("RELAY_ACCESS_HISTORICAL_HASH_SECRETS_JSON"),
            historical_key_secrets=parsed_keyring("RELAY_ACCESS_HISTORICAL_KEY_SECRETS_JSON"),
            historical_encryption_secrets=parsed_keyring(
                "RELAY_ACCESS_HISTORICAL_ENCRYPTION_SECRETS_JSON"
            ),
        )
        service.verify_keyring_references()
    if args.operation == "create":
        result = manager.create_backup()
    elif args.operation == "verify":
        if args.backup is None:
            parser.error("--backup is required for verify")
        result = manager.inspect(args.backup, verify_database=True)
    else:
        if args.backup is None or args.restore_to is None:
            parser.error("--backup and --restore-to are required for restore")
        result = manager.restore(
            args.backup,
            args.restore_to,
            replace=args.replace,
            database_validator=access_keyring_validator,
        )
    print(json.dumps({
        "ok": True,
        "path": str(result.path),
        "created_at": result.created_at,
        "key_id": result.key_id,
        "database_sha256": result.database_sha256,
        "plaintext_bytes": result.plaintext_bytes,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
