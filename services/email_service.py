"""
Resend email delivery service.
ONLY imported by handler_send.py (Lambda 2).
Lambda 1 must never import this module.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import resend
from dotenv import load_dotenv

from services.email_template import build_email_html

load_dotenv()

logger = logging.getLogger(__name__)

FROM_ADDRESS = "ResumeSetGo <contact@resumesetgo.in>"


def send_marketing_email(
    user_id: str,
    email: str,
    subject: str,
    body: str,
    cta_text: str,
    cta_url: str,
) -> str:
    """
    Dispatch a single marketing email via Resend.
    Returns the Resend message ID on success.
    Raises an exception on failure so the caller can log and continue.
    """
    resend.api_key = os.environ["RESEND_API_KEY"]

    unsubscribe_url = _build_unsubscribe_url(user_id, email)
    html = build_email_html(
        body=body,
        cta_text=cta_text,
        cta_url=cta_url,
        unsubscribe_url=unsubscribe_url,
    )

    params = {
        "from": FROM_ADDRESS,
        "to": [email],
        "subject": subject,
        "html": html,
        "headers": {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    }

    result = resend.Emails.send(params)
    message_id = result.get("id") or result.get("message_id") or str(result)
    logger.info("Sent email to %s message_id=%s", email, message_id)
    return message_id


def _build_unsubscribe_url(user_id: str, email: str) -> str:
    """
    Build an HMAC-signed unsubscribe token byte-compatible with the existing
    Node.js backend verifyUnsubscribeToken implementation.

    Token format: <payload_b64url>.<signature_b64url>

    Payload JSON: {"userId": "<uuid>", "email": "<lowercased>", "exp": <ms-epoch +180d>}
    Signature: HMAC-SHA256(payload_b64url, EMAIL_UNSUBSCRIBE_SECRET)
    """
    secret = os.environ["EMAIL_UNSUBSCRIBE_SECRET"]
    backend_url = os.environ["BACKEND_PUBLIC_URL"].rstrip("/")

    exp_ms = int(
        (datetime.now(timezone.utc) + timedelta(days=180)).timestamp() * 1000
    )
    payload_dict = {
        "userId": user_id,
        "email": email.lower(),
        "exp": exp_ms,
    }
    payload_json = json.dumps(payload_dict, separators=(",", ":"))
    payload_b64 = _b64url(payload_json.encode())

    sig = hmac.new(
        secret.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64url(sig)

    token = f"{payload_b64}.{sig_b64}"
    return f"{backend_url}/internal/email-campaigns/unsubscribe?token={token}"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
