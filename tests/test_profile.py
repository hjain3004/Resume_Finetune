import pytest

from src.profile import ProfileValidationError, load_profile
_MINIMAL_PROFILE = """
schema_version: "0.3.0"
last_updated: "2026-07-30"
ats:
  charset_policy: ascii_strict
  max_pages: 1
  forbidden_chars: ["\\u2014"]
  substitutions:
    "\\u2014": "-"
identity:
  name: Himanshu Jain
  email: himanshu.jain@sjsu.edu
education:
  - institution: San Jose State University
    degree: Master of Science in Software Engineering
    display_date: "Aug. 2025 - May 2027"
skills:
  languages: ["Python", "Java"]
projects:
  - id: proj_one
    name: Project One
    display_title: Project One - A Thing
    ownership_boundary: "SAFE TO CLAIM: all of it."
    tech:
      tech_line: "Python, pytest"
    keywords:
      exact: ["Python"]
      topical: ["backend"]
    metric_ledger:
      tests:
        value: 12
        provenance: counted
        renderable: true
    metric_scope:
      test_scope: "unit tests only"
    known_gaps:
      - id: gap_one
        severity: medium
        detail: "A gap."
        fix: "Close it."
    bullets:
      - id: proj_b1
        claim_type: verified
        priority: 1
        phrasings:
          short: Built a thing
        evidence:
          - "src/thing.py: does the thing"
        keywords_hit: ["Python"]
experience:
  - id: exp_one
    employer: Amdocs
    title: Software Developer
    scope_line: "Did backend work."
    display_date: "July 2023 - June 2025"
    ownership_boundary: "SAFE TO CLAIM: my slice."
    bullets:
      - id: exp_b1
        claim_type: verified
        priority: 1
        phrasings:
          short: Shipped a service
        evidence:
          - "prep doc: service description"
base_variants:
  backend:
    projects: [proj_one]
    bullet_order: [exp_b1, proj_b1]
do_not_claim:
  - Kubernetes
"""

_DUPLICATE_PROJECT_BLOCK = """  - id: proj_one
    name: Project One Again
    display_title: Project One Again
    ownership_boundary: "SAFE TO CLAIM: all of it."
    tech:
      tech_line: "Python"
    bullets:
      - id: proj_b_dup
        claim_type: verified
        priority: 1
        phrasings:
          short: Built another thing
        evidence:
          - "src/other.py: does another thing"
"""


def _write(tmp_path, text: str):
    path = tmp_path / "master_profile.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_duplicate_mapping_key_is_rejected(tmp_path):
    path = _write(tmp_path, "identity:\n  name: A\n  name: B\n")
    with pytest.raises(ProfileValidationError, match="duplicate key"):
        load_profile(path)


def test_malformed_yaml_is_rejected(tmp_path):
    path = _write(tmp_path, "identity: [unclosed\n")
    with pytest.raises(ProfileValidationError, match="malformed YAML"):
        load_profile(path)


def test_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        load_profile(tmp_path / "nope.yaml")

def test_non_ascii_in_phrasing_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "short: Built a thing", "short: Built a thing — with an em dash"))
    with pytest.raises(ProfileValidationError, match="non-ASCII"):
        load_profile(path)


def test_ats_forbidden_chars_may_be_non_ascii(tmp_path):
    # The exemption: declaring a banned character is not using it.
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    assert "—" in profile.ats["forbidden_chars"]


def test_blank_string_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "name: Himanshu Jain", 'name: "   "'))
    with pytest.raises(ProfileValidationError, match="nonempty"):
        load_profile(path)


from src.profile import ClaimType


def test_bullet_requires_short_phrasing(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "short: Built a thing", "tiny: Built a thing"))
    with pytest.raises(ProfileValidationError, match=r"phrasings"):
        load_profile(path)


def test_unknown_claim_type_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "claim_type: verified", "claim_type: probably_true", 1))
    with pytest.raises(ProfileValidationError, match="claim_type"):
        load_profile(path)


def test_non_verified_claim_requires_defense(tmp_path):
    # Contract C3: any claim_type other than `verified` must carry a defense.
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "claim_type: verified", "claim_type: estimated", 1))
    with pytest.raises(ProfileValidationError, match="defense"):
        load_profile(path)


def test_empty_evidence_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        '        evidence:\n          - "src/thing.py: does the thing"\n',
        "        evidence: []\n"))
    with pytest.raises(ProfileValidationError, match="nonempty string list"):
        load_profile(path)


def test_null_evidence_is_rejected(tmp_path):
    # Deleting the only list item leaves `evidence:` parsing as None, which is
    # a different failure path than an explicitly empty list.
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        '          - "src/thing.py: does the thing"\n', ""))
    with pytest.raises(ProfileValidationError, match="expected list, got NoneType"):
        load_profile(path)


def test_priority_must_be_positive_int(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace("priority: 1", "priority: 0", 1))
    with pytest.raises(ProfileValidationError, match="positive integer"):
        load_profile(path)


def test_priority_rejects_boolean(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace("priority: 1", "priority: true", 1))
    with pytest.raises(ProfileValidationError, match="expected integer"):
        load_profile(path)


def test_verified_bullet_is_not_blocked(tmp_path):
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    bullet = profile.projects[0].bullets[0]
    assert bullet.claim_type is ClaimType.VERIFIED
    assert bullet.is_blocked is False


def test_best_within_falls_back_to_short(tmp_path):
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    phrasings = profile.projects[0].bullets[0].phrasings
    assert phrasings.best_within(5) == "Built a thing"
    assert phrasings.best_within(500) == "Built a thing"


def test_duplicate_bullet_id_across_entries_is_rejected(tmp_path):
    # Contract C1: bullet ids are the fabrication anchor, globally unique.
    path = _write(tmp_path, _MINIMAL_PROFILE.replace("id: exp_b1", "id: proj_b1"))
    with pytest.raises(ProfileValidationError, match="duplicate bullet id: proj_b1"):
        load_profile(path)


def test_duplicate_project_id_is_rejected(tmp_path):
    doubled = _MINIMAL_PROFILE.replace(
        "projects:\n", "projects:\n" + _DUPLICATE_PROJECT_BLOCK, 1
    )
    with pytest.raises(ProfileValidationError, match="duplicate project id"):
        load_profile(_write(tmp_path, doubled))


from src.profile import Provenance


def test_prohibited_provenance_cannot_be_renderable(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "provenance: counted", "provenance: contradicted"))
    with pytest.raises(ProfileValidationError, match="renderable"):
        load_profile(path)


def test_metric_ledger_entry_must_be_mapping(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "      tests:\n"
        "        value: 12\n"
        "        provenance: counted\n"
        "        renderable: true\n",
        "      tests: just-a-string\n"))
    with pytest.raises(ProfileValidationError, match="expected mapping"):
        load_profile(path)


def test_metric_ledger_rejects_unknown_key(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "        renderable: true\n", "        renderable: true\n        bogus: 1\n"))
    with pytest.raises(ProfileValidationError, match="unknown key"):
        load_profile(path)


def test_metric_ledger_renderable_must_be_boolean(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "renderable: true", 'renderable: "yes"'))
    with pytest.raises(ProfileValidationError, match="expected boolean"):
        load_profile(path)


def test_metric_ledger_happy_path(tmp_path):
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    entry = profile.projects[0].metric_ledger["tests"]
    assert entry.value == 12
    assert entry.provenance is Provenance.COUNTED
    assert entry.renderable is True
    assert profile.projects[0].metric_scope["test_scope"] == "unit tests only"


from src.profile import GapStatus, Severity


def test_resolved_is_not_a_severity(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "severity: medium", "severity: resolved"))
    with pytest.raises(ProfileValidationError, match="severity"):
        load_profile(path)


def test_known_gap_defaults_to_open(tmp_path):
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    gap = profile.projects[0].known_gaps[0]
    assert gap.severity is Severity.MEDIUM
    assert gap.status is GapStatus.OPEN


def test_happy_path_loads_every_section(tmp_path):
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    assert profile.schema_version == "0.3.0"
    assert profile.identity["name"] == "Himanshu Jain"
    assert profile.education[0]["institution"] == "San Jose State University"
    assert profile.skills["languages"] == ("Python", "Java")
    assert len(profile.projects) == 1
    assert len(profile.experience) == 1
    assert profile.do_not_claim == ("Kubernetes",)


def test_missing_required_top_level_key_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace("identity:", "identity_typo:", 1))
    with pytest.raises(ProfileValidationError, match="identity: missing required key"):
        load_profile(path)


def test_do_not_claim_defaults_to_empty(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "do_not_claim:\n  - Kubernetes\n", ""))
    assert load_profile(path).do_not_claim == ()


def test_duplicate_do_not_claim_entry_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "  - Kubernetes\n", "  - Kubernetes\n  - kubernetes\n"))
    with pytest.raises(ProfileValidationError, match="duplicate entry"):
        load_profile(path)


def test_do_not_claim_term_may_not_appear_in_skills(tmp_path):
    # TAILORING_METHODOLOGY.md §2: never surface these as skills.
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        'languages: ["Python", "Java"]', 'languages: ["Python", "kubernetes"]'))
    with pytest.raises(
        ProfileValidationError, match="do_not_claim term listed as skill"
    ):
        load_profile(path)


def test_skills_category_may_not_be_empty(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        'languages: ["Python", "Java"]', "languages: []"))
    with pytest.raises(ProfileValidationError, match="nonempty string list"):
        load_profile(path)


def test_unknown_project_reference_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "projects: [proj_one]", "projects: [does_not_exist]"))
    with pytest.raises(ProfileValidationError, match="unknown project id"):
        load_profile(path)


def test_unknown_bullet_reference_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "bullet_order: [exp_b1, proj_b1]", "bullet_order: [nope]"))
    with pytest.raises(ProfileValidationError, match="unknown bullet id"):
        load_profile(path)


def test_duplicate_reference_within_variant_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "bullet_order: [exp_b1, proj_b1]", "bullet_order: [proj_b1, proj_b1]"))
    with pytest.raises(ProfileValidationError, match="duplicate reference"):
        load_profile(path)


def test_blocked_bullet_cannot_be_referenced(tmp_path):
    # Rule 9: ownership_unresolved must not render, enforced at load time.
    blocked = _MINIMAL_PROFILE.replace(
        "      - id: proj_b1\n        claim_type: verified\n        priority: 1\n",
        "      - id: proj_b1\n        claim_type: ownership_unresolved\n"
        "        priority: 1\n        defense: Attribution unconfirmed.\n",
    )
    with pytest.raises(ProfileValidationError, match="blocked"):
        load_profile(_write(tmp_path, blocked))


def test_priority_ordering_within_an_entry_is_enforced(tmp_path):
    # Rule 16: a priority-2 bullet may not precede a priority-1 bullet
    # from the same entry.
    reordered = _MINIMAL_PROFILE.replace(
        "      - id: proj_b1\n        claim_type: verified\n        priority: 1\n",
        "      - id: proj_b0\n        claim_type: verified\n        priority: 2\n"
        "        phrasings:\n          short: Lower priority thing\n"
        "        evidence:\n"
        '          - "src/other.py: other"\n'
        "      - id: proj_b1\n        claim_type: verified\n        priority: 1\n",
    ).replace("bullet_order: [exp_b1, proj_b1]", "bullet_order: [proj_b0, proj_b1]")
    with pytest.raises(ProfileValidationError, match="priority"):
        load_profile(_write(tmp_path, reordered))

def test_real_profile_loads():
    """The shipped profile and the loader must not drift apart again."""
    profile = load_profile("config/master_profile.yaml")
    assert profile.schema_version == "0.3.0"
    assert {"backend", "ml"} <= set(profile.base_variants)
    all_bullets = [
        bullet
        for source in (*profile.projects, *profile.experience)
        for bullet in source.bullets
    ]
    # Every project a base variant references must actually exist. This is the
    # drift that matters; an exact bullet count only breaks on every edit.
    known_project_ids = {project.id for project in profile.projects}
    for name, variant in profile.base_variants.items():
        assert set(variant.projects) <= known_project_ids, name
        assert variant.bullet_order, f"{name} has no bullets and cannot render"

    # Both base variants must be renderable, i.e. carry project bullets rather
    # than only the shared experience bullets.
    project_bullet_ids = {
        bullet.id for project in profile.projects for bullet in project.bullets
    }
    for name in profile.base_variants:
        selected = {bullet.id for bullet in profile.for_tailoring(name).bullets}
        assert selected & project_bullet_ids, f"{name} selects no project bullets"

    # Blocked claims exist in the corpus but must never be selectable.
    assert any(bullet.is_blocked for bullet in all_bullets)
    for name in profile.base_variants:
        assert all(
            not bullet.is_blocked for bullet in profile.for_tailoring(name).bullets
        )

def test_for_tailoring_carries_identity_skills_and_do_not_claim(tmp_path):
    view = load_profile(_write(tmp_path, _MINIMAL_PROFILE)).for_tailoring("backend")
    assert view.identity["name"] == "Himanshu Jain"
    assert view.skills["languages"] == ("Python", "Java")
    assert view.do_not_claim == ("Kubernetes",)


def test_for_tailoring_follows_bullet_order(tmp_path):
    view = load_profile(_write(tmp_path, _MINIMAL_PROFILE)).for_tailoring("backend")
    assert [bullet.id for bullet in view.bullets] == ["exp_b1", "proj_b1"]


def test_for_critic_includes_evidence_and_defense(tmp_path):
    view = load_profile(_write(tmp_path, _MINIMAL_PROFILE)).for_critic("backend")
    bullet = view.bullets[0]
    assert bullet.evidence
    assert hasattr(bullet, "defense")
    assert bullet.ownership_boundary
    assert not hasattr(bullet, "interview_risk")


def test_unknown_base_variant_is_rejected(tmp_path):
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    with pytest.raises(ProfileValidationError, match="unknown base_variant"):
        profile.for_tailoring("quantum")


def test_ats_max_pages_must_be_positive_integer(tmp_path):
    for bad in ('"1"', "0", "-1", "true", "false", "1.5"):
        path = _write(tmp_path, _MINIMAL_PROFILE.replace("max_pages: 1", f"max_pages: {bad}"))
        with pytest.raises(ProfileValidationError, match="max_pages must be a positive integer"):
            load_profile(path)
