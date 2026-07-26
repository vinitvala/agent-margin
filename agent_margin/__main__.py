from __future__ import annotations

import argparse
import sys

from .config import Config, ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_margin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build ledger.json from session transcripts")
    build_parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")

    args = parser.parse_args(argv)

    if args.command == "build":
        try:
            config: Config = load_config(args.config)
        except ConfigError as e:
            print(f"Config error: {e}", file=sys.stderr)
            return 1

        from . import build

        build.run(config)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
