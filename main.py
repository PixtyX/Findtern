"""
main.py — Pipeline orchestrator.

Fetches → filters → deduplicates → dispatches via Telegram (HTML parse mode).

Telegram HTML parse mode is used intentionally: raw job descriptions often
contain Markdown-special characters ([, _, *, !) that cause HTTP 400 errors
when sent in Markdown mode.
"""

import os
import sys
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment bootstrap
# load_dotenv() is a no-op when running on GitHub Actions (no .env present),
# so it acts as a silent local-debug helper only.
# ---------------------------------------------------------------------------
load_dotenv()

from database import init_db, is_job_new, mark_job_as_sent
from fetcher import fetch_internships

# ---------------------------------------------------------------------------
# Target keywords — all lowercase for safe substring matching
# ---------------------------------------------------------------------------
TARGET_KEYWORDS = [
    "it intern",
    "software engineer",
    "web developer",
    "php",
    "sql",
    "iot",
    "cybersecurity",
    "digital forensics",
    "information technology",
    "computer science",
]


def is_relevant(title: str, description: str) -> bool:
    """
    Return True when ANY target keyword appears as a substring
    in the combined (title + description) lowercased text.
    """
    combined = f"{title} {description}".lower()
    return any(kw in combined for kw in TARGET_KEYWORDS)


def _escape_html(text: str) -> str:
    """
    Escape the five HTML-special characters Telegram requires.
    Keep this lightweight — the full html.escape() set is unnecessary
    because Telegram's parser only cares about <, >, & inside tag names.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def send_telegram_message(text: str) -> bool:
    """
    Post *text* to the configured Telegram channel using HTML parse mode.

    Returns True on success, False on failure (caller decides whether to
    continue or halt the pipeline).
    """
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("[telegram] TELEGRAM_TOKEN or TELEGRAM_CHAT_ID missing.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            print(f"[telegram] HTTP {resp.status_code}: {resp.text[:300]}")
            return False
        return True
    except requests.exceptions.RequestException as exc:
        print(f"[telegram] Delivery failed: {exc}")
        return False


def _build_message(job: dict) -> str:
    """
    Construct an HTML-formatted Telegram message for a single job dict.
    Uses safe .get() to avoid NoneType concatenation.
    """
    title = _escape_html(job.get("job_title", "Untitled"))
    company = _escape_html(job.get("employer_name", "Unknown"))
    location = _escape_html(job.get("job_city", "") or job.get("job_country", "N/A"))
    link = job.get("job_apply_link", "") or job.get("job_google_link", "")

    lines = [
        f"🚀 <b>New Internship Found!</b>",
        f"<b>Role:</b> {title}",
        f"<b>Company:</b> {company}",
        f"<b>Location:</b> {location}",
    ]
    if link:
        lines.append(f'<a href="{link}">Apply Here</a>')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pipeline entry-point
# ---------------------------------------------------------------------------
def main() -> None:
    print("[main] Initializing database…")
    init_db()

    print("[main] Fetching internships…")
    jobs = fetch_internships()
    if not jobs:
        print("[main] No jobs returned. Exiting.")
        sys.exit(0)

    print(f"[main] Received {len(jobs)} listings. Processing…")

    dispatched = 0
    for job in jobs:
        title = job.get("job_title", "") or ""
        description = job.get("job_description", "") or ""
        job_id = job.get("job_id", "") or ""

        # --- Stage 1: keyword relevance ---
        if not is_relevant(title, description):
            continue

        # --- Stage 2: deduplication ---
        if not job_id:
            print("[main] Skipping job with empty job_id.")
            continue
        if not is_job_new(job_id):
            continue

        # --- Stage 3: dispatch ---
        message = _build_message(job)
        if send_telegram_message(message):
            mark_job_as_sent(
                job_id=job_id,
                title=title,
                company=job.get("employer_name", "Unknown"),
            )
            dispatched += 1
            print(f"[main] ✓ Sent: {title}")

    print(f"[main] Done. Dispatched {dispatched} new listing(s).")


if __name__ == "__main__":
    main()
