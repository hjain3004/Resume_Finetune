"""Minimal hand-rolled JSON-schema-subset validator (I5, docs/SELF_HEALING.md
§1). Not the `jsonschema` package — CLAUDE.md #4 forbids new dependencies,
and this project's schemas only ever need object/array/string/number/enum
checks. Schema files are the contract (SELF_HEALING §2 "I5 fires"); this
module only interprets them."""

from __future__ import annotations

_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
}


def validate(instance, schema: dict, *, path: str = "$") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type is not None:
        py_type = _TYPE_MAP[expected_type]
        if expected_type == "integer" and isinstance(instance, bool):
            errors.append(f"{path}: expected integer, got bool")
        elif expected_type == "number" and isinstance(instance, bool):
            errors.append(f"{path}: expected number, got bool")
        elif not isinstance(instance, py_type):
            errors.append(f"{path}: expected {expected_type}, got {type(instance).__name__}")
            return errors

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")

    if expected_type == "object" and isinstance(instance, dict):
        for field in schema.get("required", []):
            if field not in instance:
                errors.append(f"{path}: missing required field '{field}'")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in properties:
                    errors.append(f"{path}: unexpected additional property '{key}'")
        elif isinstance(schema.get("additionalProperties"), dict):
            additional_schema = schema["additionalProperties"]
            for key in instance:
                if key not in properties:
                    errors.extend(validate(instance[key], additional_schema, path=f"{path}.{key}"))
        for field, field_schema in properties.items():
            if field in instance:
                errors.extend(validate(instance[field], field_schema, path=f"{path}.{field}"))

    if expected_type == "array" and isinstance(instance, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(instance) < min_items:
            errors.append(f"{path}: expected at least {min_items} item(s), got {len(instance)}")
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, item in enumerate(instance):
                errors.extend(validate(item, item_schema, path=f"{path}[{i}]"))

    if expected_type in ("number", "integer") and isinstance(instance, (int, float)):
        minimum = schema.get("minimum")
        if minimum is not None and instance < minimum:
            errors.append(f"{path}: {instance} is below minimum {minimum}")
        maximum = schema.get("maximum")
        if maximum is not None and instance > maximum:
            errors.append(f"{path}: {instance} is above maximum {maximum}")

    if expected_type == "string" and isinstance(instance, str):
        min_length = schema.get("minLength")
        if min_length is not None and len(instance) < min_length:
            errors.append(f"{path}: length {len(instance)} is below minLength {min_length}")
        max_length = schema.get("maxLength")
        if max_length is not None and len(instance) > max_length:
            errors.append(f"{path}: length {len(instance)} exceeds maxLength {max_length}")

    return errors
