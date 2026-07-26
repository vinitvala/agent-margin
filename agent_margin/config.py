from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

REQUIRED_TOP_LEVEL = (
    "client_name",
    "project_name",
    "contract_value",
    "blended_cost_rate",
    "discount_given",
    "points_to_hours_factor",
    "linear",
    "period",
)
REQUIRED_LINEAR = ("api_key", "team_key")
REQUIRED_PERIOD = ("start", "end")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    client_name: str
    project_name: str
    contract_value: float
    blended_cost_rate: float
    discount_given: float
    points_to_hours_factor: float
    linear_api_key: str
    linear_team_key: str
    period_start: datetime
    period_end: datetime
    path: Path


def _require(d: dict, keys: tuple, where: str) -> None:
    missing = [k for k in keys if k not in d or d[k] in (None, "")]
    if missing:
        raise ConfigError(f"{where} missing required key(s): {', '.join(missing)}")


def _parse_dt(value: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise ConfigError(f"period.{field} is not a valid ISO 8601 timestamp: {value!r}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_config(path: str | Path = "config.yaml") -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"{path} not found. Copy config.example.yaml to {path} and fill in real values."
        )

    with path.open() as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")

    _require(raw, REQUIRED_TOP_LEVEL, str(path))
    _require(raw["linear"], REQUIRED_LINEAR, f"{path}:linear")
    _require(raw["period"], REQUIRED_PERIOD, f"{path}:period")

    return Config(
        client_name=str(raw["client_name"]),
        project_name=str(raw["project_name"]),
        contract_value=float(raw["contract_value"]),
        blended_cost_rate=float(raw["blended_cost_rate"]),
        discount_given=float(raw["discount_given"]),
        points_to_hours_factor=float(raw["points_to_hours_factor"]),
        linear_api_key=str(raw["linear"]["api_key"]),
        linear_team_key=str(raw["linear"]["team_key"]),
        period_start=_parse_dt(raw["period"]["start"], "start"),
        period_end=_parse_dt(raw["period"]["end"], "end"),
        path=path,
    )
