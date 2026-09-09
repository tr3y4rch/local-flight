"""Authenticated owner support interfaces and narrowly scoped recipient approvals."""

from __future__ import annotations

from datetime import timedelta
from email.utils import parseaddr
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .models import InvalidChallenge
from .operator import masked_email, safe_operator_text


class OperatorSearch(BaseModel):
    q: str = Field("", max_length=240)
    state: str = Field("", max_length=40)
    source: str = Field("", max_length=40)
    expiry: Literal["", "permanent", "expiring", "expired"] = ""
    license_id: str = Field("", max_length=80)
    cursor: str = Field("", max_length=512)
    limit: int = Field(50, ge=1, le=100)


class OperatorMutation(BaseModel):
    action: str = Field("", max_length=40)
    reason: str = Field(..., min_length=3, max_length=2000)
    request_id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]{8,80}$")
    confirmed: bool = False
    email: str = Field("", max_length=240)
    note: str = Field("", max_length=2000)
    support_reference: str = Field("", max_length=120)
    kind: Literal["test", "complimentary"] = "test"
    expires_at: str | None = Field(None, max_length=64)
    acknowledge_duplicate: bool = False


class OperatorConfirmation(BaseModel):
    token: str = Field(..., min_length=20, max_length=200)
    kind: Literal["invitation", "email_change"] = "invitation"


def operator_readiness(b) -> dict:
    errors = b._access_preflight_errors(mail=True)
    backup = b._access_backup_health()
    if not backup.get("healthy"):
        errors.append("verified_backup_required")
    try:
        b._license_service().verify_keyring_references()
    except Exception:
        errors.append("historical_keyring_unavailable")
    enabled = b._enabled_env("RELAY_ACCESS_OPERATOR_ISSUANCE_ENABLED")
    return {
        "environment": b._access_deployment_environment(),
        "issuance_enabled": enabled,
        "issuance_ready": enabled and not errors,
        "readiness_problems": sorted(set(errors)),
        "mail_ready": b._license_mail_ready(b._license_mailer()),
        "backup": backup,
        "owner_identity": "Authenticated console owner",
        "delivery_notice": "Recipient delivery unknown with this mail connection.",
    }


def operator_detail(b, license_id: str) -> dict:
    service = b._license_service()
    detail = service.admin_license_detail(license_id)
    support = service.operator_license_support(license_id)
    # Rebuild receiver references using the canonical public Support ID, not a
    # credential-keyed hash and never the raw install UUID.
    with service._operator_connection() as conn:
        receivers = []
        for row in conn.execute(
            "SELECT * FROM relay_activations WHERE license_id=? ORDER BY activated_at DESC LIMIT 100",
            (license_id,),
        ):
            profile = conn.execute(
                "SELECT app_version,os_family,os_version,arch,client_kind,last_heartbeat_at FROM install_profiles WHERE install_id=?",
                (row["install_id"],),
            ).fetchone()
            ref = b._install_fingerprint(row["install_id"])
            receivers.append(
                {
                    "support_id": ref,
                    "status": row["status"],
                    "device_kind": safe_operator_text(row["device_kind"]),
                    "device_name": safe_operator_text(row["device_name"], 80),
                    "activated_at": row["activated_at"],
                    "last_seen_at": row["last_seen_at"],
                    "revoked_at": row["revoked_at"],
                    "observed": {
                        k: safe_operator_text(v, 80)
                        for k, v in dict(profile or {}).items()
                    },
                    "presence": "Not inferred from last activity",
                    "fleet_ref": ref,
                    "report_ref": ref,
                }
            )
        usage = [
            dict(r)
            for r in conn.execute(
                "SELECT service,calls,last_seen FROM usage WHERE subject_key=? AND month=?",
                ("license:" + license_id, b._month_key()),
            )
        ]
    limits = {
        "aviationstack": b._int_env(
            "RELAY_LICENSED_SCHEDULE_LIMIT", b._managed_schedule_limit(), minimum=1
        ),
        "radar": b._int_env(
            "RELAY_LICENSED_RADAR_LIMIT", b._managed_radar_limit(), minimum=1
        ),
    }
    findings = []
    if support["authority"].get("effective_state") != "active":
        findings.append(
            {
                "code": "entitlement_inactive",
                "message": "Entitlement is inactive, expired, or unavailable.",
            }
        )
    if not support["email_protected"]:
        findings.append(
            {
                "code": "email_unverified",
                "message": "A verified protected address is needed for key delivery and ownership changes.",
            }
        )
    mail = service.operator_mail(license_id=license_id)
    if any(m["status"] in {"failed", "uncertain"} for m in mail["items"]):
        findings.append(
            {
                "code": "email_attention",
                "message": "Review failed or uncertain email attempts.",
            }
        )
    if not b._license_mail_ready(b._license_mailer()):
        findings.append(
            {"code": "smtp_not_ready", "message": "SMTP configuration is incomplete."}
        )
    policy = b._provider_access_policy()
    if not policy.allows("schedule", "aerodatabox") and not policy.allows(
        "schedule", "aviationstack"
    ):
        findings.append(
            {
                "code": "provider_permissions",
                "message": "Hosted schedule permissions are not enabled; a grant does not override them.",
            }
        )
    if not any(r["status"] == "active" for r in receivers):
        findings.append(
            {
                "code": "receiver_unassigned",
                "message": "No active receiver credential is assigned.",
            }
        )
    return {
        "license": {
            **b._access_license_payload(detail["license"]),
            "license_id": license_id,
        },
        **support,
        "receivers": receivers,
        "usage": {
            "period": b._month_key(),
            "reset_at": b._monthly_reset_at(b._month_key()),
            "items": usage,
            "limits": limits,
        },
        "email": mail,
        "purchases": detail["purchases"],
        "purchase_transitions": detail["purchase_transitions"],
        "diagnostics": {
            "checked_at": service.now(),
            "stored_state_only": True,
            "findings": findings,
        },
        "history": service.operator_history(license_id=license_id),
    }


def create_operator_router(b) -> APIRouter:
    router = APIRouter()
    owner = Depends(b._require_admin)

    def guarded(request, *, read=False):
        b._check_access_rate_limit(
            request,
            action="operator_read" if read else "operator_mutation",
            limit=300 if read else 60,
            window_seconds=60 if read else 600,
        )

    def execute(request, fn, mutation=None):
        try:
            origin = request.headers.get("origin", "")
            if (
                request.url.path.startswith("/v1/access/operator/")
                and origin
                and origin not in {f"https://{host}" for host in b._site_origin_hosts()}
            ):
                raise HTTPException(
                    403,
                    detail={
                        "code": "confirmation_origin_rejected",
                        "message": "Open the confirmation on the configured license-management site.",
                    },
                )
            guarded(
                request,
                read=mutation is None and request.url.path.startswith("/admin/"),
            )
            return fn()
        except HTTPException:
            raise
        except Exception as exc:
            if mutation is not None:
                try:
                    b._license_service().record_operator_event(
                        action=(mutation.action or "issue_grant") + ":rejected",
                        target=request.url.path,
                        reason=mutation.reason,
                        request_id=mutation.request_id,
                        outcome="rejected",
                        after={"code": getattr(exc, "reason_code", "request_rejected")},
                    )
                except Exception:
                    pass
            raise b._access_exception(exc) from exc

    def queue_mail(tasks):
        tasks.add_task(b._deliver_pending_notifications, limit=10)
        tasks.add_task(b._deliver_pending_license_emails, limit=10)

    @router.get("/admin/api/operator/configuration")
    def configuration(_owner=owner):
        return operator_readiness(b)

    @router.post("/admin/api/operator/licenses/search")
    def licenses(body: OperatorSearch, request: Request, _owner=owner):
        def search():
            service = b._license_service()
            page = service.admin_search(
                query=body.q,
                source=body.source,
                state=body.state,
                expiry=body.expiry,
                cursor=body.cursor,
                limit=body.limit,
            )
            for item in page["items"]:
                support = service.operator_license_support(item["license_id"])
                item.update(
                    {
                        k: support[k]
                        for k in ("authority", "recipient", "email_protected")
                    }
                )
                item["delivery"] = service.operator_mail(
                    license_id=item["license_id"], limit=1
                )["items"]
            return page

        return execute(request, search)

    @router.get("/admin/api/operator/licenses/{license_id}")
    def detail(license_id: str, _owner=owner):
        try:
            return operator_detail(b, license_id)
        except Exception as exc:
            raise b._access_exception(exc) from exc

    @router.post("/admin/api/operator/licenses/{license_id}/action")
    def license_action(
        license_id: str,
        body: OperatorMutation,
        request: Request,
        tasks: BackgroundTasks,
        _owner=owner,
    ):
        def mutate():
            if (
                body.action
                in {
                    "rotate_key",
                    "revoke_receiver",
                    "suspend_license",
                    "revoke_license",
                    "reactivate_license",
                    "start_email_change",
                    "cancel_email_change",
                }
                and not body.confirmed
            ):
                raise InvalidChallenge("Explicit impact confirmation is required")
            if body.action == "retry_reconciliation":
                service = b._license_service()
                ref = service.queue_provider_operation(
                    license_id=license_id,
                    operation="reconcile",
                    dedupe_suffix="operator-" + body.request_id,
                )
                result = {"ok": True, "operation_ref": ref[:16], "queued": True}
                service.record_operator_event(
                    action=body.action,
                    target=license_id,
                    reason=body.reason,
                    request_id=body.request_id,
                    after=result,
                )
                tasks.add_task(b._process_provider_operations, limit=1)
                return result
            return b._license_service().operator_license_action(
                license_id,
                action=body.action,
                reason=body.reason,
                request_id=body.request_id,
                email=body.email,
                note=body.note,
            )

        result = execute(request, mutate, body)
        queue_mail(tasks)
        return result

    @router.post("/admin/api/operator/grants/search")
    def grants(body: OperatorSearch, request: Request, _owner=owner):
        return execute(
            request,
            lambda: b._license_service().operator_grants(
                query=body.q, cursor=body.cursor, limit=body.limit
            ),
        )

    @router.post("/admin/api/operator/grants", status_code=202)
    def issue(
        body: OperatorMutation, request: Request, tasks: BackgroundTasks, _owner=owner
    ):
        def mutate():
            if not body.confirmed:
                raise InvalidChallenge(
                    "Confirm the environment, recipient, duration, and one-receiver rule"
                )
            if not operator_readiness(b)["issuance_ready"]:
                raise HTTPException(
                    409,
                    detail={
                        "code": "issuance_not_ready",
                        "message": "Issuance is disabled or keyring, mail, and verified backup readiness is incomplete.",
                    },
                )
            reason = body.reason + (
                " · Support reference: " + body.support_reference
                if body.support_reference
                else ""
            )
            service = b._license_service()
            expiry = body.expires_at
            if body.kind == "test" and "expires_at" not in body.model_fields_set:
                expiry = ""  # Service chooses the timestamp once, inside the idempotent transaction.
            return service.issue_operator_grant(
                kind=body.kind,
                email=body.email,
                reason=reason,
                request_id=body.request_id,
                expires_at=expiry,
            )

        result = execute(request, mutate, body)
        queue_mail(tasks)
        return result

    @router.post("/admin/api/operator/grants/{grant_id}/action")
    def grant_action(
        grant_id: str,
        body: OperatorMutation,
        request: Request,
        tasks: BackgroundTasks,
        _owner=owner,
    ):
        def mutate():
            if not body.confirmed:
                raise InvalidChallenge("Explicit grant impact confirmation is required")
            return b._license_service().operator_grant_action(
                grant_id,
                action=body.action,
                reason=body.reason,
                request_id=body.request_id,
                expires_at=body.expires_at,
            )

        result = execute(request, mutate, body)
        queue_mail(tasks)
        return result

    @router.post("/admin/api/operator/email/search")
    def mail(body: OperatorSearch, request: Request, _owner=owner):
        return execute(
            request,
            lambda: b._license_service().operator_mail(
                query=body.q,
                license_id=body.license_id,
                state=body.state,
                cursor=body.cursor,
                limit=body.limit,
            ),
        )

    @router.post("/admin/api/operator/email/{kind}/{message_ref}/action")
    def mail_action(
        kind: str,
        message_ref: str,
        body: OperatorMutation,
        request: Request,
        tasks: BackgroundTasks,
        _owner=owner,
    ):
        result = execute(
            request,
            lambda: b._license_service().operator_mail_action(
                kind=kind,
                message_ref=message_ref,
                action=body.action,
                reason=body.reason,
                request_id=body.request_id,
                acknowledge_duplicate=body.acknowledge_duplicate,
            ),
            body,
        )
        queue_mail(tasks)
        return result

    @router.post("/admin/api/operator/history/search")
    def history(body: OperatorSearch, request: Request, _owner=owner):
        return execute(
            request,
            lambda: b._license_service().operator_history(
                license_id=body.license_id, cursor=body.cursor, limit=body.limit
            ),
        )

    @router.get("/admin/api/operator/attention")
    def attention(_owner=owner):
        service = b._license_service()
        with service._operator_connection() as conn:
            counts = {}
            for table in ("license_deliveries", "notification_outbox"):
                for row in conn.execute(
                    f"SELECT status,count(*) AS n FROM {table} WHERE channel='email' AND status IN ('failed','uncertain','pending','sending') GROUP BY status"
                ):
                    counts[row["status"]] = counts.get(row["status"], 0) + row["n"]
            cutoff = (
                service._parse_time(service.now()) - timedelta(minutes=10)
            ).isoformat()
            overdue = sum(
                conn.execute(
                    f"SELECT count(*) FROM {table} WHERE channel='email' AND status IN ('pending','sending') AND updated_at<?",
                    (cutoff,),
                ).fetchone()[0]
                for table in ("license_deliveries", "notification_outbox")
            )
            pending = conn.execute(
                "SELECT count(*) FROM operator_grants WHERE status='pending'"
            ).fetchone()[0]
            soon = (service._parse_time(service.now()) + timedelta(days=7)).isoformat()
            expiring = conn.execute(
                "SELECT count(*) FROM operator_grants WHERE status IN ('pending','issued') AND expires_at>? AND expires_at<=?",
                (service.now(), soon),
            ).fetchone()[0]
        return {
            "email": counts,
            "overdue": overdue,
            "pending_invitations": pending,
            "expiring_grants": expiring,
            "configuration": operator_readiness(b),
            "provider_checks": service.admin_reconciliation_snapshot(),
            "purchase_events": service.admin_purchase_events(50),
        }

    @router.post("/admin/api/operator/toolbox/action")
    def toolbox(
        body: OperatorMutation, request: Request, tasks: BackgroundTasks, _owner=owner
    ):
        def mutate():
            service = b._license_service()
            if body.action == "smtp_test":
                mailer = b._license_mailer()
                if not b._license_mail_ready(mailer):
                    raise InvalidChallenge("SMTP is not configured")
                return service.operator_smtp_test(
                    email=parseaddr(mailer.reply_to or mailer.sender)[1],
                    reason=body.reason,
                    request_id=body.request_id,
                )
            if body.action not in {"create_backup", "verify_latest"}:
                raise InvalidChallenge("Toolbox action is not supported")
            with b._ACCESS_BACKUP_LOCK:
                with service._operator_connection() as conn:
                    replay = service._audit_replay(
                        conn, body.action, body.request_id, "backup"
                    )
                    if replay is not None:
                        return replay
                # Record intent before IO; a crash is visible, not a silent retry.
                service.record_operator_event(
                    action=body.action + ":requested",
                    target="backup",
                    reason=body.reason,
                    request_id=body.request_id,
                    outcome="started",
                )
                manager = b._access_backup_manager()
                if body.action == "create_backup":
                    manager.create_backup()
                result = b._access_backup_health()
                service.verify_keyring_references()
                service.record_operator_event(
                    action=body.action,
                    target="backup",
                    reason=body.reason,
                    request_id=body.request_id,
                    after=result,
                )
                return result

        result = execute(request, mutate, body)
        queue_mail(tasks)
        return result

    @router.post("/v1/access/operator/inspect")
    def inspect(body: OperatorConfirmation, request: Request):
        return execute(
            request,
            lambda: b._license_service().inspect_operator_confirmation(
                body.token, kind=body.kind
            ),
        )

    @router.post("/v1/access/operator/claim")
    def claim(body: OperatorConfirmation, request: Request, tasks: BackgroundTasks):
        result = execute(
            request, lambda: b._license_service().claim_operator_invitation(body.token)
        )
        queue_mail(tasks)
        return result

    @router.post("/v1/access/operator/email-change/confirm")
    def confirm(body: OperatorConfirmation, request: Request, tasks: BackgroundTasks):
        result = execute(
            request,
            lambda: b._license_service().confirm_operator_email_change(body.token),
        )
        queue_mail(tasks)
        return result

    return router
