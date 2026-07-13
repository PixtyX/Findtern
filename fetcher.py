"""
fetcher.py — Multi-source job ingestion.

Sources:
  1. JSearch (RapidAPI) — aggregates LinkedIn, Indeed, etc.
  2. Adzuna (free API) — aggregates JobStreet, Indeed, LinkedIn, etc.

Both sources are normalized to a common dict format before returning.
"""

import os
import requests

JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"
ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/my/search/1"

# ────────────────────────────────────────────────────────────────────
# Common field names used throughout the app:
#   job_id, job_title, employer_name, job_city, job_country,
#   job_description, job_apply_link
# ────────────────────────────────────────────────────────────────────


def fetch_internships(query: str | None = None) -> list:
    """
    Fetch internship listings from all available sources and merge them.

    Args:
        query: Custom search query. Defaults to "internship Malaysia".

    Returns a list of normalized job dicts, deduplicated by title+company.
    """
    all_jobs = []

    # Source 1: JSearch
    jsearch_jobs = _fetch_jsearch(query)
    all_jobs.extend(jsearch_jobs)
    print(f"[fetcher] JSearch returned {len(jsearch_jobs)} jobs.")

    # Source 2: Adzuna
    adzuna_jobs = _fetch_adzuna(query)
    all_jobs.extend(adzuna_jobs)
    print(f"[fetcher] Adzuna returned {len(adzuna_jobs)} jobs.")

    # Deduplicate by title+company (different sources may have the same job)
    seen = set()
    unique = []
    for job in all_jobs:
        key = f"{job.get('job_title', '').lower()}|{job.get('employer_name', '').lower()}"
        if key not in seen:
            seen.add(key)
            unique.append(job)

    print(f"[fetcher] Total unique jobs: {len(unique)}")
    return unique


# ────────────────────────────────────────────────────────────────────
# JSearch (RapidAPI)
# ────────────────────────────────────────────────────────────────────
def _fetch_jsearch(query: str | None) -> list:
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        print("[fetcher] RAPIDAPI_KEY missing — skipping JSearch.")
        return []

    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    # Try the specific query first, fall back to broad if empty
    queries_to_try = [q for q in [query, "internship Malaysia"] if q]
    for q in queries_to_try:
        params = {
            "query": q,
            "page": "1",
            "num_pages": "1",
        }
        print(f"[fetcher] JSearch trying: '{q}'")

        try:
            resp = requests.get(JSEARCH_URL, headers=headers, params=params, timeout=30)
            if resp.status_code == 429:
                print("[fetcher] JSearch 429 rate-limited.")
                return []
            if resp.status_code != 200:
                print(f"[fetcher] JSearch HTTP {resp.status_code}")
                continue  # try next query

            data = resp.json().get("data", [])
            if isinstance(data, list) and len(data) > 0:
                print(f"[fetcher] JSearch got {len(data)} results for '{q}'")
                return data

        except Exception as exc:
            print(f"[fetcher] JSearch error: {exc}")
            continue

    return []


# ────────────────────────────────────────────────────────────────────
# Adzuna (free API — covers JobStreet, Indeed, LinkedIn, etc.)
# ────────────────────────────────────────────────────────────────────
def _fetch_adzuna(query: str | None) -> list:
    app_id = os.environ.get("ADZUNA_APP_ID", "")
    app_key = os.environ.get("ADZUNA_APP_KEY", "")
    if not app_id or not app_key:
        print("[fetcher] ADZUNA_APP_ID/KEY missing — skipping Adzuna.")
        return []

    # Try specific query first, fall back to broad
    queries_to_try = [q for q in [query, "internship"] if q]

    for q in queries_to_try:
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "what": q,
            "where": "Malaysia",
            "results_per_page": 30,
            "max_days_old": 30,
            "content-type": "application/json",
        }
        print(f"[fetcher] Adzuna trying: '{q}'")

        try:
            resp = requests.get(ADZUNA_URL, params=params, timeout=30)
            if resp.status_code == 429:
                print("[fetcher] Adzuna 429 rate-limited.")
                return []
            if resp.status_code != 200:
                print(f"[fetcher] Adzuna HTTP {resp.status_code}")
                continue

            data = resp.json().get("results", [])
            if not isinstance(data, list) or len(data) == 0:
                continue

            print(f"[fetcher] Adzuna got {len(data)} results for '{q}'")

            # Normalize Adzuna format → common format
            normalized = []
            for job in data:
                loc = job.get("location", {})
                area = loc.get("area", [])
                normalized.append({
                    "job_id": f"adzuna_{job.get('id', '')}",
                    "job_title": job.get("title", ""),
                    "employer_name": (job.get("company") or {}).get("display_name", ""),
                    "job_city": area[1] if len(area) > 1 else "",
                    "job_country": area[0] if area else "Malaysia",
                    "job_description": job.get("description", ""),
                    "job_apply_link": job.get("redirect_url", ""),
                })
            return normalized

        except Exception as exc:
            print(f"[fetcher] Adzuna error: {exc}")
            continue

    return []
