import re
from typing import Iterable, Set, Tuple, List
from dataclasses import dataclass
from src.tailor.s2 import S2Response
from src.tailor.alignment_view import AlignmentView

def _norm(v: str) -> str:
    """Phrase normalization: lowercase and collapse whitespace."""
    return " ".join(v.casefold().split())

def contains_normalized_phrase(text: str, phrase: str) -> bool:
    """Mapped-bullet and Skills placement check."""
    return _norm(phrase) in _norm(text)

def document_occurrences(text: str, phrase: str) -> int:
    """Document occurrence counts."""
    n_phrase = _norm(phrase)
    if not n_phrase:
        return 0
    return _norm(text).count(n_phrase)

def get_length_allowance(motivating_terms: Iterable[str]) -> int:
    """Returns max(len(term) for term in motivating_terms), default=0."""
    return max((len(term) for term in motivating_terms), default=0)

def ordered_covered_terms(must_have_terms: Iterable[str], covered_terms: Set[str]) -> list[str]:
    """Ordered covered terms."""
    return [term for term in must_have_terms if term in covered_terms]

@dataclass(frozen=True)
class TermPlacement:
    term: str
    mapped_bullet_ids: tuple[str, ...]
    mapped_bullet_present: bool
    skills_present: bool
    document_occurrence_count: int

def evaluate_placement(must_have_terms: Iterable[str], s2: S2Response,
                       alignment: AlignmentView) -> tuple[TermPlacement, ...]:
    covered_dict = {c.term: tuple(c.bullet_ids) for c in s2.coverage if c.status == "covered"}
    ordered = ordered_covered_terms(must_have_terms, set(covered_dict.keys()))

    by_id = {item.bullet_id: item for item in alignment.bullets}
    skills_lines = [" ".join(items) for _, items in alignment.skills]

    full_text = []
    for b in alignment.bullets:
        full_text.append(b.plain_text)
    full_text.extend(skills_lines)
    full_text_str = " ".join(full_text)

    results = []
    for term in ordered:
        bullet_ids = covered_dict[term]
        mapped_bullets = [by_id[bid].plain_text for bid in bullet_ids if bid in by_id]

        results.append(TermPlacement(
            term=term,
            mapped_bullet_ids=bullet_ids,
            mapped_bullet_present=any(contains_normalized_phrase(b, term) for b in mapped_bullets),
            skills_present=any(contains_normalized_phrase(s, term) for s in skills_lines),
            document_occurrence_count=document_occurrences(full_text_str, term)
        ))
    return tuple(results)
