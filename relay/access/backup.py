from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import struct
import tempfile
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .models import AccessConfigurationError, InvalidChallenge


_MAGIC = b"LFRA-SQLITE-BACKUP-1\n"
_HEADER_SIZE = struct.Struct(">I")
_MAX_HEADER_BYTES = 16_384

# Cached provider datasets. None of them carry access-recovery value and they
# dominate the live database, so every backup copy is stripped of them. Leaving
# the ground and surface caches off this list made each hourly artifact 19.9 MB
# instead of 3.3 MB and filled the relay volume in forty hours.
_PROVIDER_CACHE_TABLES = (
    "schedule_snapshots",
    "provider_schedule_snapshots",
    "schedule_provider_cache",
    "mobile_standalone_cache",
    "airport_ground_snapshots",
    "airport_surface_snapshots",
)
# Bumped whenever _PROVIDER_CACHE_TABLES grows, so prune() re-strips artifacts
# written while a table was still missing from the list.
_PROVIDER_EXCLUSION_VERSION = 2
# A run copies the database, VACUUMs the copy, then writes and verifies the
# artifact, all beside each other. Three copies plus a margin is the peak.
_BACKUP_COPIES_IN_FLIGHT = 3
_BACKUP_FREE_SPACE_MARGIN = 32 * 1024 * 1024
# AES-GCM tag appended to every ciphertext, so an artifact's size can be
# checked against the plaintext length its header claims.
_GCM_TAG_BYTES = 16
# Retention tiers. Hourly granularity used to run for seven days, which is 168
# artifacts: more than the relay's 1 GB volume can hold beside the database it
# backs up. Two days of hourly recovery points, then daily cover for a quarter,
# is what actually fits.
_HOURLY_RETENTION = timedelta(hours=48)
_DAILY_RETENTION = timedelta(days=90)
_MONTHLY_RETENTION = timedelta(days=366)


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


def _stamp_from_name(path: Path) -> str:
    """Sort key from the timestamp an artifact carries in its filename.

    Modification time cannot be used. prune() rewrites older artifacts in place
    to re-strip provider caches, and the atomic replace gives each rewritten
    file a fresh mtime, so ordering by mtime makes an arbitrary old artifact
    look like the newest one. The stamp is fixed-width basic ISO 8601, so
    lexicographic order is chronological order, and reading it costs no
    decryption.
    """
    stem = path.name
    if stem.startswith("relay-access-") and stem.endswith(".lfrbak"):
        remainder = stem[len("relay-access-"):-len(".lfrbak")]
        stamp, _, suffix = remainder.rpartition("-")
        if stamp and suffix:
            return stamp
    return ""


def _remove_sqlite_temp(path: Path) -> None:
    """Remove a temporary SQLite file together with its journal/WAL sidecars."""
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


@contextmanager
def _temp_sqlite(directory: Path, prefix: str, *, data: bytes | None = None):
    """Yield a temporary SQLite path that is always removed with its sidecars.

    Cleanup has to survive a partial write. A backup that runs out of disk
    raises inside the write itself, and assigning the path inside a `with` block
    whose cleanup only began afterwards leaked every truncated file, plus the
    rollback journals VACUUM left behind.
    """
    directory.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", prefix=prefix, suffix=".sqlite", dir=str(directory), delete=False
    )
    path = Path(handle.name)
    try:
        with handle:
            if data is not None:
                handle.write(data)
                handle.flush()
        yield path
    finally:
        _remove_sqlite_temp(path)


def _strip_provider_cache(conn: sqlite3.Connection) -> None:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in _PROVIDER_CACHE_TABLES:
        if table in tables:
            conn.execute(f"DELETE FROM {table}")


class AccessBackupSpaceError(AccessConfigurationError):
    """Raised when the volume cannot hold another backup.

    A subclass of AccessConfigurationError so existing handlers keep working,
    distinct so a scheduled run can skip quietly while an operator-forced one
    still reports why.
    """


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
        with _temp_sqlite(self.backup_directory, ".relay-access-snapshot-") as snapshot_path:
            source = sqlite3.connect(str(self.database_path))
            destination = sqlite3.connect(str(snapshot_path))
            try:
                source.execute("PRAGMA busy_timeout=5000")
                source.backup(destination)
                # Access recovery does not need provider datasets. Remove them
                # from the backup copy (including freed pages), never the live DB.
                destination.execute("PRAGMA secure_delete=ON")
                _strip_provider_cache(destination)
                destination.commit()
                destination.execute("VACUUM")
            finally:
                destination.close()
                source.close()
            self._integrity_check(snapshot_path)
            return snapshot_path.read_bytes()

    def required_free_bytes(self) -> int:
        """Free space a single backup run needs beside the database.

        The snapshot copy, its VACUUM scratch and the verification copy all live
        next to the finished artifact, so the figure scales with the database
        rather than the artifact. Reporting it lets a monitor warn before the
        guard below starts refusing, instead of after.
        """
        try:
            database_bytes = self.database_path.stat().st_size
        except OSError:
            database_bytes = 0
        return _BACKUP_COPIES_IN_FLIGHT * database_bytes + _BACKUP_FREE_SPACE_MARGIN

    def _require_free_space(self) -> None:
        """Refuse a backup that cannot fit instead of filling the volume.

        Discovering the shortfall by hitting ENOSPC mid-write leaves the artifact
        unwritten and the run is retried every minute, which is how the relay
        volume reached zero bytes free.
        """
        if not self.database_path.is_file():
            return
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        required = self.required_free_bytes()
        free = shutil.disk_usage(str(self.backup_directory)).free
        if free < required:
            raise AccessBackupSpaceError(
                "Relay Access backup needs "
                f"{required} bytes free beside the database and {free} are available"
            )

    def create_backup(self, *, now: datetime | None = None) -> BackupInspection:
        created = (now or _utc_now()).astimezone(timezone.utc)
        self._require_free_space()
        plaintext = self._snapshot_bytes()
        nonce = os.urandom(12)
        database_hash = hashlib.sha256(plaintext).hexdigest()
        header = json.dumps(
            {
                "format": 1,
                "provider_data_excluded": True,
                "provider_exclusion_version": _PROVIDER_EXCLUSION_VERSION,
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

    def _read_header(self, path: Path) -> tuple[dict[str, Any], int]:
        """Return the cleartext header and the offset at which the ciphertext starts.

        Retention bucketing and the re-strip gate only need header fields, so
        they read these few hundred bytes rather than pulling every retained
        artifact through AES-GCM and SHA-256 once an hour. The offset lets a
        caller size-check an artifact without reading the payload.
        """
        path = Path(path)
        prefix_size = len(_MAGIC) + _HEADER_SIZE.size
        with path.open("rb") as handle:
            prefix = handle.read(prefix_size)
            if len(prefix) < prefix_size or not prefix.startswith(_MAGIC):
                raise InvalidChallenge(f"Encrypted backup {path.name} has an invalid format")
            (header_length,) = _HEADER_SIZE.unpack(prefix[len(_MAGIC):])
            if header_length <= 0 or header_length > _MAX_HEADER_BYTES:
                raise InvalidChallenge(f"Encrypted backup {path.name} has an invalid header")
            header_raw = handle.read(header_length)
        if len(header_raw) != header_length:
            raise InvalidChallenge(f"Encrypted backup {path.name} has an invalid header")
        try:
            header = json.loads(header_raw.decode("utf-8"))
            if not isinstance(header, dict):
                raise TypeError("Encrypted backup header is not a JSON object")
            str(header["key_id"])
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidChallenge(f"Encrypted backup {path.name} has an invalid header") from exc
        return header, prefix_size + header_length

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
            with _temp_sqlite(
                self.backup_directory, ".relay-access-verify-", data=plaintext
            ) as temporary:
                self._integrity_check(temporary)
                if database_validator is not None:
                    database_validator(temporary)
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
            key=lambda item: (_stamp_from_name(item), item.name),
            reverse=True,
        ) if self.backup_directory.is_dir() else []
        return candidates[0] if candidates else None

    def verify_keyring_references(self) -> list[str]:
        referenced: set[str] = set()
        if not self.backup_directory.is_dir():
            return []
        for path in self.backup_directory.glob("relay-access-*.lfrbak"):
            referenced.add(str(self._read_header(path)[0]["key_id"]))
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
            stamp = _stamp_from_name(latest)
            if stamp:
                created = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            else:
                created = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
        except Exception:
            return True
        return current - created >= timedelta(hours=1)

    def _remove_legacy_provider_data(self, path: Path, *, header: dict[str, Any] | None = None) -> None:
        """Keep access recovery records while removing cached datasets in old archives.

        The provider_exclusion_version gate is checked against the cleartext
        header before anything is decrypted, so an artifact already stripped at
        the current version costs a header read rather than a full decrypt and
        re-encrypt on every hourly prune. Callers holding the header pass it in.
        """
        if header is None:
            header, _ = self._read_header(path)
        if int(header.get("provider_exclusion_version") or 0) >= _PROVIDER_EXCLUSION_VERSION:
            return
        header, plaintext = self._decrypt(path)
        with _temp_sqlite(
            self.backup_directory, ".relay-access-restrip-", data=plaintext
        ) as temporary:
            conn = sqlite3.connect(temporary)
            try:
                conn.execute("PRAGMA secure_delete=ON")
                _strip_provider_cache(conn)
                conn.commit()
                conn.execute("VACUUM")
            finally:
                conn.close()
            self._integrity_check(temporary)
            clean = temporary.read_bytes()
            nonce = os.urandom(12)
            header.update(provider_data_excluded=True,
                          provider_exclusion_version=_PROVIDER_EXCLUSION_VERSION,
                          database_sha256=hashlib.sha256(clean).hexdigest(),
                          plaintext_bytes=len(clean), nonce=base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("="))
            encoded = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
            encrypted = AESGCM(self._keys[header["key_id"]]).encrypt(nonce, clean, _MAGIC + encoded)
            self._write_atomic(path, _MAGIC + _HEADER_SIZE.pack(len(encoded)) + encoded + encrypted)

    def _retention_created_at(self, path: Path) -> datetime:
        """Return an artifact's creation time, refusing anything prune must not delete.

        Bucketing must not pull the whole retained set through AES-GCM and
        SHA-256 every hour, so this trusts the cleartext header rather than
        decrypting. It still rejects every artifact retention has no business
        removing: an unparseable header, a key the relay no longer holds, a
        missing or unusable created_at, and a file whose size contradicts the
        length the header claims. A bit flip inside the ciphertext is the one
        corruption this no longer notices; inspect(verify_database=True),
        restore() and the backup health check still authenticate in full.
        """
        header, payload_offset = self._read_header(path)
        if str(header.get("key_id") or "") not in self._keys:
            raise AccessConfigurationError(
                f"Encrypted backup {path.name} references an unavailable key"
            )
        expected = payload_offset + int(header["plaintext_bytes"]) + _GCM_TAG_BYTES
        if path.stat().st_size != expected:
            raise InvalidChallenge(f"Encrypted backup {path.name} has an unexpected length")
        self._remove_legacy_provider_data(path, header=header)
        return _parse_time(header["created_at"])

    def prune(self, *, now: datetime | None = None) -> list[Path]:
        current = (now or _utc_now()).astimezone(timezone.utc)
        candidates: list[tuple[Path, datetime]] = []
        for path in self.backup_directory.glob("relay-access-*.lfrbak"):
            try:
                created = self._retention_created_at(path)
            except Exception:
                # Never delete an unreadable artifact automatically; surface it
                # to the operator/backup-health check instead.
                continue
            candidates.append((path, created))
        candidates.sort(key=lambda item: item[1], reverse=True)
        retained_buckets: set[tuple[str, str]] = set()
        removed: list[Path] = []
        for path, created in candidates:
            age = current - created
            if age < timedelta(0):
                keep = True
            elif age <= _HOURLY_RETENTION:
                bucket = ("hour", created.strftime("%Y-%m-%dT%H"))
                keep = bucket not in retained_buckets
                retained_buckets.add(bucket)
            elif age <= _DAILY_RETENTION:
                bucket = ("day", created.strftime("%Y-%m-%d"))
                keep = bucket not in retained_buckets
                retained_buckets.add(bucket)
            elif age <= _MONTHLY_RETENTION:
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
