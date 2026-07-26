from __future__ import annotations

import argparse
import sys

from .config import Config, ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_margin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build ledger.json from session transcripts")
    build_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    build_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refetch Linear issues instead of using the local cache (use after creating tickets)",
    )

    reconcile_parser = subparsers.add_parser(
        "reconcile",
        help="Sum computed spend across ALL local Claude Code sessions, for comparison against the Anthropic Console",
    )
    reconcile_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")

    args = parser.parse_args(argv)

    try:
        config: Config = load_config(args.config)
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    if args.command == "build":
        from . import build

        build.run(config, refresh_linear=args.refresh)
        return 0

    if args.command == "reconcile":
        from . import reconcile

        reconcile.run(config)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
