"""Deterministic render-measure-expand/compress optimization for Tailor2.

This module deliberately has no provider or filesystem side effects.  The lane
supplies a renderer callback which materializes one bounded candidate at a
time, while this module compares the resulting measurements and preserves the
best safe artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from enum import Enum
from difflib import SequenceMatcher
from typing import Any

from src.profile import MasterProfile
from src.render.lines import RenderedPage
from src.render.model import RenderDoc
from src.render.parse import ParsedPdf
from src.tailor2.models import DraftBullet, DraftResponse
from src.tailor2.severity import RunStatus
from src.tailor2.selection_ranking import UnusedEvidence
from src.tailor2.validators import CANONICAL_AMDOCS_BULLETS


class LayoutState(str, Enum):
    CLEAN_FIT = "clean_fit"
    MEANINGFUL_UNDERFILL = "meaningful_underfill"
    MINOR_UNDERFILL = "minor_underfill"
    SLIGHT_OVERFLOW = "slight_overflow"
    SUBSTANTIAL_OVERFLOW = "substantial_overflow"
    COLLISION_OR_CLIPPING = "collision_or_clipping"
    UNREADABLY_COMPRESSED = "unreadably_compressed"
    RENDER_FAILURE = "render_failure"


LayoutStatus = LayoutState
_TEXT_GEOMETRY_TOLERANCE_PT = 4.0


@dataclass(frozen=True)
class RenderFillConfig:
    """Hard bounds and current-template geometry constraints."""

    max_render_iterations: int = 8
    max_expansion_attempts: int = 3
    max_compression_attempts: int = 4
    max_provider_rewrites: int = 0
    max_renderer_failures: int = 1
    max_bullet_edits: int = 8
    max_token_edit_distance_ratio: float = 0.15
    minimum_margin_pt: float = 14.4
    minimum_font_pt: float = 8.0
    meaningful_underfill_pt: float = 42.0
    minor_underfill_pt: float = 18.0
    slight_overflow_pt: float = 18.0

    def __post_init__(self) -> None:
        for name in (
            "max_render_iterations",
            "max_expansion_attempts",
            "max_compression_attempts",
            "max_provider_rewrites",
            "max_renderer_failures",
            "max_bullet_edits",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        for name in (
            "minimum_margin_pt",
            "minimum_font_pt",
            "meaningful_underfill_pt",
            "minor_underfill_pt",
            "slight_overflow_pt",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if not 0 <= self.max_token_edit_distance_ratio <= 1:
            raise ValueError("max_token_edit_distance_ratio must be between 0 and 1")
        if self.max_render_iterations == 0:
            raise ValueError("max_render_iterations must be positive")
        if self.meaningful_underfill_pt < self.minor_underfill_pt:
            raise ValueError("meaningful_underfill_pt must be >= minor_underfill_pt")


@dataclass(frozen=True)
class RenderMeasurement:
    page_count: int
    page_width: float
    page_height: float
    usable_bottom: float
    usable_top: float
    occupied_bottom: float
    occupied_top: float
    occupied_vertical_extent: float
    remaining_usable_space: float
    overflow_pt: float
    text_outside_page_bounds: tuple[str, ...] = ()
    section_collisions: tuple[str, ...] = ()
    header_date_collisions: tuple[str, ...] = ()
    suspicious_line_wrapping: tuple[str, ...] = ()
    minimum_font_pt: float = 0.0
    minimum_margin_pt: float = 0.0
    excessive_compression: bool = False
    render_succeeded: bool = True
    l7_violations: tuple[str, ...] = ()

    @property
    def usable_height(self) -> float:
        return max(0.0, self.usable_top - self.usable_bottom)

    @property
    def fill_ratio(self) -> float:
        if self.usable_height <= 0:
            return 0.0
        return min(1.0, max(0.0, self.occupied_vertical_extent / self.usable_height))


@dataclass(frozen=True)
class OptimizationCandidate:
    candidate_id: str
    action: str
    draft: Any
    evidence_ids: tuple[str, ...] = ()
    value_score: float = 0.0
    clarity_score: float = 0.0
    estimated_line_cost: int = 1
    stage: int = 0
    provider_assisted: bool = False
    provider: str = ""
    model: str = ""
    reason: str = ""


@dataclass(frozen=True)
class RenderAttempt:
    candidate_id: str
    iteration: int
    draft: Any
    measurement: RenderMeasurement
    state: LayoutState
    factual_integrity: bool = True
    evidence_value: float = 0.0
    clarity_score: float = 0.0
    candidate_fingerprint: str = ""
    tex_path: str = ""
    pdf_path: str = ""
    render_error: str = ""


@dataclass(frozen=True)
class OptimizationIteration:
    iteration_number: int
    candidate_id: str
    action: str
    state: LayoutState
    accepted: bool
    decision: str
    candidate_fingerprint: str
    measurement: RenderMeasurement
    tex_path: str = ""
    pdf_path: str = ""
    provider: str = ""
    model: str = ""


@dataclass(frozen=True)
class OptimizationResult:
    best_attempt: RenderAttempt | None
    iterations: tuple[OptimizationIteration, ...]
    final_state: LayoutState
    status: RunStatus
    warnings: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    config: RenderFillConfig = field(default_factory=RenderFillConfig)

    def to_manifest_dict(self) -> dict[str, Any]:
        best = _attempt_to_dict(self.best_attempt) if self.best_attempt else None
        return {
            "schema_version": "1.0",
            "config": asdict(self.config),
            "status": self.status.value,
            "final_state": self.final_state.value,
            "best_attempt": best,
            "iterations": [
                {
                    "iteration_number": item.iteration_number,
                    "candidate_id": item.candidate_id,
                    "action": item.action,
                    "state": item.state.value,
                    "accepted": item.accepted,
                    "decision": item.decision,
                    "candidate_fingerprint": item.candidate_fingerprint,
                    "measurement": _measurement_to_dict(item.measurement),
                    "tex_path": item.tex_path,
                    "pdf_path": item.pdf_path,
                    "provider": item.provider,
                    "model": item.model,
                }
                for item in self.iterations
            ],
            "warnings": list(self.warnings),
            "unresolved": list(self.unresolved),
        }


def candidate_fingerprint(value: Any) -> str:
    """Return a stable identity for a candidate draft."""
    if is_dataclass(value):
        payload: Any = asdict(value)
    else:
        payload = value
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def measure_rendered_layout(
    doc: RenderDoc,
    parsed: ParsedPdf,
    pages: Sequence[RenderedPage],
    *,
    config: RenderFillConfig | None = None,
) -> RenderMeasurement:
    """Measure actual PDF text geometry against the current template margins."""
    config = config or RenderFillConfig()
    if parsed.page_count <= 0 or not pages:
        return RenderMeasurement(
            page_count=parsed.page_count,
            page_width=parsed.page_width,
            page_height=parsed.page_height,
            usable_bottom=config.minimum_margin_pt,
            usable_top=max(config.minimum_margin_pt, parsed.page_height - config.minimum_margin_pt),
            occupied_bottom=0.0,
            occupied_top=0.0,
            occupied_vertical_extent=0.0,
            remaining_usable_space=0.0,
            overflow_pt=0.0,
            render_succeeded=False,
            l7_violations=("no rendered page",),
        )

    boxes = tuple(parsed.boxes)
    occupied_bottom = min((box.y0 for box in boxes), default=0.0)
    occupied_top = max((box.y1 for box in boxes), default=0.0)
    usable_bottom = config.minimum_margin_pt
    usable_top = max(usable_bottom, parsed.page_height - config.minimum_margin_pt)
    outside: list[str] = []
    minimum_margin = float("inf")
    for box in boxes:
        distances = (
            box.x0,
            parsed.page_width - box.x1,
            box.y0,
            parsed.page_height - box.y1,
        )
        minimum_margin = min(minimum_margin, *distances)
        if min(distances) < -1.0:
            outside.append(f"page {box.page}: {box.text[:80]}")

    collisions = _find_box_collisions(boxes)
    header_date_collisions = _find_header_date_collisions(boxes)
    wrapping = _find_suspicious_wrapping(pages)
    l7_violations = tuple(outside + collisions + header_date_collisions)
    if minimum_margin == float("inf"):
        minimum_margin = 0.0
    overflow = max(
        0.0,
        usable_bottom - occupied_bottom - _TEXT_GEOMETRY_TOLERANCE_PT,
        occupied_top - usable_top - _TEXT_GEOMETRY_TOLERANCE_PT,
    )
    if parsed.page_count > 1:
        overflow += (parsed.page_count - 1) * max(usable_top - usable_bottom, 0.0)
    minimum_font = min(
        (line.max_font_size for page in pages for line in page.lines),
        default=0.0,
    )
    excessive = (
        minimum_font > 0.0 and minimum_font < config.minimum_font_pt
    ) or minimum_margin < config.minimum_margin_pt - _TEXT_GEOMETRY_TOLERANCE_PT
    return RenderMeasurement(
        page_count=parsed.page_count,
        page_width=parsed.page_width,
        page_height=parsed.page_height,
        usable_bottom=usable_bottom,
        usable_top=usable_top,
        occupied_bottom=occupied_bottom,
        occupied_top=occupied_top,
        occupied_vertical_extent=max(0.0, occupied_top - occupied_bottom),
        remaining_usable_space=max(0.0, occupied_bottom - usable_bottom),
        overflow_pt=overflow,
        text_outside_page_bounds=tuple(outside),
        section_collisions=tuple(collisions),
        header_date_collisions=tuple(header_date_collisions),
        suspicious_line_wrapping=tuple(wrapping),
        minimum_font_pt=minimum_font,
        minimum_margin_pt=minimum_margin,
        excessive_compression=excessive,
        render_succeeded=True,
        l7_violations=l7_violations,
    )


def classify_layout(
    measurement: RenderMeasurement,
    *,
    config: RenderFillConfig | None = None,
) -> LayoutState:
    config = config or RenderFillConfig()
    if not measurement.render_succeeded or measurement.page_count <= 0:
        return LayoutState.RENDER_FAILURE
    if (
        measurement.text_outside_page_bounds
        or measurement.section_collisions
        or measurement.header_date_collisions
    ):
        return LayoutState.COLLISION_OR_CLIPPING
    if measurement.excessive_compression:
        return LayoutState.UNREADABLY_COMPRESSED
    if measurement.page_count > 1 or measurement.overflow_pt > 0:
        if measurement.overflow_pt <= config.slight_overflow_pt and measurement.page_count <= 1:
            return LayoutState.SLIGHT_OVERFLOW
        return LayoutState.SUBSTANTIAL_OVERFLOW
    if measurement.remaining_usable_space >= config.meaningful_underfill_pt:
        return LayoutState.MEANINGFUL_UNDERFILL
    if measurement.remaining_usable_space >= config.minor_underfill_pt:
        return LayoutState.MINOR_UNDERFILL
    return LayoutState.CLEAN_FIT


measure_layout = measure_rendered_layout
classify_layout_state = classify_layout


def layout_state_rank(state: LayoutState) -> int:
    return {
        LayoutState.RENDER_FAILURE: 0,
        LayoutState.COLLISION_OR_CLIPPING: 1,
        LayoutState.UNREADABLY_COMPRESSED: 2,
        LayoutState.SUBSTANTIAL_OVERFLOW: 3,
        LayoutState.SLIGHT_OVERFLOW: 4,
        LayoutState.MEANINGFUL_UNDERFILL: 5,
        LayoutState.MINOR_UNDERFILL: 6,
        LayoutState.CLEAN_FIT: 7,
    }[state]


def _find_box_collisions(boxes: Sequence[Any]) -> list[str]:
    collisions: list[str] = []
    for index, left in enumerate(boxes):
        for right in boxes[index + 1 :]:
            if left.page != right.page:
                continue
            horizontal = left.x0 < right.x1 and right.x0 < left.x1
            vertical = left.y0 < right.y1 and right.y0 < left.y1
            vertical_overlap = min(left.y1, right.y1) - max(left.y0, right.y0)
            if horizontal and vertical_overlap > 1.0 and left.text.strip() and right.text.strip():
                collisions.append(f"page {left.page}: {left.text[:40]} / {right.text[:40]}")
                if len(collisions) >= 16:
                    return collisions
    return collisions


def _find_header_date_collisions(boxes: Sequence[Any]) -> list[str]:
    date_pattern = re.compile(r"\b(?:19|20)\d{2}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")
    headings = [box for box in boxes if box.text.strip() in {"Education", "Experience", "Projects", "Skills", "Technical Skills"}]
    dates = [box for box in boxes if date_pattern.search(box.text)]
    result: list[str] = []
    for heading in headings:
        for date in dates:
            if heading.page != date.page:
                continue
            if heading.x0 < date.x1 and date.x0 < heading.x1 and heading.y0 < date.y1 and date.y0 < heading.y1:
                result.append(f"page {heading.page}: heading/date overlap")
    return result


def _find_suspicious_wrapping(pages: Sequence[RenderedPage]) -> list[str]:
    result: list[str] = []
    for page in pages:
        for line in page.lines:
            text = line.text.strip()
            if text.endswith("-") or text in {"-", "•"}:
                result.append(f"page {page.number}: {text[:80]}")
    return result


def _measurement_to_dict(measurement: RenderMeasurement) -> dict[str, Any]:
    result = asdict(measurement)
    for key in ("text_outside_page_bounds", "section_collisions", "header_date_collisions", "suspicious_line_wrapping", "l7_violations"):
        result[key] = list(result[key])
    return result


def _attempt_to_dict(attempt: RenderAttempt | None) -> dict[str, Any] | None:
    if attempt is None:
        return None
    return {
        "candidate_id": attempt.candidate_id,
        "iteration": attempt.iteration,
        "state": attempt.state.value,
        "factual_integrity": attempt.factual_integrity,
        "evidence_value": attempt.evidence_value,
        "clarity_score": attempt.clarity_score,
        "candidate_fingerprint": attempt.candidate_fingerprint,
        "tex_path": attempt.tex_path,
        "pdf_path": attempt.pdf_path,
        "render_error": attempt.render_error,
        "measurement": _measurement_to_dict(attempt.measurement),
    }


def _failure_measurement(error: str) -> RenderMeasurement:
    return RenderMeasurement(
        page_count=0,
        page_width=0.0,
        page_height=0.0,
        usable_bottom=0.0,
        usable_top=0.0,
        occupied_bottom=0.0,
        occupied_top=0.0,
        occupied_vertical_extent=0.0,
        remaining_usable_space=0.0,
        overflow_pt=0.0,
        render_succeeded=False,
        l7_violations=(error,),
    )


def _attempt_is_safe(attempt: RenderAttempt) -> bool:
    return (
        attempt.factual_integrity
        and attempt.measurement.render_succeeded
        and attempt.state not in {
            LayoutState.COLLISION_OR_CLIPPING,
            LayoutState.UNREADABLY_COMPRESSED,
            LayoutState.RENDER_FAILURE,
        }
    )


def _attempt_is_better(candidate: RenderAttempt, current: RenderAttempt) -> bool:
    if not _attempt_is_safe(candidate):
        return False
    candidate_rank = layout_state_rank(candidate.state)
    current_rank = layout_state_rank(current.state)
    if candidate_rank != current_rank:
        return candidate_rank > current_rank
    if candidate.evidence_value != current.evidence_value:
        return candidate.evidence_value > current.evidence_value
    if candidate.clarity_score != current.clarity_score:
        return candidate.clarity_score > current.clarity_score
    return candidate.measurement.fill_ratio > current.measurement.fill_ratio + 0.01


def _draft_bullet_texts(draft: Any) -> dict[str, str]:
    bullets = getattr(draft, "bullets", None)
    if bullets is None:
        return {}
    return {str(item.bullet_id): str(item.text) for item in bullets}


def _edit_budget_ok(initial_draft: Any, candidate_draft: Any, config: RenderFillConfig) -> bool:
    initial = _draft_bullet_texts(initial_draft)
    candidate = _draft_bullet_texts(candidate_draft)
    changed = sum(initial.get(key) != value for key, value in candidate.items())
    changed += sum(key not in candidate for key in initial)
    if changed > config.max_bullet_edits:
        return False
    initial_tokens = re.findall(r"\b[\w%+~.-]+\b", " ".join(initial.values()))
    candidate_tokens = re.findall(r"\b[\w%+~.-]+\b", " ".join(candidate.values()))
    matcher = SequenceMatcher(a=initial_tokens, b=candidate_tokens, autojunk=False)
    distance = sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )
    denominator = max(1, len(initial_tokens))
    return distance / denominator <= config.max_token_edit_distance_ratio


def _candidate_sort_key(item: OptimizationCandidate) -> tuple[Any, ...]:
    if item.action == "remove":
        return (item.stage, item.value_score, item.estimated_line_cost, item.candidate_id)
    return (item.stage, -item.value_score, -item.clarity_score, item.estimated_line_cost, item.candidate_id)


def optimize_render_fill(
    initial_draft: Any,
    render: Callable[[Any, int, OptimizationCandidate | None], RenderAttempt],
    *,
    expansion_candidates: Iterable[OptimizationCandidate] = (),
    compression_candidates: Iterable[OptimizationCandidate] = (),
    config: RenderFillConfig | None = None,
    resume_manifest: dict[str, Any] | None = None,
    resume_best: RenderAttempt | None = None,
) -> OptimizationResult:
    """Run a bounded deterministic search over safe content candidates."""
    config = config or RenderFillConfig()
    completed = {
        str(item.get("candidate_id"))
        for item in (resume_manifest or {}).get("iterations", [])
        if isinstance(item, dict)
    }
    iterations: list[OptimizationIteration] = []
    warnings: list[str] = []
    unresolved: list[str] = []

    if resume_best is not None:
        best = resume_best
    else:
        initial_id = "initial"
        try:
            best = render(initial_draft, 0, None)
        except Exception as exc:  # renderer failures are an explicit outcome
            best = RenderAttempt(
                candidate_id=initial_id,
                iteration=0,
                draft=initial_draft,
                measurement=_failure_measurement(str(exc)),
                state=LayoutState.RENDER_FAILURE,
                factual_integrity=False,
                candidate_fingerprint=candidate_fingerprint(initial_draft),
                render_error=str(exc),
            )
        if not best.candidate_fingerprint:
            best = replace(best, candidate_fingerprint=candidate_fingerprint(best.draft))
        if not _attempt_is_safe(best):
            unresolved.append("initial render did not produce a safe usable artifact")
        completed.add(initial_id)

    candidates = list(expansion_candidates) + list(compression_candidates)
    candidates.sort(key=_candidate_sort_key)
    attempted = set(completed)
    expansion_count = 0
    compression_count = 0
    renderer_failures = 0
    iteration_number = len(iterations) + 1

    while best is not None and iteration_number < config.max_render_iterations:
        if best.state in {LayoutState.CLEAN_FIT, LayoutState.COLLISION_OR_CLIPPING, LayoutState.UNREADABLY_COMPRESSED, LayoutState.RENDER_FAILURE}:
            break
        desired_actions = {"expand", "richer_variant"} if best.state in {LayoutState.MEANINGFUL_UNDERFILL, LayoutState.MINOR_UNDERFILL} else {"shorten", "rewrite", "remove", "spacing"}
        pending = [item for item in candidates if item.candidate_id not in attempted and item.action in desired_actions]
        if not pending:
            break
        candidate = pending[0]
        if candidate.action in {"expand", "richer_variant"}:
            if expansion_count >= config.max_expansion_attempts:
                break
            expansion_count += 1
        else:
            if compression_count >= config.max_compression_attempts:
                break
            compression_count += 1
        if candidate.provider_assisted:
            provider_attempts = sum(1 for item in iterations if item.provider)
            if provider_attempts >= config.max_provider_rewrites:
                attempted.add(candidate.candidate_id)
                continue
        attempted.add(candidate.candidate_id)
        if not _edit_budget_ok(initial_draft, candidate.draft, config):
            iterations.append(
                OptimizationIteration(
                    iteration_number=iteration_number,
                    candidate_id=candidate.candidate_id,
                    action=candidate.action,
                    state=best.state,
                    accepted=False,
                    decision="rejected: edit budget exceeded",
                    candidate_fingerprint=candidate_fingerprint(candidate.draft),
                    measurement=best.measurement,
                )
            )
            iteration_number += 1
            continue
        try:
            attempt = render(candidate.draft, iteration_number, candidate)
        except Exception as exc:
            attempt = RenderAttempt(
                candidate_id=candidate.candidate_id,
                iteration=iteration_number,
                draft=candidate.draft,
                measurement=_failure_measurement(str(exc)),
                state=LayoutState.RENDER_FAILURE,
                factual_integrity=False,
                evidence_value=candidate.value_score,
                clarity_score=candidate.clarity_score,
                candidate_fingerprint=candidate_fingerprint(candidate.draft),
                render_error=str(exc),
            )
        if not attempt.candidate_fingerprint:
            attempt = replace(attempt, candidate_fingerprint=candidate_fingerprint(attempt.draft))
        accepted = _attempt_is_better(attempt, best)
        decision = "accepted" if accepted else "rejected: not better than latest safe artifact"
        if not _attempt_is_safe(attempt):
            decision = "rejected: unsafe render or factual integrity failure"
        iterations.append(
            OptimizationIteration(
                iteration_number=iteration_number,
                candidate_id=candidate.candidate_id,
                action=candidate.action,
                state=attempt.state,
                accepted=accepted,
                decision=decision,
                candidate_fingerprint=attempt.candidate_fingerprint,
                measurement=attempt.measurement,
                tex_path=attempt.tex_path,
                pdf_path=attempt.pdf_path,
                provider=candidate.provider,
                model=candidate.model,
            )
        )
        if accepted:
            best = attempt
        elif attempt.state in {LayoutState.RENDER_FAILURE, LayoutState.COLLISION_OR_CLIPPING, LayoutState.UNREADABLY_COMPRESSED}:
            warnings.append(f"{candidate.candidate_id}: {attempt.state.value}")
        if attempt.state is LayoutState.RENDER_FAILURE:
            renderer_failures += 1
            if renderer_failures >= config.max_renderer_failures:
                iteration_number += 1
                break
        iteration_number += 1

    if best is None or not _attempt_is_safe(best):
        status = RunStatus.REJECTED_FATAL
        final_state = LayoutState.RENDER_FAILURE if best is None else best.state
    else:
        final_state = best.state
        if final_state in {LayoutState.CLEAN_FIT}:
            status = RunStatus.ACCEPTED
        elif final_state in {LayoutState.MINOR_UNDERFILL, LayoutState.MEANINGFUL_UNDERFILL}:
            status = RunStatus.ACCEPTED_WITH_WARNINGS
            warnings.append(f"render fill ended at {final_state.value}")
        else:
            status = RunStatus.NEEDS_HUMAN_REVIEW
            unresolved.append(f"render fill ended at {final_state.value}")
    return OptimizationResult(
        best_attempt=best,
        iterations=tuple(iterations),
        final_state=final_state,
        status=status,
        warnings=tuple(dict.fromkeys(warnings)),
        unresolved=tuple(dict.fromkeys(unresolved)),
        config=config,
    )


optimize_layout = optimize_render_fill


def _profile_bullets(profile: MasterProfile) -> dict[str, tuple[Any, Any]]:
    return {
        bullet.id: (entry, bullet)
        for entry in (*profile.experience, *profile.projects)
        for bullet in entry.bullets
    }


def _replace_bullet(draft: DraftResponse, bullet_id: str, text: str) -> DraftResponse:
    bullets = [replace(item, text=text) if item.bullet_id == bullet_id else item for item in draft.bullets]
    return replace(draft, bullets=bullets)


def _current_text(draft: DraftResponse, bullet_id: str) -> str:
    for bullet in draft.bullets:
        if bullet.bullet_id == bullet_id:
            return bullet.text
    return ""


def build_richer_variant_candidates(draft: DraftResponse, profile: MasterProfile) -> list[OptimizationCandidate]:
    catalog = _profile_bullets(profile)
    result: list[OptimizationCandidate] = []
    for item in draft.bullets:
        evidence_id = item.evidence_ids[0] if item.evidence_ids else item.bullet_id
        source = catalog.get(evidence_id)
        if source is None:
            continue
        _, canonical = source
        current = item.text
        for tier, text in (("medium", canonical.phrasings.medium), ("long", canonical.phrasings.long)):
            if text and len(text) > len(current) and "\n" not in text:
                result.append(
                    OptimizationCandidate(
                        candidate_id=f"richer:{item.bullet_id}:{tier}",
                        action="richer_variant",
                        draft=_replace_bullet(draft, item.bullet_id, text),
                        evidence_ids=tuple(item.evidence_ids),
                        value_score=len(text) / 1000.0,
                        clarity_score=0.2,
                        estimated_line_cost=max(1, len(text) // 70),
                        reason=f"canonical {tier} phrasing",
                    )
                )
    return result


def build_shorter_variant_candidates(draft: DraftResponse, profile: MasterProfile) -> list[OptimizationCandidate]:
    catalog = _profile_bullets(profile)
    result: list[OptimizationCandidate] = []
    for item in draft.bullets:
        evidence_id = item.evidence_ids[0] if item.evidence_ids else item.bullet_id
        source = catalog.get(evidence_id)
        if source is None:
            continue
        _, canonical = source
        current = item.text
        for tier, text in (("medium", canonical.phrasings.medium), ("short", canonical.phrasings.short)):
            if text and len(text) < len(current) and "\n" not in text:
                result.append(
                    OptimizationCandidate(
                        candidate_id=f"shorter:{item.bullet_id}:{tier}",
                        action="shorten",
                        draft=_replace_bullet(draft, item.bullet_id, text),
                        evidence_ids=tuple(item.evidence_ids),
                        value_score=0.0,
                        clarity_score=0.3,
                        estimated_line_cost=max(1, len(text) // 70),
                        stage=0,
                        reason=f"canonical {tier} phrasing",
                    )
                )
    return result


def _unused_evidence(item: Any) -> UnusedEvidence:
    if isinstance(item, UnusedEvidence):
        return item
    return UnusedEvidence(
        evidence_id=str(item.get("evidence_id", "")),
        requirement_ids=[str(value) for value in item.get("requirement_ids", [])],
        strength=float(item.get("strength", item.get("score", 0.0))),
        likely_section=str(item.get("likely_section", "")),
        estimated_line_cost=int(item.get("estimated_line_cost", 1)),
        omission_reason=str(item.get("omission_reason", "")),
        redundancy=str(item.get("redundancy", "")),
        weaker_selected_replacement=item.get("weaker_selected_replacement"),
        later_page_fill_suitability=str(item.get("later_page_fill_suitability", "possible")),
    )


def build_expansion_candidates(
    draft: DraftResponse,
    profile: MasterProfile,
    unused_evidence: Iterable[UnusedEvidence | dict[str, Any]],
) -> list[OptimizationCandidate]:
    catalog = _profile_bullets(profile)
    present = {evidence_id for item in draft.bullets for evidence_id in item.evidence_ids}
    result: list[OptimizationCandidate] = []
    for raw_item in unused_evidence:
        item = _unused_evidence(raw_item)
        source = catalog.get(item.evidence_id)
        if source is None or item.evidence_id in present:
            continue
        _, canonical = source
        reason = " ".join((item.omission_reason, item.redundancy)).casefold()
        if canonical.is_blocked or item.strength < 0.25 or item.later_page_fill_suitability.casefold() in {"poor", "no", "never"}:
            continue
        if any(term.casefold() in reason for term in ("prohibited", "unsupported", "redundant", "duplicate")):
            continue
        text = canonical.phrasings.short
        if not text or "\n" in text:
            continue
        entry = next((entry for entry in (*profile.experience, *profile.projects) if any(b.id == item.evidence_id for b in entry.bullets)), None)
        if entry is None or any(item.evidence_id in bullet.evidence_ids for bullet in draft.bullets):
            continue
        bullet_id = f"fill:{item.evidence_id}"
        new_bullet = DraftBullet(
            bullet_id=bullet_id,
            evidence_ids=[item.evidence_id],
            supported_requirement_ids=list(item.requirement_ids),
            section="Experience" if item.likely_section.casefold() == "experience" else "Projects",
            entry_id=entry.id,
            text=text,
        )
        if any(bullet.entry_id == new_bullet.entry_id and bullet.text == text for bullet in draft.bullets):
            continue
        new_draft = replace(
            draft,
            selected_evidence_ids=list(dict.fromkeys([*draft.selected_evidence_ids, item.evidence_id])),
            bullets=[*draft.bullets, new_bullet],
            amdocs_omission_ledger=[omission for omission in draft.amdocs_omission_ledger if omission.evidence_id != item.evidence_id],
        )
        result.append(
            OptimizationCandidate(
                candidate_id=bullet_id,
                action="expand",
                draft=new_draft,
                evidence_ids=(item.evidence_id,),
                value_score=item.strength + 0.1 * len(item.requirement_ids),
                clarity_score=0.2,
                estimated_line_cost=max(1, item.estimated_line_cost),
                stage=1,
                reason="nonredundant covered evidence",
            )
        )
    return sorted(result, key=lambda item: (-item.value_score, item.estimated_line_cost, item.candidate_id))


def build_removal_candidates(draft: DraftResponse, profile: MasterProfile) -> list[OptimizationCandidate]:
    catalog = _profile_bullets(profile)
    result: list[OptimizationCandidate] = []
    for item in draft.bullets:
        evidence_ids = set(item.evidence_ids)
        if evidence_ids & set(CANONICAL_AMDOCS_BULLETS):
            continue
        source = catalog.get(next(iter(evidence_ids), ""))
        priority = source[1].priority if source else 999
        new_bullets = [bullet for bullet in draft.bullets if bullet.bullet_id != item.bullet_id]
        if len(new_bullets) == len(draft.bullets):
            continue
        result.append(
            OptimizationCandidate(
                candidate_id=f"remove:{item.bullet_id}",
                action="remove",
                draft=replace(draft, bullets=new_bullets),
                evidence_ids=tuple(item.evidence_ids),
                value_score=float(priority),
                clarity_score=0.1,
                estimated_line_cost=1,
                stage=2,
                reason=f"lowest-priority eligible bullet ({priority})",
            )
        )
    return sorted(result, key=lambda item: (item.stage, item.value_score, item.candidate_id))


def build_compression_candidates(draft: DraftResponse, profile: MasterProfile) -> list[OptimizationCandidate]:
    return [
        *build_shorter_variant_candidates(draft, profile),
        *build_removal_candidates(draft, profile),
    ]
