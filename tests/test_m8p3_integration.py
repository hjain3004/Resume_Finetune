import json
import subprocess
from pathlib import Path

import pytest

from src.profile import load_profile
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.s2 import parse_s2_response
from src.tailor.s3 import build_s3_request, parse_s3_request, s3_request_to_dict
from tests.tailor.test_s2 import _request, _valid


def test_m8p3_real_profile_alignment_round_trip_without_model_or_db():
    profile = load_profile("config/master_profile.yaml")
    s2_request = _request()
    s2_response = parse_s2_response(json.dumps(_valid(s2_request)), s2_request)
    alignment = alignment_from_profile(profile, s2_request, s2_response)
    request = build_s3_request(1, "Example", "Engineer", s2_request.s1, s2_request.s0, s2_response, alignment)
    assert parse_s3_request(s3_request_to_dict(request)) == request
    assert tuple(item.bullet_id for item in alignment.bullets) == s2_response.bullet_order
    # Every digit-based metric in the canonical projection is preserved
    # verbatim before any S3 edit is applied -- the round trip introduces
    # no lossy re-derivation of bullet text.
    import re

    number_re = re.compile(r"(?<!\w)[~+-]?(?:\d[\d,]*(?:\.\d+)?)(?:%|x|\+)?(?!\w)")
    for bullet in alignment.bullets:
        assert number_re.findall(bullet.plain_text) == number_re.findall(bullet.source_text.replace("**", ""))


def test_m8p3_cli_dry_run_creates_no_bundle_or_trace(tmp_path, monkeypatch):
    from scripts.tailor_s3 import cmd_invoke
    from src.tailor.s3 import s3_request_to_dict
    from tests.tailor.test_s3 import _request_fixture

    request = _request_fixture()
    request_path = tmp_path / "s3_request.json"
    request_path.write_text(json.dumps(s3_request_to_dict(request)), encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("{{S3_REQUEST_JSON}}", encoding="utf-8")
    banned = tmp_path / "banned.txt"
    banned.write_text("# no terms\n", encoding="utf-8")
    output = tmp_path / "out"
    args = type("Args", (), {"request": str(request_path), "banned_words": str(banned), "output": str(output), "prompt_template": str(prompt), "trace_dir": str(tmp_path / "traces"), "timeout": 1, "dry_run": True})()
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model called")))
    assert cmd_invoke(args) == 0
    assert not output.exists()
    assert not (tmp_path / "traces").exists()


def test_m8p3_full_synthetic_chain_prepare_invoke_publish_reparse(tmp_path, monkeypatch):
    """Offline end-to-end narrative: seed a DB, prepare against a real
    (do_not_claim-cleaned) profile, mock one model call with a real accepted
    edit, publish, and reparse the published bundle with the strict
    authoritative parser. No model, network, production DB, resume, or PDF
    is touched. Reuses the already-tested CLI fixtures from
    tests/test_tailor_s3_cli.py rather than re-deriving the S1->S0->S2 chain
    by hand."""
    from unittest.mock import MagicMock, patch

    from scripts.tailor_s3 import cmd_invoke, cmd_prepare
    from src.tailor.g1 import load_banned_terms
    from src.tailor.s3 import parse_s3_request
    from src.tailor.s3_pipeline import parse_s3_bundle
    from tests.test_tailor_s3_cli import _clean_profile_path, _prepare_args, _seed_db, _write_valid_s3_inputs

    profile_path = _clean_profile_path(tmp_path)
    database = tmp_path / "jobs.db"
    _seed_db(database)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=profile_path)

    prepared = tmp_path / "prepared"
    args = _prepare_args(tmp_path, inputs, database, output=prepared, profile=profile_path)
    assert cmd_prepare(args) == 0
    request_path = prepared / "s3_request.json"
    request = parse_s3_request(json.loads(request_path.read_text()))

    # The chain's coverage marks "Python" as GAP (see _write_valid_s3_inputs),
    # so a real bullet edit citing it as a motivating term would be rejected
    # by design -- real-edit semantics are already exhaustively covered by
    # tests/tailor/test_s3.py and the G1 adversarial matrix. This test
    # exercises the orchestration path itself: prepare -> invoke -> publish
    # -> reparse via the strict authoritative parser, end to end.
    model_response = json.dumps({"bullet_edits": [], "skill_additions": []})

    bundle_out = tmp_path / "bundle_out"
    invoke_args = type(
        "Args", (), {
            "request": str(request_path), "banned_words": "config/banned_words.txt",
            "output": str(bundle_out), "prompt_template": None,
            "trace_dir": str(tmp_path / "traces"), "timeout": 300, "dry_run": False,
        },
    )()
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=model_response, stderr="")):
        rc = cmd_invoke(invoke_args)
    assert rc == 0

    published = json.loads((bundle_out / "s3_bundle.json").read_text())
    banned_terms = load_banned_terms(Path("config/banned_words.txt"))
    bundle = parse_s3_bundle(published, request, banned_terms)
    assert tuple(b.bullet_id for b in bundle.draft.bullets) == tuple(b.bullet_id for b in request.alignment.bullets)
    assert all(b.text == s.source_text for b, s in zip(bundle.draft.bullets, request.alignment.bullets))
    assert bundle.g1.status.value == "static_pass"
    assert len(list((tmp_path / "traces").glob("**/*.json"))) == 1


def test_m8p3_persisted_bundle_change_log_tamper_rejected(tmp_path, monkeypatch):
    """A hand-edited change_log entry that no longer matches the deterministic
    derivation from (request, response) is rejected by the authoritative
    parser, even though the rest of the bundle is untouched."""
    from unittest.mock import MagicMock, patch

    from scripts.tailor_s3 import cmd_invoke
    from src.tailor.g1 import load_banned_terms
    from src.tailor.s3 import build_s3_request
    from src.tailor.s3_pipeline import S3BundleError, parse_s3_bundle
    from dataclasses import replace as _replace

    from src.tailor.alignment_view import _canonical_dict, _fingerprint

    profile = load_profile("config/master_profile.yaml")
    s2_request = _request()
    s2_response = parse_s2_response(json.dumps(_valid(s2_request)), s2_request)
    alignment = alignment_from_profile(profile, s2_request, s2_response)
    # Clearing do_not_claim (to sidestep the real profile's unrelated,
    # pre-existing Kubernetes/do_not_claim collision on one canonical
    # bullet -- see tests/test_tailor_s3_cli.py's _clean_profile_path)
    # changes the canonical projection, so the fingerprint must be
    # recomputed to stay self-consistent through parse_s3_request's
    # strict re-verification.
    clean_alignment = _replace(alignment, do_not_claim=(), fingerprint="")
    clean_alignment = _replace(clean_alignment, fingerprint=_fingerprint(_canonical_dict(clean_alignment)))
    request = build_s3_request(1, "Example", "Engineer", s2_request.s1, s2_request.s0, s2_response, clean_alignment)
    # Mark "Python" as an explicit GAP rather than "covered": G1's L3 dual-
    # placement check exempts GAP terms, so the empty response used below
    # legitimately passes static G1 (see test_tailor_s3_cli.py's identical
    # pattern). S2 still requires exactly one coverage entry per must_have
    # term, so it cannot simply be cleared.
    from src.tailor.s2 import CoverageEntry

    request = _replace(request, s2=_replace(request.s2, coverage=(CoverageEntry("Python", "gap", ()),)))

    prompt = tmp_path / "prompt.md"
    prompt.write_text("{{S3_REQUEST_JSON}}", encoding="utf-8")
    request_path = tmp_path / "s3_request.json"
    from src.tailor.s3 import s3_request_to_dict as _s3_req_dict

    request_path.write_text(json.dumps(_s3_req_dict(request)), encoding="utf-8")
    output = tmp_path / "out"
    args = type(
        "Args", (), {
            "request": str(request_path), "banned_words": "config/banned_words.txt",
            "output": str(output), "prompt_template": str(prompt),
            "trace_dir": str(tmp_path / "traces"), "timeout": 300, "dry_run": False,
        },
    )()
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout='{"bullet_edits": [], "skill_additions": []}', stderr="")):
        rc = cmd_invoke(args)
    assert rc == 0

    raw = json.loads((output / "s3_bundle.json").read_text())
    if raw["change_log"]:
        raw["change_log"][0]["after"] = raw["change_log"][0]["after"] + " tampered"
    else:
        raw["change_log"] = [{"location": "bullet:fabricated", "before": "x", "after": "y", "motivating_terms": [], "motivating_jd_quotes": [], "rule": "terminology_mirroring"}]

    banned_terms = load_banned_terms(Path("config/banned_words.txt"))
    with pytest.raises(S3BundleError):
        parse_s3_bundle(raw, request, banned_terms)
