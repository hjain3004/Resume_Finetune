import pytest
from src.profile import load_profile
from src.render.mapping import build_render_doc, RenderMappingError

PROFILE = load_profile("config/master_profile.yaml")


def test_backend_variant_maps_all_ordered_bullets():
    doc = build_render_doc(PROFILE, "backend")
    ordered = PROFILE.base_variants["backend"].bullet_order
    assert set(b.bullet_id for b in doc.all_bullets()) == set(ordered)


def test_per_entry_bullet_order_is_preserved():
    doc = build_render_doc(PROFILE, "backend")
    ordered = PROFILE.base_variants["backend"].bullet_order
    ordered_list = list(ordered)
    
    for group in (doc.education, doc.experience, doc.projects):
        for entry in group:
            if not entry.bullets:
                continue
            # Check that the bullets within this entry appear in the same relative order
            # as they do in the global bullet_order.
            indices = [ordered_list.index(b.bullet_id) for b in entry.bullets]
            assert indices == sorted(indices)


def test_projects_and_experience_have_dates():
    doc = build_render_doc(PROFILE, "backend")
    assert all(p.date_range != "" for p in doc.projects)
    assert all(e.date_range != "" for e in doc.experience)


def test_section_order_is_subset_of_headings_whitelist():
    doc = build_render_doc(PROFILE, "backend")
    whitelist = set(PROFILE.ats["headings_whitelist"])
    assert set(doc.section_order) <= whitelist


def test_tier_override_selects_requested_phrasing():
    ordered = PROFILE.base_variants["backend"].bullet_order
    target = ordered[0]
    doc = build_render_doc(PROFILE, "backend", tier_overrides={target: "short"})
    rendered = {b.bullet_id: b.text for b in doc.all_bullets()}
    index = {b.id: b for src in (*PROFILE.projects, *PROFILE.experience) for b in src.bullets}
    assert rendered[target] == index[target].phrasings.short


def test_unavailable_tier_is_a_hard_error_not_a_silent_downgrade():
    index = {b.id: b for src in (*PROFILE.projects, *PROFILE.experience) for b in src.bullets}
    ordered = set(PROFILE.base_variants["backend"].bullet_order)
    missing = next(
        (bid for bid, b in index.items() if bid in ordered and b.phrasings.long is None),
        None,
    )
    if missing is None:
        pytest.skip("every ordered bullet defines a long phrasing; nothing to assert")
    with pytest.raises(RenderMappingError, match="long"):
        build_render_doc(PROFILE, "backend", tier_overrides={missing: "long"})


def test_override_for_unknown_bullet_id_raises():
    with pytest.raises(RenderMappingError, match="absent"):
        build_render_doc(PROFILE, "backend", tier_overrides={"no_such_bullet": "short"})


def test_unknown_base_variant_raises():
    with pytest.raises(Exception):
        build_render_doc(PROFILE, "does_not_exist")
