"""
Read/write layer for the email_send_previews table.
One row per daily run; holds the planned_sends array and approval state.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

logger = logging.getLogger(__name__)


def _client() -> Client:
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def save_planned_run(
    run_id: str,
    planned_sends: list[dict],
    summary: dict,
    sample_email: dict | None,
    expires_at: datetime,
) -> None:
    sb = _client()
    row = {
        "run_id": run_id,
        "status": "pending_approval",
        "planned_sends": planned_sends,
        "summary": summary,
        "sample_email": sample_email,
        "expires_at": expires_at.isoformat(),
    }
    sb.table("email_send_previews").insert(row).execute()
    logger.info("Saved planned run run_id=%s planned=%d", run_id, len(planned_sends))


def load_run(run_id: str) -> dict | None:
    sb = _client()
    resp = (
        sb.table("email_send_previews")
        .select("*")
        .eq("run_id", run_id)
        .maybe_single()
        .execute()
    )
    return resp.data


def update_status(
    run_id: str,
    new_status: str,
    expected_status: str = "pending_approval",
    telegram_msg_id: str | None = None,
) -> bool:
    """
    Transition the run status with optimistic concurrency on expected_status.
    Returns True if the row was updated, False if it was already in a different state.
    """
    sb = _client()
    now_iso = datetime.now(timezone.utc).isoformat()

    updates: dict = {"status": new_status}

    if telegram_msg_id is not None:
        updates["telegram_msg_id"] = telegram_msg_id

    if new_status == "approved":
        updates["approved_at"] = now_iso
    elif new_status == "cancelled":
        updates["cancelled_at"] = now_iso
    elif new_status == "sent":
        updates["sent_at"] = now_iso

    resp = (
        sb.table("email_send_previews")
        .update(updates)
        .eq("run_id", run_id)
        .eq("status", expected_status)
        .execute()
    )

    affected = len(resp.data or [])
    if affected == 0:
        logger.warning(
            "update_status no-op: run_id=%s expected=%s new=%s (already transitioned?)",
            run_id,
            expected_status,
            new_status,
        )
        return False

    logger.info("run_id=%s status %s -> %s", run_id, expected_status, new_status)
    return True


def update_telegram_msg_id(run_id: str, telegram_msg_id: str) -> None:
    sb = _client()
    sb.table("email_send_previews").update(
        {"telegram_msg_id": telegram_msg_id}
    ).eq("run_id", run_id).execute()


def sweep_expired_runs() -> list[dict]:
    """
    Mark any pending_approval rows whose expires_at is in the past as expired.
    Returns the list of rows that were just expired so the caller can notify Telegram.
    """
    sb = _client()
    now_iso = datetime.now(timezone.utc).isoformat()

    resp = (
        sb.table("email_send_previews")
        .update({"status": "expired"})
        .eq("status", "pending_approval")
        .lt("expires_at", now_iso)
        .execute()
    )

    expired = resp.data or []
    if expired:
        run_ids = [r["run_id"] for r in expired]
        logger.info("Swept %d expired run(s): %s", len(expired), run_ids)

    return expired
