"""
fetcher.py — Job ingestion from JSearch (RapidAPI).

JSearch aggregates from LinkedIn, Indeed, Glassdoor, ZipRecruiter, and others
via Google for Jobs. Works globally including Malaysia.

Requires: RAPIDAPI_KEY env var + active subscription to JSearch on RapidAPI.
Subscribe free at: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
"""

import os
import random
import requests

# Try both JSearch endpoints — v5 (search-v2) and legacy (search)
JSEARCH_URLS = [
    "https://jsearch.p.rapidapi.com/search-v2",
    "https://jsearch.p.rapidapi.com/search",
]


def fetch_internships(query: str | None = None) -> list:
    """
    Fetch internship listings. Tries specific query first, falls back to broad.
    Returns list of job dicts.
    """
    jobs, error = _fetch_jsearch(query)
    if error:
        print(f"[fetcher] {error}")
    print(f"[fetcher] Total jobs: {len(jobs)}")
    return jobs


def fetch_internships_with_errors(query: str | None = None) -> tuple:
    """Same as fetch_internships but also returns error string. Returns (jobs, error)."""
    jobs, error = _fetch_jsearch(query)
    print(f"[fetcher] Total jobs: {len(jobs)}" + (f" ({error})" if error else ""))
    return jobs, error


def fetch_multi_query(queries: list[str]) -> tuple:
    """
    Run multiple queries, combine and deduplicate results.
    Returns (jobs_list, error_string).
    """
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        return [], "RAPIDAPI_KEY not set"

    seen_ids = set()
    all_jobs = []
    last_error = ""

    for base_url in JSEARCH_URLS:
        host = base_url.split("//")[1].split("/")[0]
        headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": host,
        }

        for q in queries:
            params = {"query": q, "page": "1", "num_pages": "2", "country": "my", "date_posted": "all"}
            print(f"[fetcher] Multi-query ({host}): '{q}'")

            try:
                resp = requests.get(base_url, headers=headers, params=params, timeout=30)
                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    break  # try next endpoint

                payload = resp.json()
                data = payload.get("data", [])
                if isinstance(data, dict):
                    data = data.get("jobs", data.get("results", []))

                if isinstance(data, list):
                    for job in data:
                        jid = job.get("job_id", "")
                        if jid and jid not in seen_ids:
                            seen_ids.add(jid)
                            all_jobs.append(job)
                    print(f"[fetcher]   '{q}' → {len(data)} results")

            except Exception as exc:
                last_error = f"Exception: {exc}"
                continue

        if all_jobs:
            break  # got results from this endpoint, skip others

    print(f"[fetcher] Multi-query total: {len(all_jobs)} unique jobs")
    return all_jobs, last_error if not all_jobs else ""


def _fetch_jsearch(query: str | None) -> tuple:
    """Returns (jobs_list, error_string). error_string is '' on success."""
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        return [], "RAPIDAPI_KEY not set"

    queries_to_try = [q for q in [query, "internship Malaysia"] if q]
    last_error = ""

    # Try each JSearch endpoint (regular + mega)
    for base_url in JSEARCH_URLS:
        host = base_url.split("//")[1].split("/")[0]
        headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": host,
        }

        for q in queries_to_try:
            params = {"query": q, "page": "1", "num_pages": "1", "country": "my", "date_posted": "all"}
            print(f"[fetcher] JSearch ({host}) trying: '{q}'")

            try:
                resp = requests.get(base_url, headers=headers, params=params, timeout=30)

                if resp.status_code == 429:
                    return [], "JSearch 429 rate-limited"

                if resp.status_code != 200:
                    body = resp.text[:300]
                    last_error = f"JSearch ({host}) HTTP {resp.status_code}: {body}"
                    print(f"[fetcher] {last_error}")
                    break  # try next endpoint, don't try more queries on this one

                payload = resp.json()
                data = payload.get("data", [])

                # JSearch changed format: data can be {"jobs": [...]} instead of [...]
                if isinstance(data, dict):
                    data = data.get("jobs", data.get("results", []))

                if isinstance(data, list) and len(data) > 0:
                    print(f"[fetcher] JSearch ({host}) got {len(data)} results for '{q}'")
                    return data, ""

                status_msg = payload.get("status", payload.get("message", "unknown"))
                last_error = f"JSearch ({host}): 0 results (status: {status_msg})"
                continue

            except Exception as exc:
                last_error = f"JSearch ({host}) exception: {exc}"
                print(f"[fetcher] {last_error}")
                continue

    return [], last_error or "JSearch: all endpoints failed"


# ────────────────────────────────────────────────────────────────────
# Cron-round fetcher — diverse queries + page rotation
# ────────────────────────────────────────────────────────────────────

# Department query templates used by the cron pipeline.
# Rotating through these ensures we don't always hit the same API results.
_CRON_QUERIES = [
    "internship Malaysia",
    "software engineer intern Malaysia",
    "marketing intern Malaysia",
    "accounting intern Malaysia",
    "finance intern Malaysia",
    "engineering intern Malaysia",
    "design intern Malaysia",
    "human resources intern Malaysia",
    "business intern Malaysia",
    "data analyst intern Malaysia",
    "internship Kuala Lumpur",
    "internship Selangor",
    "internship Penang",
    "internship Johor Bahru",
    "remote internship Malaysia",
    "IT intern Malaysia",
    "graphic design intern Malaysia",
    "sales intern Malaysia",
    "legal intern Malaysia",
    "customer service intern Malaysia",
]


def fetch_cron_round() -> list:
    """
    Fetch internships for the scheduled cron run.

    Unlike fetch_internships() which always does the same single query,
    this function:
      1. Picks a rotating subset of diverse department/location queries
      2. Randomises the page number (1-3) so we don't always get the same listings
      3. Combines and deduplicates results

    Returns list of job dicts (may be empty on failure).
    """
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        print("[fetcher] RAPIDAPI_KEY not set")
        return []

    # Pick 4-5 random queries from the pool (different set each run)
    num_queries = min(5, len(_CRON_QUERIES))
    queries = random.sample(_CRON_QUERIES, num_queries)

    seen_ids: set[str] = set()
    all_jobs: list = []
    last_error = ""

    for base_url in JSEARCH_URLS:
        host = base_url.split("//")[1].split("/")[0]
        headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": host,
        }

        for q in queries:
            # Randomise page so we don't always get page 1
            page = str(random.randint(1, 3))
            params = {
                "query": q,
                "page": page,
                "num_pages": "1",
                "country": "my",
                "date_posted": "all",
            }
            print(f"[fetcher] Cron ({host}) q='{q}' page={page}")

            try:
                resp = requests.get(base_url, headers=headers, params=params, timeout=30)

                if resp.status_code == 429:
                    last_error = "JSearch 429 rate-limited"
                    print(f"[fetcher] {last_error}")
                    break  # stop hitting this endpoint

                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    print(f"[fetcher] {last_error}")
                    break  # try next endpoint

                payload = resp.json()
                data = payload.get("data", [])
                if isinstance(data, dict):
                    data = data.get("jobs", data.get("results", []))

                if isinstance(data, list):
                    for job in data:
                        jid = job.get("job_id", "")
                        if jid and jid not in seen_ids:
                            seen_ids.add(jid)
                            all_jobs.append(job)
                    print(f"[fetcher]   '{q}' p{page} → {len(data)} results")

            except Exception as exc:
                last_error = f"Exception: {exc}"
                print(f"[fetcher] {last_error}")
                continue

        if all_jobs:
            break  # got results from this endpoint

    print(f"[fetcher] Cron round: {len(all_jobs)} unique jobs from {len(queries)} queries")
    if not all_jobs and last_error:
        print(f"[fetcher] Last error: {last_error}")
    return all_jobs
