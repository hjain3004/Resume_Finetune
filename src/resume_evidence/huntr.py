"""Fail-closed parser for explicitly classified Huntr resume examples."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class HuntrExampleKind(str, Enum):
    VERIFIED_INDIVIDUAL = "verified_individual"
    VERIFIED_COMPOSITE = "verified_composite"
    ILLUSTRATIVE = "illustrative"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HuntrExample:
    anchor: str
    heading: str
    target_level: str | None
    kind: HuntrExampleKind
    resume_markdown: str
    outcome_quote: str | None
    limitations: tuple[str, ...]


_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)
_RESUME_EXAMPLE_RE = re.compile(r"\bresume example\b", re.IGNORECASE)
_RESUME_SECTION_RE = re.compile(r"^(?:#{1,6}\s+)?(?:about|summary|experience|work experience|professional experience|education|projects|skills|technical skills|certifications)\s*:?[ \t]*$", re.IGNORECASE)
_OUTCOME_RE = re.compile(r"\b(?:reached|landed|earned|received|accepted|offer stage|offers? at|interviews? at|interview stage|screen)\b", re.IGNORECASE)
_LEVELS = ("new grad", "entry-level", "career change", "junior", "intern", "senior", "staff", "principal", "mid-level")


def _anchor(heading: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", heading.casefold()).strip("-")
    if not value:
        raise ValueError("resume example heading has empty anchor")
    return value


def _target_level(heading: str) -> str | None:
    lowered = heading.casefold()
    return next((level for level in _LEVELS if level in lowered), None)


def _kind(section: str) -> HuntrExampleKind:
    lowered = section.casefold()
    if re.search(r"\billustrative example\b", lowered):
        return HuntrExampleKind.ILLUSTRATIVE
    if re.search(r"\bverified individual\b", lowered):
        return HuntrExampleKind.VERIFIED_INDIVIDUAL
    if re.search(r"\b(?:verified composite|anonymized composite|composite|blended from|built from resumes|reconstructed)\b", lowered):
        return HuntrExampleKind.VERIFIED_COMPOSITE
    return HuntrExampleKind.UNKNOWN


def _outcome_quote(section: str) -> str | None:
    for line in section.splitlines():
        candidate = line.strip()
        if candidate and not candidate.startswith("#") and _OUTCOME_RE.search(candidate):
            return candidate
    return None


def _has_resume_content(section: str) -> bool:
    lines = section.splitlines()
    for index, line in enumerate(lines):
        if _RESUME_SECTION_RE.fullmatch(line.strip()):
            remainder = "\n".join(lines[index + 1:]).strip()
            if remainder:
                return True
    return False


def parse_huntr_examples(markdown: str) -> tuple[HuntrExample, ...]:
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError("Huntr markdown must be nonempty")
    headings = [(match.start(), len(match.group(1)), match.group(2)) for match in _HEADING_RE.finditer(markdown)]
    candidates = [(position, level, heading) for position, level, heading in headings if _RESUME_EXAMPLE_RE.search(heading)]
    if not candidates:
        return ()
    preferred_level = 3 if any(level == 3 for _, level, _ in candidates) else 2
    candidates = [item for item in candidates if item[1] == preferred_level]
    examples: list[HuntrExample] = []
    seen_anchors: set[str] = set()
    for index, (position, level, heading) in enumerate(candidates):
        end = len(markdown)
        candidate_positions = {candidate[0] for candidate in candidates[index + 1:]}
        for next_position, next_level, _ in headings:
            if next_position > position and (next_level < level or next_position in candidate_positions):
                end = next_position
                break
        section = markdown[position:end].strip()
        anchor = _anchor(heading)
        if anchor in seen_anchors:
            raise ValueError(f"duplicate Huntr anchor: {anchor}")
        seen_anchors.add(anchor)
        if not _has_resume_content(section):
            raise ValueError(f"{anchor}: empty or ambiguous resume section")
        kind = _kind(section)
        quote = _outcome_quote(section)
        limitations: list[str] = []
        if kind is HuntrExampleKind.VERIFIED_COMPOSITE:
            limitations.append("publisher-labeled composite or reconstruction")
        if kind is HuntrExampleKind.ILLUSTRATIVE:
            limitations.append("explicitly illustrative")
        if kind is HuntrExampleKind.UNKNOWN:
            limitations.append("no explicit classification label")
        examples.append(HuntrExample(anchor, heading.strip(), _target_level(heading), kind, section, quote, tuple(limitations)))
    return tuple(examples)


def promotable_huntr_examples(examples: tuple[HuntrExample, ...]) -> tuple[HuntrExample, ...]:
    return tuple(item for item in examples if item.kind in {HuntrExampleKind.VERIFIED_INDIVIDUAL, HuntrExampleKind.VERIFIED_COMPOSITE} and item.outcome_quote is not None and item.outcome_quote in item.resume_markdown)
