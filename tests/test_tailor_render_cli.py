"""Coverage for scripts/tailor_render.py (M8P-5 Task 6): fail-closed chain
revalidation, accepted-bundle reparse, and render-and-publish. No pdflatex
call in any test -- dry-run tests take the CLI's own no-op path, and every
other scenario fails before ever reaching render_and_publish. In-process
cmd_render() calls (not real subprocess spawns), matching
tests/test_tailor_g2_cli.py's established convention: monkeypatching a real
subprocess's module state is not possible, and every scenario here must
avoid a genuine pdflatex invocation."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from scripts.tailor_render import build_parser, cmd_render
from scripts.tailor_s3 import cmd_invoke as s3_cmd_invoke
from scripts.tailor_s3 import cmd_prepare as s3_cmd_prepare
from tests.test_tailor_s3_cli import (
    _clean_profile_path,
    _invoke_args as _s3_invoke_args,
    _prepare_args as _s3_prepare_args,
    _seed_db,
    _write_valid_s3_inputs,
)


def test_render_cli_contract_exists():
    assert callable(cmd_render)
    args = build_parser().parse_args(["render", "--bundle", "b", "--profile", "p",
                                      "--template", "t", "--db", "d", "--s1-request", "a",
                                      "--s1", "a", "--s0-request", "a", "--s0", "a",
                                      "--s2-request", "a", "--s2", "a", "--root", "r"])
    assert args.command == "render"


def test_applications_directory_is_gitignored():
    assert "applications/" in Path(".gitignore").read_text(encoding="utf-8")


def _render_chain(tmp_path, *, job_id=1):
    """Build a full, real S1->S0->S2->S3 chain via the already-proven S3
    CLI (subprocess mocked to return a valid empty S3 response), producing
    the upstream chain input files (used to rebuild the authoritative
    S3Request) and an accepted s3_bundle.json for the render CLI to
    consume."""
    database = tmp_path / "jobs.db"
    _seed_db(database, job_id=job_id)
    profile = _clean_profile_path(tmp_path)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=profile)

    s3_prepared = tmp_path / "s3_prepared"
    assert s3_cmd_prepare(_s3_prepare_args(tmp_path, inputs, database, output=s3_prepared, profile=profile, job_id=job_id)) == 0

    s3_out = tmp_path / "s3_out"
    valid_raw = '{"bullet_edits": [], "skill_additions": []}'
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=valid_raw, stderr="")):
        assert s3_cmd_invoke(_s3_invoke_args(tmp_path, s3_prepared / "s3_request.json", output=s3_out)) == 0

    return SimpleNamespace(
        database=database, profile=profile, inputs=inputs, job_id=job_id,
        bundle_path=s3_out / "s3_bundle.json",
    )


def _render_args(tmp_path, chain, *, root, bundle=None, banned_words="config/banned_words.txt", dry_run=False):
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
            "bundle": str(bundle if bundle is not None else chain.bundle_path),
            "banned_words": banned_words,
            "template": "profile/template.tex",
            "root": str(root),
            "dry_run": dry_run,
        },
    )()


def test_render_dry_run_writes_nothing(tmp_path):
    chain = _render_chain(tmp_path)
    root = tmp_path / "applications"
    rc = cmd_render(_render_args(tmp_path, chain, root=root, dry_run=True))
    assert rc == 0
    assert not root.exists()


def test_render_rejects_bundle_whose_fingerprint_does_not_match_profile(tmp_path, capsys):
    chain = _render_chain(tmp_path)
    raw_bundle = json.loads(chain.bundle_path.read_text())
    raw_bundle["alignment_fingerprint"] = "0" * 64
    tampered = tmp_path / "tampered_bundle.json"
    tampered.write_text(json.dumps(raw_bundle))
    root = tmp_path / "applications"

    rc = cmd_render(_render_args(tmp_path, chain, root=root, bundle=tampered))

    assert rc != 0
    assert "fingerprint" in capsys.readouterr().err
    assert not root.exists()


def test_render_refuses_a_g1_failing_bundle(tmp_path, capsys):
    """A bundle can never legitimately carry a non-passing G1 report:
    run_s3_invocation only ever persists a bundle on its own VALID outcome,
    which by construction requires static_pass. Re-parsing under DIFFERENT
    banned_terms than the bundle was originally accepted with doesn't
    surface a new (failing) G1 verdict either -- parse_s3_bundle's
    recompute-and-compare design rejects the whole bundle as drifted
    ("does not match deterministic recomputation") rather than letting a
    different G1 report through. Either way the render CLI refuses to
    publish; this test proves that refusal, using the same banned_terms
    override technique as the drift case rather than a separately-recorded
    "bad" bundle file (which cannot exist by construction)."""
    chain = _render_chain(tmp_path)
    banned = tmp_path / "banned.txt"
    banned.write_text("Python\n", encoding="utf-8")
    root = tmp_path / "applications"

    rc = cmd_render(_render_args(tmp_path, chain, root=root, banned_words=str(banned)))

    assert rc != 0
    assert "g1" in capsys.readouterr().err.lower()
    assert not root.exists()
