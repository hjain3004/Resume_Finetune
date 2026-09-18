"""Read-only access to the existing Top-10 tailoring target manifest.

This module never writes to `shortlist/tailoring_targets/**` -- it only
resolves each target's JD file path and re-derives a target_id
(`<company_slug>_<job_id>`) the rest of the harness uses to key results,
comparisons, and blind pairs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

TARGETS_DIR = Path("shortlist/tailoring_targets")
TARGETS_JSON = TARGETS_DIR / "targets.json"
JDS_DIR = TARGETS_DIR / "jds"


class TargetDiscoveryError(ValueError):
    """Raised when the Top-10 manifest is missing or malformed."""


def _slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", company.lower())


@dataclass(frozen=True)
class Top10Target:
    target_id: str
    job_id: int
    company: str
    role: str
    jd_path: Path
    jd_sha256: str
    base_variant: str
    rank: int


def load_top10_targets(targets_json: Path = TARGETS_JSON, jds_dir: Path = JDS_DIR) -> list[Top10Target]:
    if not targets_json.exists():
        raise TargetDiscoveryError(f"Top-10 manifest not found: {targets_json}")
    raw = json.loads(targets_json.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise TargetDiscoveryError(f"Top-10 manifest must be a non-empty JSON array: {targets_json}")

    targets: list[Top10Target] = []
    seen_ids: set[str] = set()
    for item in raw:
        for key in ("job_id", "company", "exact_title", "jd_filename", "jd_sha256", "base_variant", "rank"):
            if key not in item:
                raise TargetDiscoveryError(f"Top-10 target entry missing required key {key!r}: {item}")
        target_id = f"{_slug(item['company'])}_{item['job_id']}"
        if target_id in seen_ids:
            raise TargetDiscoveryError(f"duplicate derived target_id {target_id!r} in Top-10 manifest")
        seen_ids.add(target_id)
        targets.append(
            Top10Target(
                target_id=target_id,
                job_id=int(item["job_id"]),
                company=str(item["company"]),
                role=str(item["exact_title"]),
                jd_path=jds_dir / str(item["jd_filename"]),
                jd_sha256=str(item["jd_sha256"]),
                base_variant=str(item["base_variant"]),
                rank=int(item["rank"]),
            )
        )
    return sorted(targets, key=lambda t: t.rank)


def get_target(target_id: str, targets_json: Path = TARGETS_JSON, jds_dir: Path = JDS_DIR) -> Top10Target:
    for target in load_top10_targets(targets_json, jds_dir):
        if target.target_id == target_id:
            return target
    raise TargetDiscoveryError(f"unknown target_id: {target_id!r}")
