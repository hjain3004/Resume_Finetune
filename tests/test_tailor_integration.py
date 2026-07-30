import json
from unittest.mock import patch
from src.tailor.wrapper import run_tailor, run_critic

@patch('src.tailor.wrapper.subprocess.run')
def test_integration_tailor_success(mock_run):
    # Setup mocks
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
    
    # Run Tailor
    lint_errors, tailor_json, hydrated, change_list = run_tailor("test jd", master_profile, schema)
    
    assert not lint_errors
    assert tailor_json["base_variant"] == "backend"
    
    # Run Critic
    mock_run.return_value.stdout = '{"verdict": "pass"}'
    critic_res = run_critic(hydrated, "test jd", "banned", "taste")
    
    assert critic_res.get("verdict") == "pass"

@patch('src.tailor.wrapper.subprocess.run')
def test_integration_lint_failure(mock_run):
    mock_run.return_value.stdout = '''```json
{
  "base_variant": "backend",
  "reasoning": "Fits well.",
  "skills": {"languages": ["Python", "Go"]},
  "projects": [
      {"project_id": "swap1", "bullets": []},
      {"project_id": "swap2", "bullets": []}
  ],
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
    
    # Run Tailor
    lint_errors, tailor_json, hydrated, change_list = run_tailor("test jd", master_profile, schema)
    
    # Swapping 2 projects exceeds selection budget
    assert len(lint_errors) >= 1
    assert any("selection budget" in err for err in lint_errors)
