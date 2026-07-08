"""M6.8 freshness & recycling defense (docs/PHASE2_KICKOFF.md).

Three independent behaviors live here (the dedup-key-conflict half of repost
detection and the resurfacing rule live in db.insert_discovered, since they
need to run inline with the INSERT):

1. Content-based repost detection: after a row resolves, check whether its
   jd_text is a near-duplicate of a TERMINAL row at the same company — i.e.
   a posting the user already decided on, discovered again under a different
   dedup_key (different title wording/location).
2. Liveness recheck: at digest time, one polite GET per stale SHORTLISTED/
   TAILORED row to see if the posting is still up.

Deliberately scoped down from the doc's "404/410/absence from the board's
live listing": only 404/410 close a row (deterministic, no per-ATS scraping
logic); any other response (200, 5xx, timeout) just touches last_seen_at —
ambiguous signals stay open rather than risk a false CLOSE. See DECISIONS.md.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import requests

from src import db
from src.models import TERMINAL_STATUSES, Status, norm
from src.resolve.base import PoliteSession
from src.textsim import jaccard_similarity, shingles

REPOST_SIMILARITY_THRESHOLD = 0.85
_CLOSED_STATUS_CODES = (404, 410)


def find_content_repost(
    conn: sqlite3.Connection, company: str, jd_text: str, *, exclude_row_id: int
) -> sqlite3.Row | None:
    """Return the first TERMINAL row at the same company whose jd_text is a
    near-duplicate (5-word-shingle Jaccard >= 0.85) of `jd_text`, or None."""
    candidate_shingles = shingles(jd_text)
    if not candidate_shingles:
        return None
    company_norm = norm(company)
    for row in db.all_rows(conn):
        if row["id"] == exclude_row_id:
            continue
        if row["status"] not in TERMINAL_STATUSES:
            continue
        if norm(row["company"]) != company_norm:
            continue
        if not row["jd_text"]:
            continue
        if jaccard_similarity(candidate_shingles, shingles(row["jd_text"])) >= REPOST_SIMILARITY_THRESHOLD:
            return row
    return None


def record_content_repost(conn: sqlite3.Connection, job_id: int, prior_row: sqlite3.Row) -> None:
    outcome = "applied" if prior_row["status"] == Status.APPLIED else "skipped"
    prior_date = (prior_row["jd_resolved_at"] or prior_row["discovered_at"] or "")[:10]
    note = f"recycled: you {outcome} job #{prior_row['id']} ({prior_row['status']}) on {prior_date}"
    db.add_flag_and_note(conn, job_id, "repost", note)


def run_liveness_recheck(conn: sqlite3.Connection, session: PoliteSession, liveness_days: int) -> int:
    """One polite GET per SHORTLISTED/TAILORED row not checked within
    `liveness_days`. Returns the count newly marked CLOSED."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=liveness_days)).isoformat()
    closed_count = 0
    for row in db.rows_needing_liveness_check(conn, cutoff):
        url = row["ats_url"] or row["url"]
        try:
            response = session.get(url)
        except requests.exceptions.RequestException:
            continue
        if response.status_code in _CLOSED_STATUS_CODES:
            db.mark_closed(conn, row["id"], f"liveness recheck: {response.status_code} on {url}")
            closed_count += 1
        else:
            db.touch_last_seen(conn, row["id"])
    return closed_count
