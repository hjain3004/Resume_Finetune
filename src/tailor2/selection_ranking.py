"""Bounded selection, candidate integrity, and ranking contracts for Tailor2.

The module keeps model-shaped data typed and makes every safety decision
deterministic.  It does not choose resume structure; the existing draft
contract remains the authority for sections, entries, and ordering.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from src.profile import MasterProfile
from src.tailor2.audit_projection import get_skill_aliases
from src.tailor2.models import DraftBullet
from src.tailor2.validators import extract_numeric_tokens


RequirementKind = Literal["must_have", "preferred", "responsibility"]
MatchClass = Literal["direct", "adjacent", "transferable", "gap"]


class SelectionContractError(ValueError):
    """Raised when a structured selection response is incomplete or unsafe."""


@dataclass(frozen=True)
class Requirement:
    id: str
    term: str
    quote: str
    kind: RequirementKind
    alternative_group_id: str | None = None
    domain_context: str = ""
    ambiguity: str = ""
    evidence_gap: bool = False


@dataclass(frozen=True)
class RequirementAnalysis:
    requirements: list[Requirement]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceMatch:
    requirement_id: str
    evidence_ids: list[str]
    classification: MatchClass
    confidence: float
    strength: float
    explanation: str
    limitation: str = ""


@dataclass(frozen=True)
class EvidenceSelection:
    evidence_id: str
    selected: bool
    score: float
    requirement_ids: list[str]
    estimated_line_cost: int
    rationale: str
    omission_reason: str | None = None


@dataclass(frozen=True)
class SkillCandidate:
    category: str
    term: str
    include: bool
    canonical_support: bool
    selected_demonstration: bool
    evidence_ids: list[str]
    reason: str
    weak_demo_advisory: bool = False


@dataclass(frozen=True)
class BulletCandidate:
    candidate_id: str
    bullet_id: str
    evidence_ids: list[str]
    supported_requirement_ids: list[str]
    text: str
    variation: str = "canonical"


@dataclass(frozen=True)
class IntegrityFinding:
    code: str
    severity: Literal["fatal", "warning"]
    message: str


@dataclass(frozen=True)
class CandidateIntegrity:
    candidate_id: str
    valid: bool
    findings: list[IntegrityFinding]


@dataclass(frozen=True)
class CandidateRanking:
    candidate_id: str
    component_scores: dict[str, float]
    total_score: float
    rationale: str
    selected: bool = False
    fallback: bool = False


@dataclass(frozen=True)
class RankingResult:
    rankings: list[CandidateRanking]
    selected_by_bullet: dict[str, str]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class UnusedEvidence:
    evidence_id: str
    requirement_ids: list[str]
    strength: float
    likely_section: str
    estimated_line_cost: int
    omission_reason: str
    redundancy: str = ""
    weaker_selected_replacement: str | None = None
    later_page_fill_suitability: str = "possible"


@dataclass(frozen=True)
class SelectionBundle:
    requirements: RequirementAnalysis
    matches: list[EvidenceMatch]
    evidence_selection: list[EvidenceSelection]
    skills: list[SkillCandidate]
    candidates: list[BulletCandidate]
    integrity: list[CandidateIntegrity]
    rankings: RankingResult
    unused_evidence: list[UnusedEvidence]
    provider: str = ""
    model: str = ""
    warnings: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]*")
_LEADING_VERB_RE = re.compile(r"^\s*([A-Za-z][A-Za-z'-]*)")
_STOP_WORDS = frozenset(
    "a an and as at by for from in into of on or the to with through using via".split()
)
_AI_ABSTRACTIONS = frozenset(
    "leveraged optimized empowered transformed streamlined innovative robust scalable seamless".split()
)


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SelectionContractError(f"{path}: expected nonempty string")
    return value.strip()


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise SelectionContractError(f"{path}: expected list")
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SelectionContractError(f"{path}: expected number")
    if not 0 <= float(value) <= 1:
        raise SelectionContractError(f"{path}: expected value between 0 and 1")
    return float(value)


def _kind(raw: Any, path: str) -> RequirementKind:
    value = raw
    if value == "nice_to_have":
        value = "preferred"
    if value not in {"must_have", "preferred", "responsibility"}:
        raise SelectionContractError(f"{path}: invalid requirement kind")
    return value


def parse_requirement_analysis(raw: str | dict[str, Any], jd_text: str | None = None) -> RequirementAnalysis:
    """Parse stable requirement IDs, preserving quotes and OR groups."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SelectionContractError(f"requirement analysis is not JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SelectionContractError("requirement analysis must be an object")
    raw_items = raw.get("requirements", raw.get("atomic_requirements"))
    if raw_items is None:
        raise SelectionContractError("requirement analysis missing 'requirements'")
    requirements: list[Requirement] = []
    seen: set[str] = set()
    for index, item in enumerate(_require_list(raw_items, "requirements")):
        if not isinstance(item, dict):
            raise SelectionContractError(f"requirements[{index}]: expected object")
        path = f"requirements[{index}]"
        ident = _require_string(item.get("id"), f"{path}.id")
        if ident in seen:
            raise SelectionContractError(f"{path}.id: duplicate requirement ID {ident!r}")
        seen.add(ident)
        quote = _require_string(item.get("quote"), f"{path}.quote")
        if jd_text is not None and quote not in jd_text:
            raise SelectionContractError(f"{path}.quote: not an exact JD substring")
        term = _require_string(item.get("term", item.get("text")), f"{path}.term")
        requirements.append(
            Requirement(
                id=ident,
                term=term,
                quote=quote,
                kind=_kind(item.get("kind", item.get("importance", "must_have")), f"{path}.kind"),
                alternative_group_id=(
                    str(item["alternative_group_id"]).strip()
                    if item.get("alternative_group_id") is not None
                    else None
                ),
                domain_context=str(item.get("domain_context", "")).strip(),
                ambiguity=str(item.get("ambiguity", "")).strip(),
                evidence_gap=bool(item.get("evidence_gap", False)),
            )
        )
    for index, item in enumerate(raw.get("responsibilities", [])):
        if not isinstance(item, dict):
            raise SelectionContractError(f"responsibilities[{index}]: expected object")
        path = f"responsibilities[{index}]"
        ident = _require_string(item.get("id"), f"{path}.id")
        if ident in seen:
            raise SelectionContractError(f"{path}.id: duplicate requirement ID {ident!r}")
        seen.add(ident)
        quote = _require_string(item.get("quote", item.get("term")), f"{path}.quote")
        if jd_text is not None and quote not in jd_text:
            raise SelectionContractError(f"{path}.quote: not an exact JD substring")
        requirements.append(
            Requirement(
                id=ident,
                term=_require_string(item.get("term", item.get("text")), f"{path}.term"),
                quote=quote,
                kind="responsibility",
            )
        )
    if not requirements:
        raise SelectionContractError("requirement analysis must contain at least one requirement")
    return RequirementAnalysis(requirements=requirements, warnings=[str(w) for w in raw.get("warnings", [])])


def parse_evidence_matches(raw: Any, requirement_ids: set[str], evidence_ids: set[str]) -> list[EvidenceMatch]:
    items = raw.get("matches", raw) if isinstance(raw, dict) else raw
    result: list[EvidenceMatch] = []
    for index, item in enumerate(_require_list(items, "matches")):
        if not isinstance(item, dict):
            raise SelectionContractError(f"matches[{index}]: expected object")
        path = f"matches[{index}]"
        requirement_id = _require_string(item.get("requirement_id"), f"{path}.requirement_id")
        if requirement_id not in requirement_ids:
            raise SelectionContractError(f"{path}.requirement_id: unknown ID")
        item_evidence = [_require_string(value, f"{path}.evidence_ids[]") for value in _require_list(item.get("evidence_ids", []), f"{path}.evidence_ids")]
        if any(value not in evidence_ids for value in item_evidence):
            raise SelectionContractError(f"{path}.evidence_ids: unknown evidence ID")
        classification = item.get("classification")
        if classification not in {"direct", "adjacent", "transferable", "gap"}:
            raise SelectionContractError(f"{path}.classification: invalid match class")
        if classification == "gap" and item_evidence:
            raise SelectionContractError(f"{path}: gap matches cannot cite evidence")
        result.append(
            EvidenceMatch(
                requirement_id=requirement_id,
                evidence_ids=item_evidence,
                classification=classification,
                confidence=_number(item.get("confidence"), f"{path}.confidence"),
                strength=_number(item.get("strength"), f"{path}.strength"),
                explanation=_require_string(item.get("explanation"), f"{path}.explanation"),
                limitation=str(item.get("limitation", "")).strip(),
            )
        )
    return result


def parse_selection_bundle(
    raw: str | dict[str, Any],
    *,
    jd_text: str,
    profile: MasterProfile,
    variant: str,
    provider: str = "",
    model: str = "",
) -> SelectionBundle:
    """Parse the single bounded selection response used by the lane."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SelectionContractError(f"selection response is not JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SelectionContractError("selection response must be an object")
    analysis = parse_requirement_analysis(raw, jd_text)
    evidence_by_id = _all_evidence(profile, variant)
    matches = parse_evidence_matches(raw.get("matches", []), {item.id for item in analysis.requirements}, set(evidence_by_id))
    raw_selection = raw.get("evidence_selection")
    selection: list[EvidenceSelection]
    if raw_selection is None:
        selection = select_evidence_flexibly(analysis, matches, profile, variant)
    else:
        selection = []
        seen_selection_ids: set[str] = set()
        for index, item in enumerate(_require_list(raw_selection, "evidence_selection")):
            if not isinstance(item, dict):
                raise SelectionContractError(f"evidence_selection[{index}]: expected object")
            path = f"evidence_selection[{index}]"
            evidence_id = _require_string(item.get("evidence_id"), f"{path}.evidence_id")
            if evidence_id not in evidence_by_id:
                raise SelectionContractError(f"{path}.evidence_id: unknown evidence ID")
            if evidence_id in seen_selection_ids:
                raise SelectionContractError(f"{path}.evidence_id: duplicate evidence ID")
            seen_selection_ids.add(evidence_id)
            selection.append(
                EvidenceSelection(
                    evidence_id=evidence_id,
                    selected=bool(item.get("selected", False)),
                    score=float(item.get("score", 0)),
                    requirement_ids=[str(value) for value in item.get("requirement_ids", [])],
                    estimated_line_cost=int(item.get("estimated_line_cost", 1)),
                    rationale=_require_string(item.get("rationale", "model selection"), f"{path}.rationale"),
                    omission_reason=(str(item["omission_reason"]) if item.get("omission_reason") is not None else None),
                )
            )
    selected_ids = {item.evidence_id for item in selection if item.selected}
    skills = build_skill_candidates(profile, analysis, matches, selected_ids)
    raw_skills = raw.get("skills")
    if raw_skills is not None:
        if not isinstance(raw_skills, list):
            raise SelectionContractError("skills must be a list")
        requested = {(str(item.get("category")), str(item.get("term"))) for item in raw_skills if isinstance(item, dict)}
        skills = [item for item in skills if (item.category, item.term) in requested]

    candidates: list[BulletCandidate] = []
    seen_candidate_ids: set[str] = set()
    requirement_ids = {item.id for item in analysis.requirements}
    for index, item in enumerate(_require_list(raw.get("candidates", []), "candidates")):
        if not isinstance(item, dict):
            raise SelectionContractError(f"candidates[{index}]: expected object")
        path = f"candidates[{index}]"
        candidate_id = _require_string(item.get("candidate_id"), f"{path}.candidate_id")
        if candidate_id in seen_candidate_ids:
            raise SelectionContractError(f"{path}.candidate_id: duplicate candidate ID")
        seen_candidate_ids.add(candidate_id)
        candidate_evidence_ids = [_require_string(value, f"{path}.evidence_ids[]") for value in _require_list(item.get("evidence_ids", []), f"{path}.evidence_ids")]
        if any(value not in evidence_by_id for value in candidate_evidence_ids):
            raise SelectionContractError(f"{path}.evidence_ids: unknown evidence ID")
        candidate_requirement_ids = [str(value) for value in item.get("supported_requirement_ids", [])]
        if any(value not in requirement_ids for value in candidate_requirement_ids):
            raise SelectionContractError(f"{path}.supported_requirement_ids: unknown requirement ID")
        candidates.append(
            BulletCandidate(
                candidate_id=candidate_id,
                bullet_id=_require_string(item.get("bullet_id"), f"{path}.bullet_id"),
                evidence_ids=candidate_evidence_ids,
                supported_requirement_ids=candidate_requirement_ids,
                text=_require_string(item.get("text"), f"{path}.text"),
                variation=str(item.get("variation", "model")),
            )
        )
    return SelectionBundle(
        requirements=analysis,
        matches=matches,
        evidence_selection=selection,
        skills=skills,
        candidates=candidates,
        integrity=[],
        rankings=RankingResult([], {}),
        unused_evidence=[],
        provider=provider,
        model=model,
        warnings=[str(value) for value in raw.get("warnings", [])],
        unresolved=[str(value) for value in raw.get("unresolved", [])],
    )


def _all_evidence(profile: MasterProfile, variant: str | None = None) -> dict[str, Any]:
    entries = list(profile.experience) + list(profile.projects)
    allowed: set[str] | None = None
    if variant is not None and variant in profile.base_variants:
        allowed = set(profile.base_variants[variant].bullet_order)
    evidence: dict[str, Any] = {}
    for entry in entries:
        for bullet in entry.bullets:
            if not bullet.is_blocked and (allowed is None or bullet.id in allowed):
                evidence[bullet.id] = bullet
    return evidence


def select_evidence_flexibly(
    analysis: RequirementAnalysis,
    matches: list[EvidenceMatch],
    profile: MasterProfile,
    variant: str,
    *,
    line_budget: int = 22,
) -> list[EvidenceSelection]:
    """Select high-value evidence without fixed per-entry counts."""
    evidence_by_id = _all_evidence(profile, variant)
    requirements = {item.id: item for item in analysis.requirements}
    score_by_id: dict[str, float] = {eid: 0.0 for eid in evidence_by_id}
    reqs_by_id: dict[str, list[str]] = {eid: [] for eid in evidence_by_id}
    for match in matches:
        if match.classification == "gap":
            continue
        class_bonus = {"direct": 1.0, "adjacent": 0.72, "transferable": 0.45}[match.classification]
        for evidence_id in match.evidence_ids:
            if evidence_id in score_by_id:
                score_by_id[evidence_id] = max(score_by_id[evidence_id], match.confidence * match.strength * class_bonus)
                reqs_by_id[evidence_id].append(match.requirement_id)
    ranked = sorted(
        evidence_by_id,
        key=lambda eid: (-score_by_id[eid], evidence_by_id[eid].priority, eid),
    )
    owner_by_eid = {
        bullet.id: entry.id
        for entry in (*profile.experience, *profile.projects)
        for bullet in entry.bullets
    }
    selected: list[str] = []
    owners: Counter[str] = Counter()
    for evidence_id in ranked:
        bullet = evidence_by_id[evidence_id]
        cost = max(1, min(4, len(bullet.phrasings.medium or bullet.phrasings.short) // 70 + 1))
        must_cover = any(requirements[rid].kind == "must_have" for rid in reqs_by_id[evidence_id] if rid in requirements)
        owner = owner_by_eid[evidence_id]
        overrepresented = owners[owner] >= max(2, len(selected) // 2 + 1)
        if score_by_id[evidence_id] <= 0:
            continue
        if len(selected) + cost > line_budget and not must_cover:
            continue
        if overrepresented and any(owner_by_eid[item] != owner for item in ranked if item not in selected and score_by_id[item] > 0):
            continue
        selected.append(evidence_id)
        owners[owner] += 1
    selected_set = set(selected)
    output: list[EvidenceSelection] = []
    for evidence_id in evidence_by_id:
        bullet = evidence_by_id[evidence_id]
        cost = max(1, min(4, len(bullet.phrasings.medium or bullet.phrasings.short) // 70 + 1))
        output.append(
            EvidenceSelection(
                evidence_id=evidence_id,
                selected=evidence_id in selected_set,
                score=round(score_by_id[evidence_id], 4),
                requirement_ids=sorted(set(reqs_by_id[evidence_id])),
                estimated_line_cost=cost,
                rationale=("covers relevant requirements" if evidence_id in selected_set else "lower value under the flexible line budget"),
                omission_reason=None if evidence_id in selected_set else "not selected for relevance/space balance",
            )
        )
    return output


def build_skill_candidates(
    profile: MasterProfile,
    analysis: RequirementAnalysis,
    matches: list[EvidenceMatch],
    selected_evidence_ids: set[str],
) -> list[SkillCandidate]:
    """Propose only canonical terms in existing categories."""
    evidence_by_id = _all_evidence(profile)
    match_by_req = {match.requirement_id: match for match in matches}
    output: list[SkillCandidate] = []
    for category, terms in profile.skills.items():
        for term in terms:
            aliases = get_skill_aliases(term)
            matched_requirements = [
                requirement for requirement in analysis.requirements
                if requirement.kind == "must_have"
                and aliases.intersection(get_skill_aliases(requirement.term))
                and requirement.id in match_by_req
                and match_by_req[requirement.id].classification != "gap"
            ]
            evidence_ids = sorted({eid for requirement in matched_requirements for eid in match_by_req[requirement.id].evidence_ids})
            selected_demo = bool(set(evidence_ids) & selected_evidence_ids)
            include = bool(matched_requirements)
            output.append(
                SkillCandidate(
                    category=category,
                    term=term,
                    include=include,
                    canonical_support=True,
                    selected_demonstration=selected_demo,
                    evidence_ids=evidence_ids,
                    reason=("covered must-have and canonically supported" if include else "not a covered target term"),
                    weak_demo_advisory=include and not selected_demo,
                )
            )
    return output


def _normalized_numbers(text: str) -> Counter[str]:
    def normalize(token: str) -> str:
        return token.lstrip("~+")
    return Counter(normalize(token) for token in extract_numeric_tokens(text))


def _words(text: str) -> list[str]:
    return [word.casefold() for word in _WORD_RE.findall(text)]


def validate_candidate_integrity(
    candidate: BulletCandidate,
    *,
    canonical_text_by_bullet: dict[str, str],
    canonical_evidence_by_bullet: dict[str, list[str]],
    selected_evidence_ids: set[str],
    profile: MasterProfile,
    allowed_new_vocabulary: set[str] | None = None,
) -> CandidateIntegrity:
    findings: list[IntegrityFinding] = []

    def fatal(code: str, message: str) -> None:
        findings.append(IntegrityFinding(code, "fatal", message))

    original = canonical_text_by_bullet.get(candidate.bullet_id)
    if original is None:
        fatal("unknown_bullet", "candidate cites a non-canonical bullet")
        return CandidateIntegrity(candidate.candidate_id, False, findings)
    if not candidate.text.strip() or "\n" in candidate.text or "\r" in candidate.text:
        fatal("shape", "candidate text must be nonempty and single-line")
    plain_candidate = re.sub(r"[*_`]", "", candidate.text)
    plain_original = re.sub(r"[*_`]", "", original)
    if len(plain_candidate) > len(plain_original):
        fatal("line_cost", "candidate is longer than the canonical text")
    expected_evidence = canonical_evidence_by_bullet.get(candidate.bullet_id, [])
    if candidate.evidence_ids != expected_evidence:
        fatal("evidence_identity", "candidate changed the canonical evidence IDs")
    if any(evidence_id not in selected_evidence_ids for evidence_id in candidate.evidence_ids):
        fatal("unselected_evidence", "candidate cites evidence outside the selected set")
    original_match = _LEADING_VERB_RE.search(original.lstrip("* "))
    candidate_match = _LEADING_VERB_RE.search(candidate.text.lstrip("* "))
    if original_match and candidate_match and original_match.group(1).casefold() != candidate_match.group(1).casefold():
        fatal("leading_verb", "candidate changed the canonical leading action verb")
    if _normalized_numbers(candidate.text) != _normalized_numbers(original):
        fatal("numeric_tokens", "candidate changed the normalized numeric-token multiset")
    prohibited = {term.casefold() for term in profile.do_not_claim} | {"kubernetes"}
    candidate_words = set(_words(candidate.text))
    for term in prohibited:
        if term in candidate_words or term in candidate.text.casefold():
            fatal("prohibited_claim", f"candidate contains prohibited term {term!r}")
    if allowed_new_vocabulary is not None:
        original_words = set(_words(original))
        introduced = {
            word for word in candidate_words - original_words
            if word not in _STOP_WORDS and len(word) > 2
        }
        allowed = {word.casefold() for word in allowed_new_vocabulary}
        if introduced - allowed:
            fatal("new_vocabulary", "candidate introduced content vocabulary outside covered motivating terms")
    if candidate.supported_requirement_ids and any(not requirement_id.strip() for requirement_id in candidate.supported_requirement_ids):
        fatal("requirement_ids", "candidate has an empty requirement ID")
    return CandidateIntegrity(candidate.candidate_id, not any(f.severity == "fatal" for f in findings), findings)


def filter_candidates(
    candidates: list[BulletCandidate],
    *,
    canonical_text_by_bullet: dict[str, str],
    canonical_evidence_by_bullet: dict[str, list[str]],
    selected_evidence_ids: set[str],
    profile: MasterProfile,
    allowed_new_vocabulary_by_bullet: dict[str, set[str]] | None = None,
) -> tuple[list[BulletCandidate], list[CandidateIntegrity]]:
    valid: list[BulletCandidate] = []
    findings: list[CandidateIntegrity] = []
    for candidate in candidates:
        integrity = validate_candidate_integrity(
            candidate,
            canonical_text_by_bullet=canonical_text_by_bullet,
            canonical_evidence_by_bullet=canonical_evidence_by_bullet,
            selected_evidence_ids=selected_evidence_ids,
            profile=profile,
            allowed_new_vocabulary=(allowed_new_vocabulary_by_bullet or {}).get(candidate.bullet_id),
        )
        findings.append(integrity)
        if integrity.valid:
            valid.append(candidate)
    return valid, findings


def bound_candidates(candidates: list[BulletCandidate], max_per_bullet: int = 3) -> tuple[list[BulletCandidate], list[str]]:
    """Enforce the small configurable candidate-generation bound deterministically."""
    if max_per_bullet < 1:
        raise ValueError("max_per_bullet must be positive")
    counts: Counter[str] = Counter()
    bounded: list[BulletCandidate] = []
    warnings: list[str] = []
    for candidate in candidates:
        counts[candidate.bullet_id] += 1
        if counts[candidate.bullet_id] <= max_per_bullet:
            bounded.append(candidate)
        else:
            warnings.append(f"candidate bound: dropped {candidate.candidate_id} for bullet {candidate.bullet_id}")
    return bounded, warnings


def _heuristic_components(candidate: BulletCandidate, all_candidates: list[BulletCandidate]) -> dict[str, float]:
    words = _words(candidate.text)
    repeated = len(words) - len(set(words))
    has_metric = bool(extract_numeric_tokens(candidate.text))
    has_mechanism = any(term in candidate.text.casefold() for term in ("using", "through", "via", "with", "by"))
    has_outcome = any(term in candidate.text.casefold() for term in ("reducing", "improving", "increasing", "enabling", "cutting", "to "))
    abstractions = sum(word in _AI_ABSTRACTIONS for word in words)
    duplicate = sum(1 for other in all_candidates if other.candidate_id != candidate.candidate_id and other.text.casefold() == candidate.text.casefold())
    return {
        "clarity": max(1.0, 10.0 - min(6, repeated)),
        "relevance": min(10.0, 5.0 + 2.0 * len(candidate.supported_requirement_ids)),
        "achievement": 9.0 if has_metric or has_outcome else 6.0,
        "metric_interpretability": 10.0 if has_metric else 7.0,
        "defensibility": 9.0 if candidate.evidence_ids else 2.0,
        "mechanism_outcome_balance": 9.0 if has_mechanism and has_outcome else 6.0,
        "redundancy": 2.0 if duplicate else 9.0,
        "ai_abstraction": max(2.0, 10.0 - abstractions * 2.0),
        "recruiter_scan": 10.0 if len(candidate.text) <= 165 else 7.0,
        "line_cost": max(1.0, 10.0 - len(candidate.text) / 45.0),
    }


def rank_candidates(
    candidates: list[BulletCandidate],
    *,
    integrity: list[CandidateIntegrity] | None = None,
    model_rankings: Any = None,
) -> RankingResult:
    """Rank safe candidates; malformed model rankings use a deterministic fallback."""
    safe_ids = {item.candidate_id for item in integrity or [] if item.valid}
    safe = [candidate for candidate in candidates if not safe_ids or candidate.candidate_id in safe_ids]
    warnings: list[str] = []
    model_by_id: dict[str, dict[str, Any]] = {}
    if model_rankings is not None:
        items = model_rankings.get("rankings", model_rankings) if isinstance(model_rankings, dict) else model_rankings
        try:
            ranking_items = _require_list(items, "rankings")
            if not ranking_items:
                warnings.append("ranking fallback: no ranking items")
            for item in ranking_items:
                if not isinstance(item, dict):
                    raise SelectionContractError("ranking item must be an object")
                candidate_id = _require_string(item.get("candidate_id"), "rankings[].candidate_id")
                model_by_id[candidate_id] = item
        except SelectionContractError as exc:
            warnings.append(f"ranking fallback: {exc}")
            model_by_id = {}
    if model_by_id and (
        {candidate.candidate_id for candidate in safe} - set(model_by_id)
        or set(model_by_id) - {candidate.candidate_id for candidate in safe}
    ):
        warnings.append("ranking fallback: incomplete candidate ranking")
        model_by_id = {}
    rankings: list[CandidateRanking] = []
    for candidate in safe:
        model_item = model_by_id.get(candidate.candidate_id)
        if model_item is not None:
            raw_components = model_item.get("component_scores")
            if not isinstance(raw_components, dict) or not raw_components:
                warnings.append("ranking fallback: malformed component scores")
                model_by_id = {}
                rankings = []
                break
            try:
                components = {str(key): float(value) for key, value in raw_components.items()}
                total = float(model_item.get("total_score", sum(components.values())))
            except (TypeError, ValueError) as exc:
                warnings.append(f"ranking fallback: malformed numeric score ({exc})")
                model_by_id = {}
                rankings = []
                break
            rationale = str(model_item.get("rationale", "model-ranked safe candidate"))
        else:
            components = _heuristic_components(candidate, safe)
            total = round(sum(components.values()) / len(components), 4)
            rationale = "deterministic safe-candidate ranking"
        rankings.append(CandidateRanking(candidate.candidate_id, components, total, rationale))
    if not rankings and safe:
        warnings.append("ranking fallback: deterministic component scoring used")
        rankings = [
            CandidateRanking(
                candidate.candidate_id,
                _heuristic_components(candidate, safe),
                round(sum(_heuristic_components(candidate, safe).values()) / 10.0, 4),
                "deterministic safe-candidate ranking",
            )
            for candidate in safe
        ]
    rankings.sort(key=lambda item: (-item.total_score, item.candidate_id))
    selected_by_bullet: dict[str, str] = {}
    for item in rankings:
        candidate = next(candidate for candidate in safe if candidate.candidate_id == item.candidate_id)
        if candidate.bullet_id not in selected_by_bullet:
            selected_by_bullet[candidate.bullet_id] = candidate.candidate_id
    rankings = [
        CandidateRanking(item.candidate_id, item.component_scores, item.total_score, item.rationale, item.candidate_id in selected_by_bullet.values(), item.fallback)
        for item in rankings
    ]
    return RankingResult(rankings, selected_by_bullet, warnings)


def select_whole_resume(
    candidates: list[BulletCandidate],
    ranking: RankingResult,
    *,
    max_bullets: int | None = None,
) -> tuple[list[BulletCandidate], list[str]]:
    """Choose one safe candidate per bullet and surface document-level overlap."""
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    selected = [by_id[candidate_id] for candidate_id in ranking.selected_by_bullet.values() if candidate_id in by_id]
    warnings: list[str] = []
    seen_words: set[str] = set()
    deduplicated: list[BulletCandidate] = []
    for candidate in selected:
        meaningful = {word for word in _words(candidate.text) if word not in _STOP_WORDS}
        if meaningful and len(meaningful & seen_words) >= max(2, len(meaningful) // 2 + 1):
            warnings.append(f"whole-resume review: repetitive candidate {candidate.candidate_id}")
            continue
        seen_words.update(meaningful)
        deduplicated.append(candidate)
    if max_bullets is not None:
        deduplicated = deduplicated[:max_bullets]
    return deduplicated, warnings


def build_unused_evidence_ledger(
    evidence_selection: list[EvidenceSelection],
    selected_evidence_ids: set[str],
    profile: MasterProfile,
) -> list[UnusedEvidence]:
    evidence_by_id = _all_evidence(profile)
    kind_by_id = {
        bullet.id: ("Experience" if entry in profile.experience else "Projects")
        for entry in (*profile.experience, *profile.projects)
        for bullet in entry.bullets
    }
    output: list[UnusedEvidence] = []
    for decision in evidence_selection:
        if decision.evidence_id in selected_evidence_ids or decision.evidence_id not in evidence_by_id:
            continue
        bullet = evidence_by_id[decision.evidence_id]
        likely_section = kind_by_id.get(decision.evidence_id, "Projects")
        output.append(
            UnusedEvidence(
                evidence_id=decision.evidence_id,
                requirement_ids=decision.requirement_ids,
                strength=decision.score,
                likely_section=likely_section,
                estimated_line_cost=decision.estimated_line_cost,
                omission_reason=decision.omission_reason or "not selected",
                redundancy="none recorded" if decision.score > 0 else "low relevance",
                later_page_fill_suitability="good" if decision.score >= 0.5 else "poor",
            )
        )
    return output


def selection_bundle_to_dict(bundle: SelectionBundle) -> dict[str, Any]:
    return asdict(bundle)
