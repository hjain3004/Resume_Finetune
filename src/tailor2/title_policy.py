"""Deterministic title/employer identity fidelity for Tailor2.

Design decision: `config/master_profile.yaml`'s per-experience `title` field
is documented as immutable ("NEVER altered ... altering it is resume fraud,
not tailoring") and `src/profile.py` is out of this task's scope (only
`src/tailor2/**` may change), so this module does not add a schema field to
the profile itself. Instead, `DraftResponse.entry_title_overrides` (see
models.py) gives the drafter a narrow, auditable channel to propose a
JD-friendly *displayed* title for an experience entry -- exactly the "seed
the target title in the summary line only" pattern the profile's own
known_gaps note anticipates -- while this module owns the only list of
titles Tailor2 will ever accept as a substitute for the canonical one.

Any proposed title that is neither the canonical title nor a listed
approved variant is a title-identity mismatch and is corrected back to the
canonical title automatically (AUTO_CORRECTABLE, matching the task's
explicit severity classification for "canonical employer or title
mismatch") -- the run is never rejected over this, and the mismatch is
recorded as a warning so it's visible in the manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


# entry_id -> frozenset of explicitly pre-authorized display variants with
# verified provenance. NO Amdocs variants are approved (canonical title is
# "Software Developer", and altering it is documented as resume fraud).
APPROVED_TITLE_VARIANTS: dict[str, frozenset[str]] = {
    "bank_integration_internship": frozenset({"Software Engineering Intern"}),
}


@dataclass(frozen=True)
class TitleResolution:
    entry_id: str
    proposed_title: str | None
    canonical_title: str
    displayed_title: str
    resolution_status: str  # "canonical_exact" | "approved_variant" | "auto_corrected_to_canonical" | "unresolved_source_conflict"
    was_auto_corrected: bool
    requires_human_review: bool
    authority_note: str

    @property
    def final_title(self) -> str:
        """Backward compatibility with c13677c."""
        return self.displayed_title

    @property
    def is_canonical(self) -> bool:
        """True if rendered title matches canonical title."""
        return self.resolution_status in ("canonical", "canonical_exact")


def resolve_displayed_title(
    entry_id: str,
    proposed_title: str | None,
    canonical_title: str,
    approved_variants: frozenset[str] | set[str] | None = None,
    has_source_conflict: bool = False,
) -> TitleResolution:
    """Resolve what title should actually render for an experience entry.

    - Genuinely contradictory authoritative sources -> preserve safest canonical title,
      resolution_status="unresolved_source_conflict", was_auto_corrected=True, requires_human_review=True.
    - No proposal -> canonical title, resolution_status="canonical_exact".
    - Proposal equals canonical -> canonical title, resolution_status="canonical_exact".
    - Proposal is an approved variant with verified provenance -> use proposal,
      resolution_status="approved_variant".
    - Anything else -> unapproved substitution with unambiguous canonical evidence.
      Deterministically auto-corrects to canonical title, sets
      resolution_status="auto_corrected_to_canonical", was_auto_corrected=True,
      requires_human_review=False. Continues normally with transparent warning.
    """
    if has_source_conflict:
        return TitleResolution(
            entry_id=entry_id,
            proposed_title=proposed_title,
            canonical_title=canonical_title,
            displayed_title=canonical_title,
            resolution_status="unresolved_source_conflict",
            was_auto_corrected=True,
            requires_human_review=True,
            authority_note=(
                f"entry {entry_id!r}: genuine conflict among authoritative sources for title; "
                f"preserved safest canonical title {canonical_title!r}; flagged for human review."
            ),
        )

    if not proposed_title or proposed_title.strip() == canonical_title.strip():
        return TitleResolution(
            entry_id=entry_id,
            proposed_title=proposed_title,
            canonical_title=canonical_title,
            displayed_title=canonical_title,
            resolution_status="canonical_exact",
            was_auto_corrected=False,
            requires_human_review=False,
            authority_note="Verified canonical employment title.",
        )

    clean_proposed = proposed_title.strip()
    if approved_variants is None:
        approved = APPROVED_TITLE_VARIANTS.get(entry_id, frozenset())
    else:
        approved = frozenset(approved_variants)

    if clean_proposed in approved:
        return TitleResolution(
            entry_id=entry_id,
            proposed_title=proposed_title,
            canonical_title=canonical_title,
            displayed_title=clean_proposed,
            resolution_status="approved_variant",
            was_auto_corrected=False,
            requires_human_review=False,
            authority_note=f"Using authorized display variant {clean_proposed!r} with documented provenance.",
        )

    # Unapproved substitution with unambiguous canonical evidence:
    # Deterministically auto-correct to canonical title without requiring human review.
    return TitleResolution(
        entry_id=entry_id,
        proposed_title=proposed_title,
        canonical_title=canonical_title,
        displayed_title=canonical_title,
        resolution_status="auto_corrected_to_canonical",
        was_auto_corrected=True,
        requires_human_review=False,
        authority_note=(
            f"entry {entry_id!r}: proposed title {proposed_title!r} differs from canonical title "
            f"{canonical_title!r} and is not an approved display variant. Deterministically auto-corrected "
            f"to verified canonical title {canonical_title!r} from master_profile."
        ),
    )
