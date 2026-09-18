"""Deterministic adapters for the independent Tailor2 evaluation contract."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from src.profile import Bullet, MasterProfile
from src.tailor2.audit_projection import get_skill_aliases
from src.tailor2.selection_ranking import Requirement


@dataclass(frozen=True)
class SemanticRequirement:
    """A compatibility view over the authoritative selection requirement."""

    requirement: Requirement
    alternative_branches: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return self.requirement.id

    @property
    def quote(self) -> str:
        return self.requirement.quote

    @property
    def interpreted_intent(self) -> str:
        return self.requirement.term

    @property
    def is_alternative_or_group(self) -> bool:
        return len(self.alternative_branches) > 1


def parse_atomic_requirements_semantically(raw_jd: str) -> list[SemanticRequirement]:
    """Extract sentence-level requirements and explicit ``or`` alternatives."""
    if not isinstance(raw_jd, str) or not raw_jd.strip():
        return []
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", raw_jd) if part.strip()]
    requirements: list[SemanticRequirement] = []
    for index, sentence in enumerate(sentences, start=1):
        branches = tuple(
            part.strip(" ,;:")
            for part in re.split(r"\bor\b", sentence, flags=re.IGNORECASE)
            if part.strip(" ,;:")
        )
        requirements.append(
            SemanticRequirement(
                requirement=Requirement(
                    id=f"req_{index}",
                    term=sentence,
                    quote=sentence,
                    kind="must_have",
                    alternative_group_id=f"or_{index}" if len(branches) > 1 else None,
                ),
                alternative_branches=branches if len(branches) > 1 else (),
            )
        )
    return requirements


@dataclass(frozen=True)
class TailoredSkills:
    displayed_skills: tuple[str, ...]
    by_category: dict[str, tuple[str, ...]] = field(default_factory=dict)


def select_tailored_skills(jd_skills: list[str], profile: MasterProfile) -> TailoredSkills:
    """Select only profile-backed skill terms matching JD aliases."""
    requested_aliases = {alias for term in jd_skills for alias in get_skill_aliases(term)}
    banned = {term.casefold() for term in profile.do_not_claim}
    banned.add("kubernetes")
    by_category: dict[str, tuple[str, ...]] = {}
    displayed: list[str] = []
    for category, terms in profile.skills.items():
        selected = tuple(
            term
            for term in terms
            if term.casefold() not in banned
            and get_skill_aliases(term).intersection(requested_aliases)
        )
        if selected:
            by_category[category] = selected
            displayed.extend(selected)
    return TailoredSkills(displayed_skills=tuple(displayed), by_category=by_category)


@dataclass(frozen=True)
class GeneratedBulletCandidate:
    candidate_id: str
    evidence_id: str
    text: str
    score: float
    variation: str


def _bullet_index(profile: MasterProfile) -> dict[str, Bullet]:
    return {
        bullet.id: bullet
        for entry in (*profile.projects, *profile.experience)
        for bullet in entry.bullets
    }


def _candidate_score(text: str) -> float:
    lower = text.casefold()
    score = 0.72
    if any(token in lower for token in ("ensuring", "preventing", "resulting", "reducing", "exactly one")):
        score += 0.10
    if any(token in lower for token in ("using", "with", "through", "by")):
        score += 0.08
    if re.search(r"\d|\bone\b|\beight\b", lower):
        score += 0.05
    if any(token in lower for token in ("idempotent", "atomic", "reservation")):
        score += 0.04
    return round(min(score, 0.99), 4)


def generate_and_rank_bullet_candidates(
    evidence_id: str,
    profile: MasterProfile,
    count: int = 3,
) -> list[GeneratedBulletCandidate]:
    """Rank existing canonical phrasings without inventing a new claim."""
    if count < 1:
        return []
    bullet = _bullet_index(profile).get(evidence_id)
    if bullet is None or bullet.is_blocked:
        return []
    phrasings = (
        ("long", bullet.phrasings.long),
        ("medium", bullet.phrasings.medium),
        ("short", bullet.phrasings.short),
    )
    candidates = [
        GeneratedBulletCandidate(
            candidate_id=f"{evidence_id}_{variation}",
            evidence_id=evidence_id,
            text=text,
            score=_candidate_score(text),
            variation=variation,
        )
        for variation, text in phrasings
        if text is not None
    ]
    candidates.sort(key=lambda item: (-item.score, item.variation))
    return candidates[:count]


@dataclass(frozen=True)
class WholeResumeRanking:
    redundancy_penalty: float
    status: str
    repeated_openings: tuple[str, ...] = ()


def evaluate_whole_resume_ranking(draft: list[str]) -> WholeResumeRanking:
    """Apply a bounded syntactic repetition warning to a draft."""
    openings: list[str] = []
    for text in draft:
        match = re.match(r"\s*([A-Za-z][A-Za-z'-]*)", text)
        if match:
            openings.append(match.group(1).casefold())
    counts = Counter(openings)
    repeated = tuple(sorted(word for word, count in counts.items() if count > 1))
    penalty = round(sum(count - 1 for count in counts.values() if count > 1) / max(len(openings), 1), 4)
    return WholeResumeRanking(
        redundancy_penalty=penalty,
        status="PASS_WITH_WARNING" if repeated else "PASS",
        repeated_openings=repeated,
    )


@dataclass(frozen=True)
class OmittedEvidence:
    evidence_id: str
    reason: str
    priority: int


class UnusedEvidenceLedger:
    """Collect omitted evidence without performing render-time page filling."""

    def __init__(self) -> None:
        self._items: list[OmittedEvidence] = []

    def record_omission(self, *, evidence_id: str, reason: str, priority: int) -> None:
        self._items.append(OmittedEvidence(evidence_id, reason, priority))

    @property
    def items(self) -> tuple[OmittedEvidence, ...]:
        return tuple(self._items)
