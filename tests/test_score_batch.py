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


def test_score_chunk_embeds_content_invokes_claude_with_no_permission_flags(tmp_path, monkeypatch):
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
    scored = [{"id": 1, "row_ids": [1], "fit_score": 8.0, "base_variant": "backend", "missing_keywords": [], "rationale": "x"}]

    def fake_run(cmd, **kwargs):
        return MagicMock(returncode=0, stderr="", stdout=json.dumps(scored))

    with patch.object(score_batch.subprocess, "run", side_effect=fake_run) as mock_run:
        result = score_batch.score_chunk(
            chunk, work_dir=tmp_path, index=0, prompt_text=PROMPT_TEXT, profile_text=PROFILE_TEXT
        )

    assert result == scored
    # archived for I11 traceability, but never referenced in the invoked command
    assert json.loads((tmp_path / "chunk_0.json").read_text()) == chunk
    mock_run.assert_called_once()
    invoked_cmd = mock_run.call_args.args[0]
    assert invoked_cmd[:2] == ["claude", "-p"]
    assert not any(flag.startswith("--permission") or flag.startswith("--allowed") for flag in invoked_cmd)
    assert mock_run.call_args.kwargs["timeout"] == score_batch._CLAUDE_TIMEOUT_SECONDS


def test_score_chunk_strips_fences_from_stdout(tmp_path, monkeypatch):
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(PROMPT_TEXT)
    profile_path = tmp_path / "profile.md"
    profile_path.write_text(PROFILE_TEXT)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(score_batch, "PROMPT_PATH", prompt_path)
    monkeypatch.setattr(score_batch, "PROFILE_SUMMARY_PATH", profile_path)
    scored = [{"id": 1, "row_ids": [1], "fit_score": 8.0, "base_variant": "backend", "missing_keywords": [], "rationale": "x"}]
    fenced_stdout = "```json\n" + json.dumps(scored) + "\n```"

    with patch.object(
        score_batch.subprocess, "run", return_value=MagicMock(returncode=0, stderr="", stdout=fenced_stdout)
    ):
        result = score_batch.score_chunk(
            [{"id": 1}], work_dir=tmp_path, index=0, prompt_text=PROMPT_TEXT, profile_text=PROFILE_TEXT
        )

    assert result == scored


def test_score_chunk_raises_on_nonzero_exit(tmp_path):
    with patch.object(
        score_batch.subprocess, "run", return_value=MagicMock(returncode=1, stderr="boom", stdout="")
    ):
        try:
            score_batch.score_chunk(
                [{"id": 1}], work_dir=tmp_path, index=0, prompt_text=PROMPT_TEXT, profile_text=PROFILE_TEXT
            )
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "boom" in str(exc)


def test_score_chunk_raises_when_stdout_empty(tmp_path):
    with patch.object(
        score_batch.subprocess, "run", return_value=MagicMock(returncode=0, stderr="", stdout="   ")
    ):
        try:
            score_batch.score_chunk(
                [{"id": 1}], work_dir=tmp_path, index=0, prompt_text=PROMPT_TEXT, profile_text=PROFILE_TEXT
            )
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "no output" in str(exc)


def test_score_batch_chunks_invokes_per_chunk_and_concatenates(tmp_path):
    batch_path = tmp_path / "2026-07-08.json"
    objects = [{"id": i, "row_ids": [i]} for i in range(1, 9)]  # 8 objects -> 2 chunks of 6/2
    batch_path.write_text(json.dumps(objects))
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(PROMPT_TEXT)
    profile_path = tmp_path / "profile.md"
    profile_path.write_text(PROFILE_TEXT)

    def fake_score_chunk(chunk, *, work_dir, index, prompt_text, profile_text, claude_cmd):
        return [{"id": obj["id"], "row_ids": obj["row_ids"], "fit_score": 5.0, "base_variant": "backend", "missing_keywords": [], "rationale": "x"} for obj in chunk]

    with patch.object(score_batch, "score_chunk", side_effect=fake_score_chunk) as mock_score_chunk:
        out_path = score_batch.score_batch(batch_path, prompt_path=prompt_path, profile_path=profile_path)

    assert mock_score_chunk.call_count == 2
    scored = json.loads(out_path.read_text())
    assert [entry["id"] for entry in scored] == list(range(1, 9))
    assert out_path == tmp_path / "2026-07-08.scored.json"


def test_score_chunk_writes_a_trace_covering_chunk_and_profile(tmp_path, monkeypatch):
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

    with (
        patch.object(
            score_batch.subprocess,
            "run",
            return_value=MagicMock(returncode=0, stderr="", stdout=json.dumps([{"id": 1}])),
        ),
        patch.object(score_batch, "write_trace", wraps=llm_trace.write_trace) as spy,
    ):
        score_batch.score_chunk(
            chunk, work_dir=tmp_path, index=0, prompt_text=PROMPT_TEXT, profile_text=PROFILE_TEXT
        )

    spy.assert_called_once()
    assert spy.call_args.kwargs["invocation_type"] == "scoring"
    assert spy.call_args.kwargs["input_paths"] == [tmp_path / "chunk_0.json", profile_path]
    assert spy.call_args.kwargs["prompt_path"] == prompt_path
    traced_files = list((tmp_path / "data" / "traces").glob("**/*.json"))
    assert len(traced_files) == 1


def test_main_writes_scored_file_and_invokes_import(tmp_path, monkeypatch):
    batch_path = tmp_path / "2026-07-08.json"
    batch_path.write_text(json.dumps([{"id": 1, "row_ids": [1]}]))
    monkeypatch.chdir(tmp_path)

    scored_path = tmp_path / "2026-07-08.scored.json"
    with (
        patch.object(score_batch, "score_batch", return_value=scored_path) as mock_score_batch,
        patch.object(score_batch.import_scores, "main", return_value=0) as mock_import_main,
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
    ):
        scored_path.write_text("[]")
        exit_code = score_batch.main([str(batch_path), "--skip-import"])

    assert exit_code == 0
    mock_import_main.assert_not_called()
