"""Pilot operator (M8P-7 Task 1): stage table, run manifest, and
skip/conflict logic. No model, no network, no DB, no filesystem I/O beyond
what the test itself sets up under tmp_path."""
import pytest

from src.tailor.pilot import (
    MANIFEST_SCHEMA,
    STAGE_ORDER,
    Stage,
    StageState,
    artifact_path,
    manifest_to_dict,
    parse_manifest,
    rebuild_manifest,
    stage_is_complete,
)
from tests.fixtures.tailor.m8p7_chain import write_chain


def test_stage_order_matches_the_documented_chain():
    assert [s.value for s in STAGE_ORDER] == [
        "prepare", "s1", "s0", "s2", "s3", "g2", "render", "g3"]


def test_complete_stage_with_matching_identity_is_detected(tmp_path):
    write_chain(tmp_path, job_id=225, fingerprint="fp1", through="s3")
    assert stage_is_complete(tmp_path, Stage.S3, job_id=225, alignment_fingerprint="fp1")


def test_stage_with_mismatched_fingerprint_is_not_complete(tmp_path):
    write_chain(tmp_path, job_id=225, fingerprint="fp1", through="s3")
    assert not stage_is_complete(tmp_path, Stage.S3, job_id=225, alignment_fingerprint="fp2")


def test_stage_with_mismatched_job_id_is_not_complete(tmp_path):
    write_chain(tmp_path, job_id=225, fingerprint="fp1", through="s3")
    assert not stage_is_complete(tmp_path, Stage.S3, job_id=999, alignment_fingerprint="fp1")


def test_absent_artifact_is_not_complete(tmp_path):
    write_chain(tmp_path, through="s1")
    assert not stage_is_complete(tmp_path, Stage.S3, job_id=225, alignment_fingerprint="fp1")


def test_manifest_is_rebuilt_from_artifacts_not_from_a_stale_manifest(tmp_path):
    write_chain(tmp_path, through="s2")
    (tmp_path / "run_manifest.json").write_text('{"schema_version": "lies"}', encoding="utf-8")
    manifest = rebuild_manifest(tmp_path, job_id=225, company="Notion", title="SWE")
    assert manifest.schema_version == MANIFEST_SCHEMA
    by_stage = {r.stage: r.state for r in manifest.stages}
    assert by_stage[Stage.S2] is StageState.SKIPPED_COMPLETE
    assert by_stage[Stage.S3] is StageState.PENDING


def test_manifest_always_asserts_zero_mutations_and_submissions(tmp_path):
    manifest = rebuild_manifest(write_chain(tmp_path, through="s1"), job_id=225,
                                company="Notion", title="SWE")
    assert manifest.db_mutations == 0 and manifest.submissions == 0


def test_manifest_round_trips_strictly(tmp_path):
    manifest = rebuild_manifest(write_chain(tmp_path, through="s3"), job_id=225,
                                company="Notion", title="SWE")
    assert parse_manifest(manifest_to_dict(manifest)) == manifest


def test_artifact_path_is_deterministic(tmp_path):
    assert artifact_path(tmp_path, Stage.S3).name == "s3_bundle.json"
