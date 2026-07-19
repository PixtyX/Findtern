"""
bot.py — Real-time Telegram webhook server.

Telegram pushes every user interaction (commands, button taps, text)
to this server instantly. No polling, no cron delay.

Deploy this as a long-running service (Railway, Render, Fly.io, etc.).
The cron workflow (run_bot.yml) handles job fetching + delivery separately.

Endpoints:
  POST /webhook/<secret>  — receives Telegram updates
  GET  /                  — health check (used by hosting platforms)
"""

import os
import hashlib
import threading
import time
import requests as http_requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

from database import init_db
from main import handle_update

# ────────────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
WEBHOOK_SECRET = os.environ.get(
    "WEBHOOK_SECRET",
    hashlib.sha256(TELEGRAM_TOKEN.encode()).hexdigest()[:32] if TELEGRAM_TOKEN else "change-me",
)

app = Flask(__name__)

# One-time startup flag — DB + webhook + keep-alive
_started = False

# Deduplicate Telegram retries — same update_id must not be processed twice
_seen_update_ids: set[int] = set()
_seen_update_ids_lock = threading.Lock()


# ────────────────────────────────────────────────────────────────────
# Webhook endpoint — Telegram sends updates here
# ────────────────────────────────────────────────────────────────────
@app.before_request
def _ensure_started():
    """Guarantee DB schema + webhook registration before first request."""
    global _started
    if _started:
        return
    _started = True
    _startup()


@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    """Handle incoming Telegram update.

    Returns 200 immediately and processes the update in a background thread
    so Telegram doesn't retry the callback while we're still working.
    Also deduplicates by update_id to ignore any retries that slip through.
    """
    try:
        update = request.get_json(force=True, silent=True)
        if not update:
            return jsonify({"error": "invalid json"}), 400

        # Deduplicate by update_id — Telegram retries if response is slow
        update_id = update.get("update_id", 0)
        if update_id:
            with _seen_update_ids_lock:
                if update_id in _seen_update_ids:
                    print(f"[webhook] Skipping duplicate update_id={update_id}")
                    return jsonify({"ok": True})
                _seen_update_ids.add(update_id)
                # Prevent unbounded growth — evict oldest half when too large
                if len(_seen_update_ids) > 10_000:
                    keep = sorted(_seen_update_ids)[-5000:]
                    _seen_update_ids = set(keep)

        # Process in background so the webhook responds instantly
        threading.Thread(target=handle_update, args=(update,), daemon=True).start()
        return jsonify({"ok": True})

    except Exception as exc:
        # Log but always return 200 — Telegram retries on non-2xx
        print(f"[webhook] Error processing update: {exc}")
        return jsonify({"ok": True})


# ────────────────────────────────────────────────────────────────────
# Health check
# ────────────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bot": "findtern"})


# ────────────────────────────────────────────────────────────────────
# Keep-alive — prevents Render free tier from spinning down
# ────────────────────────────────────────────────────────────────────
def _keep_alive():
    """Ping own health endpoint every 14 minutes to prevent spin-down.

    Uses the external URL when available so the request counts as real
    external traffic (Render free-tier only stays awake on external hits).
    Falls back to localhost if no external URL is set.
    """
    time.sleep(60)  # wait for server to start

    # Build the URL to ping — prefer external URL so Render sees real traffic
    base_url = (
        os.environ.get("RENDER_EXTERNAL_URL")
        or os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        or (f"https://{os.environ['FLY_APP_NAME']}.fly.dev" if os.environ.get("FLY_APP_NAME") else None)
        or os.environ.get("PUBLIC_URL")
        or ""
    )
    if base_url and not base_url.startswith("http"):
        base_url = f"https://{base_url}"

    if base_url:
        ping_url = f"{base_url}/"
        print(f"[keep-alive] Pinging external URL: {ping_url}")
    else:
        port = int(os.environ.get("PORT", 8080))
        ping_url = f"http://127.0.0.1:{port}/"
        print(f"[keep-alive] No external URL found, pinging localhost: {ping_url}")

    while True:
        try:
            resp = http_requests.get(ping_url, timeout=10)
            print(f"[keep-alive] Ping {resp.status_code}")
        except Exception as exc:
            print(f"[keep-alive] Ping failed: {exc}")
        time.sleep(14 * 60)


# ────────────────────────────────────────────────────────────────────
# Startup — register webhook URL with Telegram
# ────────────────────────────────────────────────────────────────────
def _startup():
    """One-time init: DB schema + webhook registration + keep-alive."""
    if not TELEGRAM_TOKEN:
        print("[bot] ❌ TELEGRAM_TOKEN is not set.")
        return

    print("[bot] Running startup…")
    init_db()
    _register_webhook()

    # Start keep-alive thread on Render
    if os.environ.get("RENDER"):
        threading.Thread(target=_keep_alive, daemon=True).start()
        print("[bot] Keep-alive thread started.")


def _register_webhook():
    """Tell Telegram where to send updates."""
    base_url = (
        os.environ.get("RENDER_EXTERNAL_URL")
        or os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        or (f"https://{os.environ['FLY_APP_NAME']}.fly.dev" if os.environ.get("FLY_APP_NAME") else None)
        or os.environ.get("PUBLIC_URL")
        or ""
    )

    if base_url and not base_url.startswith("http"):
        base_url = f"https://{base_url}"

    if not base_url:
        print("[bot] ⚠️  No PUBLIC_URL / RENDER_EXTERNAL_URL / RAILWAY_PUBLIC_DOMAIN set.")
        print("[bot]    Webhook not registered. Set the env var and restart.")
        return

    webhook_url = f"{base_url}/webhook/{WEBHOOK_SECRET}"

    resp = http_requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook",
        json={
            "url": webhook_url,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": False,  # don't lose messages on restart
        },
        timeout=15,
    )

    if resp.status_code == 200 and resp.json().get("ok"):
        print(f"[bot] ✅ Webhook registered: {webhook_url}")
    else:
        print(f"[bot] ❌ Webhook registration failed: {resp.text[:300]}")


# ────────────────────────────────────────────────────────────────────
# Entry point (local dev only — production uses gunicorn + @before_request)
# ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _started = True
    _startup()
    port = int(os.environ.get("PORT", 8080))
    print(f"[bot] Starting webhook server on port {port}…")
    app.run(host="0.0.0.0", port=port)
