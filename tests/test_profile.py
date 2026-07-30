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
