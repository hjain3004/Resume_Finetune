import json
from unittest.mock import MagicMock, patch

from scripts import score_batch
from src import llm_trace

PROMPT_TEXT = """# Scoring prompt

Preamble text about running manually.

---

## Prompt

You are scoring a batch of resolved job postings...
Read the most recent file in `data/batch/` named `YYYY-MM-DD.json`.
"""


def test_chunk_objects_splits_into_groups_of_chunk_size():
    objects = [{"id": i} for i in range(14)]
    chunks = score_batch.chunk_objects(objects, chunk_size=6)
    assert [len(c) for c in chunks] == [6, 6, 2]


def test_chunk_objects_default_chunk_size_is_six():
    objects = [{"id": i} for i in range(13)]
    chunks = score_batch.chunk_objects(objects)
    assert [len(c) for c in chunks] == [6, 6, 1]


def test_build_chunk_prompt_overrides_file_paths_and_keeps_prompt_body():
    prompt = score_batch.build_chunk_prompt(PROMPT_TEXT, "data/batch/chunk_0.json", "data/batch/chunk_0.scored.json")
    assert "data/batch/chunk_0.json" in prompt
    assert "data/batch/chunk_0.scored.json" in prompt
    assert "You are scoring a batch of resolved job postings" in prompt
    assert "Preamble text about running manually" not in prompt


def test_score_chunk_writes_input_invokes_claude_and_reads_output(tmp_path, monkeypatch):
    # chdir so score_chunk's write_trace() call (default trace_dir="data/traces",
    # relative to cwd) lands under tmp_path instead of the repo's real data/traces/ —
    # see bbb2559 for the same class of bug with data/digests/. PROMPT_PATH is
    # normally repo-relative ("docs/scoring_prompt.md"), so it's repointed at a
    # tmp_path-local file that write_trace() can hash after the chdir.
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(PROMPT_TEXT)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(score_batch, "PROMPT_PATH", prompt_path)
    chunk = [{"id": 1, "row_ids": [1], "company": "Acme"}]
    scored = [{"id": 1, "row_ids": [1], "fit_score": 8.0, "base_variant": "backend", "missing_keywords": [], "rationale": "x"}]
    scored_path = tmp_path / "chunk_0.scored.json"

    def fake_run(cmd, **kwargs):
        scored_path.write_text(json.dumps(scored))
        return MagicMock(returncode=0, stderr="")

    with patch.object(score_batch.subprocess, "run", side_effect=fake_run) as mock_run:
        result = score_batch.score_chunk(chunk, work_dir=tmp_path, index=0, prompt_text=PROMPT_TEXT)

    assert result == scored
    assert json.loads((tmp_path / "chunk_0.json").read_text()) == chunk
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["timeout"] == score_batch._CLAUDE_TIMEOUT_SECONDS


def test_score_chunk_raises_on_nonzero_exit(tmp_path):
    with patch.object(score_batch.subprocess, "run", return_value=MagicMock(returncode=1, stderr="boom")):
        try:
            score_batch.score_chunk([{"id": 1}], work_dir=tmp_path, index=0, prompt_text=PROMPT_TEXT)
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "boom" in str(exc)


def test_score_chunk_raises_when_output_file_missing(tmp_path):
    with patch.object(score_batch.subprocess, "run", return_value=MagicMock(returncode=0, stderr="")):
        try:
            score_batch.score_chunk([{"id": 1}], work_dir=tmp_path, index=0, prompt_text=PROMPT_TEXT)
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "did not write" in str(exc)


def test_score_batch_chunks_invokes_per_chunk_and_concatenates(tmp_path):
    batch_path = tmp_path / "2026-07-08.json"
    objects = [{"id": i, "row_ids": [i]} for i in range(1, 9)]  # 8 objects -> 2 chunks of 6/2
    batch_path.write_text(json.dumps(objects))
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(PROMPT_TEXT)

    def fake_score_chunk(chunk, *, work_dir, index, prompt_text, claude_cmd):
        return [{"id": obj["id"], "row_ids": obj["row_ids"], "fit_score": 5.0, "base_variant": "backend", "missing_keywords": [], "rationale": "x"} for obj in chunk]

    with patch.object(score_batch, "score_chunk", side_effect=fake_score_chunk) as mock_score_chunk:
        out_path = score_batch.score_batch(batch_path, prompt_path=prompt_path)

    assert mock_score_chunk.call_count == 2
    scored = json.loads(out_path.read_text())
    assert [entry["id"] for entry in scored] == list(range(1, 9))
    assert out_path == tmp_path / "2026-07-08.scored.json"


def test_score_chunk_writes_a_trace(tmp_path, monkeypatch):
    # chdir so the real write_trace() (default trace_dir="data/traces", relative
    # to cwd) lands under tmp_path rather than the repo's real data/traces/.
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(PROMPT_TEXT)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(score_batch, "PROMPT_PATH", prompt_path)
    chunk = [{"id": 1, "row_ids": [1]}]
    output_path = tmp_path / "chunk_0.scored.json"

    def fake_run(cmd, **kwargs):
        output_path.write_text(json.dumps([{"id": 1}]))
        return MagicMock(returncode=0, stderr="")

    with (
        patch.object(score_batch.subprocess, "run", side_effect=fake_run),
        patch.object(score_batch, "write_trace", wraps=llm_trace.write_trace) as spy,
    ):
        score_batch.score_chunk(chunk, work_dir=tmp_path, index=0, prompt_text=PROMPT_TEXT)

    spy.assert_called_once()
    assert spy.call_args.kwargs["invocation_type"] == "scoring"
    assert spy.call_args.kwargs["input_paths"] == [tmp_path / "chunk_0.json"]
    assert spy.call_args.kwargs["prompt_path"] == prompt_path
    traced_files = list((tmp_path / "data" / "traces").glob("**/*.json"))
    assert len(traced_files) == 1
