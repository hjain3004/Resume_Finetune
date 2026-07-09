# src/audit/invariants_sources.py (stub — replaced in Task 7)
from src.audit.types import Finding


def check_i1(conn, audit_config, filters_config, freshness_config, repo_root):
    return Finding(invariant="I1", status="PASS")


def check_i2(conn, audit_config, filters_config, freshness_config, repo_root):
    return Finding(invariant="I2", status="PASS")
