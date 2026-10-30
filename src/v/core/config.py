from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any


def project_root() -> Path:
    override = os.environ.get("V_HOME")
    if override:
        return Path(override).expanduser().resolve()

    return Path(__file__).resolve().parents[3]


def _deep_merge(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    result = dict(base)

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def load_settings() -> dict[str, Any]:
    config_dir = project_root() / "config"
    default_path = config_dir / "default.toml"
    local_path = config_dir / "local.toml"

    with default_path.open("rb") as file:
        settings = tomllib.load(file)

    if local_path.is_file():
        with local_path.open("rb") as file:
            local_settings = tomllib.load(file)
        settings = _deep_merge(settings, local_settings)

    return settings