"""Anchored G2 critic contract: strict typed request/response with no field
capable of carrying resume text (D2, docs/superpowers/specs/
2026-08-24-m8p-4-g2-anchored-critic-design.md). The critic receives a
privacy-minimised, diff-centred projection of an accepted S3Bundle and may
only return {dimension, rule_id, target, quoted_line, explanation} findings
-- there is no field in which a replacement claim could travel.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.render.emphasis import parse_emphasis
from src.tailor.s0 import PositioningPoint, S0Response, s0_response_to_dict
from src.tailor.s3_pipeline import S3Bundle
from src.tailor.s3 import S3Request

G2_REQUEST_MARKER = "{{G2_REQUEST_JSON}}"
MAX_FINDINGS = 8
MAX_ROUNDS = 2
_MAX_DIAGNOSTIC = 200
_MAX_EXPLANATION = 200


class G2ParseError(ValueError):
    """Strict JSON/schema failure."""


class G2SemanticError(ValueError):
    """Validated shape that violates the constrained G2 contract."""


class G2Dimension(str, Enum):
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"
    C4 = "C4"
    C5 = "C5"


class G2TargetKind(str, Enum):
    BULLET = "bullet"
    SKILL_ADDITION = "skill_addition"


RULE_VOCABULARY: dict[G2Dimension, frozenset[str]] = {
    G2Dimension.C1: frozenset({"C1.claim_beyond_profile", "C1.evidence_mismatch"}),
    G2Dimension.C2: frozenset({"C2.register_shift", "C2.metric_replaced_by_adjective"}),
    G2Dimension.C3: frozenset({"C3.keyword_chasing", "C3.edit_not_in_coverage"}),
    G2Dimension.C4: frozenset({"C4.signal_below_fold", "C4.impact_diluted"}),
    G2Dimension.C5: frozenset({"C5.template_phrasing", "C5.generic_bullet"}),
}


@dataclass(frozen=True)
class ChangedBulletView:
    bullet_id: str
    before_plain: str
    after_plain: str
    motivating_terms: tuple[str, ...]
    motivating_jd_quotes: tuple[str, ...]
    rule: str


@dataclass(frozen=True)
class SkillAdditionView:
    category: str
    term: str
    motivating_jd_quote: str


@dataclass(frozen=True)
class UnchangedBulletView:
    bullet_id: str
    plain_text: str


@dataclass(frozen=True)
class G2Finding:
    dimension: G2Dimension
    rule_id: str
    target_kind: G2TargetKind
    target_id: str
    quoted_line: str
    explanation: str


@dataclass(frozen=True)
class G2Request:
    job_id: int
    company: str
    title: str
    context_mode: str
    round_index: int
    positioning: S0Response
    must_have: tuple[tuple[str, str], ...]
    nice_to_have: tuple[tuple[str, str], ...]
    coverage: tuple[tuple[str, str, tuple[str, ...]], ...]
    changed_bullets: tuple[ChangedBulletView, ...]
    skill_additions: tuple[SkillAdditionView, ...]
    unchanged_bullets: tuple[UnchangedBulletView, ...]
    unified_diff: str
    banned_terms: tuple[str, ...]
    taste_lessons: tuple[str, ...]
    prior_findings: tuple[G2Finding, ...]
    alignment_fingerprint: str
    bundle_schema_version: str


@dataclass(frozen=True)
class G2Response:
    scores: tuple[tuple[G2Dimension, int], ...]
    findings: tuple[G2Finding, ...]


# ---------------------------------------------------------------------------
# Small structural helpers (mirror src/tailor/s3.py's pattern).
# ---------------------------------------------------------------------------


def _bounded(value: object) -> str:
    text = repr(value)
    return text if len(text) <= _MAX_DIAGNOSTIC else text[:_MAX_DIAGNOSTIC] + "..."


def _object(value: object, fields: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise G2ParseError(f"{path}: expected object")
    if set(value) != fields:
        raise G2ParseError(f"{path}: unexpected or missing fields")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise G2ParseError(f"{path}: expected nonempty string")
    return value


def _string_array(value: object, path: str, *, empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not empty and not value):
        raise G2ParseError(f"{path}: expected {'empty or ' if empty else ''}string array")
    return tuple(_string(item, f"{path}[]") for item in value)


def _int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise G2ParseError(f"{path}: expected integer")
    return value


# ---------------------------------------------------------------------------
# Load taste lessons (config/taste.md, dated-line format; comments ignored).
# ---------------------------------------------------------------------------


def load_taste_lessons(path) -> tuple[str, ...]:
    from pathlib import Path as _Path

    lessons: list[str] = []
    for line in _Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if len(stripped) < 11 or stripped[4] != "-" or stripped[7] != "-" or stripped[10] != ":":
            continue
        date_part = stripped[:10]
        if not (date_part[:4].isdigit() and date_part[5:7].isdigit() and date_part[8:10].isdigit()):
            continue
        lessons.append(stripped)
    return tuple(lessons)


# ---------------------------------------------------------------------------
# Derive the diff-centred request from an accepted bundle. changed_bullets /
# skill_additions / unchanged_bullets come only from the bundle's
# deterministic change log and hydrated draft -- never from raw model output.
# ---------------------------------------------------------------------------


def _edited_bullet_ids(bundle: S3Bundle) -> set[str]:
    return {
        entry.location.split(":", 1)[1]
        for entry in bundle.change_log
        if entry.location.startswith("bullet:")
    }


def _changed_bullets(bundle: S3Bundle) -> tuple[ChangedBulletView, ...]:
    draft_by_id = {item.bullet_id: item for item in bundle.draft.bullets}
    views: list[ChangedBulletView] = []
    for entry in bundle.change_log:
        if not entry.location.startswith("bullet:"):
            continue
        bullet_id = entry.location.split(":", 1)[1]
        before_plain, _ = parse_emphasis(entry.before)
        views.append(ChangedBulletView(
            bullet_id=bullet_id,
            before_plain=before_plain,
            after_plain=draft_by_id[bullet_id].plain_text,
            motivating_terms=entry.motivating_terms,
            motivating_jd_quotes=entry.motivating_jd_quotes,
            rule=entry.rule,
        ))
    return tuple(views)


def _skill_addition_views(bundle: S3Bundle) -> tuple[SkillAdditionView, ...]:
    views: list[SkillAdditionView] = []
    for entry in bundle.change_log:
        if not entry.location.startswith("skills:"):
            continue
        category = entry.location.split(":", 1)[1]
        quote = entry.motivating_jd_quotes[0] if entry.motivating_jd_quotes else ""
        views.append(SkillAdditionView(category=category, term=entry.after, motivating_jd_quote=quote))
    return tuple(views)


def _unchanged_bullets(bundle: S3Bundle) -> tuple[UnchangedBulletView, ...]:
    edited = _edited_bullet_ids(bundle)
    return tuple(
        UnchangedBulletView(bullet_id=item.bullet_id, plain_text=item.plain_text)
        for item in bundle.draft.bullets
        if item.bullet_id not in edited
    )


def build_g2_request(
    s3_request: S3Request,
    bundle: S3Bundle,
    *,
    round_index: int,
    banned_terms: tuple[str, ...],
    taste_lessons: tuple[str, ...],
    prior_findings: tuple[G2Finding, ...] = (),
) -> G2Request:
    return G2Request(
        job_id=s3_request.job_id,
        company=s3_request.company,
        title=s3_request.title,
        context_mode="jd_only",
        round_index=round_index,
        positioning=s3_request.s0,
        must_have=tuple((item.term, item.quote) for item in s3_request.s1.must_have),
        nice_to_have=tuple((item.term, item.quote) for item in s3_request.s1.nice_to_have),
        coverage=tuple((entry.term, entry.status, entry.bullet_ids) for entry in s3_request.s2.coverage),
        changed_bullets=_changed_bullets(bundle),
        skill_additions=_skill_addition_views(bundle),
        unchanged_bullets=_unchanged_bullets(bundle),
        unified_diff=bundle.unified_diff,
        banned_terms=banned_terms,
        taste_lessons=taste_lessons,
        prior_findings=prior_findings,
        alignment_fingerprint=bundle.alignment_fingerprint,
        bundle_schema_version=bundle.schema_version,
    )


# ---------------------------------------------------------------------------
# Serialization / strict parsing of G2Request.
# ---------------------------------------------------------------------------

_CHANGED_BULLET_KEYS = {"bullet_id", "before_plain", "after_plain", "motivating_terms", "motivating_jd_quotes", "rule"}
_SKILL_ADDITION_KEYS = {"category", "term", "motivating_jd_quote"}
_UNCHANGED_BULLET_KEYS = {"bullet_id", "plain_text"}
_FINDING_KEYS = {"dimension", "rule_id", "target_kind", "target_id", "quoted_line", "explanation"}
_POSITIONING_POINT_KEYS = {"sentence", "profile_ids", "requirement_terms", "jd_quotes"}
_S0_RESPONSE_KEYS = {"context_mode", "points"}

_G2_REQUEST_KEYS = {
    "job_id", "company", "title", "context_mode", "round_index", "positioning",
    "must_have", "nice_to_have", "coverage", "changed_bullets", "skill_additions",
    "unchanged_bullets", "unified_diff", "banned_terms", "taste_lessons",
    "prior_findings", "alignment_fingerprint", "bundle_schema_version",
}


def _changed_bullet_to_dict(item: ChangedBulletView) -> dict[str, object]:
    return {
        "bullet_id": item.bullet_id,
        "before_plain": item.before_plain,
        "after_plain": item.after_plain,
        "motivating_terms": list(item.motivating_terms),
        "motivating_jd_quotes": list(item.motivating_jd_quotes),
        "rule": item.rule,
    }


def _parse_changed_bullet(raw: object, path: str) -> ChangedBulletView:
    obj = _object(raw, _CHANGED_BULLET_KEYS, path)
    return ChangedBulletView(
        bullet_id=_string(obj["bullet_id"], f"{path}.bullet_id"),
        before_plain=_string(obj["before_plain"], f"{path}.before_plain"),
        after_plain=_string(obj["after_plain"], f"{path}.after_plain"),
        motivating_terms=_string_array(obj["motivating_terms"], f"{path}.motivating_terms"),
        motivating_jd_quotes=_string_array(obj["motivating_jd_quotes"], f"{path}.motivating_jd_quotes"),
        rule=_string(obj["rule"], f"{path}.rule"),
    )


def _skill_addition_to_dict(item: SkillAdditionView) -> dict[str, object]:
    return {"category": item.category, "term": item.term, "motivating_jd_quote": item.motivating_jd_quote}


def _parse_skill_addition(raw: object, path: str) -> SkillAdditionView:
    obj = _object(raw, _SKILL_ADDITION_KEYS, path)
    return SkillAdditionView(
        category=_string(obj["category"], f"{path}.category"),
        term=_string(obj["term"], f"{path}.term"),
        motivating_jd_quote=_string(obj["motivating_jd_quote"], f"{path}.motivating_jd_quote"),
    )


def _unchanged_bullet_to_dict(item: UnchangedBulletView) -> dict[str, object]:
    return {"bullet_id": item.bullet_id, "plain_text": item.plain_text}


def _parse_unchanged_bullet(raw: object, path: str) -> UnchangedBulletView:
    obj = _object(raw, _UNCHANGED_BULLET_KEYS, path)
    return UnchangedBulletView(
        bullet_id=_string(obj["bullet_id"], f"{path}.bullet_id"),
        plain_text=_string(obj["plain_text"], f"{path}.plain_text"),
    )


def _finding_to_dict(item: G2Finding) -> dict[str, object]:
    return {
        "dimension": item.dimension.value,
        "rule_id": item.rule_id,
        "target_kind": item.target_kind.value,
        "target_id": item.target_id,
        "quoted_line": item.quoted_line,
        "explanation": item.explanation,
    }


def _parse_finding_structural(raw: object, path: str) -> G2Finding:
    """Structural-only finding parse: shape, enum membership, and the
    dimension/rule_id vocabulary binding. No request context is needed or
    consulted here -- semantic anchoring (target scope, quote anchoring,
    score agreement) happens in parse_g2_response, which has the request."""
    obj = _object(raw, _FINDING_KEYS, path)
    dimension_raw = obj["dimension"]
    if dimension_raw not in {item.value for item in G2Dimension}:
        raise G2ParseError(f"{path}.dimension: invalid dimension")
    dimension = G2Dimension(dimension_raw)
    rule_id = _string(obj["rule_id"], f"{path}.rule_id")
    target_kind_raw = obj["target_kind"]
    if target_kind_raw not in {item.value for item in G2TargetKind}:
        raise G2ParseError(f"{path}.target_kind: invalid target_kind")
    target_id = _string(obj["target_id"], f"{path}.target_id")
    quoted_line = _string(obj["quoted_line"], f"{path}.quoted_line")
    explanation = _string(obj["explanation"], f"{path}.explanation")
    if len(explanation) > _MAX_EXPLANATION:
        raise G2ParseError(f"{path}.explanation: exceeds {_MAX_EXPLANATION} characters")
    return G2Finding(dimension, rule_id, G2TargetKind(target_kind_raw), target_id, quoted_line, explanation)


def _parse_finding_list(raw: object, path: str) -> tuple[G2Finding, ...]:
    if not isinstance(raw, list):
        raise G2ParseError(f"{path}: expected array")
    findings: list[G2Finding] = []
    seen: set[tuple[str, str, str]] = set()
    for index, item in enumerate(raw):
        finding = _parse_finding_structural(item, f"{path}[{index}]")
        key = (finding.dimension.value, finding.target_id, finding.quoted_line)
        if key in seen:
            raise G2ParseError(f"{path}[{index}]: duplicate (dimension, target_id, quoted_line)")
        seen.add(key)
        findings.append(finding)
    return tuple(findings)


def _s0_response_to_dict(response: S0Response) -> dict[str, object]:
    return s0_response_to_dict(response)


def _parse_s0_response_structural(raw: object, path: str) -> S0Response:
    obj = _object(raw, _S0_RESPONSE_KEYS, path)
    if obj["context_mode"] != "jd_only":
        raise G2SemanticError(f"{path}.context_mode: must be jd_only")
    if not isinstance(obj["points"], list):
        raise G2ParseError(f"{path}.points: expected array")
    points: list[PositioningPoint] = []
    for index, item in enumerate(obj["points"]):
        point_path = f"{path}.points[{index}]"
        point_obj = _object(item, _POSITIONING_POINT_KEYS, point_path)
        points.append(PositioningPoint(
            sentence=_string(point_obj["sentence"], f"{point_path}.sentence"),
            profile_ids=_string_array(point_obj["profile_ids"], f"{point_path}.profile_ids", empty=True),
            requirement_terms=_string_array(point_obj["requirement_terms"], f"{point_path}.requirement_terms", empty=True),
            jd_quotes=_string_array(point_obj["jd_quotes"], f"{point_path}.jd_quotes", empty=True),
        ))
    return S0Response("jd_only", tuple(points))


def g2_request_to_dict(request: G2Request) -> dict[str, object]:
    return {
        "job_id": request.job_id,
        "company": request.company,
        "title": request.title,
        "context_mode": request.context_mode,
        "round_index": request.round_index,
        "positioning": _s0_response_to_dict(request.positioning),
        "must_have": [[term, quote] for term, quote in request.must_have],
        "nice_to_have": [[term, quote] for term, quote in request.nice_to_have],
        "coverage": [[term, status, list(bullet_ids)] for term, status, bullet_ids in request.coverage],
        "changed_bullets": [_changed_bullet_to_dict(item) for item in request.changed_bullets],
        "skill_additions": [_skill_addition_to_dict(item) for item in request.skill_additions],
        "unchanged_bullets": [_unchanged_bullet_to_dict(item) for item in request.unchanged_bullets],
        "unified_diff": request.unified_diff,
        "banned_terms": list(request.banned_terms),
        "taste_lessons": list(request.taste_lessons),
        "prior_findings": [_finding_to_dict(item) for item in request.prior_findings],
        "alignment_fingerprint": request.alignment_fingerprint,
        "bundle_schema_version": request.bundle_schema_version,
    }


def parse_g2_request(raw: object) -> G2Request:
    obj = _object(raw, _G2_REQUEST_KEYS, "$")
    job_id = obj["job_id"]
    if isinstance(job_id, bool) or not isinstance(job_id, int):
        raise G2ParseError("$.job_id: expected integer")
    company = _string(obj["company"], "$.company")
    title = _string(obj["title"], "$.title")
    if obj["context_mode"] != "jd_only":
        raise G2SemanticError("$.context_mode: must be jd_only")
    round_index = _int(obj["round_index"], "$.round_index")
    if round_index not in (1, 2):
        raise G2SemanticError("$.round_index: must be 1 or 2")
    positioning = _parse_s0_response_structural(obj["positioning"], "$.positioning")

    def _pair_list(value: object, path: str) -> tuple[tuple[str, str], ...]:
        if not isinstance(value, list):
            raise G2ParseError(f"{path}: expected array")
        pairs = []
        for index, item in enumerate(value):
            if not isinstance(item, list) or len(item) != 2:
                raise G2ParseError(f"{path}[{index}]: expected [term, quote] pair")
            pairs.append((_string(item[0], f"{path}[{index}][0]"), _string(item[1], f"{path}[{index}][1]")))
        return tuple(pairs)

    must_have = _pair_list(obj["must_have"], "$.must_have")
    nice_to_have = _pair_list(obj["nice_to_have"], "$.nice_to_have")

    if not isinstance(obj["coverage"], list):
        raise G2ParseError("$.coverage: expected array")
    coverage = []
    for index, item in enumerate(obj["coverage"]):
        path = f"$.coverage[{index}]"
        if not isinstance(item, list) or len(item) != 3:
            raise G2ParseError(f"{path}: expected [term, status, bullet_ids] triple")
        term = _string(item[0], f"{path}[0]")
        status = _string(item[1], f"{path}[1]")
        bullet_ids = _string_array(item[2], f"{path}[2]", empty=True)
        coverage.append((term, status, bullet_ids))
    coverage = tuple(coverage)

    if not isinstance(obj["changed_bullets"], list):
        raise G2ParseError("$.changed_bullets: expected array")
    changed_bullets = tuple(
        _parse_changed_bullet(item, f"$.changed_bullets[{index}]") for index, item in enumerate(obj["changed_bullets"])
    )
    if not isinstance(obj["skill_additions"], list):
        raise G2ParseError("$.skill_additions: expected array")
    skill_additions = tuple(
        _parse_skill_addition(item, f"$.skill_additions[{index}]") for index, item in enumerate(obj["skill_additions"])
    )
    if not isinstance(obj["unchanged_bullets"], list):
        raise G2ParseError("$.unchanged_bullets: expected array")
    unchanged_bullets = tuple(
        _parse_unchanged_bullet(item, f"$.unchanged_bullets[{index}]") for index, item in enumerate(obj["unchanged_bullets"])
    )
    unified_diff = obj["unified_diff"]
    if not isinstance(unified_diff, str):
        raise G2ParseError("$.unified_diff: expected string")
    banned_terms = _string_array(obj["banned_terms"], "$.banned_terms", empty=True)
    taste_lessons = _string_array(obj["taste_lessons"], "$.taste_lessons", empty=True)
    prior_findings = _parse_finding_list(obj["prior_findings"], "$.prior_findings")
    fingerprint = obj["alignment_fingerprint"]
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise G2ParseError("$.alignment_fingerprint: invalid fingerprint")
    bundle_schema_version = _string(obj["bundle_schema_version"], "$.bundle_schema_version")

    return G2Request(
        job_id=job_id,
        company=company,
        title=title,
        context_mode="jd_only",
        round_index=round_index,
        positioning=positioning,
        must_have=must_have,
        nice_to_have=nice_to_have,
        coverage=coverage,
        changed_bullets=changed_bullets,
        skill_additions=skill_additions,
        unchanged_bullets=unchanged_bullets,
        unified_diff=unified_diff,
        banned_terms=banned_terms,
        taste_lessons=taste_lessons,
        prior_findings=prior_findings,
        alignment_fingerprint=fingerprint,
        bundle_schema_version=bundle_schema_version,
    )


def build_g2_prompt(template: str, request: G2Request) -> str:
    if template.count(G2_REQUEST_MARKER) != 1:
        raise ValueError(f"G2 prompt template must contain {G2_REQUEST_MARKER!r} exactly once")
    return template.replace(G2_REQUEST_MARKER, json.dumps(g2_request_to_dict(request), sort_keys=True, indent=2))


# ---------------------------------------------------------------------------
# Strict G2 response parsing.
# ---------------------------------------------------------------------------

_G2_RESPONSE_KEYS = {"scores", "findings"}
_SCORE_KEYS = {item.value for item in G2Dimension}


def _parse_scores(raw: object, path: str) -> tuple[tuple[G2Dimension, int], ...]:
    obj = _object(raw, _SCORE_KEYS, path)
    result = []
    for dimension in G2Dimension:
        value = obj[dimension.value]
        if isinstance(value, bool) or not isinstance(value, int):
            raise G2ParseError(f"{path}.{dimension.value}: expected integer")
        if value not in (1, 2, 3):
            raise G2ParseError(f"{path}.{dimension.value}: expected 1, 2, or 3")
        result.append((dimension, value))
    return tuple(result)


def parse_g2_response(raw_output: str, request: G2Request) -> G2Response:
    try:
        value = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise G2ParseError(f"$: invalid JSON: {_bounded(exc)}") from exc
    obj = _object(value, _G2_RESPONSE_KEYS, "$")
    scores = _parse_scores(obj["scores"], "$.scores")
    raw_findings = obj["findings"]
    if not isinstance(raw_findings, list):
        raise G2ParseError("$.findings: expected array")
    if len(raw_findings) > MAX_FINDINGS:
        raise G2ParseError(f"$.findings: at most {MAX_FINDINGS} findings")
    findings = _parse_finding_list(raw_findings, "$.findings")

    changed_by_id = {item.bullet_id: item for item in request.changed_bullets}
    skill_keys = {f"{item.category}:{item.term}": item for item in request.skill_additions}

    for index, finding in enumerate(findings):
        path = f"$.findings[{index}]"
        if finding.rule_id not in RULE_VOCABULARY[finding.dimension]:
            raise G2SemanticError(f"{path}.rule_id: {_bounded(finding.rule_id)} does not belong to {finding.dimension.value}")
        if finding.target_kind is G2TargetKind.BULLET:
            target = changed_by_id.get(finding.target_id)
            if target is None:
                raise G2SemanticError(f"{path}.target_id: {_bounded(finding.target_id)} is out of scope (not a changed bullet)")
            if finding.quoted_line not in target.after_plain:
                raise G2SemanticError(f"{path}.quoted_line: not an exact substring of the target bullet's after_plain")
        else:
            target = skill_keys.get(finding.target_id)
            if target is None:
                raise G2SemanticError(f"{path}.target_id: {_bounded(finding.target_id)} is out of scope (not an accepted skill addition)")
            if finding.quoted_line != target.term:
                raise G2SemanticError(f"{path}.quoted_line: must exactly equal the added term")

    score_map = dict(scores)
    findings_by_dimension: dict[G2Dimension, list[G2Finding]] = {dimension: [] for dimension in G2Dimension}
    for finding in findings:
        findings_by_dimension[finding.dimension].append(finding)

    for dimension, score in scores:
        if score < 3 and not findings_by_dimension[dimension]:
            raise G2SemanticError(f"$.scores.{dimension.value}: scored below 3 with no finding")
        if score == 3 and findings_by_dimension[dimension]:
            raise G2SemanticError(f"$.findings: {dimension.value} carries a finding but is scored 3")

    return G2Response(scores, findings)


def g2_response_to_dict(response: G2Response) -> dict[str, object]:
    return {
        "scores": {dimension.value: score for dimension, score in response.scores},
        "findings": [_finding_to_dict(item) for item in response.findings],
    }


# ---------------------------------------------------------------------------
# Verdict rule (TAILORING_METHODOLOGY.md §4, verbatim):
# PASS iff C1 == 3 and min(C2..C5) >= 2.
# ---------------------------------------------------------------------------


class G2Verdict(str, Enum):
    PASS = "pass"
    REVISE = "revise"
    OPEN_FLAGS = "open_flags"


def evaluate_verdict(response: G2Response, *, round_index: int, max_rounds: int = MAX_ROUNDS) -> G2Verdict:
    scores = dict(response.scores)
    passed = scores[G2Dimension.C1] == 3 and min(
        scores[dimension] for dimension in (G2Dimension.C2, G2Dimension.C3, G2Dimension.C4, G2Dimension.C5)
    ) >= 2
    if passed:
        return G2Verdict.PASS
    return G2Verdict.OPEN_FLAGS if round_index >= max_rounds else G2Verdict.REVISE


def unresolved_findings(
    prior: tuple[G2Finding, ...], revised_text_by_target: dict[str, str]
) -> tuple[G2Finding, ...]:
    """Prior findings whose quoted_line is still present in the revised text
    for their target. A target absent from `revised_text_by_target` (e.g. a
    finding on a skill addition, or a target that no longer exists) counts
    as resolved -- there is nothing left to quote."""
    still: list[G2Finding] = []
    for finding in prior:
        text = revised_text_by_target.get(finding.target_id)
        if text is not None and finding.quoted_line in text:
            still.append(finding)
    return tuple(still)
