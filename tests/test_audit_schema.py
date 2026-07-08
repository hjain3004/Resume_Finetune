from src.audit_schema import validate

_OBJ_SCHEMA = {
    "type": "object",
    "required": ["id", "name"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer", "minimum": 0},
        "name": {"type": "string", "maxLength": 5},
        "tag": {"type": "string", "enum": ["a", "b"]},
        "items": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    },
}


def test_valid_object_has_no_errors():
    assert validate({"id": 1, "name": "abc"}, _OBJ_SCHEMA) == []


def test_missing_required_field_is_reported():
    errors = validate({"name": "abc"}, _OBJ_SCHEMA)
    assert any("id" in e and "required" in e for e in errors)


def test_wrong_type_is_reported():
    errors = validate({"id": "not an int", "name": "abc"}, _OBJ_SCHEMA)
    assert any("id" in e for e in errors)


def test_additional_property_rejected():
    errors = validate({"id": 1, "name": "abc", "extra": 1}, _OBJ_SCHEMA)
    assert any("extra" in e for e in errors)


def test_enum_violation_reported():
    errors = validate({"id": 1, "name": "abc", "tag": "z"}, _OBJ_SCHEMA)
    assert any("tag" in e for e in errors)


def test_max_length_violation_reported():
    errors = validate({"id": 1, "name": "too long"}, _OBJ_SCHEMA)
    assert any("name" in e for e in errors)


def test_minimum_violation_reported():
    errors = validate({"id": -1, "name": "abc"}, _OBJ_SCHEMA)
    assert any("id" in e for e in errors)


def test_array_min_items_and_item_type_checked():
    errors = validate({"id": 1, "name": "abc", "items": []}, _OBJ_SCHEMA)
    assert any("items" in e for e in errors)
    errors2 = validate({"id": 1, "name": "abc", "items": [1]}, _OBJ_SCHEMA)
    assert any("items" in e for e in errors2)
