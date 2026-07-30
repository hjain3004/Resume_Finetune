import pytest
from src.tailor.lint import check_wording_budget, check_skills_do_not_claim

def test_wording_budget_under():
    base = "Python, Go, C++, Kubernetes"
    tailored = "Python, Go (Golang), C++, Docker"
    # base tokens: ["python", "go", "c++", "kubernetes"] (len 4)
    # tailored tokens: ["python", "go", "golang", "c++", "docker"] (len 5)
    # changes:
    # replace "kubernetes" with "golang", "docker" -> Wait, difflib matches Python, Go, C++.
    # after C++ it deletes kubernetes and inserts docker. And after Go it inserts golang.
    ratio = check_wording_budget(base, tailored)
    # distance = insert golang (1) + delete kubernetes (1) + insert docker (1) = 3
    # ratio = 3 / 4 = 0.75
    assert ratio == 0.5

def test_wording_budget_exact():
    base = "Python, Go"
    tailored = "Python, Go"
    assert check_wording_budget(base, tailored) == 0.0

def test_wording_budget_empty():
    assert check_wording_budget("", "Python") == 0.0

def test_skills_do_not_claim():
    tailored = {
        "languages": ["Python", "Go"],
        "tools": ["Docker", "Kubernetes (K8s)"]
    }
    dnc = ["Kubernetes"]
    violations = check_skills_do_not_claim(tailored, dnc)
    assert len(violations) == 1
    assert "Kubernetes" in violations[0]

def test_skills_do_not_claim_clean():
    tailored = {
        "languages": ["Python", "Go"],
        "tools": ["Docker"]
    }
    dnc = ["Kubernetes"]
    violations = check_skills_do_not_claim(tailored, dnc)
    assert len(violations) == 0

from src.tailor.lint import check_selection_budget, check_experience_immutable, check_flagship_ordering, check_blocked_claims

def test_selection_budget():
    base = ["A", "B", "C"]
    tailored_valid = ["A", "B", "D"] # Swap 1 out, 1 in
    assert not check_selection_budget(base, tailored_valid)
    
    tailored_invalid = ["A", "D", "E"] # Swap 2 out, 2 in
    assert len(check_selection_budget(base, tailored_invalid)) == 1

def test_experience_immutable():
    base = ["E1", "E2"]
    assert not check_experience_immutable(base, ["E1", "E2"])
    assert len(check_experience_immutable(base, ["E1"])) == 1
    assert len(check_experience_immutable(base, ["E2", "E1"])) == 1

def test_flagship_ordering():
    priorities = {"b1": 1, "b2": 2, "b3": 4}
    assert not check_flagship_ordering(["b1", "b2", "b3"], priorities)
    assert not check_flagship_ordering(["b1", "b3"], priorities)
    assert len(check_flagship_ordering(["b2", "b1"], priorities)) == 1
    assert len(check_flagship_ordering(["b3", "b2"], priorities)) == 1

def test_blocked_claims():
    claims = {"b1": "verified", "b2": "ownership_unresolved"}
    assert not check_blocked_claims(["b1"], claims)
    assert len(check_blocked_claims(["b1", "b2"], claims)) == 1

from src.tailor.lint import check_keyword_frequency, check_dual_placement

def test_keyword_frequency():
    text = "Python is great. We love Python. Python Python Python."
    # Python appears 5 times
    assert len(check_keyword_frequency(text, ["Python"])) == 1
    assert not check_keyword_frequency(text, ["Ruby"])

def test_dual_placement():
    skills = {"languages": ["Python"]}
    bullets = "Built with Python"
    assert not check_dual_placement(["Python"], skills, bullets)
    
    assert len(check_dual_placement(["Ruby"], skills, bullets)) == 1
    assert len(check_dual_placement(["Python"], {}, bullets)) == 1
    assert len(check_dual_placement(["Python"], skills, "")) == 1
