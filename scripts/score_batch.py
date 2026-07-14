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

Self-consistency (2026-07-14, see DECISIONS.md): a single scoring pass on the
same chunk showed real run-to-run variance (mean |delta| 0.67, max 2.0, 2/30
threshold flips on the 2026-07-12 batch). Each chunk is now scored
SELF_CONSISTENCY_K independent times; results are combined per job via
`aggregate_self_consistency_runs()` (median fit_score, majority-vote
base_variant, missing_keywords/rationale from the median run). Every one of
the k raw invocations gets its own I11 trace.

Usage: python -m scripts.score_batch data/batch/2026-07-08.json
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path

from scripts import import_scores
from src.llm_trace import write_trace
from src.run_ingest import load_filters_config

logger = logging.getLogger(__name__)

CHUNK_SIZE = 6
SELF_CONSISTENCY_K = 3
BORDERLINE_MARGIN = 0.5
# Resilience for the nested `claude -p` call. A single invocation is one of
# k*num_chunks per run, so any transient failure (silent exit-1, malformed
# JSON) that isn't retried aborts the whole batch and discards every chunk
# already scored. Retry the *invocation* only — the scoring logic is unchanged.
SCORE_MAX_ATTEMPTS = 3
SCORE_RETRY_BASE_DELAY = 2.0  # seconds; exponential backoff with jitter
SCORE_RETRY_MAX_JITTER = 1.0  # seconds added to each backoff to de-correlate calls
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


# Matches a comma that is followed only by whitespace before a closing ] or }.
# Observed twice from the nested scorer (see DECISIONS.md 2026-07-14): a valid
# response with a stray trailing comma, e.g. `{"a": 1,}` or `[1, 2, ]`.
_TRAILING_COMMA_RE = re.compile(r",(\s*[)\]}])")


def repair_trailing_commas(text: str) -> str:
    """Remove trailing commas before a closing brace/bracket.

    Deliberately narrow: it only rewrites `,]`/`,}` (optionally with whitespace
    between). It is applied ONLY as a fallback after a strict parse has already
    failed, so it cannot mask an otherwise-valid-but-wrong response."""
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def parse_scoring_response(raw_output: str) -> list[dict]:
    """Parse a scorer response into the list-of-entries structure.

    Tries a strict `json.loads` first; only if that raises does it apply the
    narrow trailing-comma repair and retry. Validates the shape at the boundary
    so a well-formed-but-wrong response fails here (with context) rather than
    deep inside aggregate_self_consistency_runs()."""
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        repaired = repair_trailing_commas(raw_output)
        if repaired == raw_output:
            raise
        parsed = json.loads(repaired)  # may still raise -- caller handles it
        logger.warning("scorer response had a trailing comma; auto-repaired before parsing")

    if not isinstance(parsed, list) or not parsed:
        raise ValueError(f"scorer response is not a non-empty JSON array (got {type(parsed).__name__})")
    for entry in parsed:
        if not isinstance(entry, dict):
            raise ValueError(f"scorer response entry is not an object: {entry!r}")
        missing = {"id", "fit_score", "base_variant"} - entry.keys()
        if missing:
            raise ValueError(f"scorer response entry {entry.get('id', '?')} missing keys: {sorted(missing)}")
    return parsed


def majority_vote_variant(variants: list[str]) -> str:
    """Majority-vote across the k runs' base_variant calls.

    A genuine tie can't occur at k=3 with the 2-value ALLOWED_BASE_VARIANTS
    enum (2-1 or 3-0 always resolves), but a tie is handled anyway in case a
    run returns something outside the enum. There is no coverage-table
    lookup implemented at scoring time to break a tie by "which variant has
    more resume content" (see DECISIONS.md 2026-07-14) — the fallback is the
    'backend' profile default.
    """
    counts = Counter(variants)
    ranked = counts.most_common()
    if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
        return ranked[0][0]
    return "backend"


def aggregate_self_consistency_runs(
    chunk: list[dict],
    runs: list[list[dict]],
    *,
    threshold: float,
    margin: float = BORDERLINE_MARGIN,
) -> list[dict]:
    """Combine SELF_CONSISTENCY_K independent scoring runs of the same chunk.

    Per job: median fit_score; majority-vote base_variant; missing_keywords
    and rationale taken from whichever run produced the median fit_score
    (the middle entry once runs are sorted by score); borderline is set when
    the median lands within `margin` of `threshold`.
    """
    by_id: dict[int, list[dict]] = defaultdict(list)
    for run in runs:
        for entry in run:
            by_id[entry["id"]].append(entry)

    aggregated: list[dict] = []
    for obj in chunk:
        job_id = obj["id"]
        entries = by_id.get(job_id, [])
        if len(entries) != len(runs):
            raise RuntimeError(
                f"id {job_id}: expected a scored entry from each of {len(runs)} "
                f"self-consistency runs, got {len(entries)}"
            )
        ordered = sorted(entries, key=lambda e: e["fit_score"])
        median_entry = ordered[len(ordered) // 2]
        median_score = statistics.median(e["fit_score"] for e in entries)
        aggregated.append(
            {
                "id": job_id,
                "row_ids": median_entry["row_ids"],
                "fit_score": median_score,
                "base_variant": majority_vote_variant([e["base_variant"] for e in entries]),
                "missing_keywords": median_entry["missing_keywords"],
                "rationale": median_entry["rationale"],
                "borderline": abs(median_score - threshold) <= margin,
            }
        )
    return aggregated


def score_chunk(
    chunk: list[dict],
    *,
    work_dir: Path,
    index: int,
    prompt_text: str,
    profile_text: str,
    claude_cmd: tuple[str, ...] = DEFAULT_CLAUDE_CMD,
    k: int = SELF_CONSISTENCY_K,
    threshold: float = import_scores.DEFAULT_THRESHOLD,
) -> list[dict]:
    # Archived by the wrapper for I11 traceability only — never passed to the
    # nested call, which receives this same content embedded in the prompt.
    chunk_input_path = work_dir / f"chunk_{index}.json"
    chunk_input_path.write_text(json.dumps(chunk, indent=2))

    prompt = build_chunk_prompt(prompt_text, chunk, profile_text)

    runs: list[list[dict]] = []
    for run_index in range(k):
        raw_output, parsed = _invoke_scorer_with_retry(
            prompt, claude_cmd=claude_cmd, index=index, run_index=run_index
        )
        write_trace(
            invocation_type="scoring",
            input_paths=[chunk_input_path, PROFILE_SUMMARY_PATH],
            raw_output=raw_output,
            prompt_path=PROMPT_PATH,
            model=claude_cmd[0],
        )
        runs.append(parsed)

    return aggregate_self_consistency_runs(chunk, runs, threshold=threshold)


def _invoke_scorer_with_retry(
    prompt: str,
    *,
    claude_cmd: tuple[str, ...],
    index: int,
    run_index: int,
    max_attempts: int = SCORE_MAX_ATTEMPTS,
) -> tuple[str, list[dict]]:
    """Run one nested `claude -p` invocation, retrying transient failures.

    Retries a non-zero exit, empty stdout, or an unparseable response (after the
    trailing-comma repair fallback). Returns (raw_output, parsed_entries) on
    success. Raises RuntimeError only after every attempt has been exhausted, so
    a single flaky call no longer aborts the whole batch. The scoring content is
    unchanged -- this wraps the invocation, not the model's reasoning."""
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = subprocess.run(
                [*claude_cmd, prompt], capture_output=True, text=True, timeout=_CLAUDE_TIMEOUT_SECONDS
            )
            if result.returncode != 0:
                raise RuntimeError(f"exit {result.returncode}: {result.stderr.strip() or '<empty stderr>'}")
            raw_output = strip_json_fences(result.stdout)
            if not raw_output:
                raise RuntimeError(f"scorer returned no output (stderr: {result.stderr.strip() or '<empty>'})")
            parsed = parse_scoring_response(raw_output)
            return raw_output, parsed
        except (RuntimeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            last_error = exc
            if attempt < max_attempts:
                delay = SCORE_RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, SCORE_RETRY_MAX_JITTER)
                logger.warning(
                    "chunk %d run %d scoring attempt %d/%d failed (%s); retrying in %.1fs",
                    index, run_index, attempt, max_attempts, exc, delay,
                )
                time.sleep(delay)

    raise RuntimeError(
        f"chunk {index} run {run_index} scoring failed after {max_attempts} attempts: {last_error}"
    )


def score_batch(
    batch_path: str | Path,
    *,
    work_dir: str | Path | None = None,
    chunk_size: int = CHUNK_SIZE,
    claude_cmd: tuple[str, ...] = DEFAULT_CLAUDE_CMD,
    prompt_path: Path = PROMPT_PATH,
    profile_path: Path = PROFILE_SUMMARY_PATH,
    k: int = SELF_CONSISTENCY_K,
    threshold: float = import_scores.DEFAULT_THRESHOLD,
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
                k=k,
                threshold=threshold,
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
    threshold = args.threshold
    if threshold is None:
        threshold = load_filters_config().get("score_threshold", import_scores.DEFAULT_THRESHOLD)
    out_path = score_batch(args.batch_file, chunk_size=args.chunk_size, threshold=threshold)
    print(f"Scored batch written to {out_path}")
    if args.skip_import:
        return 0
    import_argv = [str(out_path), "--db", args.db]
    if args.threshold is not None:
        import_argv += ["--threshold", str(args.threshold)]
    return import_scores.main(import_argv)


if __name__ == "__main__":
    raise SystemExit(main())
