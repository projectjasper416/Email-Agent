-- Migration: email_send_previews
-- One row per daily agent run. Holds the planned batch and approval state.
-- Run in Supabase SQL editor before first deploy.

CREATE TABLE IF NOT EXISTS public.email_send_previews (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id          text        NOT NULL UNIQUE,
  status          text        NOT NULL DEFAULT 'pending_approval'
    CHECK (status IN ('pending_approval', 'approved', 'cancelled', 'sent', 'expired')),
  planned_sends   jsonb       NOT NULL,   -- array of full email dicts Claude produced
  summary         jsonb       NOT NULL,   -- { total_send, total_skip, campaigns: {...} }
  sample_email    jsonb,                  -- one representative entry for the Telegram summary
  telegram_msg_id text,                   -- id of the summary message; null until posted
  expires_at      timestamptz NOT NULL,   -- now() + APPROVAL_WINDOW_HOURS at insert time
  approved_at     timestamptz,
  cancelled_at    timestamptz,
  sent_at         timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_email_send_previews_status_expires
  ON public.email_send_previews(status, expires_at);

CREATE INDEX IF NOT EXISTS idx_email_send_previews_telegram_msg
  ON public.email_send_previews(telegram_msg_id);

ALTER TABLE public.email_send_previews ENABLE ROW LEVEL SECURITY;
-- No user-facing select policy — operator-internal table only.
-- Service role reads/writes; no end-user rows exist here.
