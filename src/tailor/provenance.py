"""Provenance contracts and boundary validation for JD inputs (M8N-0 / M9D target).

Distinguishes:
- verified official/ATS JD ('ats')
- user-attested official copy ('user_attested')
- aggregator summary ('aggregator')
- unverified manual text ('unverified')

Only 'ats' and 'user_attested' are permitted to enter tailoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import urllib.parse

from src.tailor.artifacts import write_json_atomic

JD_PROVENANCE_SCHEMA = "jd_provenance.v1"

_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")

KNOWN_AGGREGATOR_DOMAINS = frozenset({
    "jobright.ai",
    "jobright.com",
    "simplify.jobs",
    "linkedin.com",
    "www.linkedin.com",
    "indeed.com",
    "www.indeed.com",
    "glassdoor.com",
    "www.glassdoor.com",
    "ziprecruiter.com",
    "www.ziprecruiter.com",
    "levels.fyi",
    "www.levels.fyi",
    "joinhandshake.com",
    "handshake.com",
    "monster.com",
    "www.monster.com",
    "careerbuilder.com",
    "www.careerbuilder.com",
    "dice.com",
    "www.dice.com",
    "wellfound.com",
    "angel.co",
    "builtin.com",
    "untapped.io",
    "wayup.com",
})


class JDQuality(str, Enum):
    ATS = "ats"
    USER_ATTESTED = "user_attested"
    AGGREGATOR = "aggregator"
    UNVERIFIED = "unverified"


TAILORABLE_JD_QUALITIES = frozenset({JDQuality.ATS.value, JDQuality.USER_ATTESTED.value})


class ProvenanceError(ValueError):
    """Raised when JD provenance fails verification."""


@dataclass(frozen=True)
class AttestationMetadata:
    attested_at: str
    attester: str
    source_url: str
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "attested_at": self.attested_at,
            "attester": self.attester,
            "source_url": self.source_url,
        }
        if self.notes is not None:
            d["notes"] = self.notes
        return d


@dataclass(frozen=True)
class JDProvenance:
    schema_version: str
    company: str
    title: str
    source_url: str
    source_type: str
    jd_quality: str
    jd_sha256: str
    job_id: int | None = None
    ats_url: str | None = None
    attestation: AttestationMetadata | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "company": self.company,
            "title": self.title,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "jd_quality": self.jd_quality,
            "jd_sha256": self.jd_sha256,
            "job_id": self.job_id,
            "ats_url": self.ats_url,
            "attestation": self.attestation.to_dict() if self.attestation is not None else None,
        }


def compute_jd_sha256(jd_bytes: bytes) -> str:
    return hashlib.sha256(jd_bytes).hexdigest()


def is_aggregator_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    for agg in KNOWN_AGGREGATOR_DOMAINS:
        if hostname == agg or hostname.endswith("." + agg):
            return True
    return False


def provenance_path_for_jd(jd_path: Path | str) -> Path:
    p = Path(jd_path)
    return p.parent / f"{p.name}.provenance.json"


def find_provenance_sidecar(jd_path: Path | str) -> Path | None:
    p = Path(jd_path)
    candidates = [
        p.parent / f"{p.name}.provenance.json",
        p.with_suffix(".provenance.json"),
    ]
    if p.suffix.lower() == ".txt":
        candidates.append(p.parent / f"{p.stem}.provenance.json")
    seen: set[Path] = set()
    for cand in candidates:
        if cand not in seen:
            seen.add(cand)
            if cand.is_file():
                return cand
    return None


_REQUIRED_PROVENANCE_KEYS = {
    "schema_version",
    "company",
    "title",
    "source_url",
    "source_type",
    "jd_quality",
    "jd_sha256",
}
_OPTIONAL_PROVENANCE_KEYS = {"job_id", "ats_url", "attestation"}
_ALL_PROVENANCE_KEYS = _REQUIRED_PROVENANCE_KEYS | _OPTIONAL_PROVENANCE_KEYS


def parse_provenance_dict(raw: dict[str, Any]) -> JDProvenance:
    if not isinstance(raw, dict):
        raise ProvenanceError("provenance payload must be a JSON object")
    extra_keys = set(raw.keys()) - _ALL_PROVENANCE_KEYS
    if extra_keys:
        raise ProvenanceError(f"unrecognized keys in provenance: {sorted(extra_keys)}")
    missing_keys = _REQUIRED_PROVENANCE_KEYS - set(raw.keys())
    if missing_keys:
        raise ProvenanceError(f"missing required provenance keys: {sorted(missing_keys)}")

    if raw["schema_version"] != JD_PROVENANCE_SCHEMA:
        raise ProvenanceError(
            f"unsupported provenance schema version {raw['schema_version']!r}; expected {JD_PROVENANCE_SCHEMA!r}"
        )

    for field in ("company", "title", "source_url", "source_type", "jd_quality", "jd_sha256"):
        val = raw[field]
        if not isinstance(val, str) or not val.strip():
            raise ProvenanceError(f"field {field!r} must be a non-empty string")

    sha = raw["jd_sha256"].lower().strip()
    if not _HEX_64_RE.match(sha):
        raise ProvenanceError(f"invalid jd_sha256 format: {raw['jd_sha256']!r}")

    job_id = raw.get("job_id")
    if job_id is not None and (isinstance(job_id, bool) or not isinstance(job_id, int)):
        raise ProvenanceError(f"job_id must be an integer or null, got {type(job_id).__name__}")

    ats_url = raw.get("ats_url")
    if ats_url is not None and not isinstance(ats_url, str):
        raise ProvenanceError("ats_url must be a string or null")

    attestation_raw = raw.get("attestation")
    attestation = None
    if attestation_raw is not None:
        if not isinstance(attestation_raw, dict):
            raise ProvenanceError("attestation must be a dictionary or null")
        att_req = {"attested_at", "attester", "source_url"}
        if not att_req.issubset(attestation_raw.keys()):
            raise ProvenanceError(f"attestation missing required keys: {sorted(att_req - set(attestation_raw.keys()))}")
        notes = attestation_raw.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise ProvenanceError("attestation notes must be a string or null")
        attestation = AttestationMetadata(
            attested_at=str(attestation_raw["attested_at"]),
            attester=str(attestation_raw["attester"]),
            source_url=str(attestation_raw["source_url"]),
            notes=notes,
        )

    return JDProvenance(
        schema_version=raw["schema_version"],
        company=raw["company"].strip(),
        title=raw["title"].strip(),
        source_url=raw["source_url"].strip(),
        source_type=raw["source_type"].strip(),
        jd_quality=raw["jd_quality"].strip(),
        jd_sha256=sha,
        job_id=job_id,
        ats_url=ats_url.strip() if ats_url else None,
        attestation=attestation,
    )


def create_user_attestation(
    jd_path: Path | str,
    *,
    company: str,
    title: str,
    source_url: str,
    notes: str | None = None,
    out_path: Path | str | None = None,
) -> Path:
    jd_p = Path(jd_path)
    if not jd_p.is_file():
        raise ProvenanceError(f"JD file not found: {jd_p}")

    jd_bytes = jd_p.read_bytes()
    if not jd_bytes:
        raise ProvenanceError(f"JD file is empty: {jd_p}")

    url_str = source_url.strip()
    parsed = urllib.parse.urlparse(url_str)
    if not parsed.scheme or not parsed.netloc:
        raise ProvenanceError(f"invalid source URL: {source_url!r}")
    if is_aggregator_url(url_str):
        raise ProvenanceError(
            f"cannot attest an aggregator URL ({parsed.hostname}) as an official employer posting; "
            "user attestation requires an official company or ATS posting URL"
        )

    company_clean = company.strip()
    title_clean = title.strip()
    if not company_clean:
        raise ProvenanceError("company must be non-empty")
    if not title_clean:
        raise ProvenanceError("title must be non-empty")

    jd_sha256 = compute_jd_sha256(jd_bytes)
    now_iso = datetime.now(timezone.utc).isoformat()

    provenance = JDProvenance(
        schema_version=JD_PROVENANCE_SCHEMA,
        company=company_clean,
        title=title_clean,
        source_url=url_str,
        source_type=JDQuality.USER_ATTESTED.value,
        jd_quality=JDQuality.USER_ATTESTED.value,
        jd_sha256=jd_sha256,
        job_id=None,
        ats_url=url_str,
        attestation=AttestationMetadata(
            attested_at=now_iso,
            attester="user",
            source_url=url_str,
            notes=notes.strip() if notes else None,
        ),
    )

    dest = Path(out_path) if out_path else provenance_path_for_jd(jd_p)
    write_json_atomic(dest, provenance.to_dict())
    return dest


def _norm_str(s: str) -> str:
    return " ".join(s.casefold().split())


def validate_provenance_for_tailoring(
    jd_path: Path | str,
    *,
    company: str,
    title: str,
    db_conn: Any | None = None,
    sidecar_path: Path | str | None = None,
) -> JDProvenance:
    jd_p = Path(jd_path)
    if not jd_p.is_file():
        raise ProvenanceError(f"JD file not found: {jd_p}")

    jd_bytes = jd_p.read_bytes()
    if not jd_bytes:
        raise ProvenanceError(f"JD file is empty: {jd_p}")

    actual_hash = compute_jd_sha256(jd_bytes)

    # 1. Missing provenance
    sidecar_file = Path(sidecar_path) if sidecar_path else find_provenance_sidecar(jd_p)
    if sidecar_file is None or not sidecar_file.is_file():
        raise ProvenanceError(
            f"missing provenance sidecar for {jd_p}. File-fed tailoring requires a verified ATS or "
            f"user-attested provenance sidecar ({jd_p.name}.provenance.json). "
            "Use 'python -m scripts.tailor_now attest' for user-attested official copies."
        )

    # 2. Malformed provenance
    try:
        raw_data = json.loads(sidecar_file.read_text(encoding="utf-8"))
        prov = parse_provenance_dict(raw_data)
    except Exception as exc:
        if isinstance(exc, ProvenanceError):
            raise
        raise ProvenanceError(f"malformed provenance sidecar {sidecar_file}: {exc}") from exc

    # 3. Hash mismatch
    if prov.jd_sha256 != actual_hash:
        raise ProvenanceError(
            f"jd hash mismatch: computed {actual_hash} != sidecar {prov.jd_sha256}. "
            "The JD text has been modified since provenance was created. Re-attest or re-export required."
        )

    # 4. Company / title mismatch
    if _norm_str(prov.company) != _norm_str(company) or _norm_str(prov.title) != _norm_str(title):
        raise ProvenanceError(
            f"provenance company/title mismatch: sidecar has company={prov.company!r}, title={prov.title!r} "
            f"but run requested company={company!r}, title={title!r}"
        )

    # 5. Aggregator quality
    if prov.jd_quality == JDQuality.AGGREGATOR.value:
        raise ProvenanceError(
            f"cannot tailor aggregator-quality JD ({jd_p}): tailoring requires an official ATS JD "
            "or a user-attested official copy. Aggregator summaries are not suitable for tailoring."
        )

    # 6. Unverified quality
    if prov.jd_quality not in TAILORABLE_JD_QUALITIES:
        raise ProvenanceError(
            f"cannot tailor unverified JD ({jd_p}) with quality {prov.jd_quality!r}. "
            f"Only qualities {sorted(TAILORABLE_JD_QUALITIES)} may proceed to tailoring."
        )

    # 7. Database metadata disagreement
    if prov.job_id is not None and db_conn is not None:
        from src import db
        db_row = db.job_row_for_export(db_conn, prov.job_id)
        if db_row is not None:
            if db_row["jd_quality"] != prov.jd_quality:
                raise ProvenanceError(
                    f"database metadata disagreement for job {prov.job_id}: "
                    f"DB has jd_quality={db_row['jd_quality']!r} while provenance sidecar claims {prov.jd_quality!r}"
                )
            if _norm_str(db_row["company"]) != _norm_str(prov.company):
                raise ProvenanceError(
                    f"database metadata disagreement for job {prov.job_id}: "
                    f"DB company {db_row['company']!r} != provenance company {prov.company!r}"
                )
            if _norm_str(db_row["title"]) != _norm_str(prov.title):
                raise ProvenanceError(
                    f"database metadata disagreement for job {prov.job_id}: "
                    f"DB title {db_row['title']!r} != provenance title {prov.title!r}"
                )

    return prov
