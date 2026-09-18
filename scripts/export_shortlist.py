"""Export top shortlisted jobs to a compact directory for external / web review.

Supports two modes:
- tailoring_ready (default): Only exports verified ATS JDs
  with cryptographic provenance sidecars, excluding aggregator summaries.
- review_only: Exports shortlisted jobs for human review, clearly labeled as non-tailoring
  for any aggregator rows or unattested database rows.

Usage:
    .venv/bin/python -m scripts.export_shortlist [--db PATH] [--limit N] [--out DIR] [--mode {tailoring_ready,review_only}]
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import re
import shlex
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
    validate_provenance_for_tailoring,
)

_PUBLICATION_HOOK: Callable[[str], None] | None = None


def _call_publication_hook(stage: str) -> None:
    if _PUBLICATION_HOOK is not None:
        _PUBLICATION_HOOK(stage)


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
        if quality == JDQuality.USER_ATTESTED.value:
            return "user_attested row lacks persisted attestation metadata in database"
        if quality != JDQuality.ATS.value:
            return f"aggregator summary ({quality or 'unspecified'})"

    return None


def _check_no_legacy_non_symlinks(dest: Path) -> None:
    """Refuse to overwrite or implicitly migrate existing non-symlink public files/directories."""
    if not dest.exists():
        return
    for p in dest.iterdir():
        if p.name == "generations" or p.name.startswith(".tmp_"):
            continue
        if not p.is_symlink():
            raise ValueError(
                f"Output directory {dest} contains existing non-symlink artifact '{p.name}'. "
                "Refusing to overwrite or migrate tracked shortlist files implicitly. "
                "Please specify a new empty directory via --out."
            )


def _atomic_symlink(target_rel: Path, link_path: Path) -> None:
    """Atomically create or update a symlink to target_rel."""
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


def _ensure_compatibility_indirections(dest: Path) -> None:
    """Ensure all public paths are stable relative symlinks through dest/current."""
    items = ["jds", "jobs.db", "jobs.json", "README.md", "current.json"]
    for name in items:
        link_path = dest / name
        target_rel = Path("current") / name
        if link_path.is_symlink():
            try:
                if os.readlink(link_path) == str(target_rel):
                    continue
            except OSError:
                pass
        _atomic_symlink(target_rel, link_path)


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
    _check_no_legacy_non_symlinks(dest)
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

    generations_dir = dest / "generations"
    generations_dir.mkdir(parents=True, exist_ok=True)
    gen_id = f"gen_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    gen_dir = generations_dir / gen_id
    gen_dir.mkdir(parents=True, exist_ok=True)
    committed = False

    try:
        gen_jds = gen_dir / "jds"
        gen_jds.mkdir(parents=True, exist_ok=True)

        # 1. SQLite database
        _call_publication_hook("before_db")
        gen_db_file = gen_dir / "jobs.db"
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

        # 2. Individual JDs and provenance sidecars
        _call_publication_hook("before_jds")
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

            raw_quality = r["jd_quality"] or "unverified"
            if raw_quality == JDQuality.USER_ATTESTED.value:
                tailor_badge = "Review-Only (Missing Persisted Attestation)"
                sidecar_quality = JDQuality.UNVERIFIED.value
                source_type = "unverified"
                ats_url = None
                sidecar_job_id = None
            elif raw_quality == JDQuality.ATS.value:
                tailor_badge = "Tailoring-Ready"
                sidecar_quality = JDQuality.ATS.value
                source_type = (r["resolver"] or "").strip() or (r["source"] or "").strip() or "ats"
                ats_url = (r["ats_url"] or "").strip() or (r["url"] if raw_quality == "ats" else None)
                sidecar_job_id = r["id"]
            else:
                tailor_badge = "Review-Only (Aggregator)"
                sidecar_quality = raw_quality
                source_type = (r["resolver"] or "").strip() or (r["source"] or "").strip() or "aggregator"
                ats_url = None
                sidecar_job_id = None

            sidecar = JDProvenance(
                schema_version=JD_PROVENANCE_SCHEMA,
                company=r["company"],
                title=r["title"],
                source_url=r["url"],
                source_type=source_type,
                jd_quality=sidecar_quality,
                jd_sha256=jd_sha256,
                job_id=sidecar_job_id,
                ats_url=ats_url,
                attestation=None,
            )
            sidecar_path = gen_jds / f"{filename}.provenance.json"
            sidecar_path.write_text(json.dumps(sidecar.to_dict(), indent=2), encoding="utf-8")

            table_rows.append(
                f"| {idx} | {r['fit_score']} | {r['company']} | {r['title']} | {r['base_variant']} | "
                f"{r['location'] or 'N/A'} | {tailor_badge} | [`{filename}`](jds/{filename}) |"
            )

        # 3. Validate every JD against compact DB in tailoring_ready mode
        _call_publication_hook("before_validation")
        if export_mode is ExportMode.TAILORING_READY:
            verify_conn = db.get_readonly_connection(gen_db_file)
            try:
                for idx, r in enumerate(included_rows, 1):
                    co_slug = slugify(r["company"])
                    title_slug = slugify(r["title"])
                    filename = f"{idx:02d}_{co_slug}_{title_slug}.txt"
                    jd_file_path = gen_jds / filename
                    sidecar_path = gen_jds / f"{filename}.provenance.json"
                    validate_provenance_for_tailoring(
                        jd_file_path,
                        company=r["company"],
                        title=r["title"],
                        db_conn=verify_conn,
                        sidecar_path=sidecar_path,
                    )
            finally:
                verify_conn.close()

        # 4. JSON export
        _call_publication_hook("before_json")
        gen_json_file = gen_dir / "jobs.json"
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

        # 5. README documentation
        _call_publication_hook("before_readme")
        if export_mode is ExportMode.TAILORING_READY:
            mode_header = f"# Shortlisted Jobs (Tailoring-Ready)"
            mode_desc = (
                f"This directory contains {len(included_rows)} shortlisted jobs verified as ATS-quality.\n"
                "All JDs are equipped with cryptographic provenance sidecars (`.provenance.json`) and "
                "are ready for direct use with the Apply-Now tailoring lane."
            )
            if included_rows:
                top_job = included_rows[0]
                top_co = top_job["company"]
                top_ti = top_job["title"]
                top_var = top_job["base_variant"] or "backend"
                top_co_slug = slugify(top_co)
                top_ti_slug = slugify(top_ti)
                example_jd = str(dest / "jds" / f"01_{top_co_slug}_{top_ti_slug}.txt")
                example_db = str(dest / "jobs.db")
                cmd_argv = [
                    "python", "-m", "scripts.tailor_now", "run",
                    "--jd", example_jd,
                    "--company", top_co,
                    "--title", top_ti,
                    "--variant", top_var,
                    "--db", example_db,
                ]
                example_cmd = shlex.join(cmd_argv)
            else:
                example_cmd = f"python -m scripts.tailor_now run --jd {dest}/jds/<file>.txt --company \"<Company>\" --title \"<Title>\" --variant <variant> --db {dest}/jobs.db"

            usage_sec = f"""## Usage with Apply-Now Lane
```bash
{example_cmd}
```
- **Using as pipeline database:**
  ```bash
  mkdir -p data && cp {shlex.quote(str(dest / "jobs.db"))} data/jobs.db
  ```"""
        else:
            mode_header = f"# Shortlisted Jobs (REVIEW ONLY - NOT TAILORING READY)"
            mode_desc = (
                "> [!WARNING]\n"
                "> **REVIEW ONLY EXPORT — NOT TAILORING READY**\n"
                "> This directory contains shortlisted jobs for human/external review.\n"
                "> Aggregator summaries and database rows marked user_attested lack persisted attestation "
                "metadata and cannot be tailored directly.\n"
                "> To tailor any non-ATS job, obtain the literal official employer posting and run:\n"
                "> `python -m scripts.tailor_now attest --jd <path> --company \"<Company>\" --title \"<Title>\" --source-url \"<Official URL>\"`"
            )
            usage_sec = f"""## Usage Instructions
- **Official ATS JDs:** May be used directly with the Apply-Now lane.
- **Aggregator / unverified / unattested summaries:** Cannot be tailored directly. To tailor, recover the official posting and run:
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
- `jobs.db`: Standalone SQLite database (contains schema + {len(included_rows)} jobs + latest run).
- `jobs.json`: Complete JSON export of {len(included_rows)} jobs with scores, rationales, and full JD texts.
- `jds/`: Individual plaintext JD files and their `.provenance.json` sidecars.

{usage_sec}

## Shortlist Table

| # | Score | Company | Title | Variant | Location | Status | File |
|---|---|---|---|---|---|---|---|
""" + "\n".join(table_rows) + "\n" + exclusion_md

        gen_readme_file = gen_dir / "README.md"
        gen_readme_file.write_text(readme_content, encoding="utf-8")

        # 6. Write current.json inside gen_dir
        _call_publication_hook("before_current_json")
        current_data = {
            "generation_id": gen_id,
            "mode": export_mode.value,
            "limit": limit,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": {
                "jds": f"generations/{gen_id}/jds",
                "db": f"generations/{gen_id}/jobs.db",
                "json": f"generations/{gen_id}/jobs.json",
                "readme": f"generations/{gen_id}/README.md",
            },
        }
        gen_current_json = gen_dir / "current.json"
        gen_current_json.write_text(json.dumps(current_data, indent=2), encoding="utf-8")

        # 7. Ensure stable compatibility indirections BEFORE swapping current
        _call_publication_hook("before_indirections")
        _ensure_compatibility_indirections(dest)

        # 8. Atomic commit point: swap dest / "current" -> generations / gen_id
        _call_publication_hook("before_pointer_swap")
        tmp_current = dest / f".tmp_current_{uuid.uuid4().hex}"
        tmp_current.symlink_to(Path("generations") / gen_id)
        try:
            _call_publication_hook("during_pointer_swap")
            os.replace(tmp_current, dest / "current")
            committed = True
        finally:
            if tmp_current.is_symlink() or tmp_current.exists():
                try:
                    tmp_current.unlink()
                except OSError:
                    pass

        return dest

    except Exception:
        if not committed and gen_dir.exists():
            shutil.rmtree(gen_dir, ignore_errors=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export top shortlisted jobs safely.")
    parser.add_argument("--db", default="data/jobs.db", help="Path to source SQLite database")
    parser.add_argument("--out", default="shortlist", help="Output directory")
    parser.add_argument("--limit", type=int, default=40, help="Number of jobs to export")
    parser.add_argument(
        "--mode",
        choices=[m.value for m in ExportMode],
        default=ExportMode.TAILORING_READY.value,
        help="Export mode: tailoring_ready (only ATS JDs) or review_only (includes aggregators)",
    )
    args = parser.parse_args()

    out_path = export_shortlist(db_path=args.db, out_dir=args.out, limit=args.limit, mode=args.mode)
    print(f"Exported to {out_path}")
