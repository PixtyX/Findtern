# Findtern — Personalized Internship Aggregator & Telegram Bot

A serverless pipeline that fetches internship postings from RapidAPI JSearch, deduplicates them against Supabase PostgreSQL, and delivers **personalized** alerts to each user via Telegram based on their preferred departments, locations, and custom keywords.

## Architecture

```mermaid
flowchart LR
    A[JSearch API] -->|fetch| B[Dedup Layer]
    B -->|new jobs| C[Preference Filter]
    C -->|per-user DM| D[User Digests]
    D -->|"Show More"| E[Callback Router]
    E -->|next batch| D
    F["/start"] -->|settings UI| G[User Preferences]
    G -->|filter| C
```

## Features

### Personalized Job Feed

Users DM the bot with `/start` and configure:

- **12 Departments** — IT, Accounting, Marketing, Finance, Engineering, Design, HR, Business, Sales, Legal, Healthcare, Education
- **12 Locations** — KL, JB, Penang, Selangor, Melaka, Ipoh, Kuching, KK, and more (with nearby-area matching)
- **Work Type** — Remote, Hybrid, On-site, or Any
- **Custom Keywords** — Add your own (e.g. "fintech", "startup", "python")
- **Frequency** — Every 6h, 12h, daily, or every 2 days

### UX Flow

```
User sends /start to the bot:
  [Bot] Welcome to Findtern!
        Set up your preferences below...

        Findtern — Your Preferences
        ━━━━━━━━━━━━━━━━━━━━
        Departments: None selected
        Locations: None selected
        Work Type: Any
        Frequency: Every 6 hours

        [Departments] [Locations]
        [Work Type]  [Frequency]
        [Custom Keywords]
        [Done]

User selects "Departments":
  [Bot] Select Departments
        Toggle on/off by tapping:
        [✅ IT / Tech]    [⬜ Accounting]
        [⬜ Marketing]    [⬜ Finance]
        ...

Next cron run delivers personalized matches:
  [Bot] Findtern — 8 New Internships For You!
        Software Engineer Intern
        Company: TechCorp Malaysia
        Location: Kuala Lumpur
        Apply Here
        ━━━━━━━━━━━━━━━━━━━━
        3 more available. Tap below:
        [Show More] [Show All]
        [Settings]
```

## Files

| File                            | Purpose                                                        |
| ------------------------------- | -------------------------------------------------------------- |
| `database.py`                   | Supabase PostgreSQL layer: dedup, batches, user prefs, digests |
| `schema.py`                     | DDL definitions for all 5 tables                               |
| `fetcher.py`                    | RapidAPI JSearch HTTP client with rate-limit handling          |
| `telegram.py`                   | Telegram Bot API: send, DM, callbacks, rate limiting           |
| `preferences.py`                | Department/location definitions, settings UI, job matching     |
| `main.py`                       | Pipeline orchestrator: fetch → dedup → per-user DM delivery    |
| `.github/workflows/run_bot.yml` | GitHub Actions cron (every 6 hours)                            |

## Setup

You need **3 API keys**. Below is where to get them and where to paste them.

### Step 1: Get Your API Keys

**Supabase (database):**

1. Go to [supabase.com](https://supabase.com) → create a free project
2. Go to **SQL Editor** → paste the full schema below → click **Run**
3. Go to **Settings → Database** → copy the **direct** connection string (not pooled)
4. It looks like: `postgresql://postgres.xxxxx:password@aws-0-...supabase.com:5432/postgres`

**Telegram Bot:**

1. Open Telegram → message [@BotFather](https://t.me/BotFather) → send `/newbot`
2. Follow the prompts → copy the **token** it gives you

**RapidAPI:**

1. Go to [JSearch on RapidAPI](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) → click **Subscribe** (free tier)
2. Copy your API key from the dashboard

### Step 2: Where to Paste Your Keys

You have **two options** depending on how you want to run the bot:

**Option A — Production (recommended): GitHub Actions**
The bot runs automatically on GitHub's servers every 6 hours. You paste your keys into GitHub Secrets:

1. Push this repo to GitHub
2. Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
3. Add these 3 secrets:

| Secret Name      | What to paste                       |
| ---------------- | ----------------------------------- |
| `TELEGRAM_TOKEN` | The token from BotFather            |
| `RAPIDAPI_KEY`   | The API key from RapidAPI           |
| `DATABASE_URL`   | The connection string from Supabase |

4. Go to **Actions** tab → click **"Run Internship Bot"** → **"Run workflow"** to test it

That's it. The bot now runs every 6 hours automatically.

**Option B — Local testing: .env file**
If you want to test on your own machine first:

1. In this project folder, copy the example env file:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` in a text editor and paste your values:
   ```
   TELEGRAM_TOKEN=paste_your_bot_token_here
   RAPIDAPI_KEY=paste_your_rapidapi_key_here
   DATABASE_URL=paste_your_supabase_url_here
   ```
3. Install dependencies and run:
   ```bash
   pip install -r requirements.txt
   python main.py
   ```

### Database Schema

Run this in Supabase SQL Editor (Settings → SQL Editor):

```sql
CREATE TABLE IF NOT EXISTS sent_jobs (
    job_id     TEXT PRIMARY KEY,
    title      TEXT,
    company    TEXT,
    link       TEXT,
    date_found TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_batches (
    batch_id       TEXT PRIMARY KEY,
    total_new_jobs INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'active',
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pending_callbacks (
    id             SERIAL PRIMARY KEY,
    batch_id       TEXT NOT NULL REFERENCES job_batches(batch_id) ON DELETE CASCADE,
    remaining_jobs TEXT NOT NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_preferences (
    chat_id          TEXT PRIMARY KEY,
    departments      TEXT NOT NULL DEFAULT '[]',
    locations        TEXT NOT NULL DEFAULT '[]',
    custom_keywords  TEXT NOT NULL DEFAULT '[]',
    remote_pref      TEXT NOT NULL DEFAULT 'any',
    notify_frequency TEXT NOT NULL DEFAULT '6h',
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_digests (
    id              SERIAL PRIMARY KEY,
    chat_id         TEXT NOT NULL,
    remaining_jobs  TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## How It Works

1. **User setup** — User DMs the bot with `/start`, configures departments, locations, work type, and keywords.
2. **Fetch** — Every 6 hours, the cron job calls JSearch API for internship listings.
3. **Deduplicate** — Checks `sent_jobs` table for existing `job_id`.
4. **Filter** — For each user with preferences, filters jobs by their departments, locations, work type, and custom keywords.
5. **Deliver** — DMs each matched user the first 5 jobs with "Show More" / "Show All" buttons.
6. **Callbacks** — On next cron run, processes button taps and delivers additional batches.
7. **Cleanup** — Stale digests older than 48 hours are automatically purged.

Users who haven't set preferences yet are silently skipped — no spam, no unwanted messages.

## Bot Commands

| Command     | Description                       |
| ----------- | --------------------------------- |
| `/start`    | Open the preferences setup wizard |
| `/settings` | Change your preferences           |
| `/cancel`   | Cancel keyword entry mode         |
| `/help`     | Show available commands           |

## Rate Limiting

- **Telegram**: 1-second delay between message sends
- **RapidAPI**: Graceful handling of 429 (Too Many Requests)
- **"Show All"**: Capped at 50 jobs per interaction to prevent spam
- **Frequency control**: Users can set digest frequency (6h, 12h, daily, 2 days)

## License

MIT
