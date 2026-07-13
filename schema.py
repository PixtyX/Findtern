"""
schema.py — Database schema definitions.

Tables:
  sent_jobs           — master dedup table (one row per unique job)
  job_batches         — tracks each "new jobs found" event (channel)
  pending_callbacks   — stores queued job IDs for channel "Show More"
  user_preferences    — per-user customization (departments, locations, etc.)
  user_digests        — per-user job delivery queue
"""

# ---------- sent_jobs ----------
SENT_JOBS_DDL = """
CREATE TABLE IF NOT EXISTS sent_jobs (
    job_id     TEXT PRIMARY KEY,
    title      TEXT,
    company    TEXT,
    link       TEXT,
    date_found TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# ---------- job_batches ----------
JOB_BATCHES_DDL = """
CREATE TABLE IF NOT EXISTS job_batches (
    batch_id       TEXT PRIMARY KEY,
    total_new_jobs INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'active',
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# ---------- pending_callbacks ----------
PENDING_CALLBACKS_DDL = """
CREATE TABLE IF NOT EXISTS pending_callbacks (
    id             SERIAL PRIMARY KEY,
    batch_id       TEXT NOT NULL REFERENCES job_batches(batch_id) ON DELETE CASCADE,
    remaining_jobs TEXT NOT NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# ---------- user_preferences ----------
# Stores per-user customization for personalized job delivery.
# chat_id is the Telegram user/chat ID (negative for groups, positive for DMs).
USER_PREFERENCES_DDL = """
CREATE TABLE IF NOT EXISTS user_preferences (
    chat_id          TEXT PRIMARY KEY,
    departments      TEXT NOT NULL DEFAULT '[]',
    locations        TEXT NOT NULL DEFAULT '[]',
    custom_keywords  TEXT NOT NULL DEFAULT '[]',
    remote_pref      TEXT NOT NULL DEFAULT 'any',
    notify_frequency TEXT NOT NULL DEFAULT '6h',
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    last_digest_at   TIMESTAMP,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# ---------- user_digests ----------
# Per-user queue of matched jobs waiting to be delivered.
# remaining_jobs is a JSON array of full job dicts (same as pending_callbacks).
USER_DIGESTS_DDL = """
CREATE TABLE IF NOT EXISTS user_digests (
    id              SERIAL PRIMARY KEY,
    chat_id         TEXT NOT NULL,
    remaining_jobs  TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
