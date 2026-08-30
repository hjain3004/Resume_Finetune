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
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlsplit, urlunsplit

import yaml

from src.resume_evidence.capture import normalize_crawl4ai_capture, normalize_firecrawl_capture, parse_capture, write_capture_atomic
from src.resume_evidence.huntr import parse_huntr_examples, promotable_huntr_examples

MANIFEST_SCHEMA = "m8q.resume_research.v1"
SKELETON_SCHEMA = "m8q.huntr_skeleton.v1"
MIN_HOST_DELAY = 2.0


@dataclass(frozen=True)
class ResearchTarget:
    target_id: str
    url: str
    source_kind: str
    captured_sha256: str | None


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
    if not target.target_id.strip():
        raise ResearchOperatorError("target_id must be nonempty")
    if target.captured_sha256 is not None and (len(target.captured_sha256) != 64 or target.captured_sha256 != target.captured_sha256.lower() or any(char not in "0123456789abcdef" for char in target.captured_sha256)):
        raise ResearchOperatorError("captured_sha256 must be lowercase SHA-256")


def load_source_manifest(path: Path) -> tuple[ResearchTarget, ...]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "targets"} or raw["schema_version"] != MANIFEST_SCHEMA or not isinstance(raw["targets"], list):
        raise ResearchOperatorError("manifest has invalid schema")
    result = []
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
        ids.add(target.target_id); urls.add(canonical); result.append(target)
    return tuple(result)


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp, path)
    except Exception:
        try: os.unlink(temp)
        except OSError: pass
        raise


def _publish_checkpoint(path: Path, entries: list[dict[str, object]]) -> None:
    _atomic_json(path, {"schema_version": MANIFEST_SCHEMA, "captures": entries})


def _default_runner(argv: tuple[str, ...]):
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def run_scrape_batch(targets: tuple[ResearchTarget, ...], output_root: Path, runner=_default_runner, sleeper=sleep, max_pages: int = 5, fallback_runner=None) -> BatchResult:
    if max_pages < 0:
        raise ResearchOperatorError("max_pages must be nonnegative")
    for target in targets:
        validate_research_target(target)
    if len({target.target_id for target in targets}) != len(targets) or len({_canonical_url(target.url) for target in targets}) != len(targets):
        raise ResearchOperatorError("duplicate target")
    output_root = Path(output_root); output_root.mkdir(parents=True, exist_ok=True)
    checkpoint = output_root / "checkpoint.json"
    entries: list[dict[str, object]] = []
    if checkpoint.exists():
        loaded = json.loads(checkpoint.read_text(encoding="utf-8"))
        entries = list(loaded.get("captures", [])) if isinstance(loaded, dict) else []
    succeeded: list[str] = []; skipped: list[str] = []; failed: list[str] = []
    last_call: float | None = None
    for target in targets[:max_pages]:
        output_path = output_root / f"{target.target_id}.json"
        if output_path.exists():
            digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
            if target.captured_sha256 is not None and digest == target.captured_sha256:
                skipped.append(target.target_id); continue
            raise ResearchOperatorError(f"existing output conflict: {target.target_id}")
        if last_call is not None:
            sleeper(MIN_HOST_DELAY)
        argv = ("firecrawl", "scrape", target.url, "--format", "markdown,links", "--only-main-content", "--redact-pii", "--timing", "-o", str(output_path))
        last_call = monotonic()
        result = runner(argv)
        returncode = getattr(result, "returncode", 0)
        if isinstance(result, str):
            stdout = result; returncode = 0
        else:
            stdout = getattr(result, "stdout", "") or ""
        if returncode != 0:
            failure_kind = getattr(result, "failure_kind", "provider_failure")
            if fallback_runner is None or failure_kind not in {"retrieval_failure", "incomplete_extraction"}:
                failed.append(target.target_id)
                raise ResearchOperatorError(f"Firecrawl failed for {target.target_id}")
            fallback_raw = fallback_runner(target.url)
            if isinstance(fallback_raw, ResearchOperatorError):
                failed.append(target.target_id)
                raise fallback_raw
            capture = normalize_crawl4ai_capture(fallback_raw, target.url, datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"), firecrawl_failure=failure_kind)
            write_capture_atomic(output_path, capture)
            digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
            entries.append({"target_id": target.target_id, "url": target.url, "transport": "crawl4ai", "sha256": digest, "status": "fallback_success", "firecrawl_result": failure_kind})
            _publish_checkpoint(checkpoint, entries)
            succeeded.append(target.target_id)
            continue
        if not output_path.exists() and stdout.strip():
            output_path.write_text(stdout, encoding="utf-8")
        if not output_path.exists() or not output_path.read_text(encoding="utf-8").strip():
            failed.append(target.target_id)
            raise ResearchOperatorError(f"Firecrawl output missing or empty: {target.target_id}")
        raw = json.loads(output_path.read_text(encoding="utf-8"))
        capture = normalize_firecrawl_capture(raw, target.url, datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
        write_capture_atomic(output_path, capture)
        digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
        entries.append({"target_id": target.target_id, "url": target.url, "transport": "firecrawl", "sha256": digest, "status": "success"})
        _publish_checkpoint(checkpoint, entries)
        succeeded.append(target.target_id)
    return BatchResult(tuple(succeeded), tuple(skipped), tuple(failed), checkpoint)


def extract_huntr(raw_dir: Path, inbox_dir: Path, manifest_path: Path) -> int:
    targets = {target.target_id: target for target in load_source_manifest(manifest_path)}
    count = 0
    for path in sorted(Path(raw_dir).glob("*.json")):
        if path.name == "checkpoint.json": continue
        capture = parse_capture(json.loads(path.read_text(encoding="utf-8")))
        examples = promotable_huntr_examples(parse_huntr_examples(capture.markdown))
        target_id = next((key for key, target in targets.items() if target.url == capture.source_url), "unknown")
        for example in examples:
            reference_id = f"{target_id}__{example.anchor}"
            skeleton = {"schema_version": SKELETON_SCHEMA, "reference_id": reference_id, "source_url": capture.source_url, "capture_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "target_heading": example.heading, "target_level": example.target_level, "kind": example.kind.value, "outcome_quote": example.outcome_quote, "limitations": list(example.limitations)}
            destination = Path(inbox_dir) / reference_id / "skeleton.yaml"
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".skeleton.", suffix=".tmp", dir=destination.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle: yaml.safe_dump(skeleton, handle, sort_keys=False)
                os.replace(temporary, destination)
            except Exception:
                try: os.unlink(temporary)
                except OSError: pass
                raise
            count += 1
    return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.research_resume_evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    scrape = sub.add_parser("scrape-batch"); scrape.add_argument("--manifest", required=True); scrape.add_argument("--output", required=True); scrape.add_argument("--max-pages", type=int, required=True)
    extract = sub.add_parser("extract-huntr"); extract.add_argument("--raw", required=True); extract.add_argument("--inbox", required=True); extract.add_argument("--manifest", required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "scrape-batch":
            result = run_scrape_batch(load_source_manifest(Path(args.manifest)), Path(args.output), max_pages=args.max_pages)
            print(f"scraped={len(result.succeeded)} skipped={len(result.skipped)}")
        else:
            print(f"skeletons={extract_huntr(Path(args.raw), Path(args.inbox), Path(args.manifest))}")
        return 0
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"research_resume_evidence: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
