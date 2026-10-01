from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vinci_core.paths import default_home as default_home


@dataclass
class BudgetConfig:
    monthly_cap_usd: float | None = None
    require_approval_over: float | None = None


@dataclass
class VinciConfig:
    home: Path
    protocol_version: str = "0.1.0"
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    preference: str = "cheapest"
    demo: bool = False
    daemon_port: int = 4310
    gsheet_id: str = ""
    gsheet_tab: str = ""

    @property
    def cas_dir(self) -> Path:
        return self.home / "cas"

    @property
    def sqlite_path(self) -> Path:
        return self.home / "vinci.sqlite"

    @property
    def catalog_lock_path(self) -> Path:
        return self.home / "catalog.lock.json"


def load_config(home: Path | None = None) -> VinciConfig:
    root = home or default_home()
    root.mkdir(parents=True, exist_ok=True)
    (root / "cas").mkdir(exist_ok=True)
    path = root / "config.toml"
    data: dict[str, Any] = {}
    if path.exists():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    budget_raw = data.get("budget") or {}
    return VinciConfig(
        home=root,
        protocol_version=str(data.get("protocol_version", "0.1.0")),
        providers=dict(data.get("providers") or {}),
        secrets=dict(data.get("secrets") or {}),
        budget=BudgetConfig(
            monthly_cap_usd=budget_raw.get("monthly_cap_usd"),
            require_approval_over=budget_raw.get("require_approval_over"),
        ),
        preference=str(data.get("preference", "cheapest")),
        demo=bool(data.get("demo", False)),
        daemon_port=int(data.get("daemon_port", 4310)),
        gsheet_id=str(data.get("gsheet_id") or ""),
        gsheet_tab=str(data.get("gsheet_tab") or ""),
    )


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_config(config: VinciConfig) -> Path:
    config.home.mkdir(parents=True, exist_ok=True)
    (config.home / "cas").mkdir(exist_ok=True)
    lines = [
        f'protocol_version = "{config.protocol_version}"',
        f'preference = "{config.preference}"',
        f"demo = {_toml_value(config.demo)}",
        f"daemon_port = {config.daemon_port}",
        "",
    ]
    if config.gsheet_id:
        lines.append(f"gsheet_id = {_toml_value(config.gsheet_id)}")
    if config.gsheet_tab:
        lines.append(f"gsheet_tab = {_toml_value(config.gsheet_tab)}")
    lines.extend(["", "[budget]"])
    if config.budget.monthly_cap_usd is not None:
        lines.append(f"monthly_cap_usd = {config.budget.monthly_cap_usd}")
    if config.budget.require_approval_over is not None:
        lines.append(f"require_approval_over = {config.budget.require_approval_over}")
    lines.append("")
    for name, body in config.providers.items():
        lines.append(f"[providers.{name}]")
        for key, value in body.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    if config.secrets:
        lines.append("[secrets]")
        for key, value in config.secrets.items():
            lines.append(f'{key} = "{value}"')
        lines.append("")
    path = config.home / "config.toml"
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path
