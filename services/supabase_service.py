"""
All Supabase interactions for the email marketing agent.

Uses the service role key (bypasses RLS) because the agent reads data
across all users — the anon key returns empty results due to RLS policies.
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
FREQUENCY_CAP_DAYS = 4


def _client() -> Client:
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


# ---------------------------------------------------------------------------
# get_eligible_users
# ---------------------------------------------------------------------------

def get_eligible_users() -> list[dict]:
    """
    Fetch all free users who pass suppression and frequency-cap filters,
    build a full behavioral profile for each, and return the list.
    """
    sb = _client()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=FREQUENCY_CAP_DAYS)

    # 1. All users
    users_resp = sb.table("users").select(
        "id, email, first_name, created_at, onboarding_answers, onboarding_questionnaire_completed"
    ).execute()
    users_by_id: dict[str, dict] = {u["id"]: u for u in (users_resp.data or [])}

    if not users_by_id:
        return []

    all_user_ids = list(users_by_id.keys())

    # 2. Subscriptions (absent row = free)
    subs_resp = sb.table("user_subscriptions").select(
        "user_id, is_premium, premium_expires_at, "
        "free_tailor_limit, free_tailor_uses, "
        "free_review_limit, free_review_uses, "
        "free_job_fit_limit, free_job_fit_uses, "
        "free_resume_limit, free_resume_uses"
    ).execute()
    subs_by_user: dict[str, dict] = {s["user_id"]: s for s in (subs_resp.data or [])}

    # 3. Unsubscribed users
    unsub_resp = sb.table("user_email_preferences").select(
        "user_id, marketing_unsubscribed_at"
    ).not_.is_("marketing_unsubscribed_at", "null").execute()
    unsubscribed_ids = {r["user_id"] for r in (unsub_resp.data or [])}

    # 4. Recent sends from AI log (frequency cap)
    ai_sends_resp = sb.table("ai_marketing_email_log").select(
        "user_id, sent_at"
    ).eq("decision", "sent").gte("sent_at", cutoff.isoformat()).execute()
    recently_ai_sent = {r["user_id"] for r in (ai_sends_resp.data or [])}

    # 5. Recent sends from legacy cron (frequency cap)
    legacy_resp = sb.table("email_campaign_sends").select(
        "user_id, sent_at"
    ).gte("sent_at", cutoff.isoformat()).execute()
    recently_legacy_sent = {r["user_id"] for r in (legacy_resp.data or [])}

    recently_emailed = recently_ai_sent | recently_legacy_sent

    # 6. Resumes (non-deleted)
    resumes_resp = sb.table("resumes").select(
        "id, user_id, is_reviewed, suggested_target_roles, created_at"
    ).eq("removed_by_user", False).execute()
    resumes_by_user: dict[str, list] = defaultdict(list)
    resume_id_to_user: dict[str, str] = {}
    for r in (resumes_resp.data or []):
        resumes_by_user[r["user_id"]].append(r)
        resume_id_to_user[r["id"]] = r["user_id"]

    # 7. Tailorings — no user_id; join via resumes
    tailorings_resp = sb.table("resume_ai_tailorings").select(
        "resume_id, created_at"
    ).execute()
    tailorings_by_user: dict[str, list] = defaultdict(list)
    for t in (tailorings_resp.data or []):
        uid = resume_id_to_user.get(t["resume_id"])
        if uid:
            tailorings_by_user[uid].append(t)

    # 8. Jobs
    jobs_resp = sb.table("jobs").select(
        "user_id, company, role, status, created_at, updated_at"
    ).execute()
    jobs_by_user: dict[str, list] = defaultdict(list)
    for j in (jobs_resp.data or []):
        jobs_by_user[j["user_id"]].append(j)

    # 9. Payments
    payments_resp = sb.table("payments").select(
        "user_id, status, created_at, paid_at"
    ).execute()
    payments_by_user: dict[str, list] = defaultdict(list)
    for p in (payments_resp.data or []):
        payments_by_user[p["user_id"]].append(p)

    # 10. LLM token usage (true last-active)
    token_resp = sb.table("llm_token_usage").select("user_id, created_at").execute()
    last_active_by_user: dict[str, str] = {}
    for t in (token_resp.data or []):
        uid = t["user_id"]
        if uid not in last_active_by_user or t["created_at"] > last_active_by_user[uid]:
            last_active_by_user[uid] = t["created_at"]

    # 11. Skill analysis (completed only)
    skill_resp = sb.table("user_resume_skill_analysis").select(
        "user_id, target_role, analysis_json, created_at"
    ).eq("status", "completed").execute()
    skill_by_user: dict[str, dict] = {}
    for s in (skill_resp.data or []):
        uid = s["user_id"]
        if uid not in skill_by_user or s["created_at"] > skill_by_user[uid]["created_at"]:
            skill_by_user[uid] = s

    # 12. Job fit analysis (completed only, most recent per user)
    fit_resp = sb.table("user_external_job_fit_analysis").select(
        "user_id, fit_json, status, resume_id_used, created_at"
    ).eq("status", "completed").execute()
    fit_by_user: dict[str, dict] = {}
    for f in (fit_resp.data or []):
        uid = f["user_id"]
        if uid not in fit_by_user or f["created_at"] > fit_by_user[uid]["created_at"]:
            fit_by_user[uid] = f

    # 13. LinkedIn optimization (completed only)
    linkedin_resp = sb.table("user_linkedin_optimization").select(
        "user_id, target_role, optimization_json, created_at"
    ).eq("status", "completed").execute()
    linkedin_by_user: dict[str, dict] = {}
    for li in (linkedin_resp.data or []):
        uid = li["user_id"]
        if uid not in linkedin_by_user or li["created_at"] > linkedin_by_user[uid]["created_at"]:
            linkedin_by_user[uid] = li

    # 14. Journal entries (power user signal)
    journal_resp = sb.table("user_journal_entries").select("user_id").execute()
    journal_users = {r["user_id"] for r in (journal_resp.data or [])}

    # --- Build profiles for eligible users ---
    profiles = []

    for user_id, user in users_by_id.items():
        # Suppression checks
        if user_id in unsubscribed_ids:
            continue
        if user_id in recently_emailed:
            continue

        # Free status check
        sub = subs_by_user.get(user_id)
        if _is_premium(sub, now):
            continue

        # Account age
        created_at = _parse_dt(user["created_at"])
        if created_at is None:
            continue
        account_age_days = (now - created_at).days
        if account_age_days < 1:
            continue

        profile = _build_profile(
            user=user,
            sub=sub,
            now=now,
            account_age_days=account_age_days,
            resumes=resumes_by_user.get(user_id, []),
            tailorings=tailorings_by_user.get(user_id, []),
            jobs=jobs_by_user.get(user_id, []),
            payments=payments_by_user.get(user_id, []),
            last_active_str=last_active_by_user.get(user_id),
            skill_row=skill_by_user.get(user_id),
            fit_row=fit_by_user.get(user_id),
            linkedin_row=linkedin_by_user.get(user_id),
            wrote_journal=user_id in journal_users,
        )

        # Account-age guardrail vs. the legacy cron.
        # The legacy cron owns the no-resume / not-tailored campaigns during a
        # user's first week (it fires on account-age days 3, 5, 7). So within
        # the first 7 days we stay out of exactly those users (anyone who has
        # not tailored yet) and let the legacy cron run. Past day 7 — or for
        # users who have already tailored at any age — the agent is free to
        # act; the 4-day frequency cap above is what prevents us from doubling
        # up with the legacy cron's day-30/45 touches.
        in_legacy_campaign_state = profile["tailoring_count"] == 0
        if account_age_days < 7 and in_legacy_campaign_state:
            continue

        profiles.append(profile)

    logger.info("get_eligible_users: returning %d eligible users", len(profiles))
    return profiles


def _is_premium(sub: dict | None, now: datetime) -> bool:
    if sub is None:
        return False
    if not sub.get("is_premium"):
        return False
    expires = sub.get("premium_expires_at")
    if expires is None:
        return True  # lifetime premium
    exp_dt = _parse_dt(expires)
    return exp_dt is not None and exp_dt > now


def _build_profile(
    user: dict,
    sub: dict | None,
    now: datetime,
    account_age_days: int,
    resumes: list,
    tailorings: list,
    jobs: list,
    payments: list,
    last_active_str: str | None,
    skill_row: dict | None,
    fit_row: dict | None,
    linkedin_row: dict | None,
    wrote_journal: bool,
) -> dict:
    oa = user.get("onboarding_answers") or {}

    # Subscription limits
    free_tailor_limit = (sub or {}).get("free_tailor_limit", 2)
    free_tailor_uses = (sub or {}).get("free_tailor_uses", 0)
    free_review_limit = (sub or {}).get("free_review_limit", 1)
    free_review_uses = (sub or {}).get("free_review_uses", 0)
    free_job_fit_limit = (sub or {}).get("free_job_fit_limit", 1)
    free_job_fit_uses = (sub or {}).get("free_job_fit_uses", 0)
    free_resume_limit = (sub or {}).get("free_resume_limit", 1)
    free_resume_uses = (sub or {}).get("free_resume_uses", 0)

    # resume_ai_tailorings has one row per resume *section*, so len(tailorings)
    # over-counts. The true number of tailorings the user has run is the quota
    # counter on the subscription.
    tailoring_count = free_tailor_uses
    tailorings_remaining = max(0, free_tailor_limit - free_tailor_uses)

    # Target role: onboarding first, then resume
    target_role = oa.get("targetRole") or oa.get("target_role")
    if not target_role and resumes:
        suggested = (resumes[0].get("suggested_target_roles") or [])
        target_role = suggested[0] if suggested else None

    # Funnel stage
    has_resume = len(resumes) > 0
    resume_reviewed = any(r.get("is_reviewed") for r in resumes)
    funnel_stage = _compute_funnel(has_resume, resume_reviewed, tailoring_count)

    # Last activity
    days_since_last_activity = None
    if last_active_str:
        last_active = _parse_dt(last_active_str)
        if last_active:
            days_since_last_activity = (now - last_active).days

    # Last tailoring
    days_since_last_tailoring = None
    if tailorings:
        latest_tailor_str = max(t["created_at"] for t in tailorings)
        latest_tailor = _parse_dt(latest_tailor_str)
        if latest_tailor:
            days_since_last_tailoring = (now - latest_tailor).days

    # Jobs
    job_statuses = [j.get("status") for j in jobs]
    has_interview_or_offer = any(s in ("Interview", "Offer") for s in job_statuses)

    # Abandoned checkout: has a 'created' payment but no 'paid' payment
    user_payments = payments
    has_created = any(p.get("status") == "created" for p in user_payments)
    has_paid = any(p.get("status") == "paid" for p in user_payments)
    abandoned_checkout = has_created and not has_paid

    # Feature objects
    skill_analysis = _extract_skill_analysis(skill_row)
    job_fit = _extract_job_fit(fit_row)
    linkedin_optimization = _extract_linkedin(linkedin_row, tailoring_count)

    unused_features = []
    if not skill_analysis or not skill_analysis.get("completed"):
        unused_features.append("skill_analysis")
    if not job_fit or not job_fit.get("completed"):
        unused_features.append("job_fit")
    if not linkedin_optimization or not linkedin_optimization.get("completed"):
        unused_features.append("linkedin_optimization")

    return {
        "id": user["id"],
        "email": user["email"],
        "first_name": user.get("first_name"),
        "account_age_days": account_age_days,
        "target_role": target_role,
        "goal": oa.get("goal"),
        "experience_level": oa.get("experienceLevel") or oa.get("experience_level"),
        "help_priority": oa.get("priority") or oa.get("help_priority"),
        "location_preference": oa.get("locationPreference") or oa.get("location_preference"),
        "onboarding_completed": user.get("onboarding_questionnaire_completed", False),
        "has_resume": has_resume,
        "resume_reviewed": resume_reviewed,
        "tailoring_count": tailoring_count,
        "tailorings_remaining": tailorings_remaining,
        "hit_tailor_limit": free_tailor_uses >= free_tailor_limit,
        "hit_review_limit": free_review_uses >= free_review_limit,
        "hit_job_fit_limit": free_job_fit_uses >= free_job_fit_limit,
        "hit_resume_limit": free_resume_uses >= free_resume_limit,
        "funnel_stage": funnel_stage,
        "days_since_last_activity": days_since_last_activity,
        "days_since_last_tailoring": days_since_last_tailoring,
        "jobs_tracked": len(jobs),
        "job_statuses": job_statuses,
        "has_interview_or_offer": has_interview_or_offer,
        "abandoned_checkout": abandoned_checkout,
        "skill_analysis": skill_analysis,
        "job_fit": job_fit,
        "linkedin_optimization": linkedin_optimization,
        "unused_features": unused_features,
        "wrote_journal": wrote_journal,
        "marketing_unsubscribed": False,  # already filtered above
    }


def _compute_funnel(has_resume: bool, resume_reviewed: bool, tailoring_count: int) -> str:
    if not has_resume:
        return "registered_no_resume"
    if not resume_reviewed:
        return "resume_no_review"
    if tailoring_count == 0:
        return "reviewed_not_tailored"
    return "tailored_active"


def _extract_skill_analysis(row: dict | None) -> dict | None:
    if not row:
        return None
    has_gaps = None
    try:
        analysis = row.get("analysis_json")
        if isinstance(analysis, str):
            analysis = json.loads(analysis)
        if isinstance(analysis, dict):
            # Defensively probe common key patterns
            gaps = analysis.get("skill_gaps") or analysis.get("gaps") or analysis.get("missing_skills")
            if gaps is not None:
                has_gaps = bool(gaps)
    except Exception:
        pass
    return {
        "completed": True,
        "target_role": row.get("target_role"),
        "has_gaps": has_gaps,
    }


def _extract_job_fit(row: dict | None) -> dict | None:
    if not row:
        return None
    fit_score = None
    fit_level = None
    try:
        fit = row.get("fit_json")
        if isinstance(fit, str):
            fit = json.loads(fit)
        if isinstance(fit, dict):
            score = fit.get("fit_score") or fit.get("score") or fit.get("overall_score")
            if score is not None:
                fit_score = int(score)
                if fit_score >= 75:
                    fit_level = "strong"
                elif fit_score >= 50:
                    fit_level = "partial"
                else:
                    fit_level = "weak"
    except Exception:
        pass
    return {
        "completed": True,
        "fit_score": fit_score,
        "fit_level": fit_level,
    }


def _extract_linkedin(row: dict | None, tailoring_count: int) -> dict | None:
    if not row:
        return None
    return {
        "completed": True,
        "target_role": row.get("target_role"),
        "has_resume_tailoring": tailoring_count > 0,
    }


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ---------------------------------------------------------------------------
# get_user_detail
# ---------------------------------------------------------------------------

def get_user_detail(user_id: str) -> dict:
    sb = _client()
    resp = sb.table("users").select(
        "id, email, first_name, created_at, onboarding_answers, onboarding_questionnaire_completed"
    ).eq("id", user_id).maybe_single().execute()
    return resp.data or {}


# ---------------------------------------------------------------------------
# get_user_email_history
# ---------------------------------------------------------------------------

def get_user_email_history(user_id: str, limit: int = 5) -> dict:
    sb = _client()

    ai_resp = (
        sb.table("ai_marketing_email_log")
        .select("campaign_key, subject, decision, sent_at")
        .eq("user_id", user_id)
        .order("sent_at", desc=True)
        .limit(limit)
        .execute()
    )

    legacy_resp = (
        sb.table("email_campaign_sends")
        .select("campaign_type, sent_at")
        .eq("user_id", user_id)
        .order("sent_at", desc=True)
        .limit(limit)
        .execute()
    )

    return {
        "ai_agent_emails": ai_resp.data or [],
        "legacy_emails": legacy_resp.data or [],
    }


# ---------------------------------------------------------------------------
# log_decision
# ---------------------------------------------------------------------------

def log_decision(
    user_id: str,
    email: str,
    campaign_key: str,
    subject: str,
    decision: str,
    reason: str,
    signals: dict,
    run_id: str,
    status: str = "sent",
    provider_message_id: str | None = None,
    error_message: str | None = None,
) -> None:
    sb = _client()
    row = {
        "user_id": user_id,
        "run_id": run_id,
        "sent_to_email": email,
        "campaign_key": campaign_key,
        "subject": subject,
        "decision": decision,
        "status": status,
        "decision_reason": reason,
        "signals_snapshot": signals,
        "model": MODEL,
        "provider_message_id": provider_message_id,
        "error_message": error_message,
    }
    try:
        sb.table("ai_marketing_email_log").insert(row).execute()
    except Exception:
        logger.exception(
            "Failed to log decision user_id=%s decision=%s", user_id, decision
        )
