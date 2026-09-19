"""Deterministic sanitize-and-deliver policy for Tailor2 drafts.

This module deliberately has no provider or filesystem dependencies.  It turns
an imperfect model draft into the safest evidence-grounded DraftResponse that
the renderer can consume, while keeping a machine-readable record of every
element that was replaced or removed.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from typing import Any

from src.profile import MasterProfile
from src.tailor2.models import AmdocsOmission, DraftBullet, DraftResponse
from src.tailor2.validators import CANONICAL_AMDOCS_BULLETS, extract_numeric_tokens


@dataclass(frozen=True)
class QuarantineRecord:
    evidence_id: str | None
    location: str
    finding: str
    action: str
    replacement: str | None = None


@dataclass(frozen=True)
class SanitizationResult:
    draft: DraftResponse
    quarantine_ledger: list[QuarantineRecord] = field(default_factory=list)
    auto_corrections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    safe_fallback_used: bool = False
    model_calls_required: bool = False


def _evidence_by_id(profile: MasterProfile) -> dict[str, Any]:
    return {
        bullet.id: bullet
        for entry in (*profile.experience, *profile.projects)
        for bullet in entry.bullets
    }


def _entry_for_evidence(profile: MasterProfile, evidence_id: str) -> tuple[str, str]:
    for entry in profile.experience:
        if any(bullet.id == evidence_id for bullet in entry.bullets):
            return "Experience", entry.id
    for entry in profile.projects:
        if any(bullet.id == evidence_id for bullet in entry.bullets):
            return "Projects", entry.id
    raise KeyError(evidence_id)


def _normalized_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def resolve_evidence_id(value: str, evidence_by_id: dict[str, Any]) -> str | None:
    """Resolve only exact or unambiguous canonical-prefix aliases."""
    if value in evidence_by_id:
        return value
    folded = value.casefold()
    exact = [eid for eid in evidence_by_id if eid.casefold() == folded]
    if len(exact) == 1:
        return exact[0]
    normalized = _normalized_id(value)
    candidates = [eid for eid in evidence_by_id if _normalized_id(eid).startswith(normalized)]
    return candidates[0] if len(candidates) == 1 else None


def _canonical_text(evidence: Any, findings: list[str] | None = None) -> str:
    phrasings = getattr(evidence, "phrasings", None)
    candidates = [
        getattr(phrasings, "medium", ""),
        getattr(phrasings, "long", ""),
        getattr(phrasings, "short", ""),
    ] if phrasings else []
    finding_text = " ".join(findings or []).casefold()
    if "code smell" in finding_text:
        medium = candidates[0] if candidates else ""
        if medium and "findings" in medium.casefold():
            return re.sub(r"(?i)sonarqube findings", "SonarQube code smells", medium).strip()
        exact_category = [value for value in candidates if "code smell" in value.casefold()]
        if exact_category:
            return re.sub(r"(?i)roughly\s+", "~", exact_category[0]).strip()
    return next((value.strip() for value in candidates if value), "")


def _allowed_numeric_tokens(evidence: Any) -> set[str]:
    texts: list[str] = []
    phrasings = getattr(evidence, "phrasings", None)
    if phrasings:
        texts.extend(
            value
            for value in (
                getattr(phrasings, "short", ""),
                getattr(phrasings, "medium", ""),
                getattr(phrasings, "long", ""),
            )
            if isinstance(value, str)
        )
    for attribute in ("evidence", "defense"):
        value = getattr(evidence, attribute, "")
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, (list, tuple)):
            texts.extend(item for item in value if isinstance(item, str))
    return {
        normalized
        for text in texts
        for token in extract_numeric_tokens(text)
        for normalized in (token, token.lstrip("~+").strip())
    }


def _prohibited_term(text: str, profile: MasterProfile) -> str | None:
    terms = [*profile.do_not_claim, "Kubernetes"]
    for term in terms:
        if re.search(r"\b" + re.escape(term) + r"\b", text, re.IGNORECASE):
            return term
    return None


def build_safe_fallback(profile: MasterProfile, variant: str) -> DraftResponse:
    """Construct a conservative draft solely from canonical profile data."""
    evidence_by_id = _evidence_by_id(profile)
    bullets: list[DraftBullet] = []
    selected: list[str] = []
    for index, evidence_id in enumerate(profile.base_variants[variant].bullet_order, start=1):
        evidence = evidence_by_id[evidence_id]
        section, entry_id = _entry_for_evidence(profile, evidence_id)
        bullets.append(
            DraftBullet(
                bullet_id=f"fallback_{index:02d}_{evidence_id}",
                evidence_ids=[evidence_id],
                supported_requirement_ids=[],
                section=section,
                entry_id=entry_id,
                text=_canonical_text(evidence),
            )
        )
        selected.append(evidence_id)
    return DraftResponse(
        atomic_requirements=[],
        selected_evidence_ids=selected,
        amdocs_omission_ledger=[],
        section_order=["Experience", "Projects", "Technical Skills"],
        bullets=bullets,
    )


def _populate_omission_ledger(
    draft: DraftResponse,
    evidence_by_id: dict[str, Any],
    selected_ids: list[str],
    corrections: list[str],
) -> DraftResponse:
    represented = {eid for bullet in draft.bullets for eid in bullet.evidence_ids}
    ledger_by_id: dict[str, AmdocsOmission] = {}
    for item in draft.amdocs_omission_ledger:
        resolved = resolve_evidence_id(item.evidence_id, evidence_by_id)
        if resolved is None:
            corrections.append(f"Dropped unknown omission-ledger evidence {item.evidence_id!r}.")
            continue
        category = item.category if item.category in {"relevance", "space"} else "space"
        ledger_by_id.setdefault(resolved, AmdocsOmission(resolved, category, item.reason or "Omitted safely."))
        if resolved != item.evidence_id:
            corrections.append(f"Normalized omission-ledger alias {item.evidence_id!r} to {resolved!r}.")

    accounting_ids = [*CANONICAL_AMDOCS_BULLETS, *selected_ids]
    for evidence_id in accounting_ids:
        if evidence_id in evidence_by_id and evidence_id not in represented and evidence_id not in ledger_by_id:
            ledger_by_id[evidence_id] = AmdocsOmission(
                evidence_id,
                "space",
                "Omitted from the delivered draft; retained as canonical evidence for human review.",
            )
            corrections.append(f"Auto-accounted omitted evidence {evidence_id!r} in the omission ledger.")
    return dataclasses.replace(draft, amdocs_omission_ledger=list(ledger_by_id.values()))


def sanitize_draft(
    draft: DraftResponse,
    profile: MasterProfile,
    variant: str,
    *,
    selected_evidence_ids: set[str] | None = None,
    audit_findings: dict[str, list[str]] | None = None,
) -> SanitizationResult:
    """Keep safe elements, restore canonical wording, and never call a model."""
    evidence_by_id = _evidence_by_id(profile)
    quarantine: list[QuarantineRecord] = []
    corrections: list[str] = []
    warnings: list[str] = []
    findings = audit_findings or {}
    normalized_selected: list[str] = []

    if selected_evidence_ids is None:
        raw_selected_ids = list(draft.selected_evidence_ids)
    else:
        requested_ids = set(selected_evidence_ids) | set(draft.selected_evidence_ids)
        raw_selected_ids = [eid for eid in draft.selected_evidence_ids if eid in requested_ids]
        raw_selected_ids.extend(sorted(requested_ids - set(raw_selected_ids)))
    for raw_id in raw_selected_ids:
        resolved = resolve_evidence_id(raw_id, evidence_by_id)
        if resolved is None:
            warnings.append(f"Dropped unknown selected evidence {raw_id!r}.")
            continue
        if resolved not in normalized_selected:
            normalized_selected.append(resolved)
        if resolved != raw_id:
            corrections.append(f"Normalized selected evidence alias {raw_id!r} to {resolved!r}.")

    sanitized_bullets: list[DraftBullet] = []
    seen_texts: set[str] = set()
    for bullet in draft.bullets:
        resolved_ids: list[str] = []
        for raw_id in bullet.evidence_ids:
            resolved = resolve_evidence_id(raw_id, evidence_by_id)
            if resolved is None:
                quarantine.append(
                    QuarantineRecord(raw_id, f"bullets[{bullet.bullet_id}]", "unknown evidence reference", "removed", None)
                )
                continue
            if resolved not in resolved_ids:
                resolved_ids.append(resolved)
            if resolved != raw_id:
                corrections.append(f"Normalized bullet {bullet.bullet_id!r} evidence alias {raw_id!r} to {resolved!r}.")

        if not resolved_ids:
            quarantine.append(
                QuarantineRecord(None, f"bullets[{bullet.bullet_id}]", "bullet has no resolvable evidence", "removed", None)
            )
            continue

        entry_section, entry_id = _entry_for_evidence(profile, resolved_ids[0])
        replacement: str | None = None
        finding_parts: list[str] = []
        prohibited = _prohibited_term(bullet.text, profile)
        if prohibited:
            finding_parts.append(f"prohibited term {prohibited!r}")
        if "\n" in bullet.text or "\r" in bullet.text or not bullet.text.strip():
            finding_parts.append("empty or multiline bullet")
        allowed_tokens = set().union(*(_allowed_numeric_tokens(evidence_by_id[eid]) for eid in resolved_ids))
        if any(token not in allowed_tokens and token.lstrip("~+").strip() not in allowed_tokens for token in extract_numeric_tokens(bullet.text)):
            finding_parts.append("altered or unsupported numeric token")
        finding_parts.extend(findings.get(bullet.bullet_id, []))
        if finding_parts:
            replacement = _canonical_text(evidence_by_id[resolved_ids[0]], finding_parts)
            replacement_prohibited = _prohibited_term(replacement, profile)
            if replacement and not replacement_prohibited:
                text = replacement
                action = "replaced_with_canonical"
            else:
                text = ""
                action = "removed"
                replacement = None
            quarantine.append(
                QuarantineRecord(
                    resolved_ids[0],
                    f"bullets[{bullet.bullet_id}]",
                    "; ".join(finding_parts),
                    action,
                    replacement,
                )
            )
        else:
            text = bullet.text

        if not text or text in seen_texts:
            if text:
                quarantine.append(
                    QuarantineRecord(resolved_ids[0], f"bullets[{bullet.bullet_id}]", "duplicate bullet text", "removed", None)
                )
            continue
        seen_texts.add(text)
        sanitized_bullets.append(
            dataclasses.replace(
                bullet,
                evidence_ids=resolved_ids,
                section=entry_section,
                entry_id=entry_id,
                text=text,
            )
        )

    sanitized = dataclasses.replace(
        draft,
        selected_evidence_ids=normalized_selected,
        bullets=sanitized_bullets,
    )
    fallback_used = False
    if not sanitized.bullets:
        sanitized = build_safe_fallback(profile, variant)
        fallback_used = True
        warnings.append("Draft contained no safe grounded bullets; built the canonical safe fallback.")

    sanitized = _populate_omission_ledger(sanitized, evidence_by_id, normalized_selected, corrections)
    counts: dict[str, int] = {}
    for bullet in sanitized.bullets:
        counts[bullet.entry_id] = counts.get(bullet.entry_id, 0) + 1
    if any(count > 3 for entry_id, count in counts.items() if entry_id == "bank_integration_internship"):
        warnings.append("Preferred MalyTech bullet budget exceeded; retained grounded overflow for render-fill.")

    return SanitizationResult(
        draft=sanitized,
        quarantine_ledger=quarantine,
        auto_corrections=corrections,
        warnings=warnings,
        safe_fallback_used=fallback_used,
    )
