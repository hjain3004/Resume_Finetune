import json
import pytest
from src import audit_schema

# Load the schema once for all tests
with open("config/tailored_schema.json") as f:
    TAILORED_SCHEMA = json.load(f)

def test_tailored_schema_valid():
    instance = {
        "base_variant": "backend",
        "reasoning": "Fits perfectly.",
        "skills": {
            "languages": ["Python", "Go"]
        },
        "projects": [
            {
                "project_id": "campus_marketplace",
                "bullets": [
                    {
                        "bullet_id": "cm_arch",
                        "phrasing_tier": "short",
                        "motivating_jd_quote": "RESTful services"
                    }
                ]
            }
        ],
        "experience": [
            {
                "experience_id": "amdocs_se",
                "bullets": [
                    {
                        "bullet_id": "amdocs_ci",
                        "phrasing_tier": "long",
                        "proposed_rewrite": "needs kubernetes mention"
                    }
                ]
            }
        ]
    }
    errors = audit_schema.validate(instance, TAILORED_SCHEMA)
    assert not errors

def test_tailored_schema_missing_required():
    instance = {
        "base_variant": "backend"
        # missing reasoning, skills, projects, experience
    }
    errors = audit_schema.validate(instance, TAILORED_SCHEMA)
    assert len(errors) == 4
    error_texts = " ".join(errors)
    assert "missing required field 'reasoning'" in error_texts
    assert "missing required field 'skills'" in error_texts
    assert "missing required field 'projects'" in error_texts
    assert "missing required field 'experience'" in error_texts

def test_tailored_schema_extraneous_prose_in_projects():
    instance = {
        "base_variant": "backend",
        "reasoning": "Fits.",
        "skills": {"l": ["a"]},
        "projects": [
            {
                "project_id": "campus_marketplace",
                "text": "This is extraneous text",
                "bullets": []
            }
        ],
        "experience": []
    }
    errors = audit_schema.validate(instance, TAILORED_SCHEMA)
    assert len(errors) == 1
    assert "unexpected additional property 'text'" in errors[0]

def test_tailored_schema_invalid_phrasing_tier():
    instance = {
        "base_variant": "backend",
        "reasoning": "Fits.",
        "skills": {"l": ["a"]},
        "projects": [
            {
                "project_id": "campus_marketplace",
                "bullets": [
                    {
                        "bullet_id": "cm_arch",
                        "phrasing_tier": "invalid_tier"
                    }
                ]
            }
        ],
        "experience": []
    }
    errors = audit_schema.validate(instance, TAILORED_SCHEMA)
    assert len(errors) == 1
    assert "not in enum" in errors[0]
    assert "invalid_tier" in errors[0]

def test_tailored_schema_empty_skill_string():
    instance = {
        "base_variant": "backend",
        "reasoning": "Fits.",
        "skills": {"l": [""]},
        "projects": [],
        "experience": []
    }
    errors = audit_schema.validate(instance, TAILORED_SCHEMA)
    assert len(errors) == 1
    assert "is below minLength 1" in errors[0]
