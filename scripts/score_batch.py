"""Sub-batched scoring wrapper per PHASE2_KICKOFF.md M6.7 item 1.

Splits an exported batch into chunks of at most CHUNK_SIZE objects, invokes
the headless scorer (`claude -p`) once per chunk against a chunk-local input
file, and concatenates the results into one *.scored.json — the same file
scripts/import_scores.py already validates and applies. Motivation
(RecruitBench, Sood 2026): scoring a large pool in one prompt under-scores
true positives (lost-in-the-middle); parallel batches of ~6 doubled recall at
unchanged precision.

Usage: python -m scripts.score_batch data/batch/2026-07-08.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from src.llm_trace import write_trace

CHUNK_SIZE = 6
PROMPT_PATH = Path("docs/scoring_prompt.md")
_PROMPT_HEADER_MARKER = "## Prompt"
_CLAUDE_TIMEOUT_SECONDS = 300


def chunk_objects(objects: list[dict], chunk_size: int = CHUNK_SIZE) -> list[list[dict]]:
    return [objects[i : i + chunk_size] for i in range(0, len(objects), chunk_size)]


def build_chunk_prompt(prompt_text: str, chunk_input_path: Path, chunk_output_path: Path) -> str:
    """Same prompt body as docs/scoring_prompt.md, prefixed with an override
    telling the scorer which chunk-local files to use instead of "the most
    recent file in data/batch/" and the date-derived output path."""
    if _PROMPT_HEADER_MARKER not in prompt_text:
        raise ValueError(f"{PROMPT_PATH} is missing the '{_PROMPT_HEADER_MARKER}' section marker")
    body = prompt_text.split(_PROMPT_HEADER_MARKER, 1)[1]
    override = (
        f"For this invocation only, read the batch from `{chunk_input_path}` instead of "
        "\"the most recent file in data/batch/\", and write the scored result to "
        f"`{chunk_output_path}` instead of the date-derived path. All other instructions "
        "in the prompt below apply unchanged.\n\n"
    )
    return override + _PROMPT_HEADER_MARKER + body


def score_chunk(
    chunk: list[dict],
    *,
    work_dir: Path,
    index: int,
    prompt_text: str,
    claude_cmd: tuple[str, ...] = ("claude", "-p"),
) -> list[dict]:
    chunk_input_path = work_dir / f"chunk_{index}.json"
    chunk_output_path = work_dir / f"chunk_{index}.scored.json"
    chunk_input_path.write_text(json.dumps(chunk, indent=2))

    prompt = build_chunk_prompt(prompt_text, chunk_input_path, chunk_output_path)
    result = subprocess.run(
        [*claude_cmd, prompt], capture_output=True, text=True, timeout=_CLAUDE_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        raise RuntimeError(f"chunk {index} scoring failed (exit {result.returncode}): {result.stderr}")
    if not chunk_output_path.exists():
        raise RuntimeError(f"chunk {index} scorer did not write {chunk_output_path}")
    raw_output = chunk_output_path.read_text()
    write_trace(
        invocation_type="scoring",
        input_paths=[chunk_input_path],
        raw_output=raw_output,
        prompt_path=PROMPT_PATH,
        model=claude_cmd[0],
    )
    return json.loads(raw_output)


def score_batch(
    batch_path: str | Path,
    *,
    work_dir: str | Path | None = None,
    chunk_size: int = CHUNK_SIZE,
    claude_cmd: tuple[str, ...] = ("claude", "-p"),
    prompt_path: Path = PROMPT_PATH,
) -> Path:
    batch_path = Path(batch_path)
    objects = json.loads(batch_path.read_text())
    prompt_text = prompt_path.read_text()
    resolved_work_dir = Path(work_dir) if work_dir is not None else batch_path.parent
    resolved_work_dir.mkdir(parents=True, exist_ok=True)

    all_scored: list[dict] = []
    for index, chunk in enumerate(chunk_objects(objects, chunk_size)):
        all_scored.extend(
            score_chunk(
                chunk, work_dir=resolved_work_dir, index=index, prompt_text=prompt_text, claude_cmd=claude_cmd
            )
        )

    out_path = batch_path.with_suffix("").with_suffix(".scored.json")
    out_path.write_text(json.dumps(all_scored, indent=2))
    return out_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.score_batch",
        description="Score an exported batch in chunks of at most 6 objects via the headless scorer.",
    )
    parser.add_argument("batch_file", metavar="BATCH_JSON", help="path to the exported *.json batch file")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE, help="max objects per scoring call")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out_path = score_batch(args.batch_file, chunk_size=args.chunk_size)
    print(f"Scored batch written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
