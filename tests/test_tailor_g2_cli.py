"""Coverage for scripts/tailor_g2.py (M8P-4 Task 6): fail-closed prepare
chain revalidation (S1->S0->S2->S3 plus accepted-bundle reparse) and
invoke/publish. No live model call -- subprocess.run is patched throughout.
Reuses tests.test_tailor_s3_cli's already-proven chain fixtures rather than
re-deriving the S1->S2->S3 construction here.

Deviation from the plan's Task 6 Step 1 pseudocode: the plan illustrates
these tests spawning `python -m scripts.tailor_g2` as a real subprocess.
This file instead calls cmd_prepare/cmd_invoke in-process (as
tests/test_tailor_s3_cli.py already does), because real subprocess
spawning would require faking out the `claude` binary on PATH across a
process boundary to keep "invoke failure" scenarios from ever risking a
real model/network call -- a materially different and riskier mechanism
than patching subprocess.run in-process. Flagged in the final report.
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from scripts.tailor_g2 import build_parser, cmd_invoke, cmd_prepare
from scripts.tailor_s3 import cmd_invoke as s3_cmd_invoke
from scripts.tailor_s3 import cmd_prepare as s3_cmd_prepare
from src.models import Status
from src.tailor.g2_pipeline import parse_g2_bundle
from tests.test_tailor_s3_cli import (
    _clean_profile_path,
    _invoke_args as _s3_invoke_args,
    _prepare_args as _s3_prepare_args,
    _seed_db,
    _write_valid_s3_inputs,
)


def test_g2_cli_contract_exists():
    assert callable(cmd_prepare)
    assert callable(cmd_invoke)
    args = build_parser().parse_args(["invoke", "--request", "r", "--s3-request", "s", "--output", "o"])
    assert args.command == "invoke"


def _g2_chain(tmp_path, *, job_id=1, status=Status.SHORTLISTED):
    """Build a full, real S1->S0->S2->S3 chain via the already-proven S3
    CLI (subprocess mocked to return a valid empty S3 response), producing
    a prepared s3_request.json and an accepted s3_bundle.json for the G2
    CLI to consume."""
    database = tmp_path / "jobs.db"
    _seed_db(database, job_id=job_id, status=status)
    profile = _clean_profile_path(tmp_path)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=profile)

    s3_prepared = tmp_path / "s3_prepared"
    prepare_args = _s3_prepare_args(tmp_path, inputs, database, output=s3_prepared, profile=profile, job_id=job_id)
    assert s3_cmd_prepare(prepare_args) == 0
    s3_request_path = s3_prepared / "s3_request.json"

    s3_out = tmp_path / "s3_out"
    valid_raw = '{"bullet_edits": [], "skill_additions": []}'
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=valid_raw, stderr="")):
        assert s3_cmd_invoke(_s3_invoke_args(tmp_path, s3_request_path, output=s3_out)) == 0

    return SimpleNamespace(
        database=database, profile=profile, inputs=inputs, job_id=job_id,
        s3_request_path=s3_request_path, s3_bundle_path=s3_out / "s3_bundle.json",
    )


def _g2_prepare_args(tmp_path, chain, *, output=None, bundle=None):
    output = output or (tmp_path / "g2_prepared")
    return type(
        "Args", (),
        {
            "job_id": chain.job_id,
            "db": str(chain.database),
            "profile": chain.profile,
            "s1_request": str(chain.inputs / "s1_request.json"),
            "s1": str(chain.inputs / "s1.json"),
            "s0_request": str(chain.inputs / "s0_request.json"),
            "s0": str(chain.inputs / "s0.json"),
            "s2_request": str(chain.inputs / "s2_request.json"),
            "s2": str(chain.inputs / "s2.json"),
            "bundle": str(bundle if bundle is not None else chain.s3_bundle_path),
            "banned_words": "config/banned_words.txt",
            "taste": "config/taste.md",
            "output": str(output),
        },
    )()


def _g2_invoke_args(tmp_path, request_path, s3_request_path, *, output=None, dry_run=False, trace_dir=None, timeout=300, max_rounds=2):
    return type(
        "Args", (),
        {
            "request": str(request_path),
            "s3_request": str(s3_request_path),
            "banned_words": "config/banned_words.txt",
            "taste": "config/taste.md",
            "output": str(output or (tmp_path / "g2_out")),
            "prompt_template": None,
            "s3_prompt_template": None,
            "trace_dir": trace_dir,
            "timeout": timeout,
            "max_rounds": max_rounds,
            "dry_run": dry_run,
        },
    )()


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------


def test_prepare_success_writes_deterministic_artifacts(tmp_path):
    chain = _g2_chain(tmp_path)
    output = tmp_path / "g2_prepared"
    assert cmd_prepare(_g2_prepare_args(tmp_path, chain, output=output)) == 0
    assert (output / "s3_request.json").exists()
    assert (output / "g2_request.json").exists()


def test_prepare_rejects_bundle_with_wrong_fingerprint(tmp_path, capsys):
    chain = _g2_chain(tmp_path)
    raw_bundle = json.loads(chain.s3_bundle_path.read_text())
    raw_bundle["alignment_fingerprint"] = "0" * 64
    tampered = tmp_path / "tampered_bundle.json"
    tampered.write_text(json.dumps(raw_bundle))
    output = tmp_path / "g2_prepared"

    rc = cmd_prepare(_g2_prepare_args(tmp_path, chain, output=output, bundle=tampered))

    assert rc != 0
    assert not (output / "g2_request.json").exists()
    assert "fingerprint" in capsys.readouterr().err


def test_prepare_rejects_prohibited_job(tmp_path, capsys):
    """job 229 is prohibited before any file is even read, so it is fine to
    point --job-id/--db at a separately-seeded prohibited row while reusing
    an unrelated valid chain's file paths for the other flags."""
    chain = _g2_chain(tmp_path, job_id=1)
    prohibited_db = tmp_path / "prohibited.db"
    _seed_db(prohibited_db, job_id=229, status=Status.SHORTLISTED)
    output = tmp_path / "g2_prepared"
    args = _g2_prepare_args(tmp_path, chain, output=output)
    args.job_id = 229
    args.db = str(prohibited_db)

    rc = cmd_prepare(args)

    assert rc != 0
    assert not (output / "g2_request.json").exists()
    assert "prohibited" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# invoke
# ---------------------------------------------------------------------------


def _pass_response_raw():
    return json.dumps({"scores": {"C1": 3, "C2": 3, "C3": 3, "C4": 3, "C5": 3}, "findings": []})


def test_invoke_dry_run_makes_no_call_and_no_artifact(tmp_path):
    chain = _g2_chain(tmp_path)
    prepared = tmp_path / "g2_prepared"
    assert cmd_prepare(_g2_prepare_args(tmp_path, chain, output=prepared)) == 0
    output = tmp_path / "g2_out"
    trace_dir = tmp_path / "data" / "traces"

    with patch.object(subprocess, "run") as mock_run:
        rc = cmd_invoke(
            _g2_invoke_args(
                tmp_path, prepared / "g2_request.json", prepared / "s3_request.json",
                output=output, dry_run=True, trace_dir=str(trace_dir),
            )
        )

    assert rc == 0
    mock_run.assert_not_called()
    assert not (output / "g2_bundle.json").exists()
    assert not trace_dir.exists()


def test_invoke_success_writes_bundle_that_reparses(tmp_path):
    chain = _g2_chain(tmp_path)
    prepared = tmp_path / "g2_prepared"
    assert cmd_prepare(_g2_prepare_args(tmp_path, chain, output=prepared)) == 0
    output = tmp_path / "g2_out"
    trace_dir = tmp_path / "traces"

    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=_pass_response_raw(), stderr="")):
        rc = cmd_invoke(
            _g2_invoke_args(
                tmp_path, prepared / "g2_request.json", prepared / "s3_request.json",
                output=output, trace_dir=str(trace_dir),
            )
        )

    assert rc == 0
    bundle_path = output / "g2_bundle.json"
    assert bundle_path.exists()
    raw = json.loads(bundle_path.read_text())
    parsed = parse_g2_bundle(raw)
    assert parsed.verdict.value == "pass"


def test_invoke_failure_preserves_existing_bundle(tmp_path):
    chain = _g2_chain(tmp_path)
    prepared = tmp_path / "g2_prepared"
    assert cmd_prepare(_g2_prepare_args(tmp_path, chain, output=prepared)) == 0
    output = tmp_path / "g2_out"
    trace_dir = tmp_path / "traces"

    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=_pass_response_raw(), stderr="")):
        assert cmd_invoke(
            _g2_invoke_args(
                tmp_path, prepared / "g2_request.json", prepared / "s3_request.json",
                output=output, trace_dir=str(trace_dir),
            )
        ) == 0
    existing_bytes = (output / "g2_bundle.json").read_bytes()

    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout="not json", stderr="")):
        rc = cmd_invoke(
            _g2_invoke_args(
                tmp_path, prepared / "g2_request.json", prepared / "s3_request.json",
                output=output, trace_dir=str(trace_dir),
            )
        )

    assert rc != 0
    assert (output / "g2_bundle.json").read_bytes() == existing_bytes
