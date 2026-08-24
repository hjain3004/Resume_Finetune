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
