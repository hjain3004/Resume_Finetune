"""Deterministic static G1 checks for hydrated S3 drafts."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.render.emphasis import EmphasisError, parse_emphasis
from src.tailor.lint import contains_normalized_phrase, normalize_tokens
from src.tailor.s3 import EditBudget, S3Request, S3Response, TailoredDraft, calculate_edit_budget


class G1Status(str, Enum):
    STATIC_PASS = "static_pass"
    FAIL = "fail"


@dataclass(frozen=True)
class G1Violation:
    rule: str
    location: str
    message: str


@dataclass(frozen=True)
class G1Report:
    status: G1Status
    violations: tuple[G1Violation, ...]
    edit_budget: EditBudget
    render_line_check: str


def load_banned_terms(path: Path) -> tuple[str, ...]:
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        term = line.strip()
        if term and not term.startswith("#"):
            terms.append(term)
    return tuple(terms)


def _violate(violations: list[G1Violation], rule: str, location: str, message: str) -> None:
    violations.append(G1Violation(rule, location, message))


def _text_items(draft: TailoredDraft) -> tuple[tuple[str, str], ...]:
    return tuple(
        [(f"bullet:{item.bullet_id}", item.plain_text) for item in draft.bullets]
        + [(f"skills:{category}", " ".join(items)) for category, items in draft.skills]
    )


def _occurrences(text: str, phrase: str) -> int:
    haystack = normalize_tokens(text)
    needle = normalize_tokens(phrase)
    if not needle:
        return 0
    return sum(
        haystack[index:index + len(needle)] == needle
        for index in range(len(haystack) - len(needle) + 1)
    )


def _numeric_tokens(text: str) -> Counter[str]:
    import re
    return Counter(match.group(0) for match in re.finditer(r"(?<!\w)[~+-]?(?:\d[\d,]*(?:\.\d+)?)(?:%|x|\+)?(?!\w)", text))


def run_static_g1(
    request: S3Request,
    response: S3Response,
    draft: TailoredDraft,
    banned_terms: tuple[str, ...],
) -> G1Report:
    violations: list[G1Violation] = []
    alignment = request.alignment
    expected_project_ids = tuple(choice.project_id for choice in request.s2.projects)
    expected_bullet_ids = tuple(item.bullet_id for item in alignment.bullets)
    if draft.job_id != request.job_id:
        _violate(violations, "G0", "job_id", "does not match request")
    if draft.company != request.company:
        _violate(violations, "G0", "company", "does not match request")
    if draft.title != request.title:
        _violate(violations, "G0", "title", "does not match request")
    if draft.base_variant != request.s2.base_variant:
        _violate(violations, "G0", "base_variant", "does not match S2")
    if draft.project_ids != expected_project_ids:
        _violate(violations, "L1", "projects", "project selection changed")
    if draft.experience_ids != alignment.experience_ids:
        _violate(violations, "L1", "experience", "experience selection changed")
    if tuple(item.bullet_id for item in draft.bullets) != expected_bullet_ids:
        _violate(violations, "L1", "bullets", "bullet order or membership changed")
    if tuple(category for category, _ in draft.skills) != tuple(category for category, _ in alignment.skills):
        _violate(violations, "L1", "skills", "skill categories changed")
    if draft.alignment_fingerprint != alignment.fingerprint:
        _violate(violations, "G0", "alignment_fingerprint", "does not match alignment")
    if any(item.claim_type in {"ownership_unresolved", "needs_input"} for item in alignment.bullets):
        _violate(violations, "L6", "bullets", "blocked canonical claim")

    # G0 canonical-binding checks -- apply to EVERY draft bullet, not just the
    # ids the response declared as edited. A bullet keeping its id but
    # carrying a fabricated owner, or carrying text that was never validated
    # as either the canonical source or an accepted edit, must fail here
    # even if bullet-order/membership above happened to match (Defects 2/3).
    canonical_by_id = {item.bullet_id: item for item in alignment.bullets}
    edits_by_id = {edit.bullet_id: edit for edit in response.bullet_edits}
    expected_skill_map: dict[str, list[str]] = {category: list(items) for category, items in alignment.skills}
    for addition in response.skill_additions:
        if addition.category in expected_skill_map:
            expected_skill_map[addition.category].append(addition.term)
    expected_skills = tuple((category, tuple(items)) for category, items in expected_skill_map.items())
    if draft.skills != expected_skills:
        _violate(violations, "L1", "skills", "skill contents do not match canonical skills plus accepted additions")

    for draft_bullet in draft.bullets:
        source = canonical_by_id.get(draft_bullet.bullet_id)
        if source is None:
            _violate(violations, "L1", f"bullet:{draft_bullet.bullet_id}", "unknown bullet id")
            continue
        if draft_bullet.owner_id != source.owner_id:
            _violate(violations, "G0", f"bullet:{draft_bullet.bullet_id}", "owner_id does not match canonical alignment")
        if draft_bullet.owner_kind != source.owner_kind:
            _violate(violations, "G0", f"bullet:{draft_bullet.bullet_id}", "owner_kind does not match canonical alignment")
        edit = edits_by_id.get(draft_bullet.bullet_id)
        if edit is None:
            if draft_bullet.text != source.source_text:
                _violate(violations, "L1", f"bullet:{draft_bullet.bullet_id}", "unedited bullet text does not match canonical source")
        elif draft_bullet.text != edit.after:
            _violate(violations, "L1", f"bullet:{draft_bullet.bullet_id}", "edited bullet text does not match the accepted edit")
        try:
            reparsed_plain, reparsed_emphasis = parse_emphasis(draft_bullet.text)
        except EmphasisError:
            _violate(violations, "L4", f"bullet:{draft_bullet.bullet_id}", "invalid emphasis")
        else:
            if draft_bullet.plain_text != reparsed_plain:
                _violate(violations, "G0", f"bullet:{draft_bullet.bullet_id}", "stored plain_text does not match its own marked text")
            if draft_bullet.emphasis != reparsed_emphasis:
                _violate(violations, "G0", f"bullet:{draft_bullet.bullet_id}", "stored emphasis does not match its own marked text")

    for location, text in _text_items(draft):
        for term in banned_terms:
            if contains_normalized_phrase(text, term):
                _violate(violations, "L2", location, f"banned term: {term}")
        for term in alignment.do_not_claim:
            if contains_normalized_phrase(text, term):
                _violate(violations, "L6", location, f"do_not_claim term: {term}")

    by_id = {item.bullet_id: item for item in draft.bullets}
    covered = {entry.term: entry for entry in request.s2.coverage if entry.status == "covered"}
    all_text = " ".join(text for _, text in _text_items(draft))
    for requirement in request.s1.must_have:
        entry = covered.get(requirement.term)
        if entry is None:
            continue
        bullet_text = " ".join(by_id[item].plain_text for item in entry.bullet_ids if item in by_id)
        if not contains_normalized_phrase(bullet_text, requirement.term):
            _violate(violations, "L3", f"must_have:{requirement.term}", "covered term missing from mapped bullet")
        if not contains_normalized_phrase(" ".join(item for _, items in draft.skills for item in items), requirement.term):
            _violate(violations, "L3", f"must_have:{requirement.term}", "covered term missing from skills")
        count = _occurrences(all_text, requirement.term)
        if count > 4:
            _violate(violations, "L3", f"must_have:{requirement.term}", "term appears more than four times")
        covered_index = [item.term for item in request.s1.must_have if item.term in covered].index(requirement.term)
        if covered_index < 5 and count not in (2, 3):
            _violate(violations, "L3", f"must_have:{requirement.term}", "first five covered terms must appear two or three times")

    canonical = {item.bullet_id: item for item in alignment.bullets}
    edited = {item.bullet_id for item in response.bullet_edits}
    for bullet_id in edited:
        source = canonical[bullet_id]
        draft_bullet = by_id[bullet_id]
        try:
            plain, _ = parse_emphasis(draft_bullet.text)
        except EmphasisError:
            _violate(violations, "L4", f"bullet:{bullet_id}", "invalid emphasis")
            continue
        if "\n" in draft_bullet.text or "\r" in draft_bullet.text:
            _violate(violations, "L4", f"bullet:{bullet_id}", "line break")
        if (normalize_tokens(source.plain_text)[:1] != normalize_tokens(plain)[:1]):
            _violate(violations, "L4", f"bullet:{bullet_id}", "leading action verb changed")
        if _numeric_tokens(source.plain_text) != _numeric_tokens(plain):
            _violate(violations, "L4", f"bullet:{bullet_id}", "numeric-token multiset changed")
        if len(plain) > len(source.plain_text):
            _violate(violations, "L4", f"bullet:{bullet_id}", "plain-text length grew")

    budget = calculate_edit_budget(request, draft)
    if budget.ratio > 0.15:
        _violate(violations, "L5", "edit_budget", "edit distance exceeds 15 percent")
    return G1Report(G1Status.STATIC_PASS if not violations else G1Status.FAIL, tuple(violations), budget, "pending")


def g1_violation_to_dict(violation: G1Violation) -> dict[str, object]:
    return {"rule": violation.rule, "location": violation.location, "message": violation.message}


def g1_report_to_dict(report: G1Report) -> dict[str, object]:
    from src.tailor.s3 import edit_budget_to_dict

    return {
        "status": report.status.value,
        "violations": [g1_violation_to_dict(item) for item in report.violations],
        "edit_budget": edit_budget_to_dict(report.edit_budget),
        "render_line_check": report.render_line_check,
    }


_G1_VIOLATION_KEYS = {"rule", "location", "message"}


def _nonempty_str(value: object, path: str) -> str:
    from src.tailor.s3 import S3ParseError

    if not isinstance(value, str) or not value.strip():
        raise S3ParseError(f"{path}: expected nonempty string")
    return value


def parse_g1_violation(raw: object, path: str) -> G1Violation:
    from src.tailor.s3 import S3ParseError

    if not isinstance(raw, dict) or set(raw) != _G1_VIOLATION_KEYS:
        raise S3ParseError(f"{path}: unexpected or missing fields")
    return G1Violation(
        rule=_nonempty_str(raw["rule"], f"{path}.rule"),
        location=_nonempty_str(raw["location"], f"{path}.location"),
        message=_nonempty_str(raw["message"], f"{path}.message"),
    )


_G1_REPORT_KEYS = {"status", "violations", "edit_budget", "render_line_check"}
_G1_STATUS_VALUES = {status.value for status in G1Status}


def parse_g1_report(raw: object, path: str = "$.g1") -> G1Report:
    from src.tailor.s3 import S3ParseError, parse_edit_budget

    if not isinstance(raw, dict) or set(raw) != _G1_REPORT_KEYS:
        raise S3ParseError(f"{path}: unexpected or missing fields")
    status = raw["status"]
    if status not in _G1_STATUS_VALUES:
        raise S3ParseError(f"{path}.status: invalid status")
    if not isinstance(raw["violations"], list):
        raise S3ParseError(f"{path}.violations: expected array")
    violations = tuple(
        parse_g1_violation(item, f"{path}.violations[{index}]") for index, item in enumerate(raw["violations"])
    )
    edit_budget = parse_edit_budget(raw["edit_budget"], f"{path}.edit_budget")
    render_line_check = _nonempty_str(raw["render_line_check"], f"{path}.render_line_check")
    return G1Report(G1Status(status), violations, edit_budget, render_line_check)
