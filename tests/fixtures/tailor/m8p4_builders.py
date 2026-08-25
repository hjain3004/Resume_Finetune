"""Synthetic M8P-4 inputs. No network, no model, no real profile mutation."""


def valid_scores(**overrides) -> dict[str, int]:
    base = {"C1": 3, "C2": 3, "C3": 3, "C4": 3, "C5": 3}
    base.update(overrides)
    return base


def finding_dict(**overrides) -> dict[str, str]:
    # "target_id" and "quoted_line" match the fixture edited bullet's
    # after-emphasis-stripped text in tests/tailor/conftest.py's
    # s3_pair_with_bundle: "...four asynchronous Python microservices...".
    base = {
        "dimension": "C5",
        "rule_id": "C5.template_phrasing",
        "target_kind": "bullet",
        "target_id": "int_b1",
        "quoted_line": "four asynchronous Python microservices",
        "explanation": "reads as template output",
    }
    base.update(overrides)
    return base
