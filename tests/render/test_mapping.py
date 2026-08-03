import textwrap

import pytest
from src.profile import load_profile
from src.render.mapping import build_render_doc, RenderMappingError

PROFILE = load_profile("config/master_profile.yaml")

# Definition order inside `exp_one` is [exp_b1, exp_b2, exp_b3]; the variant asks
# for [exp_b3, exp_b1, exp_b2]. All three share priority 1, so the flagship
# ordering rule permits the mismatch. Rendering must follow the variant.
_ORDER_MISMATCH_PROFILE = textwrap.dedent("""
    schema_version: "0.3.0"
    last_updated: "2026-08-03"
    ats:
      charset_policy: ascii_strict
      forbidden_chars: []
      substitutions: {}
      headings_whitelist: ["Education", "Experience", "Projects", "Technical Skills"]
    identity:
      name: Test User
      email: test@example.com
    education:
      - institution: Example University
        degree: Master of Science
        display_date: "Aug. 2025 - May 2027"
    skills:
      languages: [Python]
    projects:
      - id: proj_one
        name: Project One
        display_title: Project One
        display_date: "Sep 2025 - Dec 2025"
        ownership_boundary: "SAFE TO CLAIM: synthetic fixture."
        tech: {tech_line: "Python"}
        keywords: {exact: [Python], topical: [backend]}
        metric_ledger: {}
        metric_scope: {}
        known_gaps: []
        bullets:
          - id: proj_b1
            claim_type: verified
            priority: 1
            phrasings: {short: "Built a project."}
            evidence: ["synthetic fixture"]
            keywords_hit: [Python]
    experience:
      - id: exp_one
        employer: Example Corp
        title: Engineer
        scope_line: "Synthetic backend work."
        display_date: "July 2023 - June 2025"
        ownership_boundary: "SAFE TO CLAIM: synthetic fixture."
        bullets:
          - id: exp_b1
            claim_type: verified
            priority: 1
            phrasings: {short: "Alpha bullet."}
            evidence: ["synthetic fixture"]
          - id: exp_b2
            claim_type: verified
            priority: 1
            phrasings: {short: "Bravo bullet."}
            evidence: ["synthetic fixture"]
          - id: exp_b3
            claim_type: verified
            priority: 1
            phrasings: {short: "Charlie bullet."}
            evidence: ["synthetic fixture"]
    base_variants:
      backend:
        projects: [proj_one]
        bullet_order: [exp_b3, exp_b1, exp_b2, proj_b1]
    do_not_claim: [Kubernetes]
""")


def _order_mismatch_profile(tmp_path):
    path = tmp_path / "order_mismatch.yaml"
    path.write_text(_ORDER_MISMATCH_PROFILE)
    return load_profile(str(path))


def test_entry_bullets_follow_variant_order_not_definition_order(tmp_path):
    """The variant is the authority on sequence; YAML definition order is not.

    Regression guard for the defect that made a YAML reorder look necessary:
    _entry_bullets walked each entry's source bullets, so per-entry sequence
    silently came from the file instead of base_variants.*.bullet_order.
    """
    profile = _order_mismatch_profile(tmp_path)
    doc = build_render_doc(profile, "backend")

    entry = doc.experience[0]
    assert [b.bullet_id for b in entry.bullets] == ["exp_b3", "exp_b1", "exp_b2"]


def test_variant_order_survives_a_tier_override(tmp_path):
    """Overrides change the text of a bullet, never its position."""
    profile = _order_mismatch_profile(tmp_path)
    doc = build_render_doc(profile, "backend", tier_overrides={"exp_b1": "short"})

    entry = doc.experience[0]
    assert [b.bullet_id for b in entry.bullets] == ["exp_b3", "exp_b1", "exp_b2"]
    assert entry.bullets[1].text == "Alpha bullet."


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


def test_to_render_bullet_parses_emphasis():
    import dataclasses
    from src.profile import Phrasings
    from src.render.mapping import _to_render_bullet

    # Get a real bullet to clone
    base_bullet = PROFILE.projects[0].bullets[0]
    marked = dataclasses.replace(
        base_bullet,
        phrasings=Phrasings(medium="Built **an event store** on PostgreSQL.", short="")
    )
    rb = _to_render_bullet(marked, "medium")
    assert rb.text == "Built an event store on PostgreSQL."
    assert rb.emphasis == ((6, 20),)
