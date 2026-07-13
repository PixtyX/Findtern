"""
fetcher.py — Job ingestion from JSearch (RapidAPI).

JSearch aggregates from LinkedIn, Indeed, Glassdoor, ZipRecruiter, and others
via Google for Jobs. Works globally including Malaysia.

Requires: RAPIDAPI_KEY env var + active subscription to JSearch on RapidAPI.
Subscribe free at: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
"""

import os
import requests

# Try both JSearch endpoints — regular and Mega
JSEARCH_URLS = [
    "https://jsearch.p.rapidapi.com/search",
    "https://jsearch-mega.p.rapidapi.com/search",
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
            params = {"query": q, "page": "1", "num_pages": "1"}
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
