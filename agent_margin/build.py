from __future__ import annotations

from .config import Config


def run(config: Config) -> None:
    print(f"Config OK: {config.project_name} / {config.client_name}")
    print(f"Period: {config.period_start.isoformat()} .. {config.period_end.isoformat()}")
    print("Walker, cost engine, attribution, and rollup land in later tickets.")
