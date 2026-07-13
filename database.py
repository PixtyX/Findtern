"""
database.py — Supabase PostgreSQL layer with batch pagination support.

Every function opens and explicitly closes its own cursor + connection
in a finally block to prevent connection-pool exhaustion on serverless
runners where long-lived pools are unreliable.
"""

import json
import os
import secrets
import psycopg2
from psycopg2 import pool

from schema import (
    SENT_JOBS_DDL,
    JOB_BATCHES_DDL,
    PENDING_CALLBACKS_DDL,
    USER_PREFERENCES_DDL,
    USER_DIGESTS_DDL,
)


# ────────────────────────────────────────────────────────────────────
# Connection pool (thread-safe, reuses connections across requests)
# ────────────────────────────────────────────────────────────────────
_pool = None


def _get_pool():
    """Lazy-init a threaded connection pool."""
    global _pool
    if _pool is None:
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            raise RuntimeError("DATABASE_URL environment variable is not set.")
        _pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=url,
        )
    return _pool


def get_connection():
    """Return a psycopg2 connection from the pool."""
    return _get_pool().getconn()


def _release_connection(conn):
    """Return a connection to the pool."""
    if _pool and conn:
        _pool.putconn(conn)


# ────────────────────────────────────────────────────────────────────
# Schema bootstrap
# ────────────────────────────────────────────────────────────────────
def init_db():
    """Create all tables if they do not exist."""
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(SENT_JOBS_DDL)
        cur.execute(JOB_BATCHES_DDL)
        cur.execute(PENDING_CALLBACKS_DDL)
        cur.execute(USER_PREFERENCES_DDL)
        cur.execute(USER_DIGESTS_DDL)
        conn.commit()
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


# ────────────────────────────────────────────────────────────────────
# Job deduplication (sent_jobs)
# ────────────────────────────────────────────────────────────────────
def is_job_new(job_id: str) -> bool:
    """Return True when *job_id* is NOT already present in sent_jobs."""
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM sent_jobs WHERE job_id = %s", (job_id,))
        return cur.fetchone() is None
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


def mark_job_as_sent(job_id: str, title: str, company: str, link: str = ""):
    """
    Insert a record into sent_jobs and commit.
    Safe to call with a job_id that may already exist (upsert).
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO sent_jobs (job_id, title, company, link)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (job_id) DO NOTHING
            """,
            (job_id, title, company, link),
        )
        conn.commit()
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


# ────────────────────────────────────────────────────────────────────
# Batch pagination
# ────────────────────────────────────────────────────────────────────
def _mk_batch_id() -> str:
    """Generate an 8-character hex batch identifier."""
    return secrets.token_hex(4)


def create_batch(job_dicts: list) -> str:
    """
    Create a new batch and store the list of job dicts as a pending-callback
    entry. Returns the batch_id.

    *job_dicts* is a list of raw job dicts (from JSearch).
    We persist the full dicts as JSON so we can build Telegram messages
    later without re-fetching from the API.
    """
    batch_id = _mk_batch_id()
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        # 1. Create the batch record
        cur.execute(
            "INSERT INTO job_batches (batch_id, total_new_jobs) VALUES (%s, %s)",
            (batch_id, len(job_dicts)),
        )

        # 2. Store ALL job dicts as pending (JSON-encoded)
        cur.execute(
            "INSERT INTO pending_callbacks (batch_id, remaining_jobs) VALUES (%s, %s)",
            (batch_id, json.dumps(job_dicts, default=str)),
        )

        conn.commit()
        return batch_id
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


def pop_pending_jobs(batch_id: str, count: int = 5) -> list:
    """
    Pop up to *count* job dicts from the pending queue for *batch_id*.
    Returns a list of job dicts (may be empty).
    Updates the remaining_jobs column in-place; deletes the row if exhausted.
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT id, remaining_jobs FROM pending_callbacks WHERE batch_id = %s",
            (batch_id,),
        )
        row = cur.fetchone()
        if row is None:
            return []

        pc_id, remaining_json = row
        remaining = json.loads(remaining_json)
        batch = remaining[:count]
        leftover = remaining[count:]

        if leftover:
            cur.execute(
                "UPDATE pending_callbacks SET remaining_jobs = %s WHERE id = %s",
                (json.dumps(leftover, default=str), pc_id),
            )
        else:
            cur.execute("DELETE FROM pending_callbacks WHERE id = %s", (pc_id,))
            # Mark the batch as completed
            cur.execute(
                "UPDATE job_batches SET status = 'completed' WHERE batch_id = %s",
                (batch_id,),
            )

        conn.commit()
        return batch
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


def has_pending_jobs(batch_id: str) -> bool:
    """Check whether a batch still has un-sent jobs."""
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT remaining_jobs FROM pending_callbacks WHERE batch_id = %s",
            (batch_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False
        remaining = json.loads(row[0])
        return len(remaining) > 0
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


# ────────────────────────────────────────────────────────────────────
# User preferences
# ────────────────────────────────────────────────────────────────────
def get_user_preference(chat_id: str) -> dict | None:
    """Return user preferences as a dict, or None if not set."""
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT departments, locations, custom_keywords,
                   remote_pref, notify_frequency, active
            FROM user_preferences WHERE chat_id = %s
            """,
            (chat_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "departments": json.loads(row[0]),
            "locations": json.loads(row[1]),
            "custom_keywords": json.loads(row[2]),
            "remote_pref": row[3],
            "notify_frequency": row[4],
            "active": row[5],
        }
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


def upsert_user_preference(
    chat_id: str,
    departments: list | None = None,
    locations: list | None = None,
    custom_keywords: list | None = None,
    remote_pref: str | None = None,
    notify_frequency: str | None = None,
):
    """Insert or update user preferences. Only provided fields are changed."""
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Build SET clause dynamically
        sets = []
        params = []
        if departments is not None:
            sets.append("departments = %s")
            params.append(json.dumps(departments))
        if locations is not None:
            sets.append("locations = %s")
            params.append(json.dumps(locations))
        if custom_keywords is not None:
            sets.append("custom_keywords = %s")
            params.append(json.dumps(custom_keywords))
        if remote_pref is not None:
            sets.append("remote_pref = %s")
            params.append(remote_pref)
        if notify_frequency is not None:
            sets.append("notify_frequency = %s")
            params.append(notify_frequency)

        if not sets:
            return

        sets.append("updated_at = CURRENT_TIMESTAMP")

        # Upsert: insert with defaults, then update provided fields
        cur.execute(
            """
            INSERT INTO user_preferences (chat_id)
            VALUES (%s)
            ON CONFLICT (chat_id) DO NOTHING
            """,
            (chat_id,),
        )

        cur.execute(
            f"UPDATE user_preferences SET {', '.join(sets)} WHERE chat_id = %s",
            params + [chat_id],
        )

        conn.commit()
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


def get_all_active_users() -> list:
    """
    Return list of dicts: [{chat_id, departments, locations, ...}, ...]
    Only returns users with active=TRUE.
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT chat_id, departments, locations, custom_keywords,
                   remote_pref, notify_frequency
            FROM user_preferences WHERE active = TRUE
            """
        )
        rows = cur.fetchall()
        users = []
        for row in rows:
            users.append({
                "chat_id": row[0],
                "departments": json.loads(row[1]),
                "locations": json.loads(row[2]),
                "custom_keywords": json.loads(row[3]),
                "remote_pref": row[4],
                "notify_frequency": row[5],
            })
        return users
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


# ────────────────────────────────────────────────────────────────────
# User digests (per-user job delivery queue)
# ────────────────────────────────────────────────────────────────────
def create_user_digest(chat_id: str, job_dicts: list):
    """Store a list of matched job dicts for a user's digest."""
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_digests (chat_id, remaining_jobs) VALUES (%s, %s)",
            (chat_id, json.dumps(job_dicts, default=str)),
        )
        conn.commit()
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


def pop_user_digest_jobs(chat_id: str, count: int = 5) -> list:
    """
    Pop up to *count* job dicts from a user's digest.
    Deletes the row when exhausted.
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT id, remaining_jobs FROM user_digests WHERE chat_id = %s ORDER BY id LIMIT 1",
            (chat_id,),
        )
        row = cur.fetchone()
        if row is None:
            return []

        digest_id, remaining_json = row
        remaining = json.loads(remaining_json)
        batch = remaining[:count]
        leftover = remaining[count:]

        if leftover:
            cur.execute(
                "UPDATE user_digests SET remaining_jobs = %s WHERE id = %s",
                (json.dumps(leftover, default=str), digest_id),
            )
        else:
            cur.execute("DELETE FROM user_digests WHERE id = %s", (digest_id,))

        conn.commit()
        return batch
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


def has_user_digest_jobs(chat_id: str) -> bool:
    """Check whether a user has pending digest jobs."""
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM user_digests WHERE chat_id = %s LIMIT 1",
            (chat_id,),
        )
        return cur.fetchone() is not None
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


def get_user_last_digest(chat_id: str):
    """Return the last_digest_at timestamp for a user, or None."""
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT last_digest_at FROM user_preferences WHERE chat_id = %s",
            (chat_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


def update_user_last_digest(chat_id: str):
    """Set last_digest_at to now for a user."""
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE user_preferences
            SET last_digest_at = CURRENT_TIMESTAMP
            WHERE chat_id = %s
            """,
            (chat_id,),
        )
        conn.commit()
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)


# ────────────────────────────────────────────────────────────────────
# Cleanup — call once per run
# ────────────────────────────────────────────────────────────────────
def cleanup_expired_batches(max_age_hours: int = 48):
    """
    Delete pending_callbacks and job_batches older than max_age_hours.
    This prevents stale batches from accumulating if users never click
    the button, and frees the DB from holding large JSON blobs forever.
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Delete stale pending_callbacks first (FK cascade also handles this,
        # but explicit delete avoids orphan warnings in logs)
        cur.execute(
            f"""
            DELETE FROM pending_callbacks
            WHERE batch_id IN (
                SELECT batch_id FROM job_batches
                WHERE created_at < NOW() - INTERVAL '{max_age_hours} hours'
            )
            """
        )

        # Delete stale batches
        cur.execute(
            f"""
            DELETE FROM job_batches
            WHERE created_at < NOW() - INTERVAL '{max_age_hours} hours'
            """
        )

        conn.commit()
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            _release_connection(conn)
