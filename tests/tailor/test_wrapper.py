from src.tailor.wrapper import hydrate_tailor_draft, derive_change_list

def test_hydrate_tailor_draft():
    master_profile = {
        "projects": [
            {
                "id": "campus_marketplace",
                "name": "Campus Marketplace",
                "bullets": [
                    {
                        "id": "cm_arch",
                        "phrasings": {
                            "short": "Architected Go microservices.",
                            "long": "Architected Go microservices with high availability."
                        }
                    }
                ]
            }
        ]
    }
    
    tailor_json = {
        "skills": {"languages": ["Python", "Go"]},
        "projects": [
            {
                "project_id": "campus_marketplace",
                "bullets": [
                    {
                        "bullet_id": "cm_arch",
                        "phrasing_tier": "short"
                    }
                ]
            }
        ],
        "experience": []
    }
    
    hydrated = hydrate_tailor_draft(tailor_json, master_profile)
    assert "SKILLS" in hydrated
    assert "languages: Python, Go" in hydrated
    assert "Campus Marketplace" in hydrated
    assert "- Architected Go microservices." in hydrated
    assert "high availability" not in hydrated

def test_derive_change_list():
    master_profile = {
        "base_variants": {
            "backend": {
                "projects": ["proj_1"]
            }
        }
    }
    
    tailor_json = {
        "projects": [
            {
                "project_id": "proj_1",
                "bullets": [{"bullet_id": "b1", "phrasing_tier": "short", "motivating_jd_quote": "We need Go"}]
            },
            {
                "project_id": "proj_2",
                "bullets": []
            }
        ]
    }
    
    changes = derive_change_list("backend", tailor_json, master_profile)
    assert len(changes) >= 1
    # Check that it noted the project swap
    proj_change = next(c for c in changes if c["location"] == "projects")
    assert "proj_1" in proj_change["before"]
    assert "proj_2" in proj_change["after"]

from unittest.mock import patch
from src.tailor.wrapper import run_tailor, run_critic

@patch('src.tailor.wrapper.subprocess.run')
def test_run_tailor_valid(mock_run):
    mock_run.return_value.stdout = '''```json
{
  "base_variant": "backend",
  "reasoning": "Fits well.",
  "skills": {"languages": ["Python", "Go"]},
  "projects": [],
  "experience": []
}
```'''
    
    schema = {
      "type": "object",
      "required": ["base_variant", "reasoning", "skills", "projects", "experience"],
      "properties": {
          "base_variant": {"type": "string"},
          "reasoning": {"type": "string"},
          "skills": {"type": "object"},
          "projects": {"type": "array"},
          "experience": {"type": "array"}
      }
    }
    
    master_profile = {
        "base_variants": {"backend": {"projects": [], "bullet_order": []}},
        "projects": [],
        "experience": []
    }
    
    errors, tailor_json, hydrated, change_list = run_tailor("test jd", master_profile, schema)
    assert not errors
    assert tailor_json["base_variant"] == "backend"

@patch('src.tailor.wrapper.subprocess.run')
def test_run_critic(mock_run):
    mock_run.return_value.stdout = '{"verdict": "pass"}'
    res = run_critic("hydrated text", "jd text", "banned", "taste")
    assert res.get("verdict") == "pass"
