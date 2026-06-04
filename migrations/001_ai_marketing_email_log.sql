-- Migration: ai_marketing_email_log
-- Per-user audit trail for every agent decision (sent + skipped).
-- Run in Supabase SQL editor before first deploy.

CREATE TABLE IF NOT EXISTS public.ai_marketing_email_log (
  id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             uuid        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  run_id              text,                            -- links to email_send_previews.run_id
  sent_to_email       text        NOT NULL,
  campaign_key        text        NOT NULL,            -- free-form, AI-chosen snake_case label
  subject             text        NOT NULL,
  decision            text        NOT NULL DEFAULT 'sent'
    CHECK (decision IN ('sent', 'skipped')),
  status              text        NOT NULL DEFAULT 'sent'
    CHECK (status IN ('sent', 'failed')),
  decision_reason     text,                            -- Claude's 1-2 sentence explanation
  signals_snapshot    jsonb,                           -- full user profile dict at decision time
  model               text,                            -- e.g. 'claude-haiku-4-5-20251001'
  provider_message_id text,                            -- Resend message id for successful sends
  error_message       text,                            -- populated when status='failed'
  sent_at             timestamptz NOT NULL DEFAULT now(),
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_marketing_email_log_user_id
  ON public.ai_marketing_email_log(user_id);

CREATE INDEX IF NOT EXISTS idx_ai_marketing_email_log_sent_at
  ON public.ai_marketing_email_log(sent_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_marketing_email_log_campaign
  ON public.ai_marketing_email_log(campaign_key);

CREATE INDEX IF NOT EXISTS idx_ai_marketing_email_log_run_id
  ON public.ai_marketing_email_log(run_id);

ALTER TABLE public.ai_marketing_email_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ai_marketing_email_log_select_own ON public.ai_marketing_email_log;
CREATE POLICY ai_marketing_email_log_select_own
  ON public.ai_marketing_email_log
  FOR SELECT
  USING (auth.uid() = user_id);
-- Inserts performed by service role from both Lambdas (bypasses RLS).
