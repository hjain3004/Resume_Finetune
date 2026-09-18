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

# entry_id -> set of titles that may be substituted for the canonical
# Experience.title when the drafter proposes one via entry_title_overrides.
# Intentionally conservative: every variant here is a title Himanshu has
# actually held or that differs from the canonical title only in a way that
# does not change seniority, scope, or employment relationship (e.g. the
# generic industry-standard rendering of an internal title).
APPROVED_TITLE_VARIANTS: dict[str, frozenset[str]] = {
    "amdocs_software_developer": frozenset({"Software Developer", "Software Engineer"}),
    "bank_integration_internship": frozenset({"Software Engineering Intern"}),
}


@dataclass(frozen=True)
class TitleResolution:
    entry_id: str
    proposed_title: str | None
    canonical_title: str
    final_title: str
    was_auto_corrected: bool


def resolve_displayed_title(
    entry_id: str,
    proposed_title: str | None,
    canonical_title: str,
) -> TitleResolution:
    """Resolve what title should actually render for an experience entry.

    - No proposal -> canonical title, no correction.
    - Proposal exactly equals canonical -> canonical title, no correction.
    - Proposal is a listed approved variant for this entry -> use the
      proposal as-is (it is a legitimate, pre-approved rendering).
    - Anything else -> silently corrected to canonical; caller is expected
      to record `was_auto_corrected` as a warning, per the AUTO_CORRECTABLE
      severity tier (continue the run, don't fail it).
    """
    if not proposed_title or proposed_title == canonical_title:
        return TitleResolution(entry_id, proposed_title, canonical_title, canonical_title, False)

    approved = APPROVED_TITLE_VARIANTS.get(entry_id, frozenset())
    if proposed_title in approved:
        return TitleResolution(entry_id, proposed_title, canonical_title, proposed_title, False)

    return TitleResolution(entry_id, proposed_title, canonical_title, canonical_title, True)
