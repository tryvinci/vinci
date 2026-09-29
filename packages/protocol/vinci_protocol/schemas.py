from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, cast


def schema_dir() -> Any:
    return files("vinci_protocol") / "jsonschema"


def load_schema(name: str) -> dict[str, Any]:
    text = (schema_dir() / f"{name}.schema.json").read_text(encoding="utf-8")
    return cast(dict[str, Any], json.loads(text))
