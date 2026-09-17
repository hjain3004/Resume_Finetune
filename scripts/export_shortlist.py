"""Export top shortlisted jobs to a compact directory for external / web review.

Usage:
    .venv/bin/python -m scripts.export_shortlist [--db PATH] [--limit N] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_")
    return s[:max_len]


def export_shortlist(
    db_path: str = "data/jobs.db",
    out_dir: str = "shortlist",
    limit: int = 40,
) -> Path:
    dest = Path(out_dir)
    jds_dest = dest / "jds"
    jds_dest.mkdir(parents=True, exist_ok=True)

    src_conn = sqlite3.connect(db_path)
    src_conn.row_factory = sqlite3.Row

    rows = src_conn.execute(
        """
        SELECT * FROM jobs 
        WHERE status = 'SHORTLISTED' 
        ORDER BY fit_score DESC, id DESC 
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    if not rows:
        print(f"No shortlisted jobs found in {db_path}.")
        return dest

    # 1. SQLite database
    db_file = dest / f"jobs_top{limit}.db"
    if db_file.exists():
        db_file.unlink()

    dst_conn = sqlite3.connect(db_file)
    schema_rows = src_conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name IN ('jobs', 'runs', 'run_sources')"
    ).fetchall()
    for s in schema_rows:
        if s[0]:
            dst_conn.execute(s[0])

    runs = src_conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchall()
    if runs:
        run_cols = [col[1] for col in src_conn.execute("PRAGMA table_info(runs)").fetchall()]
        placeholders = ", ".join(["?"] * len(run_cols))
        dst_conn.executemany(
            f"INSERT INTO runs ({', '.join(run_cols)}) VALUES ({placeholders})",
            [tuple(r) for r in runs],
        )

    job_cols = [col[1] for col in src_conn.execute("PRAGMA table_info(jobs)").fetchall()]
    placeholders = ", ".join(["?"] * len(job_cols))
    dst_conn.executemany(
        f"INSERT INTO jobs ({', '.join(job_cols)}) VALUES ({placeholders})",
        [tuple(r) for r in rows],
    )
    dst_conn.commit()
    dst_conn.close()

    # 2. JSON export and individual JDs
    jobs_list = []
    table_rows = []

    for idx, r in enumerate(rows, 1):
        job_dict = dict(r)
        jobs_list.append(job_dict)

        co_slug = slugify(r["company"])
        title_slug = slugify(r["title"])
        filename = f"{idx:02d}_{co_slug}_{title_slug}.txt"
        jd_file_path = jds_dest / filename
        jd_file_path.write_text(r["jd_text"] or "", encoding="utf-8")

        table_rows.append(
            f"| {idx} | {r['fit_score']} | {r['company']} | {r['title']} | {r['base_variant']} | "
            f"{r['location'] or 'N/A'} | [`{filename}`](jds/{filename}) |"
        )

    json_file = dest / f"jobs_top{limit}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(jobs_list, f, indent=2)

    readme_content = f"""# Top {limit} Shortlisted Jobs

This directory contains the top {limit} shortlisted jobs scored from the latest ingestion batch.
It is staged for use with Codex on Chrome / GitHub.

## Contents
- `{db_file.name}`: Standalone SQLite database (contains schema + top {limit} jobs + latest run).
- `{json_file.name}`: Complete JSON export of all {limit} jobs with scores, rationales, and full JD texts.
- `jds/`: Individual plaintext JD files for each job, named by rank and company.

## Usage with Codex / Tailoring Lane
- **Direct file tailoring:**
  ```bash
  python -m scripts.tailor_now run --jd shortlist/jds/<file>.txt --company "<Company>" --title "<Title>" --variant <variant>
  ```
- **Using as pipeline database:**
  ```bash
  mkdir -p data && cp shortlist/{db_file.name} data/jobs.db
  ```

## Shortlist Table

| # | Score | Company | Title | Variant | Location | File |
|---|---|---|---|---|---|---|
""" + "\n".join(table_rows) + "\n"

    (dest / "README.md").write_text(readme_content, encoding="utf-8")
    return dest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export top shortlisted jobs.")
    parser.add_argument("--db", default="data/jobs.db", help="Path to source SQLite database")
    parser.add_argument("--out", default="shortlist", help="Output directory")
    parser.add_argument("--limit", type=int, default=40, help="Number of jobs to export")
    args = parser.parse_args()

    out_path = export_shortlist(db_path=args.db, out_dir=args.out, limit=args.limit)
    print(f"Exported top {args.limit} jobs to {out_path}")
