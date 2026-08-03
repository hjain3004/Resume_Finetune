import json
from pathlib import Path

import pytest

from src.profile import MasterProfile, load_profile
from src.profile_lint import MEDIUM_MAX, SHORT_MAX, lint_profile
from scripts.validate_profile import _load_banned_terms
from src.render.emphasis import parse_emphasis

_EXPECTED_REAL_TOTALS = {"backend": 3399, "ml": 3537}

FIXTURE = Path("tests/fixtures/profile_lint_minimal.yaml")
_CLEAN_MEDIUM = "Built **an event store** on PostgreSQL for the ordering domain."
_CLEAN_SHORT = "Built an event store on PostgreSQL."
_BANNED = ("robust",)


def _profile(
    tmp_path: Path,
    medium: str = _CLEAN_MEDIUM,
    short: str = _CLEAN_SHORT,
) -> MasterProfile:
    text = FIXTURE.read_text(encoding="utf-8")
    text = text.replace('"MEDIUM_SENTINEL"', json.dumps(medium))
    text = text.replace('"SHORT_SENTINEL"', json.dumps(short))
    path = tmp_path / "p.yaml"
    path.write_text(text, encoding="utf-8")
    return load_profile(path)


def _lint(profile: MasterProfile, *, variant_budget: int = 3800) -> list[str]:
    return lint_profile(profile, _BANNED, variant_budget=variant_budget)


def test_clean_fixture_passes(tmp_path):
    assert _lint(_profile(tmp_path)) == []


def test_overlong_medium_is_reported(tmp_path):
    violations = _lint(_profile(tmp_path, medium="Built **x** " + "y" * MEDIUM_MAX))
    assert any("medium" in v and "exceeds" in v for v in violations)


def test_overlong_short_is_reported(tmp_path):
    violations = _lint(_profile(tmp_path, short="Built " + "y" * SHORT_MAX))
    assert any("short" in v and "exceeds" in v for v in violations)


def test_gerund_opening_is_reported(tmp_path):
    violations = _lint(_profile(tmp_path, medium="Building **a thing** here."))
    assert any("gerund" in v for v in violations)


def test_banned_word_is_reported(tmp_path):
    violations = _lint(_profile(tmp_path, medium="Built **a robust thing** here."))
    assert any("banned" in v and "robust" in v for v in violations)


def test_banned_word_does_not_match_inside_larger_word(tmp_path):
    profile = _profile(tmp_path, medium="Built **system robustness** here.")
    assert not any("banned" in v for v in _lint(profile))


def test_unbalanced_markup_is_reported(tmp_path):
    violations = _lint(_profile(tmp_path, medium="Built **a thing here."))
    assert any("markup" in v for v in violations)


def test_more_than_three_spans_is_reported(tmp_path):
    medium = "Built **a** and **b** and **c** and **d** here."
    violations = _lint(_profile(tmp_path, medium=medium))
    assert any("spans" in v for v in violations)


def test_ordered_bullet_without_emphasis_is_reported(tmp_path):
    violations = _lint(_profile(tmp_path, medium="Built a thing here."))
    assert any("at least one" in v for v in violations)


def test_short_only_bullet_does_not_crash(tmp_path):
    assert _lint(_profile(tmp_path)) == []


def test_variant_budget_counts_short_fallback(tmp_path):
    violations = _lint(_profile(tmp_path), variant_budget=10)
    assert any("budget" in v and "base_variants" in v for v in violations)


def _real_variant_total(profile: MasterProfile, name: str) -> int:
    index = {
        bullet.id: bullet
        for source in (*profile.projects, *profile.experience)
        for bullet in source.bullets
    }
    return sum(
        len(
            parse_emphasis(
                index[bullet_id].phrasings.medium
                or index[bullet_id].phrasings.short
            )[0]
        )
        for bullet_id in profile.base_variants[name].bullet_order
    )


def test_real_profile_passes_the_lint():
    profile = load_profile("config/master_profile.yaml")
    assert lint_profile(profile, _load_banned_terms()) == []


def test_real_variants_have_exact_shape_and_budget():
    profile = load_profile("config/master_profile.yaml")
    assert set(profile.base_variants) == set(_EXPECTED_REAL_TOTALS)
    for name, expected_total in _EXPECTED_REAL_TOTALS.items():
        assert len(profile.base_variants[name].bullet_order) == 13
        assert _real_variant_total(profile, name) == expected_total
        assert expected_total <= 3600
