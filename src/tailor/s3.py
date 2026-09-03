"""Strict constrained S3 alignment contract and deterministic edit validation."""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
import difflib
from enum import Enum
from typing import Any

from src.render.emphasis import EmphasisError, parse_emphasis
from src.tailor.alignment_view import AlignmentView, alignment_to_dict, parse_alignment
from src.tailor.profile_views import (
    PositioningEntry,
    PositioningView,
    SelectionBullet,
    SelectionCatalog,
    SelectionEntry,
    SelectionVariant,
)
from src.tailor.s0 import (
    S0Request,
    S0Response,
    parse_s0_response,
    s0_response_to_dict,
)
from src.tailor.s1 import (
    S1Response,
    parse_s1_response_dict,
    s1_response_to_dict,
)
from src.tailor.s2 import (
    S2Request,
    S2Response,
    build_s2_request,
    parse_s2_response,
    s2_response_to_dict,
)

S3_REQUEST_MARKER = "{{S3_REQUEST_JSON}}"


_MAX_DIAGNOSTIC = 200
_NUMBER_RE = re.compile(r"(?<!\w)[~+-]?(?:\d[\d,]*(?:\.\d+)?)(?:%|x|\+)?(?!\w)")
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#.\-/]*")
_FUNCTION_WORDS = frozenset(
    "a an and as at by for from in into of on or the to via with within across"
    " can does do is are was were be been being that this these those than then"
    " using used use into their its our your more less new one two three"
    .split()
)


class S3ParseError(ValueError):
    """Strict JSON/schema failure."""


class S3SemanticError(ValueError):
    """Validated shape that violates the constrained S3 contract."""


class S3HydrationError(ValueError):
    """Reserved for deterministic hydration failures in Task 3."""


class S3EditRule(str, Enum):
    TERMINOLOGY_MIRRORING = "terminology_mirroring"
    XYZ_TIGHTENING = "xyz_tightening"


@dataclass(frozen=True)
class BulletEdit:
    bullet_id: str
    after: str
    motivating_terms: tuple[str, ...]
    rule: S3EditRule


@dataclass(frozen=True)
class SkillAddition:
    category: str
    term: str
    motivating_term: str


@dataclass(frozen=True)
class S3Request:
    job_id: int
    company: str
    title: str
    context_mode: str
    s1: S1Response
    s0: S0Response
    s2: S2Response
    alignment: AlignmentView


@dataclass(frozen=True)
class S3Response:
    bullet_edits: tuple[BulletEdit, ...]
    skill_additions: tuple[SkillAddition, ...]


@dataclass(frozen=True)
class DraftBullet:
    bullet_id: str
    owner_id: str
    owner_kind: str
    text: str
    plain_text: str
    emphasis: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class TailoredDraft:
    job_id: int
    company: str
    title: str
    base_variant: str
    project_ids: tuple[str, ...]
    experience_ids: tuple[str, ...]
    bullets: tuple[DraftBullet, ...]
    skills: tuple[tuple[str, tuple[str, ...]], ...]
    alignment_fingerprint: str


@dataclass(frozen=True)
class ChangeEntry:
    location: str
    before: str
    after: str
    motivating_terms: tuple[str, ...]
    motivating_jd_quotes: tuple[str, ...]
    rule: str


@dataclass(frozen=True)
class EditBudget:
    changed_tokens: int
    base_tokens: int
    ratio: float


def build_s3_prompt(template: str, request: S3Request) -> str:
    if template.count(S3_REQUEST_MARKER) != 1:
        raise ValueError(f"S3 prompt template must contain {S3_REQUEST_MARKER!r} exactly once")
    return template.replace(S3_REQUEST_MARKER, json.dumps(s3_request_to_dict(request), sort_keys=True, indent=2))


def _bounded(value: object) -> str:
    text = repr(value)
    return text if len(text) <= _MAX_DIAGNOSTIC else text[:_MAX_DIAGNOSTIC] + "..."


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _object(value: object, fields: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise S3ParseError(f"{path}: expected object")
    if set(value) != fields:
        raise S3ParseError(f"{path}: unexpected or missing fields")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise S3ParseError(f"{path}: expected nonempty string")
    return value


def _string_array(value: object, path: str, *, empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not empty and not value):
        raise S3ParseError(f"{path}: expected {'empty or ' if empty else ''}string array")
    result = tuple(_string(item, f"{path}[]") for item in value)
    if len({_normalize(item) for item in result}) != len(result):
        raise S3ParseError(f"{path}: duplicate values")
    return result


def build_s3_request(
    job_id: int,
    company: str,
    title: str,
    s1: S1Response,
    s0: S0Response,
    s2: S2Response,
    alignment: AlignmentView,
) -> S3Request:
    return S3Request(job_id, company, title, "jd_only", s1, s0, s2, alignment)


def s3_request_to_dict(request: S3Request) -> dict[str, object]:
    return {
        "job_id": request.job_id,
        "company": request.company,
        "title": request.title,
        "context_mode": request.context_mode,
        "s1": s1_response_to_dict(request.s1),
        "s0": s0_response_to_dict(request.s0),
        "s2": s2_response_to_dict(request.s2),
        "alignment": alignment_to_dict(request.alignment),
    }


def _s1_from_dict(raw: object) -> S1Response:
    if not isinstance(raw, dict):
        raise S3ParseError("$.s1: expected object")
    quotes: list[str] = []
    for key in ("must_have", "nice_to_have", "responsibilities_summary"):
        items = raw.get(key, [])
        if isinstance(items, list):
            quotes.extend(item["quote"] for item in items if isinstance(item, dict) and isinstance(item.get("quote"), str))
    for key in ("seniority_signals", "disqualifiers"):
        items = raw.get(key, [])
        if isinstance(items, list):
            quotes.extend(item for item in items if isinstance(item, str))
    context = raw.get("company_context")
    if isinstance(context, dict):
        quotes.extend(item["quote"] for item in context.values() if isinstance(item, dict) and isinstance(item.get("quote"), str))
    try:
        return parse_s1_response_dict(raw, " ".join(quotes))
    except Exception as exc:
        raise S3ParseError(f"$.s1: invalid response: {_bounded(exc)}") from exc


def _synthetic_s2_request(
    job_id: int,
    company: str,
    title: str,
    s1: S1Response,
    s0: S0Response,
    s2_raw: dict[str, Any],
    alignment: AlignmentView,
) -> S2Request:
    projects = tuple(SelectionEntry(item, "project", item, (), ()) for item in alignment.project_ids)
    experiences = tuple(SelectionEntry(item, "experience", item, (), ()) for item in alignment.experience_ids)
    bullets = tuple(
        SelectionBullet(item.bullet_id, item.owner_id, item.owner_kind, 1, item.claim_type, item.keywords_hit)
        for item in alignment.bullets
    )
    exp_order: list[str] = []
    counts: list[tuple[str, int]] = []
    for item in alignment.bullets:
        if item.owner_kind != "experience":
            continue
        if not exp_order or exp_order[-1] != item.owner_id:
            exp_order.append(item.owner_id)
            counts.append((item.owner_id, 0))
        counts[-1] = (item.owner_id, counts[-1][1] + 1)
    variant = SelectionVariant(alignment.base_variant, alignment.project_ids, tuple(item.bullet_id for item in alignment.bullets), tuple(exp_order), tuple(counts))
    catalog = SelectionCatalog(alignment.base_variant, (variant,), projects, experiences, bullets, alignment.do_not_claim, ())
    try:
        return build_s2_request(job_id, company, title, s1, s0, catalog)
    except Exception as exc:
        raise S3ParseError(f"$.s2: cannot build nested validation context: {_bounded(exc)}") from exc


def parse_s3_request(raw: object) -> S3Request:
    obj = _object(raw, {"job_id", "company", "title", "context_mode", "s1", "s0", "s2", "alignment"}, "$")
    if isinstance(obj["job_id"], bool) or not isinstance(obj["job_id"], int):
        raise S3ParseError("$.job_id: expected integer")
    company = _string(obj["company"], "$.company")
    title = _string(obj["title"], "$.title")
    if obj["context_mode"] != "jd_only":
        raise S3SemanticError("$.context_mode: must be jd_only")
    s1 = _s1_from_dict(obj["s1"])
    alignment = parse_alignment(obj["alignment"])
    raw_point_ids = {
        item
        for point in obj["s0"].get("points", [])
        if isinstance(point, dict)
        for item in point.get("profile_ids", [])
        if isinstance(item, str)
    }
    all_profile_ids = tuple(dict.fromkeys((*alignment.project_ids, *alignment.experience_ids, *raw_point_ids)))
    positioning = PositioningView(
        tuple(PositioningEntry(item, "project", item, item, (), ()) for item in all_profile_ids),
        (),
    )
    s0_request = S0Request(obj["job_id"], company, title, s1, positioning)
    try:
        s0 = parse_s0_response(json.dumps(obj["s0"], separators=(",", ":")), s0_request)
    except Exception as exc:
        raise S3ParseError(f"$.s0: invalid response: {_bounded(exc)}") from exc
    if not isinstance(obj["s2"], dict):
        raise S3ParseError("$.s2: expected object")
    s2_request = _synthetic_s2_request(obj["job_id"], company, title, s1, s0, obj["s2"], alignment)
    try:
        s2 = parse_s2_response(json.dumps(obj["s2"], separators=(",", ":")), s2_request)
    except Exception as exc:
        raise S3ParseError(f"$.s2: invalid response: {_bounded(exc)}") from exc
    return S3Request(obj["job_id"], company, title, "jd_only", s1, s0, s2, alignment)


def _numeric_tokens(text: str) -> Counter[str]:
    return Counter(match.group(0) for match in _NUMBER_RE.finditer(text))


def _words(text: str) -> list[str]:
    return [item.casefold() for item in _WORD_RE.findall(text)]


def _first_word(text: str) -> str:
    words = _words(text)
    return words[0] if words else ""


def _covered_mapping(request: S3Request) -> dict[str, tuple[str, ...]]:
    return {entry.term: entry.bullet_ids for entry in request.s2.coverage if entry.status == "covered"}


def _validate_bullet_edit(edit: BulletEdit, request: S3Request) -> None:
    by_id = {bullet.bullet_id: bullet for bullet in request.alignment.bullets}
    if edit.bullet_id not in by_id:
        raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: bullet is not selected")
    if not edit.motivating_terms:
        raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: motivating_terms is empty")
    must_have = {item.term for item in request.s1.must_have}
    covered = _covered_mapping(request)
    for term in edit.motivating_terms:
        if term not in must_have:
            raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: term is not an exact must-have: {_bounded(term)}")
        if term not in covered or edit.bullet_id not in covered[term]:
            raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: term is not covered by this bullet")
    source = by_id[edit.bullet_id]
    try:
        plain_after, _ = parse_emphasis(edit.after)
    except (EmphasisError, TypeError) as exc:
        raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: invalid emphasis: {_bounded(exc)}") from exc
    if not plain_after.strip() or "\n" in edit.after or "\r" in edit.after:
        raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: after must be one nonempty line")
    if _first_word(source.plain_text) != _first_word(plain_after):
        raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: leading action verb changed")
    if _numeric_tokens(source.plain_text) != _numeric_tokens(plain_after):
        raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: numeric-token multiset changed")
    budget = max((len(term) for term in edit.motivating_terms), default=0)
    if len(plain_after) > len(source.plain_text) + budget:
        raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: plain-text length grew beyond the mirrored term")
    before_counts = Counter(_words(source.plain_text))
    after_counts = Counter(_words(plain_after))
    motivating_words = set(_words(" ".join(edit.motivating_terms)))
    additions = after_counts - before_counts
    uncited = {word for word, count in additions.items() if word not in motivating_words and word not in _FUNCTION_WORDS and not word.isdigit()}
    if uncited:
        raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: uncited vocabulary: {_bounded(sorted(uncited))}")


def _validate_skill_additions(response: S3Response, request: S3Request) -> None:
    categories = {category: items for category, items in request.alignment.skills}
    existing = {_normalize(item) for items in categories.values() for item in items}
    dnc = {_normalize(item) for item in request.alignment.do_not_claim}
    must_have = {item.term for item in request.s1.must_have}
    covered = _covered_mapping(request)
    seen: set[tuple[str, str]] = set()
    for addition in response.skill_additions:
        if addition.category not in categories:
            raise S3SemanticError(f"skill_additions.{addition.category}: unknown category")
        if addition.term != addition.motivating_term:
            raise S3SemanticError(f"skill_additions.{addition.category}: term and motivating_term must match")
        if addition.term not in must_have or addition.term not in covered:
            raise S3SemanticError(f"skill_additions.{addition.category}: term is not an exact covered must-have")
        normalized = (_normalize(addition.category), _normalize(addition.term))
        if normalized in seen:
            raise S3SemanticError(f"skill_additions.{addition.category}: duplicate normalized addition")
        seen.add(normalized)
        if _normalize(addition.term) in existing:
            raise S3SemanticError(f"skill_additions.{addition.category}: term already exists")
        if _normalize(addition.term) in dnc:
            raise S3SemanticError(f"skill_additions.{addition.category}: do_not_claim collision")
        existing.add(_normalize(addition.term))


def parse_s3_response(raw_output: str, request: S3Request) -> S3Response:
    try:
        value = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise S3ParseError(f"$: invalid JSON: {_bounded(exc)}") from exc
    obj = _object(value, {"bullet_edits", "skill_additions"}, "$")
    raw_edits = obj["bullet_edits"]
    raw_additions = obj["skill_additions"]
    if not isinstance(raw_edits, list) or not isinstance(raw_additions, list):
        raise S3ParseError("bullet_edits and skill_additions must be arrays")
    if len(raw_edits) > 8:
        raise S3ParseError("bullet_edits: at most 8 edits")
    edits: list[BulletEdit] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_edits):
        edit = _object(item, {"bullet_id", "after", "motivating_terms", "rule"}, f"$.bullet_edits[{index}]")
        bullet_id = _string(edit["bullet_id"], f"$.bullet_edits[{index}].bullet_id")
        if bullet_id in seen_ids:
            raise S3ParseError(f"$.bullet_edits[{index}].bullet_id: duplicate id")
        seen_ids.add(bullet_id)
        after = _string(edit["after"], f"$.bullet_edits[{index}].after")
        terms = _string_array(edit["motivating_terms"], f"$.bullet_edits[{index}].motivating_terms")
        if edit["rule"] not in {rule.value for rule in S3EditRule}:
            raise S3ParseError(f"$.bullet_edits[{index}].rule: invalid rule")
        parsed = BulletEdit(bullet_id, after, terms, S3EditRule(edit["rule"]))
        canonical = next((item for item in request.alignment.bullets if item.bullet_id == bullet_id), None)
        if canonical is not None and after == canonical.source_text:
            raise S3ParseError(f"$.bullet_edits[{index}].after: unchanged canonical source")
        edits.append(parsed)
    additions: list[SkillAddition] = []
    for index, item in enumerate(raw_additions):
        addition = _object(item, {"category", "term", "motivating_term"}, f"$.skill_additions[{index}]")
        additions.append(SkillAddition(_string(addition["category"], f"$.skill_additions[{index}].category"), _string(addition["term"], f"$.skill_additions[{index}].term"), _string(addition["motivating_term"], f"$.skill_additions[{index}].motivating_term")))
    response = S3Response(tuple(edits), tuple(additions))
    for edit in response.bullet_edits:
        _validate_bullet_edit(edit, request)
    _validate_skill_additions(response, request)
    return response


def s3_response_to_dict(response: S3Response) -> dict[str, object]:
    return {
        "bullet_edits": [
            {"bullet_id": edit.bullet_id, "after": edit.after, "motivating_terms": list(edit.motivating_terms), "rule": edit.rule.value}
            for edit in response.bullet_edits
        ],
        "skill_additions": [
            {"category": addition.category, "term": addition.term, "motivating_term": addition.motivating_term}
            for addition in response.skill_additions
        ],
    }


def draft_bullet_to_dict(bullet: DraftBullet) -> dict[str, object]:
    return {
        "bullet_id": bullet.bullet_id,
        "owner_id": bullet.owner_id,
        "owner_kind": bullet.owner_kind,
        "text": bullet.text,
        "plain_text": bullet.plain_text,
        "emphasis": [[start, end] for start, end in bullet.emphasis],
    }


def tailored_draft_to_dict(draft: TailoredDraft) -> dict[str, object]:
    return {
        "job_id": draft.job_id,
        "company": draft.company,
        "title": draft.title,
        "base_variant": draft.base_variant,
        "project_ids": list(draft.project_ids),
        "experience_ids": list(draft.experience_ids),
        "bullets": [draft_bullet_to_dict(bullet) for bullet in draft.bullets],
        "skills": [[category, list(items)] for category, items in draft.skills],
        "alignment_fingerprint": draft.alignment_fingerprint,
    }


def change_entry_to_dict(entry: ChangeEntry) -> dict[str, object]:
    return {
        "location": entry.location,
        "before": entry.before,
        "after": entry.after,
        "motivating_terms": list(entry.motivating_terms),
        "motivating_jd_quotes": list(entry.motivating_jd_quotes),
        "rule": entry.rule,
    }


def edit_budget_to_dict(budget: EditBudget) -> dict[str, object]:
    return {
        "changed_tokens": budget.changed_tokens,
        "base_tokens": budget.base_tokens,
        "ratio": budget.ratio,
    }


# ---------------------------------------------------------------------------
# Strict structural parsers for the persisted bundle contract (m8p3.s3_bundle.v1).
# These mirror the *_to_dict serializers above field-for-field. Semantic/
# recompute validation against an authoritative S3Request lives in
# src.tailor.s3_pipeline.parse_s3_bundle(); these functions only prove the
# JSON is well-typed.
# ---------------------------------------------------------------------------


def _int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise S3ParseError(f"{path}: expected integer")
    return value


def _float(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise S3ParseError(f"{path}: expected number")
    return float(value)


def _plain_string_array(value: object, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise S3ParseError(f"{path}: expected string array")
    return tuple(value)


def _emphasis_spans(value: object, path: str) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, list):
        raise S3ParseError(f"{path}: expected array")
    spans: list[tuple[int, int]] = []
    for index, span in enumerate(value):
        if (
            not isinstance(span, list)
            or len(span) != 2
            or any(isinstance(bound, bool) or not isinstance(bound, int) for bound in span)
        ):
            raise S3ParseError(f"{path}[{index}]: invalid emphasis span")
        spans.append((span[0], span[1]))
    return tuple(spans)


_DRAFT_BULLET_KEYS = {"bullet_id", "owner_id", "owner_kind", "text", "plain_text", "emphasis"}


def parse_draft_bullet(raw: object, path: str) -> DraftBullet:
    obj = _object(raw, _DRAFT_BULLET_KEYS, path)
    bullet_id = _string(obj["bullet_id"], f"{path}.bullet_id")
    owner_id = _string(obj["owner_id"], f"{path}.owner_id")
    if obj["owner_kind"] not in ("project", "experience"):
        raise S3ParseError(f"{path}.owner_kind: invalid kind")
    text = _string(obj["text"], f"{path}.text")
    plain_text = _string(obj["plain_text"], f"{path}.plain_text")
    emphasis = _emphasis_spans(obj["emphasis"], f"{path}.emphasis")
    return DraftBullet(bullet_id, owner_id, obj["owner_kind"], text, plain_text, emphasis)


_TAILORED_DRAFT_KEYS = {
    "job_id", "company", "title", "base_variant", "project_ids",
    "experience_ids", "bullets", "skills", "alignment_fingerprint",
}


def parse_tailored_draft(raw: object, path: str = "$.draft") -> TailoredDraft:
    obj = _object(raw, _TAILORED_DRAFT_KEYS, path)
    job_id = _int(obj["job_id"], f"{path}.job_id")
    company = _string(obj["company"], f"{path}.company")
    title = _string(obj["title"], f"{path}.title")
    base_variant = _string(obj["base_variant"], f"{path}.base_variant")
    project_ids = _plain_string_array(obj["project_ids"], f"{path}.project_ids")
    experience_ids = _plain_string_array(obj["experience_ids"], f"{path}.experience_ids")
    if not isinstance(obj["bullets"], list):
        raise S3ParseError(f"{path}.bullets: expected array")
    bullets: list[DraftBullet] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(obj["bullets"]):
        bullet = parse_draft_bullet(item, f"{path}.bullets[{index}]")
        if bullet.bullet_id in seen_ids:
            raise S3ParseError(f"{path}.bullets[{index}].bullet_id: duplicate id")
        seen_ids.add(bullet.bullet_id)
        bullets.append(bullet)
    if not isinstance(obj["skills"], list):
        raise S3ParseError(f"{path}.skills: expected array")
    skills: list[tuple[str, tuple[str, ...]]] = []
    seen_categories: set[str] = set()
    for index, item in enumerate(obj["skills"]):
        if not isinstance(item, list) or len(item) != 2:
            raise S3ParseError(f"{path}.skills[{index}]: expected [category, items] pair")
        category = _string(item[0], f"{path}.skills[{index}][0]")
        if category in seen_categories:
            raise S3ParseError(f"{path}.skills[{index}]: duplicate category")
        seen_categories.add(category)
        items = _plain_string_array(item[1], f"{path}.skills[{index}][1]")
        skills.append((category, items))
    fingerprint = obj["alignment_fingerprint"]
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise S3ParseError(f"{path}.alignment_fingerprint: invalid fingerprint")
    return TailoredDraft(job_id, company, title, base_variant, project_ids, experience_ids, tuple(bullets), tuple(skills), fingerprint)


_CHANGE_ENTRY_KEYS = {"location", "before", "after", "motivating_terms", "motivating_jd_quotes", "rule"}


def parse_change_entry(raw: object, path: str) -> ChangeEntry:
    obj = _object(raw, _CHANGE_ENTRY_KEYS, path)
    location = _string(obj["location"], f"{path}.location")
    if not isinstance(obj["before"], str):
        raise S3ParseError(f"{path}.before: expected string")
    if not isinstance(obj["after"], str):
        raise S3ParseError(f"{path}.after: expected string")
    motivating_terms = _plain_string_array(obj["motivating_terms"], f"{path}.motivating_terms")
    motivating_jd_quotes = _plain_string_array(obj["motivating_jd_quotes"], f"{path}.motivating_jd_quotes")
    rule = _string(obj["rule"], f"{path}.rule")
    return ChangeEntry(location, obj["before"], obj["after"], motivating_terms, motivating_jd_quotes, rule)


def parse_change_log(raw: object, path: str = "$.change_log") -> tuple[ChangeEntry, ...]:
    if not isinstance(raw, list):
        raise S3ParseError(f"{path}: expected array")
    return tuple(parse_change_entry(item, f"{path}[{index}]") for index, item in enumerate(raw))


_EDIT_BUDGET_KEYS = {"changed_tokens", "base_tokens", "ratio"}


def parse_edit_budget(raw: object, path: str = "$.edit_budget") -> EditBudget:
    obj = _object(raw, _EDIT_BUDGET_KEYS, path)
    changed = _int(obj["changed_tokens"], f"{path}.changed_tokens")
    base = _int(obj["base_tokens"], f"{path}.base_tokens")
    ratio = _float(obj["ratio"], f"{path}.ratio")
    return EditBudget(changed, base, ratio)


def hydrate_s3(request: S3Request, response: S3Response) -> TailoredDraft:
    """Apply only validated model edits to the canonical alignment projection."""
    for edit in response.bullet_edits:
        _validate_bullet_edit(edit, request)
    _validate_skill_additions(response, request)
    edits = {edit.bullet_id: edit for edit in response.bullet_edits}
    bullets: list[DraftBullet] = []
    for source in request.alignment.bullets:
        text = edits[source.bullet_id].after if source.bullet_id in edits else source.source_text
        try:
            plain_text, emphasis = parse_emphasis(text)
        except EmphasisError as exc:
            raise S3HydrationError(f"bullet {source.bullet_id}: invalid emphasis: {_bounded(exc)}") from exc
        bullets.append(DraftBullet(source.bullet_id, source.owner_id, source.owner_kind, text, plain_text, emphasis))
    skill_map = {category: list(items) for category, items in request.alignment.skills}
    for addition in response.skill_additions:
        skill_map[addition.category].append(addition.term)
    skills = tuple((category, tuple(items)) for category, items in skill_map.items())
    return TailoredDraft(
        job_id=request.job_id,
        company=request.company,
        title=request.title,
        base_variant=request.s2.base_variant,
        project_ids=tuple(choice.project_id for choice in request.s2.projects),
        experience_ids=request.alignment.experience_ids,
        bullets=tuple(bullets),
        skills=skills,
        alignment_fingerprint=request.alignment.fingerprint,
    )


def _requirement_quotes(request: S3Request, terms: tuple[str, ...]) -> tuple[str, ...]:
    quotes = {item.term: item.quote for item in (*request.s1.must_have, *request.s1.nice_to_have)}
    return tuple(quotes[term] for term in terms)


def derive_change_log(
    request: S3Request, response: S3Response, draft: TailoredDraft
) -> tuple[ChangeEntry, ...]:
    canonical = {item.bullet_id: item for item in request.alignment.bullets}
    entries: list[ChangeEntry] = []
    for edit in response.bullet_edits:
        source = canonical[edit.bullet_id]
        entries.append(ChangeEntry(
            location=f"bullet:{edit.bullet_id}",
            before=source.source_text,
            after=edit.after,
            motivating_terms=edit.motivating_terms,
            motivating_jd_quotes=_requirement_quotes(request, edit.motivating_terms),
            rule=edit.rule.value,
        ))
    for addition in response.skill_additions:
        entries.append(ChangeEntry(
            location=f"skills:{addition.category}",
            before="",
            after=addition.term,
            motivating_terms=(addition.motivating_term,),
            motivating_jd_quotes=_requirement_quotes(request, (addition.motivating_term,)),
            rule="skill_addition",
        ))
    return tuple(entries)


def _plain_projection(view: AlignmentView | TailoredDraft) -> list[str]:
    lines = [f"base_variant: {view.base_variant}", "projects:"]
    lines.extend(f"- {project_id}" for project_id in view.project_ids)
    lines.append("experience:")
    lines.extend(f"- {experience_id}" for experience_id in view.experience_ids)
    lines.append("bullets:")
    lines.extend(f"- {bullet.bullet_id}: {bullet.plain_text}" for bullet in view.bullets)
    lines.append("skills:")
    lines.extend(f"- {category}: {', '.join(items)}" for category, items in view.skills)
    return lines


def derive_unified_diff(request: S3Request, draft: TailoredDraft) -> str:
    before = _plain_projection(request.alignment)
    after = _plain_projection(draft)
    return "\n".join(difflib.unified_diff(before, after, fromfile="canonical", tofile="tailored", lineterm="")) + "\n"


def _edit_distance(base: list[str], tailored: list[str]) -> int:
    matcher = difflib.SequenceMatcher(None, base, tailored, autojunk=False)
    distance = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            distance += max(i2 - i1, j2 - j1)
        elif tag == "delete":
            distance += i2 - i1
        elif tag == "insert":
            distance += j2 - j1
    return distance


def calculate_edit_budget(request: S3Request, draft: TailoredDraft) -> EditBudget:
    base_tokens = _words(" ".join(item.plain_text for item in request.alignment.bullets) + " " + " ".join(item for _, values in request.alignment.skills for item in values))
    tailored_tokens = _words(" ".join(item.plain_text for item in draft.bullets) + " " + " ".join(item for _, values in draft.skills for item in values))
    changed = _edit_distance(base_tokens, tailored_tokens)
    denominator = len(base_tokens)
    return EditBudget(changed, denominator, changed / denominator if denominator else 0.0)


# ---------------------------------------------------------------------------
# M8P-4 addition (post-M8P-3R integration, purely additive): the bounded S3
# revision path a G2 critic finding may trigger. No existing function above
# this line is modified. `G2Finding` is only referenced as a forward-ref
# type (this module already uses `from __future__ import annotations`) and
# is imported lazily inside function bodies to avoid a circular import with
# src.tailor.g2, which itself imports S3Request from this module.
# ---------------------------------------------------------------------------

S3_REVISION_MARKER = "{{S3_REVISION_JSON}}"


@dataclass(frozen=True)
class S3RevisionContext:
    round_index: int
    findings: tuple["G2Finding", ...]  # noqa: F821 -- forward ref, see module note above


def build_s3_revision_prompt(template: str, request: S3Request, context: S3RevisionContext) -> str:
    if template.count(S3_REQUEST_MARKER) != 1 or template.count(S3_REVISION_MARKER) != 1:
        raise ValueError(
            f"S3 revision prompt template must contain {S3_REQUEST_MARKER!r} and "
            f"{S3_REVISION_MARKER!r} exactly once each"
        )
    revision_payload = {
        "round_index": context.round_index,
        "findings": [
            {
                "dimension": finding.dimension.value,
                "rule_id": finding.rule_id,
                "target_kind": finding.target_kind.value,
                "target_id": finding.target_id,
                "quoted_line": finding.quoted_line,
                "explanation": finding.explanation,
            }
            for finding in context.findings
        ],
    }
    text = template.replace(S3_REQUEST_MARKER, json.dumps(s3_request_to_dict(request), sort_keys=True, indent=2))
    return text.replace(S3_REVISION_MARKER, json.dumps(revision_payload, sort_keys=True, indent=2))


def validate_revision_scope(response: S3Response, previous: S3Response, context: S3RevisionContext) -> None:
    """A revision may only touch bullet ids that already had an edit in
    `previous`, or that a finding in `context` named. Raises S3SemanticError
    for any edit outside that scope -- a revision may not open a new front
    the critic never flagged (§7 rule 2 of the M8P-4 design)."""
    from src.tailor.g2 import G2TargetKind  # local import: avoids circular import at module load

    allowed = {edit.bullet_id for edit in previous.bullet_edits}
    allowed |= {finding.target_id for finding in context.findings if finding.target_kind is G2TargetKind.BULLET}
    for edit in response.bullet_edits:
        if edit.bullet_id not in allowed:
            raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: outside revision scope")
