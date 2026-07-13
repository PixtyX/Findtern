"""
fetcher.py — Data ingestion from RapidAPI JSearch endpoint.

Includes HTTP status checking, 429 rate-limit detection,
and safe dictionary access via .get() to guard against NoneType errors.
"""

import os
import requests

RAPIDAPI_URL = "https://jsearch.p.rapidapi.com/search"


def fetch_internships() -> list:
    """
    Fetch IT internship listings for Malaysia via RapidAPI JSearch.

    Returns a list of job dicts on success, or an empty list on any failure.
    Handles 429 (rate-limit) explicitly so the caller can exit gracefully.
    """
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        print("[fetcher] RAPIDAPI_KEY is missing from environment.")
        return []

    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    params = {"query": "IT Internship in Malaysia", "page": "1", "num_pages": "1"}

    try:
        response = requests.get(RAPIDAPI_URL, headers=headers, params=params, timeout=30)

        # --- Rate-limit guard ---
        if response.status_code == 429:
            print("[fetcher] 429 Too Many Requests — exiting gracefully.")
            return []

        # --- Generic non-2xx guard ---
        if response.status_code != 200:
            # Never log response body — may contain echoed API key
            print(f"[fetcher] Unexpected HTTP {response.status_code}")
            return []

        payload = response.json()
        data = payload.get("data", [])
        if not isinstance(data, list):
            print("[fetcher] API returned non-list 'data'; coercing to empty list.")
            return []

        return data

    except requests.exceptions.RequestException as exc:
        print(f"[fetcher] Request failed: {exc}")
        return []
    except (ValueError, KeyError) as exc:
        print(f"[fetcher] JSON parse / key error: {exc}")
        return []
