# Findtern — IT/Tech Internship Aggregator & Telegram Alert Bot

A serverless pipeline that fetches IT internship postings from RapidAPI JSearch, filters them by technology keywords, deduplicates against a Supabase PostgreSQL database, and dispatches new listings to a Telegram channel using HTML parse mode.

## Architecture

```
┌────────────┐     ┌────────────┐     ┌────────────┐     ┌─────────────┐
│  JSearch   │────▶│  Keyword   │────▶│  Supabase   │────▶│  Telegram   │
│  API       │     │  Filter    │     │  Dedup DB   │     │  Channel    │
└────────────┘     └────────────┘     └────────────┘     └─────────────┘
     fetcher.py        main.py           database.py         main.py
```

## Files

| File                            | Purpose                                                        |
| ------------------------------- | -------------------------------------------------------------- |
| `database.py`                   | Supabase PostgreSQL connection & CRUD helpers                  |
| `fetcher.py`                    | RapidAPI JSearch HTTP client with rate-limit handling          |
| `main.py`                       | Pipeline orchestrator: fetch → filter → deduplicate → dispatch |
| `.github/workflows/run_bot.yml` | GitHub Actions cron (every 6 hours)                            |

## Setup

### 1. Supabase Database

Create a free project at [supabase.com](https://supabase.com), then run this SQL in the SQL Editor:

```sql
CREATE TABLE IF NOT EXISTS sent_jobs (
    job_id    TEXT PRIMARY KEY,
    title     TEXT,
    company   TEXT,
    date_found TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Copy the **direct** connection string (not pooled) from Settings → Database.

### 2. Telegram Bot

1. Message [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copy the bot token.
3. Add the bot to your channel/group as an admin.
4. Get the chat ID (use `https://api.telegram.org/bot<TOKEN>/getUpdates` after sending a message).

### 3. RapidAPI JSearch

1. Subscribe to the [JSearch API](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) on RapidAPI.
2. Copy your API key from the dashboard.

### 4. GitHub Secrets

Go to your repo → Settings → Secrets and variables → Actions, and add:

| Secret             | Value                                      |
| ------------------ | ------------------------------------------ |
| `TELEGRAM_TOKEN`   | Your Telegram bot token                    |
| `TELEGRAM_CHAT_ID` | Your channel/group chat ID                 |
| `RAPIDAPI_KEY`     | Your RapidAPI subscription key             |
| `DATABASE_URL`     | Your Supabase PostgreSQL connection string |

### 5. Local Development

```bash
cp .env.example .env        # Fill in real values
pip install -r requirements.txt
python main.py
```

## How It Works

1. **Fetch** — Calls JSearch API for "IT Internship in Malaysia".
2. **Filter** — Scans title + description for target keywords (case-insensitive substring match).
3. **Deduplicate** — Checks `sent_jobs` table for existing `job_id`.
4. **Dispatch** — Sends HTML-formatted message to Telegram (avoids Markdown escaping pitfalls).
5. **Record** — Inserts `job_id` into `sent_jobs` to prevent future duplicates.

The GitHub Actions workflow triggers automatically every 6 hours (`0 */6 * * *` UTC) and can also be triggered manually via `workflow_dispatch`.

## License

MIT
