import pytest

from src.profile import ProfileValidationError, load_profile


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
