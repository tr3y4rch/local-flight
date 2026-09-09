"""Private operator workflows. Public callers only receive scoped confirmation results.

This mixin uses LicenseService's connection/cryptography primitives so that
authority checks and operator writes share the same transaction boundaries.
"""

from __future__ import annotations

import json
import base64
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from .crypto import (
    derive_license_key,
    generated_license_key_hash,
    normalize_license_key,
    random_token,
    keyed_hash,
)
from .models import (
    InvalidChallenge,
    LicenseInactive,
    LicenseNotFound,
    PurchaseEnvironmentMismatch,
)


def safe_operator_text(value: str, limit: int = 2000) -> str:
    text = str(value or "").strip()[:limit]
    text = re.sub(r"(?i)\b(?:lfra[-\s]?)[a-z0-9\s-]{12,}", "[redacted key]", text)
    text = re.sub(
        r"(?i)\b(?:lfr[a-z]*_|lfm_|sk_(?:test|live)_|whsec_)[a-z0-9_-]+",
        "[redacted credential]",
        text,
    )
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", "[redacted email]", text)
    text = re.sub(
        r"(?i)(?:token|secret|password|api[_-]?key)\s*[:=]\s*\S+",
        "[redacted secret]",
        text,
    )
    return text


def masked_email(value: str) -> str:
    local, separator, domain = str(value or "").partition("@")
    return f"{local[:1]}***@{domain}" if separator else "Not protected"


class OperatorSupportMixin:
    @contextmanager
    def _operator_connection(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _license_row(self, conn: sqlite3.Connection, license_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM relay_licenses WHERE license_id=?", (license_id,)
        ).fetchone()
        if row is None:
            raise LicenseNotFound("Relay Access license was not found")
        return row

    def _authority_conn(
        self, conn: sqlite3.Connection, license_id: str, *, active: bool = True
    ) -> dict[str, Any]:
        row = self._license_row(conn, license_id)
        grant = conn.execute(
            "SELECT * FROM operator_grants WHERE license_id=?", (license_id,)
        ).fetchone()
        if grant is not None:
            environment = str(grant["environment"])
            expected = (
                "production" if self.deployment_environment == "production" else "test"
            )
            if self.deployment_environment and environment != expected:
                raise PurchaseEnvironmentMismatch(
                    "Operator grant belongs to a different relay environment"
                )
            expired = bool(
                grant["expires_at"]
                and self._parse_time(grant["expires_at"])
                <= self._parse_time(self.now())
            )
            state = "expired" if expired else str(grant["status"])
            valid = state == "issued"
            source = "operator_" + str(grant["kind"])
            expires_at = grant["expires_at"]
        else:
            purchase = conn.execute(
                "SELECT * FROM purchase_records WHERE license_id=?", (license_id,)
            ).fetchone()
            # Never turn a missing operator authority into a paid production license.
            if purchase is None or str(row["purchase_source"]).startswith("operator_"):
                raise LicenseInactive(
                    "License authority is missing",
                    reason_code="license_authority_missing",
                )
            environment = str(purchase["environment"])
            state = str(purchase["state"])
            valid = state in {"paid", "purchased"}
            source, expires_at = str(purchase["provider"]), None
        if active and (not valid or row["status"] != "active"):
            raise LicenseInactive(
                (
                    "Operator access has expired. Contact the issuer."
                    if state == "expired"
                    else "Relay Access license is not active"
                ),
                access_state=(
                    "revoked"
                    if state == "expired"
                    else self._safe_access_state(str(row["status"]))
                ),
                reason_code=(
                    "license_expired" if state == "expired" else "license_inactive"
                ),
            )
        return {
            "source": source,
            "environment": environment,
            "expires_at": expires_at,
            "authority_state": state,
            "effective_state": "expired" if state == "expired" else str(row["status"]),
            "grant_id": str(grant["grant_id"]) if grant else "",
        }

    def authority(self, license_id: str, *, active: bool = True) -> dict[str, Any]:
        with self._operator_connection() as conn:
            return self._authority_conn(conn, license_id, active=active)

    def _operator_reason(self, value: str) -> str:
        reason = safe_operator_text(value)
        if not reason:
            raise InvalidChallenge("An operator reason is required")
        return reason

    def _request_id(self, value: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", value or ""):
            raise InvalidChallenge("A stable operation request identifier is required")
        return value

    def _audit_conn(
        self,
        conn,
        *,
        action: str,
        target: str,
        request_id: str,
        reason: str,
        license_id: str = "",
        before: dict | None = None,
        after: dict | None = None,
        outcome: str = "completed",
        actor: str = "owner",
    ) -> None:
        conn.execute(
            """INSERT OR IGNORE INTO operator_audit
            (event_id,license_id,target_ref,actor,action,request_id,reason_ciphertext,encryption_key_id,outcome,before_json,after_json,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "audit_" + uuid.uuid4().hex,
                license_id or None,
                target,
                actor,
                action,
                request_id,
                self._seal("operator-reason", safe_operator_text(reason)),
                self.encryption_secret_id,
                outcome,
                json.dumps(before or {}),
                json.dumps(after or {}),
                self.now(),
            ),
        )

    def _audit_replay(
        self, conn, action: str, request_id: str, target: str
    ) -> dict | None:
        row = conn.execute(
            "SELECT * FROM operator_audit WHERE action=? AND request_id=?",
            (action, request_id),
        ).fetchone()
        if row:
            if row["target_ref"] != target:
                raise InvalidChallenge(
                    "Operation identifier was already used for another target"
                )
            return json.loads(row["after_json"])
        return None

    def _expiry(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            parsed = self._parse_time(value)
            if parsed <= self._parse_time(self.now()):
                raise ValueError
            return parsed.isoformat()
        except (ValueError, TypeError, OverflowError) as exc:
            raise InvalidChallenge("Expiry must be a future date and time") from exc

    def _holder_email_conn(self, conn, holder_id: str, *, verified: bool = True) -> str:
        holder = conn.execute(
            "SELECT * FROM license_holders WHERE holder_id=?", (holder_id,)
        ).fetchone()
        if not holder or (verified and not holder["verified_at"]):
            raise InvalidChallenge("A verified protected email address is required")
        return self._open(
            holder["notification_email_key_id"],
            "holder-notification-email",
            holder["notification_email_ciphertext"],
        )

    def _notice_conn(
        self,
        conn,
        *,
        email: str,
        purpose: str,
        payload: dict,
        dedupe: str,
        license_id: str = "",
        holder_id: str = "",
        expires_at: str | None = None,
    ) -> str:
        ref = "notice_" + uuid.uuid4().hex
        now = self.now()
        conn.execute(
            """INSERT OR IGNORE INTO notification_outbox
            (notification_id,channel,purpose,license_id,destination_ciphertext,payload_ciphertext,encryption_key_id,dedupe_key,status,created_at,updated_at,next_attempt_at,expires_at)
            VALUES (?,'email',?,?,?,?,?,?,'pending',?,?,?,?)""",
            (
                ref,
                purpose,
                license_id or None,
                self._seal("notification-destination", email),
                self._seal("notification-payload", json.dumps(payload)),
                self.encryption_secret_id,
                dedupe,
                now,
                now,
                now,
                expires_at,
            ),
        )
        if holder_id:
            conn.execute(
                "UPDATE notification_outbox SET holder_id=? WHERE notification_id=?",
                (holder_id, ref),
            )
        subject_ref = payload.get("grant_id") or payload.get("change_id")
        if subject_ref:
            conn.execute(
                "UPDATE notification_outbox SET subject_ref=? WHERE notification_id=?",
                (subject_ref, ref),
            )
        return str(
            conn.execute(
                "SELECT notification_id FROM notification_outbox WHERE dedupe_key=?",
                (dedupe,),
            ).fetchone()[0]
        )

    def _grant_invitation_conn(self, conn, grant, *, request_id: str) -> None:
        conn.execute(
            "UPDATE access_challenges SET consumed_at=? WHERE purpose='operator_claim' AND subject_ref=? AND consumed_at IS NULL",
            (self.now(), grant["grant_id"]),
        )
        token = random_token("lfrop_", 32)
        expiry = self._parse_time(self.now()) + timedelta(hours=24)
        if grant["expires_at"]:
            expiry = min(expiry, self._parse_time(grant["expires_at"]))
        self._insert_challenge(
            conn,
            purpose="operator_claim",
            token=token,
            subject_ref=grant["grant_id"],
            minutes=1440,
        )
        challenge = self._challenge_for_token(conn, "operator_claim", token)
        conn.execute(
            "UPDATE access_challenges SET expires_at=? WHERE challenge_id=?",
            (expiry.isoformat(), challenge["challenge_id"]),
        )
        conn.execute(
            "UPDATE operator_grants SET invitation_expires_at=?,updated_at=? WHERE grant_id=?",
            (expiry.isoformat(), self.now(), grant["grant_id"]),
        )
        self._notice_conn(
            conn,
            email=self._open(
                grant["encryption_key_id"], "operator-email", grant["email_ciphertext"]
            ),
            purpose="operator:invitation",
            payload={
                "token": token,
                "grant_id": grant["grant_id"],
                "expires_at": grant["expires_at"],
                "kind": grant["kind"],
            },
            dedupe="operator-invitation:" + request_id,
            expires_at=expiry.isoformat(),
        )

    def issue_operator_grant(
        self,
        *,
        kind: str,
        email: str,
        reason: str,
        request_id: str,
        expires_at: str | None = None,
    ) -> dict:
        reason, request_id = self._operator_reason(reason), self._request_id(request_id)
        email, expiry = self.normalize_email(email), self._expiry(expires_at)
        expected_kind = (
            "complimentary" if self.deployment_environment == "production" else "test"
        )
        if (
            self.deployment_environment not in {"production", "staging"}
            or kind != expected_kind
        ):
            raise InvalidChallenge(
                "Grant type is not permitted in this relay environment"
            )
        default_test_duration = kind == "test" and expires_at == ""
        request_values = json.dumps(
            [
                kind,
                email,
                reason,
                "default_seven_days" if default_test_duration else expiry,
            ]
        )
        fingerprint = self._token_hash("operator-request", request_values)
        with self._operator_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM operator_grants WHERE request_id=?", (request_id,)
            ).fetchone()
            if existing:
                expected_fingerprint = keyed_hash(
                    self._hash_secrets[existing["hash_key_id"]],
                    "operator-request",
                    request_values,
                )
                if existing["request_fingerprint"] != expected_fingerprint:
                    raise InvalidChallenge(
                        "Operation identifier was already used with different values"
                    )
                return self._grant_summary(existing)
            ref, now = "grant_" + uuid.uuid4().hex, self.now()
            if default_test_duration:
                expiry = (self._parse_time(now) + timedelta(days=7)).isoformat()
            conn.execute(
                """INSERT INTO operator_grants
                (grant_id,kind,environment,status,email_ciphertext,email_hmac,hash_key_id,encryption_key_id,reason_ciphertext,request_id,request_fingerprint,expires_at,invitation_expires_at,created_at,updated_at)
                VALUES (?,?,?,'pending',?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ref,
                    kind,
                    "production" if kind == "complimentary" else "test",
                    self._seal("operator-email", email),
                    self._email_hmac(email),
                    self.hash_secret_id,
                    self.encryption_secret_id,
                    self._seal("operator-reason", reason),
                    request_id,
                    fingerprint,
                    expiry,
                    now,
                    now,
                    now,
                ),
            )
            grant = conn.execute(
                "SELECT * FROM operator_grants WHERE grant_id=?", (ref,)
            ).fetchone()
            self._grant_invitation_conn(conn, grant, request_id=request_id)
            result = self._grant_summary(
                conn.execute(
                    "SELECT * FROM operator_grants WHERE grant_id=?", (ref,)
                ).fetchone()
            )
            self._audit_conn(
                conn,
                action="issue_grant",
                target=ref,
                request_id=request_id,
                reason=reason,
                after=result,
            )
            return result

    def _grant_summary(self, row) -> dict:
        expired = bool(
            row["expires_at"]
            and self._parse_time(row["expires_at"]) <= self._parse_time(self.now())
        )
        return {
            key: row[key]
            for key in (
                "grant_id",
                "license_id",
                "kind",
                "environment",
                "expires_at",
                "invitation_expires_at",
                "created_at",
                "updated_at",
            )
        } | {
            "status": "expired" if expired else row["status"],
            "recipient": masked_email(
                self._open(
                    row["encryption_key_id"], "operator-email", row["email_ciphertext"]
                )
            ),
        }

    def inspect_operator_confirmation(self, token: str, *, kind: str) -> dict:
        purpose = "operator_claim" if kind == "invitation" else "operator_email_change"
        with self._operator_connection() as conn:
            challenge = self._challenge_for_token(conn, purpose, token)
            self._validate_challenge_row(challenge)
            if kind == "invitation":
                row = conn.execute(
                    "SELECT * FROM operator_grants WHERE grant_id=?",
                    (challenge["subject_ref"],),
                ).fetchone()
                if not row or row["status"] != "pending":
                    raise InvalidChallenge("Invitation is no longer available")
                summary = self._grant_summary(row)
                if summary["status"] == "expired":
                    raise InvalidChallenge("Invitation has expired")
                return {
                    "kind": kind,
                    "recipient": summary["recipient"],
                    "expires_at": row["expires_at"],
                    "grant_kind": row["kind"],
                }
            row = conn.execute(
                "SELECT * FROM email_change_requests WHERE change_id=?",
                (challenge["subject_ref"],),
            ).fetchone()
            if (
                not row
                or row["status"] != "pending"
                or self._parse_time(row["expires_at"]) <= self._parse_time(self.now())
            ):
                raise InvalidChallenge("Email change is no longer available")
            return {
                "kind": "email_change",
                "recipient": masked_email(
                    self._open(
                        row["encryption_key_id"],
                        "operator-email",
                        row["new_email_ciphertext"],
                    )
                ),
                "expires_at": row["expires_at"],
                "disconnects_receiver": True,
            }

    def claim_operator_invitation(self, token: str) -> dict:
        with self._operator_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            challenge = self._challenge_for_token(conn, "operator_claim", token)
            self._validate_challenge_row(challenge)
            grant = conn.execute(
                "SELECT * FROM operator_grants WHERE grant_id=?",
                (challenge["subject_ref"],),
            ).fetchone()
            if (
                not grant
                or grant["status"] != "pending"
                or self._grant_summary(grant)["status"] == "expired"
            ):
                raise InvalidChallenge("Invitation is no longer available")
            expected = (
                "production" if self.deployment_environment == "production" else "test"
            )
            if grant["environment"] != expected:
                raise PurchaseEnvironmentMismatch(
                    "Invitation belongs to another relay environment"
                )
            email = self._open(
                grant["encryption_key_id"], "operator-email", grant["email_ciphertext"]
            )
            holder = self._holder_for_email(conn, email, create=True)
            now, license_id = self.now(), "lic_" + uuid.uuid4().hex
            conn.execute(
                "UPDATE license_holders SET verified_at=COALESCE(verified_at,?) WHERE holder_id=?",
                (now, holder),
            )
            key = derive_license_key(self._key_secret, license_id, 1)
            normalized = normalize_license_key(key)
            conn.execute(
                """INSERT INTO relay_licenses
                (license_id,holder_id,product_code,purchase_source,status,key_version,key_secret_id,hash_secret_id,license_key_hmac,key_prefix,key_last_four,created_at,updated_at)
                VALUES (?,?,?,?,'active',1,?,?,?,?,?,?,?)""",
                (
                    license_id,
                    holder,
                    self.product_code,
                    "operator_" + grant["kind"],
                    self.key_secret_id,
                    self.hash_secret_id,
                    generated_license_key_hash(self._hash_secret, normalized),
                    key[:14],
                    normalized[-4:],
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE operator_grants SET license_id=?,status='issued',updated_at=? WHERE grant_id=?",
                (license_id, now, grant["grant_id"]),
            )
            conn.execute(
                "UPDATE access_challenges SET consumed_at=? WHERE challenge_id=?",
                (now, challenge["challenge_id"]),
            )
            self._queue_current_key_conn(
                conn,
                self._license_row(conn, license_id),
                purpose="operator_issue",
                dedupe="operator-issue:" + grant["grant_id"],
            )
            result = {
                "ok": True,
                "license_id": license_id,
                "key_ref": key[:14] + "…" + normalized[-4:],
                "delivery": "queued",
            }
            self._audit_conn(
                conn,
                action="claim_grant",
                target=grant["grant_id"],
                request_id=challenge["challenge_id"],
                reason="Recipient confirmed invitation",
                license_id=license_id,
                after={"status": "issued"},
                actor="verified_recipient",
            )
            return result

    def _queue_current_key_conn(self, conn, row, *, purpose: str, dedupe: str) -> str:
        self._authority_conn(conn, str(row["license_id"]))
        self._holder_email_conn(conn, str(row["holder_id"] or ""))
        ref, now = "delivery_" + uuid.uuid4().hex, self.now()
        conn.execute(
            """INSERT OR IGNORE INTO license_deliveries
            (delivery_id,license_id,holder_id,channel,purpose,key_version,dedupe_key,status,created_at,updated_at,next_attempt_at)
            VALUES (?,?,?,'email',?,?,?,'pending',?,?,?)""",
            (
                ref,
                row["license_id"],
                row["holder_id"],
                purpose,
                row["key_version"],
                dedupe,
                now,
                now,
                now,
            ),
        )
        return str(
            conn.execute(
                "SELECT delivery_id FROM license_deliveries WHERE dedupe_key=?",
                (dedupe,),
            ).fetchone()[0]
        )

    def operator_grant_action(
        self,
        grant_id: str,
        *,
        action: str,
        reason: str,
        request_id: str,
        expires_at: str | None = None,
    ) -> dict:
        reason, request_id = self._operator_reason(reason), self._request_id(request_id)
        with self._operator_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            replay = self._audit_replay(conn, "grant:" + action, request_id, grant_id)
            if replay is not None:
                return replay
            row = conn.execute(
                "SELECT * FROM operator_grants WHERE grant_id=?", (grant_id,)
            ).fetchone()
            if not row:
                raise LicenseNotFound("Operator grant was not found")
            expected = (
                "production" if self.deployment_environment == "production" else "test"
            )
            if row["environment"] != expected:
                raise PurchaseEnvironmentMismatch(
                    "Grant belongs to another relay environment"
                )
            before = self._grant_summary(row)
            license_id = str(row["license_id"] or "")
            if action == "resend_invitation" and row["status"] == "pending":
                if (
                    self._parse_time(self.now()) - self._parse_time(row["updated_at"])
                ).total_seconds() < 600:
                    raise InvalidChallenge(
                        "Wait ten minutes before resending this invitation"
                    )
                if before["status"] == "expired":
                    raise InvalidChallenge(
                        "Renew the grant before sending another invitation"
                    )
                self._grant_invitation_conn(conn, row, request_id=request_id)
            elif action in {"adjust_expiry", "renew"}:
                expiry = self._expiry(expires_at)
                if action == "adjust_expiry" and before["status"] in {
                    "expired",
                    "revoked",
                    "cancelled",
                }:
                    raise InvalidChallenge(
                        "Use Renew to restore an inactive operator grant"
                    )
                new_status = (
                    ("issued" if license_id else "pending")
                    if action == "renew"
                    else row["status"]
                )
                conn.execute(
                    "UPDATE operator_grants SET expires_at=?,status=?,updated_at=? WHERE grant_id=?",
                    (expiry, new_status, self.now(), grant_id),
                )
                if action == "renew" and license_id:
                    if (
                        before["status"] != "issued"
                        or self._license_row(conn, license_id)["status"] != "active"
                    ):
                        self._invalidate_license_conn(
                            conn, license_id, reason="operator_renewal"
                        )
                    conn.execute(
                        "UPDATE relay_licenses SET status='active',revoked_at=NULL,updated_at=? WHERE license_id=?",
                        (self.now(), license_id),
                    )
                elif action == "renew":
                    self._grant_invitation_conn(
                        conn,
                        conn.execute(
                            "SELECT * FROM operator_grants WHERE grant_id=?",
                            (grant_id,),
                        ).fetchone(),
                        request_id=request_id,
                    )
            elif action in {"suspend", "revoke"}:
                if action == "suspend" and not license_id:
                    raise InvalidChallenge("Only an issued license can be suspended")
                if action == "revoke":
                    conn.execute(
                        "UPDATE operator_grants SET status='revoked',updated_at=? WHERE grant_id=?",
                        (self.now(), grant_id),
                    )
                else:
                    conn.execute(
                        "UPDATE operator_grants SET status='suspended',updated_at=? WHERE grant_id=?",
                        (self.now(), grant_id),
                    )
                if license_id:
                    conn.execute(
                        "UPDATE relay_licenses SET status=?,updated_at=? WHERE license_id=?",
                        (
                            "suspended" if action == "suspend" else "revoked",
                            self.now(),
                            license_id,
                        ),
                    )
                    self._invalidate_license_conn(
                        conn, license_id, reason="operator_" + action
                    )
                conn.execute(
                    "UPDATE access_challenges SET consumed_at=? WHERE purpose='operator_claim' AND subject_ref=?",
                    (self.now(), grant_id),
                )
            else:
                raise InvalidChallenge("Operator grant action is not available")
            result = self._grant_summary(
                conn.execute(
                    "SELECT * FROM operator_grants WHERE grant_id=?", (grant_id,)
                ).fetchone()
            )
            self._audit_conn(
                conn,
                action="grant:" + action,
                target=grant_id,
                request_id=request_id,
                reason=reason,
                license_id=license_id,
                before=before,
                after=result,
            )
            return result

    def _invalidate_license_conn(self, conn, license_id: str, *, reason: str) -> None:
        now = self.now()
        conn.execute(
            "UPDATE relay_activations SET status='revoked',revoked_at=?,revoke_reason=? WHERE license_id=? AND status IN ('active','pending_commit')",
            (now, reason, license_id),
        )
        conn.execute(
            "UPDATE access_challenges SET consumed_at=? WHERE license_id=? AND consumed_at IS NULL",
            (now, license_id),
        )
        conn.execute(
            "UPDATE license_deliveries SET status='cancelled',next_attempt_at=NULL,detail_code=?,updated_at=? WHERE license_id=? AND status IN ('pending','failed','uncertain')",
            (reason, now, license_id),
        )
        conn.execute(
            "UPDATE notification_outbox SET status='cancelled',next_attempt_at=NULL,detail_code=?,updated_at=? WHERE license_id=? AND channel='email' AND status IN ('pending','failed','uncertain')",
            (reason, now, license_id),
        )

    def expire_operator_grants(self) -> int:
        with self._operator_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT * FROM operator_grants WHERE status IN ('issued','pending') AND expires_at IS NOT NULL AND expires_at<=?",
                (self.now(),),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE operator_grants SET status='expired',updated_at=? WHERE grant_id=?",
                    (self.now(), row["grant_id"]),
                )
                if row["license_id"]:
                    self._invalidate_license_conn(
                        conn, row["license_id"], reason="license_expired"
                    )
                self._audit_conn(
                    conn,
                    action="grant_expired",
                    target=row["grant_id"],
                    request_id=row["grant_id"] + ":" + row["expires_at"],
                    reason="Configured expiry reached",
                    license_id=row["license_id"] or "",
                    after={"status": "expired"},
                    actor="system",
                )
            return len(rows)

    def _rotate_operator_key_conn(self, conn, row, *, purpose: str) -> None:
        license_id = str(row["license_id"])
        self._authority_conn(conn, license_id)
        version = int(row["key_version"]) + 1
        key = derive_license_key(self._key_secret, license_id, version)
        normalized = normalize_license_key(key)
        self._invalidate_license_conn(conn, license_id, reason=purpose)
        conn.execute(
            """UPDATE relay_licenses SET key_version=?,key_secret_id=?,hash_secret_id=?,
            license_key_hmac=?,key_prefix=?,key_last_four=?,updated_at=? WHERE license_id=?""",
            (
                version,
                self.key_secret_id,
                self.hash_secret_id,
                generated_license_key_hash(self._hash_secret, normalized),
                key[:14],
                normalized[-4:],
                self.now(),
                license_id,
            ),
        )
        self._queue_current_key_conn(
            conn,
            self._license_row(conn, license_id),
            purpose=purpose,
            dedupe=f"{purpose}:{license_id}:{version}",
        )

    def operator_license_action(
        self,
        license_id: str,
        *,
        action: str,
        reason: str,
        request_id: str,
        email: str = "",
        note: str = "",
    ) -> dict:
        reason, request_id = self._operator_reason(reason), self._request_id(request_id)
        with self._operator_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            replay = self._audit_replay(conn, action, request_id, license_id)
            if replay is not None:
                return replay
            row = self._license_row(conn, license_id)
            before = {"status": row["status"], "key_version": row["key_version"]}
            result = {"ok": True, "action": action}
            if action == "add_note":
                text = self._operator_reason(note)
                conn.execute(
                    "INSERT INTO operator_notes VALUES (?,?,?,?,?,?)",
                    (
                        "note_" + uuid.uuid4().hex,
                        license_id,
                        self._seal("operator-note", text),
                        self.encryption_secret_id,
                        request_id,
                        self.now(),
                    ),
                )
            elif action in {"resend_key_email", "send_recovery_link"}:
                self._authority_conn(conn, license_id)
                destination = self._holder_email_conn(
                    conn,
                    str(row["holder_id"] or ""),
                    verified=action != "send_recovery_link",
                )
                last = conn.execute(
                    """SELECT created_at FROM operator_audit WHERE license_id=?
                    AND action=? AND outcome='completed' ORDER BY created_at DESC LIMIT 1""",
                    (license_id, action),
                ).fetchone()
                if (
                    last
                    and (
                        self._parse_time(self.now())
                        - self._parse_time(last["created_at"])
                    ).total_seconds()
                    < 600
                ):
                    raise InvalidChallenge(
                        "Wait ten minutes before sending another message"
                    )
                if action == "resend_key_email":
                    latest = conn.execute(
                        """SELECT * FROM license_deliveries WHERE license_id=? AND channel='email' AND key_version=?
                        ORDER BY created_at DESC,delivery_id DESC LIMIT 1""",
                        (license_id, row["key_version"]),
                    ).fetchone()
                    if latest and latest["status"] == "uncertain":
                        raise InvalidChallenge(
                            "Review the uncertain message and explicitly acknowledge possible duplicate delivery before retrying"
                        )
                    if latest and (
                        latest["status"] in {"pending", "sending"}
                        or (latest["status"] == "failed" and latest["next_attempt_at"])
                        or (
                            self._parse_time(self.now())
                            - self._parse_time(latest["created_at"])
                        ).total_seconds()
                        < 600
                    ):
                        result.update(queued=False, message_ref=latest["delivery_id"])
                    else:
                        ref = self._queue_current_key_conn(
                            conn,
                            row,
                            purpose="operator_resend",
                            dedupe="operator-resend:" + request_id,
                        )
                        result.update(queued=True, message_ref=ref)
                else:
                    token = random_token("lfrml_", 32)
                    self._insert_challenge(
                        conn,
                        purpose="email_magic",
                        token=token,
                        holder_id=row["holder_id"],
                        license_id=license_id,
                        payload={
                            "request_purpose": "recovery",
                            "attach_license": False,
                        },
                        minutes=15,
                    )
                    ref = self._notice_conn(
                        conn,
                        email=destination,
                        purpose="magic_link:operator_recovery",
                        payload={"token": token, "request_purpose": "recovery"},
                        license_id=license_id,
                        holder_id=row["holder_id"],
                        dedupe="operator-recovery:" + request_id,
                        expires_at=self._future(15),
                    )
                    result.update(queued=True, message_ref=ref)
            elif action in {"suspend_license", "revoke_license"}:
                status = "suspended" if action == "suspend_license" else "revoked"
                conn.execute(
                    "UPDATE relay_licenses SET status=?,revoked_at=?,updated_at=? WHERE license_id=?",
                    (status, self.now(), self.now(), license_id),
                )
                self._invalidate_license_conn(conn, license_id, reason=action)
            elif action == "reactivate_license":
                authority = self._authority_conn(conn, license_id, active=False)
                if authority["authority_state"] not in {"paid", "purchased", "issued"}:
                    raise LicenseInactive(
                        "Active purchase authority or a valid operator grant is required"
                    )
                conn.execute(
                    "UPDATE relay_licenses SET status='active',revoked_at=NULL,updated_at=? WHERE license_id=?",
                    (self.now(), license_id),
                )
            elif action == "revoke_receiver":
                conn.execute(
                    "UPDATE relay_activations SET status='revoked',revoked_at=?,revoke_reason='operator_receiver_revoke' WHERE license_id=? AND status IN ('active','pending_commit')",
                    (self.now(), license_id),
                )
                conn.execute(
                    "UPDATE access_challenges SET consumed_at=? WHERE license_id=? AND purpose IN ('activation_grant','confirm_move','remote_companion_ws')",
                    (self.now(), license_id),
                )
            elif action == "rotate_key":
                self._holder_email_conn(conn, str(row["holder_id"] or ""))
                self._rotate_operator_key_conn(
                    conn, row, purpose="operator_key_rotation"
                )
                result["delivery"] = "queued"
            elif action == "start_email_change":
                self._authority_conn(conn, license_id)
                old_email = self._holder_email_conn(conn, str(row["holder_id"] or ""))
                new_email = self.normalize_email(email)
                if new_email == old_email:
                    raise InvalidChallenge(
                        "The new email must differ from the protected address"
                    )
                active = conn.execute(
                    "SELECT * FROM email_change_requests WHERE license_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1",
                    (license_id,),
                ).fetchone()
                if (
                    active
                    and (
                        self._parse_time(self.now())
                        - self._parse_time(active["created_at"])
                    ).total_seconds()
                    < 600
                ):
                    raise InvalidChallenge(
                        "An email change was recently requested. Wait ten minutes before replacing it."
                    )
                conn.execute(
                    "UPDATE email_change_requests SET status='superseded',updated_at=? WHERE license_id=? AND status='pending'",
                    (self.now(), license_id),
                )
                change_id, now = "change_" + uuid.uuid4().hex, self.now()
                conn.execute(
                    """INSERT INTO email_change_requests
                    (change_id,license_id,old_holder_id,expected_key_version,new_email_ciphertext,new_email_hmac,hash_key_id,encryption_key_id,status,expires_at,request_id,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,'pending',?,?,?,?)""",
                    (
                        change_id,
                        license_id,
                        row["holder_id"],
                        row["key_version"],
                        self._seal("operator-email", new_email),
                        self._email_hmac(new_email),
                        self.hash_secret_id,
                        self.encryption_secret_id,
                        self._future(30),
                        request_id,
                        now,
                        now,
                    ),
                )
                for side, destination in (("old", old_email), ("new", new_email)):
                    token = random_token("lfrec_", 32)
                    self._insert_challenge(
                        conn,
                        purpose="operator_email_change",
                        token=token,
                        license_id=license_id,
                        subject_ref=change_id,
                        payload={"side": side},
                        minutes=30,
                    )
                    self._notice_conn(
                        conn,
                        email=destination,
                        purpose="operator:email_change",
                        payload={"token": token, "change_id": change_id, "side": side},
                        license_id=license_id,
                        dedupe=f"email-change:{change_id}:{side}",
                        expires_at=self._future(30),
                    )
                result.update(
                    change_id=change_id,
                    status="pending",
                    recipient=masked_email(new_email),
                )
            elif action == "cancel_email_change":
                changes = conn.execute(
                    "SELECT change_id FROM email_change_requests WHERE license_id=? AND status='pending'",
                    (license_id,),
                ).fetchall()
                for change in changes:
                    conn.execute(
                        "UPDATE access_challenges SET consumed_at=? WHERE purpose='operator_email_change' AND subject_ref=?",
                        (self.now(), change["change_id"]),
                    )
                conn.execute(
                    "UPDATE email_change_requests SET status='cancelled',updated_at=? WHERE license_id=? AND status='pending'",
                    (self.now(), license_id),
                )
            else:
                raise InvalidChallenge("Operator action is not supported")
            current = self._license_row(conn, license_id)
            result.update(
                license_status=current["status"], key_version=current["key_version"]
            )
            self._audit_conn(
                conn,
                action=action,
                target=license_id,
                request_id=request_id,
                reason=reason,
                license_id=license_id,
                before=before,
                after=result,
            )
            return result

    def confirm_operator_email_change(self, token: str) -> dict:
        with self._operator_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            challenge = self._challenge_for_token(conn, "operator_email_change", token)
            self._validate_challenge_row(challenge)
            change = conn.execute(
                "SELECT * FROM email_change_requests WHERE change_id=?",
                (challenge["subject_ref"],),
            ).fetchone()
            if (
                not change
                or change["status"] != "pending"
                or self._parse_time(change["expires_at"])
                <= self._parse_time(self.now())
            ):
                raise InvalidChallenge("Email change is no longer available")
            row = self._license_row(conn, change["license_id"])
            self._authority_conn(conn, change["license_id"])
            if (
                row["holder_id"] != change["old_holder_id"]
                or row["key_version"] != change["expected_key_version"]
            ):
                raise InvalidChallenge(
                    "The license changed. Ask the operator to start again."
                )
            side = self._json_payload(challenge["payload_json"]).get("side")
            if side not in {"old", "new"}:
                raise InvalidChallenge("Email confirmation is invalid")
            conn.execute(
                f"UPDATE email_change_requests SET {side}_confirmed_at=?,updated_at=? WHERE change_id=?",
                (self.now(), self.now(), change["change_id"]),
            )
            conn.execute(
                "UPDATE access_challenges SET consumed_at=? WHERE challenge_id=?",
                (self.now(), challenge["challenge_id"]),
            )
            change = conn.execute(
                "SELECT * FROM email_change_requests WHERE change_id=?",
                (change["change_id"],),
            ).fetchone()
            complete = bool(change["old_confirmed_at"] and change["new_confirmed_at"])
            if complete:
                old_email = self._holder_email_conn(conn, change["old_holder_id"])
                email = self._open(
                    change["encryption_key_id"],
                    "operator-email",
                    change["new_email_ciphertext"],
                )
                holder_id = self._holder_for_email(conn, email, create=True)
                conn.execute(
                    "UPDATE license_holders SET verified_at=COALESCE(verified_at,?) WHERE holder_id=?",
                    (self.now(), holder_id),
                )
                conn.execute(
                    "UPDATE relay_licenses SET holder_id=?,updated_at=? WHERE license_id=?",
                    (holder_id, self.now(), row["license_id"]),
                )
                self._rotate_operator_key_conn(
                    conn,
                    self._license_row(conn, row["license_id"]),
                    purpose="protected_email_changed",
                )
                conn.execute(
                    "UPDATE email_change_requests SET status='completed',updated_at=? WHERE change_id=?",
                    (self.now(), change["change_id"]),
                )
                self._notice_conn(
                    conn,
                    email=old_email,
                    purpose="operator:email_changed",
                    payload={},
                    license_id=row["license_id"],
                    dedupe="email-changed:" + change["change_id"],
                )
            result = {
                "ok": True,
                "status": "completed" if complete else "awaiting_other_address",
                "reconnect_required": complete,
            }
            self._audit_conn(
                conn,
                action="confirm_email_change:" + side,
                target=change["change_id"],
                request_id=challenge["challenge_id"],
                reason="Mailbox holder explicitly confirmed",
                license_id=row["license_id"],
                after=result,
                actor="verified_recipient",
            )
            return result

    def operator_history(
        self, *, license_id: str = "", cursor: str = "", limit: int = 50
    ) -> dict:
        limit = max(1, min(limit, 100))
        with self._operator_connection() as conn:
            clauses, params = [], []
            if license_id:
                clauses.append("license_id=?")
                params.append(license_id)
            if cursor:
                clauses.append("rowid<?")
                params.append(self._operator_cursor(cursor))
            where = "WHERE " + " AND ".join(clauses) if clauses else ""
            rows = conn.execute(
                f"SELECT rowid AS sequence,* FROM operator_audit {where} ORDER BY rowid DESC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            items = [
                {
                    key: row[key]
                    for key in (
                        "event_id",
                        "license_id",
                        "target_ref",
                        "actor",
                        "action",
                        "outcome",
                        "created_at",
                    )
                }
                | {
                    "reason": self._open(
                        row["encryption_key_id"],
                        "operator-reason",
                        row["reason_ciphertext"],
                    ),
                    "before": json.loads(row["before_json"]),
                    "after": json.loads(row["after_json"]),
                }
                for row in rows[:limit]
            ]
            return {
                "items": items,
                "has_more": len(rows) > limit,
                "next_cursor": (
                    str(rows[limit - 1]["sequence"]) if len(rows) > limit else ""
                ),
            }

    @staticmethod
    def _operator_cursor(value: str) -> int:
        try:
            result = int(value)
            if result <= 0:
                raise ValueError
            return result
        except (TypeError, ValueError) as exc:
            raise InvalidChallenge("Operator cursor is invalid") from exc

    def operator_grants(
        self, *, query: str = "", cursor: str = "", limit: int = 50
    ) -> dict:
        limit = max(1, min(limit, 100))
        with self._operator_connection() as conn:
            clauses, params = [], []
            if query:
                if "@" in query:
                    candidates = self._hash_candidates(
                        "holder-email", self.normalize_email(query)
                    )
                    clauses.append(
                        "email_hmac IN (" + ",".join("?" for _ in candidates) + ")"
                    )
                    params.extend(value for _, value in candidates)
                else:
                    clauses.append("(grant_id=? OR license_id=?)")
                    params.extend([query, query])
            if cursor:
                clauses.append("rowid<?")
                params.append(self._operator_cursor(cursor))
            where = "WHERE " + " AND ".join(clauses) if clauses else ""
            rows = conn.execute(
                f"SELECT rowid AS sequence,* FROM operator_grants {where} ORDER BY rowid DESC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            return {
                "items": [self._grant_summary(row) for row in rows[:limit]],
                "has_more": len(rows) > limit,
                "next_cursor": (
                    str(rows[limit - 1]["sequence"]) if len(rows) > limit else ""
                ),
            }

    def operator_license_support(self, license_id: str) -> dict:
        with self._operator_connection() as conn:
            row = self._license_row(conn, license_id)
            try:
                authority = self._authority_conn(conn, license_id, active=False)
            except (LicenseInactive, PurchaseEnvironmentMismatch):
                authority = {
                    "effective_state": "unavailable",
                    "authority_state": "missing_or_wrong_environment",
                    "expires_at": None,
                    "grant_id": "",
                }
            recipient = "Not protected"
            protected = False
            if row["holder_id"]:
                try:
                    recipient = masked_email(
                        self._holder_email_conn(conn, row["holder_id"])
                    )
                    protected = True
                except InvalidChallenge:
                    recipient = masked_email(
                        self._holder_email_conn(conn, row["holder_id"], verified=False)
                    )
            notes = conn.execute(
                "SELECT * FROM operator_notes WHERE license_id=? ORDER BY rowid DESC LIMIT 100",
                (license_id,),
            ).fetchall()
            changes = conn.execute(
                "SELECT * FROM email_change_requests WHERE license_id=? ORDER BY rowid DESC LIMIT 20",
                (license_id,),
            ).fetchall()
            eligible = (
                authority.get("authority_state") in {"paid", "purchased", "issued"}
                and authority["effective_state"] == "active"
            )
            reason = (
                ""
                if eligible and protected
                else "An active entitlement and verified protected address are required"
            )
            return {
                "authority": authority,
                "recipient": recipient,
                "email_protected": protected,
                "actions": {
                    key: {
                        "enabled": eligible
                        and (
                            bool(row["holder_id"])
                            if key == "send_recovery_link"
                            else protected
                        ),
                        "reason": reason,
                    }
                    for key in (
                        "resend_key_email",
                        "send_recovery_link",
                        "rotate_key",
                        "start_email_change",
                    )
                },
                "notes": [
                    {
                        "note_id": n["note_id"],
                        "created_at": n["created_at"],
                        "text": self._open(
                            n["encryption_key_id"],
                            "operator-note",
                            n["note_ciphertext"],
                        ),
                    }
                    for n in notes
                ],
                "email_changes": [
                    {
                        "change_id": c["change_id"],
                        "status": (
                            "expired"
                            if c["status"] == "pending"
                            and c["expires_at"] <= self.now()
                            else c["status"]
                        ),
                        "recipient": masked_email(
                            self._open(
                                c["encryption_key_id"],
                                "operator-email",
                                c["new_email_ciphertext"],
                            )
                        ),
                        "old_confirmed": bool(c["old_confirmed_at"]),
                        "new_confirmed": bool(c["new_confirmed_at"]),
                        "expires_at": c["expires_at"],
                        "created_at": c["created_at"],
                    }
                    for c in changes
                ],
            }

    def check_receiver_authority(
        self, *, install_id: str, activation_id: str = ""
    ) -> dict:
        with self._operator_connection() as conn:
            row = conn.execute(
                "SELECT * FROM relay_activations WHERE install_id=? AND status='active'"
                + (" AND activation_id=?" if activation_id else "")
                + " ORDER BY activated_at DESC LIMIT 1",
                (install_id, activation_id) if activation_id else (install_id,),
            ).fetchone()
            if not row:
                raise LicenseInactive("Relay Access receiver is no longer active")
            return self._authority_conn(conn, row["license_id"]) | {
                "activation_id": row["activation_id"]
            }

    def _mail_row(self, conn, kind: str, ref: str):
        tables = {
            "license": ("license_deliveries", "delivery_id"),
            "notification": ("notification_outbox", "notification_id"),
        }
        if kind not in tables:
            raise InvalidChallenge("Message kind is invalid")
        table, column = tables[kind]
        row = conn.execute(
            f"SELECT * FROM {table} WHERE {column}=? AND channel='email'", (ref,)
        ).fetchone()
        if not row:
            raise InvalidChallenge("Email message was not found")
        return table, column, row

    def _mail_eligible_conn(self, conn, kind: str, row) -> None:
        if kind == "license":
            license_row = self._license_row(conn, row["license_id"])
            self._authority_conn(conn, row["license_id"])
            if (
                row["key_version"] != license_row["key_version"]
                or row["holder_id"] != license_row["holder_id"]
            ):
                raise InvalidChallenge("Message was superseded by a license change")
        elif (
            str(row["purpose"]).startswith("operator:")
            and row["purpose"] != "operator:email_changed"
            and row["purpose"] != "operator:smtp_test"
        ):
            payload = json.loads(
                self._open(
                    row["encryption_key_id"],
                    "notification-payload",
                    row["payload_ciphertext"] or "",
                )
            )
            purpose = (
                "operator_claim"
                if row["purpose"] == "operator:invitation"
                else "operator_email_change"
            )
            challenge = self._challenge_for_token(
                conn, purpose, str(payload.get("token") or "")
            )
            self._validate_challenge_row(challenge)
            if purpose == "operator_claim":
                grant = conn.execute(
                    "SELECT * FROM operator_grants WHERE grant_id=?",
                    (challenge["subject_ref"],),
                ).fetchone()
                if not grant or self._grant_summary(grant)["status"] != "pending":
                    raise InvalidChallenge("Invitation was superseded")
            else:
                change = conn.execute(
                    "SELECT * FROM email_change_requests WHERE change_id=?",
                    (challenge["subject_ref"],),
                ).fetchone()
                if not change or change["status"] != "pending":
                    raise InvalidChallenge("Email change was superseded")
        elif row["license_id"] and row["purpose"] != "operator:email_changed":
            self._authority_conn(conn, row["license_id"])
            license_row = self._license_row(conn, row["license_id"])
            if (
                row["holder_id"]
                and license_row["holder_id"]
                and license_row["holder_id"] != row["holder_id"]
            ):
                raise InvalidChallenge("Message belongs to a former holder")

    def begin_mail_attempt(self, *, kind: str, message_ref: str) -> dict:
        with self._operator_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _, _, row = self._mail_row(conn, kind, message_ref)
            if row["status"] != "sending":
                raise InvalidChallenge("Message is not claimed for sending")
            self._mail_eligible_conn(conn, kind, row)
            ref = "attempt_" + uuid.uuid4().hex
            message_id = "<" + uuid.uuid4().hex + "@localflight.invalid>"
            conn.execute(
                "INSERT INTO mail_attempts (attempt_id,message_ref,message_kind,message_id,started_at,stage) VALUES (?,?,?,?,?,'connect')",
                (ref, message_ref, kind, message_id, self.now()),
            )
            return {"attempt_id": ref, "message_id": message_id}

    def finish_mail_attempt(
        self,
        attempt_id: str,
        *,
        outcome: str,
        stage: str,
        detail_code: str = "",
        smtp_code: int | None = None,
    ) -> None:
        if outcome not in {"accepted", "failed", "uncertain"} or stage not in {
            "connect",
            "tls",
            "authenticate",
            "transmit",
            "accepted",
        }:
            raise InvalidChallenge("Mail evidence state is invalid")
        with self._operator_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM mail_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if not row:
                raise InvalidChallenge("Mail attempt was not found")
            conn.execute(
                "UPDATE mail_attempts SET outcome=?,stage=?,finished_at=?,detail_code=?,smtp_code=? WHERE attempt_id=?",
                (
                    outcome,
                    stage,
                    self.now(),
                    re.sub(r"[^a-z0-9_]", "", detail_code)[:64],
                    smtp_code,
                    attempt_id,
                ),
            )
            if outcome == "uncertain":
                table, column, _ = self._mail_row(
                    conn, row["message_kind"], row["message_ref"]
                )
                conn.execute(
                    f"UPDATE {table} SET status='uncertain',detail_code='smtp_outcome_uncertain',next_attempt_at=NULL,updated_at=? WHERE {column}=?",
                    (self.now(), row["message_ref"]),
                )

    def recover_interrupted_mail(self) -> None:
        cutoff = (self._parse_time(self.now()) - timedelta(minutes=10)).isoformat()
        with self._operator_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for table in ("license_deliveries", "notification_outbox"):
                conn.execute(
                    f"UPDATE {table} SET status='uncertain',detail_code='sending_interrupted',next_attempt_at=NULL,updated_at=? WHERE channel='email' AND status='sending' AND updated_at<?",
                    (self.now(), cutoff),
                )
            conn.execute(
                "UPDATE mail_attempts SET outcome='uncertain',detail_code='sending_interrupted',finished_at=? WHERE outcome='sending' AND started_at<?",
                (self.now(), cutoff),
            )

    def operator_mail_action(
        self,
        *,
        kind: str,
        message_ref: str,
        action: str,
        reason: str,
        request_id: str,
        acknowledge_duplicate: bool = False,
    ) -> dict:
        reason, request_id = self._operator_reason(reason), self._request_id(request_id)
        with self._operator_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            replay = self._audit_replay(conn, "mail:" + action, request_id, message_ref)
            if replay is not None:
                return replay
            table, column, row = self._mail_row(conn, kind, message_ref)
            if action == "cancel" and (
                row["status"] == "pending"
                or (row["status"] == "failed" and row["next_attempt_at"])
            ):
                state, next_attempt = "cancelled", None
            elif action == "retry" and row["status"] in {"failed", "uncertain"}:
                self._mail_eligible_conn(conn, kind, row)
                if row["status"] == "uncertain" and not acknowledge_duplicate:
                    raise InvalidChallenge(
                        "Confirm that retrying may deliver a duplicate email"
                    )
                latest = conn.execute(
                    "SELECT created_at FROM operator_audit WHERE target_ref=? AND action='mail:retry' ORDER BY rowid DESC LIMIT 1",
                    (message_ref,),
                ).fetchone()
                if (
                    latest
                    and (
                        self._parse_time(self.now())
                        - self._parse_time(latest["created_at"])
                    ).total_seconds()
                    < 600
                ):
                    raise InvalidChallenge("Wait ten minutes before retrying again")
                state, next_attempt = "pending", self.now()
            else:
                raise InvalidChallenge(
                    "This message cannot be retried or cancelled in its current state"
                )
            conn.execute(
                f"UPDATE {table} SET status=?,next_attempt_at=?,updated_at=?,detail_code=? WHERE {column}=?",
                (
                    state,
                    next_attempt,
                    self.now(),
                    "operator_cancelled" if action == "cancel" else None,
                    message_ref,
                ),
            )
            result = {"ok": True, "message_ref": message_ref, "status": state}
            self._audit_conn(
                conn,
                action="mail:" + action,
                target=message_ref,
                request_id=request_id,
                reason=reason,
                license_id=row["license_id"] or "",
                before={"status": row["status"]},
                after=result,
            )
            return result

    def operator_mail(
        self,
        *,
        license_id: str = "",
        query: str = "",
        state: str = "",
        cursor: str = "",
        limit: int = 50,
    ) -> dict:
        limit = max(1, min(limit, 100))
        with self._operator_connection() as conn:
            clauses, params = ["1=1"], []
            if license_id:
                clauses.append("license_id=?")
                params.append(license_id)
            if state:
                clauses.append("status=?")
                params.append(state)
            if query:
                if "@" in query:
                    hashes = self._hash_candidates(
                        "holder-email", self.normalize_email(query)
                    )
                    marks = ",".join("?" for _ in hashes)
                    clauses.append(
                        f"""(license_id IN (
                            SELECT l.license_id FROM relay_licenses l JOIN license_holders h ON h.holder_id=l.holder_id WHERE h.email_hmac IN ({marks})
                            UNION SELECT d.license_id FROM license_deliveries d JOIN license_holders h ON h.holder_id=d.holder_id WHERE h.email_hmac IN ({marks})
                            UNION SELECT g.license_id FROM operator_grants g WHERE g.email_hmac IN ({marks})
                            UNION SELECT c.license_id FROM email_change_requests c WHERE c.new_email_hmac IN ({marks})
                        ) OR message_ref IN (
                            SELECT n.notification_id FROM notification_outbox n JOIN operator_grants g ON g.grant_id=n.subject_ref WHERE g.email_hmac IN ({marks})
                        ))"""
                    )
                    params.extend([value for _, value in hashes] * 5)
                else:
                    clauses.append("(message_ref=? OR purpose LIKE ?)")
                    params.extend((query, "%" + query.replace("%", "") + "%"))
            if cursor:
                try:
                    marker = json.loads(
                        base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
                    )
                    clauses.append("(created_at<? OR (created_at=? AND message_ref<?))")
                    params.extend((marker[0], marker[0], marker[1]))
                except (ValueError, TypeError, IndexError) as exc:
                    raise InvalidChallenge("Mail cursor is invalid") from exc
            rows = conn.execute(
                """SELECT * FROM (
                SELECT delivery_id AS message_ref,'license' AS kind,license_id,purpose,status,attempt_count,created_at,updated_at,next_attempt_at,delivered_at,detail_code
                FROM license_deliveries WHERE channel='email'
                UNION ALL
                SELECT notification_id,'notification',license_id,purpose,status,attempt_count,created_at,updated_at,next_attempt_at,delivered_at,detail_code
                FROM notification_outbox WHERE channel='email'
                ) WHERE """
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC,message_ref DESC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            items = []
            for row in rows[:limit]:
                item = dict(row)
                attempts = conn.execute(
                    "SELECT * FROM mail_attempts WHERE message_ref=? ORDER BY started_at DESC LIMIT 50",
                    (row["message_ref"],),
                ).fetchall()
                item["attempts"] = [dict(a) for a in attempts]
                item["recipient_delivery"] = "unknown"
                item["recipient"] = "Not recorded"
                if row["kind"] == "notification":
                    notice = conn.execute(
                        "SELECT * FROM notification_outbox WHERE notification_id=?",
                        (row["message_ref"],),
                    ).fetchone()
                    item["recipient"] = masked_email(
                        self._open(
                            notice["encryption_key_id"],
                            "notification-destination",
                            notice["destination_ciphertext"],
                        )
                    )
                else:
                    delivery = conn.execute(
                        "SELECT holder_id FROM license_deliveries WHERE delivery_id=?",
                        (row["message_ref"],),
                    ).fetchone()
                    try:
                        item["recipient"] = masked_email(
                            self._holder_email_conn(conn, delivery["holder_id"])
                        )
                    except InvalidChallenge:
                        pass
                item["evidence_label"] = (
                    ("SMTP accepted" if attempts else "SMTP accepted—legacy record")
                    if row["status"] == "sent"
                    else {
                        "pending": "Queued",
                        "sending": "Sending",
                        "failed": (
                            "Retry scheduled"
                            if row["next_attempt_at"]
                            else "Failed—operator attention required"
                        ),
                        "uncertain": "Outcome uncertain",
                        "cancelled": "Cancelled/superseded",
                    }.get(row["status"], row["status"])
                )
                items.append(item)
            next_cursor = ""
            if len(rows) > limit:
                last = rows[limit - 1]
                next_cursor = (
                    base64.urlsafe_b64encode(
                        json.dumps([last["created_at"], last["message_ref"]]).encode()
                    )
                    .decode()
                    .rstrip("=")
                )
            return {
                "items": items,
                "has_more": len(rows) > limit,
                "next_cursor": next_cursor,
                "delivery_notice": "Recipient delivery unknown with this mail connection.",
            }

    def record_operator_event(
        self,
        *,
        action: str,
        target: str,
        reason: str,
        request_id: str,
        after: dict | None = None,
        outcome: str = "completed",
    ) -> None:
        with self._operator_connection() as conn:
            self._audit_conn(
                conn,
                action=action,
                target=target,
                reason=self._operator_reason(reason),
                request_id=self._request_id(request_id),
                after=after,
                outcome=outcome,
            )

    def operator_smtp_test(self, *, email: str, reason: str, request_id: str) -> dict:
        reason, request_id = self._operator_reason(reason), self._request_id(request_id)
        with self._operator_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            replay = self._audit_replay(conn, "smtp_test", request_id, "smtp")
            if replay is not None:
                return replay
            last = conn.execute(
                "SELECT created_at FROM operator_audit WHERE action='smtp_test' ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if (
                last
                and (
                    self._parse_time(self.now()) - self._parse_time(last["created_at"])
                ).total_seconds()
                < 600
            ):
                raise InvalidChallenge(
                    "Wait ten minutes before sending another SMTP test"
                )
            ref = self._notice_conn(
                conn,
                email=self.normalize_email(email),
                purpose="operator:smtp_test",
                payload={},
                dedupe="smtp-test:" + request_id,
            )
            result = {
                "ok": True,
                "message_ref": ref,
                "recipient": masked_email(email),
                "status": "queued",
            }
            self._audit_conn(
                conn,
                action="smtp_test",
                target="smtp",
                reason=reason,
                request_id=request_id,
                after=result,
            )
            return result
