import pytest
from pydantic import ValidationError
from src.llm_tailor.schemas import RepairedBullet

def test_pydantic_strictness_guard():
    """
    Explicitly assert that passing `"3"` or `True` to an integer field, 
    or passing an undocumented extra field, fails validation against a representative model.
    This ensures `model_config = ConfigDict(strict=True, extra="forbid")` is never silently removed.
    
    Since we only have string lists in our current models (no ints), we will add a dummy 
    strict model here mirroring our config to test the exact rules required by the user,
    or we can test the `extra="forbid"` on our actual model.
    """
    
    # 1. Test extra="forbid" on our actual model
    with pytest.raises(ValidationError) as exc:
        RepairedBullet(id="am_b01", text="some text", extra_field="not allowed")
    assert "Extra inputs are not permitted" in str(exc.value)

    # 2. To test `strict=True` integer coercion (as requested in the prompt: `"3" -> int rejected`),
    # we create a representative model with the exact same ConfigDict we mandate for all models.
    from pydantic import BaseModel, ConfigDict
    class RepresentativeStrictModel(BaseModel):
        model_config = ConfigDict(strict=True, extra="forbid")
        count: int
        
    with pytest.raises(ValidationError) as exc1:
        RepresentativeStrictModel(count="3")
    assert "Input should be a valid integer" in str(exc1.value)
    
    with pytest.raises(ValidationError) as exc2:
        RepresentativeStrictModel(count=True)
    assert "Input should be a valid integer" in str(exc2.value)
