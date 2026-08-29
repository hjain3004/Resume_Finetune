"""Extract a real model response from an I11 trace into a committed test
fixture. `data/traces/` is gitignored, so the raw responses that broke S1
live (a fenced response, a curly-apostrophe response) must be extracted
once and committed, following the same pattern scripts/record_fixture.py
already set for the ingestion layer.

Privacy gate (mandatory, not optional): traces embed the JD and profile
content verbatim. This recorder refuses to write any fixture whose
raw_output contains a non-empty value from config/master_profile.yaml's
identity block (name, phone, email, LinkedIn, GitHub, location), and
prints exactly what it refused."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.profile import load_profile

DEFAULT_PROFILE_PATH = Path("config/master_profile.yaml")
DEFAULT_FIXTURE_DIR = Path("tests/fixtures/tailor/traces")


def _identity_values(profile_path: Path = DEFAULT_PROFILE_PATH) -> tuple[str, ...]:
    profile = load_profile(profile_path)
    return tuple(value for value in profile.identity.values() if value)


def record_trace_fixture(
    trace_path: Path, output_path: Path, *, profile_path: Path = DEFAULT_PROFILE_PATH,
) -> None:
    """Write `output_path` containing only the trace's `raw_output`.
    Raises ValueError (message mentions "identity") and writes nothing if
    raw_output contains any identity value."""
    trace = json.loads(Path(trace_path).read_text(encoding="utf-8"))
    raw_output = trace["raw_output"]

    for value in _identity_values(profile_path):
        if value in raw_output:
            print(
                f"record_trace_fixture: refused -- raw_output contains an identity value ({value!r})",
                file=sys.stderr,
            )
            raise ValueError(f"identity leakage: fixture would contain {value!r}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(raw_output, encoding="utf-8")


def main(argv=None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print("usage: python -m scripts.record_trace_fixture <trace.json> <name>", file=sys.stderr)
        return 1
    trace_path, name = args
    output_path = DEFAULT_FIXTURE_DIR / f"{name}.txt"
    try:
        record_trace_fixture(Path(trace_path), output_path)
    except ValueError as exc:
        print(f"record_trace_fixture: {exc}", file=sys.stderr)
        return 1
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"record_trace_fixture: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
