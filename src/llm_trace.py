"""Shared LLM I/O trace-writing helper (I11, docs/SELF_HEALING.md §1). Every
LLM invocation script (scoring, tailoring, critic) must route through
write_trace() so a trace under data/traces/ exists for every scored/tailored
artifact — the audit's I11 check treats a scored artifact with no trace file
anywhere as a bypass of this helper."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_trace(
    *,
    invocation_type: str,
    input_paths: list[Path],
    raw_output: str,
    prompt_path: Path,
    model: str,
    trace_dir: Path = Path("data/traces"),
) -> Path:
    timestamp = _utcnow_iso()
    day_dir = trace_dir / timestamp[:10]
    day_dir.mkdir(parents=True, exist_ok=True)

    prompt_hash = hashlib.sha256(Path(prompt_path).read_bytes()).hexdigest()
    payload = {
        "invocation_type": invocation_type,
        "timestamp": timestamp,
        "model": model,
        "prompt_hash": prompt_hash,
        "inputs": [
            {"path": str(p), "content": Path(p).read_text()} for p in input_paths
        ],
        "raw_output": raw_output,
    }

    safe_stamp = timestamp.replace(":", "").replace("+00:00", "Z")
    output_hash = hashlib.sha256(raw_output.encode("utf-8")).hexdigest()[:8]
    trace_path = day_dir / f"{invocation_type}_{safe_stamp}_{output_hash}.json"
    trace_path.write_text(json.dumps(payload, indent=2))
    return trace_path
