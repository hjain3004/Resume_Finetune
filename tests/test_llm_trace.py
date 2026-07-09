import json

from src.llm_trace import write_trace


def test_write_trace_creates_json_file_with_expected_fields(tmp_path):
    input_file = tmp_path / "chunk_0.json"
    input_file.write_text('[{"id": 1}]')
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("score these jobs")
    trace_dir = tmp_path / "traces"

    path = write_trace(
        invocation_type="scoring",
        input_paths=[input_file],
        raw_output='[{"id": 1, "fit_score": 8}]',
        prompt_path=prompt_file,
        model="claude",
        trace_dir=trace_dir,
    )

    assert path.exists()
    assert path.parent.parent == trace_dir
    data = json.loads(path.read_text())
    assert data["invocation_type"] == "scoring"
    assert data["model"] == "claude"
    assert data["raw_output"] == '[{"id": 1, "fit_score": 8}]'
    assert data["inputs"] == [{"path": str(input_file), "content": '[{"id": 1}]'}]
    assert data["prompt_hash"] == __import__("hashlib").sha256(b"score these jobs").hexdigest()
    assert "timestamp" in data


def test_write_trace_creates_trace_dir_if_missing(tmp_path):
    input_file = tmp_path / "chunk_0.json"
    input_file.write_text("[]")
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("prompt")
    trace_dir = tmp_path / "does" / "not" / "exist"

    write_trace(
        invocation_type="scoring",
        input_paths=[input_file],
        raw_output="[]",
        prompt_path=prompt_file,
        model="claude",
        trace_dir=trace_dir,
    )

    assert trace_dir.exists()
    assert len(list(trace_dir.glob("**/*.json"))) == 1
