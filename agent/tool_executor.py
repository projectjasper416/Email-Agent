import json
import logging

from services import supabase_service

logger = logging.getLogger(__name__)

# Snapshot of user profiles indexed by user_id, populated when get_eligible_users runs.
# Used to attach signals_snapshot to send_email calls without a second DB round-trip.
_user_profile_cache: dict[str, dict] = {}


def execute_tool(
    tool_name: str,
    tool_input: dict,
    planned_sends: list,
    skip_log: list,
    run_id: str,
    counters: dict,
) -> str:
    try:
        if tool_name == "get_eligible_users":
            return _get_eligible_users()

        if tool_name == "get_user_detail":
            return _get_user_detail(tool_input)

        if tool_name == "get_user_email_history":
            return _get_user_email_history(tool_input)

        if tool_name == "send_email":
            return _send_email(tool_input, planned_sends, run_id, counters)

        if tool_name == "skip_user":
            return _skip_user(tool_input, skip_log, run_id, counters)

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    except Exception as exc:
        logger.exception("Unhandled error in execute_tool tool=%s", tool_name)
        counters["errors"] += 1
        return json.dumps({"error": str(exc)})


def _get_eligible_users() -> str:
    try:
        users = supabase_service.get_eligible_users()
        # Populate the profile cache so send_email can attach signals_snapshot
        _user_profile_cache.clear()
        for u in users:
            _user_profile_cache[u["id"]] = u
        return json.dumps({"eligible_count": len(users), "users": users})
    except Exception as exc:
        logger.exception("get_eligible_users failed")
        return json.dumps({"error": str(exc), "eligible_count": 0, "users": []})


def _get_user_detail(tool_input: dict) -> str:
    try:
        user_id = tool_input["user_id"]
        detail = supabase_service.get_user_detail(user_id)
        return json.dumps(detail)
    except Exception as exc:
        logger.exception("get_user_detail failed user_id=%s", tool_input.get("user_id"))
        return json.dumps({"error": str(exc)})


def _get_user_email_history(tool_input: dict) -> str:
    try:
        user_id = tool_input["user_id"]
        limit = tool_input.get("limit", 5)
        history = supabase_service.get_user_email_history(user_id, limit)
        return json.dumps(history)
    except Exception as exc:
        logger.exception("get_user_email_history failed user_id=%s", tool_input.get("user_id"))
        return json.dumps({"error": str(exc)})


def _send_email(tool_input: dict, planned_sends: list, run_id: str, counters: dict) -> str:
    user_id = tool_input["user_id"]
    signals_snapshot = _user_profile_cache.get(user_id, {})

    entry = {
        "user_id": user_id,
        "email": tool_input["email"],
        "campaign_key": tool_input["campaign_key"],
        "subject": tool_input["subject"],
        "body": tool_input["body"],
        "cta_text": tool_input["cta_text"],
        "cta_url": tool_input["cta_url"],
        "signals_snapshot": signals_snapshot,
        "run_id": run_id,
    }

    # Derive first_name for the Telegram preview
    entry["first_name"] = signals_snapshot.get("first_name", "")

    planned_sends.append(entry)
    position = len(planned_sends)
    counters["sends"] += 1

    logger.info(
        "Queued send #%d: user_id=%s campaign=%s subject=%s",
        position,
        user_id,
        tool_input["campaign_key"],
        tool_input["subject"],
    )

    return json.dumps({"queued": True, "run_id": run_id, "position": position})


def _skip_user(tool_input: dict, skip_log: list, run_id: str, counters: dict) -> str:
    user_id = tool_input["user_id"]
    reason = tool_input["reason"]
    signals_snapshot = _user_profile_cache.get(user_id, {})

    supabase_service.log_decision(
        user_id=user_id,
        email=signals_snapshot.get("email", ""),
        campaign_key="skip",
        subject="",
        decision="skipped",
        reason=reason,
        signals=signals_snapshot,
        run_id=run_id,
    )

    skip_entry = {"user_id": user_id, "reason": reason}
    skip_log.append(skip_entry)
    counters["skips"] += 1

    logger.info("Skipped user_id=%s reason=%s", user_id, reason)
    return json.dumps({"skipped": True, "user_id": user_id})
