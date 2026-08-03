"""Style lint for config/master_profile.yaml.

Separate from load_profile on purpose: a style violation must never make the
profile schema-invalid for the tailor. Thresholds are calibrated to the user's
own one-page resumes (median ~275 chars, max 395), not to L4's 2-line rule.

Every check returns violation strings; empty means clean, matching
src/render/l7.py and src/tailor/lint.py.
"""

import logging
import re

from src.profile import Bullet, MasterProfile
from src.render.emphasis import EmphasisError, parse_emphasis

logger = logging.getLogger(__name__)

MEDIUM_MAX = 400
SHORT_MAX = 200
MAX_SPANS = 3
VARIANT_BUDGET = 3800


def _plain(raw: str) -> str:
    return parse_emphasis(raw)[0]


def _contains_term(plain: str, term: str) -> bool:
    pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
    return re.search(pattern, plain, flags=re.IGNORECASE) is not None


def _check_phrasing(
    bullet_id: str,
    tier: str,
    raw: str,
    limit: int | None,
    banned_terms: tuple[str, ...],
    *,
    require_emphasis: bool = False,
) -> list[str]:
    try:
        plain, spans = parse_emphasis(raw)
    except EmphasisError as exc:
        return [f"lint {bullet_id}.{tier}: invalid markup: {exc}"]

    violations: list[str] = []
    if limit is not None and len(plain) > limit:
        violations.append(
            f"lint {bullet_id}.{tier}: {len(plain)} chars exceeds limit of {limit}"
        )
    if len(spans) > MAX_SPANS:
        violations.append(
            f"lint {bullet_id}.{tier}: {len(spans)} emphasis spans exceeds {MAX_SPANS}"
        )
    words = plain.split()
    if words and words[0].casefold().endswith("ing"):
        violations.append(
            f"lint {bullet_id}.{tier}: opens with gerund {words[0]!r}; use past tense"
        )
    violations.extend(
        f"lint {bullet_id}.{tier}: contains banned word or phrase {term!r}"
        for term in banned_terms
        if _contains_term(plain, term)
    )
    if require_emphasis and not spans:
        violations.append(
            f"lint {bullet_id}.{tier}: rendered bullet needs at least one emphasis span"
        )
    return violations


def _all_bullets(profile: MasterProfile) -> tuple[Bullet, ...]:
    return tuple(
        bullet
        for source in (*profile.projects, *profile.experience)
        for bullet in source.bullets
    )


def lint_profile(
    profile: MasterProfile,
    banned_terms: tuple[str, ...],
    *,
    variant_budget: int = VARIANT_BUDGET,
) -> list[str]:
    """Every style violation in the profile. Empty list == clean."""
    bullets = _all_bullets(profile)
    ordered_ids = {
        bullet_id
        for variant in profile.base_variants.values()
        for bullet_id in variant.bullet_order
    }

    violations: list[str] = []
    for bullet in bullets:
        violations.extend(
            _check_phrasing(
                bullet.id,
                "short",
                bullet.phrasings.short,
                SHORT_MAX,
                banned_terms,
            )
        )
        if bullet.phrasings.long is not None:
            violations.extend(
                _check_phrasing(
                    bullet.id,
                    "long",
                    bullet.phrasings.long,
                    None,
                    banned_terms,
                )
            )
        if bullet.phrasings.medium is not None:
            violations.extend(
                _check_phrasing(
                    bullet.id,
                    "medium",
                    bullet.phrasings.medium,
                    MEDIUM_MAX,
                    banned_terms,
                    require_emphasis=bullet.id in ordered_ids,
                )
            )

    index = {bullet.id: bullet for bullet in bullets}
    for name, variant in profile.base_variants.items():
        total = 0
        for bullet_id in variant.bullet_order:
            bullet = index[bullet_id]
            raw = bullet.phrasings.medium or bullet.phrasings.short
            try:
                total += len(_plain(raw))
            except EmphasisError:
                total += len(raw)
        if total > variant_budget:
            violations.append(
                f"lint base_variants.{name}: {total} chars of bullet text exceeds "
                f"the one-page budget of {variant_budget}"
            )

    logger.info("profile lint: %d violation(s)", len(violations))
    return violations
