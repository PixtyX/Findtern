"""
main.py — DM-based pipeline orchestrator.

Flow per cron run:
  1. Bootstrap database schema
  2. Clean up stale data (>48h old)
  3. Process pending callbacks (settings UI + Show More delivery)
  4. Fetch new internships from JSearch API
  5. Global deduplication against sent_jobs
  6. Per-user delivery: filter by preferences → DM first 5 + Show More

Design principles:
  - 100% DM-based — no channel, no broadcast, no spam
  - Users explore at their own pace via /start → preferences → Show More
  - Users who haven't set preferences get a gentle nudge, not job blasts
  - Max 5 messages per cron run per user (they tap Show More for more)
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

from database import (
    init_db,
    is_job_new,
    mark_job_as_sent,
    cleanup_expired_batches,
    get_all_active_users,
    create_user_digest,
    pop_user_digest_jobs,
    has_user_digest_jobs,
    get_user_last_digest,
    update_user_last_digest,
)
from fetcher import fetch_internships
from telegram import (
    send_dm,
    build_job_card,
    get_pending_callbacks,
    answer_callback,
)
from preferences import (
    build_settings_menu,
    handle_settings_callback,
    handle_keyword_input,
    matches_preferences,
    should_send_digest,
)

# ---------------------------------------------------------------------------
# Delivery tuning
# ---------------------------------------------------------------------------
BATCH_SIZE = 5
MAX_SHOW_ALL = 50


# ────────────────────────────────────────────────────────────────────
# Callback processing
# ────────────────────────────────────────────────────────────────────
def handle_update(update: dict):
    """
    Process a single Telegram update (used by both webhook and polling).
    Handles callback queries and text commands in real time.
    """
    # ── Callback queries (button taps) ──
    cq = update.get("callback_query")
    if cq:
        cq_id = cq.get("id", "")
        data = cq.get("data", "")
        from_user = cq.get("from", {})
        user_id = str(from_user.get("id", ""))

        if not user_id:
            answer_callback(cq_id, "Error: no user ID")
            return

        settings_prefixes = ("settings:", "dept:", "loc:", "remote:", "freq:", "kw:")
        if any(data.startswith(p) for p in settings_prefixes):
            handle_settings_callback(cq_id, user_id, data)
            return

        if data.startswith("udmore:"):
            _handle_show_more(cq_id, user_id)
            return

        if data.startswith("udall:"):
            _handle_show_all(cq_id, user_id)
            return

        answer_callback(cq_id, "Unknown action")
        return

    # ── Text messages (commands + keyword input) ──
    msg = update.get("message")
    if not msg:
        return

    text = (msg.get("text") or "").strip()
    from_user = msg.get("from", {})
    user_id = str(from_user.get("id", ""))

    if not user_id or not text:
        return

    # Non-command text → keyword input
    if not text.startswith("/"):
        handle_keyword_input(user_id, text)
        return

    # Bot commands
    cmd = text.split()[0].lower().split("@")[0]
    if cmd in ("/start", "/settings"):
        send_dm(user_id,
            "<b>Welcome to Findtern!</b>\n\n"
            "Set up your preferences below to get personalized "
            "internship alerts delivered right here.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n",
        )
        menu_text, kb = build_settings_menu(user_id)
        send_dm(user_id, menu_text, reply_markup=kb)
    elif cmd == "/cancel":
        from preferences import _pending_keyword_lock, _pending_keyword_user
        with _pending_keyword_lock:
            _pending_keyword_user.pop(user_id, None)
        send_dm(user_id, "✅ Cancelled. Use /settings to configure preferences.")
    elif cmd == "/help":
        send_dm(user_id,
            "<b>Findtern — Commands</b>\n\n"
            "/start — Set up your preferences\n"
            "/settings — Change your preferences\n"
            "/cancel — Cancel keyword entry\n"
            "/help — Show this message\n\n"
            "You'll automatically receive personalized "
            "internship alerts based on your preferences."
        )


def _process_callbacks():
    """
    Fetch pending updates from Telegram via polling and route them.
    Used by the cron-based flow. The webhook server calls handle_update() directly.
    """
    callbacks, text_commands = get_pending_callbacks()

    for user_id, text in text_commands:
        handle_update({"message": {"text": text, "from": {"id": int(user_id)}}})

    for cq in callbacks:
        handle_update({"callback_query": cq})


# ────────────────────────────────────────────────────────────────────
# Per-user job delivery (Show More / Show All)
# ────────────────────────────────────────────────────────────────────
def _handle_show_more(cq_id: str, user_id: str):
    """Pop next BATCH_SIZE jobs from a user's digest and DM them."""
    jobs = pop_user_digest_jobs(user_id, count=BATCH_SIZE)
    if not jobs:
        answer_callback(cq_id, "No more listings — start a new search with /start")
        return

    still_pending = has_user_digest_jobs(user_id)
    for job in jobs:
        card = build_job_card(job)
        keyboard = None
        if still_pending:
            keyboard = {
                "inline_keyboard": [
                    [{"text": "Show More", "callback_data": f"udmore:{user_id}"}],
                    [{"text": "Show All", "callback_data": f"udall:{user_id}"}],
                ]
            }
        send_dm(user_id, card, reply_markup=keyboard)

    if still_pending:
        answer_callback(cq_id, f"Sent {len(jobs)} — more available")
    else:
        answer_callback(cq_id, f"Sent {len(jobs)} — that's all")
        send_dm(user_id,
            "✅ <b>Findtern — All caught up!</b>\n\n"
            "You've seen all new listings for this round.\n"
            "New jobs are checked every 6 hours. You'll get a DM "
            "when something matching your preferences appears.\n\n"
            "Use /settings to change your preferences anytime."
        )


def _handle_show_all(cq_id: str, user_id: str):
    """Send ALL remaining jobs from a user's digest. Capped at MAX_SHOW_ALL."""
    total_sent = 0
    while has_user_digest_jobs(user_id):
        if total_sent >= MAX_SHOW_ALL:
            send_dm(user_id,
                f"⚠️ Reached the {MAX_SHOW_ALL}-job limit. "
                "Use <b>Show More</b> to continue."
            )
            break
        jobs = pop_user_digest_jobs(user_id, count=BATCH_SIZE)
        if not jobs:
            break
        for job in jobs:
            send_dm(user_id, build_job_card(job))
            total_sent += 1

    answer_callback(cq_id, f"✅ Delivered {total_sent} listing(s)!")
    send_dm(user_id,
        "✅ <b>Findtern — All listings delivered!</b>\n\n"
        "New jobs are checked every 6 hours. Use /settings anytime."
    )


def _deliver_to_users(new_jobs: list):
    """
    For each active user with preferences:
      1. Filter new_jobs against their preferences
      2. Create a digest in user_digests
      3. DM first BATCH_SIZE with Show More button
    Users WITHOUT preferences are silently skipped (they get nudged on /start).
    """
    users = get_all_active_users()
    if not users:
        print("[main] No users with preferences set up yet.")
        return

    print(f"[main] Processing delivery for {len(users)} user(s)…")

    delivered = 0
    for user in users:
        user_id = user["chat_id"]

        # Check frequency — skip if not enough time has passed
        last_digest = get_user_last_digest(user_id)
        if not should_send_digest(user, last_digest):
            print(f"[main] User {user_id}: frequency check skipped.")
            continue

        # Filter jobs matching this user's preferences
        matched = [job for job in new_jobs if matches_preferences(job, user)]
        if not matched:
            print(f"[main] User {user_id}: no matching jobs.")
            continue

        # Create digest
        create_user_digest(user_id, matched)

        # Pop first batch and send
        first_batch = pop_user_digest_jobs(user_id, count=BATCH_SIZE)
        total = len(matched)
        remaining = total - len(first_batch)

        # Build summary for this user
        header = (
            f"<b>Findtern — {total} New Internship{'s' if total != 1 else ''} For You!</b>\n\n"
        )
        cards = [build_job_card(job) for job in first_batch]
        footer = "\n━━━━━━━━━━━━━━━━━━━━\n"
        keyboard = None

        if remaining > 0:
            footer += f"\n{remaining} more available. Tap below:"
            keyboard = {
                "inline_keyboard": [
                    [{"text": "Show More", "callback_data": f"udmore:{user_id}"}],
                    [{"text": "Show All", "callback_data": f"udall:{user_id}"}],
                    [{"text": "Settings", "callback_data": "settings:main"}],
                ]
            }
        else:
            footer += "\nThat's all for this round!"
            keyboard = {
                "inline_keyboard": [
                    [{"text": "Settings", "callback_data": "settings:main"}],
                ]
            }

        text = header + "\n\n".join(cards) + footer

        MAX_MSG_LEN = 4096
        if len(text) > MAX_MSG_LEN:
            text = text[:MAX_MSG_LEN - 20] + "\n\n… (truncated)"

        if send_dm(user_id, text, reply_markup=keyboard):
            delivered += 1
            update_user_last_digest(user_id)
            print(f"[main] User {user_id}: sent {len(first_batch)}/{total} matched jobs.")
        else:
            print(f"[main] User {user_id}: DM failed (user may have blocked bot).")

    print(f"[main] Delivered to {delivered}/{len(users)} user(s).")


# ────────────────────────────────────────────────────────────────────
# Job seeding
# ────────────────────────────────────────────────────────────────────
def _mark_jobs_sent(jobs: list):
    """Mark a list of job dicts as sent in the dedup table."""
    for job in jobs:
        job_id = job.get("job_id", "") or ""
        if not job_id:
            continue
        mark_job_as_sent(
            job_id=job_id,
            title=job.get("job_title", ""),
            company=job.get("employer_name", ""),
            link=job.get("job_apply_link", "") or "",
        )


# ────────────────────────────────────────────────────────────────────
# Main pipeline
# ────────────────────────────────────────────────────────────────────
def main() -> None:
    # ── 1. Schema bootstrap ──
    print("[main] Initializing database…")
    init_db()

    # ── 2. Cleanup ──
    cleanup_expired_batches(max_age_hours=48)

    # ── 3. Process callbacks (only in polling mode — skip when webhook is active) ──
    if "--with-callbacks" in sys.argv:
        _process_callbacks()

    # ── 4. Fetch new internships ──
    print("[main] Fetching internships…")
    raw_jobs = fetch_internships()
    if not raw_jobs:
        print("[main] No jobs returned from API. Exiting.")
        sys.exit(0)

    print(f"[main] Received {len(raw_jobs)} raw listings.")

    # ── 5. Global deduplication ──
    new_jobs = []
    for job in raw_jobs:
        job_id = job.get("job_id", "") or ""
        if not job_id:
            continue
        if not is_job_new(job_id):
            continue
        new_jobs.append(job)

    total = len(new_jobs)
    if total == 0:
        print("[main] No new jobs found. Exiting.")
        sys.exit(0)

    print(f"[main] Found {total} new (not previously seen) listings.")

    # ── 6. Mark all as seen globally ──
    _mark_jobs_sent(new_jobs)

    # ── 7. Per-user personalized DM delivery ──
    _deliver_to_users(new_jobs)

    print(f"[main] Done. {total} new listings processed.")


# ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        if "--callbacks-only" in sys.argv:
            # Lightweight mode: just process Telegram interactions (for frequent cron)
            print("[main] Callbacks-only mode…")
            init_db()
            _process_callbacks()
            print("[main] Callbacks processed.")
            sys.exit(0)
        main()
    except Exception as exc:
        print(f"[main] FATAL: {exc}")
        sys.exit(1)
