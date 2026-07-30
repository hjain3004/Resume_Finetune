"""Master-profile loader for Phase 3 tailoring (M8 item 2).

Parses and validates config/master_profile.yaml per
docs/superpowers/specs/2026-07-30-m8-profile-schema-reconciliation-design.md.
Pure: no SQLite, no network, no logging, and no I/O beyond reading the
requested YAML file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class ProfileValidationError(ValueError):
    pass


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys instead of last-wins."""


def _no_duplicates(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False):
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise ProfileValidationError(
                f"line {key_node.start_mark.line + 1}: duplicate key: {key!r}"
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates
)


def _read_yaml(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        return yaml.load(text, _StrictLoader)
    except ProfileValidationError:
        raise
    except yaml.YAMLError as exc:
        raise ProfileValidationError(f"{path}: malformed YAML: {exc}") from exc


_ASCII_EXEMPT_PATHS = ("ats.forbidden_chars", "ats.substitutions")


def _is_ascii_exempt(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _ASCII_EXEMPT_PATHS)


def _check_ascii(value: str, path: str) -> None:
    if _is_ascii_exempt(path):
        return
    if not value.isascii():
        offenders = sorted({ch for ch in value if not ch.isascii()})
        rendered = ", ".join(f"{ch!r} (U+{ord(ch):04X})" for ch in offenders)
        raise ProfileValidationError(f"{path}: non-ASCII character(s): {rendered}")


def _require_mapping(value: Any, path: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise ProfileValidationError(
            f"{path}: expected mapping, got {type(value).__name__}"
        )
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProfileValidationError(
            f"{path}: expected list, got {type(value).__name__}"
        )
    return value


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ProfileValidationError(
            f"{path}: expected string, got {type(value).__name__}"
        )
    stripped = value.strip()
    if not stripped:
        raise ProfileValidationError(f"{path}: expected nonempty string")
    _check_ascii(stripped, path)
    return stripped


def _string_list(value: Any, path: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    items = _require_list(value, path)
    if not allow_empty and not items:
        raise ProfileValidationError(f"{path}: expected nonempty string list")
    return tuple(
        _require_string(item, f"{path}.{index}") for index, item in enumerate(items)
    )


def _require_positive_int(value: Any, path: str) -> int:
    # bool must be rejected explicitly: isinstance(True, int) is True in Python,
    # so `priority: true` would otherwise validate as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfileValidationError(
            f"{path}: expected integer, got {type(value).__name__}"
        )
    if value < 1:
        raise ProfileValidationError(f"{path}: expected positive integer, got {value}")
    return value


def _required_field(raw: dict[Any, Any], field: str, path: str) -> str:
    field_path = f"{path}.{field}"
    if field not in raw:
        raise ProfileValidationError(f"{field_path}: missing required key")
    return _require_string(raw[field], field_path)


def load_profile(path: str | Path) -> "MasterProfile":
    raw = _read_yaml(Path(path))
    root = _require_mapping(raw, "master_profile.yaml")
    raise NotImplementedError("built up across Tasks 2-9")
