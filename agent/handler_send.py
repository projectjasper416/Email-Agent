"""
Lambda 2 — Phase 2: Send

Triggered by:
  - API Gateway HTTP POST /telegram/callback (Telegram webhook)

Responsibilities:
  1. Verify the Telegram webhook secret, chat ID, and run state
  2. On Approve: dispatch all planned emails via Resend, log sends
  3. On Cancel: mark the run cancelled
  4. Edit the Telegram summary to reflect the final outcome
  5. Always return 200 to Telegram (prevents retries)

This is the ONLY place email_service is imported. Lambda 1 must never import it.
"""

import json
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv

from services import email_service, preview_service, supabase_service, telegram_service

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def marketing_agent_send(event: dict, context) -> dict:
    """
    Always returns 200 to Telegram regardless of outcome.
    Failures are logged to CloudWatch and reflected in the Telegram message.
    """
    try:
        _run(event)
    except ValueError as exc:
        # Auth / validation failure — log and return 200 silently
        logger.warning("Rejected Telegram callback: %s", exc)
    except Exception:
        logger.exception("Unhandled error in marketing_agent_send")

    # Always 200 — Telegram must not retry
    return {"statusCode": 200, "body": ""}


def _run(event: dict) -> None:
    # Parse and validate the callback (raises ValueError on auth failure)
    parsed = telegram_service.parse_callback(event)
    run_id = parsed["run_id"]
    action = parsed["action"]
    callback_query_id = parsed["callback_query_id"]
    message_id = parsed["message_id"]

    logger.info("Received callback run_id=%s action=%s", run_id, action)

    # Load the preview row
    run_row = preview_service.load_run(run_id)
    now = datetime.now(timezone.utc)

    if not run_row:
        telegram_service.edit_summary(message_id, f"⚠️ Run {run_id} not found.")
        telegram_service.answer_callback(callback_query_id, "Run not found.")
        return

    # State + expiry check
    if run_row["status"] != "pending_approval":
        telegram_service.edit_summary(
            message_id,
            f"ℹ️ Run {run_id} is already in state '{run_row['status']}' — no action taken.",
        )
        telegram_service.answer_callback(callback_query_id, f"Already {run_row['status']}.")
        return

    expires_at_str = run_row.get("expires_at", "")
    if expires_at_str:
        from services.supabase_service import _parse_dt
        expires_at = _parse_dt(expires_at_str)
        if expires_at and now > expires_at:
            # Mark as expired if the sweeper missed it
            preview_service.update_status(run_id, "expired")
            telegram_service.edit_summary(
                message_id,
                f"⏰ Run {run_id} has expired — no emails were sent.",
            )
            telegram_service.answer_callback(callback_query_id, "Run expired.")
            return

    if action == "cancel":
        _handle_cancel(run_id, message_id, callback_query_id)
    elif action == "approve":
        _handle_approve(run_id, run_row, message_id, callback_query_id)


def _handle_cancel(run_id: str, message_id: str, callback_query_id: str) -> None:
    updated = preview_service.update_status(run_id, "cancelled")
    if not updated:
        telegram_service.answer_callback(callback_query_id, "Already processed.")
        return

    telegram_service.edit_summary(message_id, f"❌ Cancelled — 0 emails sent. (run_id: {run_id})")
    telegram_service.answer_callback(callback_query_id, "Cancelled.")
    logger.info("Run cancelled: run_id=%s", run_id)


def _handle_approve(
    run_id: str,
    run_row: dict,
    message_id: str,
    callback_query_id: str,
) -> None:
    # Transition to approved with optimistic concurrency
    updated = preview_service.update_status(run_id, "approved")
    if not updated:
        telegram_service.answer_callback(callback_query_id, "Already processed.")
        return

    # Acknowledge immediately so Telegram doesn't show a loading spinner
    telegram_service.answer_callback(callback_query_id, "Sending…")

    planned_sends: list[dict] = run_row.get("planned_sends") or []
    sent_count = 0
    failed_count = 0

    for entry in planned_sends:
        user_id = entry.get("user_id", "")
        email = entry.get("email", "")
        subject = entry.get("subject", "")
        body = entry.get("body", "")
        cta_text = entry.get("cta_text", "")
        cta_url = entry.get("cta_url", "")
        campaign_key = entry.get("campaign_key", "")
        signals = entry.get("signals_snapshot", {})

        try:
            provider_message_id = email_service.send_marketing_email(
                user_id=user_id,
                email=email,
                subject=subject,
                body=body,
                cta_text=cta_text,
                cta_url=cta_url,
            )
            supabase_service.log_decision(
                user_id=user_id,
                email=email,
                campaign_key=campaign_key,
                subject=subject,
                decision="sent",
                reason="Approved by operator and dispatched via Resend.",
                signals=signals,
                run_id=run_id,
                status="sent",
                provider_message_id=provider_message_id,
            )
            sent_count += 1

        except Exception as exc:
            logger.exception("Failed to send email to %s", email)
            failed_count += 1
            try:
                supabase_service.log_decision(
                    user_id=user_id,
                    email=email,
                    campaign_key=campaign_key,
                    subject=subject,
                    decision="sent",
                    reason="Operator approved; dispatch failed.",
                    signals=signals,
                    run_id=run_id,
                    status="failed",
                    error_message=str(exc),
                )
            except Exception:
                logger.exception("Failed to log failed send for %s", email)

    # Mark the run complete
    preview_service.update_status(run_id, "sent", expected_status="approved")

    now_utc = datetime.now(timezone.utc).strftime("%H:%M UTC")
    if failed_count == 0:
        outcome = f"✅ Sent {sent_count} emails at {now_utc} — run_id: {run_id}"
    else:
        outcome = (
            f"✅ Sent {sent_count} emails at {now_utc} "
            f"({failed_count} failed) — run_id: {run_id}"
        )

    telegram_service.edit_summary(message_id, outcome)
    logger.info("Approve complete: run_id=%s sent=%d failed=%d", run_id, sent_count, failed_count)
