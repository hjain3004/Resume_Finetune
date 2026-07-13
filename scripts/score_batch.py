"""Sub-batched scoring wrapper per PHASE2_KICKOFF.md M6.7 item 1.

Splits an exported batch into chunks of at most CHUNK_SIZE objects and scores
each chunk via a headless `claude -p` call. Trust boundary (2026-07-13,
user-approved PROTECTED-file change, see DECISIONS.md): the nested call is a
pure text-in/text-out function with ZERO filesystem authority — no
permission flags, no tool access. The wrapper embeds the chunk and
`config/profile_summary.md` directly into the prompt text, reads the
response from stdout only, and owns every filesystem write itself
(chunk archival for I11 tracing, the concatenated *.scored.json, and the
call to scripts/import_scores.py). The model never reads or writes a file.

Motivation for sub-batching (RecruitBench, Sood 2026): scoring a large pool
in one prompt under-scores true positives (lost-in-the-middle); parallel
batches of ~6 doubled recall at unchanged precision.

Usage: python -m scripts.score_batch data/batch/2026-07-08.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from scripts import import_scores
from src.llm_trace import write_trace

CHUNK_SIZE = 6
PROMPT_PATH = Path("docs/scoring_prompt.md")
PROFILE_SUMMARY_PATH = Path("config/profile_summary.md")
_PROMPT_HEADER_MARKER = "## Prompt"
_PROFILE_MARKER = "{{PROFILE_SUMMARY}}"
_BATCH_MARKER = "{{BATCH_JSON}}"
_CLAUDE_TIMEOUT_SECONDS = 300
# Pure text-in/text-out: no permission flags, because the prompt asks for no
# tool use at all. Nothing to approve, nothing to sandbox.
DEFAULT_CLAUDE_CMD: tuple[str, ...] = ("claude", "-p")
_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?|\n?```\s*$", re.MULTILINE)


def chunk_objects(objects: list[dict], chunk_size: int = CHUNK_SIZE) -> list[list[dict]]:
    return [objects[i : i + chunk_size] for i in range(0, len(objects), chunk_size)]


def build_chunk_prompt(prompt_text: str, chunk: list[dict], profile_text: str) -> str:
    """Embed the chunk and profile summary directly into the prompt body,
    replacing the {{PROFILE_SUMMARY}} / {{BATCH_JSON}} markers. The model
    receives everything it needs as text; it is never told a file path."""
    if _PROMPT_HEADER_MARKER not in prompt_text:
        raise ValueError(f"{PROMPT_PATH} is missing the '{_PROMPT_HEADER_MARKER}' section marker")
    body = prompt_text.split(_PROMPT_HEADER_MARKER, 1)[1]
    if _PROFILE_MARKER not in body or _BATCH_MARKER not in body:
        raise ValueError(f"{PROMPT_PATH} is missing the '{_PROFILE_MARKER}' or '{_BATCH_MARKER}' marker")
    body = body.replace(_PROFILE_MARKER, profile_text).replace(_BATCH_MARKER, json.dumps(chunk, indent=2))
    return _PROMPT_HEADER_MARKER + body


def strip_json_fences(text: str) -> str:
    """Remove accidental markdown code fences around a JSON response."""
    return _FENCE_RE.sub("", text.strip()).strip()


def score_chunk(
    chunk: list[dict],
    *,
    work_dir: Path,
    index: int,
    prompt_text: str,
    profile_text: str,
    claude_cmd: tuple[str, ...] = DEFAULT_CLAUDE_CMD,
) -> list[dict]:
    # Archived by the wrapper for I11 traceability only — never passed to the
    # nested call, which receives this same content embedded in the prompt.
    chunk_input_path = work_dir / f"chunk_{index}.json"
    chunk_input_path.write_text(json.dumps(chunk, indent=2))

    prompt = build_chunk_prompt(prompt_text, chunk, profile_text)
    result = subprocess.run(
        [*claude_cmd, prompt], capture_output=True, text=True, timeout=_CLAUDE_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        raise RuntimeError(f"chunk {index} scoring failed (exit {result.returncode}): {result.stderr}")
    raw_output = strip_json_fences(result.stdout)
    if not raw_output:
        raise RuntimeError(f"chunk {index} scorer returned no output (stderr: {result.stderr})")
    write_trace(
        invocation_type="scoring",
        input_paths=[chunk_input_path, PROFILE_SUMMARY_PATH],
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
    claude_cmd: tuple[str, ...] = DEFAULT_CLAUDE_CMD,
    prompt_path: Path = PROMPT_PATH,
    profile_path: Path = PROFILE_SUMMARY_PATH,
) -> Path:
    batch_path = Path(batch_path)
    objects = json.loads(batch_path.read_text())
    prompt_text = prompt_path.read_text()
    profile_text = profile_path.read_text()
    resolved_work_dir = Path(work_dir) if work_dir is not None else batch_path.parent
    resolved_work_dir.mkdir(parents=True, exist_ok=True)

    all_scored: list[dict] = []
    for index, chunk in enumerate(chunk_objects(objects, chunk_size)):
        all_scored.extend(
            score_chunk(
                chunk,
                work_dir=resolved_work_dir,
                index=index,
                prompt_text=prompt_text,
                profile_text=profile_text,
                claude_cmd=claude_cmd,
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
    parser.add_argument("--db", metavar="PATH", default="data/jobs.db", help="path to the SQLite database")
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="fit_score threshold for SHORTLISTED (default: config/filters.yaml score_threshold)",
    )
    parser.add_argument(
        "--skip-import",
        action="store_true",
        help="write the *.scored.json file but don't run scripts.import_scores against the DB",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out_path = score_batch(args.batch_file, chunk_size=args.chunk_size)
    print(f"Scored batch written to {out_path}")
    if args.skip_import:
        return 0
    import_argv = [str(out_path), "--db", args.db]
    if args.threshold is not None:
        import_argv += ["--threshold", str(args.threshold)]
    return import_scores.main(import_argv)


if __name__ == "__main__":
    raise SystemExit(main())
