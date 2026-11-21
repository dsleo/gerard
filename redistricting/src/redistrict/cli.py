"""Command-line entry point. Grows one subcommand per pipeline stage."""

from __future__ import annotations

import argparse
import sys

from redistrict.config import ConfigError, load_config


def _cmd_check_config(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
    except (ConfigError, OSError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(f"OK  scenario={cfg.global_.scenario}  K={cfg.global_.total_seats}  "
          f"allocation={cfg.allocation.method}  hash={cfg.content_hash[:12]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="redistrict")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check-config", help="validate a config.yaml")
    p.add_argument("config", help="path to config.yaml")
    p.set_defaults(func=_cmd_check_config)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
