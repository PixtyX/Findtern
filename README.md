# Findtern

A Telegram bot that finds internship listings tailored to you and delivers them straight to your DMs. It searches across LinkedIn, Indeed, Glassdoor, and other major job boards in real time.

## What It Does

- **Instant search** — type `/search` to find matching internships right now
- **Automated delivery** — the bot checks for new listings on your schedule and DMs you when something matches
- **Smart filtering** — matches jobs by department keywords, location, work type, and custom keywords across job titles and descriptions
- **No duplicates** — already-seen listings are never sent again

## How to Start

1. Open Telegram and search for the **Findtern** bot
2. Send `/start`
3. Pick your preferences:
   - **Departments** — choose one or more (IT, Marketing, Finance, Accounting, Design, Engineering, HR, and more)
   - **Locations** — where you want to work (KL, Penang, Johor Bahru, Selangor, and more)
   - **Work Type** — Remote, Hybrid, On-site, or Any
   - **Custom Keywords** — add specific terms like "fintech", "python", or "startup"
   - **Frequency** — how often you want to be notified (every 6 hours, daily, every 2 days, or pause)
4. Tap **Done**

That's it. You'll start receiving matching internships automatically.

## Commands

| Command     | What it does                              |
| ----------- | ----------------------------------------- |
| `/start`    | Set up or reset your preferences          |
| `/settings` | Change what you're looking for            |
| `/search`   | Search for matching internships right now |
| `/cancel`   | Cancel keyword entry                      |
| `/help`     | Show available commands                   |

## How It Works

### Instant Search

Type `/search` or tap the **🔍 Search Now** button in settings. The bot:

1. Builds targeted search queries from your preferences (department keywords + location)
2. Fetches results from JSearch (aggregates LinkedIn, Indeed, Glassdoor, ZipRecruiter, and more)
3. Filters results using smart keyword matching:
   - **Title match** — keyword appears in the job title (strongest signal)
   - **Multi-word keyword in description** — e.g. "software engineer" in the job description
   - **Multiple single-word keywords in description** — e.g. both "software" and "sql" appear (prevents false matches like "accounting software")
4. Deduplicates against jobs you've already seen
5. Delivers the first 5 matching jobs with **Show More** / **Show All** buttons

### Automated Delivery

Based on your chosen frequency (every 6 hours, 12 hours, daily, or every 2 days), the bot automatically checks for new listings and sends you matches. You can pause this without losing your settings by setting Frequency to **Paused**.

### Filtering Rules

- At least one department keyword must appear in the **job title**, OR a multi-word keyword in the description, OR 2+ single-word keywords in the description
- Location must match your selected areas (unless too few results, then location filter is relaxed)
- Work type must match your remote preference (if set)

## Tips

- Use `/search` to test your preferences — see what matches before waiting for automated delivery
- The more departments and locations you select, the more results you'll get
- Custom keywords work across all departments — great for niche skills like "fintech" or "python"
- If you're getting too many results, narrow your locations or add more specific custom keywords
- If you're getting none, try adding more locations or switching Work Type to "Any"
- You can pause alerts without losing your settings — just set Frequency to "Paused"

## Tech Stack

- **Bot** — Python + Flask webhook server (real-time responses)
- **Database** — PostgreSQL (user preferences, job deduplication, delivery digests)
- **Job Source** — JSearch API via RapidAPI (aggregates LinkedIn, Indeed, Glassdoor, and more)
- **Hosting** — Render (webhook server), GitHub Actions (scheduled job fetching + delivery)
