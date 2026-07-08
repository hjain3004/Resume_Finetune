"""Export RESOLVED jobs to a scoring batch file per ARCHITECTURE §11.

Usage: python -m scripts.export_batch [--db PATH] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src import db
from src.models import Status, norm

JD_TEXT_TRUNCATE_LEN = 6000
SHINGLE_SIZE = 5
SIMILARITY_THRESHOLD = 0.85

_AGO_LINE_RE = re.compile(r"^.{0,60}·\s*\d+\s*(?:minutes?|hours?|days?)\s+ago.*$", re.MULTILINE)
_WHITESPACE_RE = re.compile(r"\s+")


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def normalize_jd(text: str) -> str:
    """Lowercase, strip relative-time chrome lines, collapse whitespace."""
    text = (text or "").lower()
    text = _AGO_LINE_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_jd(text).encode("utf-8")).hexdigest()


def _shingles(text: str, n: int = SHINGLE_SIZE) -> set[str]:
    words = normalize_jd(text).split(" ")
    words = [w for w in words if w]
    if not words:
        return set()
    if len(words) < n:
        return {" ".join(words)}
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class _Cluster:
    rep_id: int
    rep_company: str
    rep_title: str
    rep_jd_text: str
    rep_flags: list[str]
    rep_jd_quality: str
    company_norm: str
    title_norm: str
    content_hash: str
    shingles: set[str]
    row_ids: list[int] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)


def _cluster_rows(rows: list[sqlite3.Row]) -> list[_Cluster]:
    """Group RESOLVED rows into duplicate clusters (exact content-hash or near-dup by title)."""
    clusters: list[_Cluster] = []
    for row in rows:
        jd_text = row["jd_text"] or ""
        company_norm = norm(row["company"])
        title_norm = norm(row["title"])
        c_hash = content_hash(jd_text)
        shingles = _shingles(jd_text)
        location = row["location"]

        match = None
        for cluster in clusters:
            if cluster.company_norm != company_norm:
                continue
            if cluster.content_hash == c_hash:
                match = cluster
                break
            if cluster.title_norm == title_norm and jaccard_similarity(shingles, cluster.shingles) >= SIMILARITY_THRESHOLD:
                match = cluster
                break

        if match is not None:
            match.row_ids.append(row["id"])
            if location and location not in match.locations:
                match.locations.append(location)
        else:
            clusters.append(
                _Cluster(
                    rep_id=row["id"],
                    rep_company=row["company"],
                    rep_title=row["title"],
                    rep_jd_text=jd_text,
                    rep_flags=json.loads(row["flags"]) if row["flags"] else [],
                    rep_jd_quality=row["jd_quality"] or "ats",
                    company_norm=company_norm,
                    title_norm=title_norm,
                    content_hash=c_hash,
                    shingles=shingles,
                    row_ids=[row["id"]],
                    locations=[location] if location else [],
                )
            )
    return clusters


def export_batch(
    conn: sqlite3.Connection,
    *,
    base_dir: str | Path = "data/batch",
    date_str: str | None = None,
) -> Path:
    date_str = date_str or _today_iso()
    rows = conn.execute(
        "SELECT id, company, title, jd_text, location, flags, jd_quality FROM jobs WHERE status = ? ORDER BY id",
        (Status.RESOLVED,),
    ).fetchall()
    clusters = _cluster_rows(rows)
    batch = [
        {
            "id": cluster.rep_id,
            "row_ids": sorted(cluster.row_ids),
            "company": cluster.rep_company,
            "title": cluster.rep_title,
            "locations": cluster.locations,
            "flags": cluster.rep_flags,
            "jd_quality": cluster.rep_jd_quality,
            "jd_text": cluster.rep_jd_text[:JD_TEXT_TRUNCATE_LEN],
        }
        for cluster in clusters
    ]

    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{date_str}.json"
    path.write_text(json.dumps(batch, indent=2))
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.export_batch",
        description="Export RESOLVED jobs to a scoring batch JSON file.",
    )
    parser.add_argument("--db", metavar="PATH", default="data/jobs.db", help="path to the SQLite database")
    parser.add_argument("--out-dir", metavar="DIR", default="data/batch", help="directory to write the batch file to")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    conn = db.get_connection(args.db)
    path = export_batch(conn, base_dir=args.out_dir)
    print(f"Exported batch to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
