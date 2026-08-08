from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from . import __version__
from .bridge import BridgeRefusal, catalog, solve


def _add_plugin_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--load-module",
        action="append",
        default=[],
        metavar="PYTHON.MODULE",
        help="import an admitted installed module that self-registers UP engines",
    )
    parser.add_argument(
        "--register",
        action="append",
        default=[],
        metavar="NAME=PYTHON.MODULE:CLASS",
        help="register an admitted installed UP engine class",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mfw-pypi-planner")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog_parser = subparsers.add_parser(
        "catalog", help="emit installed engine and operation inventory"
    )
    _add_plugin_arguments(catalog_parser)

    solve_parser = subparsers.add_parser("solve", help="manufacture a bounded PDDL candidate plan")
    solve_parser.add_argument("--domain", type=Path, required=True)
    solve_parser.add_argument("--problem", type=Path, required=True)
    solve_parser.add_argument("--plan", type=Path, required=True)
    solve_parser.add_argument("--engine", default="auto")
    solve_parser.add_argument("--mode", choices=("auto", "classical", "temporal"), default="auto")
    solve_parser.add_argument("--timeout", type=float)
    _add_plugin_arguments(solve_parser)
    return parser


def _emit(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "catalog":
            _emit(catalog(registrations=args.register, load_modules=args.load_module))
            return 0
        if args.command == "solve":
            _emit(
                solve(
                    domain=args.domain,
                    problem_path=args.problem,
                    plan_path=args.plan,
                    engine=args.engine,
                    mode=args.mode,
                    timeout=args.timeout,
                    registrations=args.register,
                    load_modules=args.load_module,
                )
            )
            return 0
        raise AssertionError(f"unhandled command: {args.command}")
    except BridgeRefusal as exc:
        _emit(
            {
                "schema": "urn:mfw:pypi-planner-refusal:v1",
                "status": f"REFUSED:{exc.reason}",
                "detail": exc.detail,
            }
        )
        return 3
    except Exception as exc:
        _emit(
            {
                "schema": "urn:mfw:pypi-planner-failure:v1",
                "status": "tool_failed",
                "error_type": type(exc).__name__,
                "detail": str(exc),
            }
        )
        return 4


if __name__ == "__main__":
    sys.exit(main())
