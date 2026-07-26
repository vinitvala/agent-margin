from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

REQUIRED_TOP_LEVEL = (
    "client_name",
    "project_name",
    "contract_value",
    "blended_cost_rate",
    "discount_given",
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
    linear_api_key: str
    linear_team_key: str
    period_start: datetime
    period_end: datetime
    path: Path
    # Per-ticket human-supplied "what would this have taken without AI" hours.
    # There is deliberately NO factor-derived fallback: a story-point estimate
    # multiplied by a constant is not a measurement, and v0 shipped a headline
    # number built entirely out of one. Absent an entry here, every hours-based
    # figure downstream stays null rather than being invented.
    baseline_hours: dict[str, float] = field(default_factory=dict)
    # Whether a human has confirmed contract_value / discount_given /
    # blended_cost_rate are real figures for a real engagement, rather than
    # placeholders carried over from a mockup.
    inputs_verified: bool = False
    # Real monthly cost of a Claude seat. Under a subscription this is the only
    # figure actually billed, so token counts become an allocation driver rather
    # than a price: a ticket's share of total agent usage claims that share of
    # the seat. Leave None to skip allocation entirely.
    seat_cost_per_month: float | None = None
    # Seats to allocate. Must stay 1 unless the denominator covers every seat's
    # transcripts -- this tool reads one machine, so a higher count spreads N
    # seats of cost across one person's work. See build.py for the guard.
    n_seats: int = 1


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

    if "points_to_hours_factor" in raw:
        raise ConfigError(
            "points_to_hours_factor is no longer supported. Multiplying story "
            "points by a constant produces an estimate that looks measured and "
            "isn't. Supply real per-ticket figures under baseline_hours instead, "
            "or omit them and let hours-based output stay null."
        )

    baseline_raw = raw.get("baseline_hours") or {}
    if not isinstance(baseline_raw, dict):
        raise ConfigError(f"{path}:baseline_hours must be a mapping of ticket ID to hours")

    return Config(
        client_name=str(raw["client_name"]),
        project_name=str(raw["project_name"]),
        contract_value=float(raw["contract_value"]),
        blended_cost_rate=float(raw["blended_cost_rate"]),
        discount_given=float(raw["discount_given"]),
        linear_api_key=str(raw["linear"]["api_key"]),
        linear_team_key=str(raw["linear"]["team_key"]),
        period_start=_parse_dt(raw["period"]["start"], "start"),
        period_end=_parse_dt(raw["period"]["end"], "end"),
        path=path,
        baseline_hours={str(k).upper(): float(v) for k, v in baseline_raw.items()},
        inputs_verified=bool(raw.get("inputs_verified", False)),
        seat_cost_per_month=(
            float(raw["seat_cost_per_month"])
            if raw.get("seat_cost_per_month") is not None
            else None
        ),
        n_seats=int(raw.get("n_seats", 1)),
    )
