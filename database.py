"""
database.py — Supabase PostgreSQL deduplication layer.

All cursor/connection objects are opened and explicitly closed
inside every function to prevent connection-pool exhaustion on
serverless runners where long-lived pools are unreliable.
"""

import os
import psycopg2


def get_connection():
    """Return a psycopg2 connection using DATABASE_URL."""
    return psycopg2.connect(os.environ["DATABASE_URL"])


def init_db():
    """Create the sent_jobs table if it does not exist."""
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_jobs (
                job_id    TEXT PRIMARY KEY,
                title     TEXT,
                company   TEXT,
                date_found TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


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
            conn.close()


def mark_job_as_sent(job_id: str, title: str, company: str):
    """Insert a record into sent_jobs and commit."""
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sent_jobs (job_id, title, company) VALUES (%s, %s, %s)",
            (job_id, title, company),
        )
        conn.commit()
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()
