"""M8P-6 Task 6: adversarial/integration coverage across the full G3 +
feedback CLI path. No model call, no network, no pdflatex, no SQLite write."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import yaml

from scripts.tailor_g3 import cmd_build, cmd_record
from src.tailor.g2_pipeline import g2_bundle_to_dict
from src.tailor.publish import render_result_to_dict
from src.tailor.s0 import s0_response_to_dict
from src.tailor.s1 import s1_response_to_dict
from src.tailor.s2 import s2_response_to_dict
from src.tailor.s3_pipeline import s3_bundle_to_dict
from tests.tailor.test_g3 import _build_chain

DB_PATH = Path("data/jobs.db")
PROTECTED_PATHS = (Path("config/taste.md"), Path("config/banned_words.txt"))


def _write_bundles(tmp_path):
    chain = _build_chain()
    s3_bundle, g2_bundle, render_result, s1, s0, s2 = chain
    paths = SimpleNamespace(
        s3=tmp_path / "s3_bundle.json", g2=tmp_path / "g2_bundle.json",
        render=tmp_path / "render_result.json", s1=tmp_path / "s1.json",
        s0=tmp_path / "s0.json", s2=tmp_path / "s2.json",
    )
    paths.s3.write_text(json.dumps(s3_bundle_to_dict(s3_bundle)), encoding="utf-8")
    paths.g2.write_text(json.dumps(g2_bundle_to_dict(g2_bundle)), encoding="utf-8")
    paths.render.write_text(json.dumps(render_result_to_dict(render_result)), encoding="utf-8")
    paths.s1.write_text(json.dumps(s1_response_to_dict(s1)), encoding="utf-8")
    paths.s0.write_text(json.dumps(s0_response_to_dict(s0)), encoding="utf-8")
    paths.s2.write_text(json.dumps(s2_response_to_dict(s2)), encoding="utf-8")
    return paths, chain


def _build_args(paths, output):
    return type("Args", (), {
        "bundle": str(paths.s3), "g2_bundle": str(paths.g2), "render_result": str(paths.render),
        "s1": str(paths.s1), "s0": str(paths.s0), "s2": str(paths.s2), "output": str(output),
    })()


def _fill_form(form_text: str, **overrides) -> str:
    data = yaml.safe_load(form_text)
    data.update({
        "reviewed_at": "2026-08-25", "accept": "accept", "would_submit": "yes",
        "needs_another_revision": "no", "company_alignment": 3, "visual_quality": 3,
    })
    for entry in data["bullet_feedback"]:
        entry["verdict"] = "keep"
    data.update(overrides)
    return yaml.safe_dump(data, sort_keys=False)


def test_protected_config_files_are_never_written(tmp_path):
    """M8P-6 derives taste candidates; it never edits taste.md or
    banned_words.txt. Runs build + record end to end and checks both."""
    before = {path: path.read_bytes() for path in PROTECTED_PATHS if path.exists()}

    bundles, _ = _write_bundles(tmp_path)
    output = tmp_path / "app_dir"
    assert cmd_build(_build_args(bundles, output)) == 0

    good_form = tmp_path / "good_form.yaml"
    good_form.write_text(_fill_form((output / "feedback_form.yaml").read_text()), encoding="utf-8")
    feedback_dir = tmp_path / "feedback"
    record_args = type("Args", (), {"form": str(good_form), "packet": str(output / "packet.json"),
                                    "feedback_dir": str(feedback_dir)})()
    assert cmd_record(record_args) == 0

    for path, content in before.items():
        assert path.read_bytes() == content


def test_no_sqlite_write(tmp_path):
    checksum_before = hashlib.sha256(DB_PATH.read_bytes()).hexdigest() if DB_PATH.exists() else None

    bundles, _ = _write_bundles(tmp_path)
    output = tmp_path / "app_dir"
    assert cmd_build(_build_args(bundles, output)) == 0
    good_form = tmp_path / "good_form.yaml"
    good_form.write_text(_fill_form((output / "feedback_form.yaml").read_text()), encoding="utf-8")
    feedback_dir = tmp_path / "feedback"
    record_args = type("Args", (), {"form": str(good_form), "packet": str(output / "packet.json"),
                                    "feedback_dir": str(feedback_dir)})()
    assert cmd_record(record_args) == 0

    checksum_after = hashlib.sha256(DB_PATH.read_bytes()).hexdigest() if DB_PATH.exists() else None
    assert checksum_after == checksum_before


def test_second_differing_assessment_preserves_the_first(tmp_path):
    bundles, _ = _write_bundles(tmp_path)
    output = tmp_path / "app_dir"
    assert cmd_build(_build_args(bundles, output)) == 0

    feedback_dir = tmp_path / "feedback"
    good_form = tmp_path / "good_form.yaml"
    good_form.write_text(_fill_form((output / "feedback_form.yaml").read_text()), encoding="utf-8")
    record_args = type("Args", (), {"form": str(good_form), "packet": str(output / "packet.json"),
                                    "feedback_dir": str(feedback_dir)})()
    assert cmd_record(record_args) == 0

    first_files = sorted(feedback_dir.glob("*-r1.json"))
    assert len(first_files) == 1
    first_bytes = first_files[0].read_bytes()

    revised_form = tmp_path / "revised_form.yaml"
    revised_form.write_text(
        _fill_form((output / "feedback_form.yaml").read_text(), would_submit="not_as_is",
                  free_form="on reflection, reword the latency framing"),
        encoding="utf-8",
    )
    revised_args = type("Args", (), {"form": str(revised_form), "packet": str(output / "packet.json"),
                                     "feedback_dir": str(feedback_dir)})()
    assert cmd_record(revised_args) == 0

    assert first_files[0].read_bytes() == first_bytes
    assert len(sorted(feedback_dir.glob("*-r2.json"))) == 1


def test_g3_cli_makes_no_model_call():
    source = Path("scripts/tailor_g3.py").read_text(encoding="utf-8")
    assert "src.tailor.invoke" not in source and "src.llm_trace" not in source
