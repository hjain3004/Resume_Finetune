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
class HuntrPageContext:
    methodology_quote: str | None
    reconstruction_quote: str | None
    publisher_outcome_linked: bool
    publisher_reconstructed: bool
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class HuntrExample:
    anchor: str
    heading: str
    target_level: str | None
    kind: HuntrExampleKind
    resume_markdown: str
    outcome_quote: str | None
    page_methodology_quote: str | None
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class HuntrPage:
    source_markdown: str
    context: HuntrPageContext
    examples: tuple[HuntrExample, ...]


@dataclass(frozen=True)
class _Heading:
    start: int
    level: int
    text: str


_HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$", re.MULTILINE)
_RESUME_EXAMPLE_RE = re.compile(r"\bresume example\b", re.IGNORECASE)
_RESUME_SECTION_RE = re.compile(r"^(?:#{1,6}\s+)?(?:about|summary|experience|work experience|professional experience|education|projects|skills|technical skills|certifications)\s*:?[ \t]*$", re.IGNORECASE)
_OUTCOME_RE = re.compile(r"\b(?:reached|landed|earned|received|accepted|offer stage|offers? at|interviews? at|interview stage|screen)\b", re.IGNORECASE)
_OUTCOME_PROVENANCE_RE = re.compile(r"\b(?:logged|tracked|real)\b.{0,100}\b(?:interview|offer|screen)s?\b|\b(?:interview|offer|screen)s?\b.{0,100}\b(?:logged|tracked|real)\b", re.IGNORECASE)
_RECONSTRUCTION_RE = re.compile(r"\b(?:reconstruct(?:ed|ion)?|rebuild(?:ing|built)?|anonymi[sz](?:ed|ation)|composite|blended)\b", re.IGNORECASE)
_LEVELS = ("new grad", "entry-level", "career change", "junior", "intern", "senior", "staff", "principal", "mid-level")


def _anchor(heading: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", heading.casefold()).strip("-")
    if not value:
        raise ValueError("resume example heading has empty anchor")
    return value


def _target_level(heading: str) -> str | None:
    lowered = heading.casefold()
    return next((level for level in _LEVELS if level in lowered), None)


def _headings(markdown: str) -> tuple[_Heading, ...]:
    return tuple(_Heading(match.start(), len(match.group(1)), match.group(2)) for match in _HEADING_RE.finditer(markdown))


def _candidate_spans(markdown: str, headings: tuple[_Heading, ...]) -> tuple[tuple[_Heading, int, int], ...]:
    candidates = [(index, heading) for index, heading in enumerate(headings) if _RESUME_EXAMPLE_RE.search(heading.text)]
    filtered: list[tuple[int, _Heading]] = []
    for candidate_position, (heading_index, heading) in enumerate(candidates):
        end = len(markdown)
        for following in headings[heading_index + 1:]:
            if following.level < heading.level:
                end = following.start
                break
        if candidate_position + 1 < len(candidates):
            end = min(end, candidates[candidate_position + 1][1].start)
        if candidate_position + 1 < len(candidates) and candidates[candidate_position + 1][1].level > heading.level:
            if not _has_resume_content(markdown[heading.start:end]):
                continue
        filtered.append((heading_index, heading))
    candidates = filtered
    spans: list[tuple[_Heading, int, int]] = []
    for candidate_index, (heading_index, heading) in enumerate(candidates):
        end = len(markdown)
        for following in headings[heading_index + 1:]:
            if following.level < heading.level:
                end = following.start
                break
        if candidate_index + 1 < len(candidates):
            end = min(end, candidates[candidate_index + 1][1].start)
        spans.append((heading, heading.start, end))
    return tuple(spans)


def _page_context(markdown: str, spans: tuple[tuple[_Heading, int, int], ...]) -> HuntrPageContext:
    page_lines: list[str] = []
    cursor = 0
    for _, start, end in spans:
        page_lines.extend(markdown[cursor:start].splitlines())
        cursor = end
    page_lines.extend(markdown[cursor:].splitlines())
    lines = [line.strip() for line in page_lines if line.strip() and not line.lstrip().startswith("#")]
    provenance = next((line for line in lines if _OUTCOME_PROVENANCE_RE.search(line)), None)
    reconstruction = next((line for line in lines if _RECONSTRUCTION_RE.search(line)), None)
    limitations: list[str] = []
    if reconstruction:
        limitations.append("publisher methodology describes reconstructed or anonymized examples")
    if not provenance:
        limitations.append("page-level outcome provenance is not explicit")
    return HuntrPageContext(
        methodology_quote=reconstruction or provenance,
        reconstruction_quote=reconstruction,
        publisher_outcome_linked=provenance is not None,
        publisher_reconstructed=provenance is not None and reconstruction is not None,
        limitations=tuple(limitations),
    )


def _outcome_quote(section: str) -> str | None:
    for line in section.splitlines():
        candidate = line.strip()
        if candidate and not candidate.startswith("#") and _OUTCOME_RE.search(candidate):
            return candidate
    return None


def _has_resume_content(section: str) -> bool:
    lines = section.splitlines()
    for index, line in enumerate(lines):
        if _RESUME_SECTION_RE.fullmatch(line.strip()) and "\n".join(lines[index + 1:]).strip():
            return True
    return False


def _metadata_prefix(section: str) -> str:
    lines = section.splitlines()
    for index, line in enumerate(lines):
        if _RESUME_SECTION_RE.fullmatch(line.strip()):
            return "\n".join(lines[:index])
    return section


def _kind(section: str, context: HuntrPageContext, outcome_quote: str | None) -> HuntrExampleKind:
    lowered = _metadata_prefix(section).casefold()
    if re.search(r"\billustrative example\b", lowered):
        return HuntrExampleKind.ILLUSTRATIVE
    if re.search(r"\bverified individual\b", lowered):
        return HuntrExampleKind.VERIFIED_INDIVIDUAL
    if re.search(r"\b(?:verified composite|anonymized composite|composite|blended from|built from resumes|reconstructed)\b", lowered):
        return HuntrExampleKind.VERIFIED_COMPOSITE
    if context.publisher_reconstructed and outcome_quote is not None:
        return HuntrExampleKind.VERIFIED_COMPOSITE
    return HuntrExampleKind.UNKNOWN


def parse_huntr_page(markdown: str) -> HuntrPage:
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError("Huntr markdown must be nonempty")
    headings = _headings(markdown)
    spans = _candidate_spans(markdown, headings)
    context = _page_context(markdown, spans)
    examples: list[HuntrExample] = []
    seen_anchors: set[str] = set()
    for heading, start, end in spans:
        section = markdown[start:end].strip()
        anchor = _anchor(heading.text)
        if anchor in seen_anchors:
            raise ValueError(f"duplicate Huntr anchor: {anchor}")
        seen_anchors.add(anchor)
        if not _has_resume_content(section):
            raise ValueError(f"{anchor}: empty or ambiguous resume section")
        outcome_quote = _outcome_quote(section)
        kind = _kind(section, context, outcome_quote)
        limitations = list(context.limitations)
        if kind is HuntrExampleKind.VERIFIED_COMPOSITE:
            limitations.append("publisher-labeled composite or reconstruction")
        if kind is HuntrExampleKind.ILLUSTRATIVE:
            limitations.append("explicitly illustrative")
        if kind is HuntrExampleKind.UNKNOWN:
            limitations.append("no explicit classification label")
        examples.append(HuntrExample(anchor, heading.text.strip(), _target_level(heading.text), kind, section, outcome_quote, context.methodology_quote, tuple(dict.fromkeys(limitations))))
    return HuntrPage(markdown, context, tuple(examples))


def parse_huntr_examples(markdown: str) -> tuple[HuntrExample, ...]:
    """Backward-compatible projection of the page parser."""
    return parse_huntr_page(markdown).examples


def promotable_huntr_examples(page_or_examples: HuntrPage | tuple[HuntrExample, ...]) -> tuple[HuntrExample, ...]:
    page = page_or_examples if isinstance(page_or_examples, HuntrPage) else None
    examples = page.examples if page is not None else page_or_examples
    promotable: list[HuntrExample] = []
    for item in examples:
        has_exact_outcome = item.outcome_quote is not None and item.outcome_quote in item.resume_markdown
        if item.kind is HuntrExampleKind.VERIFIED_INDIVIDUAL and has_exact_outcome:
            promotable.append(item)
        elif item.kind is HuntrExampleKind.VERIFIED_COMPOSITE and has_exact_outcome and item.page_methodology_quote is not None:
            promotable.append(item)
    return tuple(promotable)
