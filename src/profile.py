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


def load_profile(path: str | Path) -> "MasterProfile":
    raw = _read_yaml(Path(path))
    root = _require_mapping(raw, "master_profile.yaml")
    raise NotImplementedError("built up across Tasks 2-9")
