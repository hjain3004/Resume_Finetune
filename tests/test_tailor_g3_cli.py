"""Coverage for scripts/tailor_g3.py (M8P-6 Task 6): build/record/summarize.
No model call, no network, no pdflatex, no SQLite. In-process cmd_*() calls
(not real subprocess spawns), matching the established convention from
tests/test_tailor_g2_cli.py and tests/test_tailor_render_cli.py -- kept
uniform with the rest of this test suite's process model."""
import json
from pathlib import Path
from types import SimpleNamespace

from scripts.tailor_g3 import build_parser, cmd_build, cmd_record, cmd_summarize
from src.tailor.g2_pipeline import g2_bundle_to_dict
from src.tailor.publish import render_result_to_dict
from src.tailor.s0 import s0_response_to_dict
from src.tailor.s1 import s1_response_to_dict
from src.tailor.s2 import s2_response_to_dict
from src.tailor.s3_pipeline import s3_bundle_to_dict
from tests.tailor.test_g3 import EDITED_BULLET_ID, _build_chain


def test_g3_cli_contract_exists():
    assert callable(cmd_build) and callable(cmd_record) and callable(cmd_summarize)
    args = build_parser().parse_args(["summarize"])
    assert args.command == "summarize"


def _write_bundles(tmp_path, *, chain=None):
    chain = chain or _build_chain()
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


def test_build_writes_the_three_packet_files(tmp_path):
    bundles, _ = _write_bundles(tmp_path)
    output = tmp_path / "app_dir"
    rc = cmd_build(_build_args(bundles, output))
    assert rc == 0
    for name in ("review.md", "packet.json", "feedback_form.yaml"):
        assert (output / name).exists()


def test_build_rejects_mismatched_fingerprints(tmp_path, capsys):
    from dataclasses import replace
    s3_bundle, g2_bundle, render_result, s1, s0, s2 = _build_chain()
    tampered_render = replace(render_result, alignment_fingerprint="0" * 64)
    bundles, _ = _write_bundles(tmp_path, chain=(s3_bundle, g2_bundle, tampered_render, s1, s0, s2))
    output = tmp_path / "app_dir"

    rc = cmd_build(_build_args(bundles, output))

    assert rc != 0
    assert "fingerprint" in capsys.readouterr().err
    assert not output.exists()


def _fill_form(form_text: str, **overrides) -> str:
    import yaml
    data = yaml.safe_load(form_text)
    data.update({
        "reviewed_at": "2026-08-25", "accept": "accept", "would_submit": "yes",
        "needs_another_revision": "no", "company_alignment": 3, "visual_quality": 3,
    })
    for entry in data["bullet_feedback"]:
        entry["verdict"] = "keep"
    data.update(overrides)
    return yaml.safe_dump(data, sort_keys=False)


def test_record_rejects_an_invalid_form_and_stores_nothing(tmp_path):
    bundles, chain = _write_bundles(tmp_path)
    output = tmp_path / "app_dir"
    assert cmd_build(_build_args(bundles, output)) == 0

    bad_form = tmp_path / "bad_form.yaml"
    bad_form.write_text(
        (output / "feedback_form.yaml").read_text().replace('accept: ""', 'accept: "not_a_real_choice"'),
        encoding="utf-8",
    )
    feedback_dir = tmp_path / "feedback"

    args = type("Args", (), {"form": str(bad_form), "packet": str(output / "packet.json"),
                             "feedback_dir": str(feedback_dir)})()
    rc = cmd_record(args)

    assert rc != 0
    assert not feedback_dir.exists() or not list(feedback_dir.glob("*.json"))


def test_record_then_summarize(tmp_path):
    import contextlib
    import io

    bundles, chain = _write_bundles(tmp_path)
    output = tmp_path / "app_dir"
    assert cmd_build(_build_args(bundles, output)) == 0

    good_form = tmp_path / "good_form.yaml"
    good_form.write_text(_fill_form((output / "feedback_form.yaml").read_text()), encoding="utf-8")
    feedback_dir = tmp_path / "feedback"

    record_args = type("Args", (), {"form": str(good_form), "packet": str(output / "packet.json"),
                                    "feedback_dir": str(feedback_dir)})()
    assert cmd_record(record_args) == 0

    buf = io.StringIO()
    summarize_args = type("Args", (), {"feedback_dir": str(feedback_dir), "job_id": None})()
    with contextlib.redirect_stdout(buf):
        rc = cmd_summarize(summarize_args)
    assert rc == 0
    assert "total: 1" in buf.getvalue()


def test_summarize_writes_nothing(tmp_path):
    import contextlib
    import io

    bundles, chain = _write_bundles(tmp_path)
    output = tmp_path / "app_dir"
    assert cmd_build(_build_args(bundles, output)) == 0
    good_form = tmp_path / "good_form.yaml"
    good_form.write_text(_fill_form((output / "feedback_form.yaml").read_text()), encoding="utf-8")
    feedback_dir = tmp_path / "feedback"
    record_args = type("Args", (), {"form": str(good_form), "packet": str(output / "packet.json"),
                                    "feedback_dir": str(feedback_dir)})()
    assert cmd_record(record_args) == 0

    before = sorted(p.name for p in feedback_dir.iterdir())
    with contextlib.redirect_stdout(io.StringIO()):
        cmd_summarize(type("Args", (), {"feedback_dir": str(feedback_dir), "job_id": None})())
    assert sorted(p.name for p in feedback_dir.iterdir()) == before
