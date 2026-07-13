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

# Track whether startup has already run (gunicorn forks workers)
_startup_done = False


# ────────────────────────────────────────────────────────────────────
# Webhook endpoint — Telegram sends updates here
# ────────────────────────────────────────────────────────────────────
@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    """Handle incoming Telegram update."""
    try:
        update = request.get_json(force=True, silent=True)
        if not update:
            return jsonify({"error": "invalid json"}), 400

        handle_update(update)
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
    """Ping own health endpoint every 14 minutes to prevent spin-down."""
    time.sleep(60)  # wait for server to start
    while True:
        try:
            port = int(os.environ.get("PORT", 8080))
            http_requests.get(f"http://127.0.0.1:{port}/", timeout=10)
        except Exception:
            pass
        time.sleep(14 * 60)


# ────────────────────────────────────────────────────────────────────
# Startup — register webhook URL with Telegram
# ────────────────────────────────────────────────────────────────────
def _startup():
    """One-time init: DB schema + webhook registration. Safe to call multiple times."""
    global _startup_done
    if _startup_done:
        return
    _startup_done = True

    if not TELEGRAM_TOKEN:
        print("[bot] ❌ TELEGRAM_TOKEN is not set.")
        return

    init_db()
    _register_webhook()

    # Start keep-alive thread on Render
    if os.environ.get("RENDER"):
        threading.Thread(target=_keep_alive, daemon=True).start()


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
# Gunicorn hook — runs once in the master process before workers fork
# ────────────────────────────────────────────────────────────────────
def on_starting(server):
    """Called just before the master process is initialized."""
    _startup()


def post_fork(server, worker):
    """Called after a worker has been forked."""
    _startup()


# ────────────────────────────────────────────────────────────────────
# Entry point (local dev only — production uses gunicorn)
# ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _startup()
    port = int(os.environ.get("PORT", 8080))
    print(f"[bot] Starting webhook server on port {port}…")
    app.run(host="0.0.0.0", port=port)
