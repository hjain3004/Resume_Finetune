"""Renderer-agnostic intermediate representation. No I/O, no rendering."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RenderBullet:
    """One bullet. `bullet_id` carries G0 traceability to the renderer boundary.

    `text` is always plain: emphasis markup is stripped at mapping time so L7's
    survival checks compare against exactly what the PDF will contain.
    `emphasis` holds (start, end) half-open offsets into `text`.
    """

    bullet_id: str
    text: str
    emphasis: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class RenderEntry:
    """One education / experience / project entry.

    Defaults are empty because the sources are genuinely asymmetric: projects
    carry no date, and neither projects nor experience carry a location.
    """

    entry_id: str
    heading: str
    subheading: str
    date_range: str = ""
    location: str = ""
    bullets: tuple[RenderBullet, ...] = ()


@dataclass(frozen=True)
class RenderDoc:
    """What we intend the PDF to say. L7 asserts the PDF actually says it."""

    identity: dict[str, str]
    education: tuple[RenderEntry, ...]
    experience: tuple[RenderEntry, ...]
    projects: tuple[RenderEntry, ...]
    skills: dict[str, tuple[str, ...]]
    section_order: tuple[str, ...]
    ats: dict[str, Any]

    def all_bullets(self) -> tuple[RenderBullet, ...]:
        """Every bullet across all sections, in document order."""
        return tuple(
            bullet
            for group in (self.education, self.experience, self.projects)
            for entry in group
            for bullet in entry.bullets
        )

    def all_skill_terms(self) -> tuple[str, ...]:
        return tuple(term for terms in self.skills.values() for term in terms)
