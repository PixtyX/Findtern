"""
preferences.py — User preference management and settings UI.

Provides:
  - Department & location definitions with keyword mappings
  - Settings menu building (inline keyboards)
  - Callback handlers for settings interactions
  - Per-user job matching logic
"""

import os
import re

from database import (
    get_user_preference,
    upsert_user_preference,
)
from telegram import (
    escape_html,
    send_dm,
    answer_callback,
)

# ────────────────────────────────────────────────────────────────────
# Keyword entry state tracking
# Maps user_id (str) → True when awaiting keyword input
# Protected by a lock for thread-safe webhook access
# ────────────────────────────────────────────────────────────────────
import threading

_pending_keyword_lock = threading.Lock()
_pending_keyword_user: dict = {}

# ────────────────────────────────────────────────────────────────────
# Department definitions
# Each has a label, emoji, and list of matching keywords
# ────────────────────────────────────────────────────────────────────
DEPARTMENTS = {
    "IT": {
        "label": "IT / Tech",
        "keywords": [
            "it intern", "software engineer", "web developer", "php",
            "sql", "iot", "cybersecurity", "digital forensics",
            "information technology", "computer science", "developer",
            "tech intern", "software", "frontend", "backend", "full stack",
            "devops", "cloud", "data engineer",
        ],
    },
    "ACC": {
        "label": "Accounting",
        "keywords": [
            "accounting", "accountant", "audit", "bookkeeper",
            "tax", "financial reporting", "accounts payable",
            "accounts receivable", "payroll", "cpa", "acca",
            "management accounting", "cost accounting",
        ],
    },
    "MKT": {
        "label": "Marketing",
        "keywords": [
            "marketing", "digital marketing", "social media",
            "content creator", "seo", "sem", "brand", "advertising",
            "copywriter", "market research", "google ads", "facebook ads",
            "influencer", "communications", "public relations",
        ],
    },
    "FIN": {
        "label": "Finance",
        "keywords": [
            "finance", "financial analyst", "investment", "banking",
            "fintech", "wealth management", "risk analyst",
            "credit analyst", "trading", "portfolio", "insurance",
        ],
    },
    "ENG": {
        "label": "Engineering",
        "keywords": [
            "engineer", "mechanical", "electrical", "civil",
            "chemical engineer", "manufacturing", "quality engineer",
            "process engineer", "cad", "autocad", "solidworks",
        ],
    },
    "DSGN": {
        "label": "Design / Creative",
        "keywords": [
            "designer", "graphic design", "ui", "ux", "figma",
            "photoshop", "illustrator", "creative", "multimedia",
            "video editor", "animation", "3d", "interior design",
        ],
    },
    "HR": {
        "label": "Human Resources",
        "keywords": [
            "human resource", "hr intern", "recruitment", "talent",
            "people operations", "training", "organizational development",
            "compensation", "benefits", "onboarding",
        ],
    },
    "BIZ": {
        "label": "Business / Admin",
        "keywords": [
            "business", "admin", "operations", "project management",
            "consulting", "strategy", "supply chain", "logistics",
            "procurement", "business development", "intern",
        ],
    },
    "SALES": {
        "label": "Sales",
        "keywords": [
            "sales", "account executive", "business development",
            "client relations", "customer success", "b2b", "b2c",
            "retail", "merchandising",
        ],
    },
    "LEGAL": {
        "label": "Legal",
        "keywords": [
            "legal", "law", "compliance", "paralegal",
            "corporate law", "contract", "regulatory",
        ],
    },
    "MED": {
        "label": "Healthcare / Medical",
        "keywords": [
            "medical", "healthcare", "nurse", "pharmacist",
            "clinical", "hospital", "biomedical", "pharmacy",
            "dentist", "physiotherapy",
        ],
    },
    "EDU": {
        "label": "Education",
        "keywords": [
            "education", "teaching", "tutor", "trainer",
            "curriculum", "academic", "lecturer", "school",
        ],
    },
}

# ────────────────────────────────────────────────────────────────────
# Location definitions — city → nearby areas for fuzzy matching
# ────────────────────────────────────────────────────────────────────
LOCATIONS = {
    "KL": {
        "label": "Kuala Lumpur",
        "areas": ["kuala lumpur", "kl", "bangsar", "mont kiara",
                  "sri hartamas", "sentul", "cheras", "setapak"],
    },
    "JB": {
        "label": "Johor Bahru",
        "areas": ["johor bahru", "jb", "iskandar", "nusajaya",
                  "tebrau", "skudai", "kulai"],
    },
    "PEN": {
        "label": "Penang",
        "areas": ["penang", "george town", "bayan lepas",
                  "butterworth", "seberang perai", "pulau pinang"],
    },
    "SEL": {
        "label": "Selangor",
        "areas": ["selangor", "shah alam", "petaling jaya", "pj",
                  "subang", "klang", "kajang", "cyberjaya",
                  "puchong", "seri kembangan", "sepang"],
    },
    "MLK": {
        "label": "Melaka",
        "areas": ["melaka", "malacca", "ayer keroh", "klebang"],
    },
    "IPH": {
        "label": "Ipoh",
        "areas": ["ipoh", "perak", "taiping", "batu gajah"],
    },
    "KCH": {
        "label": "Kuching",
        "areas": ["kuching", "sarawak", "samarahan", "bintulu"],
    },
    "SDK": {
        "label": "Kota Kinabalu",
        "areas": ["kota kinabalu", "sabah", "kk", "penampang"],
    },
    "NSW": {
        "label": "Negeri Sembilan",
        "areas": ["negeri sembilan", "seremban", "nilai", "port dickson"],
    },
    "KTN": {
        "label": "Kelantan",
        "areas": ["kelantan", "kota bharu", "kuala terengganu", "terengganu"],
    },
    "SGR": {
        "label": "Singapore Border",
        "areas": ["woodlands", "tuas", "singapore border", "sg border"],
    },
    "RMTE": {
        "label": "Remote / Work from Home",
        "areas": ["remote", "work from home", "wfh", "virtual", "online"],
    },
}

# ────────────────────────────────────────────────────────────────────
# Remote work preference options
# ────────────────────────────────────────────────────────────────────
REMOTE_OPTIONS = {
    "any":    {"label": "Any"},
    "remote": {"label": "Remote"},
    "hybrid": {"label": "Hybrid"},
    "onsite": {"label": "On-site"},
}

# ────────────────────────────────────────────────────────────────────
# Notification frequency options
# ────────────────────────────────────────────────────────────────────
FREQ_OPTIONS = {
    "6h":  {"label": "Every 6 hours"},
    "12h": {"label": "Every 12 hours"},
    "24h": {"label": "Daily"},
    "48h": {"label": "Every 2 days"},
    "off": {"label": "Paused"},
}


# ════════════════════════════════════════════════════════════════════
# Settings menu builder
# ════════════════════════════════════════════════════════════════════
def build_settings_menu(user_id: str) -> tuple:
    """
    Build the main settings page showing current preferences.
    Returns (message_text, reply_markup).
    """
    prefs = get_user_preference(user_id)
    depts = prefs.get("departments", []) if prefs else []
    locs = prefs.get("locations", []) if prefs else []
    remote = prefs.get("remote_pref", "any") if prefs else "any"
    freq = prefs.get("notify_frequency", "6h") if prefs else "6h"
    custom_kw = prefs.get("custom_keywords", []) if prefs else []

    # ── Format current selections ──
    if depts:
        dept_display = ", ".join(
            DEPARTMENTS[d]['label']
            for d in depts if d in DEPARTMENTS
        )
    else:
        dept_display = "<i>None selected</i>"

    if locs:
        loc_display = ", ".join(
            LOCATIONS[l]['label']
            for l in locs if l in LOCATIONS
        )
    else:
        loc_display = "<i>None selected</i>"

    remote_info = REMOTE_OPTIONS.get(remote, REMOTE_OPTIONS["any"])
    freq_info = FREQ_OPTIONS.get(freq, FREQ_OPTIONS["6h"])

    if custom_kw:
        kw_display = ", ".join(f"<code>{escape_html(k)}</code>" for k in custom_kw)
    else:
        kw_display = "<i>None</i>"

    text = (
        "<b>Findtern — Your Preferences</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Departments:</b>\n{dept_display}\n\n"
        f"<b>Locations:</b>\n{loc_display}\n\n"
        f"<b>Work Type:</b> {remote_info['label']}\n"
        f"<b>Frequency:</b> {freq_info['label']}\n"
        f"<b>Custom Keywords:</b> {kw_display}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Tap a button below to change:"
    )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🔍 Search Now", "callback_data": "settings:search"},
            ],
            [
                {"text": "Departments", "callback_data": "settings:dept"},
                {"text": "Locations", "callback_data": "settings:loc"},
            ],
            [
                {"text": "Work Type", "callback_data": "settings:remote"},
                {"text": "Frequency", "callback_data": "settings:freq"},
            ],
            [
                {"text": "Custom Keywords", "callback_data": "settings:kw"},
            ],
            [
                {"text": "Done", "callback_data": "settings:done"},
            ],
        ]
    }

    return text, keyboard


def build_dept_keyboard(user_id: str) -> tuple:
    """Build department selection keyboard with checkmarks."""
    prefs = get_user_preference(user_id)
    selected = set(prefs.get("departments", [])) if prefs else set()

    lines = [
        "<b>Select Departments</b>\n"
        "Toggle on/off by tapping:\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]
    keyboard_rows = []
    row = []

    for code, info in DEPARTMENTS.items():
        check = "✅" if code in selected else "⬜"
        row.append({
            "text": f"{check} {info['label']}",
            "callback_data": f"dept:{code}",
        })
        if len(row) == 2:
            keyboard_rows.append(row)
            row = []

    if row:
        keyboard_rows.append(row)

    keyboard_rows.append([{"text": "Back", "callback_data": "settings:main"}])
    return "\n".join(lines), {"inline_keyboard": keyboard_rows}


def build_loc_keyboard(user_id: str) -> tuple:
    """Build location selection keyboard with checkmarks."""
    prefs = get_user_preference(user_id)
    selected = set(prefs.get("locations", [])) if prefs else set()

    lines = [
        "<b>Select Locations</b>\n"
        "Toggle on/off by tapping:\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]
    keyboard_rows = []
    row = []

    for code, info in LOCATIONS.items():
        check = "✅" if code in selected else "⬜"
        row.append({
            "text": f"{check} {info['label']}",
            "callback_data": f"loc:{code}",
        })
        if len(row) == 2:
            keyboard_rows.append(row)
            row = []

    if row:
        keyboard_rows.append(row)

    keyboard_rows.append([{"text": "Back", "callback_data": "settings:main"}])
    return "\n".join(lines), {"inline_keyboard": keyboard_rows}


def build_remote_keyboard(user_id: str) -> tuple:
    """Build remote work preference keyboard."""
    prefs = get_user_preference(user_id)
    current = prefs.get("remote_pref", "any") if prefs else "any"

    lines = [
        "<b>Work Type Preference</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]
    keyboard_rows = []
    for code, info in REMOTE_OPTIONS.items():
        check = "✅" if code == current else "⬜"
        keyboard_rows.append([{
            "text": f"{check} {info['label']}",
            "callback_data": f"remote:{code}",
        }])

    keyboard_rows.append([{"text": "Back", "callback_data": "settings:main"}])
    return "\n".join(lines), {"inline_keyboard": keyboard_rows}


def build_freq_keyboard(user_id: str) -> tuple:
    """Build notification frequency keyboard."""
    prefs = get_user_preference(user_id)
    current = prefs.get("notify_frequency", "6h") if prefs else "6h"

    lines = [
        "<b>How often should we check?</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]
    keyboard_rows = []
    for code, info in FREQ_OPTIONS.items():
        check = "✅" if code == current else "⬜"
        keyboard_rows.append([{
            "text": f"{check} {info['label']}",
            "callback_data": f"freq:{code}",
        }])

    keyboard_rows.append([{"text": "Back", "callback_data": "settings:main"}])
    return "\n".join(lines), {"inline_keyboard": keyboard_rows}


def build_kw_keyboard(user_id: str) -> tuple:
    """Build custom keywords management keyboard."""
    prefs = get_user_preference(user_id)
    keywords = prefs.get("custom_keywords", []) if prefs else []

    lines = [
        "<b>Custom Keywords</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]
    if keywords:
        lines.append("Your keywords:")
        for i, kw in enumerate(keywords):
            lines.append(f"  {i+1}. <code>{escape_html(kw)}</code>")
    else:
        lines.append("<i>No custom keywords set.</i>")

    lines.append("\nAdd your own keywords to match ANY department.")
    lines.append("e.g. \"fintech\", \"startup\", \"remote\"")

    keyboard_rows = [
        [{"text": "Add Keyword", "callback_data": "kw:add"}],
    ]

    if keywords:
        for i, kw in enumerate(keywords):
            keyboard_rows.append([{
                "text": f'Remove "{kw}"',
                "callback_data": f"kw:rm:{i}",
            }])
        keyboard_rows.append([{
            "text": "Clear All",
            "callback_data": "kw:clear",
        }])

    keyboard_rows.append([{"text": "Back", "callback_data": "settings:main"}])
    return "\n".join(lines), {"inline_keyboard": keyboard_rows}


# ════════════════════════════════════════════════════════════════════
# Settings callback handler
# ════════════════════════════════════════════════════════════════════
def handle_settings_callback(cq_id: str, user_id: str, data: str) -> bool:
    """
    Process a settings-related callback query.
    Returns True if handled, False if not a settings action.
    """
    parts = data.split(":", 1)
    if len(parts) != 2:
        return False
    prefix, value = parts

    # ── Main menu navigation ──
    if prefix == "settings":
        if value == "done":
            answer_callback(cq_id, "✅ Preferences saved!")
            send_dm(user_id, "✅ <b>Findtern — Preferences saved!</b>\nYour personalized internship feed is now active.")
            return True
        if value == "search":
            answer_callback(cq_id, "🔍 Searching…")
            # Import at call time to avoid circular import
            import main as _main
            _main._handle_search_now(user_id)
            return True
        text, kb = {"dept": build_dept_keyboard, "loc": build_loc_keyboard,
                     "remote": build_remote_keyboard, "freq": build_freq_keyboard,
                     "kw": build_kw_keyboard, "main": build_settings_menu
                    }.get(value, build_settings_menu)(user_id)
        send_dm(user_id, text, reply_markup=kb)
        answer_callback(cq_id)
        return True

    # ── Department toggle ──
    if prefix == "dept":
        if value not in DEPARTMENTS:
            answer_callback(cq_id, "Unknown department")
            return True
        prefs = get_user_preference(user_id)
        depts = list(prefs.get("departments", [])) if prefs else []
        if value in depts:
            depts.remove(value)
            answer_callback(cq_id, f"Removed {DEPARTMENTS[value]['label']}")
        else:
            depts.append(value)
            answer_callback(cq_id, f"Added {DEPARTMENTS[value]['label']}")
        upsert_user_preference(user_id, departments=depts)
        text, kb = build_dept_keyboard(user_id)
        send_dm(user_id, text, reply_markup=kb)
        return True

    # ── Location toggle ──
    if prefix == "loc":
        if value not in LOCATIONS:
            answer_callback(cq_id, "Unknown location")
            return True
        prefs = get_user_preference(user_id)
        locs = list(prefs.get("locations", [])) if prefs else []
        if value in locs:
            locs.remove(value)
            answer_callback(cq_id, f"Removed {LOCATIONS[value]['label']}")
        else:
            locs.append(value)
            answer_callback(cq_id, f"Added {LOCATIONS[value]['label']}")
        upsert_user_preference(user_id, locations=locs)
        text, kb = build_loc_keyboard(user_id)
        send_dm(user_id, text, reply_markup=kb)
        return True

    # ── Remote work preference ──
    if prefix == "remote":
        if value not in REMOTE_OPTIONS:
            answer_callback(cq_id, "Unknown option")
            return True
        upsert_user_preference(user_id, remote_pref=value)
        answer_callback(cq_id, f"Set to {REMOTE_OPTIONS[value]['label']}")
        text, kb = build_remote_keyboard(user_id)
        send_dm(user_id, text, reply_markup=kb)
        return True

    # ── Notification frequency ──
    if prefix == "freq":
        if value not in FREQ_OPTIONS:
            answer_callback(cq_id, "Unknown option")
            return True
        upsert_user_preference(user_id, notify_frequency=value)
        answer_callback(cq_id, f"Set to {FREQ_OPTIONS[value]['label']}")
        text, kb = build_freq_keyboard(user_id)
        send_dm(user_id, text, reply_markup=kb)
        return True

    # ── Custom keywords ──
    if prefix == "kw":
        prefs = get_user_preference(user_id)
        keywords = list(prefs.get("custom_keywords", [])) if prefs else []

        if value == "add":
            with _pending_keyword_lock:
                _pending_keyword_user[user_id] = True
            send_dm(user_id,
                "<b>Add a Custom Keyword</b>\n\n"
                "Type the keyword you want to match.\n"
                "It will be matched against job titles and descriptions.\n\n"
                "Examples: <code>fintech</code>, <code>startup</code>, <code>python</code>\n\n"
                "Send /cancel to go back.",
            )
            answer_callback(cq_id, "Type your keyword…")
            return True

        if value == "clear":
            upsert_user_preference(user_id, custom_keywords=[])
            answer_callback(cq_id, "All keywords cleared")
            text, kb = build_kw_keyboard(user_id)
            send_dm(user_id, text, reply_markup=kb)
            return True

        if value.startswith("rm:"):
            try:
                idx = int(value[3:])
                removed = keywords.pop(idx)
                upsert_user_preference(user_id, custom_keywords=keywords)
                answer_callback(cq_id, f"Removed \"{removed}\"")
            except (ValueError, IndexError):
                answer_callback(cq_id, "Invalid index")
            text, kb = build_kw_keyboard(user_id)
            send_dm(user_id, text, reply_markup=kb)
            return True

    return False


def handle_keyword_input(user_id: str, text: str) -> bool:
    """
    Check if user is in keyword-entry mode and process their input.
    Returns True if the message was consumed as keyword input.
    """
    with _pending_keyword_lock:
        if user_id not in _pending_keyword_user:
            return False

    keyword = text.strip().lower()

    if keyword.startswith("/cancel"):
        with _pending_keyword_lock:
            _pending_keyword_user.pop(user_id, None)
        text_out, kb = build_settings_menu(user_id)
        send_dm(user_id, text_out, reply_markup=kb)
        return True

    if not keyword or len(keyword) > 50:
        send_dm(user_id, "⚠️ Keyword must be 1-50 characters. Try again or /cancel")
        return True

    prefs = get_user_preference(user_id)
    keywords = list(prefs.get("custom_keywords", [])) if prefs else []

    if keyword in keywords:
        send_dm(user_id, f"⚠️ <code>{escape_html(keyword)}</code> is already in your list.")
        return True

    keywords.append(keyword)
    upsert_user_preference(user_id, custom_keywords=keywords)
    with _pending_keyword_lock:
        _pending_keyword_user.pop(user_id, None)

    send_dm(user_id,
        f"✅ Added <code>{escape_html(keyword)}</code>!\n"
        "Your feed will now include jobs matching this keyword."
    )
    text_out, kb = build_kw_keyboard(user_id)
    send_dm(user_id, text_out, reply_markup=kb)
    return True


# ════════════════════════════════════════════════════════════════════
# Job matching
# ════════════════════════════════════════════════════════════════════
def matches_preferences(job: dict, prefs: dict, skip_location: bool = False) -> bool:
    """
    Check if a job matches a user's preferences.
    A job matches if it satisfies ALL configured filters:
      - At least one department keyword OR custom keyword in title+description
      - Location match (if locations are set and skip_location=False)
      - Remote preference (if not "any")
    """
    title = (job.get("job_title", "") or "").lower()
    desc = (job.get("job_description", "") or "").lower()
    combined = f"{title} {desc}"

    city = (job.get("job_city", "") or "").lower()
    country = (job.get("job_country", "") or "").lower()
    job_loc = f"{city} {country}"

    depts = prefs.get("departments", [])
    locations = prefs.get("locations", [])
    custom_kw = prefs.get("custom_keywords", [])
    remote_pref = prefs.get("remote_pref", "any")

    # ── Keyword matching (departments + custom) ──
    # Use word-boundary matching to prevent "software" matching "accounting software"
    def _word_match(keyword: str, text: str) -> bool:
        """Check if keyword appears as a whole word/phrase in text."""
        pattern = r'\b' + re.escape(keyword) + r'\b'
        return bool(re.search(pattern, text))

    has_keyword_match = False

    # Check department keywords — multi-signal approach
    for dept_code in depts:
        dept = DEPARTMENTS.get(dept_code)
        if not dept:
            continue
        kw_list = dept["keywords"]

        # Signal 1: Any keyword in title → strong match
        if any(_word_match(kw, title) for kw in kw_list):
            has_keyword_match = True
            break

        # Signal 2: Multi-word keyword in description → specific enough
        multi_word_kws = [kw for kw in kw_list if " " in kw]
        if any(_word_match(kw, desc) for kw in multi_word_kws):
            has_keyword_match = True
            break

        # Signal 3: 2+ single-word keywords in description → likely relevant
        single_kws = [kw for kw in kw_list if " " not in kw]
        desc_matches = sum(1 for kw in single_kws if _word_match(kw, desc))
        if desc_matches >= 2:
            has_keyword_match = True
            break

    # Check custom keywords — same logic
    if not has_keyword_match and custom_kw:
        if any(_word_match(kw, title) for kw in custom_kw):
            has_keyword_match = True
        elif any(_word_match(kw, desc) for kw in custom_kw):
            has_keyword_match = True

    # If no departments AND no custom keywords selected, match everything
    if not depts and not custom_kw:
        has_keyword_match = True

    if not has_keyword_match:
        return False

    # ── Location matching ──
    if locations and not skip_location:
        location_match = False
        for loc_code in locations:
            loc = LOCATIONS.get(loc_code)
            if loc and any(area in job_loc for area in loc["areas"]):
                location_match = True
                break
        if not location_match:
            return False

    # ── Remote preference matching ──
    if remote_pref != "any":
        remote_keywords = {
            "remote": ["remote", "work from home", "wfh", "virtual"],
            "hybrid": ["hybrid", "flexible"],
            "onsite": ["on-site", "onsite", "in-office", "on site"],
        }
        required = remote_keywords.get(remote_pref, [])
        if required and not any(kw in combined for kw in required):
            return False

    return True


# ════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════
def should_send_digest(prefs: dict, last_digest_time) -> bool:
    """
    Check if enough time has passed since the last digest based on
    the user's notification frequency preference.
    last_digest_time can be a datetime object from PostgreSQL or None.
    """
    if not last_digest_time:
        return True

    freq = prefs.get("notify_frequency", "6h")
    if freq == "off":
        return False

    import time
    from datetime import datetime, timezone

    # Convert datetime to Unix timestamp
    if hasattr(last_digest_time, 'timestamp'):
        last_ts = last_digest_time.timestamp()
    else:
        return True  # Can't parse — assume it's old enough

    intervals = {"6h": 6*3600, "12h": 12*3600, "24h": 24*3600, "48h": 48*3600}
    interval = intervals.get(freq, 6*3600)
    return (time.time() - last_ts) >= interval
