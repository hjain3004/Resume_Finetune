"""Human feedback contract: a strictly validated YAML review form, an
immutable append-only record store, a read-only summary, and pure
taste-candidate derivation. No model call, no network -- this module
consumes only plain values (job id, fingerprint string, bullet id set,
bullet plain-text mapping)."""
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from src.tailor.artifacts import write_json_atomic

FEEDBACK_SCHEMA = "m8p6.feedback_record.v1"
DEFAULT_FEEDBACK_DIR = Path("data/feedback")


class FeedbackParseError(ValueError):
    """Raised when the YAML document is not a well-formed mapping."""


class FeedbackValidationError(ValueError):
    """Raised when a well-formed mapping fails a content rule."""


class Accept(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"


class WouldSubmit(str, Enum):
    YES = "yes"
    NO = "no"
    NOT_AS_IS = "not_as_is"


class YesNo(str, Enum):
    YES = "yes"
    NO = "no"


class BulletVerdict(str, Enum):
    KEEP = "keep"
    REWORD = "reword"
    REVERT = "revert"


@dataclass(frozen=True)
class BulletFeedback:
    bullet_id: str
    verdict: BulletVerdict
    comment: str


@dataclass(frozen=True)
class UnsupportedClaim:
    bullet_id: str
    quoted_text: str
    why: str


@dataclass(frozen=True)
class FeedbackRecord:
    schema_version: str
    job_id: int
    alignment_fingerprint: str
    reviewed_at: str
    accept: Accept
    would_submit: WouldSubmit
    needs_another_revision: YesNo
    company_alignment: int
    visual_quality: int
    bullet_feedback: tuple[BulletFeedback, ...]
    missing_skills: tuple[str, ...]
    overemphasized_skills: tuple[str, ...]
    unsupported_claims: tuple[UnsupportedClaim, ...]
    free_form: str


_REQUIRED_KEYS = {
    "schema_version", "job_id", "alignment_fingerprint", "reviewed_at",
    "accept", "would_submit", "needs_another_revision",
    "company_alignment", "visual_quality", "bullet_feedback",
    "missing_skills", "overemphasized_skills", "unsupported_claims", "free_form",
}


def build_feedback_form(job_id: int, alignment_fingerprint: str, changed_bullet_ids: tuple[str, ...]) -> str:
    """Emit the YAML form pre-populated with the assessment keys and empty
    values, plus one bullet_feedback entry per changed bullet id, in order."""
    lines = [
        "# Fill in every non-optional field. Leave a comment empty rather than inventing one.",
        f'schema_version: "{FEEDBACK_SCHEMA}"',
        f"job_id: {job_id}",
        f'alignment_fingerprint: "{alignment_fingerprint}"',
        'reviewed_at: ""                    # YYYY-MM-DD',
        "",
        'accept: ""                         # accept | reject',
        'would_submit: ""                   # yes | no | not_as_is',
        'needs_another_revision: ""         # yes | no',
        "",
        'company_alignment: ""              # 1 | 2 | 3   (3 = clearly speaks to this company/product)',
        'visual_quality: ""                 # 1 | 2 | 3   (3 = would hand this to a recruiter as-is)',
        "",
        "bullet_feedback:                   # one entry per changed bullet; comment may be empty",
    ]
    for bullet_id in changed_bullet_ids:
        lines.append(f"  - bullet_id: {bullet_id}")
        lines.append('    verdict: ""                    # keep | reword | revert')
        lines.append('    comment: ""')
    lines += [
        "",
        "missing_skills: []                 # terms the resume should have surfaced and did not",
        "overemphasized_skills: []          # terms given more weight than the evidence supports",
        "unsupported_claims: []             # {bullet_id, quoted_text, why} -- anything misleading",
        "",
        'free_form: ""',
    ]
    return "\n".join(lines) + "\n"


def _enum_or_raise(enum_cls: type[Enum], value: object, field: str) -> Enum:
    if not isinstance(value, str) or value == "":
        raise FeedbackValidationError(f"{field}: must be filled in, got {value!r}")
    try:
        return enum_cls(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_cls)
        raise FeedbackValidationError(f"{field}: {value!r} is not one of {allowed}") from exc


def _score_or_raise(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FeedbackValidationError(f"{field}: must be an integer 1-3, got {value!r}")
    if value not in (1, 2, 3):
        raise FeedbackValidationError(f"{field}: must be 1, 2, or 3, got {value!r}")
    return value


def _date_or_raise(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise FeedbackValidationError(f"{field}: must be a YYYY-MM-DD string, got {value!r}")
    try:
        datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise FeedbackValidationError(f"{field}: not a valid YYYY-MM-DD date: {value!r}") from exc
    return value


def _dedup_terms(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, list):
        raise FeedbackValidationError(f"{field}: must be a list")
    seen: dict[str, str] = {}
    result: list[str] = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise FeedbackValidationError(f"{field}: entries must be non-empty strings, got {item!r}")
        key = " ".join(item.split()).casefold()
        if key in seen:
            raise FeedbackValidationError(f"{field}: duplicate term {item!r} (matches {seen[key]!r})")
        seen[key] = item
        result.append(item)
    return tuple(result)


def parse_feedback_form(
    text: str, *, job_id: int, alignment_fingerprint: str,
    changed_bullet_ids: frozenset[str], bullet_plain_text_by_id: dict[str, str],
) -> FeedbackRecord:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise FeedbackParseError(f"invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise FeedbackParseError("feedback form must be a YAML mapping")
    if set(raw) != _REQUIRED_KEYS:
        missing = _REQUIRED_KEYS - set(raw)
        extra = set(raw) - _REQUIRED_KEYS
        raise FeedbackParseError(f"unexpected field set: missing={sorted(missing)} extra={sorted(extra)}")

    if raw["schema_version"] != FEEDBACK_SCHEMA:
        raise FeedbackValidationError(
            f"schema_version: unknown version {raw['schema_version']!r}, expected {FEEDBACK_SCHEMA!r}"
        )
    if raw["job_id"] != job_id:
        raise FeedbackValidationError(f"job_id: {raw['job_id']!r} does not match the packet's job_id {job_id!r}")
    if raw["alignment_fingerprint"] != alignment_fingerprint:
        raise FeedbackValidationError(
            f"alignment_fingerprint: {raw['alignment_fingerprint']!r} does not match "
            f"the packet's fingerprint {alignment_fingerprint!r}"
        )

    accept = _enum_or_raise(Accept, raw["accept"], "accept")
    would_submit = _enum_or_raise(WouldSubmit, raw["would_submit"], "would_submit")
    needs_another_revision = _enum_or_raise(YesNo, raw["needs_another_revision"], "needs_another_revision")
    company_alignment = _score_or_raise(raw["company_alignment"], "company_alignment")
    visual_quality = _score_or_raise(raw["visual_quality"], "visual_quality")
    reviewed_at = _date_or_raise(raw["reviewed_at"], "reviewed_at")

    bullet_feedback_raw = raw["bullet_feedback"]
    if not isinstance(bullet_feedback_raw, list):
        raise FeedbackValidationError("bullet_feedback: must be a list")
    seen_ids: set[str] = set()
    bullet_feedback: list[BulletFeedback] = []
    for entry in bullet_feedback_raw:
        if not isinstance(entry, dict) or set(entry) != {"bullet_id", "verdict", "comment"}:
            raise FeedbackValidationError("bullet_feedback: each entry needs bullet_id, verdict, comment")
        bullet_id = entry["bullet_id"]
        if bullet_id in seen_ids:
            raise FeedbackValidationError(f"bullet_feedback: duplicate bullet id {bullet_id!r}")
        seen_ids.add(bullet_id)
        if bullet_id not in changed_bullet_ids:
            raise FeedbackValidationError(f"bullet_feedback: {bullet_id!r} is not a changed bullet id")
        verdict = _enum_or_raise(BulletVerdict, entry["verdict"], f"bullet_feedback.{bullet_id}.verdict")
        comment = entry["comment"]
        if not isinstance(comment, str):
            raise FeedbackValidationError(f"bullet_feedback.{bullet_id}.comment: must be a string")
        bullet_feedback.append(BulletFeedback(bullet_id=bullet_id, verdict=verdict, comment=comment))
    missing_ids = changed_bullet_ids - seen_ids
    if missing_ids:
        raise FeedbackValidationError(f"bullet_feedback: missing entries for {sorted(missing_ids)}")

    missing_skills = _dedup_terms(raw["missing_skills"], "missing_skills")
    overemphasized_skills = _dedup_terms(raw["overemphasized_skills"], "overemphasized_skills")

    unsupported_claims_raw = raw["unsupported_claims"]
    if not isinstance(unsupported_claims_raw, list):
        raise FeedbackValidationError("unsupported_claims: must be a list")
    unsupported_claims: list[UnsupportedClaim] = []
    for entry in unsupported_claims_raw:
        if not isinstance(entry, dict) or set(entry) != {"bullet_id", "quoted_text", "why"}:
            raise FeedbackValidationError("unsupported_claims: each entry needs bullet_id, quoted_text, why")
        bullet_id = entry["bullet_id"]
        quoted_text = entry["quoted_text"]
        why = entry["why"]
        if bullet_id not in bullet_plain_text_by_id:
            raise FeedbackValidationError(f"unsupported_claims: {bullet_id!r} is not a known bullet id")
        if not isinstance(quoted_text, str) or quoted_text not in bullet_plain_text_by_id[bullet_id]:
            raise FeedbackValidationError(
                f"unsupported_claims: quoted_text {quoted_text!r} is not an exact "
                f"substring of bullet {bullet_id!r}'s rendered plain text"
            )
        if not isinstance(why, str):
            raise FeedbackValidationError("unsupported_claims: why must be a string")
        unsupported_claims.append(UnsupportedClaim(bullet_id=bullet_id, quoted_text=quoted_text, why=why))

    free_form = raw["free_form"]
    if not isinstance(free_form, str):
        raise FeedbackValidationError("free_form: must be a string")

    return FeedbackRecord(
        schema_version=raw["schema_version"], job_id=job_id, alignment_fingerprint=alignment_fingerprint,
        reviewed_at=reviewed_at, accept=accept, would_submit=would_submit,
        needs_another_revision=needs_another_revision, company_alignment=company_alignment,
        visual_quality=visual_quality, bullet_feedback=tuple(bullet_feedback),
        missing_skills=missing_skills, overemphasized_skills=overemphasized_skills,
        unsupported_claims=tuple(unsupported_claims), free_form=free_form,
    )


def feedback_record_to_dict(record: FeedbackRecord) -> dict[str, object]:
    return {
        "schema_version": record.schema_version,
        "job_id": record.job_id,
        "alignment_fingerprint": record.alignment_fingerprint,
        "reviewed_at": record.reviewed_at,
        "accept": record.accept.value,
        "would_submit": record.would_submit.value,
        "needs_another_revision": record.needs_another_revision.value,
        "company_alignment": record.company_alignment,
        "visual_quality": record.visual_quality,
        "bullet_feedback": [
            {"bullet_id": item.bullet_id, "verdict": item.verdict.value, "comment": item.comment}
            for item in record.bullet_feedback
        ],
        "missing_skills": list(record.missing_skills),
        "overemphasized_skills": list(record.overemphasized_skills),
        "unsupported_claims": [
            {"bullet_id": item.bullet_id, "quoted_text": item.quoted_text, "why": item.why}
            for item in record.unsupported_claims
        ],
        "free_form": record.free_form,
    }


def parse_feedback_record(raw: object) -> FeedbackRecord:
    """Structural reparse of an already-validated, persisted record (no
    packet context to bind against here -- that happened once, at
    parse_feedback_form time)."""
    if not isinstance(raw, dict) or set(raw) != _REQUIRED_KEYS:
        raise FeedbackParseError("feedback record must be a mapping with the exact expected field set")
    if raw["schema_version"] != FEEDBACK_SCHEMA:
        raise FeedbackValidationError(f"schema_version: unknown version {raw['schema_version']!r}")

    accept = _enum_or_raise(Accept, raw["accept"], "accept")
    would_submit = _enum_or_raise(WouldSubmit, raw["would_submit"], "would_submit")
    needs_another_revision = _enum_or_raise(YesNo, raw["needs_another_revision"], "needs_another_revision")
    company_alignment = _score_or_raise(raw["company_alignment"], "company_alignment")
    visual_quality = _score_or_raise(raw["visual_quality"], "visual_quality")
    reviewed_at = _date_or_raise(raw["reviewed_at"], "reviewed_at")

    bullet_feedback = tuple(
        BulletFeedback(bullet_id=item["bullet_id"], verdict=BulletVerdict(item["verdict"]), comment=item["comment"])
        for item in raw["bullet_feedback"]
    )
    unsupported_claims = tuple(
        UnsupportedClaim(bullet_id=item["bullet_id"], quoted_text=item["quoted_text"], why=item["why"])
        for item in raw["unsupported_claims"]
    )
    return FeedbackRecord(
        schema_version=raw["schema_version"], job_id=raw["job_id"],
        alignment_fingerprint=raw["alignment_fingerprint"], reviewed_at=reviewed_at,
        accept=accept, would_submit=would_submit, needs_another_revision=needs_another_revision,
        company_alignment=company_alignment, visual_quality=visual_quality,
        bullet_feedback=bullet_feedback, missing_skills=tuple(raw["missing_skills"]),
        overemphasized_skills=tuple(raw["overemphasized_skills"]),
        unsupported_claims=unsupported_claims, free_form=raw["free_form"],
    )


# ---------------------------------------------------------------------------
# Immutable append-only storage and read-only summary
# ---------------------------------------------------------------------------

class FeedbackOutcomeKind(str, Enum):
    PARSE_FAILURE = "parse_failure"
    VALIDATION_FAILURE = "validation_failure"
    ALREADY_RECORDED = "already_recorded"
    RECORDED = "recorded"


@dataclass(frozen=True)
class FeedbackOutcome:
    kind: FeedbackOutcomeKind
    path: Path | None
    revision: int | None
    error: str | None


@dataclass(frozen=True)
class FeedbackSummary:
    total: int
    accepted: int
    rejected: int
    would_submit_yes: int
    would_submit_no: int
    would_submit_not_as_is: int
    needs_revision: int
    mean_company_alignment: float
    mean_visual_quality: float
    distinct_jobs: int


def _record_key(job_id: int, alignment_fingerprint: str) -> str:
    return f"{job_id}-{alignment_fingerprint[:12]}"


def _existing_revisions(feedback_dir: Path, key: str) -> list[tuple[int, Path]]:
    revisions = []
    for path in feedback_dir.glob(f"{key}-r*.json"):
        suffix = path.stem.rsplit("-r", 1)[-1]
        if suffix.isdigit():
            revisions.append((int(suffix), path))
    revisions.sort()
    return revisions


def store_feedback(record: FeedbackRecord, *, feedback_dir: Path = DEFAULT_FEEDBACK_DIR) -> FeedbackOutcome:
    """Append-only: a second, differing assessment of the same
    (job_id, alignment_fingerprint) key becomes r2, r3, ... An identical
    re-record of the latest revision is an idempotent no-op."""
    feedback_dir = Path(feedback_dir)
    key = _record_key(record.job_id, record.alignment_fingerprint)
    new_dict = feedback_record_to_dict(record)

    revisions = _existing_revisions(feedback_dir, key) if feedback_dir.exists() else []
    if revisions:
        latest_revision, latest_path = revisions[-1]
        latest_dict = json.loads(latest_path.read_text(encoding="utf-8"))
        if latest_dict == new_dict:
            return FeedbackOutcome(FeedbackOutcomeKind.ALREADY_RECORDED, latest_path, latest_revision, None)
        next_revision = latest_revision + 1
    else:
        next_revision = 1

    path = feedback_dir / f"{key}-r{next_revision}.json"
    write_json_atomic(path, new_dict)

    index_line = {
        "schema_version": record.schema_version,
        "job_id": record.job_id,
        "alignment_fingerprint": record.alignment_fingerprint,
        "revision": next_revision,
        "reviewed_at": record.reviewed_at,
        "accept": record.accept.value,
        "would_submit": record.would_submit.value,
        "path": str(path),
    }
    with open(feedback_dir / "index.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(index_line, sort_keys=True))
        handle.write("\n")

    return FeedbackOutcome(FeedbackOutcomeKind.RECORDED, path, next_revision, None)


def load_feedback_index(feedback_dir: Path = DEFAULT_FEEDBACK_DIR) -> tuple[dict[str, object], ...]:
    index_path = Path(feedback_dir) / "index.jsonl"
    if not index_path.exists():
        return ()
    lines = index_path.read_text(encoding="utf-8").splitlines()
    return tuple(json.loads(line) for line in lines if line.strip())


def summarize_feedback(feedback_dir: Path = DEFAULT_FEEDBACK_DIR, *, job_id: int | None = None) -> FeedbackSummary:
    """Read-only: computes statistics over the LATEST revision per
    (job_id, alignment_fingerprint) key -- a superseded revision is history,
    not current signal. Opens each selected record file because
    company_alignment/visual_quality/needs_another_revision are not carried
    in the lightweight index line."""
    entries = load_feedback_index(feedback_dir)
    latest_by_key: dict[tuple[object, object], dict[str, object]] = {}
    for entry in entries:
        key = (entry["job_id"], entry["alignment_fingerprint"])
        current = latest_by_key.get(key)
        if current is None or entry["revision"] > current["revision"]:
            latest_by_key[key] = entry

    selected = list(latest_by_key.values())
    if job_id is not None:
        selected = [entry for entry in selected if entry["job_id"] == job_id]

    records = [parse_feedback_record(json.loads(Path(entry["path"]).read_text(encoding="utf-8"))) for entry in selected]

    total = len(records)
    accepted = sum(1 for item in records if item.accept is Accept.ACCEPT)
    would_submit_yes = sum(1 for item in records if item.would_submit is WouldSubmit.YES)
    would_submit_no = sum(1 for item in records if item.would_submit is WouldSubmit.NO)
    would_submit_not_as_is = sum(1 for item in records if item.would_submit is WouldSubmit.NOT_AS_IS)
    needs_revision = sum(1 for item in records if item.needs_another_revision is YesNo.YES)
    mean_company_alignment = (sum(item.company_alignment for item in records) / total) if total else 0.0
    mean_visual_quality = (sum(item.visual_quality for item in records) / total) if total else 0.0
    distinct_jobs = len({item.job_id for item in records})

    return FeedbackSummary(
        total=total, accepted=accepted, rejected=total - accepted,
        would_submit_yes=would_submit_yes, would_submit_no=would_submit_no,
        would_submit_not_as_is=would_submit_not_as_is, needs_revision=needs_revision,
        mean_company_alignment=mean_company_alignment, mean_visual_quality=mean_visual_quality,
        distinct_jobs=distinct_jobs,
    )


# ---------------------------------------------------------------------------
# Taste-candidate derivation -- pure, writes nothing. M8P-6 derives
# candidates; a human applies them to config/taste.md and
# config/banned_words.txt in M8P-7 (both are PROTECTED prompt inputs).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TasteCandidate:
    date: str
    lesson: str
    mechanically_enforceable: bool
    evidence: str


def derive_taste_candidates(record: FeedbackRecord) -> tuple[TasteCandidate, ...]:
    candidates: list[TasteCandidate] = []

    for item in record.bullet_feedback:
        if item.verdict is BulletVerdict.REWORD and item.comment.strip():
            candidates.append(TasteCandidate(
                date=record.reviewed_at,
                lesson=item.comment.strip(),
                mechanically_enforceable=False,
                evidence=f"reword verdict on bullet {item.bullet_id}",
            ))

    for term in record.overemphasized_skills:
        candidates.append(TasteCandidate(
            date=record.reviewed_at,
            lesson=f"do not overemphasize {term}",
            mechanically_enforceable=True,
            evidence=f"overemphasized_skills: {term}",
        ))

    for claim in record.unsupported_claims:
        candidates.append(TasteCandidate(
            date=record.reviewed_at,
            lesson=f"unsupported claim on bullet {claim.bullet_id}: {claim.why}",
            mechanically_enforceable=False,
            evidence=f"unsupported_claims: {claim.bullet_id}",
        ))

    return tuple(sorted(candidates, key=lambda candidate: (candidate.evidence, candidate.lesson)))
