"""
telegram.py — Telegram Bot API client with rate limiting and callback handling.

Design decisions:
  - HTML parse mode only (never Markdown — raw job descriptions break it)
  - 1-second delay between message sends to respect Telegram rate limits
  - Callback query processing via getUpdates (no webhook server needed)
  - All HTML-unsafe characters are escaped before sending
"""

import os
import time
import requests

# ────────────────────────────────────────────────────────────────────
# Rate limiting
# ────────────────────────────────────────────────────────────────────
_last_send_ts: float = 0.0
RATE_LIMIT_DELAY: float = 1.0  # seconds between sends


def _rate_limit():
    """Sleep if necessary to maintain the minimum delay between sends."""
    global _last_send_ts
    elapsed = time.time() - _last_send_ts
    if elapsed < RATE_LIMIT_DELAY:
        time.sleep(RATE_LIMIT_DELAY - elapsed)
    _last_send_ts = time.time()


# ────────────────────────────────────────────────────────────────────
# HTML escaping
# ────────────────────────────────────────────────────────────────────
def escape_html(text: str) -> str:
    """
    Escape characters that Telegram's HTML parser requires.
    Order matters: & first, then < and >.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ────────────────────────────────────────────────────────────────────
# API helpers
# ────────────────────────────────────────────────────────────────────
def _bot_url(method: str) -> str:
    """Build a Telegram Bot API URL."""
    token = os.environ.get("TELEGRAM_TOKEN", "")
    return f"https://api.telegram.org/bot{token}/{method}"


def _chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "")


def _check_credentials() -> bool:
    """Return True if TELEGRAM_TOKEN is present."""
    token = os.environ.get("TELEGRAM_TOKEN", "")
    if not token:
        print("[telegram] TELEGRAM_TOKEN is missing.")
        return False
    return True


# ────────────────────────────────────────────────────────────────────
# Message sending
# ────────────────────────────────────────────────────────────────────
def send_message(text: str, reply_markup: dict | None = None) -> bool:
    """
    Send an HTML-formatted message to the configured chat.
    Kept for backward compatibility — prefer send_dm() for new code.
    """
    if not _check_credentials():
        return False

    _rate_limit()
    token = os.environ.get("TELEGRAM_TOKEN", "")

    payload = {
        "chat_id": _chat_id(),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        resp = requests.post(
            _bot_url("sendMessage"), json=payload, timeout=15
        )
        if resp.status_code != 200:
            # Redact token from URL before logging
            safe_body = resp.text[:300].replace(token, "***") if token else resp.text[:300]
            print(f"[telegram] sendMessage HTTP {resp.status_code}: {safe_body}")
            return False
        return True
    except requests.exceptions.RequestException as exc:
        print(f"[telegram] sendMessage failed: {exc}")
        return False


def send_dm(user_id: str, text: str, reply_markup: dict | None = None) -> bool:
    """
    Send a direct message to a specific user by their Telegram user/chat ID.
    Used for personalized settings UI and per-user job delivery.
    """
    token = os.environ.get("TELEGRAM_TOKEN", "")
    if not token:
        print("[telegram] TELEGRAM_TOKEN is missing.")
        return False

    _rate_limit()

    payload = {
        "chat_id": user_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        resp = requests.post(
            _bot_url("sendMessage"), json=payload, timeout=15
        )
        if resp.status_code != 200:
            # Check if user blocked the bot (403 Forbidden)
            if resp.status_code == 403:
                print(f"[telegram] User {user_id} blocked the bot or hasn't started it")
                return False
            safe_body = resp.text[:300].replace(token, "***") if token else resp.text[:300]
            print(f"[telegram] send_dm HTTP {resp.status_code}: {safe_body}")
            return False
        return True
    except requests.exceptions.RequestException as exc:
        print(f"[telegram] send_dm failed: {exc}")
        return False


# ────────────────────────────────────────────────────────────────────
# Message building
# ────────────────────────────────────────────────────────────────────
def build_job_card(job: dict) -> str:
    """
    Build an HTML-formatted Telegram message for a single job dict.
    Uses safe .get() to avoid NoneType errors.
    Validates apply link to prevent javascript: or data: URI injection.
    """
    title = escape_html(job.get("job_title", "Untitled"))
    company = escape_html(job.get("employer_name", "Unknown"))
    location = escape_html(
        job.get("job_city", "") or job.get("job_country", "N/A")
    )
    link = job.get("job_apply_link", "") or job.get("job_google_link", "")

    # Validate link scheme — only allow https:// (blocks javascript:, data:, etc.)
    if link and not link.startswith(("https://", "http://")):
        link = ""

    lines = [
        f"<b>{title}</b>",
        f"<b>Company:</b> {company}",
        f"<b>Location:</b> {location}",
    ]
    if link:
        lines.append(f'<a href="{link}">Apply Here</a>')
    return "\n".join(lines)


def build_summary_message(count: int, first_batch: list, batch_id: str) -> tuple:
    """
    Build the initial summary message + inline keyboard.
    Enforces Telegram's 4096-char message limit.

    Returns (message_text, reply_markup_dict).
    """
    MAX_MSG_LEN = 4096

    header = (
        f"📢 <b>{count} New Internship{'s' if count != 1 else ''} Found!</b>\n\n"
        f"Here are the first {len(first_batch)}:\n"
        "─────────────────\n"
    )

    cards = []
    for job in first_batch:
        cards.append(build_job_card(job))

    footer = "\n─────────────────\n"

    remaining = count - len(first_batch)
    keyboard = None
    if remaining > 0:
        footer += f"\n📋 {remaining} more available. Tap below to see them."
        keyboard = {
            "inline_keyboard": [
                [{"text": "📋 Show More", "callback_data": f"more:{batch_id}"}],
                [{"text": "🔔 Show All", "callback_data": f"all:{batch_id}"}],
            ]
        }
    else:
        footer += "\n✅ That's all for this round!"

    text = header + "\n\n".join(cards) + footer

    # Guard: truncate if over Telegram's 4096-char limit
    if len(text) > MAX_MSG_LEN:
        text = text[: MAX_MSG_LEN - 20] + "\n\n… (truncated)"

    return text, keyboard


def build_next_batch_message(
    batch: list, batch_id: str, total_remaining: int
) -> tuple:
    """
    Build a "here are more jobs" message + inline keyboard.
    Enforces Telegram's 4096-char message limit.

    Returns (message_text, reply_markup_dict).
    """
    MAX_MSG_LEN = 4096

    header = f"📋 <b>More Internships ({len(batch)}):</b>\n\n"
    cards = [build_job_card(job) for job in batch]
    footer = "\n─────────────────\n"

    keyboard = None
    if total_remaining > 0:
        footer += f"\n📋 {total_remaining} more remaining."
        keyboard = {
            "inline_keyboard": [
                [{"text": "📋 Show More", "callback_data": f"more:{batch_id}"}],
                [{"text": "🔔 Show All", "callback_data": f"all:{batch_id}"}],
            ]
        }
    else:
        footer += "\n✅ You've seen all new listings!"

    text = header + "\n\n".join(cards) + footer

    # Guard: truncate if over Telegram's 4096-char limit
    if len(text) > MAX_MSG_LEN:
        text = text[: MAX_MSG_LEN - 20] + "\n\n… (truncated)"

    return text, keyboard


# ────────────────────────────────────────────────────────────────────
# Callback query processing
# ────────────────────────────────────────────────────────────────────
def get_pending_callbacks() -> tuple:
    """
    Fetch unprocessed updates from Telegram via getUpdates.

    Returns (callbacks_list, text_commands_list).
    callbacks_list: list of callback_query dicts
    text_commands_list: list of (user_id, command_text) tuples for bot commands
    """
    if not _check_credentials():
        return [], []

    params = {"offset": -1, "limit": 100, "timeout": 0}
    try:
        resp = requests.get(
            _bot_url("getUpdates"), params=params, timeout=10
        )
        if resp.status_code != 200:
            print(f"[telegram] getUpdates HTTP {resp.status_code}")
            return [], []

        data = resp.json()
        if not data.get("ok"):
            return [], []

        updates = data.get("result", [])
        callbacks = []
        text_commands = []
        max_update_id = 0

        for update in updates:
            uid = update.get("update_id", 0)
            if uid > max_update_id:
                max_update_id = uid

            # Callback queries (button taps)
            cq = update.get("callback_query")
            if cq:
                callbacks.append(cq)
                continue

            # Text messages (commands like /start, /settings, or keyword input)
            msg = update.get("message")
            if msg:
                text = (msg.get("text") or "").strip()
                from_user = msg.get("from", {})
                user_id = str(from_user.get("id", ""))
                if user_id and text:
                    text_commands.append((user_id, text))

        # Acknowledge all updates so Telegram doesn't re-deliver them
        if max_update_id > 0:
            _acknowledge_updates(max_update_id)

        return callbacks, text_commands

    except requests.exceptions.RequestException as exc:
        print(f"[telegram] getUpdates failed: {exc}")
        return [], []


def _acknowledge_updates(last_update_id: int):
    """
    Tell Telegram we've processed everything up to last_update_id.
    Uses offset = last_update_id + 1 to mark all prior as read.
    """
    try:
        requests.get(
            _bot_url("getUpdates"),
            params={"offset": last_update_id + 1, "timeout": 0},
            timeout=5,
        )
    except requests.exceptions.RequestException:
        pass  # best-effort


def answer_callback(callback_id: str, text: str = ""):
    """
    Answer a callback query to dismiss the loading indicator on the client.
    text — optional toast text shown briefly to the user.
    """
    if not _check_credentials():
        return

    try:
        requests.post(
            _bot_url("answerCallbackQuery"),
            json={"callback_query_id": callback_id, "text": text},
            timeout=10,
        )
    except requests.exceptions.RequestException:
        pass  # best-effort, not critical
