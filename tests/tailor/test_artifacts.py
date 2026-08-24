import json

import pytest

from src.tailor.artifacts import write_json_atomic


def test_write_json_atomic_is_deterministic_and_creates_parent(tmp_path):
    target = tmp_path / "nested" / "artifact.json"
    write_json_atomic(target, {"z": 1, "a": [2]})
    assert target.read_text() == '{\n  "a": [\n    2\n  ],\n  "z": 1\n}\n'


def test_write_json_atomic_preserves_existing_target_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "artifact.json"
    target.write_text("accepted\n")
    monkeypatch.setattr("src.tailor.artifacts.os.replace", lambda *_: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(OSError):
        write_json_atomic(target, {"new": True})
    assert target.read_text() == "accepted\n"
    assert list(tmp_path.glob(".*.tmp")) == []
