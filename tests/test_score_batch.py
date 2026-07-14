import json
from unittest.mock import MagicMock, patch

from scripts import score_batch
from src import llm_trace

PROMPT_TEXT = """# Scoring prompt

Preamble text about running manually.

---

## Prompt

You are scoring a batch of resolved job postings...

### Candidate profile summary

{{PROFILE_SUMMARY}}

### Batch of job postings to score

```json
{{BATCH_JSON}}
```
"""

PROFILE_TEXT = "Himanshu Jain — backend-focused new grad, San Jose, CA."


def test_chunk_objects_splits_into_groups_of_chunk_size():
    objects = [{"id": i} for i in range(14)]
    chunks = score_batch.chunk_objects(objects, chunk_size=6)
    assert [len(c) for c in chunks] == [6, 6, 2]


def test_chunk_objects_default_chunk_size_is_six():
    objects = [{"id": i} for i in range(13)]
    chunks = score_batch.chunk_objects(objects)
    assert [len(c) for c in chunks] == [6, 6, 1]


def test_build_chunk_prompt_embeds_profile_and_batch_and_keeps_prompt_body():
    chunk = [{"id": 1, "row_ids": [1], "company": "Acme"}]
    prompt = score_batch.build_chunk_prompt(PROMPT_TEXT, chunk, PROFILE_TEXT)
    assert PROFILE_TEXT in prompt
    assert '"company": "Acme"' in prompt
    assert "You are scoring a batch of resolved job postings" in prompt
    assert "Preamble text about running manually" not in prompt
    assert "{{PROFILE_SUMMARY}}" not in prompt
    assert "{{BATCH_JSON}}" not in prompt


def test_build_chunk_prompt_missing_markers_raises():
    bad_prompt = "## Prompt\n\nno markers here"
    try:
        score_batch.build_chunk_prompt(bad_prompt, [{"id": 1}], PROFILE_TEXT)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "marker" in str(exc)


def test_strip_json_fences_removes_surrounding_fence():
    fenced = '```json\n[{"id": 1}]\n```'
    assert score_batch.strip_json_fences(fenced) == '[{"id": 1}]'


def test_strip_json_fences_leaves_bare_json_untouched():
    bare = '[{"id": 1}]'
    assert score_batch.strip_json_fences(bare) == bare


def _entry(**overrides) -> dict:
    entry = {
        "id": 1,
        "row_ids": [1],
        "fit_score": 8.0,
        "base_variant": "backend",
        "missing_keywords": [],
        "rationale": "x",
    }
    entry.update(overrides)
    return entry


def test_majority_vote_variant_picks_the_2_of_3_winner():
    assert score_batch.majority_vote_variant(["backend", "ml", "backend"]) == "backend"
    assert score_batch.majority_vote_variant(["ml", "ml", "backend"]) == "ml"


def test_majority_vote_variant_falls_back_to_backend_on_tie():
    assert score_batch.majority_vote_variant(["ml", "backend"]) == "backend"
    assert score_batch.majority_vote_variant(["frontend", "ml"]) == "backend"


def test_aggregate_self_consistency_runs_takes_median_score_and_median_run_fields():
    chunk = [{"id": 1, "row_ids": [1]}]
    runs = [
        [_entry(id=1, fit_score=6.0, rationale="low run", missing_keywords=["a"])],
        [_entry(id=1, fit_score=8.0, rationale="median run", missing_keywords=["b"])],
        [_entry(id=1, fit_score=9.0, rationale="high run", missing_keywords=["c"])],
    ]

    aggregated = score_batch.aggregate_self_consistency_runs(chunk, runs, threshold=7.0)

    assert len(aggregated) == 1
    entry = aggregated[0]
    assert entry["fit_score"] == 8.0
    assert entry["rationale"] == "median run"
    assert entry["missing_keywords"] == ["b"]


def test_aggregate_self_consistency_runs_majority_votes_base_variant():
    chunk = [{"id": 1, "row_ids": [1]}]
    runs = [
        [_entry(id=1, fit_score=7.0, base_variant="backend")],
        [_entry(id=1, fit_score=7.0, base_variant="ml")],
        [_entry(id=1, fit_score=7.0, base_variant="backend")],
    ]

    aggregated = score_batch.aggregate_self_consistency_runs(chunk, runs, threshold=7.0)

    assert aggregated[0]["base_variant"] == "backend"


def test_aggregate_self_consistency_runs_sets_borderline_within_margin():
    chunk = [{"id": 1, "row_ids": [1]}, {"id": 2, "row_ids": [2]}]
    runs = [
        [_entry(id=1, fit_score=7.4), _entry(id=2, fit_score=9.0)],
        [_entry(id=1, fit_score=7.4), _entry(id=2, fit_score=9.0)],
        [_entry(id=1, fit_score=7.4), _entry(id=2, fit_score=9.0)],
    ]

    aggregated = score_batch.aggregate_self_consistency_runs(chunk, runs, threshold=7.0)

    by_id = {e["id"]: e for e in aggregated}
    assert by_id[1]["borderline"] is True  # |7.4 - 7.0| = 0.4 <= 0.5
    assert by_id[2]["borderline"] is False  # |9.0 - 7.0| = 2.0 > 0.5


def test_aggregate_self_consistency_runs_raises_on_missing_entry():
    chunk = [{"id": 1, "row_ids": [1]}]
    runs = [
        [_entry(id=1, fit_score=7.0)],
        [],  # this run returned nothing for id 1
        [_entry(id=1, fit_score=7.0)],
    ]

    try:
        score_batch.aggregate_self_consistency_runs(chunk, runs, threshold=7.0)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "id 1" in str(exc)


def test_score_chunk_invokes_claude_k_times_with_no_permission_flags(tmp_path, monkeypatch):
    # chdir so score_chunk's write_trace() call (default trace_dir="data/traces",
    # relative to cwd) lands under tmp_path instead of the repo's real data/traces/ —
    # see bbb2559 for the same class of bug with data/digests/. PROMPT_PATH is
    # normally repo-relative ("docs/scoring_prompt.md"), so it's repointed at a
    # tmp_path-local file that write_trace() can hash after the chdir.
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(PROMPT_TEXT)
    profile_path = tmp_path / "profile.md"
    profile_path.write_text(PROFILE_TEXT)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(score_batch, "PROMPT_PATH", prompt_path)
    monkeypatch.setattr(score_batch, "PROFILE_SUMMARY_PATH", profile_path)
    chunk = [{"id": 1, "row_ids": [1], "company": "Acme"}]
    scored = [_entry(id=1, fit_score=8.0)]

    def fake_run(cmd, **kwargs):
        return MagicMock(returncode=0, stderr="", stdout=json.dumps(scored))

    with patch.object(score_batch.subprocess, "run", side_effect=fake_run) as mock_run:
        result = score_batch.score_chunk(
            chunk, work_dir=tmp_path, index=0, prompt_text=PROMPT_TEXT, profile_text=PROFILE_TEXT, threshold=7.0
        )

    assert len(result) == 1
    assert result[0]["fit_score"] == 8.0
    # archived for I11 traceability, but never referenced in the invoked command
    assert json.loads((tmp_path / "chunk_0.json").read_text()) == chunk
    assert mock_run.call_count == score_batch.SELF_CONSISTENCY_K
    for call in mock_run.call_args_list:
        invoked_cmd = call.args[0]
        assert invoked_cmd[:2] == ["claude", "-p"]
        assert not any(flag.startswith("--permission") or flag.startswith("--allowed") for flag in invoked_cmd)
        assert call.kwargs["timeout"] == score_batch._CLAUDE_TIMEOUT_SECONDS


def test_score_chunk_strips_fences_from_stdout(tmp_path, monkeypatch):
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(PROMPT_TEXT)
    profile_path = tmp_path / "profile.md"
    profile_path.write_text(PROFILE_TEXT)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(score_batch, "PROMPT_PATH", prompt_path)
    monkeypatch.setattr(score_batch, "PROFILE_SUMMARY_PATH", profile_path)
    scored = [_entry(id=1, fit_score=8.0)]
    fenced_stdout = "```json\n" + json.dumps(scored) + "\n```"

    with patch.object(
        score_batch.subprocess, "run", return_value=MagicMock(returncode=0, stderr="", stdout=fenced_stdout)
    ):
        result = score_batch.score_chunk(
            [{"id": 1, "row_ids": [1]}],
            work_dir=tmp_path,
            index=0,
            prompt_text=PROMPT_TEXT,
            profile_text=PROFILE_TEXT,
            threshold=7.0,
        )

    assert result[0]["fit_score"] == 8.0


def test_score_chunk_raises_on_nonzero_exit_after_retries(tmp_path):
    # A persistently failing invocation is retried SCORE_MAX_ATTEMPTS times, then
    # raises. time.sleep is patched so the backoff doesn't slow the test.
    with (
        patch.object(score_batch.time, "sleep"),
        patch.object(
            score_batch.subprocess, "run", return_value=MagicMock(returncode=1, stderr="boom", stdout="")
        ) as mock_run,
    ):
        try:
            score_batch.score_chunk(
                [{"id": 1, "row_ids": [1]}],
                work_dir=tmp_path,
                index=0,
                prompt_text=PROMPT_TEXT,
                profile_text=PROFILE_TEXT,
            )
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "boom" in str(exc)
            assert "3 attempts" in str(exc)
    assert mock_run.call_count == score_batch.SCORE_MAX_ATTEMPTS


def test_score_chunk_raises_when_stdout_empty_after_retries(tmp_path):
    with (
        patch.object(score_batch.time, "sleep"),
        patch.object(
            score_batch.subprocess, "run", return_value=MagicMock(returncode=0, stderr="", stdout="   ")
        ) as mock_run,
    ):
        try:
            score_batch.score_chunk(
                [{"id": 1, "row_ids": [1]}],
                work_dir=tmp_path,
                index=0,
                prompt_text=PROMPT_TEXT,
                profile_text=PROFILE_TEXT,
            )
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "no output" in str(exc)
    assert mock_run.call_count == score_batch.SCORE_MAX_ATTEMPTS


def test_repair_trailing_commas_removes_stray_commas():
    # The repair strips the comma but may leave interior whitespace, which is
    # still valid JSON -- assert the repaired strings all parse and round-trip.
    for broken, expected in [
        ('{"a": 1,}', {"a": 1}),
        ("[1, 2, ]", [1, 2]),
        ('{"a": [1,],\n}', {"a": [1]}),
    ]:
        assert json.loads(score_batch.repair_trailing_commas(broken)) == expected


def test_repair_trailing_commas_leaves_valid_json_untouched():
    valid = '{"a": 1, "b": [2, 3]}'
    assert score_batch.repair_trailing_commas(valid) == valid


def test_parse_scoring_response_repairs_trailing_comma():
    entry = _entry(id=1, fit_score=8.0)
    # strict json.loads would reject this trailing comma before the closing ]
    raw = "[" + json.dumps(entry) + ",\n]"
    parsed = score_batch.parse_scoring_response(raw)
    assert parsed == [entry]


def test_parse_scoring_response_rejects_missing_keys():
    raw = json.dumps([{"id": 1, "fit_score": 8.0}])  # no base_variant
    try:
        score_batch.parse_scoring_response(raw)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "base_variant" in str(exc)


def test_parse_scoring_response_rejects_non_array():
    try:
        score_batch.parse_scoring_response('{"id": 1}')
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "array" in str(exc)


def test_score_chunk_retries_then_succeeds(tmp_path, monkeypatch):
    # First invocation fails (silent exit-1), retry succeeds. The whole batch
    # must not abort on the first flake.
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(PROMPT_TEXT)
    profile_path = tmp_path / "profile.md"
    profile_path.write_text(PROFILE_TEXT)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(score_batch, "PROMPT_PATH", prompt_path)
    monkeypatch.setattr(score_batch, "PROFILE_SUMMARY_PATH", profile_path)
    scored = json.dumps([_entry(id=1, fit_score=8.0)])
    responses = [
        MagicMock(returncode=1, stderr="", stdout=""),  # transient silent failure
        MagicMock(returncode=0, stderr="", stdout=scored),
        MagicMock(returncode=0, stderr="", stdout=scored),
        MagicMock(returncode=0, stderr="", stdout=scored),
    ]

    with (
        patch.object(score_batch.time, "sleep"),
        patch.object(score_batch.subprocess, "run", side_effect=responses) as mock_run,
    ):
        result = score_batch.score_chunk(
            [{"id": 1, "row_ids": [1]}],
            work_dir=tmp_path,
            index=0,
            prompt_text=PROMPT_TEXT,
            profile_text=PROFILE_TEXT,
            k=3,
            threshold=7.0,
        )

    assert result[0]["fit_score"] == 8.0
    assert mock_run.call_count == 4  # 1 retry + 3 successful runs


def test_score_batch_chunks_invokes_per_chunk_and_concatenates(tmp_path):
    batch_path = tmp_path / "2026-07-08.json"
    objects = [{"id": i, "row_ids": [i]} for i in range(1, 9)]  # 8 objects -> 2 chunks of 6/2
    batch_path.write_text(json.dumps(objects))
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(PROMPT_TEXT)
    profile_path = tmp_path / "profile.md"
    profile_path.write_text(PROFILE_TEXT)

    def fake_score_chunk(chunk, *, work_dir, index, prompt_text, profile_text, claude_cmd, k, threshold):
        return [_entry(id=obj["id"], row_ids=obj["row_ids"], fit_score=5.0) for obj in chunk]

    with patch.object(score_batch, "score_chunk", side_effect=fake_score_chunk) as mock_score_chunk:
        out_path = score_batch.score_batch(batch_path, prompt_path=prompt_path, profile_path=profile_path)

    assert mock_score_chunk.call_count == 2
    scored = json.loads(out_path.read_text())
    assert [entry["id"] for entry in scored] == list(range(1, 9))
    assert out_path == tmp_path / "2026-07-08.scored.json"


def test_score_chunk_writes_a_trace_per_self_consistency_run(tmp_path, monkeypatch):
    # chdir so the real write_trace() (default trace_dir="data/traces", relative
    # to cwd) lands under tmp_path rather than the repo's real data/traces/.
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(PROMPT_TEXT)
    profile_path = tmp_path / "profile.md"
    profile_path.write_text(PROFILE_TEXT)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(score_batch, "PROMPT_PATH", prompt_path)
    monkeypatch.setattr(score_batch, "PROFILE_SUMMARY_PATH", profile_path)
    chunk = [{"id": 1, "row_ids": [1]}]

    def fake_run(cmd, **kwargs):
        return MagicMock(returncode=0, stderr="", stdout=json.dumps([_entry(id=1, fit_score=8.0)]))

    with (
        patch.object(score_batch.subprocess, "run", side_effect=fake_run),
        patch.object(score_batch, "write_trace", wraps=llm_trace.write_trace) as spy,
    ):
        score_batch.score_chunk(
            chunk, work_dir=tmp_path, index=0, prompt_text=PROMPT_TEXT, profile_text=PROFILE_TEXT, threshold=7.0
        )

    assert spy.call_count == score_batch.SELF_CONSISTENCY_K
    for call in spy.call_args_list:
        assert call.kwargs["invocation_type"] == "scoring"
        assert call.kwargs["input_paths"] == [tmp_path / "chunk_0.json", profile_path]
        assert call.kwargs["prompt_path"] == prompt_path
    traced_files = list((tmp_path / "data" / "traces").glob("**/*.json"))
    assert len(traced_files) == score_batch.SELF_CONSISTENCY_K


def test_main_writes_scored_file_and_invokes_import(tmp_path, monkeypatch):
    batch_path = tmp_path / "2026-07-08.json"
    batch_path.write_text(json.dumps([{"id": 1, "row_ids": [1]}]))
    monkeypatch.chdir(tmp_path)

    scored_path = tmp_path / "2026-07-08.scored.json"
    with (
        patch.object(score_batch, "score_batch", return_value=scored_path) as mock_score_batch,
        patch.object(score_batch.import_scores, "main", return_value=0) as mock_import_main,
        patch.object(score_batch, "load_filters_config", return_value={"score_threshold": 7.0}),
    ):
        scored_path.write_text("[]")
        exit_code = score_batch.main([str(batch_path), "--db", "data/jobs.db"])

    assert exit_code == 0
    mock_score_batch.assert_called_once()
    mock_import_main.assert_called_once_with([str(scored_path), "--db", "data/jobs.db"])


def test_main_skip_import_does_not_call_import_scores(tmp_path, monkeypatch):
    batch_path = tmp_path / "2026-07-08.json"
    batch_path.write_text(json.dumps([{"id": 1, "row_ids": [1]}]))
    monkeypatch.chdir(tmp_path)

    scored_path = tmp_path / "2026-07-08.scored.json"
    with (
        patch.object(score_batch, "score_batch", return_value=scored_path),
        patch.object(score_batch.import_scores, "main") as mock_import_main,
        patch.object(score_batch, "load_filters_config", return_value={"score_threshold": 7.0}),
    ):
        scored_path.write_text("[]")
        exit_code = score_batch.main([str(batch_path), "--skip-import"])

    assert exit_code == 0
    mock_import_main.assert_not_called()
