from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from vinci_protocol.models import WorkflowSpec

REQUIRED_MANIFEST = ("id", "version", "tags", "inputs", "outputs", "capabilities")


def _split_ref(ref: str) -> tuple[str, str | None]:
    if ref.startswith("@") and ref.count("@") >= 2:
        name, version = ref.rsplit("@", 1)
        return name, version
    if not ref.startswith("@") and "@" in ref:
        name, version = ref.rsplit("@", 1)
        return name, version
    return ref, None


@dataclass
class Skill:
    id: str
    version: str
    path: Path
    manifest: dict[str, Any]
    workflow: WorkflowSpec
    skill_md: str

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"

    @property
    def tags(self) -> list[str]:
        tags = self.manifest.get("tags") or []
        return [str(t) for t in tags]


def default_bundled_skills_root() -> Path:
    env = os.environ.get("VINCI_SKILLS_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "skills"


def _load_one(path: Path) -> Skill:
    manifest_path = path / "vinci.yaml"
    workflow_path = path / "workflow.yaml"
    skill_md_path = path / "SKILL.md"
    if not manifest_path.is_file() or not workflow_path.is_file():
        raise ValueError(f"{path} is missing vinci.yaml or workflow.yaml")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(manifest, dict):
        raise ValueError(f"{manifest_path} must be a mapping")
    missing = [key for key in REQUIRED_MANIFEST if key not in manifest]
    if missing:
        raise ValueError(f"{path.name} missing {missing}")
    raw_workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
    workflow = WorkflowSpec.model_validate(raw_workflow)
    skill_md = skill_md_path.read_text(encoding="utf-8") if skill_md_path.is_file() else ""
    return Skill(
        id=str(manifest["id"]),
        version=str(manifest["version"]),
        path=path,
        manifest=manifest,
        workflow=workflow,
        skill_md=skill_md,
    )


def validate_skill_dir(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        skill = _load_one(path)
    except Exception as exc:  # noqa: BLE001 — validation collects errors
        return [str(exc)]
    perms = skill.manifest.get("permissions") or []
    if not isinstance(perms, list):
        errors.append("permissions must be a list")
    secrets = skill.manifest.get("secret_names") or []
    for name in secrets:
        if not str(name).isupper() or any(c in str(name) for c in "=/"):
            errors.append(f"secret name must be an identifier: {name}")
    return errors


def skill_dirname(skill_id: str) -> str:
    return skill_id.lstrip("@").replace("/", "-")


def install_skill_dir(src: Path, dest_root: Path) -> Skill:
    src = src.expanduser().resolve()
    errors = validate_skill_dir(src)
    if errors:
        raise ValueError("; ".join(errors))
    skill = _load_one(src)
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / skill_dirname(skill.id)
    if dest.resolve() != src.resolve():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", ".git"))
    return _load_one(dest)


class SkillLoader:
    def __init__(self, roots: list[Path] | None = None) -> None:
        bundled = default_bundled_skills_root()
        self.roots = roots or [bundled]

    def list_skills(self) -> list[Skill]:
        found: dict[str, Skill] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                if not (child / "vinci.yaml").is_file():
                    continue
                skill = _load_one(child)
                found[skill.id] = skill
        return list(found.values())

    def get(self, ref: str) -> Skill:
        skill_id, version = _split_ref(ref)
        for skill in self.list_skills():
            if skill.id == skill_id or skill.ref == ref or skill.path.name == skill_id:
                if version and skill.version != version:
                    continue
                return skill
        raise KeyError(ref)

    def search(self, query: str) -> list[Skill]:
        needle = query.lower().strip()
        if not needle:
            return self.list_skills()
        hits: list[Skill] = []
        for skill in self.list_skills():
            blob = " ".join(
                [
                    skill.id,
                    skill.skill_md,
                    " ".join(skill.tags),
                    json.dumps(skill.manifest, default=str),
                ]
            ).lower()
            if needle in blob or all(part in blob for part in needle.split()):
                hits.append(skill)
        return hits

    def inspect(self, ref: str) -> dict[str, Any]:
        skill = self.get(ref)
        return {
            "id": skill.id,
            "version": skill.version,
            "tags": skill.tags,
            "permissions": skill.manifest.get("permissions") or [],
            "secret_names": skill.manifest.get("secret_names") or [],
            "est_cost": skill.manifest.get("est_cost") or skill.manifest.get("estimated_cost"),
            "capabilities": skill.manifest.get("capabilities"),
            "safety_tags": skill.manifest.get("safety_tags") or [],
            "skill_md": skill.skill_md,
            "inputs": skill.manifest.get("inputs") or {},
            "workflow": skill.workflow.model_dump(mode="json"),
        }


_TEMPLATE = re.compile(r"\{\{\s*([^}]+)\s*\}\}")


def interpolate(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: interpolate(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(item, context) for item in value]
    if not isinstance(value, str):
        return value

    def lookup(path: str) -> Any:
        current: Any = context
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit():
                current = current[int(part)]
            else:
                if path.startswith("inputs."):
                    return ""
                raise KeyError(path)
        return current

    match = _TEMPLATE.fullmatch(value.strip())
    if match:
        return lookup(match.group(1).strip())

    def repl(match: re.Match[str]) -> str:
        return str(lookup(match.group(1).strip()))

    return _TEMPLATE.sub(repl, value)
