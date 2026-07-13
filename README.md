# Findtern

A Telegram bot that finds internship listings tailored to you and delivers them straight to your DMs.

## What It Does

Findtern searches for new internship postings every 6 hours and sends you only the ones that match what you're looking for — your preferred field, location, and work type. No spam, no irrelevant listings.

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

## How It Works After Setup

- Every 6hrs/12hrs/day(depending on your selection), the bot checks for new listings
- If something matches your preferences, you get a DM with up to 5 listings
- Tap **Show More** to see the next batch, or **Show All** to see everything at once. Due to server limitations, a maximum of 50 listings can be shown at a time.
- Already-seen listings are never sent again
- You can change your preferences anytime with `/settings`

## Commands

| Command     | What it does                     |
| ----------- | -------------------------------- |
| `/start`    | Set up or reset your preferences |
| `/settings` | Change what you're looking for   |
| `/help`     | Show available commands          |

## Tips

- The more departments and locations you select, the more results you'll get
- Custom keywords work across all departments — great for niche skills
- If you're getting too many results, remove some departments or narrow your locations
- If you're getting none, try adding more locations or switching Work Type to "Any"
- You can pause alerts without losing your settings — just set Frequency to "Paused"
