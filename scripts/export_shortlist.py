"""Export top shortlisted jobs to a compact directory for external / web review.

Supports two modes:
- tailoring_ready (default): Only exports verified ATS or user-attested official JDs
  with cryptographic provenance sidecars, excluding aggregator summaries.
- review_only: Exports shortlisted jobs for human review, clearly labeled as non-tailoring
  for any aggregator rows.

Usage:
    .venv/bin/python -m scripts.export_shortlist [--db PATH] [--limit N] [--out DIR] [--mode {tailoring_ready,review_only}]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from typing import Any
import uuid

from src import db
from src.tailor.provenance import (
    JD_PROVENANCE_SCHEMA,
    JDQuality,
    JDProvenance,
    compute_jd_sha256,
)


class ExportMode(str, Enum):
    TAILORING_READY = "tailoring_ready"
    REVIEW_ONLY = "review_only"


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_")
    return s[:max_len]


@dataclass(frozen=True)
class ExcludedJob:
    job_id: int
    company: str
    title: str
    reason: str


def _evaluate_row_eligibility(row: sqlite3.Row, mode: ExportMode) -> str | None:
    """Return None if eligible, or an exclusion reason string if ineligible."""
    company = (row["company"] or "").strip()
    title = (row["title"] or "").strip()
    url = (row["url"] or "").strip()
    jd_text = (row["jd_text"] or "").strip()
    quality = (row["jd_quality"] or "").strip()

    if not company:
        return "missing company"
    if not title:
        return "missing title"
    if not url:
        return "missing url"
    if not jd_text or len(jd_text) < 300:
        return f"incomplete or short jd_text ({len(jd_text)} chars, min 300)"

    if mode is ExportMode.TAILORING_READY:
        if quality != JDQuality.ATS.value and quality != JDQuality.USER_ATTESTED.value:
            return f"aggregator summary ({quality or 'unspecified'})"

    return None


def _atomic_symlink(target_rel: Path, link_path: Path) -> None:
    """Atomically create or update a symlink to target_rel."""
    if link_path.is_dir() and not link_path.is_symlink():
        shutil.rmtree(link_path)
    tmp_link = link_path.parent / f".tmp_symlink_{link_path.name}_{uuid.uuid4().hex}"
    try:
        tmp_link.symlink_to(target_rel)
        os.replace(tmp_link, link_path)
    finally:
        if tmp_link.is_symlink() or tmp_link.exists():
            try:
                tmp_link.unlink()
            except OSError:
                pass


def export_shortlist(
    db_path: str = "data/jobs.db",
    out_dir: str = "shortlist",
    limit: int = 40,
    mode: str | ExportMode = ExportMode.TAILORING_READY,
) -> Path:
    if isinstance(mode, str):
        export_mode = ExportMode(mode)
    else:
        export_mode = mode

    dest = Path(out_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    src_conn = db.get_readonly_connection(db_path)
    try:
        candidate_rows = db.shortlisted_jobs_by_fit(src_conn, limit=limit)
    finally:
        src_conn.close()

    if not candidate_rows:
        print(f"No shortlisted jobs found in {db_path}.", file=sys.stderr)
        return dest

    included_rows: list[sqlite3.Row] = []
    excluded_jobs: list[ExcludedJob] = []

    for row in candidate_rows:
        reason = _evaluate_row_eligibility(row, export_mode)
        if reason is not None:
            excluded_jobs.append(
                ExcludedJob(
                    job_id=row["id"],
                    company=row["company"] or "Unknown",
                    title=row["title"] or "Unknown",
                    reason=reason,
                )
            )
            if export_mode is ExportMode.TAILORING_READY:
                continue
        included_rows.append(row)

    # Print summary of inclusion/exclusion
    print(f"Evaluated {len(candidate_rows)} shortlisted job(s) from {db_path}:")
    print(f"  Included: {len(included_rows)} ({export_mode.value})")
    if excluded_jobs:
        print(f"  Excluded: {len(excluded_jobs)}")
        reasons_tally: dict[str, int] = {}
        for ex in excluded_jobs:
            reasons_tally[ex.reason] = reasons_tally.get(ex.reason, 0) + 1
        for r, count in sorted(reasons_tally.items()):
            print(f"    - {count} {r}")

    # Safe immutable generation directory publication
    generations_dir = dest / "generations"
    generations_dir.mkdir(parents=True, exist_ok=True)
    gen_id = f"gen_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    gen_dir = generations_dir / gen_id
    gen_dir.mkdir(parents=True, exist_ok=True)

    try:
        gen_jds = gen_dir / "jds"
        gen_jds.mkdir(parents=True, exist_ok=True)

        # 1. SQLite database
        gen_db_file = gen_dir / f"jobs_top{limit}.db"
        dst_conn = sqlite3.connect(gen_db_file)
        try:
            src_conn_rw = db.get_readonly_connection(db_path)
            try:
                schema_stmts = db.table_schema_statements(src_conn_rw)
                for s in schema_stmts:
                    dst_conn.execute(s)

                latest_run = db.latest_run_row(src_conn_rw)
                if latest_run is not None:
                    run_cols = db.table_columns(src_conn_rw, "runs")
                    db.insert_rows_into_table(dst_conn, "runs", run_cols, [latest_run])

                if included_rows:
                    job_cols = db.table_columns(src_conn_rw, "jobs")
                    db.insert_rows_into_table(dst_conn, "jobs", job_cols, included_rows)
            finally:
                src_conn_rw.close()
            dst_conn.commit()
        finally:
            dst_conn.close()

        # 2. JSON export, individual JDs, and provenance sidecars
        jobs_list: list[dict[str, Any]] = []
        table_rows: list[str] = []

        for idx, r in enumerate(included_rows, 1):
            job_dict = dict(r)
            jobs_list.append(job_dict)

            co_slug = slugify(r["company"])
            title_slug = slugify(r["title"])
            filename = f"{idx:02d}_{co_slug}_{title_slug}.txt"
            jd_file_path = gen_jds / filename
            jd_text = r["jd_text"] or ""
            jd_bytes = jd_text.encode("utf-8")
            jd_file_path.write_bytes(jd_bytes)

            jd_sha256 = compute_jd_sha256(jd_bytes)

            # Determine quality & source type for provenance sidecar
            raw_quality = r["jd_quality"] or "unverified"
            source_type = r["resolver"] or ("ats" if r["ats_url"] else "aggregator")

            sidecar = JDProvenance(
                schema_version=JD_PROVENANCE_SCHEMA,
                company=r["company"],
                title=r["title"],
                source_url=r["url"],
                source_type=source_type,
                jd_quality=raw_quality,
                jd_sha256=jd_sha256,
                job_id=r["id"],
                ats_url=r["ats_url"] or (r["url"] if raw_quality == "ats" else None),
                attestation=None,
            )
            sidecar_path = gen_jds / f"{filename}.provenance.json"
            sidecar_path.write_text(json.dumps(sidecar.to_dict(), indent=2), encoding="utf-8")

            can_tailor = raw_quality in (JDQuality.ATS.value, JDQuality.USER_ATTESTED.value)
            tailor_badge = "Tailoring-Ready" if can_tailor else "Review-Only (Aggregator)"

            table_rows.append(
                f"| {idx} | {r['fit_score']} | {r['company']} | {r['title']} | {r['base_variant']} | "
                f"{r['location'] or 'N/A'} | {tailor_badge} | [`{filename}`](jds/{filename}) |"
            )

        gen_json_file = gen_dir / f"jobs_top{limit}.json"
        with open(gen_json_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "mode": export_mode.value,
                    "limit": limit,
                    "total_evaluated": len(candidate_rows),
                    "included_count": len(included_rows),
                    "excluded_count": len(excluded_jobs),
                    "excluded": [
                        {"id": ex.job_id, "company": ex.company, "title": ex.title, "reason": ex.reason}
                        for ex in excluded_jobs
                    ],
                    "jobs": jobs_list,
                },
                f,
                indent=2,
            )

        # 3. README documentation
        if export_mode is ExportMode.TAILORING_READY:
            mode_header = f"# Top {limit} Shortlisted Jobs (Tailoring-Ready)"
            mode_desc = (
                f"This directory contains {len(included_rows)} shortlisted jobs verified as ATS-quality or "
                "user-attested official postings.\n"
                "All JDs are equipped with cryptographic provenance sidecars (`.provenance.json`) and "
                "are ready for direct use with the Apply-Now tailoring lane."
            )
            usage_sec = f"""## Usage with Codex / Apply-Now Lane
- **Direct file tailoring:**
  ```bash
  python -m scripts.tailor_now run --jd shortlist/jds/<file>.txt --company "<Company>" --title "<Title>" --variant <variant>
  ```
- **Using as pipeline database:**
  ```bash
  mkdir -p data && cp shortlist/jobs_top{limit}.db data/jobs.db
  ```"""
        else:
            mode_header = f"# Top {limit} Shortlisted Jobs (REVIEW ONLY - NOT TAILORING READY)"
            mode_desc = (
                "> [!WARNING]\n"
                "> **REVIEW ONLY EXPORT — DO NOT TAILOR AGGREGATOR ROWS DIRECTLY**\n"
                "> This directory contains shortlisted jobs for human/external review, including aggregator summaries.\n"
                "> Aggregator summaries lack literal employer wording and cannot be tailored directly.\n"
                "> To tailor an aggregator job, obtain the literal official employer posting and run:\n"
                "> `python -m scripts.tailor_now attest --jd <path> --company \"<Company>\" --title \"<Title>\" --source-url \"<Official URL>\"`"
            )
            usage_sec = f"""## Usage Instructions
- **Official ATS JDs:** May be used directly with the Apply-Now lane.
- **Aggregator summaries:** Must first be attested with official employer copy via:
  ```bash
  python -m scripts.tailor_now attest --jd <path> --company "<Company>" --title "<Title>" --source-url "<Official URL>"
  ```"""

        exclusion_md = ""
        if excluded_jobs:
            ex_rows = [
                f"| {ex.job_id} | {ex.company} | {ex.title} | {ex.reason} |"
                for ex in excluded_jobs
            ]
            exclusion_md = (
                f"\n## Excluded Shortlisted Jobs ({len(excluded_jobs)})\n\n"
                "| ID | Company | Title | Reason |\n"
                "|---|---|---|---|\n"
                + "\n".join(ex_rows)
                + "\n"
            )

        readme_content = f"""{mode_header}

{mode_desc}

## Contents
- `jobs_top{limit}.db`: Standalone SQLite database (contains schema + {len(included_rows)} jobs + latest run).
- `jobs_top{limit}.json`: Complete JSON export of {len(included_rows)} jobs with scores, rationales, and full JD texts.
- `jds/`: Individual plaintext JD files and their `.provenance.json` sidecars.

{usage_sec}

## Shortlist Table

| # | Score | Company | Title | Variant | Location | Status | File |
|---|---|---|---|---|---|---|---|
""" + "\n".join(table_rows) + "\n" + exclusion_md

        gen_readme_file = gen_dir / "README.md"
        gen_readme_file.write_text(readme_content, encoding="utf-8")

        # 4. Atomic publication: update symlinks to the new generation
        _atomic_symlink(Path("generations") / gen_id / "jds", dest / "jds")
        _atomic_symlink(Path("generations") / gen_id / f"jobs_top{limit}.db", dest / f"jobs_top{limit}.db")
        _atomic_symlink(Path("generations") / gen_id / f"jobs_top{limit}.json", dest / f"jobs_top{limit}.json")
        _atomic_symlink(Path("generations") / gen_id / "README.md", dest / "README.md")
        _atomic_symlink(Path("generations") / gen_id, dest / "current")

        # 5. Write atomic current.json pointer LAST
        current_data = {
            "generation_id": gen_id,
            "mode": export_mode.value,
            "limit": limit,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": {
                "jds": f"generations/{gen_id}/jds",
                "db": f"generations/{gen_id}/jobs_top{limit}.db",
                "json": f"generations/{gen_id}/jobs_top{limit}.json",
                "readme": f"generations/{gen_id}/README.md",
            },
        }
        tmp_current = dest / f".tmp_current_{uuid.uuid4().hex}.json"
        tmp_current.write_text(json.dumps(current_data, indent=2), encoding="utf-8")
        os.replace(tmp_current, dest / "current.json")

    except Exception:
        if gen_dir.exists():
            shutil.rmtree(gen_dir, ignore_errors=True)
        raise

    return dest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export top shortlisted jobs safely.")
    parser.add_argument("--db", default="data/jobs.db", help="Path to source SQLite database")
    parser.add_argument("--out", default="shortlist", help="Output directory")
    parser.add_argument("--limit", type=int, default=40, help="Number of jobs to export")
    parser.add_argument(
        "--mode",
        choices=[m.value for m in ExportMode],
        default=ExportMode.TAILORING_READY.value,
        help="Export mode: tailoring_ready (only ATS/attested JDs) or review_only (includes aggregators)",
    )
    args = parser.parse_args()

    out_path = export_shortlist(db_path=args.db, out_dir=args.out, limit=args.limit, mode=args.mode)
    print(f"Exported to {out_path}")
