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
