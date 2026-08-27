"""Synthetic per-application artifact trees for M8P-7. No model, no network, no DB."""
import json
from pathlib import Path


def write_chain(directory: Path, *, job_id: int = 225, fingerprint: str = "fp1",
                through: str = "s3") -> Path:
    """Write valid-looking accepted artifacts up to and including `through`."""
    directory.mkdir(parents=True, exist_ok=True)
    stages = ["s1", "s0", "s2", "s3", "g2", "render", "g3"]
    files = {"s1": "s1_response.json", "s0": "s0_response.json", "s2": "s2_response.json",
             "s3": "s3_bundle.json", "g2": "g2_bundle.json",
             "render": "render_result.json", "g3": "packet.json"}
    for stage in stages[: stages.index(through) + 1]:
        payload = {"job_id": job_id}
        if stage in {"s2", "s3", "g2", "render", "g3"}:
            payload["alignment_fingerprint"] = fingerprint
        (directory / files[stage]).write_text(json.dumps(payload), encoding="utf-8")
    return directory
