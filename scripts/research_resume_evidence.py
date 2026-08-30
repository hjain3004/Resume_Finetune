"""Bounded, research-only acquisition from the public Huntr pages."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlsplit, urlunsplit

import yaml

from src.resume_evidence.capture import (
    normalize_crawl4ai_capture,
    normalize_crawl4ai_page,
    normalize_firecrawl_capture,
    parse_capture,
    write_capture_atomic,
)
from src.resume_evidence.huntr import parse_huntr_page, promotable_huntr_examples
from src.resume_evidence.transport import (
    ResearchOutcome,
    TransportResult,
    classify_firecrawl_result,
)

MANIFEST_SCHEMA = "m8q.resume_research.v1"
SKELETON_SCHEMA = "m8q.huntr_skeleton.v1"
MIN_HOST_DELAY = 2.0
FIRECRAWL_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class ResearchTarget:
    target_id: str
    url: str
    source_kind: str
    captured_sha256: str | None


@dataclass(frozen=True)
class FirecrawlExecution:
    process: subprocess.CompletedProcess[str] | None
    timed_out: bool = False


@dataclass(frozen=True)
class CheckpointAttempt:
    transport: str
    outcome: ResearchOutcome
    diagnostic: str

    def to_dict(self) -> dict[str, object]:
        return {
            "transport": self.transport,
            "outcome": self.outcome.value,
            "diagnostic": self.diagnostic,
        }


@dataclass(frozen=True)
class CheckpointEntry:
    target_id: str
    url: str
    attempts: tuple[CheckpointAttempt, ...]
    status: str
    sha256: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "target_id": self.target_id,
            "url": self.url,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "status": self.status,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class BatchResult:
    succeeded: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[str, ...]
    checkpoint: Path


class ResearchOperatorError(ValueError):
    pass


def _canonical_url(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold().removeprefix("www.")
    return urlunsplit((parts.scheme.casefold(), host, parts.path or "/", "", ""))


def validate_research_target(target: ResearchTarget) -> None:
    if not isinstance(target.target_id, str) or not target.target_id.strip():
        raise ResearchOperatorError("target_id must be nonempty")
    if target.source_kind != "huntr":
        raise ResearchOperatorError("source_kind must be huntr")
    parts = urlsplit(target.url)
    host = (parts.hostname or "").casefold()
    if parts.scheme != "https" or host not in {"huntr.co", "www.huntr.co"}:
        raise ResearchOperatorError("target must use HTTPS and an approved Huntr host")
    if not parts.path.startswith("/resume-examples/") or parts.path == "/resume-examples/":
        raise ResearchOperatorError("target path must be below /resume-examples/")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ResearchOperatorError("target must not contain query, fragment, or userinfo")
    if target.captured_sha256 is not None and (
        not isinstance(target.captured_sha256, str)
        or len(target.captured_sha256) != 64
        or target.captured_sha256 != target.captured_sha256.lower()
        or any(char not in "0123456789abcdef" for char in target.captured_sha256)
    ):
        raise ResearchOperatorError("captured_sha256 must be lowercase SHA-256")


def load_source_manifest(path: Path) -> tuple[ResearchTarget, ...]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema_version", "targets"}
        or raw["schema_version"] != MANIFEST_SCHEMA
        or not isinstance(raw["targets"], list)
    ):
        raise ResearchOperatorError("manifest has invalid schema")
    result: list[ResearchTarget] = []
    ids: set[str] = set()
    urls: set[str] = set()
    for item in raw["targets"]:
        if not isinstance(item, dict) or set(item) != {"target_id", "url", "source_kind", "captured_sha256"}:
            raise ResearchOperatorError("manifest target has invalid fields")
        target = ResearchTarget(item["target_id"], item["url"], item["source_kind"], item["captured_sha256"])
        validate_research_target(target)
        canonical = _canonical_url(target.url)
        if target.target_id in ids:
            raise ResearchOperatorError("duplicate target_id")
        if canonical in urls:
            raise ResearchOperatorError("duplicate canonical URL")
        ids.add(target.target_id)
        urls.add(canonical)
        result.append(target)
    return tuple(result)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _valid_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and value == value.lower() and all(char in "0123456789abcdef" for char in value)


def _parse_checkpoint(path: Path) -> list[CheckpointEntry]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchOperatorError(f"checkpoint is unreadable: {path}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "captures"} or raw["schema_version"] != MANIFEST_SCHEMA or not isinstance(raw["captures"], list):
        raise ResearchOperatorError("checkpoint has invalid schema")
    entries: list[CheckpointEntry] = []
    ids: set[str] = set()
    urls: set[str] = set()
    for raw_entry in raw["captures"]:
        if not isinstance(raw_entry, dict) or set(raw_entry) != {"target_id", "url", "attempts", "status", "sha256"}:
            raise ResearchOperatorError("checkpoint entry has invalid fields")
        target = ResearchTarget(raw_entry["target_id"], raw_entry["url"], "huntr", None)
        validate_research_target(target)
        if target.target_id in ids or _canonical_url(target.url) in urls:
            raise ResearchOperatorError("checkpoint contains duplicate target")
        raw_attempts = raw_entry["attempts"]
        if not isinstance(raw_attempts, list) or not raw_attempts:
            raise ResearchOperatorError("checkpoint attempts must be nonempty")
        attempts: list[CheckpointAttempt] = []
        for raw_attempt in raw_attempts:
            if not isinstance(raw_attempt, dict) or set(raw_attempt) != {"transport", "outcome", "diagnostic"}:
                raise ResearchOperatorError("checkpoint attempt has invalid fields")
            if raw_attempt["transport"] not in {"firecrawl", "crawl4ai"} or not isinstance(raw_attempt["diagnostic"], str) or len(raw_attempt["diagnostic"]) > 2000:
                raise ResearchOperatorError("checkpoint attempt has invalid values")
            try:
                outcome = ResearchOutcome(raw_attempt["outcome"])
            except (TypeError, ValueError) as exc:
                raise ResearchOperatorError("checkpoint attempt has invalid outcome") from exc
            attempts.append(CheckpointAttempt(raw_attempt["transport"], outcome, raw_attempt["diagnostic"]))
        status = raw_entry["status"]
        digest = raw_entry["sha256"]
        if status not in {"succeeded", "skipped", "failed"}:
            raise ResearchOperatorError("checkpoint has invalid status")
        if status in {"succeeded", "skipped"} and not _valid_hash(digest):
            raise ResearchOperatorError("checkpoint success requires SHA-256")
        if status == "failed" and digest is not None:
            raise ResearchOperatorError("checkpoint failure must not have SHA-256")
        if status == "succeeded" and attempts[-1].outcome is not ResearchOutcome.SUCCESS:
            raise ResearchOperatorError("checkpoint success requires successful final attempt")
        if status == "failed" and attempts[-1].outcome is ResearchOutcome.SUCCESS:
            raise ResearchOperatorError("checkpoint failure cannot end in success")
        entries.append(CheckpointEntry(target.target_id, target.url, tuple(attempts), status, digest))
        ids.add(target.target_id)
        urls.add(_canonical_url(target.url))
    return entries


def _publish_checkpoint(path: Path, entries: list[CheckpointEntry]) -> None:
    _atomic_json(path, {"schema_version": MANIFEST_SCHEMA, "captures": [entry.to_dict() for entry in entries]})


def _default_runner(argv: tuple[str, ...]) -> FirecrawlExecution:
    try:
        process = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=FIRECRAWL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        process = subprocess.CompletedProcess(argv, 124, stdout, stderr)
        return FirecrawlExecution(process, timed_out=True)
    return FirecrawlExecution(process)


def _execution(value: object) -> FirecrawlExecution:
    if isinstance(value, FirecrawlExecution):
        return value
    if isinstance(value, subprocess.CompletedProcess):
        return FirecrawlExecution(value)
    if isinstance(value, str):
        process = subprocess.CompletedProcess((), 0, value, "")
        return FirecrawlExecution(process)
    if hasattr(value, "returncode"):
        process = subprocess.CompletedProcess(
            (),
            int(getattr(value, "returncode")),
            getattr(value, "stdout", "") or "",
            getattr(value, "stderr", "") or "",
        )
        return FirecrawlExecution(process)
    process = getattr(value, "process", None)
    if isinstance(process, subprocess.CompletedProcess):
        return FirecrawlExecution(process, bool(getattr(value, "timed_out", False)))
    return FirecrawlExecution(None)


def _safe_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fallback_diagnostic(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:1900]}"


def _normalizable_output(path: Path) -> tuple[bool, object | None]:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return False, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, None
    valid = isinstance(raw, dict) and isinstance(raw.get("data"), dict) and isinstance(raw["data"].get("markdown"), str) and bool(raw["data"]["markdown"].strip())
    return valid, raw


def _default_fallback_factory():
    from src.resolve.browser import Crawl4AIBrowserClient

    return Crawl4AIBrowserClient()


def _run_fallback_client(factory, target: ResearchTarget, failure: ResearchOutcome, clock, sleeper, last_request_at: float | None) -> tuple[object, float]:
    if last_request_at is not None:
        remaining = MIN_HOST_DELAY - (clock() - last_request_at)
        if remaining > 0:
            sleeper(remaining)
    request_started = clock()
    client = factory()
    try:
        client.start()
        page = client.crawl(target.url)
        return page, request_started
    finally:
        client.close()


def run_scrape_batch(
    targets: tuple[ResearchTarget, ...],
    output_root: Path,
    runner=_default_runner,
    sleeper=sleep,
    max_pages: int = 5,
    fallback_runner=None,
    *,
    allow_crawl4ai_fallback: bool = False,
    fallback_factory=None,
    clock=monotonic,
) -> BatchResult:
    if max_pages < 0:
        raise ResearchOperatorError("max_pages must be nonnegative")
    for target in targets:
        validate_research_target(target)
    if len({target.target_id for target in targets}) != len(targets) or len({_canonical_url(target.url) for target in targets}) != len(targets):
        raise ResearchOperatorError("duplicate target")
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    checkpoint = output_root / "checkpoint.json"
    entries = _parse_checkpoint(checkpoint) if checkpoint.exists() else []
    succeeded: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    last_request_at: float | None = None
    for target in targets[:max_pages]:
        output_path = output_root / f"{target.target_id}.json"
        if output_path.exists():
            digest = _file_sha256(output_path)
            if target.captured_sha256 is not None and digest == target.captured_sha256:
                skipped.append(target.target_id)
                continue
            raise ResearchOperatorError(f"existing output conflict: {target.target_id}")
        if last_request_at is not None:
            remaining = MIN_HOST_DELAY - (clock() - last_request_at)
            if remaining > 0:
                sleeper(remaining)
        last_request_at = clock()
        argv = (
            "firecrawl", "scrape", target.url,
            "--format", "markdown,links",
            "--only-main-content", "--redact-pii", "--timing",
            "--proxy", "basic", "-o", str(output_path),
        )
        execution = _execution(runner(argv))
        output_valid, raw = _normalizable_output(output_path)
        if execution.process is not None and execution.process.returncode == 0 and not output_path.exists() and execution.process.stdout:
            output_path.write_text(execution.process.stdout, encoding="utf-8")
            output_valid, raw = _normalizable_output(output_path)
        result: TransportResult = classify_firecrawl_result(
            execution.process,
            output_exists=output_path.exists(),
            output_valid=output_valid,
            timed_out=execution.timed_out,
        )
        attempts = [CheckpointAttempt("firecrawl", result.outcome, result.diagnostic)]
        if result.outcome is ResearchOutcome.SUCCESS:
            assert raw is not None
            capture = normalize_firecrawl_capture(raw, target.url, _safe_timestamp())
            write_capture_atomic(output_path, capture)
            digest = _file_sha256(output_path)
            entries.append(CheckpointEntry(target.target_id, target.url, tuple(attempts), "succeeded", digest))
            _publish_checkpoint(checkpoint, entries)
            succeeded.append(target.target_id)
            continue
        eligible = result.outcome in {ResearchOutcome.RETRIEVAL_FAILURE, ResearchOutcome.INCOMPLETE_EXTRACTION}
        if not allow_crawl4ai_fallback or not eligible:
            entries.append(CheckpointEntry(target.target_id, target.url, tuple(attempts), "failed", None))
            _publish_checkpoint(checkpoint, entries)
            failed.append(target.target_id)
            raise ResearchOperatorError(f"Firecrawl {result.outcome.value} for {target.target_id}: {result.diagnostic}")
        try:
            if fallback_factory is not None:
                page, last_request_at = _run_fallback_client(fallback_factory, target, result.outcome, clock, sleeper, last_request_at)
                capture = normalize_crawl4ai_page(page, target.url, _safe_timestamp(), firecrawl_failure=result.outcome.value)
            elif fallback_runner is not None:
                if last_request_at is not None:
                    remaining = MIN_HOST_DELAY - (clock() - last_request_at)
                    if remaining > 0:
                        sleeper(remaining)
                last_request_at = clock()
                raw_fallback = fallback_runner(target.url)
                capture = normalize_crawl4ai_capture(raw_fallback, target.url, _safe_timestamp(), firecrawl_failure=result.outcome.value)
            else:
                raise ResearchOperatorError("Crawl4AI fallback is enabled but no adapter is configured")
        except Exception as exc:
            attempts.append(CheckpointAttempt("crawl4ai", ResearchOutcome.PROVIDER_FAILURE, _fallback_diagnostic(exc)))
            entries.append(CheckpointEntry(target.target_id, target.url, tuple(attempts), "failed", None))
            _publish_checkpoint(checkpoint, entries)
            failed.append(target.target_id)
            raise
        write_capture_atomic(output_path, capture)
        digest = _file_sha256(output_path)
        attempts.append(CheckpointAttempt("crawl4ai", ResearchOutcome.SUCCESS, ""))
        entries.append(CheckpointEntry(target.target_id, target.url, tuple(attempts), "succeeded", digest))
        _publish_checkpoint(checkpoint, entries)
        succeeded.append(target.target_id)
    return BatchResult(tuple(succeeded), tuple(skipped), tuple(failed), checkpoint)


def extract_huntr(raw_dir: Path, inbox_dir: Path, manifest_path: Path) -> int:
    targets = {target.target_id: target for target in load_source_manifest(manifest_path)}
    count = 0
    for path in sorted(Path(raw_dir).glob("*.json")):
        if path.name == "checkpoint.json":
            continue
        capture = parse_capture(json.loads(path.read_text(encoding="utf-8")))
        page = parse_huntr_page(capture.markdown)
        examples = promotable_huntr_examples(page)
        target_id = next((key for key, target in targets.items() if target.url == capture.source_url), "unknown")
        for example in examples:
            reference_id = f"{target_id}__{example.anchor}"
            skeleton = {
                "schema_version": SKELETON_SCHEMA,
                "reference_id": reference_id,
                "source_url": capture.source_url,
                "capture_sha256": _file_sha256(path),
                "target_heading": example.heading,
                "target_level": example.target_level,
                "kind": example.kind.value,
                "outcome_quote": example.outcome_quote,
                "limitations": list(example.limitations),
            }
            destination = Path(inbox_dir) / reference_id / "skeleton.yaml"
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".skeleton.", suffix=".tmp", dir=destination.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    yaml.safe_dump(skeleton, handle, sort_keys=False)
                os.replace(temporary, destination)
            except Exception:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise
            count += 1
    return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.research_resume_evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scrape = subparsers.add_parser("scrape-batch")
    scrape.add_argument("--manifest", required=True)
    scrape.add_argument("--output", required=True)
    scrape.add_argument("--max-pages", type=int, required=True)
    scrape.add_argument("--allow-crawl4ai-fallback", action="store_true")
    extract = subparsers.add_parser("extract-huntr")
    extract.add_argument("--raw", required=True)
    extract.add_argument("--inbox", required=True)
    extract.add_argument("--manifest", required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "scrape-batch":
            result = run_scrape_batch(
                load_source_manifest(Path(args.manifest)),
                Path(args.output),
                max_pages=args.max_pages,
                allow_crawl4ai_fallback=args.allow_crawl4ai_fallback,
                fallback_factory=_default_fallback_factory if args.allow_crawl4ai_fallback else None,
            )
            print(f"scraped={len(result.succeeded)} skipped={len(result.skipped)}")
        else:
            print(f"skeletons={extract_huntr(Path(args.raw), Path(args.inbox), Path(args.manifest))}")
        return 0
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"research_resume_evidence: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
