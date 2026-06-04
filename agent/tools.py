TOOLS = [
    {
        "name": "get_eligible_users",
        "description": (
            "Fetch all free users eligible for a marketing email today. "
            "This tool already applies all suppression and frequency-cap filters: "
            "premium users, unsubscribed users, users emailed in the last 4 days by "
            "either the AI agent or the legacy cron, and users whose account is less "
            "than 1 day old are all excluded before you see the list. "
            "You do not need to second-guess eligibility — trust the list and focus on "
            "deciding what to send each user. "
            "Returns a list of user profile objects and the total eligible count. "
            "Call this tool exactly once at the start of your run."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_user_detail",
        "description": (
            "Fetch a deeper profile for a single user by their UUID. "
            "Returns identity fields and the full onboarding_answers JSONB object. "
            "Call this mid-loop when the profile from get_eligible_users appears "
            "incomplete or you need to verify a specific field before using it in copy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "The UUID of the user to fetch.",
                }
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "get_user_email_history",
        "description": (
            "Return the recent email history for a single user from both the AI agent "
            "log and the legacy cron system. Each entry shows campaign_key, subject, "
            "decision (sent/skipped), and sent_at. "
            "NOTE: open and click data are NOT available — do not infer engagement "
            "from this tool; you only know what was sent, not whether it was read. "
            "Use this to avoid repeating an angle that has already been tried recently."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "The UUID of the user.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return per system. Defaults to 5.",
                    "default": 5,
                },
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "send_email",
        "description": (
            "Record a planned email send for this user. The full batch is reviewed by "
            "a human operator via Telegram before any email is actually delivered — "
            "calling this tool does NOT immediately dispatch an email. "
            "You write the subject (max 50 chars) and body (2-3 warm, conversational "
            "sentences personalized to this specific user's situation). "
            "Choose a campaign_key that is a short snake_case label describing the "
            "angle you are using, e.g. 'hit_tailor_limit_upgrade' or "
            "'skill_gap_found_tailor'. "
            "The cta_url should be a deep link to the most relevant app page, not "
            "just the homepage. "
            "Returns {queued: true, run_id, position} confirming the record was saved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "UUID of the recipient.",
                },
                "email": {
                    "type": "string",
                    "description": "Email address of the recipient.",
                },
                "campaign_key": {
                    "type": "string",
                    "description": "Short snake_case label for this campaign angle.",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line. Max 50 characters.",
                },
                "body": {
                    "type": "string",
                    "description": (
                        "Email body. 2-3 sentences, warm and conversational. "
                        "Personalized to this user's situation. "
                        "No spam trigger words (free, urgent, limited time, guaranteed)."
                    ),
                },
                "cta_text": {
                    "type": "string",
                    "description": "CTA button label, e.g. 'Tailor my resume now'.",
                },
                "cta_url": {
                    "type": "string",
                    "description": "Deep link URL for the CTA button.",
                },
            },
            "required": ["user_id", "email", "campaign_key", "subject", "body", "cta_text", "cta_url"],
        },
    },
    {
        "name": "skip_user",
        "description": (
            "Log that you have decided not to email this user today. "
            "You MUST call this for every user you decide not to email — "
            "silently skipping a user without calling this tool is not acceptable. "
            "The skip log is the audit trail used to review and improve targeting. "
            "Provide a 1-2 sentence reason explaining the specific signal that led "
            "to this skip decision."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "UUID of the user being skipped.",
                },
                "reason": {
                    "type": "string",
                    "description": "1-2 sentences explaining why you are skipping this user.",
                },
            },
            "required": ["user_id", "reason"],
        },
    },
]
