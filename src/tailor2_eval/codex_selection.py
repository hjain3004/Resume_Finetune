"""Read-only deterministic selection and private materialization for the Luna pilot."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src import db
from src.tailor2_eval.checksums import sha256_file
from src.tailor2_eval.targets import Top10Target

EXPECTED_COMPANIES = (
    "Zoom",
    "DoorDash",
    "ID.me",
    "RoadRunner",
    "LexisNexis",
    "C3.ai",
    "Commure",
    "KLA",
    "AiPrise",
    "Arch",
)

EXPECTED_COMPANY_KEYS = (
    "zoom",
    "doordash",
    "idme",
    "roadrunner",
    "lexisnexislegalprofessional",
    "c3ai",
    "commure",
    "kla",
    "aiprise",
    "arch",
)


class CodexSelectionDriftError(RuntimeError):
    """The read-only database no longer produces the approved pilot set."""


def _normalize_company(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def select_codex_targets(conn: Any) -> list[Any]:
    chosen: list[Any] = []
    seen_companies: set[str] = set()
    for row in db.load_shortlisted_ats_jobs_readonly(conn):
        company = str(row["company"] or "").strip()
        if company.casefold() == "openai" or not str(row["jd_text"] or "").strip():
            continue
        if not row["base_variant"] or int(row["id"]) in db.PROHIBITED_TAILORING_JOB_IDS:
            continue
        normalized = _normalize_company(company)
        if normalized in seen_companies:
            continue
        seen_companies.add(normalized)
        chosen.append(row)
        if len(chosen) == 10:
            break
    companies = tuple(str(row["company"]) for row in chosen)
    company_keys = tuple(_normalize_company(company) for company in companies)
    if company_keys != EXPECTED_COMPANY_KEYS:
        raise CodexSelectionDriftError(f"deterministic Luna selection changed: expected {EXPECTED_COMPANIES}, got {companies}")
    if any(company.casefold() == "openai" for company in companies):
        raise CodexSelectionDriftError("OpenAI must not be selected for the Luna pilot")
    return chosen


def materialize_private_selection(conn: Any, artifact_root: Path, db_checksum: str) -> tuple[list[Top10Target], Path]:
    artifact_root = Path(artifact_root)
    jds_dir = artifact_root / "selection" / "jds"
    jds_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    targets: list[Top10Target] = []
    for rank, row in enumerate(select_codex_targets(conn), start=1):
        company = str(row["company"])
        job_id = int(row["id"])
        target_id = f"{_normalize_company(company)}_{job_id}"
        jd_filename = f"{rank:02d}_{_normalize_company(company)}_{job_id}.txt"
        jd_path = jds_dir / jd_filename
        jd_path.write_text(str(row["jd_text"]), encoding="utf-8")
        target = Top10Target(
            target_id=target_id,
            job_id=job_id,
            company=company,
            role=str(row["title"]),
            jd_path=jd_path,
            jd_sha256=sha256_file(jd_path),
            base_variant=str(row["base_variant"]),
            rank=rank,
        )
        targets.append(target)
        manifest.append(
            {
                "job_id": job_id,
                "company": company,
                "exact_title": str(row["title"]),
                "location": str(row["location"] or ""),
                "base_variant": str(row["base_variant"]),
                "jd_filename": jd_filename,
                "jd_sha256": target.jd_sha256,
                "rank": rank,
                "source_url": str(row["ats_url"] or row["url"] or ""),
            }
        )
    manifest_path = artifact_root / "selection" / "selection_manifest.json"
    manifest_path.write_text(
        json.dumps({"db_checksum": db_checksum, "companies": list(EXPECTED_COMPANIES), "targets": manifest}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return targets, manifest_path


def load_private_selection_manifest(manifest_path: Path) -> list[Top10Target]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    entries = payload["targets"] if isinstance(payload, dict) else payload
    base_dir = Path(manifest_path).parent / "jds"
    return [
        Top10Target(
            target_id=f"{_normalize_company(item['company'])}_{int(item['job_id'])}",
            job_id=int(item["job_id"]),
            company=str(item["company"]),
            role=str(item["exact_title"]),
            jd_path=base_dir / str(item["jd_filename"]),
            jd_sha256=str(item["jd_sha256"]),
            base_variant=str(item["base_variant"]),
            rank=int(item["rank"]),
        )
        for item in entries
    ]
