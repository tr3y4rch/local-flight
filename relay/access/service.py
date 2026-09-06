from __future__ import annotations

import json
import base64
import secrets
import sqlite3
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from .crypto import (
    derive_license_key,
    generated_license_key_hash,
    keyed_hash,
    license_key_hash,
    normalize_license_key,
    open_value,
    random_token,
    require_secret,
    seal_value,
)
from .models import (
    AccessConfigurationError,
    AccessRateLimited,
    ActivationResult,
    DeviceCredential,
    HolderSession,
    InvalidChallenge,
    InvalidLicenseKey,
    LicenseInactive,
    LicenseNotFound,
    MagicLinkDelivery,
    RelayLicense,
    VerifiedPurchase,
)


ConnectionFactory = Callable[[], sqlite3.Connection]


class LicenseService:
    """Account-light licensing and one-receiver activation service."""

    def __init__(
        self,
        connect: ConnectionFactory,
        *,
        hash_secret: str,
        key_secret: str,
        product_code: str = "beacon_relay_lifetime_v1",
        key_secret_id: str = "v1",
        hash_secret_id: str = "v1",
        encryption_secret: str = "",
        encryption_secret_id: str = "v1",
        historical_hash_secrets: dict[str, str] | None = None,
        historical_key_secrets: dict[str, str] | None = None,
        historical_encryption_secrets: dict[str, str] | None = None,
    ) -> None:
        self._connect = connect
        self.hash_secret_id = (hash_secret_id or "v1").strip()[:32]
        self.key_secret_id = (key_secret_id or "v1").strip()[:32]
        self.encryption_secret_id = (encryption_secret_id or "v1").strip()[:32]
        self._hash_secrets = {
            str(secret_id).strip()[:32]: require_secret(value, f"Relay Access hash secret {secret_id}")
            for secret_id, value in (historical_hash_secrets or {}).items()
            if str(secret_id).strip()
        }
        self._key_secrets = {
            str(secret_id).strip()[:32]: require_secret(value, f"Relay Access key secret {secret_id}")
            for secret_id, value in (historical_key_secrets or {}).items()
            if str(secret_id).strip()
        }
        self._encryption_secrets = {
            str(secret_id).strip()[:32]: require_secret(value, f"Relay Access encryption secret {secret_id}")
            for secret_id, value in (historical_encryption_secrets or {}).items()
            if str(secret_id).strip()
        }
        self._hash_secrets[self.hash_secret_id] = require_secret(hash_secret, "Relay Access hash secret")
        self._key_secrets[self.key_secret_id] = require_secret(key_secret, "Relay Access key secret")
        self._encryption_secrets[self.encryption_secret_id] = require_secret(
            encryption_secret or key_secret,
            "Relay Access encryption secret",
        )
        self._hash_secret = self._hash_secrets[self.hash_secret_id]
        self._key_secret = self._key_secrets[self.key_secret_id]
        self._encryption_secret = self._encryption_secrets[self.encryption_secret_id]
        self.product_code = product_code

    def verify_keyring_references(self) -> dict[str, list[str]]:
        """Fail closed when persisted rows refer to a key that is unavailable.

        This check is intentionally read-only and safe to run both at startup
        and after restoring a database backup.  A key rotation is not complete
        merely because a new write key exists: every historical identifier
        referenced by the database must remain readable until a dedicated
        rehash/re-encryption migration removes it.
        """

        checks: tuple[tuple[str, str, str, dict[str, str]], ...] = (
            ("relay_licenses", "key_secret_id", "1=1", self._key_secrets),
            ("relay_licenses", "hash_secret_id", "1=1", self._hash_secrets),
            (
                "license_holders",
                "notification_email_key_id",
                "notification_email_ciphertext IS NOT NULL",
                self._encryption_secrets,
            ),
            (
                "purchase_records",
                "identity_hash_key_id",
                "external_purchase_hash IS NOT NULL",
                self._hash_secrets,
            ),
            (
                "purchase_records",
                "reconciliation_key_id",
                "reconciliation_handle_ciphertext IS NOT NULL",
                self._encryption_secrets,
            ),
            (
                "relay_activations",
                "credential_hash_secret_id",
                "credential_hash IS NOT NULL",
                self._hash_secrets,
            ),
            (
                "access_challenges",
                "hash_secret_id",
                "token_hash IS NOT NULL",
                self._hash_secrets,
            ),
            (
                "purchase_events",
                "hash_secret_id",
                "event_key IS NOT NULL",
                self._hash_secrets,
            ),
            (
                "mobile_ownership_evidence",
                "hash_secret_id",
                "evidence_hash IS NOT NULL",
                self._hash_secrets,
            ),
            (
                "notification_outbox",
                "encryption_key_id",
                "destination_ciphertext IS NOT NULL OR payload_ciphertext IS NOT NULL",
                self._encryption_secrets,
            ),
            (
                "provider_reconciliation_health",
                "encryption_key_id",
                "cursor_ciphertext IS NOT NULL",
                self._encryption_secrets,
            ),
        )
        referenced: dict[str, set[str]] = {"hash": set(), "license": set(), "encryption": set()}
        missing: set[str] = set()
        conn = self._connect()
        try:
            for table, column, predicate, keyring in checks:
                columns = {
                    str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                }
                if column not in columns:
                    continue
                rows = conn.execute(
                    f"SELECT DISTINCT COALESCE(NULLIF({column}, ''), 'v1') FROM {table} WHERE {predicate}"
                ).fetchall()
                family = (
                    "license" if keyring is self._key_secrets
                    else "hash" if keyring is self._hash_secrets
                    else "encryption"
                )
                for row in rows:
                    secret_id = str(row[0] or "v1")
                    referenced[family].add(secret_id)
                    if secret_id not in keyring:
                        missing.add(f"{family}:{secret_id}")
        finally:
            conn.close()
        if missing:
            raise AccessConfigurationError(
                "Relay Access database references unavailable key IDs: " + ", ".join(sorted(missing))
            )
        return {family: sorted(values) for family, values in referenced.items()}

    def _hash_candidates(self, namespace: str, value: str) -> list[tuple[str, str]]:
        return [
            (secret_id, keyed_hash(secret, namespace, value))
            for secret_id, secret in self._hash_secrets.items()
        ]

    def _seal(self, namespace: str, value: str) -> str:
        return seal_value(self._encryption_secret, namespace, value)

    def _open(self, secret_id: str, namespace: str, value: str) -> str:
        secret = self._encryption_secrets.get((secret_id or "v1").strip())
        if secret is None:
            raise AccessConfigurationError(f"Relay Access encryption secret {secret_id or 'v1'} is not available")
        return open_value(secret, namespace, value)

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _future(minutes: int) -> str:
        return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()

    @staticmethod
    def _parse_time(value: str) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def normalize_email(value: str) -> str:
        email = (value or "").strip().casefold()
        if not email or len(email) > 240 or "@" not in email:
            raise InvalidChallenge("A valid email address is required")
        local, _, domain = email.partition("@")
        if not local or "." not in domain or any(char.isspace() for char in email):
            raise InvalidChallenge("A valid email address is required")
        return email

    def _email_hmac(self, email: str) -> str:
        return keyed_hash(self._hash_secret, "holder-email", self.normalize_email(email))

    def _token_hash(self, namespace: str, token: str) -> str:
        return keyed_hash(self._hash_secret, namespace, token)

    def _token_hash_candidates(self, namespace: str, token: str) -> list[tuple[str, str]]:
        return self._hash_candidates(namespace, token)

    def _external_purchase_hash(self, provider: str, external_id: str) -> str:
        clean_provider = provider.strip().lower()
        clean_external = external_id.strip()
        if not clean_provider or not clean_external:
            raise InvalidChallenge("Verified purchase identity is incomplete")
        return keyed_hash(self._hash_secret, f"purchase:{clean_provider}", clean_external)

    def _external_purchase_hash_candidates(self, provider: str, external_id: str) -> list[tuple[str, str]]:
        clean_provider = provider.strip().lower()
        clean_external = external_id.strip()
        if not clean_provider or not clean_external:
            raise InvalidChallenge("Verified purchase identity is incomplete")
        return self._hash_candidates(f"purchase:{clean_provider}", clean_external)

    @staticmethod
    def _safe_access_state(value: str) -> str:
        normalized = (value or "").strip().lower()
        return normalized if normalized in {"active", "suspended", "refunded", "revoked"} else "revoked"

    def _inactive_error(
        self,
        *,
        license_status: str,
        credential_status: str = "unknown",
        reason: str = "",
        message: str = "Relay Access is not active",
        current_receiver: dict[str, Any] | None = None,
    ) -> LicenseInactive:
        access_state = self._safe_access_state(license_status)
        credential_state = (credential_status or "unknown").strip().lower()
        if credential_state not in {
            "active", "pending_commit", "replaced", "deactivated", "revoked", "unknown"
        }:
            credential_state = "unknown"
        reason_code = (reason or "").strip().lower()
        if not reason_code:
            reason_code = {
                "pending_commit": "activation_not_committed",
                "replaced": "receiver_moved",
                "deactivated": "receiver_released",
                "revoked": "credential_revoked",
            }.get(credential_state) or {
                "suspended": "purchase_suspended",
                "refunded": "purchase_refunded",
                "revoked": "purchase_revoked",
            }.get(access_state, "credential_inactive")
        return LicenseInactive(
            message,
            access_state=access_state,
            credential_state=credential_state,
            reason_code=reason_code,
            retryable=False,
            current_receiver=current_receiver,
        )

    def _license_from_row(self, row: sqlite3.Row) -> RelayLicense:
        return RelayLicense(
            license_id=str(row["license_id"]),
            license_ref=str(row["license_id"]),
            product_code=str(row["product_code"]),
            purchase_source=str(row["purchase_source"]),
            status=str(row["status"]),
            holder_id=str(row["holder_id"]) if row["holder_id"] else None,
            key_prefix=str(row["key_prefix"]),
            key_last_four=str(row["key_last_four"]),
            created_at=str(row["created_at"]),
        )

    def _license_key_for_row(self, row: sqlite3.Row) -> str:
        row_keys = set(row.keys())
        secret_id = str(row["key_secret_id"] or "v1") if "key_secret_id" in row_keys else "v1"
        secret = self._key_secrets.get(secret_id)
        if secret is None:
            raise AccessConfigurationError(f"Relay Access key secret {secret_id} is not available")
        return derive_license_key(secret, str(row["license_id"]), int(row["key_version"] or 1))

    def _holder_for_email(self, conn: sqlite3.Connection, email: str, *, create: bool) -> str | None:
        normalized_email = self.normalize_email(email)
        email_hmac = self._email_hmac(normalized_email)
        sealed_email = self._seal("holder-notification-email", normalized_email)
        hashes = self._hash_candidates("holder-email", normalized_email)
        placeholders = ",".join("?" for _ in hashes)
        row = conn.execute(
            f"SELECT holder_id FROM license_holders WHERE email_hmac IN ({placeholders})",
            tuple(value for _secret_id, value in hashes),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE license_holders
                SET email_hmac=?, notification_email_ciphertext=?, notification_email_key_id=?, last_seen_at=?
                WHERE holder_id=?
                """,
                (email_hmac, sealed_email, self.encryption_secret_id, self.now(), str(row["holder_id"])),
            )
            return str(row["holder_id"])
        if not create:
            return None
        holder_id = f"holder_{uuid.uuid4().hex}"
        now = self.now()
        conn.execute(
            """
            INSERT INTO license_holders (
                holder_id, email_hmac, notification_email_ciphertext,
                notification_email_key_id, created_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (holder_id, email_hmac, sealed_email, self.encryption_secret_id, now, now),
        )
        return holder_id

    def _record_purchase_transition_conn(
        self,
        conn: sqlite3.Connection,
        *,
        purchase_id: str,
        license_id: str,
        from_state: str | None,
        to_state: str,
        reason_code: str,
        source: str,
    ) -> None:
        if from_state is not None and from_state.strip().lower() == to_state.strip().lower():
            return
        conn.execute(
            """
            INSERT INTO purchase_state_transitions (
                transition_id, purchase_id, license_id, from_state, to_state,
                reason_code, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"pst_{uuid.uuid4().hex}",
                purchase_id,
                license_id,
                from_state.strip().lower() if from_state else None,
                to_state.strip().lower(),
                (reason_code or "state_changed")[:80],
                (source or "authority")[:40],
                self.now(),
            ),
        )

    def _insert_purchase_license_conn(
        self,
        conn: sqlite3.Connection,
        purchase: VerifiedPurchase,
        *,
        external_hash: str,
        holder_id: str | None = None,
        state_reason: str = "",
    ) -> tuple[RelayLicense, str]:
        now = self.now()
        if holder_id is None and purchase.email:
            holder_id = self._holder_for_email(conn, purchase.email, create=True)
        license_id = f"lic_{uuid.uuid4().hex}"
        key_version = 1
        key = derive_license_key(self._key_secret, license_id, key_version)
        normalized_key = normalize_license_key(key)
        purchase_id = f"pur_{uuid.uuid4().hex}"
        conn.execute(
            """
            INSERT INTO relay_licenses (
                license_id, holder_id, product_code, purchase_source, status,
                key_version, key_secret_id, hash_secret_id, license_key_hmac, key_prefix, key_last_four,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                license_id,
                holder_id,
                self.product_code,
                purchase.provider.strip().lower(),
                key_version,
                self.key_secret_id,
                self.hash_secret_id,
                generated_license_key_hash(self._hash_secret, normalized_key),
                key[:14],
                normalized_key[-4:],
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO purchase_records (
                purchase_id, provider, external_purchase_hash, license_id,
                product_id, environment, state, evidence_hash, created_at, updated_at,
                last_verified_at, state_reason, state_changed_at, identity_kind,
                identity_hash_key_id, reconciliation_mode,
                reconciliation_handle_ciphertext, reconciliation_key_id,
                acknowledgement_state
            ) VALUES (?, ?, ?, ?, ?, ?, 'paid', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                purchase_id,
                purchase.provider.strip().lower(),
                external_hash,
                license_id,
                purchase.product_id,
                purchase.environment,
                purchase.evidence_hash,
                now,
                now,
                now,
                state_reason[:80] or None,
                now,
                (purchase.identity_kind or f"{purchase.provider.strip().lower()}_purchase")[:64],
                self.hash_secret_id,
                (purchase.reconciliation_mode or "device_only")[:32],
                self._seal(
                    f"provider-reconciliation:{purchase.provider.strip().lower()}",
                    purchase.reconciliation_handle,
                ) if purchase.reconciliation_handle else None,
                self.encryption_secret_id if purchase.reconciliation_handle else None,
                purchase.acknowledgement_state[:32] or None,
            ),
        )
        self._record_purchase_transition_conn(
            conn,
            purchase_id=purchase_id,
            license_id=license_id,
            from_state=None,
            to_state="paid",
            reason_code=state_reason or "purchase_verified",
            source=purchase.provider,
        )
        row = conn.execute("SELECT * FROM relay_licenses WHERE license_id=?", (license_id,)).fetchone()
        return self._license_from_row(row), key

    def _replace_terminal_purchase_conn(
        self,
        conn: sqlite3.Connection,
        existing: sqlite3.Row,
        purchase: VerifiedPurchase,
        *,
        external_hash: str,
        reason: str,
    ) -> tuple[RelayLicense, str]:
        purchase_id = str(existing["linked_purchase_id"])
        tombstone_hash = keyed_hash(
            self._hash_secret,
            f"purchase-tombstone:{purchase.provider.strip().lower()}",
            f"{purchase_id}:{external_hash}",
        )
        conn.execute(
            """
            UPDATE purchase_records
            SET external_purchase_hash=?, state_reason=?, updated_at=?
            WHERE purchase_id=?
            """,
            (tombstone_hash, reason[:80], self.now(), purchase_id),
        )
        return self._insert_purchase_license_conn(
            conn,
            purchase,
            external_hash=external_hash,
            holder_id=str(existing["holder_id"]) if existing["holder_id"] else None,
            state_reason="authoritative_repurchase",
        )

    def _google_proof_postdates_terminal_state(self, purchase: VerifiedPurchase, existing: sqlite3.Row) -> bool:
        if purchase.provider.strip().lower() != "google_app" or int(purchase.verified_at_ms or 0) <= 0:
            return False
        changed_at = str(existing["purchase_state_changed_at"] or "")
        if not changed_at:
            return False
        try:
            proof_time = datetime.fromtimestamp(int(purchase.verified_at_ms) / 1000.0, tz=timezone.utc)
            return proof_time > self._parse_time(changed_at)
        except (OverflowError, OSError, TypeError, ValueError):
            return False

    def fulfill_purchase(self, purchase: VerifiedPurchase) -> tuple[RelayLicense, str, bool]:
        if purchase.state not in {"paid", "purchased"}:
            raise self._inactive_error(
                license_status="revoked" if purchase.state == "revoked" else "suspended",
                reason="store_entitlement_inactive",
                message="Purchase is not in an active state",
            )
        provider = purchase.provider.strip().lower()
        external_hash = self._external_purchase_hash(provider, purchase.external_id)
        external_candidates = self._external_purchase_hash_candidates(provider, purchase.external_id)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            placeholders = ",".join("?" for _ in external_candidates)
            existing = conn.execute(
                f"""
                SELECT l.*, p.state AS purchase_state, p.purchase_id AS linked_purchase_id,
                       p.state_changed_at AS purchase_state_changed_at
                FROM purchase_records p
                JOIN relay_licenses l ON l.license_id=p.license_id
                WHERE p.provider=? AND p.external_purchase_hash IN ({placeholders})
                """,
                (provider, *(value for _secret_id, value in external_candidates)),
            ).fetchone()
            if existing:
                now = self.now()
                current_purchase_state = str(existing["purchase_state"] or "").strip().lower()
                if current_purchase_state in {"refunded", "revoked"}:
                    if provider == "apple_app":
                        # Apple documents appTransactionID as stable across a
                        # refund and repurchase. A fresh, signed AppTransaction
                        # therefore restores the original portable license.
                        conn.execute(
                            """
                            UPDATE purchase_records
                            SET state='paid', state_reason='authoritative_apple_restore',
                                state_changed_at=?, last_verified_at=?, updated_at=?,
                                evidence_hash=COALESCE(NULLIF(?, ''), evidence_hash)
                            WHERE purchase_id=?
                            """,
                            (now, now, now, purchase.evidence_hash, str(existing["linked_purchase_id"])),
                        )
                        conn.execute(
                            """
                            UPDATE relay_licenses
                            SET status='active', revoked_at=NULL, updated_at=?
                            WHERE license_id=?
                            """,
                            (now, str(existing["license_id"])),
                        )
                        self._record_purchase_transition_conn(
                            conn,
                            purchase_id=str(existing["linked_purchase_id"]),
                            license_id=str(existing["license_id"]),
                            from_state=current_purchase_state,
                            to_state="paid",
                            reason_code="authoritative_apple_restore",
                            source="apple_server",
                        )
                    elif self._google_proof_postdates_terminal_state(purchase, existing):
                        replacement, replacement_key = self._replace_terminal_purchase_conn(
                            conn,
                            existing,
                            purchase,
                            external_hash=external_hash,
                            reason="superseded_by_verified_repurchase",
                        )
                        conn.commit()
                        return replacement, replacement_key, True
                    else:
                        conn.commit()
                        raise self._inactive_error(
                            license_status=current_purchase_state,
                            credential_status="revoked",
                            reason="terminal_purchase_requires_repurchase",
                            message="This purchase was permanently revoked",
                        )
                conn.execute(
                    """
                    UPDATE purchase_records
                    SET external_purchase_hash=?, identity_hash_key_id=?, last_verified_at=?,
                        evidence_hash=COALESCE(NULLIF(?, ''), evidence_hash), updated_at=?,
                        identity_kind=COALESCE(NULLIF(?, ''), identity_kind),
                        reconciliation_mode=COALESCE(NULLIF(?, ''), reconciliation_mode),
                        reconciliation_handle_ciphertext=COALESCE(NULLIF(?, ''), reconciliation_handle_ciphertext),
                        reconciliation_key_id=CASE WHEN NULLIF(?, '') IS NULL THEN reconciliation_key_id ELSE ? END,
                        acknowledgement_state=COALESCE(NULLIF(?, ''), acknowledgement_state)
                    WHERE purchase_id=?
                    """,
                    (
                        external_hash,
                        self.hash_secret_id,
                        now,
                        purchase.evidence_hash,
                        now,
                        purchase.identity_kind,
                        purchase.reconciliation_mode,
                        self._seal(
                            f"provider-reconciliation:{provider}",
                            purchase.reconciliation_handle,
                        ) if purchase.reconciliation_handle else "",
                        purchase.reconciliation_handle,
                        self.encryption_secret_id,
                        purchase.acknowledgement_state,
                        str(existing["linked_purchase_id"]),
                    ),
                )
                if current_purchase_state in {"suspended", "disputed"}:
                    conn.execute(
                        """
                        UPDATE purchase_records
                        SET state='paid', state_reason='authoritative_reverification',
                            state_changed_at=?, last_verified_at=?, updated_at=?
                        WHERE purchase_id=?
                        """,
                        (now, now, now, str(existing["linked_purchase_id"])),
                    )
                    conn.execute(
                        """
                        UPDATE relay_licenses
                        SET status='active', revoked_at=NULL, updated_at=?
                        WHERE license_id=?
                        """,
                        (now, str(existing["license_id"])),
                    )
                    self._record_purchase_transition_conn(
                        conn,
                        purchase_id=str(existing["linked_purchase_id"]),
                        license_id=str(existing["license_id"]),
                        from_state=current_purchase_state,
                        to_state="paid",
                        reason_code="authoritative_reverification",
                        source=provider,
                    )
                if purchase.email and not existing["holder_id"]:
                    holder_id = self._holder_for_email(conn, purchase.email, create=True)
                    conn.execute(
                        "UPDATE relay_licenses SET holder_id=?, updated_at=? WHERE license_id=? AND holder_id IS NULL",
                        (holder_id, now, str(existing["license_id"])),
                    )
                existing = conn.execute(
                    "SELECT * FROM relay_licenses WHERE license_id=?",
                    (str(existing["license_id"]),),
                ).fetchone()
                conn.commit()
                return self._license_from_row(existing), self._license_key_for_row(existing), False

            license_record, key = self._insert_purchase_license_conn(
                conn,
                purchase,
                external_hash=external_hash,
            )
            conn.commit()
            return license_record, key, True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_purchase_state(
        self,
        provider: str,
        external_id: str,
        state: str,
        *,
        reason: str = "",
        evidence_hash: str = "",
    ) -> RelayLicense:
        external_hash = self._external_purchase_hash(provider, external_id)
        external_candidates = self._external_purchase_hash_candidates(provider, external_id)
        normalized_state = state.strip().lower()
        license_status = {
            "paid": "active",
            "purchased": "active",
            "suspended": "suspended",
            "refunded": "refunded",
            "disputed": "suspended",
            "revoked": "revoked",
        }.get(normalized_state)
        if not license_status:
            raise InvalidChallenge("Unsupported purchase state")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            placeholders = ",".join("?" for _ in external_candidates)
            row = conn.execute(
                f"SELECT * FROM purchase_records WHERE provider=? AND external_purchase_hash IN ({placeholders})",
                (provider.strip().lower(), *(value for _secret_id, value in external_candidates)),
            ).fetchone()
            if not row:
                raise LicenseNotFound("Purchase was not found")
            current_state = str(row["state"] or "").strip().lower()
            if current_state in {"refunded", "revoked"} and normalized_state != current_state:
                raise self._inactive_error(
                    license_status=current_state,
                    credential_status="revoked",
                    reason="terminal_purchase_state",
                    message="A permanently revoked purchase cannot change state",
                )
            now = self.now()
            conn.execute(
                """
                UPDATE purchase_records
                SET external_purchase_hash=?, identity_hash_key_id=?, state=?, state_reason=?, updated_at=?,
                    state_changed_at=CASE WHEN state<>? THEN ? ELSE state_changed_at END,
                    last_verified_at=?,
                    evidence_hash=COALESCE(NULLIF(?, ''), evidence_hash)
                WHERE purchase_id=?
                """,
                (
                    external_hash,
                    self.hash_secret_id,
                    normalized_state,
                    reason[:80],
                    now,
                    normalized_state,
                    now,
                    now,
                    evidence_hash,
                    str(row["purchase_id"]),
                ),
            )
            self._record_purchase_transition_conn(
                conn,
                purchase_id=str(row["purchase_id"]),
                license_id=str(row["license_id"]),
                from_state=current_state,
                to_state=normalized_state,
                reason_code=reason or f"purchase_{normalized_state}",
                source=provider,
            )
            conn.execute(
                "UPDATE relay_licenses SET status=?, updated_at=?, revoked_at=? WHERE license_id=?",
                (
                    license_status,
                    now,
                    None if license_status == "active" else now,
                    str(row["license_id"]),
                ),
            )
            if license_status != "active":
                conn.execute(
                    """
                    UPDATE relay_activations
                    SET status='revoked', revoked_at=?, revoke_reason=?
                    WHERE license_id=? AND status IN ('active', 'pending_commit')
                    """,
                    (now, f"purchase_{normalized_state}", str(row["license_id"])),
                )
            conn.commit()
            license_row = conn.execute(
                "SELECT * FROM relay_licenses WHERE license_id=?",
                (str(row["license_id"]),),
            ).fetchone()
            return self._license_from_row(license_row)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def begin_purchase_event(self, provider: str, event_id: str, event_type: str) -> bool:
        namespace = f"event:{provider.strip().lower()}"
        event_key = self._token_hash(namespace, event_id.strip())
        event_candidates = self._token_hash_candidates(namespace, event_id.strip())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            placeholders = ",".join("?" for _ in event_candidates)
            existing = conn.execute(
                f"SELECT event_key, status, created_at FROM purchase_events WHERE event_key IN ({placeholders})",
                tuple(value for _secret_id, value in event_candidates),
            ).fetchone()
            if existing:
                existing_key = str(existing["event_key"])
                retry = bool(str(existing["status"]) == "failed")
                if str(existing["status"]) == "processing":
                    try:
                        retry = self._parse_time(str(existing["created_at"])) <= datetime.now(timezone.utc) - timedelta(minutes=10)
                    except (TypeError, ValueError):
                        retry = True
                if retry:
                    conn.execute(
                        """
                        UPDATE purchase_events
                        SET status='processing', detail_code=NULL, created_at=?, processed_at=NULL
                        WHERE event_key=?
                        """,
                        (self.now(), existing_key),
                    )
                conn.commit()
                return retry
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO purchase_events (
                    event_key, provider, event_type, status, created_at, hash_secret_id
                ) VALUES (?, ?, ?, 'processing', ?, ?)
                """,
                (event_key, provider.strip().lower(), event_type[:80], self.now(), self.hash_secret_id),
            )
            if cursor.rowcount == 1:
                conn.commit()
                return True
            conn.commit()
            return False
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def finish_purchase_event(
        self,
        provider: str,
        event_id: str,
        *,
        status: str,
        detail_code: str = "",
        purchase_id: str = "",
        license_id: str = "",
    ) -> None:
        event_candidates = self._token_hash_candidates(
            f"event:{provider.strip().lower()}",
            event_id.strip(),
        )
        placeholders = ",".join("?" for _ in event_candidates)
        conn = self._connect()
        try:
            conn.execute(
                f"""
                UPDATE purchase_events
                SET status=?, detail_code=?, processed_at=?, purchase_id=?, license_id=?
                WHERE event_key IN ({placeholders})
                """,
                (
                    status[:32],
                    detail_code[:80],
                    self.now(),
                    purchase_id or None,
                    license_id or None,
                    *(value for _secret_id, value in event_candidates),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def create_checkout_claim(self, *, product_id: str = "") -> tuple[str, str]:
        checkout_ref = f"chk_{uuid.uuid4().hex}"
        result_secret = random_token("lfrs_", 32)
        conn = self._connect()
        try:
            self._insert_challenge(
                conn,
                purpose="checkout_result",
                token=result_secret,
                subject_ref=checkout_ref,
                payload={"state": "pending", "product_id": product_id.strip()},
                minutes=90,
                challenge_id=checkout_ref,
            )
            conn.commit()
            return checkout_ref, result_secret
        finally:
            conn.close()

    def bind_checkout_session(self, checkout_ref: str, session_id: str) -> None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payload_json FROM access_challenges WHERE challenge_id=? AND purpose='checkout_result'",
                (checkout_ref,),
            ).fetchone()
            if not row:
                raise InvalidChallenge("Checkout could not be found")
            payload = self._json_payload(row["payload_json"])
            payload["stripe_session_hash"] = self._token_hash("stripe-session", session_id)
            conn.execute(
                "UPDATE access_challenges SET payload_json=? WHERE challenge_id=?",
                (json.dumps(payload, separators=(",", ":")), checkout_ref),
            )
            conn.commit()
        finally:
            conn.close()

    def validate_checkout_session(self, checkout_ref: str, session_id: str) -> str:
        if not checkout_ref.strip() or not session_id.strip():
            raise InvalidChallenge("Stripe Checkout identity is incomplete")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payload_json FROM access_challenges WHERE challenge_id=? AND purpose='checkout_result'",
                (checkout_ref,),
            ).fetchone()
            if not row:
                raise InvalidChallenge("Checkout could not be found")
            payload = self._json_payload(row["payload_json"])
            expected = str(payload.get("stripe_session_hash") or "")
            actuals = [
                value for _secret_id, value in self._token_hash_candidates("stripe-session", session_id.strip())
            ]
            if not expected or not any(secrets.compare_digest(expected, actual) for actual in actuals):
                raise InvalidChallenge("Stripe Checkout does not match this purchase")
            return str(payload.get("product_id") or "")
        finally:
            conn.close()

    def create_attestation_challenge(self, *, platform: str, install_id: str, intent: str = "") -> str:
        clean_platform = platform.strip().lower()
        if clean_platform not in {"ios", "android"}:
            raise InvalidChallenge("Platform must be ios or android")
        if not install_id.strip():
            raise InvalidChallenge("Installation identity is required")
        clean_intent = intent.strip().lower()
        if clean_intent and clean_intent not in {"inspect", "companion", "standalone"}:
            raise InvalidChallenge("Mobile ownership intent is not supported")
        nonce = str(secrets.randbelow(2_000_000_000) + 1)
        conn = self._connect()
        try:
            self._insert_challenge(
                conn,
                purpose="mobile_attestation",
                token=nonce,
                install_id=install_id,
                subject_ref=clean_platform,
                payload={"intent": clean_intent},
                minutes=5,
            )
            conn.commit()
            return nonce
        finally:
            conn.close()

    def consume_attestation_challenge(
        self,
        *,
        platform: str,
        install_id: str,
        nonce: str,
        intent: str = "",
        proof_signed_at_ms: int = 0,
    ) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = self._challenge_for_token(conn, "mobile_attestation", nonce)
            self._validate_challenge_row(row)
            if str(row["subject_ref"] or "") != platform.strip().lower() or str(row["install_id"] or "") != install_id:
                raise InvalidChallenge("Mobile verification challenge does not match this installation")
            expected_intent = str(self._json_payload(row["payload_json"]).get("intent") or "")
            if expected_intent and expected_intent != intent.strip().lower():
                raise InvalidChallenge("Mobile verification challenge does not match this intent")
            try:
                proof_time = datetime.fromtimestamp(int(proof_signed_at_ms) / 1000.0, tz=timezone.utc)
            except (OverflowError, OSError, TypeError, ValueError) as exc:
                raise InvalidChallenge("Mobile ownership proof signing time is invalid") from exc
            challenge_time = self._parse_time(str(row["created_at"] or ""))
            now = datetime.now(timezone.utc)
            if proof_time < challenge_time - timedelta(seconds=10) or proof_time > now + timedelta(seconds=60):
                raise InvalidChallenge("Mobile ownership proof was not signed for this challenge window")
            conn.execute(
                "UPDATE access_challenges SET consumed_at=? WHERE challenge_id=?",
                (self.now(), str(row["challenge_id"])),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def claim_mobile_ownership_evidence(
        self,
        *,
        provider: str,
        evidence_hash: str,
        install_id: str,
    ) -> bool:
        """Bind one provider-signed proof to the first installation that uses it.

        The database receives keyed references only. Repeating a request from
        the same installation is safe and idempotent; presenting the captured
        evidence from a different installation is rejected.
        """
        clean_provider = provider.strip().lower()
        clean_evidence = evidence_hash.strip().lower()
        clean_install = install_id.strip()
        if clean_provider not in {"apple_app", "google_app"}:
            raise InvalidChallenge("Mobile ownership provider is not supported")
        if len(clean_evidence) != 64 or any(char not in "0123456789abcdef" for char in clean_evidence):
            raise InvalidChallenge("Mobile ownership evidence reference is invalid")
        if not clean_install:
            raise InvalidChallenge("Installation identity is required")
        evidence_ref = self._token_hash(f"mobile-evidence:{clean_provider}", clean_evidence)
        install_ref = self._token_hash("mobile-evidence-install", clean_install)
        now = self.now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT install_ref_hash FROM mobile_ownership_evidence
                WHERE provider=? AND evidence_hash=?
                """,
                (clean_provider, evidence_ref),
            ).fetchone()
            if existing and not secrets.compare_digest(str(existing["install_ref_hash"]), install_ref):
                raise InvalidChallenge("Mobile ownership proof was already used by another installation")
            if existing:
                conn.execute(
                    """
                    UPDATE mobile_ownership_evidence SET last_seen_at=?
                    WHERE provider=? AND evidence_hash=?
                    """,
                    (now, clean_provider, evidence_ref),
                )
                created = False
            else:
                conn.execute(
                    """
                    INSERT INTO mobile_ownership_evidence (
                        provider, evidence_hash, install_ref_hash, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (clean_provider, evidence_ref, install_ref, now, now),
                )
                created = True
            conn.commit()
            return created
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_mobile_license_claim(self, *, license_id: str, install_id: str) -> str:
        claim = random_token("lfrclaim_", 32)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT status FROM relay_licenses WHERE license_id=?",
                (license_id,),
            ).fetchone()
            if not row:
                raise LicenseNotFound("Relay Access license was not found")
            if str(row["status"]) != "active":
                raise LicenseInactive("Relay Access license is not active")
            now = self.now()
            conn.execute(
                """
                UPDATE access_challenges SET consumed_at=?
                WHERE purpose='mobile_license_claim' AND license_id=? AND install_id=? AND consumed_at IS NULL
                """,
                (now, license_id, install_id),
            )
            self._insert_challenge(
                conn,
                purpose="mobile_license_claim",
                token=claim,
                license_id=license_id,
                install_id=install_id,
                minutes=10,
            )
            conn.commit()
            return claim
        finally:
            conn.close()

    def create_remote_companion_ws_ticket(
        self,
        *,
        install_id: str,
        install_ref: str,
        activation_id: str = "",
        license_id: str = "",
        legacy_activation_hash: str = "",
    ) -> str:
        """Mint a one-minute, one-use WebSocket credential after HTTP authentication."""
        if not install_id.strip() or not install_ref.strip():
            raise InvalidChallenge("Remote Companion ticket identity is incomplete")
        licensed = bool(license_id.strip() or activation_id.strip())
        if licensed != bool(license_id.strip() and activation_id.strip()):
            raise InvalidChallenge("Remote Companion receiver identity is incomplete")
        if licensed == bool(legacy_activation_hash.strip()):
            raise InvalidChallenge("Remote Companion ticket must use one receiver identity")
        ticket = random_token("lfrws_", 32)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if licensed:
                active = conn.execute(
                    """
                    SELECT 1 FROM relay_activations a
                    JOIN relay_licenses l ON l.license_id=a.license_id
                    WHERE a.activation_id=? AND a.license_id=? AND a.install_id=?
                      AND a.status='active' AND l.status='active'
                    """,
                    (activation_id, license_id, install_id),
                ).fetchone()
                if not active:
                    raise LicenseInactive("Relay Access receiver is no longer active")
            self._insert_challenge(
                conn,
                purpose="remote_companion_ws",
                token=ticket,
                license_id=license_id or None,
                install_id=install_id,
                subject_ref=activation_id or legacy_activation_hash,
                payload={"install_ref": install_ref, "legacy": not licensed},
                minutes=1,
            )
            conn.commit()
            return ticket
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def consume_remote_companion_ws_ticket(self, *, ticket: str, install_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = self._challenge_for_token(conn, "remote_companion_ws", ticket)
            self._validate_challenge_row(row)
            # Burn a real one-use ticket before checking its bound receiver.
            # A copied ticket presented with the wrong installation must not
            # remain usable by a later request.
            conn.execute(
                "UPDATE access_challenges SET consumed_at=? WHERE challenge_id=?",
                (self.now(), str(row["challenge_id"])),
            )
            conn.commit()
            if str(row["install_id"] or "") != install_id:
                raise InvalidChallenge("Remote Companion ticket belongs to another installation")
            payload = self._json_payload(row["payload_json"])
            legacy = bool(payload.get("legacy"))
            purchase_environment = "production"
            if row["license_id"]:
                active = conn.execute(
                    """
                    SELECT p.environment
                    FROM relay_activations a
                    JOIN relay_licenses l ON l.license_id=a.license_id
                    LEFT JOIN purchase_records p ON p.license_id=l.license_id
                    WHERE a.activation_id=? AND a.license_id=? AND a.install_id=?
                      AND a.status='active' AND l.status='active'
                    ORDER BY p.updated_at DESC LIMIT 1
                    """,
                    (str(row["subject_ref"] or ""), str(row["license_id"]), install_id),
                ).fetchone()
                if not active:
                    raise LicenseInactive("Relay Access receiver is no longer active")
                purchase_environment = str(active["environment"] or "production")
                legacy = False
            elif not legacy or not row["subject_ref"]:
                raise InvalidChallenge("Remote Companion ticket has no receiver identity")
            return {
                "install_ref": str(payload.get("install_ref") or ""),
                "legacy": legacy,
                "legacy_activation_hash": str(row["subject_ref"] or "") if legacy else "",
                "license_id": str(row["license_id"] or ""),
                "purchase_environment": purchase_environment,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fulfill_checkout(self, checkout_ref: str, purchase: VerifiedPurchase) -> tuple[RelayLicense, str, bool]:
        license_record, key, created = self.fulfill_purchase(purchase)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payload_json FROM access_challenges WHERE challenge_id=? AND purpose='checkout_result'",
                (checkout_ref,),
            ).fetchone()
            if not row:
                raise InvalidChallenge("Checkout could not be found")
            payload = self._json_payload(row["payload_json"])
            payload.update({"state": "active", "license_id": license_record.license_id})
            conn.execute(
                """
                UPDATE access_challenges SET license_id=?, payload_json=? WHERE challenge_id=?
                """,
                (license_record.license_id, json.dumps(payload, separators=(",", ":")), checkout_ref),
            )
            conn.commit()
            return license_record, key, created
        finally:
            conn.close()

    def fail_checkout(self, checkout_ref: str, state: str = "failed") -> None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payload_json FROM access_challenges WHERE challenge_id=? AND purpose='checkout_result'",
                (checkout_ref,),
            ).fetchone()
            if not row:
                return
            payload = self._json_payload(row["payload_json"])
            payload["state"] = state[:24]
            conn.execute(
                "UPDATE access_challenges SET payload_json=? WHERE challenge_id=?",
                (json.dumps(payload, separators=(",", ":")), checkout_ref),
            )
            conn.commit()
        finally:
            conn.close()

    def checkout_result(self, checkout_ref: str, result_secret: str) -> dict[str, Any]:
        hashes = self._token_hash_candidates("challenge:checkout_result", result_secret)
        placeholders = ",".join("?" for _ in hashes)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"""
                SELECT * FROM access_challenges
                WHERE challenge_id=? AND purpose='checkout_result' AND token_hash IN ({placeholders})
                """,
                (checkout_ref, *(value for _secret_id, value in hashes)),
            ).fetchone()
            self._validate_challenge_row(row, allow_consumed=True)
            payload = self._json_payload(row["payload_json"])
            state = str(payload.get("state") or "pending")
            result: dict[str, Any] = {"state": state, "checkout_ref": checkout_ref}
            if state == "active" and row["license_id"]:
                license_row = conn.execute(
                    "SELECT * FROM relay_licenses WHERE license_id=?",
                    (str(row["license_id"]),),
                ).fetchone()
                result["license"] = self._license_from_row(license_row)
                if not row["consumed_at"]:
                    result["license_key"] = self._license_key_for_row(license_row)
                    self._record_key_delivery_conn(
                        conn,
                        license_row,
                        channel="browser",
                        purpose="stripe_checkout",
                        dedupe_key=f"checkout:{checkout_ref}",
                    )
                    conn.execute(
                        "UPDATE access_challenges SET consumed_at=? WHERE challenge_id=?",
                        (self.now(), checkout_ref),
                    )
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _record_key_delivery_conn(
        self,
        conn: sqlite3.Connection,
        license_row: sqlite3.Row,
        *,
        channel: str,
        purpose: str,
        dedupe_key: str,
        holder_id: str | None = None,
    ) -> str:
        now = self.now()
        delivery_id = f"delivery_{uuid.uuid4().hex}"
        conn.execute(
            """
            INSERT OR IGNORE INTO license_deliveries (
                delivery_id, license_id, holder_id, channel, purpose, key_version,
                dedupe_key, status, created_at, updated_at, consumed_at, delivered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'revealed', ?, ?, ?, ?)
            """,
            (
                delivery_id,
                str(license_row["license_id"]),
                holder_id or license_row["holder_id"],
                channel[:24],
                purpose[:48],
                int(license_row["key_version"] or 1),
                dedupe_key[:180],
                now,
                now,
                now,
                now,
            ),
        )
        conn.execute(
            """
            UPDATE relay_licenses
            SET first_delivered_at=COALESCE(first_delivered_at, ?), last_delivered_at=?, updated_at=?
            WHERE license_id=?
            """,
            (now, now, now, str(license_row["license_id"])),
        )
        existing = conn.execute(
            "SELECT delivery_id FROM license_deliveries WHERE dedupe_key=?",
            (dedupe_key[:180],),
        ).fetchone()
        return str(existing["delivery_id"] if existing else delivery_id)

    def queue_license_email(self, license_id: str, *, purpose: str = "initial") -> str:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM relay_licenses WHERE license_id=?", (license_id,)).fetchone()
            if not row:
                raise LicenseNotFound("Relay Access license was not found")
            if not row["holder_id"]:
                raise InvalidChallenge("Relay Access license does not have a verified delivery address")
            version = int(row["key_version"] or 1)
            dedupe_key = f"email:{license_id}:{version}:{purpose[:48]}"
            delivery_id = f"delivery_{uuid.uuid4().hex}"
            now = self.now()
            conn.execute(
                """
                INSERT OR IGNORE INTO license_deliveries (
                    delivery_id, license_id, holder_id, channel, purpose, key_version,
                    dedupe_key, status, created_at, updated_at, next_attempt_at
                ) VALUES (?, ?, ?, 'email', ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    delivery_id,
                    license_id,
                    str(row["holder_id"]),
                    purpose[:48],
                    version,
                    dedupe_key,
                    now,
                    now,
                    now,
                ),
            )
            existing = conn.execute(
                "SELECT delivery_id FROM license_deliveries WHERE dedupe_key=?",
                (dedupe_key,),
            ).fetchone()
            conn.commit()
            return str(existing["delivery_id"] if existing else delivery_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def claim_due_license_emails(self, *, limit: int = 10) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = self.now()
            stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            rows = conn.execute(
                """
                SELECT d.*, l.*, h.notification_email_ciphertext, h.notification_email_key_id
                FROM license_deliveries d
                JOIN relay_licenses l ON l.license_id=d.license_id
                JOIN license_holders h ON h.holder_id=d.holder_id
                WHERE d.channel='email'
                  AND d.key_version=l.key_version
                  AND l.status='active'
                  AND (
                    (d.status='pending' AND COALESCE(d.next_attempt_at, d.created_at)<=?)
                    OR (d.status='failed' AND d.next_attempt_at IS NOT NULL AND d.next_attempt_at<=?)
                    OR (d.status='sending' AND d.last_attempt_at<=?)
                  )
                ORDER BY d.created_at ASC LIMIT ?
                """,
                (now, now, stale, max(1, min(int(limit), 50))),
            ).fetchall()
            claimed: list[dict[str, Any]] = []
            for row in rows:
                delivery_id = str(row["delivery_id"])
                conn.execute(
                    """
                    UPDATE license_deliveries
                    SET status='sending', attempt_count=attempt_count+1,
                        last_attempt_at=?, updated_at=?, detail_code=NULL
                    WHERE delivery_id=?
                    """,
                    (now, now, delivery_id),
                )
                claimed.append(
                    {
                        "delivery_id": delivery_id,
                        "license_id": str(row["license_id"]),
                        "purpose": str(row["purpose"]),
                        "attempt_count": int(row["attempt_count"] or 0) + 1,
                        "email": self._open(
                            str(row["notification_email_key_id"] or "v1"),
                            "holder-notification-email",
                            str(row["notification_email_ciphertext"] or ""),
                        ),
                        "license_key": self._license_key_for_row(row),
                    }
                )
            conn.commit()
            return claimed
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def finish_license_email(self, delivery_id: str, *, sent: bool, detail_code: str = "") -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM license_deliveries WHERE delivery_id=? AND channel='email'",
                (delivery_id,),
            ).fetchone()
            if not row:
                raise InvalidChallenge("License delivery was not found")
            now = self.now()
            if sent:
                conn.execute(
                    """
                    UPDATE license_deliveries
                    SET status='sent', delivered_at=?, updated_at=?, next_attempt_at=NULL, detail_code=NULL
                    WHERE delivery_id=?
                    """,
                    (now, now, delivery_id),
                )
                conn.execute(
                    """
                    UPDATE relay_licenses
                    SET first_delivered_at=COALESCE(first_delivered_at, ?), last_delivered_at=?, updated_at=?
                    WHERE license_id=?
                    """,
                    (now, now, now, str(row["license_id"])),
                )
            else:
                attempts = int(row["attempt_count"] or 0)
                terminal = attempts >= 8
                delay = min(21_600, 60 * (5 ** max(0, min(attempts - 1, 4))))
                next_attempt = None if terminal else (
                    datetime.now(timezone.utc) + timedelta(seconds=delay)
                ).isoformat()
                conn.execute(
                    """
                    UPDATE license_deliveries
                    SET status=?, detail_code=?, next_attempt_at=?, updated_at=?
                    WHERE delivery_id=?
                    """,
                    (
                        "failed",
                        (detail_code[:64] + ":retry_limit")[:80] if terminal else detail_code[:80],
                        next_attempt,
                        now,
                        delivery_id,
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def check_rate_limit(
        self,
        *,
        subject: str,
        action: str,
        limit: int,
        window_seconds: int,
    ) -> None:
        seconds = max(1, int(window_seconds))
        maximum = max(1, int(limit))
        now_epoch = int(time.time())
        window = now_epoch - (now_epoch % seconds)
        subject_hash = self._token_hash(f"rate:{action[:40]}", subject or "unknown")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO access_rate_limits (subject_hash, action, window_started_at, count, updated_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(subject_hash, action, window_started_at)
                DO UPDATE SET count=count+1, updated_at=excluded.updated_at
                """,
                (subject_hash, action[:40], window, self.now()),
            )
            row = conn.execute(
                """
                SELECT count FROM access_rate_limits
                WHERE subject_hash=? AND action=? AND window_started_at=?
                """,
                (subject_hash, action[:40], window),
            ).fetchone()
            conn.commit()
            if int(row["count"] if row else 0) > maximum:
                raise AccessRateLimited(
                    "Too many Relay Access requests; try again shortly",
                    retry_after=max(1, window + seconds - now_epoch),
                )
        except AccessRateLimited:
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _license_by_key(self, conn: sqlite3.Connection, key: str) -> sqlite3.Row:
        hashes = [
            (secret_id, license_key_hash(secret, key))
            for secret_id, secret in self._hash_secrets.items()
        ]
        placeholders = ",".join("?" for _ in hashes)
        row = conn.execute(
            f"SELECT * FROM relay_licenses WHERE license_key_hmac IN ({placeholders})",
            tuple(value for _secret_id, value in hashes),
        ).fetchone()
        if not row:
            raise InvalidLicenseKey("Relay Access key is not valid")
        return row

    def activate(
        self,
        *,
        install_id: str,
        device_kind: str,
        device_name: str,
        license_key: str = "",
        activation_grant: str = "",
        confirm_move_token: str = "",
        prepare_only: bool = False,
    ) -> ActivationResult:
        if not install_id.strip():
            raise InvalidChallenge("Installation identity is required")
        if bool(license_key.strip()) == bool(activation_grant.strip()):
            raise InvalidChallenge("Provide either a license key or an activation grant")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            grant_row: sqlite3.Row | None = None
            if license_key:
                license_row = self._license_by_key(conn, license_key)
            else:
                grant_row = self._challenge_for_token(conn, "activation_grant", activation_grant)
                self._validate_challenge_row(grant_row)
                if grant_row["install_id"] and str(grant_row["install_id"]) != install_id:
                    raise InvalidChallenge("Activation grant belongs to another installation")
                license_row = conn.execute(
                    "SELECT * FROM relay_licenses WHERE license_id=?",
                    (str(grant_row["license_id"]),),
                ).fetchone()
            result = self._activate_license_conn(
                conn,
                license_row=license_row,
                install_id=install_id,
                device_kind=device_kind,
                device_name=device_name,
                confirm_move_token=confirm_move_token,
                grant_row=grant_row,
            )
            conn.commit()
            if (
                not prepare_only
                and result.activation_state == "pending_commit"
                and result.credential is not None
            ):
                return self.commit_activation(result.credential.credential, install_id=install_id)
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def activate_license(
        self,
        *,
        license_id: str = "",
        install_id: str,
        device_kind: str,
        device_name: str,
        activation_grant: str = "",
        confirm_move_token: str = "",
        prepare_only: bool = False,
    ) -> ActivationResult:
        """Activate a license already authorized by a verified store proof or holder grant."""
        if not install_id.strip():
            raise InvalidChallenge("Installation identity is required")
        if not license_id.strip() and not activation_grant.strip():
            raise InvalidChallenge("An authorized Relay Access license is required")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            grant_row: sqlite3.Row | None = None
            selected_license_id = license_id.strip()
            if activation_grant:
                grant_row = self._challenge_for_token(conn, "activation_grant", activation_grant)
                self._validate_challenge_row(grant_row)
                if grant_row["install_id"] and str(grant_row["install_id"]) != install_id:
                    raise InvalidChallenge("Activation grant belongs to another installation")
                grant_license_id = str(grant_row["license_id"] or "")
                if selected_license_id and grant_license_id != selected_license_id:
                    raise InvalidChallenge("Activation grant belongs to another license")
                selected_license_id = grant_license_id
            license_row = conn.execute(
                "SELECT * FROM relay_licenses WHERE license_id=?",
                (selected_license_id,),
            ).fetchone()
            result = self._activate_license_conn(
                conn,
                license_row=license_row,
                install_id=install_id,
                device_kind=device_kind,
                device_name=device_name,
                confirm_move_token=confirm_move_token,
                grant_row=grant_row,
            )
            conn.commit()
            if (
                not prepare_only
                and result.activation_state == "pending_commit"
                and result.credential is not None
            ):
                return self.commit_activation(result.credential.credential, install_id=install_id)
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _activate_license_conn(
        self,
        conn: sqlite3.Connection,
        *,
        license_row: sqlite3.Row | None,
        install_id: str,
        device_kind: str,
        device_name: str,
        confirm_move_token: str,
        grant_row: sqlite3.Row | None,
    ) -> ActivationResult:
        if not license_row:
            raise LicenseNotFound("Relay Access license was not found")
        if str(license_row["status"]) != "active":
            raise self._inactive_error(
                license_status=str(license_row["status"]),
                credential_status="unknown",
                message="Relay Access license is not active",
            )
        kind = device_kind.strip().lower()
        if kind not in {"desktop", "mobile_standalone"}:
            raise InvalidChallenge("Receiver type is not supported")
        target_name = (device_name or kind.replace("_", " ").title())[:80]
        license_id = str(license_row["license_id"])
        now = self.now()
        conn.execute(
            """
            UPDATE relay_activations
            SET status='revoked', revoked_at=?, revoke_reason='pending_commit_expired'
            WHERE license_id=? AND status='pending_commit'
              AND COALESCE(pending_expires_at, '')<=?
            """,
            (now, license_id, now),
        )
        active = conn.execute(
            "SELECT * FROM relay_activations WHERE license_id=? AND status='active'",
            (license_id,),
        ).fetchone()
        moving = bool(active and str(active["install_id"]) != install_id)
        if moving and not confirm_move_token:
            move_token = random_token("lfrm_", 32)
            self._insert_challenge(
                conn,
                purpose="confirm_move",
                token=move_token,
                holder_id=str(license_row["holder_id"]) if license_row["holder_id"] else None,
                license_id=license_id,
                install_id=install_id,
                subject_ref=str(active["activation_id"]),
                payload={"device_kind": kind, "device_name": target_name},
                minutes=10,
            )
            return ActivationResult(
                activated=False,
                license=self._license_from_row(license_row),
                move_token=move_token,
                current_receiver={
                    "device_kind": str(active["device_kind"]),
                    "device_name": str(active["device_name"]),
                    "activated_at": str(active["activated_at"]),
                },
            )
        move_row: sqlite3.Row | None = None
        if confirm_move_token:
            move_row = self._challenge_for_token(conn, "confirm_move", confirm_move_token)
            self._validate_challenge_row(move_row)
            move_payload = self._json_payload(move_row["payload_json"])
            if (
                not moving
                or str(move_row["license_id"] or "") != license_id
                or str(move_row["install_id"] or "") != install_id
                or str(move_row["subject_ref"] or "") != str(active["activation_id"])
                or str(move_payload.get("device_kind") or "") != kind
                or str(move_payload.get("device_name") or "") != target_name
            ):
                raise InvalidChallenge(
                    "Move confirmation is stale or does not match this receiver",
                    access_state="active",
                    credential_state="unknown",
                    reason_code="move_confirmation_stale",
                    current_receiver={
                        "device_kind": str(active["device_kind"]),
                        "device_name": str(active["device_name"]),
                    } if active else None,
                )

        # A preparation retry invalidates only the prior uncommitted secret.
        # It never touches the receiver that is currently serving data.
        conn.execute(
            """
            UPDATE relay_activations
            SET status='revoked', revoked_at=?, revoke_reason='pending_commit_superseded'
            WHERE license_id=? AND status='pending_commit'
            """,
            (now, license_id),
        )
        credential = random_token("lfr_", 32)
        credential_hash = self._token_hash("device-credential", credential)
        activation_id = f"act_{uuid.uuid4().hex}"
        credential_prefix = credential[:12]
        pending_expires_at = self._future(10)
        conn.execute(
            """
            INSERT INTO relay_activations (
                activation_id, license_id, install_id, device_kind, device_name,
                credential_hash, credential_prefix, credential_hash_secret_id,
                status, activated_at, last_seen_at, expected_activation_id,
                pending_expires_at, grant_challenge_id, move_challenge_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_commit', ?, NULL, ?, ?, ?, ?)
            """,
            (
                activation_id,
                license_id,
                install_id,
                kind,
                target_name,
                credential_hash,
                credential_prefix,
                self.hash_secret_id,
                now,
                str(active["activation_id"]) if active else None,
                pending_expires_at,
                str(grant_row["challenge_id"]) if grant_row is not None else None,
                str(move_row["challenge_id"]) if move_row is not None else None,
            ),
        )
        return ActivationResult(
            activated=False,
            activation_state="pending_commit",
            pending_expires_in=600,
            license=self._license_from_row(license_row),
            replaced_receiver=bool(active),
            credential=DeviceCredential(
                credential=credential,
                credential_prefix=credential_prefix,
                activation_id=activation_id,
                license_ref=license_id,
                install_id=install_id,
                device_kind=kind,
                device_name=target_name,
            ),
        )

    def commit_activation(self, credential: str, *, install_id: str) -> ActivationResult:
        """Commit a credential only after the client has persisted it safely.

        The currently active receiver is left untouched until this transaction.
        Replaying a successful commit is idempotent, while a stale expected
        receiver can never replace a newer one.
        """
        clean = credential.strip()
        if not clean.startswith("lfr_"):
            raise LicenseNotFound(
                "Relay Access credential was not found",
                credential_state="unknown",
                reason_code="credential_unknown",
            )
        hashes = self._token_hash_candidates("device-credential", clean)
        placeholders = ",".join("?" for _ in hashes)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"""
                SELECT a.*, l.status AS license_status, l.*
                FROM relay_activations a
                JOIN relay_licenses l ON l.license_id=a.license_id
                WHERE a.credential_hash IN ({placeholders})
                """,
                tuple(value for _secret_id, value in hashes),
            ).fetchone()
            if not row:
                raise LicenseNotFound(
                    "Relay Access credential was not found",
                    credential_state="unknown",
                    reason_code="credential_unknown",
                )
            status = str(row["status"] or "unknown")
            license_status = str(row["license_status"] or "revoked")
            if str(row["install_id"] or "") != install_id:
                raise self._inactive_error(
                    license_status=license_status,
                    credential_status=status,
                    reason="credential_install_mismatch",
                    message="Relay Access credential belongs to another installation",
                )
            if status == "active" and license_status == "active":
                conn.commit()
                return ActivationResult(
                    activated=True,
                    activation_state="active",
                    license=self._license_from_row(row),
                    credential=DeviceCredential(
                        credential=clean,
                        credential_prefix=str(row["credential_prefix"]),
                        activation_id=str(row["activation_id"]),
                        license_ref=str(row["license_id"]),
                        install_id=install_id,
                        device_kind=str(row["device_kind"]),
                        device_name=str(row["device_name"]),
                    ),
                )
            if status != "pending_commit":
                raise self._inactive_error(
                    license_status=license_status,
                    credential_status=status,
                    reason=str(row["revoke_reason"] or ""),
                    message="Relay Access credential can no longer be committed",
                )
            now = self.now()
            try:
                expired = self._parse_time(str(row["pending_expires_at"] or "")) <= datetime.now(timezone.utc)
            except (TypeError, ValueError):
                expired = True
            if expired:
                raise self._inactive_error(
                    license_status=license_status,
                    credential_status="revoked",
                    reason="pending_commit_expired",
                    message="Relay Access activation expired before it was committed",
                )
            if license_status != "active":
                raise self._inactive_error(
                    license_status=license_status,
                    credential_status="pending_commit",
                    message="Relay Access license is not active",
                )

            license_id = str(row["license_id"])
            active = conn.execute(
                "SELECT * FROM relay_activations WHERE license_id=? AND status='active'",
                (license_id,),
            ).fetchone()
            expected_activation_id = str(row["expected_activation_id"] or "")
            actual_activation_id = str(active["activation_id"] or "") if active else ""
            current_receiver = {
                "device_kind": str(active["device_kind"]),
                "device_name": str(active["device_name"]),
                "activated_at": str(active["activated_at"]),
            } if active else None
            if actual_activation_id != expected_activation_id:
                raise InvalidChallenge(
                    "The active receiver changed before this activation was committed",
                    access_state="active",
                    credential_state="pending_commit",
                    reason_code="activation_commit_stale",
                    current_receiver=current_receiver,
                )

            for challenge_column, purpose in (
                ("grant_challenge_id", "activation_grant"),
                ("move_challenge_id", "confirm_move"),
            ):
                challenge_id = str(row[challenge_column] or "")
                if not challenge_id:
                    continue
                challenge = conn.execute(
                    "SELECT * FROM access_challenges WHERE challenge_id=? AND purpose=?",
                    (challenge_id, purpose),
                ).fetchone()
                self._validate_challenge_row(challenge)
                if (
                    str(challenge["license_id"] or "") != license_id
                    or str(challenge["install_id"] or "") not in {"", install_id}
                ):
                    raise InvalidChallenge(
                        "Activation authorization no longer matches this installation",
                        access_state="active",
                        credential_state="pending_commit",
                        reason_code="activation_authorization_stale",
                    )
                if purpose == "confirm_move" and str(challenge["subject_ref"] or "") != expected_activation_id:
                    raise InvalidChallenge(
                        "Move confirmation no longer matches the active receiver",
                        access_state="active",
                        credential_state="pending_commit",
                        reason_code="move_confirmation_stale",
                        current_receiver=current_receiver,
                    )

            if active:
                conn.execute(
                    """
                    UPDATE relay_activations
                    SET status='replaced', revoked_at=?, revoke_reason='receiver_replaced'
                    WHERE activation_id=? AND status='active'
                    """,
                    (now, actual_activation_id),
                )
            conn.execute(
                """
                UPDATE relay_activations
                SET status='active', activated_at=?, last_seen_at=?, pending_expires_at=NULL
                WHERE activation_id=? AND status='pending_commit'
                """,
                (now, now, str(row["activation_id"])),
            )
            challenge_ids = [
                str(row[column] or "")
                for column in ("grant_challenge_id", "move_challenge_id")
                if str(row[column] or "")
            ]
            if challenge_ids:
                challenge_placeholders = ",".join("?" for _ in challenge_ids)
                conn.execute(
                    f"UPDATE access_challenges SET consumed_at=? WHERE challenge_id IN ({challenge_placeholders})",
                    (now, *challenge_ids),
                )
            updated = conn.execute(
                "SELECT * FROM relay_licenses WHERE license_id=?",
                (license_id,),
            ).fetchone()
            conn.commit()
            return ActivationResult(
                activated=True,
                activation_state="active",
                license=self._license_from_row(updated),
                replaced_receiver=bool(active),
                credential=DeviceCredential(
                    credential=clean,
                    credential_prefix=str(row["credential_prefix"]),
                    activation_id=str(row["activation_id"]),
                    license_ref=license_id,
                    install_id=install_id,
                    device_kind=str(row["device_kind"]),
                    device_name=str(row["device_name"]),
                ),
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def resolve_credential(self, credential: str, *, install_id: str = "") -> dict[str, Any]:
        clean = credential.strip()
        if not clean.startswith("lfr_"):
            raise LicenseNotFound(
                "Relay Access credential was not found",
                credential_state="unknown",
                reason_code="credential_unknown",
            )
        hashes = self._token_hash_candidates("device-credential", clean)
        placeholders = ",".join("?" for _ in hashes)
        conn = self._connect()
        try:
            row = conn.execute(
                f"""
                SELECT a.*, l.status AS license_status, l.product_code, l.purchase_source,
                       l.key_prefix, l.key_last_four, l.holder_id,
                       (
                           SELECT p.environment FROM purchase_records p
                           WHERE p.license_id=l.license_id ORDER BY p.updated_at DESC LIMIT 1
                       ) AS purchase_environment,
                       (
                           SELECT p.state_reason FROM purchase_records p
                           WHERE p.license_id=l.license_id ORDER BY p.updated_at DESC LIMIT 1
                       ) AS purchase_state_reason
                FROM relay_activations a
                JOIN relay_licenses l ON l.license_id=a.license_id
                WHERE a.credential_hash IN ({placeholders})
                """,
                tuple(value for _secret_id, value in hashes),
            ).fetchone()
            if not row:
                raise LicenseNotFound(
                    "Relay Access credential was not found",
                    credential_state="unknown",
                    reason_code="credential_unknown",
                )
            credential_status = str(row["status"] or "unknown")
            license_status = str(row["license_status"] or "revoked")
            current = conn.execute(
                """
                SELECT device_kind, device_name, activated_at
                FROM relay_activations
                WHERE license_id=? AND status='active'
                """,
                (str(row["license_id"]),),
            ).fetchone()
            current_receiver = {
                "device_kind": str(current["device_kind"]),
                "device_name": str(current["device_name"]),
                "activated_at": str(current["activated_at"]),
            } if current else None
            if credential_status != "active":
                raise self._inactive_error(
                    license_status=license_status,
                    credential_status=credential_status,
                    reason=str(row["revoke_reason"] or ""),
                    message="Relay Access credential is no longer active",
                    current_receiver=current_receiver,
                )
            if install_id and str(row["install_id"]) != install_id:
                raise self._inactive_error(
                    license_status=license_status,
                    credential_status="active",
                    reason="credential_install_mismatch",
                    message="Relay Access credential belongs to another installation",
                    current_receiver=current_receiver,
                )
            if license_status != "active":
                raise self._inactive_error(
                    license_status=license_status,
                    credential_status="revoked",
                    reason=str(row["purchase_state_reason"] or ""),
                    message="Relay Access license is not active",
                    current_receiver=current_receiver,
                )
            conn.execute(
                "UPDATE relay_activations SET last_seen_at=? WHERE activation_id=?",
                (self.now(), str(row["activation_id"])),
            )
            conn.commit()
            return dict(row)
        finally:
            conn.close()

    def status(self, credential: str, *, install_id: str = "") -> dict[str, Any]:
        row = self.resolve_credential(credential, install_id=install_id)
        return {
            "active": True,
            "access_state": "active",
            "reason_code": "license_active",
            "license_ref": str(row["license_id"]),
            "product_code": str(row["product_code"]),
            "purchase_source": str(row["purchase_source"]),
            "purchase_environment": str(row["purchase_environment"] or "production"),
            "device_kind": str(row["device_kind"]),
            "device_name": str(row["device_name"]),
            "receiver_role": "independent_receiver",
            "key_ref": f"{row['key_prefix']}…{row['key_last_four']}",
            "email_protected": bool(row["holder_id"]),
            "recovery_available": bool(row["holder_id"]),
            "transfer_available": True,
            "activated_at": str(row["activated_at"]),
            "last_seen_at": str(row["last_seen_at"] or ""),
            "seat_state": "active_receiver",
            "delivery_available": True,
            "environment": str(row["purchase_environment"] or "production"),
        }

    def deactivate(self, credential: str, *, install_id: str) -> dict[str, Any]:
        clean = credential.strip()
        if not clean.startswith("lfr_"):
            raise LicenseNotFound(
                "Relay Access credential was not found",
                credential_state="unknown",
                reason_code="credential_unknown",
            )
        hashes = self._token_hash_candidates("device-credential", clean)
        placeholders = ",".join("?" for _ in hashes)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"""
                SELECT a.activation_id, a.install_id, a.license_id, a.status, l.status AS license_status
                FROM relay_activations a
                JOIN relay_licenses l ON l.license_id=a.license_id
                WHERE a.credential_hash IN ({placeholders})
                """,
                tuple(value for _secret_id, value in hashes),
            ).fetchone()
            if not row:
                raise LicenseNotFound(
                    "Relay Access credential was not found",
                    credential_state="unknown",
                    reason_code="credential_unknown",
                )
            if str(row["install_id"]) != install_id:
                raise self._inactive_error(
                    license_status=str(row["license_status"] or "revoked"),
                    credential_status=str(row["status"] or "unknown"),
                    reason="credential_install_mismatch",
                    message="Relay Access credential belongs to another installation",
                )
            now = self.now()
            previous_state = str(row["status"] or "unknown")
            if previous_state in {"active", "pending_commit"}:
                conn.execute(
                    """
                    UPDATE relay_activations
                    SET status='deactivated', revoked_at=?, revoke_reason='self_deactivated'
                    WHERE activation_id=? AND status IN ('active', 'pending_commit')
                    """,
                    (now, str(row["activation_id"])),
                )
            active = conn.execute(
                """
                SELECT device_kind, device_name, activated_at
                FROM relay_activations WHERE license_id=? AND status='active'
                """,
                (str(row["license_id"]),),
            ).fetchone()
            conn.commit()
            return {
                "license_ref": str(row["license_id"]),
                "active": False,
                "access_state": self._safe_access_state(str(row["license_status"] or "revoked")),
                "credential_state": "deactivated" if previous_state in {"active", "pending_commit"} else previous_state,
                "reason_code": "receiver_released" if previous_state in {"active", "pending_commit"} else str(previous_state),
                "seat_state": "active_elsewhere" if active else "available",
                "current_main_device": {
                    "device_kind": str(active["device_kind"]),
                    "device_name": str(active["device_name"]),
                    "activated_at": str(active["activated_at"]),
                } if active else None,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def notification_email_for_license(self, license_id: str) -> str:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT h.notification_email_ciphertext, h.notification_email_key_id
                FROM relay_licenses l
                JOIN license_holders h ON h.holder_id=l.holder_id
                WHERE l.license_id=?
                """,
                (license_id,),
            ).fetchone()
            if not row or not row["notification_email_ciphertext"]:
                return ""
            return self._open(
                str(row["notification_email_key_id"] or "v1"),
                "holder-notification-email",
                str(row["notification_email_ciphertext"]),
            )
        finally:
            conn.close()

    def queue_magic_link_notification(self, delivery: MagicLinkDelivery) -> str:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            challenge = self._challenge_for_token(conn, "email_magic", delivery.token)
            self._validate_challenge_row(challenge)
            notification_id = f"notice_{uuid.uuid4().hex}"
            now = self.now()
            dedupe_key = f"magic:{challenge['challenge_id']}"
            conn.execute(
                """
                INSERT OR IGNORE INTO notification_outbox (
                    notification_id, channel, purpose, holder_id, license_id,
                    destination_ciphertext, payload_ciphertext, encryption_key_id,
                    dedupe_key, status, attempt_count, created_at, updated_at,
                    next_attempt_at, expires_at
                ) VALUES (?, 'email', ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?)
                """,
                (
                    notification_id,
                    f"magic_link:{delivery.purpose[:32]}",
                    str(challenge["holder_id"] or "") or None,
                    str(challenge["license_id"] or "") or None,
                    self._seal("notification-destination", delivery.email),
                    self._seal(
                        "notification-payload",
                        json.dumps(
                            {"token": delivery.token, "request_purpose": delivery.purpose[:32]},
                            separators=(",", ":"),
                        ),
                    ),
                    self.encryption_secret_id,
                    dedupe_key,
                    now,
                    now,
                    now,
                    str(challenge["expires_at"]),
                ),
            )
            existing = conn.execute(
                "SELECT notification_id FROM notification_outbox WHERE dedupe_key=?",
                (dedupe_key,),
            ).fetchone()
            conn.commit()
            return str(existing["notification_id"] if existing else notification_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def queue_receiver_move_notification(
        self,
        *,
        license_id: str,
        activation_id: str,
        device_name: str,
    ) -> str:
        email = self.notification_email_for_license(license_id)
        if not email:
            return ""
        conn = self._connect()
        try:
            now = self.now()
            notification_id = f"notice_{uuid.uuid4().hex}"
            dedupe_key = f"receiver-move:{activation_id}"
            conn.execute(
                """
                INSERT OR IGNORE INTO notification_outbox (
                    notification_id, channel, purpose, license_id, activation_id,
                    destination_ciphertext, payload_ciphertext, encryption_key_id,
                    dedupe_key, status, attempt_count, created_at, updated_at, next_attempt_at
                ) VALUES (?, 'email', 'receiver_move', ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
                """,
                (
                    notification_id,
                    license_id,
                    activation_id,
                    self._seal("notification-destination", email),
                    self._seal(
                        "notification-payload",
                        json.dumps({"device_name": device_name[:80]}, separators=(",", ":")),
                    ),
                    self.encryption_secret_id,
                    dedupe_key,
                    now,
                    now,
                    now,
                ),
            )
            conn.commit()
            return notification_id
        finally:
            conn.close()

    def queue_provider_operation(
        self,
        *,
        license_id: str,
        operation: str,
        dedupe_suffix: str = "",
    ) -> str:
        """Queue an acknowledgement or authority reconciliation durably.

        The provider handle (for example a Play purchase token or Apple app
        transaction ID) is decrypted only long enough to place it into this
        encrypted outbox.  Operator responses expose neither copy.
        """

        clean_operation = operation.strip().lower()
        if clean_operation not in {"acknowledge", "reconcile"}:
            raise InvalidChallenge("Provider operation is not supported")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT p.purchase_id, p.provider, p.product_id, p.environment,
                       p.reconciliation_handle_ciphertext, p.reconciliation_key_id
                FROM purchase_records p
                WHERE p.license_id=?
                """,
                (license_id,),
            ).fetchone()
            if not row:
                raise LicenseNotFound("Relay Access purchase was not found")
            encrypted_handle = str(row["reconciliation_handle_ciphertext"] or "")
            if not encrypted_handle:
                raise InvalidChallenge("Purchase cannot be reconciled automatically")
            provider = str(row["provider"] or "").strip().lower()
            handle = self._open(
                str(row["reconciliation_key_id"] or "v1"),
                f"provider-reconciliation:{provider}",
                encrypted_handle,
            )
            purchase_id = str(row["purchase_id"])
            notification_id = f"notice_{uuid.uuid4().hex}"
            suffix = dedupe_suffix.strip() or (
                "once" if clean_operation == "acknowledge"
                else datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )
            dedupe_key = f"provider:{clean_operation}:{purchase_id}:{suffix}"[:180]
            now = self.now()
            payload = json.dumps(
                {
                    "purchase_id": purchase_id,
                    "provider": provider,
                    "product_id": str(row["product_id"] or ""),
                    "environment": str(row["environment"] or ""),
                },
                separators=(",", ":"),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO notification_outbox (
                    notification_id, channel, purpose, license_id,
                    destination_ciphertext, payload_ciphertext, encryption_key_id,
                    dedupe_key, status, attempt_count, created_at, updated_at, next_attempt_at
                ) VALUES (?, 'provider', ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
                """,
                (
                    notification_id,
                    f"{provider}:{clean_operation}"[:64],
                    license_id,
                    self._seal("provider-operation-handle", handle),
                    self._seal("provider-operation-payload", payload),
                    self.encryption_secret_id,
                    dedupe_key,
                    now,
                    now,
                    now,
                ),
            )
            existing = conn.execute(
                "SELECT notification_id FROM notification_outbox WHERE dedupe_key=?",
                (dedupe_key,),
            ).fetchone()
            if clean_operation == "reconcile":
                conn.execute(
                    """
                    UPDATE purchase_records
                    SET next_reconcile_at=?, updated_at=? WHERE purchase_id=?
                    """,
                    (now, now, purchase_id),
                )
            conn.commit()
            return str(existing["notification_id"] if existing else notification_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def claim_due_provider_operations(self, *, limit: int = 10) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = self.now()
            stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            rows = conn.execute(
                """
                SELECT * FROM notification_outbox
                WHERE channel='provider' AND (
                    (status='pending' AND COALESCE(next_attempt_at, created_at)<=?)
                    OR (status='failed' AND next_attempt_at IS NOT NULL AND next_attempt_at<=?)
                    OR (status='sending' AND updated_at<=?)
                )
                ORDER BY created_at ASC LIMIT ?
                """,
                (now, now, stale, max(1, min(int(limit), 50))),
            ).fetchall()
            claimed: list[dict[str, Any]] = []
            for row in rows:
                key_id = str(row["encryption_key_id"] or "v1")
                try:
                    payload = json.loads(
                        self._open(
                            key_id,
                            "provider-operation-payload",
                            str(row["payload_ciphertext"] or ""),
                        ) or "{}"
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                handle = self._open(
                    key_id,
                    "provider-operation-handle",
                    str(row["destination_ciphertext"] or ""),
                )
                conn.execute(
                    """
                    UPDATE notification_outbox
                    SET status='sending', attempt_count=attempt_count+1,
                        updated_at=?, detail_code=NULL
                    WHERE notification_id=?
                    """,
                    (now, str(row["notification_id"])),
                )
                claimed.append(
                    {
                        "notification_id": str(row["notification_id"]),
                        "license_id": str(row["license_id"] or ""),
                        "purpose": str(row["purpose"] or ""),
                        "handle": handle,
                        "payload": payload,
                    }
                )
            conn.commit()
            return claimed
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def finish_provider_operation(
        self,
        notification_id: str,
        *,
        sent: bool,
        provider: str,
        purchase_id: str = "",
        detail_code: str = "",
    ) -> None:
        self.finish_notification(notification_id, sent=sent, detail_code=detail_code)
        now = self.now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if purchase_id:
                conn.execute(
                    """
                    UPDATE purchase_records
                    SET last_reconciled_at=CASE WHEN ? THEN ? ELSE last_reconciled_at END,
                        next_reconcile_at=?, updated_at=?
                    WHERE purchase_id=?
                    """,
                    (
                        1 if sent else 0,
                        now,
                        (datetime.now(timezone.utc) + timedelta(days=1 if sent else 0, minutes=0 if sent else 15)).isoformat(),
                        now,
                        purchase_id,
                    ),
                )
            conn.execute(
                """
                INSERT INTO provider_reconciliation_health (
                    provider, status, last_success_at, last_attempt_at,
                    next_attempt_at, detail_code, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    status=excluded.status,
                    last_success_at=COALESCE(excluded.last_success_at, provider_reconciliation_health.last_success_at),
                    last_attempt_at=excluded.last_attempt_at,
                    next_attempt_at=excluded.next_attempt_at,
                    detail_code=excluded.detail_code,
                    updated_at=excluded.updated_at
                """,
                (
                    provider[:40],
                    "healthy" if sent else "degraded",
                    now if sent else None,
                    now,
                    (datetime.now(timezone.utc) + timedelta(days=1 if sent else 0, minutes=0 if sent else 15)).isoformat(),
                    None if sent else (detail_code or "provider_operation_failed")[:80],
                    now,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mark_purchase_acknowledged(self, purchase_id: str) -> None:
        conn = self._connect()
        try:
            result = conn.execute(
                """
                UPDATE purchase_records
                SET acknowledgement_state='acknowledged', updated_at=?
                WHERE purchase_id=?
                """,
                (self.now(), purchase_id),
            )
            if result.rowcount != 1:
                raise LicenseNotFound("Relay Access purchase was not found")
            conn.commit()
        finally:
            conn.close()

    def queue_due_reconciliations(self, *, limit: int = 20) -> int:
        conn = self._connect()
        try:
            now = self.now()
            rows = conn.execute(
                """
                SELECT license_id, purchase_id
                FROM purchase_records
                WHERE reconciliation_handle_ciphertext IS NOT NULL
                  AND reconciliation_mode IN ('server_authoritative', 'device_and_server')
                  AND (provider='apple_app' OR state NOT IN ('refunded', 'revoked'))
                  AND (next_reconcile_at IS NULL OR next_reconcile_at<=?)
                ORDER BY COALESCE(next_reconcile_at, created_at) ASC LIMIT ?
                """,
                (now, max(1, min(int(limit), 100))),
            ).fetchall()
        finally:
            conn.close()
        queued = 0
        bucket = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for row in rows:
            try:
                self.queue_provider_operation(
                    license_id=str(row["license_id"]),
                    operation="reconcile",
                    dedupe_suffix=bucket,
                )
                queued += 1
            except Exception:
                continue
        return queued

    def claim_due_notifications(self, *, limit: int = 10) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = self.now()
            stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            rows = conn.execute(
                """
                SELECT * FROM notification_outbox
                WHERE channel='email' AND (
                    (status='pending' AND COALESCE(next_attempt_at, created_at)<=?)
                    OR (status='failed' AND next_attempt_at IS NOT NULL AND next_attempt_at<=?)
                    OR (status='sending' AND updated_at<=?)
                )
                ORDER BY created_at ASC LIMIT ?
                """,
                (now, now, stale, max(1, min(int(limit), 50))),
            ).fetchall()
            claimed: list[dict[str, Any]] = []
            for row in rows:
                key_id = str(row["encryption_key_id"] or "v1")
                destination = self._open(
                    key_id,
                    "notification-destination",
                    str(row["destination_ciphertext"] or ""),
                )
                try:
                    payload = json.loads(
                        self._open(
                            key_id,
                            "notification-payload",
                            str(row["payload_ciphertext"] or ""),
                        ) or "{}"
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                purpose = str(row["purpose"] or "")
                if purpose.startswith("magic_link:"):
                    token = str(payload.get("token") or "")
                    challenge = self._challenge_for_token(conn, "email_magic", token) if token else None
                    refresh = challenge is None or bool(challenge["consumed_at"])
                    if challenge is not None and not refresh:
                        try:
                            refresh = self._parse_time(str(challenge["expires_at"])) <= datetime.now(timezone.utc) + timedelta(minutes=1)
                        except (TypeError, ValueError):
                            refresh = True
                    if refresh:
                        token = random_token("lfrml_", 32)
                        self._insert_challenge(
                            conn,
                            purpose="email_magic",
                            token=token,
                            holder_id=str(row["holder_id"] or "") or None,
                            license_id=str(row["license_id"] or "") or None,
                            payload={
                                "request_purpose": str(payload.get("request_purpose") or "recovery")[:32],
                                "attach_license": bool(row["license_id"]),
                            },
                            minutes=15,
                        )
                        payload["token"] = token
                        expires_at = self._future(15)
                        conn.execute(
                            """
                            UPDATE notification_outbox
                            SET payload_ciphertext=?, encryption_key_id=?, expires_at=?
                            WHERE notification_id=?
                            """,
                            (
                                self._seal(
                                    "notification-payload",
                                    json.dumps(payload, separators=(",", ":")),
                                ),
                                self.encryption_secret_id,
                                expires_at,
                                str(row["notification_id"]),
                            ),
                        )
                    payload["token"] = token
                conn.execute(
                    """
                    UPDATE notification_outbox
                    SET status='sending', attempt_count=attempt_count+1,
                        updated_at=?, detail_code=NULL
                    WHERE notification_id=?
                    """,
                    (now, str(row["notification_id"])),
                )
                claimed.append(
                    {
                        "notification_id": str(row["notification_id"]),
                        "purpose": purpose,
                        "email": destination,
                        "payload": payload,
                    }
                )
            conn.commit()
            return claimed
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def finish_notification(self, notification_id: str, *, sent: bool, detail_code: str = "") -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT attempt_count FROM notification_outbox WHERE notification_id=?",
                (notification_id,),
            ).fetchone()
            if not row:
                raise InvalidChallenge("Notification was not found")
            now = self.now()
            if sent:
                conn.execute(
                    """
                    UPDATE notification_outbox
                    SET status='sent', delivered_at=?, updated_at=?, next_attempt_at=NULL, detail_code=NULL
                    WHERE notification_id=?
                    """,
                    (now, now, notification_id),
                )
            else:
                attempts = int(row["attempt_count"] or 0)
                terminal = attempts >= 8
                delay = min(21_600, 60 * (5 ** max(0, min(attempts - 1, 4))))
                next_attempt = None if terminal else (
                    datetime.now(timezone.utc) + timedelta(seconds=delay)
                ).isoformat()
                conn.execute(
                    """
                    UPDATE notification_outbox
                    SET status='failed', detail_code=?, next_attempt_at=?, updated_at=?
                    WHERE notification_id=?
                    """,
                    (
                        (detail_code or "delivery_failed")[:80],
                        next_attempt,
                        now,
                        notification_id,
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def request_magic_link(self, email: str, *, credential: str = "", purpose: str = "recovery") -> MagicLinkDelivery | None:
        normalized_email = self.normalize_email(email)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            license_id: str | None = None
            if credential.startswith("lfrclaim_"):
                claim = self._challenge_for_token(conn, "mobile_license_claim", credential.strip())
                self._validate_challenge_row(claim)
                license_id = str(claim["license_id"] or "")
                if not license_id:
                    raise LicenseNotFound("Relay Access license was not found")
                holder_id = self._holder_for_email(conn, normalized_email, create=True)
                conn.execute(
                    "UPDATE access_challenges SET consumed_at=? WHERE challenge_id=?",
                    (self.now(), str(claim["challenge_id"])),
                )
            elif credential.startswith("lfr_"):
                hashes = self._token_hash_candidates("device-credential", credential.strip())
                placeholders = ",".join("?" for _ in hashes)
                activation = conn.execute(
                    f"""
                    SELECT a.license_id FROM relay_activations a
                    JOIN relay_licenses l ON l.license_id=a.license_id
                    WHERE a.credential_hash IN ({placeholders}) AND a.status='active' AND l.status='active'
                    """,
                    tuple(value for _secret_id, value in hashes),
                ).fetchone()
                if not activation:
                    raise LicenseNotFound("Relay Access credential was not found")
                license_id = str(activation["license_id"])
                holder_id = self._holder_for_email(conn, normalized_email, create=True)
            else:
                holder_id = self._holder_for_email(conn, normalized_email, create=False)
                if not holder_id:
                    conn.rollback()
                    return None
            token = random_token("lfrml_", 32)
            self._insert_challenge(
                conn,
                purpose="email_magic",
                token=token,
                holder_id=holder_id,
                license_id=license_id,
                payload={"request_purpose": purpose[:32], "attach_license": bool(license_id)},
                minutes=15,
            )
            conn.commit()
            return MagicLinkDelivery(email=normalized_email, token=token, purpose=purpose[:32])
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def exchange_magic_link(self, token: str) -> HolderSession:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = self._challenge_for_token(conn, "email_magic", token)
            self._validate_challenge_row(row)
            holder_id = str(row["holder_id"] or "")
            if not holder_id:
                raise InvalidChallenge("Magic link has no holder")
            now = self.now()
            conn.execute(
                "UPDATE license_holders SET verified_at=COALESCE(verified_at, ?), last_seen_at=? WHERE holder_id=?",
                (now, now, holder_id),
            )
            if row["license_id"]:
                updated = conn.execute(
                    """
                    UPDATE relay_licenses SET holder_id=?, updated_at=?
                    WHERE license_id=? AND (holder_id IS NULL OR holder_id=?)
                    """,
                    (holder_id, now, str(row["license_id"]), holder_id),
                )
                if updated.rowcount != 1:
                    raise InvalidChallenge("License is already protected by another email")
            conn.execute(
                "UPDATE access_challenges SET consumed_at=? WHERE challenge_id=?",
                (now, str(row["challenge_id"])),
            )
            session_token = random_token("lfrhs_", 32)
            self._insert_challenge(
                conn,
                purpose="holder_session",
                token=session_token,
                holder_id=holder_id,
                minutes=15,
            )
            license_rows = conn.execute(
                "SELECT * FROM relay_licenses WHERE holder_id=? ORDER BY created_at DESC",
                (holder_id,),
            ).fetchall()
            delivered_license_id = str(row["license_id"] or "")
            delivered_key = ""
            if delivered_license_id:
                delivered_row = next(
                    (item for item in license_rows if str(item["license_id"]) == delivered_license_id),
                    None,
                )
                if delivered_row is None:
                    raise LicenseNotFound("Relay Access license was not found")
                # A mobile-created master key is revealed only during its first
                # verified delivery. Subsequent protection/recovery links open
                # management; recovering a lost key requires an explicit
                # rotation so the old key and receiver are revoked.
                if not delivered_row["first_delivered_at"]:
                    delivered_key = self._license_key_for_row(delivered_row)
                    self._record_key_delivery_conn(
                        conn,
                        delivered_row,
                        channel="browser",
                        purpose="verified_mobile_claim",
                        dedupe_key=f"magic:{row['challenge_id']}",
                        holder_id=holder_id,
                    )
                    version = int(delivered_row["key_version"] or 1)
                    now = self.now()
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO license_deliveries (
                            delivery_id, license_id, holder_id, channel, purpose, key_version,
                            dedupe_key, status, created_at, updated_at, next_attempt_at
                        ) VALUES (?, ?, ?, 'email', 'verified_mobile_claim', ?, ?, 'pending', ?, ?, ?)
                        """,
                        (
                            f"delivery_{uuid.uuid4().hex}",
                            delivered_license_id,
                            holder_id,
                            version,
                            f"email:{delivered_license_id}:{version}:verified_mobile_claim",
                            now,
                            now,
                            now,
                        ),
                    )
                else:
                    delivered_license_id = ""
            conn.commit()
            return HolderSession(
                token=session_token,
                holder_id=holder_id,
                licenses=tuple(self._license_from_row(item) for item in license_rows),
                delivered_license_id=delivered_license_id,
                license_key=delivered_key,
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_activation_grant(self, holder_session: str, license_id: str, *, install_id: str = "") -> str:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            session = self._challenge_for_token(conn, "holder_session", holder_session)
            self._validate_challenge_row(session)
            holder_id = str(session["holder_id"] or "")
            license_row = conn.execute(
                "SELECT * FROM relay_licenses WHERE license_id=? AND holder_id=?",
                (license_id, holder_id),
            ).fetchone()
            if not license_row:
                raise LicenseNotFound("Relay Access license was not found")
            if str(license_row["status"]) != "active":
                raise LicenseInactive("Relay Access license is not active")
            grant = random_token("lfrag_", 32)
            self._insert_challenge(
                conn,
                purpose="activation_grant",
                token=grant,
                holder_id=holder_id,
                license_id=license_id,
                install_id=install_id or None,
                minutes=10,
            )
            conn.commit()
            return grant
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def holder_license_summaries(self, holder_session: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            session = self._challenge_for_token(conn, "holder_session", holder_session)
            self._validate_challenge_row(session)
            rows = conn.execute(
                """
                SELECT l.*, a.device_kind, a.device_name, a.activated_at, a.last_seen_at
                FROM relay_licenses l
                LEFT JOIN relay_activations a
                  ON a.license_id=l.license_id AND a.status='active'
                WHERE l.holder_id=?
                ORDER BY l.created_at DESC
                """,
                (str(session["holder_id"] or ""),),
            ).fetchall()
            summaries: list[dict[str, Any]] = []
            for row in rows:
                delivery = conn.execute(
                    """
                    SELECT channel, purpose, status, attempt_count, updated_at
                    FROM license_deliveries
                    WHERE license_id=?
                    ORDER BY CASE WHEN channel='email' THEN 0 ELSE 1 END,
                             created_at DESC, delivery_id DESC
                    LIMIT 1
                    """,
                    (str(row["license_id"]),),
                ).fetchone()
                summaries.append({
                    "license": self._license_from_row(row),
                    "receiver": {
                        "device_kind": str(row["device_kind"] or ""),
                        "device_name": str(row["device_name"] or ""),
                        "activated_at": str(row["activated_at"] or ""),
                        "last_seen_at": str(row["last_seen_at"] or ""),
                    } if row["device_kind"] else None,
                    "key_delivery": {
                        "state": str(delivery["status"]),
                        "status": str(delivery["status"]),
                        "channel": str(delivery["channel"]),
                        "purpose": str(delivery["purpose"]),
                        "attempt_count": int(delivery["attempt_count"] or 0),
                        "updated_at": str(delivery["updated_at"]),
                    } if delivery else {
                        "state": "pending",
                        "status": "pending",
                        "channel": "",
                        "purpose": "",
                        "attempt_count": 0,
                        "updated_at": "",
                    },
                })
            return summaries
        finally:
            conn.close()

    def license_receiver_summary(self, license_id: str, *, current_install_id: str = "") -> dict[str, Any]:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT l.*, a.install_id, a.device_kind, a.device_name, a.activated_at, a.last_seen_at
                FROM relay_licenses l
                LEFT JOIN relay_activations a
                  ON a.license_id=l.license_id AND a.status='active'
                WHERE l.license_id=?
                """,
                (license_id,),
            ).fetchone()
            if not row:
                raise LicenseNotFound("Relay Access license was not found")
            receiver = None
            seat_state = "available"
            if row["device_kind"]:
                seat_state = (
                    "active_here"
                    if current_install_id and str(row["install_id"] or "") == current_install_id
                    else "active_elsewhere"
                )
                receiver = {
                    "device_kind": str(row["device_kind"] or ""),
                    "device_name": str(row["device_name"] or ""),
                    "activated_at": str(row["activated_at"] or ""),
                    "last_seen_at": str(row["last_seen_at"] or ""),
                }
            return {
                "license": self._license_from_row(row),
                "receiver": receiver,
                "seat_state": seat_state,
            }
        finally:
            conn.close()

    def rotate_license_key(self, holder_session: str, license_id: str) -> tuple[RelayLicense, str]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            session = self._challenge_for_token(conn, "holder_session", holder_session)
            self._validate_challenge_row(session)
            row = conn.execute(
                "SELECT * FROM relay_licenses WHERE license_id=? AND holder_id=?",
                (license_id, str(session["holder_id"] or "")),
            ).fetchone()
            if not row:
                raise LicenseNotFound("Relay Access license was not found")
            version = int(row["key_version"] or 1) + 1
            key = derive_license_key(self._key_secret, license_id, version)
            normalized = normalize_license_key(key)
            now = self.now()
            conn.execute(
                """
                UPDATE relay_licenses
                SET key_version=?, key_secret_id=?, hash_secret_id=?, license_key_hmac=?, key_prefix=?, key_last_four=?, updated_at=?
                WHERE license_id=?
                """,
                (
                    version,
                    self.key_secret_id,
                    self.hash_secret_id,
                    generated_license_key_hash(self._hash_secret, normalized),
                    key[:14],
                    normalized[-4:],
                    now,
                    license_id,
                ),
            )
            conn.execute(
                """
                UPDATE relay_activations
                SET status='revoked', revoked_at=?, revoke_reason='license_key_rotated'
                WHERE license_id=? AND status IN ('active', 'pending_commit')
                """,
                (now, license_id),
            )
            conn.execute(
                """
                UPDATE license_deliveries
                SET status='failed', next_attempt_at=NULL,
                    detail_code='superseded_by_key_rotation', updated_at=?
                WHERE license_id=? AND key_version<?
                  AND status IN ('pending', 'sending', 'failed')
                """,
                (now, license_id, version),
            )
            updated = conn.execute("SELECT * FROM relay_licenses WHERE license_id=?", (license_id,)).fetchone()
            self._record_key_delivery_conn(
                conn,
                updated,
                channel="browser",
                purpose="holder_key_rotation",
                dedupe_key=f"holder-rotate:{license_id}:{version}",
            )
            if updated["holder_id"]:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO license_deliveries (
                        delivery_id, license_id, holder_id, channel, purpose, key_version,
                        dedupe_key, status, created_at, updated_at, next_attempt_at
                    ) VALUES (?, ?, ?, 'email', 'holder_key_rotation', ?, ?, 'pending', ?, ?, ?)
                    """,
                    (
                        f"delivery_{uuid.uuid4().hex}",
                        license_id,
                        str(updated["holder_id"]),
                        version,
                        f"email:{license_id}:{version}:holder_key_rotation",
                        now,
                        now,
                        now,
                    ),
                )
            conn.commit()
            return self._license_from_row(updated), key
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def revoke_activation(self, holder_session: str, license_id: str) -> bool:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            session = self._challenge_for_token(conn, "holder_session", holder_session)
            self._validate_challenge_row(session)
            owned = conn.execute(
                "SELECT 1 FROM relay_licenses WHERE license_id=? AND holder_id=?",
                (license_id, str(session["holder_id"] or "")),
            ).fetchone()
            if not owned:
                raise LicenseNotFound("Relay Access license was not found")
            now = self.now()
            result = conn.execute(
                """
                UPDATE relay_activations
                SET status='revoked', revoked_at=?, revoke_reason='holder_revoked'
                WHERE license_id=? AND status IN ('active', 'pending_commit')
                """,
                (now, license_id),
            )
            conn.commit()
            return result.rowcount > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def admin_snapshot(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT l.license_id, l.product_code, l.purchase_source, l.status,
                       CASE WHEN l.holder_id IS NULL THEN 0 ELSE 1 END AS email_protected,
                       l.key_prefix, l.key_last_four, l.created_at, l.updated_at,
                       a.install_id, a.device_kind, a.device_name, a.activated_at, a.last_seen_at
                FROM relay_licenses l
                LEFT JOIN relay_activations a ON a.license_id=l.license_id AND a.status='active'
                ORDER BY l.created_at DESC LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["email_protected"] = bool(item.get("email_protected"))
                install_id = str(item.pop("install_id", "") or "")
                item["install_ref"] = self._token_hash("admin-install", install_id)[:12] if install_id else ""
                result.append(item)
            return result
        finally:
            conn.close()

    def admin_search(
        self,
        *,
        limit: int = 100,
        cursor: str = "",
        query: str = "",
        source: str = "",
        state: str = "",
    ) -> dict[str, Any]:
        page_size = max(1, min(int(limit), 200))
        clauses: list[str] = []
        params: list[Any] = []
        clean_source = source.strip().lower()
        clean_state = state.strip().lower()
        if clean_source:
            clauses.append("l.purchase_source=?")
            params.append(clean_source)
        if clean_state:
            clauses.append("l.status=?")
            params.append(clean_state)
        clean_query = query.strip()
        if clean_query:
            if "@" in clean_query:
                normalized = self.normalize_email(clean_query)
                hashes = self._hash_candidates("holder-email", normalized)
                placeholders = ",".join("?" for _ in hashes)
                clauses.append(f"h.email_hmac IN ({placeholders})")
                params.extend(value for _secret_id, value in hashes)
            else:
                escaped = clean_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                like = f"%{escaped}%"
                clauses.append(
                    "(l.license_id LIKE ? ESCAPE '\\' OR l.key_prefix LIKE ? ESCAPE '\\' "
                    "OR l.key_last_four LIKE ? ESCAPE '\\' OR l.purchase_source LIKE ? ESCAPE '\\')"
                )
                params.extend((like, like, like, like))
        count_where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        count_params = tuple(params)
        if cursor:
            try:
                padded = cursor + "=" * (-len(cursor) % 4)
                marker = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
                marker_created = str(marker["created_at"])
                marker_id = str(marker["license_id"])
            except Exception as exc:
                raise InvalidChallenge("Operator page cursor is invalid") from exc
            clauses.append("(l.created_at<? OR (l.created_at=? AND l.license_id<?))")
            params.extend((marker_created, marker_created, marker_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        conn = self._connect()
        try:
            total_row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM relay_licenses l
                LEFT JOIN license_holders h ON h.holder_id=l.holder_id
                {count_where}
                """,
                count_params,
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT l.license_id, l.product_code, l.purchase_source, l.status,
                       CASE WHEN l.holder_id IS NULL THEN 0 ELSE 1 END AS email_protected,
                       l.key_prefix, l.key_last_four, l.created_at, l.updated_at,
                       a.install_id, a.device_kind, a.device_name, a.activated_at, a.last_seen_at
                FROM relay_licenses l
                LEFT JOIN license_holders h ON h.holder_id=l.holder_id
                LEFT JOIN relay_activations a ON a.license_id=l.license_id AND a.status='active'
                {where}
                ORDER BY l.created_at DESC, l.license_id DESC LIMIT ?
                """,
                (*params, page_size + 1),
            ).fetchall()
            has_more = len(rows) > page_size
            visible = rows[:page_size]
            items: list[dict[str, Any]] = []
            for row in visible:
                item = dict(row)
                item["email_protected"] = bool(item.get("email_protected"))
                install_id = str(item.pop("install_id", "") or "")
                item["install_ref"] = self._token_hash("admin-install", install_id)[:12] if install_id else ""
                if item.get("device_name"):
                    item["device_name"] = str(item["device_name"])[:80]
                items.append(item)
            next_cursor = ""
            if has_more and visible:
                tail = visible[-1]
                encoded = json.dumps(
                    {"created_at": str(tail["created_at"]), "license_id": str(tail["license_id"])},
                    separators=(",", ":"),
                ).encode("utf-8")
                next_cursor = base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")
            return {
                "items": items,
                "next_cursor": next_cursor,
                "has_more": has_more,
                "total": int(total_row["total"] if total_row else 0),
            }
        finally:
            conn.close()

    def admin_license_detail(self, license_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            license_row = conn.execute("SELECT * FROM relay_licenses WHERE license_id=?", (license_id,)).fetchone()
            if not license_row:
                raise LicenseNotFound("Relay Access license was not found")
            activations = conn.execute(
                """
                SELECT install_id, device_kind, device_name, credential_prefix, status,
                       activated_at, last_seen_at, revoked_at, revoke_reason, pending_expires_at
                FROM relay_activations WHERE license_id=? ORDER BY activated_at DESC LIMIT 100
                """,
                (license_id,),
            ).fetchall()
            purchases = conn.execute(
                """
                SELECT provider, product_id, environment, state, state_reason,
                       evidence_hash, identity_kind, reconciliation_mode,
                       last_reconciled_at, next_reconcile_at, acknowledgement_state,
                       created_at, updated_at, last_verified_at, state_changed_at
                FROM purchase_records WHERE license_id=? ORDER BY updated_at DESC
                """,
                (license_id,),
            ).fetchall()
            deliveries = conn.execute(
                """
                SELECT channel, purpose, key_version, status, attempt_count,
                       created_at, updated_at, delivered_at, detail_code
                FROM license_deliveries WHERE license_id=? ORDER BY created_at DESC LIMIT 100
                """,
                (license_id,),
            ).fetchall()
            events = conn.execute(
                """
                SELECT event_key, provider, event_type, status, detail_code, created_at, processed_at
                FROM purchase_events WHERE license_id=? ORDER BY created_at DESC LIMIT 100
                """,
                (license_id,),
            ).fetchall()
            notifications = conn.execute(
                """
                SELECT channel, purpose, status, attempt_count, created_at, updated_at,
                       next_attempt_at, delivered_at, expires_at, detail_code
                FROM notification_outbox WHERE license_id=? ORDER BY created_at DESC LIMIT 100
                """,
                (license_id,),
            ).fetchall()
            transitions = conn.execute(
                """
                SELECT from_state, to_state, reason_code, source, created_at
                FROM purchase_state_transitions
                WHERE license_id=? ORDER BY created_at DESC LIMIT 100
                """,
                (license_id,),
            ).fetchall()
            return {
                "license": self._license_from_row(license_row),
                "activations": [
                    {
                        **{key: row[key] for key in row.keys() if key != "install_id"},
                        "install_ref": self._token_hash("admin-install", str(row["install_id"] or ""))[:12],
                    }
                    for row in activations
                ],
                "purchases": [
                    {
                        **{key: row[key] for key in row.keys() if key != "evidence_hash"},
                        "evidence_ref": str(row["evidence_hash"] or "")[:12],
                    }
                    for row in purchases
                ],
                "deliveries": [dict(row) for row in deliveries],
                "events": [
                    {
                        **{key: row[key] for key in row.keys() if key != "event_key"},
                        "event_ref": str(row["event_key"] or "")[:16],
                    }
                    for row in events
                ],
                "notifications": [dict(row) for row in notifications],
                "purchase_transitions": [dict(row) for row in transitions],
            }
        finally:
            conn.close()

    def admin_purchase_events(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT event_key, provider, event_type, status, detail_code, created_at, processed_at
                FROM purchase_events ORDER BY created_at DESC LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [
                {
                    **{key: row[key] for key in row.keys() if key != "event_key"},
                    "event_ref": str(row["event_key"] or "")[:16],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def admin_resolve_purchase_event(self, event_ref: str, *, action: str) -> dict[str, Any]:
        clean_ref = event_ref.strip().lower()
        clean_action = action.strip().lower()
        if len(clean_ref) != 16 or any(char not in "0123456789abcdef" for char in clean_ref):
            raise InvalidChallenge("Purchase event reference is invalid")
        if clean_action not in {"mark_resolved", "retry_reconciliation"}:
            raise InvalidChallenge("Purchase event action is not supported")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT event_key, provider, status, license_id
                FROM purchase_events WHERE event_key LIKE ?
                """,
                (f"{clean_ref}%",),
            ).fetchall()
            if len(rows) != 1:
                raise InvalidChallenge("Purchase event reference is ambiguous or missing")
            row = rows[0]
            now = self.now()
            if clean_action == "mark_resolved":
                conn.execute(
                    """
                    UPDATE purchase_events
                    SET status='processed', detail_code='operator_resolved', processed_at=?
                    WHERE event_key=?
                    """,
                    (now, str(row["event_key"])),
                )
            else:
                license_id = str(row["license_id"] or "")
                if not license_id:
                    raise InvalidChallenge("Unlinked event needs provider-side investigation before retry")
                conn.execute(
                    """
                    UPDATE purchase_events
                    SET status='reconciliation_required', detail_code='operator_retry_queued', processed_at=NULL
                    WHERE event_key=?
                    """,
                    (str(row["event_key"]),),
                )
            conn.commit()
            return {
                "event_ref": clean_ref,
                "status": "processed" if clean_action == "mark_resolved" else "reconciliation_required",
                "license_id": str(row["license_id"] or ""),
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def admin_delivery_snapshot(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT delivery_id, license_id, channel, purpose, key_version, status,
                       attempt_count, created_at, updated_at, delivered_at, next_attempt_at, detail_code
                FROM license_deliveries ORDER BY created_at DESC LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def admin_notification_snapshot(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT notification_id, license_id, channel, purpose, status,
                       attempt_count, created_at, updated_at, delivered_at,
                       next_attempt_at, expires_at, detail_code
                FROM notification_outbox ORDER BY created_at DESC LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def admin_reconciliation_snapshot(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT provider, status, last_success_at, last_attempt_at,
                       next_attempt_at, detail_code, updated_at
                FROM provider_reconciliation_health ORDER BY provider
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def cleanup(self, *, challenge_days: int = 7, audit_days: int = 180) -> dict[str, int]:
        challenge_cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, challenge_days))).isoformat()
        audit_cutoff = (datetime.now(timezone.utc) - timedelta(days=max(30, audit_days))).isoformat()
        rate_cutoff_epoch = int(time.time()) - (2 * 24 * 60 * 60)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            pending_activations = conn.execute(
                """
                UPDATE relay_activations
                SET status='revoked', revoked_at=?, revoke_reason='pending_commit_expired'
                WHERE status='pending_commit' AND COALESCE(pending_expires_at, '')<=?
                """,
                (self.now(), self.now()),
            ).rowcount
            challenges = conn.execute(
                """
                DELETE FROM access_challenges
                WHERE expires_at<? AND (consumed_at IS NOT NULL OR created_at<?)
                """,
                (self.now(), challenge_cutoff),
            ).rowcount
            rates = conn.execute(
                "DELETE FROM access_rate_limits WHERE window_started_at<?",
                (rate_cutoff_epoch,),
            ).rowcount
            deliveries = conn.execute(
                """
                DELETE FROM license_deliveries
                WHERE created_at<?
                  AND (status IN ('sent', 'revealed') OR (status='failed' AND next_attempt_at IS NULL))
                """,
                (audit_cutoff,),
            ).rowcount
            purchase_events = conn.execute(
                "DELETE FROM purchase_events WHERE created_at<? AND status='processed'",
                (audit_cutoff,),
            ).rowcount
            mobile_evidence = conn.execute(
                "DELETE FROM mobile_ownership_evidence WHERE last_seen_at<?",
                (challenge_cutoff,),
            ).rowcount
            notifications = conn.execute(
                """
                DELETE FROM notification_outbox
                WHERE created_at<? AND status IN ('sent', 'cancelled')
                """,
                (audit_cutoff,),
            ).rowcount
            conn.commit()
            return {
                "challenges": max(0, int(challenges)),
                "rate_limits": max(0, int(rates)),
                "deliveries": max(0, int(deliveries)),
                "purchase_events": max(0, int(purchase_events)),
                "mobile_evidence": max(0, int(mobile_evidence)),
                "pending_activations": max(0, int(pending_activations)),
                "notifications": max(0, int(notifications)),
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def admin_set_license_status(self, license_id: str, status: str) -> RelayLicense:
        normalized = status.strip().lower()
        if normalized not in {"active", "revoked", "suspended"}:
            raise InvalidChallenge("License status is not supported")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM relay_licenses WHERE license_id=?", (license_id,)).fetchone()
            if not row:
                raise LicenseNotFound("Relay Access license was not found")
            if normalized == "active":
                purchase = conn.execute(
                    """
                    SELECT state FROM purchase_records
                    WHERE license_id=? ORDER BY updated_at DESC LIMIT 1
                    """,
                    (license_id,),
                ).fetchone()
                if purchase and str(purchase["state"]).strip().lower() not in {"paid", "purchased"}:
                    raise LicenseInactive(
                        "The purchase authority must be active before this license can be reactivated"
                    )
            now = self.now()
            conn.execute(
                "UPDATE relay_licenses SET status=?, updated_at=?, revoked_at=? WHERE license_id=?",
                (normalized, now, None if normalized == "active" else now, license_id),
            )
            if normalized != "active":
                conn.execute(
                    """
                    UPDATE relay_activations SET status='revoked', revoked_at=?, revoke_reason='admin_license_status'
                    WHERE license_id=? AND status IN ('active', 'pending_commit')
                    """,
                    (now, license_id),
                )
            conn.commit()
            updated = conn.execute("SELECT * FROM relay_licenses WHERE license_id=?", (license_id,)).fetchone()
            return self._license_from_row(updated)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def admin_revoke_activation(self, license_id: str) -> bool:
        conn = self._connect()
        try:
            result = conn.execute(
                """
                UPDATE relay_activations SET status='revoked', revoked_at=?, revoke_reason='admin_revoked'
                WHERE license_id=? AND status IN ('active', 'pending_commit')
                """,
                (self.now(), license_id),
            )
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    def admin_retry_deliveries(self, license_id: str) -> int:
        conn = self._connect()
        try:
            row = conn.execute("SELECT 1 FROM relay_licenses WHERE license_id=?", (license_id,)).fetchone()
            if not row:
                raise LicenseNotFound("Relay Access license was not found")
            now = self.now()
            result = conn.execute(
                """
                UPDATE license_deliveries
                SET status='pending', next_attempt_at=?, updated_at=?, detail_code=NULL
                WHERE license_id=? AND channel='email' AND status='failed'
                  AND key_version=(
                    SELECT key_version FROM relay_licenses WHERE license_id=?
                  )
                  AND COALESCE(detail_code, '')<>'superseded_by_key_rotation'
                """,
                (now, now, license_id, license_id),
            )
            conn.commit()
            return max(0, int(result.rowcount))
        finally:
            conn.close()

    def admin_retry_notifications(self, license_id: str) -> int:
        conn = self._connect()
        try:
            row = conn.execute("SELECT 1 FROM relay_licenses WHERE license_id=?", (license_id,)).fetchone()
            if not row:
                raise LicenseNotFound("Relay Access license was not found")
            now = self.now()
            result = conn.execute(
                """
                UPDATE notification_outbox
                SET status='pending', next_attempt_at=?, updated_at=?, detail_code=NULL
                WHERE channel='email' AND status='failed' AND (
                    license_id=? OR (
                        license_id IS NULL
                        AND holder_id=(SELECT holder_id FROM relay_licenses WHERE license_id=?)
                    )
                )
                """,
                (now, now, license_id, license_id),
            )
            conn.commit()
            return max(0, int(result.rowcount))
        finally:
            conn.close()

    def admin_retry_reconciliation(self, license_id: str) -> str:
        return self.queue_provider_operation(
            license_id=license_id,
            operation="reconcile",
            dedupe_suffix=f"operator-{uuid.uuid4().hex}",
        )

    def admin_rotate_license_key(self, license_id: str) -> RelayLicense:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM relay_licenses WHERE license_id=?", (license_id,)).fetchone()
            if not row:
                raise LicenseNotFound("Relay Access license was not found")
            if str(row["status"] or "").strip().lower() != "active":
                raise LicenseInactive("Only an active Relay Access license can rotate its key")
            if not row["holder_id"]:
                raise InvalidChallenge("Protect this license with a verified email before rotating its key")
            version = int(row["key_version"] or 1) + 1
            key = derive_license_key(self._key_secret, license_id, version)
            normalized = normalize_license_key(key)
            now = self.now()
            conn.execute(
                """
                UPDATE relay_licenses
                SET key_version=?, key_secret_id=?, hash_secret_id=?, license_key_hmac=?, key_prefix=?, key_last_four=?, updated_at=?
                WHERE license_id=?
                """,
                (
                    version,
                    self.key_secret_id,
                    self.hash_secret_id,
                    generated_license_key_hash(self._hash_secret, normalized),
                    key[:14],
                    normalized[-4:],
                    now,
                    license_id,
                ),
            )
            conn.execute(
                """
                UPDATE relay_activations
                SET status='revoked', revoked_at=?, revoke_reason='license_key_rotated'
                WHERE license_id=? AND status IN ('active', 'pending_commit')
                """,
                (now, license_id),
            )
            conn.execute(
                """
                UPDATE license_deliveries
                SET status='failed', next_attempt_at=NULL,
                    detail_code='superseded_by_key_rotation', updated_at=?
                WHERE license_id=? AND key_version<?
                  AND status IN ('pending', 'sending', 'failed')
                """,
                (now, license_id, version),
            )
            updated = conn.execute("SELECT * FROM relay_licenses WHERE license_id=?", (license_id,)).fetchone()
            conn.execute(
                """
                INSERT INTO license_deliveries (
                    delivery_id, license_id, holder_id, channel, purpose, key_version,
                    dedupe_key, status, created_at, updated_at, next_attempt_at
                ) VALUES (?, ?, ?, 'email', 'admin_key_rotation', ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    f"delivery_{uuid.uuid4().hex}",
                    license_id,
                    str(updated["holder_id"]),
                    version,
                    f"email:{license_id}:{version}:admin_key_rotation",
                    now,
                    now,
                    now,
                ),
            )
            conn.commit()
            return self._license_from_row(updated)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _insert_challenge(
        self,
        conn: sqlite3.Connection,
        *,
        purpose: str,
        token: str,
        holder_id: str | None = None,
        license_id: str | None = None,
        install_id: str | None = None,
        subject_ref: str | None = None,
        payload: dict[str, Any] | None = None,
        minutes: int,
        challenge_id: str | None = None,
    ) -> str:
        identifier = challenge_id or f"challenge_{uuid.uuid4().hex}"
        conn.execute(
            """
            INSERT INTO access_challenges (
                challenge_id, purpose, token_hash, holder_id, license_id, install_id,
                subject_ref, payload_json, created_at, expires_at, hash_secret_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier,
                purpose,
                self._token_hash(f"challenge:{purpose}", token),
                holder_id,
                license_id,
                install_id,
                subject_ref,
                json.dumps(payload or {}, separators=(",", ":")),
                self.now(),
                self._future(minutes),
                self.hash_secret_id,
            ),
        )
        return identifier

    def _challenge_for_token(self, conn: sqlite3.Connection, purpose: str, token: str) -> sqlite3.Row | None:
        hashes = self._token_hash_candidates(f"challenge:{purpose}", token.strip())
        placeholders = ",".join("?" for _ in hashes)
        return conn.execute(
            f"SELECT * FROM access_challenges WHERE purpose=? AND token_hash IN ({placeholders})",
            (purpose, *(value for _secret_id, value in hashes)),
        ).fetchone()

    def _validate_challenge_row(self, row: sqlite3.Row | None, *, allow_consumed: bool = False) -> None:
        if not row:
            raise InvalidChallenge("Access link is invalid")
        if row["consumed_at"] and not allow_consumed:
            raise InvalidChallenge("Access link has already been used")
        try:
            expired = self._parse_time(str(row["expires_at"])) <= datetime.now(timezone.utc)
        except (TypeError, ValueError):
            expired = True
        if expired:
            raise InvalidChallenge("Access link has expired")

    @staticmethod
    def _json_payload(value: Any) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
