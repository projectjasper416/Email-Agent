"""
Telegram Bot API integration via raw HTTPS requests.
No wrapper SDK — requests directly to the Bot API endpoints.
"""

import json
import logging
import os
import time
from collections import Counter

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE_LEN = 4096
TRUNCATE_AT = 3500
DEFAULT_FULL_DISPLAY_MAX = 100


def _token() -> str:
    return os.environ["TELEGRAM_BOT_TOKEN"]


def _chat_id() -> str:
    return os.environ["TELEGRAM_CHAT_ID"]


def _preview_mode() -> str:
    return os.environ.get("TELEGRAM_PREVIEW_MODE", "full").lower()


def _full_display_max() -> int:
    return int(os.environ.get("TELEGRAM_FULL_DISPLAY_MAX", str(DEFAULT_FULL_DISPLAY_MAX)))


def _post(method: str, payload: dict) -> dict:
    url = TELEGRAM_API.format(token=_token(), method=method)
    resp = requests.post(url, json=payload, timeout=15)
    data = resp.json()
    if not data.get("ok"):
        logger.error("Telegram API error method=%s: %s", method, data)
    return data


def send_preview(
    run_id: str,
    planned_sends: list[dict],
    summary: dict,
    expires_at_str: str,
) -> str | None:
    """
    Post per-email previews (in full mode) and the summary message with
    Approve/Cancel buttons. Returns the summary message_id.
    """
    mode = _preview_mode()
    total_send = len(planned_sends)
    total_skip = summary.get("total_skip", 0)

    if mode == "full":
        _send_full_previews(run_id, planned_sends)
    elif mode == "sample":
        _send_sample_preview(run_id, planned_sends)
    # summary mode: no per-email messages

    summary_text = _build_summary_text(run_id, total_send, total_skip, summary, expires_at_str)

    approve_data = f"approve:{run_id}"
    cancel_data = f"cancel:{run_id}"

    result = _post("sendMessage", {
        "chat_id": _chat_id(),
        "text": summary_text,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve & Send", "callback_data": approve_data},
                    {"text": "❌ Cancel Run", "callback_data": cancel_data},
                ]
            ]
        },
    })

    if result.get("ok"):
        return str(result["result"]["message_id"])

    logger.error("Failed to send Telegram summary for run_id=%s", run_id)
    return None


def _send_full_previews(run_id: str, planned_sends: list[dict]) -> None:
    total = len(planned_sends)
    use_paginated = total > _full_display_max()

    if use_paginated:
        _send_paginated_previews(run_id, planned_sends)
        return

    for i, entry in enumerate(planned_sends, start=1):
        text = _format_email_preview(i, total, entry)
        _post("sendMessage", {"chat_id": _chat_id(), "text": text})
        time.sleep(1.0)  # respect Telegram per-chat rate limit (~1/sec)


def _send_paginated_previews(run_id: str, planned_sends: list[dict]) -> None:
    page_size = 5
    total = len(planned_sends)

    for page_start in range(0, total, page_size):
        chunk = planned_sends[page_start: page_start + page_size]
        lines = []
        for i, entry in enumerate(chunk, start=page_start + 1):
            name = entry.get("first_name") or ""
            email = entry.get("email", "")
            display = f"{name} <{email}>" if name else email
            lines.append(
                f"[{i}/{total}] {entry.get('campaign_key', '')}\n"
                f"  To: {display}\n"
                f"  Subject: {entry.get('subject', '')}"
            )
        text = "\n\n".join(lines)
        if len(text) > MAX_MESSAGE_LEN:
            text = text[: MAX_MESSAGE_LEN - 20] + "\n[truncated]"
        _post("sendMessage", {"chat_id": _chat_id(), "text": text})
        time.sleep(1.0)


def _send_sample_preview(run_id: str, planned_sends: list[dict]) -> None:
    if not planned_sends:
        return
    sample = planned_sends[:3]
    lines = ["Sample emails from this run:\n"]
    for i, entry in enumerate(sample, start=1):
        lines.append(_format_email_preview(i, len(planned_sends), entry))
    text = "\n\n---\n\n".join(lines)
    text += f"\n\nFull list in Supabase: email_send_previews / run_id={run_id}"
    if len(text) > MAX_MESSAGE_LEN:
        text = text[: MAX_MESSAGE_LEN - 20] + "\n[truncated]"
    _post("sendMessage", {"chat_id": _chat_id(), "text": text})
    time.sleep(1.0)


def _format_email_preview(n: int, total: int, entry: dict) -> str:
    name = entry.get("first_name") or ""
    email = entry.get("email", "")
    display = f"{name} <{email}>" if name else email
    body = entry.get("body", "")
    if len(body) > TRUNCATE_AT:
        run_id = entry.get("run_id", "")
        body = body[:TRUNCATE_AT] + f"\n[truncated — full body in email_send_previews / {run_id}]"

    text = (
        f"Email {n} of {total} • {entry.get('campaign_key', '')}\n"
        f"To: {display}\n"
        f"Subject: {entry.get('subject', '')}\n\n"
        f"{body}\n\n"
        f"CTA: \"{entry.get('cta_text', '')}\" → {entry.get('cta_url', '')}"
    )
    if len(text) > MAX_MESSAGE_LEN:
        text = text[: MAX_MESSAGE_LEN - 20] + "\n[truncated]"
    return text


def _build_summary_text(
    run_id: str,
    total_send: int,
    total_skip: int,
    summary: dict,
    expires_at_str: str,
) -> str:
    campaigns: dict = summary.get("campaigns", {})
    top = sorted(campaigns.items(), key=lambda x: x[1], reverse=True)[:5]
    top_lines = "\n".join(f"  {k:<35} {v:>3}" for k, v in top) if top else "  (none)"

    expires_display = expires_at_str.replace("+00:00", " UTC").replace("T", " ")[:19] + " UTC"

    lines = [
        "ResumeSetGo Email Agent — Daily Preview",
        f"Run ID: {run_id}",
        "─" * 40,
        f"Planned:  {total_send} emails",
        f"Skipped: {total_skip} users",
        f"Expires: {expires_display}",
        "",
        "Top campaigns:",
        top_lines,
    ]
    return "\n".join(lines)


def edit_summary(message_id: str, new_text: str) -> None:
    """Replace the summary text and strip the inline keyboard."""
    if len(new_text) > MAX_MESSAGE_LEN:
        new_text = new_text[: MAX_MESSAGE_LEN - 20] + "\n[truncated]"
    _post("editMessageText", {
        "chat_id": _chat_id(),
        "message_id": int(message_id),
        "text": new_text,
        "reply_markup": {"inline_keyboard": []},
    })


def answer_callback(callback_query_id: str, text: str) -> None:
    """Show a small toast to the operator in the Telegram UI. Fire-and-forget."""
    try:
        _post("answerCallbackQuery", {
            "callback_query_id": callback_query_id,
            "text": text,
        })
    except Exception:
        logger.exception("answer_callback failed (non-fatal)")


def send_notice(text: str) -> None:
    """Post a plain informational message to the operator chat."""
    _post("sendMessage", {"chat_id": _chat_id(), "text": text})


def parse_callback(event: dict) -> dict:
    """
    Parse and validate an API Gateway event containing a Telegram callback_query.
    Returns {run_id, action, callback_query_id, message_id} or raises ValueError.

    Three-layer security check:
      1. X-Telegram-Bot-Api-Secret-Token header matches TELEGRAM_WEBHOOK_SECRET
      2. callback_query.from.id matches TELEGRAM_CHAT_ID
      3. callback_query.data is 'approve:<run_id>' or 'cancel:<run_id>'
    """
    webhook_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

    # Layer 1: webhook secret header (API Gateway lowercases header names)
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    incoming_secret = headers.get("x-telegram-bot-api-secret-token", "")
    if not webhook_secret or incoming_secret != webhook_secret:
        raise ValueError("Invalid or missing webhook secret token")

    # Parse body
    body = event.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    callback_query = body.get("callback_query")
    if not callback_query:
        raise ValueError("Not a callback_query event")

    # Layer 2: sender must be the operator
    from_id = str(callback_query.get("from", {}).get("id", ""))
    expected_chat_id = str(_chat_id())
    if from_id != expected_chat_id:
        raise ValueError(f"callback from unexpected user id={from_id}")

    # Layer 3: parse action:run_id
    data = callback_query.get("data", "")
    parts = data.split(":", 1)
    if len(parts) != 2 or parts[0] not in ("approve", "cancel"):
        raise ValueError(f"Unexpected callback_data: {data!r}")

    action, run_id = parts[0], parts[1]
    callback_query_id = str(callback_query.get("id", ""))
    message_id = str(callback_query.get("message", {}).get("message_id", ""))

    return {
        "run_id": run_id,
        "action": action,
        "callback_query_id": callback_query_id,
        "message_id": message_id,
    }
