"""Tier B: cross-check Tier A heuristics against a real resume parser.

Deselected by default (see the `oracle` marker in pyproject.toml). Requires Node.
A disagreement is a finding to investigate and record, not an automatic failure.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path("tests/fixtures/render")
ORACLE = Path("tools/openresume-cli")

pytestmark = pytest.mark.oracle


@pytest.mark.skipif(shutil.which("node") is None, reason="Node not installed")
@pytest.mark.skipif(not ORACLE.exists(), reason="OpenResume CLI not vendored")
def test_oracle_agrees_two_column_fixture_loses_content():
    result = subprocess.run(
        ["node", str(ORACLE / "parse.js"), str(FIXTURES / "bad_two_column.pdf")],
        capture_output=True, text=True, check=True,
    )
    parsed = json.loads(result.stdout)
    assert not parsed.get("workExperiences"), (
        "Tier A flags this fixture as two-column; the oracle should also fail to "
        "extract structured experience from it. Agreement here is what justifies "
        "trusting Tier A in CI."
    )
