"""Coverage for scripts/tailor_s3.py (M8P-3R): fail-closed prepare chain
revalidation and invoke/publish. All fixtures use temporary SQLite
databases and config/master_profile.yaml read-only; data/jobs.db is never
touched. No live model call -- subprocess.run is patched throughout."""

import json
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.tailor_s3 import build_parser, cmd_invoke, cmd_prepare, main
from src import db
from src.models import Status
from src.profile import load_profile
from src.tailor.s0 import build_s0_request, s0_request_to_dict, s0_response_to_dict
from src.tailor.s1 import S1Request, s1_request_to_dict, s1_response_to_dict
from src.tailor.s2 import parse_s2_response, s2_request_to_dict, s2_response_to_dict
from src.tailor.s3 import parse_s3_request
from src.tailor.s3_pipeline import S3BundleError, parse_s3_bundle


def test_s3_cli_contract_exists():
    assert callable(cmd_prepare)
    assert callable(cmd_invoke)
    assert build_parser().parse_args(["invoke", "--request", "r", "--banned-words", "b", "--output", "o"]).command == "invoke"


PROFILE_PATH = "config/master_profile.yaml"


def _seed_db(path, *, base_variant="backend", job_id=1, status=Status.SHORTLISTED, jd_text="Python"):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    conn.execute(
        """
        INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at,
                           status, jd_text, jd_quality, base_variant)
        VALUES (?, ?, 'Example', 'Engineer', 'Remote', 'https://example.test/job',
                'inbox', '2026-08-01T00:00:00+00:00', ?, ?, 'ats', ?)
        """,
        (job_id, f"key-{job_id}", status, jd_text, base_variant),
    )
    conn.commit()
    conn.close()


def _clean_profile_path(tmp_path):
    """A copy of the real master profile with do_not_claim emptied.

    The real config/master_profile.yaml's "backend" variant's canonical,
    unedited bullet order already includes a bullet mentioning "Kubernetes"
    while "Kubernetes" is listed in do_not_claim -- a pre-existing profile-
    content condition (not introduced by this repair, and out of scope to
    fix here: M8P-3R may not change profile content). Using this cleaned
    copy for CLI fixtures isolates the invoke/publish tests from that
    unrelated data condition without touching the real file.
    """
    import yaml

    with open(PROFILE_PATH, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    data["do_not_claim"] = []
    path = tmp_path / "clean_profile.yaml"
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
    return str(path)


def _local_fixtures(profile_path):
    """Reimplementation of test_m8p2_contracts._fixtures()/test_s2._request(),
    parameterized by profile path (those shared helpers hardcode the real
    profile path, which this file cannot always use -- see
    _clean_profile_path)."""
    from src.tailor.s0 import parse_s0_response
    from src.tailor.s1 import parse_s1_response
    from src.tailor.s2 import build_s2_request

    profile = load_profile(profile_path)
    positioning = profile.for_positioning()
    catalog = profile.for_selection("backend")
    s1 = parse_s1_response(
        json.dumps(
            {
                "must_have": [{"term": "Python", "quote": "Python"}],
                "nice_to_have": [],
                "responsibilities_summary": [],
                "seniority_signals": [],
                "disqualifiers": [],
                "company_context": None,
                "suspected_injection": [],
            }
        ),
        "Python",
    )
    s0_request = build_s0_request(1, "Example", "Engineer", s1, positioning)
    s0 = parse_s0_response(
        json.dumps(
            {
                "context_mode": "jd_only",
                "points": [
                    {"sentence": "Lead with backend delivery.", "profile_ids": [positioning.projects[0].id], "requirement_terms": ["Python"], "jd_quotes": ["Python"]},
                    {"sentence": "Support the claim with production experience.", "profile_ids": [positioning.experiences[0].id], "requirement_terms": ["Python"], "jd_quotes": ["Python"]},
                ],
            }
        ),
        s0_request,
    )
    s2_request = build_s2_request(1, "Example", "Engineer", s1, s0, catalog)
    return s1, s0, s0_request, s2_request


def _write_valid_s3_inputs(directory, *, profile_path):
    """Build a fully valid, file-based S1->S0->S2 chain for job_id=1 with no
    DB or model call, against the given (real or cleaned) profile path."""
    directory.mkdir(parents=True, exist_ok=True)
    s1, s0, s0_request, s2_request = _local_fixtures(profile_path)

    variant = next(item for item in s2_request.catalog.variants if item.name == "backend")
    s2_valid_raw = {
        "base_variant": "backend",
        "projects": [{"project_id": item, "reason": "selected", "s0_point_indexes": [0]} for item in variant.projects],
        "bullet_order": list(variant.bullet_order),
        # GAP (not "covered"): G1's L3 dual-placement check exempts GAP
        # terms, so an all-empty S3 response passes static G1 without
        # needing a real bullet edit or skill addition.
        "coverage": [{"term": "Python", "status": "gap", "bullet_ids": []}],
    }
    s2_response = parse_s2_response(json.dumps(s2_valid_raw), s2_request)

    s1_request = S1Request(job_id=1, company="Example", title="Engineer", jd_text="Python", jd_quality="ats")

    (directory / "s1_request.json").write_text(json.dumps(s1_request_to_dict(s1_request)))
    (directory / "s1.json").write_text(json.dumps(s1_response_to_dict(s1)))
    (directory / "s0_request.json").write_text(json.dumps(s0_request_to_dict(s0_request)))
    (directory / "s0.json").write_text(json.dumps(s0_response_to_dict(s0)))
    (directory / "s2_request.json").write_text(json.dumps(s2_request_to_dict(s2_request)))
    (directory / "s2.json").write_text(json.dumps(s2_response_to_dict(s2_response)))
    return directory


def _prepare_args(tmp_path, inputs, database, *, output=None, profile=PROFILE_PATH, job_id=1):
    output = output or (tmp_path / "out")
    return type(
        "Args", (),
        {
            "job_id": job_id,
            "db": str(database),
            "profile": profile,
            "s1_request": str(inputs / "s1_request.json"),
            "s1": str(inputs / "s1.json"),
            "s0_request": str(inputs / "s0_request.json"),
            "s0": str(inputs / "s0.json"),
            "s2_request": str(inputs / "s2_request.json"),
            "s2": str(inputs / "s2.json"),
            "output": str(output),
        },
    )()


# ---------------------------------------------------------------------------
# prepare: success + failure matrix
# ---------------------------------------------------------------------------


def test_prepare_success_writes_deterministic_s3_request(tmp_path):
    database = tmp_path / "jobs.db"
    _seed_db(database)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)
    output = tmp_path / "out"
    assert cmd_prepare(_prepare_args(tmp_path, inputs, database, output=output)) == 0
    request_path = output / "s3_request.json"
    assert request_path.exists()
    parsed = parse_s3_request(json.loads(request_path.read_text()))
    assert parsed.job_id == 1 and parsed.company == "Example" and parsed.title == "Engineer"


def test_prepare_rejects_prohibited_job_id(tmp_path):
    database = tmp_path / "jobs.db"
    _seed_db(database, job_id=229, status=Status.SHORTLISTED)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)
    output = tmp_path / "out"
    args = _prepare_args(tmp_path, inputs, database, output=output, job_id=229)
    assert cmd_prepare(args) != 0
    assert not (output / "s3_request.json").exists()


def test_prepare_rejects_ineligible_job_status(tmp_path):
    database = tmp_path / "jobs.db"
    _seed_db(database, status=Status.SCORED)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)
    output = tmp_path / "out"
    assert cmd_prepare(_prepare_args(tmp_path, inputs, database, output=output)) != 0
    assert not (output / "s3_request.json").exists()


def test_prepare_rejects_db_s1_mismatch(tmp_path):
    database = tmp_path / "jobs.db"
    _seed_db(database, jd_text="Python (backend)")  # differs from the persisted s1_request's jd_text
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)
    output = tmp_path / "out"
    assert cmd_prepare(_prepare_args(tmp_path, inputs, database, output=output)) != 0
    assert not (output / "s3_request.json").exists()


def test_prepare_rejects_injection_blocked_s1(tmp_path):
    database = tmp_path / "jobs.db"
    _seed_db(database)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)
    s1_raw = json.loads((inputs / "s1.json").read_text())
    s1_raw["suspected_injection"] = [{"quote": "Python", "reason": "instruction-like"}]
    (inputs / "s1.json").write_text(json.dumps(s1_raw))
    output = tmp_path / "out"
    assert cmd_prepare(_prepare_args(tmp_path, inputs, database, output=output)) != 0
    assert not (output / "s3_request.json").exists()


def test_prepare_rejects_s0_request_drift(tmp_path):
    database = tmp_path / "jobs.db"
    _seed_db(database)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)
    s0_request_raw = json.loads((inputs / "s0_request.json").read_text())
    s0_request_raw["positioning"]["projects"][0]["label"] = "tampered label"
    (inputs / "s0_request.json").write_text(json.dumps(s0_request_raw))
    output = tmp_path / "out"
    assert cmd_prepare(_prepare_args(tmp_path, inputs, database, output=output)) != 0
    assert not (output / "s3_request.json").exists()


def test_prepare_rejects_s0_response_drift(tmp_path):
    database = tmp_path / "jobs.db"
    _seed_db(database)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)
    s0_raw = json.loads((inputs / "s0.json").read_text())
    s0_raw["points"][0]["sentence"] = "a completely different, unvalidated sentence"
    (inputs / "s0.json").write_text(json.dumps(s0_raw))
    output = tmp_path / "out"
    assert cmd_prepare(_prepare_args(tmp_path, inputs, database, output=output)) != 0
    assert not (output / "s3_request.json").exists()


def test_prepare_rejects_s2_request_drift(tmp_path):
    database = tmp_path / "jobs.db"
    _seed_db(database)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)
    s2_request_raw = json.loads((inputs / "s2_request.json").read_text())
    s2_request_raw["catalog"]["bullets"][0]["keywords_hit"] = ["fabricated"]
    (inputs / "s2_request.json").write_text(json.dumps(s2_request_raw))
    output = tmp_path / "out"
    assert cmd_prepare(_prepare_args(tmp_path, inputs, database, output=output)) != 0
    assert not (output / "s3_request.json").exists()


def test_prepare_rejects_s2_response_drift(tmp_path):
    database = tmp_path / "jobs.db"
    _seed_db(database)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)
    s2_raw = json.loads((inputs / "s2.json").read_text())
    s2_raw["bullet_order"] = list(reversed(s2_raw["bullet_order"]))
    (inputs / "s2.json").write_text(json.dumps(s2_raw))
    output = tmp_path / "out"
    assert cmd_prepare(_prepare_args(tmp_path, inputs, database, output=output)) != 0
    assert not (output / "s3_request.json").exists()


def test_prepare_rejects_stale_persisted_catalog(tmp_path):
    """The persisted s2_request's catalog snapshot no longer matches a
    freshly derived one -- simulates S2 having been prepared before a
    profile edit, without also refreshing s2_request.json."""
    database = tmp_path / "jobs.db"
    _seed_db(database)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)
    s2_request_raw = json.loads((inputs / "s2_request.json").read_text())
    s2_request_raw["catalog"]["do_not_claim"] = list(s2_request_raw["catalog"]["do_not_claim"]) + ["stale-entry"]
    (inputs / "s2_request.json").write_text(json.dumps(s2_request_raw))
    output = tmp_path / "out"
    assert cmd_prepare(_prepare_args(tmp_path, inputs, database, output=output)) != 0
    assert not (output / "s3_request.json").exists()


def test_prepare_rejects_changed_db_recommended_variant(tmp_path):
    """The DB row's base_variant no longer matches the variant baked into
    the persisted S1/S0/S2 chain -- the recommendation changed underneath
    an already-prepared request."""
    database = tmp_path / "jobs.db"
    _seed_db(database, base_variant="ml")
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)  # built against "backend"
    output = tmp_path / "out"
    assert cmd_prepare(_prepare_args(tmp_path, inputs, database, output=output)) != 0
    assert not (output / "s3_request.json").exists()


def test_prepare_rejects_current_profile_drift(tmp_path):
    """The live profile file used for this prepare run differs from the one
    the persisted S2 catalog was derived against."""
    import yaml

    database = tmp_path / "jobs.db"
    _seed_db(database)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)
    with open(PROFILE_PATH, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    data["do_not_claim"] = list(data.get("do_not_claim", [])) + ["Freshly Drifted Skill"]
    mutated_profile = tmp_path / "mutated_profile.yaml"
    with open(mutated_profile, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
    output = tmp_path / "out"
    args = _prepare_args(tmp_path, inputs, database, output=output, profile=str(mutated_profile))
    assert cmd_prepare(args) != 0
    assert not (output / "s3_request.json").exists()


def test_prepare_preserves_existing_request_on_later_failure(tmp_path):
    database = tmp_path / "jobs.db"
    _seed_db(database)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)
    output = tmp_path / "out"
    assert cmd_prepare(_prepare_args(tmp_path, inputs, database, output=output)) == 0
    before = (output / "s3_request.json").read_text()

    s1_raw = json.loads((inputs / "s1.json").read_text())
    s1_raw["suspected_injection"] = [{"quote": "Python", "reason": "instruction-like"}]
    (inputs / "s1.json").write_text(json.dumps(s1_raw))
    assert cmd_prepare(_prepare_args(tmp_path, inputs, database, output=output)) != 0

    after = (output / "s3_request.json").read_text()
    assert before == after


def test_prepare_never_touches_production_db_path(tmp_path):
    """Sanity guard: --db always resolves to a tmp_path SQLite file, never
    the real production database."""
    database = tmp_path / "jobs.db"
    _seed_db(database)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=PROFILE_PATH)
    args = _prepare_args(tmp_path, inputs, database)
    assert Path(args.db).resolve() != Path("data/jobs.db").resolve()
    assert Path(args.db).resolve() == database.resolve()


# ---------------------------------------------------------------------------
# invoke: dry-run, valid publication, failure preservation
# ---------------------------------------------------------------------------


def _s3_request_path(tmp_path):
    """A prepared s3_request.json suitable for invoke tests: built against a
    do_not_claim-cleaned profile copy so static G1 passes on the unedited
    canonical draft (see _clean_profile_path)."""
    database = tmp_path / "jobs.db"
    _seed_db(database)
    profile = _clean_profile_path(tmp_path)
    inputs = _write_valid_s3_inputs(tmp_path / "inputs", profile_path=profile)
    output = tmp_path / "prepared"
    assert cmd_prepare(_prepare_args(tmp_path, inputs, database, output=output, profile=profile)) == 0
    return output / "s3_request.json"


def _invoke_args(tmp_path, request_path, *, output=None, dry_run=False, prompt_template=None, trace_dir=None, timeout=300):
    return type(
        "Args", (),
        {
            "request": str(request_path),
            "banned_words": "config/banned_words.txt",
            "output": str(output or (tmp_path / "bundle_out")),
            "prompt_template": prompt_template,
            "trace_dir": trace_dir,
            "timeout": timeout,
            "dry_run": dry_run,
        },
    )()


def test_invoke_dry_run_makes_no_call_trace_or_bundle(tmp_path):
    request_path = _s3_request_path(tmp_path)
    output = tmp_path / "bundle_out"
    with patch.object(subprocess, "run") as mock_run:
        rc = cmd_invoke(_invoke_args(tmp_path, request_path, output=output, dry_run=True, trace_dir=str(tmp_path / "traces")))
    assert rc == 0
    mock_run.assert_not_called()
    assert not output.exists()
    assert not (tmp_path / "traces").exists()


def test_invoke_valid_publishes_bundle_that_reparses_with_authoritative_parser(tmp_path):
    request_path = _s3_request_path(tmp_path)
    request = parse_s3_request(json.loads(request_path.read_text()))
    output = tmp_path / "bundle_out"
    trace_dir = tmp_path / "traces"
    valid_raw = '{"bullet_edits": [], "skill_additions": []}'
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=valid_raw, stderr="")):
        rc = cmd_invoke(_invoke_args(tmp_path, request_path, output=output, trace_dir=str(trace_dir)))
    assert rc == 0
    bundle_path = output / "s3_bundle.json"
    assert bundle_path.exists()
    raw = json.loads(bundle_path.read_text())
    # No dataclass leaked through -- every value is a JSON primitive/container.
    reserialized = json.dumps(raw)
    assert isinstance(json.loads(reserialized), dict)

    from src.tailor.g1 import load_banned_terms

    banned_terms = load_banned_terms(__import__("pathlib").Path("config/banned_words.txt"))
    bundle = parse_s3_bundle(raw, request, banned_terms)
    assert bundle.job_id == request.job_id
    assert bundle.g1.status.value == "static_pass"
    assert len(list(trace_dir.glob("**/*.json"))) == 1


@pytest.mark.parametrize(
    "stdout,expect_trace",
    [
        ("not json at all", True),  # parse failure
        ('{"bullet_edits": [{"bullet_id": "unknown", "after": "x", "motivating_terms": ["Python"], "rule": "terminology_mirroring"}], "skill_additions": []}', True),  # semantic failure
    ],
)
def test_invoke_failure_exits_nonzero_and_preserves_existing_bundle(tmp_path, stdout, expect_trace):
    request_path = _s3_request_path(tmp_path)
    output = tmp_path / "bundle_out"
    trace_dir = tmp_path / "traces"

    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout='{"bullet_edits": [], "skill_additions": []}', stderr="")):
        assert cmd_invoke(_invoke_args(tmp_path, request_path, output=output, trace_dir=str(trace_dir))) == 0
    before = (output / "s3_bundle.json").read_text()
    before_tmp_files = {p.name for p in output.iterdir() if p.name.startswith(".")}

    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=stdout, stderr="")):
        rc = cmd_invoke(_invoke_args(tmp_path, request_path, output=output, trace_dir=str(trace_dir)))
    assert rc != 0
    after = (output / "s3_bundle.json").read_text()
    assert before == after
    after_tmp_files = {p.name for p in output.iterdir() if p.name.startswith(".")}
    assert after_tmp_files == before_tmp_files == set()


def test_invoke_invocation_failure_exits_nonzero_and_preserves_bundle(tmp_path):
    request_path = _s3_request_path(tmp_path)
    output = tmp_path / "bundle_out"
    trace_dir = tmp_path / "traces"
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout='{"bullet_edits": [], "skill_additions": []}', stderr="")):
        assert cmd_invoke(_invoke_args(tmp_path, request_path, output=output, trace_dir=str(trace_dir))) == 0
    before = (output / "s3_bundle.json").read_text()

    with patch.object(subprocess, "run", return_value=MagicMock(returncode=1, stdout="", stderr="boom")):
        rc = cmd_invoke(_invoke_args(tmp_path, request_path, output=output, trace_dir=str(trace_dir)))
    assert rc != 0
    assert (output / "s3_bundle.json").read_text() == before


def test_invoke_g1_failure_exits_nonzero_and_writes_no_bundle(tmp_path):
    request_path = _s3_request_path(tmp_path)
    output = tmp_path / "bundle_out"
    trace_dir = tmp_path / "traces"
    banned_words = tmp_path / "banned.txt"
    banned_words.write_text("Python\n", encoding="utf-8")
    args = _invoke_args(tmp_path, request_path, output=output, trace_dir=str(trace_dir))
    args.banned_words = str(banned_words)
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout='{"bullet_edits": [], "skill_additions": []}', stderr="")):
        rc = cmd_invoke(args)
    assert rc != 0
    assert not (output / "s3_bundle.json").exists()


def test_authoritative_bundle_parser_rejects_tampered_owner(tmp_path):
    """Defect 2 regression at the persisted-artifact boundary: a hand-edited
    bundle with a fabricated bullet owner must be rejected by the strict
    authoritative parser even though it round-trips as valid JSON."""
    request_path = _s3_request_path(tmp_path)
    request = parse_s3_request(json.loads(request_path.read_text()))
    output = tmp_path / "bundle_out"
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout='{"bullet_edits": [], "skill_additions": []}', stderr="")):
        assert cmd_invoke(_invoke_args(tmp_path, request_path, output=output, trace_dir=str(tmp_path / "traces"))) == 0

    raw = json.loads((output / "s3_bundle.json").read_text())
    raw["draft"]["bullets"][0]["owner_id"] = "fabricated-owner"

    from src.tailor.g1 import load_banned_terms
    from pathlib import Path

    banned_terms = load_banned_terms(Path("config/banned_words.txt"))
    with pytest.raises(S3BundleError):
        parse_s3_bundle(raw, request, banned_terms)


def test_authoritative_bundle_parser_rejects_undeclared_text_mutation(tmp_path):
    """Defect 3 regression at the persisted-artifact boundary: mutating an
    unedited bullet's stored text without a corresponding bullet_edit."""
    request_path = _s3_request_path(tmp_path)
    request = parse_s3_request(json.loads(request_path.read_text()))
    output = tmp_path / "bundle_out"
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout='{"bullet_edits": [], "skill_additions": []}', stderr="")):
        assert cmd_invoke(_invoke_args(tmp_path, request_path, output=output, trace_dir=str(tmp_path / "traces"))) == 0

    raw = json.loads((output / "s3_bundle.json").read_text())
    raw["draft"]["bullets"][0]["text"] = raw["draft"]["bullets"][0]["text"] + " Extra unvalidated words."
    raw["draft"]["bullets"][0]["plain_text"] = raw["draft"]["bullets"][0]["plain_text"] + " Extra unvalidated words."

    from src.tailor.g1 import load_banned_terms
    from pathlib import Path

    banned_terms = load_banned_terms(Path("config/banned_words.txt"))
    with pytest.raises(S3BundleError):
        parse_s3_bundle(raw, request, banned_terms)


def test_main_invoke_dry_run_argv(tmp_path):
    request_path = _s3_request_path(tmp_path)
    with patch.object(subprocess, "run") as mock_run:
        rc = main(["invoke", "--request", str(request_path), "--banned-words", "config/banned_words.txt", "--output", str(tmp_path / "out"), "--dry-run"])
    assert rc == 0
    mock_run.assert_not_called()
