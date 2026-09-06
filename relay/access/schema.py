from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


ACCESS_SCHEMA_VERSION = 7


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    column = definition.split()[0]
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _record_migration(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO relay_access_schema_migrations (version, applied_at) VALUES (?, ?)",
        (int(version), _now()),
    )


def _execute_script(conn: sqlite3.Connection, script: str) -> None:
    """Execute a DDL script without sqlite3.executescript's implicit commit."""
    statement = ""
    for line in script.splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise sqlite3.OperationalError("Incomplete Relay Access migration statement")


def _apply_access_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS relay_access_schema_migrations (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    # The first integration skeleton briefly used this shorter table name. Copy
    # its history forward when upgrading those databases, without depending on
    # it for future migrations.
    legacy_migrations = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='access_schema_migrations'"
    ).fetchone()
    if legacy_migrations:
        conn.execute(
            """
            INSERT OR IGNORE INTO relay_access_schema_migrations (version, applied_at)
            SELECT version, applied_at FROM access_schema_migrations
            """
        )

    # Version 1 is also safe for databases made by the pre-versioned skeleton.
    _execute_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS license_holders (
            holder_id       TEXT PRIMARY KEY,
            email_hmac      TEXT NOT NULL UNIQUE,
            notification_email_ciphertext TEXT,
            created_at      TEXT NOT NULL,
            verified_at     TEXT,
            last_seen_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS relay_licenses (
            license_id         TEXT PRIMARY KEY,
            holder_id          TEXT,
            product_code       TEXT NOT NULL,
            purchase_source    TEXT NOT NULL,
            status             TEXT NOT NULL,
            key_version        INTEGER NOT NULL DEFAULT 1,
            license_key_hmac   TEXT NOT NULL UNIQUE,
            key_prefix         TEXT NOT NULL,
            key_last_four      TEXT NOT NULL,
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            revoked_at         TEXT,
            FOREIGN KEY (holder_id) REFERENCES license_holders(holder_id)
        );

        CREATE TABLE IF NOT EXISTS purchase_records (
            purchase_id           TEXT PRIMARY KEY,
            provider              TEXT NOT NULL,
            external_purchase_hash TEXT NOT NULL,
            license_id            TEXT NOT NULL,
            product_id            TEXT NOT NULL,
            environment           TEXT NOT NULL,
            state                 TEXT NOT NULL,
            evidence_hash         TEXT,
            created_at            TEXT NOT NULL,
            updated_at            TEXT NOT NULL,
            UNIQUE (provider, external_purchase_hash),
            FOREIGN KEY (license_id) REFERENCES relay_licenses(license_id)
        );

        CREATE TABLE IF NOT EXISTS purchase_events (
            event_key       TEXT PRIMARY KEY,
            provider        TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            status          TEXT NOT NULL,
            detail_code     TEXT,
            created_at      TEXT NOT NULL,
            processed_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS relay_activations (
            activation_id    TEXT PRIMARY KEY,
            license_id       TEXT NOT NULL,
            install_id       TEXT NOT NULL,
            device_kind      TEXT NOT NULL,
            device_name      TEXT NOT NULL,
            credential_hash  TEXT NOT NULL UNIQUE,
            credential_prefix TEXT NOT NULL,
            status            TEXT NOT NULL,
            activated_at      TEXT NOT NULL,
            last_seen_at      TEXT,
            revoked_at        TEXT,
            revoke_reason     TEXT,
            FOREIGN KEY (license_id) REFERENCES relay_licenses(license_id)
        );

        CREATE TABLE IF NOT EXISTS access_challenges (
            challenge_id     TEXT PRIMARY KEY,
            purpose          TEXT NOT NULL,
            token_hash       TEXT NOT NULL UNIQUE,
            holder_id        TEXT,
            license_id       TEXT,
            install_id       TEXT,
            subject_ref      TEXT,
            payload_json     TEXT NOT NULL DEFAULT '{}',
            created_at       TEXT NOT NULL,
            expires_at       TEXT NOT NULL,
            consumed_at      TEXT,
            FOREIGN KEY (holder_id) REFERENCES license_holders(holder_id),
            FOREIGN KEY (license_id) REFERENCES relay_licenses(license_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_relay_activations_one_active_license
            ON relay_activations (license_id) WHERE status='active';
        CREATE INDEX IF NOT EXISTS idx_relay_activations_install
            ON relay_activations (install_id, status);
        CREATE INDEX IF NOT EXISTS idx_relay_licenses_holder
            ON relay_licenses (holder_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_purchase_records_license
            ON purchase_records (license_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_access_challenges_subject
            ON access_challenges (purpose, subject_ref, expires_at);
        """
    )
    _add_column(conn, "license_holders", "notification_email_ciphertext TEXT")
    _record_migration(conn, 1)

    # Version 2 makes delivery/retry, throttling, and key-secret provenance durable.
    _add_column(conn, "relay_licenses", "key_secret_id TEXT NOT NULL DEFAULT 'v1'")
    _add_column(conn, "relay_licenses", "first_delivered_at TEXT")
    _add_column(conn, "relay_licenses", "last_delivered_at TEXT")
    _add_column(conn, "purchase_records", "last_verified_at TEXT")
    _add_column(conn, "purchase_records", "state_reason TEXT")
    _add_column(conn, "purchase_events", "purchase_id TEXT")
    _add_column(conn, "purchase_events", "license_id TEXT")
    _execute_script(
        conn,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_purchase_records_one_license
            ON purchase_records (license_id);

        CREATE TABLE IF NOT EXISTS license_deliveries (
            delivery_id       TEXT PRIMARY KEY,
            license_id        TEXT NOT NULL,
            holder_id         TEXT,
            channel           TEXT NOT NULL,
            purpose           TEXT NOT NULL,
            key_version       INTEGER NOT NULL,
            dedupe_key        TEXT NOT NULL UNIQUE,
            status            TEXT NOT NULL,
            attempt_count     INTEGER NOT NULL DEFAULT 0,
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL,
            available_until   TEXT,
            consumed_at       TEXT,
            last_attempt_at   TEXT,
            delivered_at      TEXT,
            next_attempt_at   TEXT,
            detail_code       TEXT,
            FOREIGN KEY (license_id) REFERENCES relay_licenses(license_id),
            FOREIGN KEY (holder_id) REFERENCES license_holders(holder_id)
        );

        CREATE INDEX IF NOT EXISTS idx_license_deliveries_due
            ON license_deliveries (channel, status, next_attempt_at, created_at);
        CREATE INDEX IF NOT EXISTS idx_license_deliveries_license
            ON license_deliveries (license_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS access_rate_limits (
            subject_hash      TEXT NOT NULL,
            action            TEXT NOT NULL,
            window_started_at INTEGER NOT NULL,
            count             INTEGER NOT NULL,
            updated_at        TEXT NOT NULL,
            PRIMARY KEY (subject_hash, action, window_started_at)
        );
        CREATE INDEX IF NOT EXISTS idx_access_rate_limits_updated
            ON access_rate_limits (updated_at);
        """
    )
    _record_migration(conn, 2)

    # Version 3 adopts the public delivery-state vocabulary and records actual
    # purchase-state transitions separately from routine verification traffic.
    _add_column(conn, "purchase_records", "state_changed_at TEXT")
    conn.execute(
        "UPDATE purchase_records SET state_changed_at=COALESCE(state_changed_at, created_at)"
    )
    conn.execute("UPDATE license_deliveries SET status='sending' WHERE status='processing'")
    conn.execute(
        """
        UPDATE license_deliveries
        SET status='failed', next_attempt_at=NULL,
            detail_code=COALESCE(NULLIF(detail_code, ''), 'retry_limit_reached')
        WHERE status='dead_letter'
        """
    )
    _record_migration(conn, 3)

    # Version 4 remembers only keyed references to recently accepted mobile
    # ownership evidence. A captured provider proof can therefore be retried by
    # its original installation, but cannot be raced into a second installation.
    _execute_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS mobile_ownership_evidence (
            provider          TEXT NOT NULL,
            evidence_hash     TEXT NOT NULL,
            install_ref_hash  TEXT NOT NULL,
            first_seen_at     TEXT NOT NULL,
            last_seen_at      TEXT NOT NULL,
            PRIMARY KEY (provider, evidence_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_mobile_ownership_evidence_seen
            ON mobile_ownership_evidence (last_seen_at);
        """,
    )
    _record_migration(conn, 4)

    # Version 5 completes the licensed cutover primitives. Activations are
    # prepared before a client persists its credential and become usable only
    # after an explicit commit. Provider reconciliation handles and queued
    # notifications are encrypted by the service; plaintext identifiers and
    # email addresses never belong in these tables.
    _add_column(conn, "license_holders", "notification_email_key_id TEXT NOT NULL DEFAULT 'v1'")
    _add_column(conn, "relay_licenses", "hash_secret_id TEXT NOT NULL DEFAULT 'v1'")
    _add_column(conn, "purchase_records", "identity_kind TEXT")
    _add_column(conn, "purchase_records", "identity_hash_key_id TEXT NOT NULL DEFAULT 'v1'")
    _add_column(conn, "purchase_records", "reconciliation_mode TEXT NOT NULL DEFAULT 'device_only'")
    _add_column(conn, "purchase_records", "reconciliation_handle_ciphertext TEXT")
    _add_column(conn, "purchase_records", "reconciliation_key_id TEXT")
    _add_column(conn, "purchase_records", "last_reconciled_at TEXT")
    _add_column(conn, "purchase_records", "next_reconcile_at TEXT")
    _add_column(conn, "purchase_records", "acknowledgement_state TEXT")
    _add_column(conn, "relay_activations", "expected_activation_id TEXT")
    _add_column(conn, "relay_activations", "pending_expires_at TEXT")
    _add_column(conn, "relay_activations", "grant_challenge_id TEXT")
    _execute_script(
        conn,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_relay_activations_one_pending_license
            ON relay_activations (license_id) WHERE status='pending_commit';
        CREATE INDEX IF NOT EXISTS idx_relay_activations_pending_expiry
            ON relay_activations (status, pending_expires_at);

        CREATE TABLE IF NOT EXISTS notification_outbox (
            notification_id      TEXT PRIMARY KEY,
            channel              TEXT NOT NULL,
            purpose              TEXT NOT NULL,
            holder_id            TEXT,
            license_id           TEXT,
            activation_id        TEXT,
            destination_ciphertext TEXT,
            payload_ciphertext   TEXT,
            encryption_key_id    TEXT NOT NULL,
            dedupe_key           TEXT NOT NULL UNIQUE,
            status               TEXT NOT NULL,
            attempt_count        INTEGER NOT NULL DEFAULT 0,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL,
            next_attempt_at      TEXT,
            delivered_at         TEXT,
            expires_at           TEXT,
            detail_code          TEXT,
            FOREIGN KEY (holder_id) REFERENCES license_holders(holder_id),
            FOREIGN KEY (license_id) REFERENCES relay_licenses(license_id),
            FOREIGN KEY (activation_id) REFERENCES relay_activations(activation_id)
        );
        CREATE INDEX IF NOT EXISTS idx_notification_outbox_due
            ON notification_outbox (status, next_attempt_at, created_at);
        CREATE INDEX IF NOT EXISTS idx_notification_outbox_license
            ON notification_outbox (license_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS provider_reconciliation_health (
            provider             TEXT PRIMARY KEY,
            status               TEXT NOT NULL,
            last_success_at      TEXT,
            last_attempt_at      TEXT,
            next_attempt_at      TEXT,
            cursor_ciphertext    TEXT,
            encryption_key_id    TEXT,
            detail_code          TEXT,
            updated_at           TEXT NOT NULL
        );
        """,
    )
    _record_migration(conn, 5)

    # Version 6 records which hash key produced every long-lived lookup and
    # binds a prepared activation to the exact one-use grants that authorized
    # it.  Candidate-key lookup keeps older rows readable during rotation.
    _add_column(conn, "relay_activations", "credential_hash_secret_id TEXT NOT NULL DEFAULT 'v1'")
    _add_column(conn, "relay_activations", "move_challenge_id TEXT")
    _add_column(conn, "access_challenges", "hash_secret_id TEXT NOT NULL DEFAULT 'v1'")
    _add_column(conn, "purchase_events", "hash_secret_id TEXT NOT NULL DEFAULT 'v1'")
    _add_column(conn, "mobile_ownership_evidence", "hash_secret_id TEXT NOT NULL DEFAULT 'v1'")
    _record_migration(conn, 6)

    # Version 7 gives operators an immutable, sanitized purchase-state trail.
    # Provider identifiers and proof bodies remain in keyed/encrypted records;
    # this table stores only internal references and stable reason codes.
    _execute_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS purchase_state_transitions (
            transition_id  TEXT PRIMARY KEY,
            purchase_id    TEXT NOT NULL,
            license_id     TEXT NOT NULL,
            from_state     TEXT,
            to_state       TEXT NOT NULL,
            reason_code    TEXT,
            source         TEXT NOT NULL,
            created_at     TEXT NOT NULL,
            FOREIGN KEY (purchase_id) REFERENCES purchase_records(purchase_id),
            FOREIGN KEY (license_id) REFERENCES relay_licenses(license_id)
        );
        CREATE INDEX IF NOT EXISTS idx_purchase_transitions_license
            ON purchase_state_transitions (license_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_purchase_transitions_purchase
            ON purchase_state_transitions (purchase_id, created_at DESC);
        """,
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO purchase_state_transitions (
            transition_id, purchase_id, license_id, from_state, to_state,
            reason_code, source, created_at
        )
        SELECT 'migration-' || purchase_id, purchase_id, license_id, NULL, state,
               COALESCE(NULLIF(state_reason, ''), 'schema_baseline'),
               'migration', COALESCE(state_changed_at, created_at)
        FROM purchase_records
        """
    )
    _record_migration(conn, 7)


def ensure_access_schema(conn: sqlite3.Connection) -> None:
    """Apply idempotent, additive Relay Access migrations atomically."""
    savepoint = "relay_access_schema_upgrade"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        _apply_access_schema(conn)
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
    else:
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")


def access_schema_version(conn: sqlite3.Connection) -> int:
    canonical = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='relay_access_schema_migrations'"
    ).fetchone()
    table = "relay_access_schema_migrations" if canonical else "access_schema_migrations"
    row = conn.execute(f"SELECT COALESCE(MAX(version), 0) FROM {table}").fetchone()
    return int(row[0] if row else 0)
