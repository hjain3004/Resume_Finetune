"""Export RESOLVED jobs to a scoring batch file per ARCHITECTURE §11.

Usage: python -m scripts.export_batch [--db PATH] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src import db
from src.models import Status, norm
from src.textsim import content_hash, jaccard_similarity, normalize_jd, shingles as _shingles

JD_TEXT_TRUNCATE_LEN = 6000

# M7 I3 fix (2026-07-12): kept in sync with config/audit.yaml's i3.similarity_threshold
# (PROTECTED per docs/SELF_HEALING.md §4 item 3) — both check_i3 and _cluster_rows must
# agree on what counts as a near-duplicate. See DECISIONS.md for the approval.
SIMILARITY_THRESHOLD = 0.85


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


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
    row_ids: list[int] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)


def _cluster_rows(rows: list[sqlite3.Row]) -> list[_Cluster]:
    """Group RESOLVED rows into duplicate clusters within the same company, on
    any of three signals: (1) exact content-hash match, (2) exact title match
    (M6.6: aggregator resolvers like jobright generate a differently-worded AI
    summary per location for the same posting, so same-company+same-title rows
    can legitimately score well below any reasonable shingle-similarity
    threshold — an exact title match is itself strong enough evidence), or
    (3) Jaccard content similarity >= SIMILARITY_THRESHOLD (M7 I3 fix,
    2026-07-12: restores the fuzzy-match path M6.6 removed, as an ADDITIONAL
    signal alongside the exact-title path rather than a replacement — closes
    the gap where check_i3 flagged same-company pairs with high content
    similarity but differently-worded titles that this function had no way to
    merge; see DECISIONS.md)."""
    clusters: list[_Cluster] = []
    for row in rows:
        jd_text = row["jd_text"] or ""
        company_norm = norm(row["company"])
        title_norm = norm(row["title"])
        c_hash = content_hash(jd_text)
        row_shingles = _shingles(jd_text)
        location = row["location"]

        match = None
        for cluster in clusters:
            if cluster.company_norm != company_norm:
                continue
            if cluster.content_hash == c_hash:
                match = cluster
                break
            if cluster.title_norm == title_norm:
                match = cluster
                break
            if jaccard_similarity(row_shingles, _shingles(cluster.rep_jd_text)) >= SIMILARITY_THRESHOLD:
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
