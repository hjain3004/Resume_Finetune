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
