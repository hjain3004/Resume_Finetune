import json
import pytest
from src.tailor.s1 import parse_s1_response, Requirement

def test_s1_preserves_model_produced_atomic_terms():
    """
    Per M8N-0c design, we fail closed on programmatic Python regex splitting
    to avoid corrupting indivisible concepts like "TCP/IP" or "R&D".
    S1 relies exclusively on the LLM to provide atomic terms (via the prompt).
    This test verifies that parse_s1_response exactly preserves whatever the model outputs.
    """
    jd_text = "We need TCP/IP, React and Node.js, data structures, algorithms, and distributed systems. Also Java / C++."
    # The model should natively output atomic requirements based on its prompt.
    valid_json = {
        "must_have": [
            {"term": "TCP/IP", "quote": "We need TCP/IP"},
            {"term": "React and Node.js", "quote": "React and Node.js"},
            {"term": "data structures", "quote": "data structures, algorithms, and distributed systems"},
            {"term": "algorithms", "quote": "data structures, algorithms, and distributed systems"},
            {"term": "distributed systems", "quote": "data structures, algorithms, and distributed systems"}
        ],
        "nice_to_have": [
            {"term": "Java / C++", "quote": "Java / C++"}
        ],
        "responsibilities_summary": [],
        "seniority_signals": [],
        "disqualifiers": [],
        "company_context": None,
        "suspected_injection": []
    }

    resp = parse_s1_response(json.dumps(valid_json), jd_text)

    # Assert exact preservation of terms and quotes
    assert resp.must_have == (
        Requirement("TCP/IP", "We need TCP/IP"),
        Requirement("React and Node.js", "React and Node.js"),
        Requirement("data structures", "data structures, algorithms, and distributed systems"),
        Requirement("algorithms", "data structures, algorithms, and distributed systems"),
        Requirement("distributed systems", "data structures, algorithms, and distributed systems")
    )

    assert resp.nice_to_have == (
        Requirement("Java / C++", "Java / C++"),
    )
