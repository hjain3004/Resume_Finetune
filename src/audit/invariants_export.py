"""I3 (duplicate leakage), I3b (over-merge detector), I4 (content purity), I5
(schema completeness) — docs/SELF_HEALING.md §1. All four operate on the
latest data/batch/YYYY-MM-DD.json export file (and, for I5, the latest
*.scored.json if one exists)."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

from src import audit_schema, db
from src.audit import Finding
from src.models import norm
from src.textsim import jaccard_similarity, shingles


def _latest_json_file(directory: Path, *, suffix: str = ".json", exclude_suffix: str | None = None) -> Path | None:
    if not directory.exists():
        return None
    candidates = [
        p for p in directory.glob(f"*{suffix}")
        if exclude_suffix is None or not p.name.endswith(exclude_suffix)
    ]
    if not candidates:
        return None
    return sorted(candidates)[-1]


def _load_batch(repo_root: Path) -> list[dict] | None:
    path = _latest_json_file(repo_root / "data" / "batch", exclude_suffix=".scored.json")
    if path is None:
        return None
    return json.loads(path.read_text())


def _load_scored(repo_root: Path) -> list[dict] | None:
    path = _latest_json_file(repo_root / "data" / "batch", suffix=".scored.json")
    if path is None:
        return None
    return json.loads(path.read_text())


def check_i3(conn, audit_config, filters_config, freshness_config, repo_root) -> Finding:
    """I3 fires on either of two independent signals within the same company:
    (1) content similarity >= threshold, or (2) an exact title match. Signal
    (2) mirrors scripts/export_batch.py's M6.6 _cluster_rows() fix: aggregator
    resolvers like jobright generate a differently-worded AI summary per
    location for the same posting, so same-company+same-title objects can
    legitimately score below any reasonable shingle-similarity threshold. An
    exact title match within a company is itself strong evidence of the same
    posting leaking through as two batch objects. See DECISIONS.md."""
    threshold = audit_config.get("i3", {}).get("similarity_threshold", 0.85)
    batch = _load_batch(Path(repo_root))
    if not batch:
        return Finding(invariant="I3", status="PASS")

    evidence = []
    for a, b in itertools.combinations(batch, 2):
        if norm(a["company"]) != norm(b["company"]):
            continue
        sim = jaccard_similarity(shingles(a["jd_text"]), shingles(b["jd_text"]))
        content_match = sim >= threshold
        title_match = norm(a["title"]) == norm(b["title"])
        if content_match or title_match:
            matched_on = "content" if content_match else "title"
            evidence.append({"ids": [a["id"], b["id"]], "similarity": sim, "matched_on": matched_on})

    status = "FAIL" if evidence else "PASS"
    return Finding(invariant="I3", status=status, evidence=evidence)


def check_i3b(conn, audit_config, filters_config, freshness_config, repo_root) -> Finding:
    threshold = audit_config.get("i3b", {}).get("similarity_threshold", 0.50)
    batch = _load_batch(Path(repo_root))
    if not batch:
        return Finding(invariant="I3b", status="PASS")

    evidence = []
    for obj in batch:
        row_ids = obj["row_ids"]
        if len(row_ids) < 2:
            continue
        texts = {}
        for row_id in row_ids:
            jd_text = db.jd_text_by_id(conn, row_id)
            if jd_text:
                texts[row_id] = jd_text
        pairs = list(itertools.combinations(texts.items(), 2))
        matrix = []
        low_sim_found = False
        for (id_a, text_a), (id_b, text_b) in pairs:
            sim = jaccard_similarity(shingles(text_a), shingles(text_b))
            matrix.append({"pair": [id_a, id_b], "similarity": sim})
            if sim < threshold:
                low_sim_found = True
        if low_sim_found:
            evidence.append({"cluster_id": obj["id"], "row_ids": row_ids, "similarity_matrix": matrix})

    status = "WARN" if evidence else "PASS"
    return Finding(invariant="I3b", status=status, evidence=evidence)


def _load_chrome_patterns(path: Path) -> list[str]:
    patterns = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            patterns.append(line)
    return patterns


def check_i4(conn, audit_config, filters_config, freshness_config, repo_root) -> Finding:
    patterns_path = Path(repo_root) / "config" / "chrome_patterns.txt"
    if not patterns_path.exists():
        patterns_path = Path("config/chrome_patterns.txt")
    patterns = _load_chrome_patterns(patterns_path)

    batch = _load_batch(Path(repo_root))
    if not batch:
        return Finding(invariant="I4", status="PASS")

    evidence = []
    for obj in batch:
        for pattern in patterns:
            if re.search(pattern, obj["jd_text"], re.IGNORECASE | re.MULTILINE):
                evidence.append({"id": obj["id"], "pattern": pattern})
                break

    status = "FAIL" if evidence else "PASS"
    return Finding(invariant="I4", status=status, evidence=evidence)


def check_i5(conn, audit_config, filters_config, freshness_config, repo_root) -> Finding:
    root = Path(repo_root)
    batch_schema_path = root / "config" / "batch_schema.json"
    scored_schema_path = root / "config" / "scored_schema.json"
    if not batch_schema_path.exists():
        batch_schema_path = Path("config/batch_schema.json")
    if not scored_schema_path.exists():
        scored_schema_path = Path("config/scored_schema.json")
    batch_schema = json.loads(batch_schema_path.read_text())
    scored_schema = json.loads(scored_schema_path.read_text())

    evidence = []
    batch = _load_batch(root)
    if batch:
        for obj in batch:
            errors = audit_schema.validate(obj, batch_schema)
            if errors:
                evidence.append({"id": obj.get("id"), "errors": errors, "file": "batch"})

    scored = _load_scored(root)
    if scored:
        for obj in scored:
            errors = audit_schema.validate(obj, scored_schema)
            if errors:
                evidence.append({"id": obj.get("id"), "errors": errors, "file": "scored"})

    status = "FAIL" if evidence else "PASS"
    return Finding(invariant="I5", status=status, evidence=evidence)
