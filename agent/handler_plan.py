"""
Lambda 1 — Phase 1: Plan

Triggered by:
  - EventBridge cron at 9am UTC daily
  - HTTP POST /run (with x-api-key) for manual replans

Responsibilities:
  1. Sweep expired pending_approval runs
  2. Run the MCP agentic loop via agent.py
  3. Save the planned batch to email_send_previews
  4. Push the Telegram preview and summary with Approve/Cancel buttons
  5. Back-fill telegram_msg_id on the preview row
  6. Return 200 with counts

Does NOT import email_service. Does NOT send any email.
"""

import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from agent.agent import run_agent
from services import preview_service, telegram_service

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def marketing_agent_plan(event: dict, context) -> dict:
    try:
        return _run(event)
    except Exception:
        logger.exception("Unhandled error in marketing_agent_plan")
        return _response(500, {"error": "Internal server error"})


def _run(event: dict) -> dict:
    now = datetime.now(timezone.utc)
    run_id = f"run_{now.strftime('%Y%m%d')}_{_seq(now)}"
    logger.info("Starting Phase 1 run_id=%s", run_id)

    # 1. Sweep expired runs
    expired = preview_service.sweep_expired_runs()
    for row in expired:
        count = len((row.get("planned_sends") or []))
        telegram_service.send_notice(
            f"⏰ Yesterday's batch expired unsent ({count} emails) — run_id: {row['run_id']}"
        )

    # 2. Run the MCP loop
    planned_sends, skip_log, counters = run_agent(run_id)
    total_send = len(planned_sends)
    total_skip = len(skip_log)
    logger.info("Loop finished: planned=%d skipped=%d turns=%d", total_send, total_skip, counters["turns"])

    if total_send == 0:
        telegram_service.send_notice(
            f"📭 run_id={run_id}: No emails planned for today ({total_skip} users skipped)."
        )
        return _response(200, {
            "run_id": run_id,
            "planned": 0,
            "skipped": total_skip,
            "message": "No emails to plan today.",
        })

    # 3. Build summary
    campaign_counts: Counter = Counter(e["campaign_key"] for e in planned_sends)
    summary = {
        "total_send": total_send,
        "total_skip": total_skip,
        "campaigns": dict(campaign_counts),
    }
    sample_email = planned_sends[0] if planned_sends else None

    # 4. Compute expiry
    approval_hours = int(os.environ.get("APPROVAL_WINDOW_HOURS", "2"))
    expires_at = now + timedelta(hours=approval_hours)

    # 5. Save to DB
    preview_service.save_planned_run(
        run_id=run_id,
        planned_sends=planned_sends,
        summary=summary,
        sample_email=sample_email,
        expires_at=expires_at,
    )

    # 6. Push Telegram preview
    telegram_msg_id = telegram_service.send_preview(
        run_id=run_id,
        planned_sends=planned_sends,
        summary=summary,
        expires_at_str=expires_at.isoformat(),
    )

    # 7. Back-fill telegram_msg_id
    if telegram_msg_id:
        preview_service.update_telegram_msg_id(run_id, telegram_msg_id)

    return _response(200, {
        "run_id": run_id,
        "planned": total_send,
        "skipped": total_skip,
        "telegram_msg_id": telegram_msg_id,
        "expires_at": expires_at.isoformat(),
    })


def _seq(now: datetime) -> str:
    # Simple sequence based on minute-of-day for human readability
    return f"{now.hour:02d}{now.minute:02d}"


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
