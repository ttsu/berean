"""The `catena` command.

`acquire` is implemented (PLAN Task 4). The rest are planned and exit 69
(EX_UNAVAILABLE) rather than 0, because a provisioning step that reports
success while acquiring nothing is the failure this project can least afford.
"""

from __future__ import annotations

import sys

USAGE = """catena — Berean retrieval and citation service

Usage:
  catena acquire (--corpus <id> | --all) [--bless] [--verify-only]
                 [--show-diagnostic] [--from-file PATH]
  catena ingest  --corpus <id> --source PATH                  (Task 5)
  catena serve                                                (Task 7)
  catena version

Phase 1 is under construction. See specs/001-phase-1-pca-baseline/PLAN.md.
"""

NOT_IMPLEMENTED = {
    "ingest": "ingestion is not implemented yet (PLAN Task 5)",
    "serve": "the gRPC server is not implemented yet (PLAN Task 7)",
}

EX_UNAVAILABLE = 69
EX_USAGE = 64


def main(argv: list[str] | None = None) -> int:
    from catena import __version__

    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(USAGE, file=sys.stderr, end="")
        return EX_USAGE

    command = args[0]
    if command == "version":
        print(__version__)
        return 0
    if command == "acquire":
        from catena.acquire import cli

        return cli.main(args[1:])
    if command in NOT_IMPLEMENTED:
        print(f"catena: {NOT_IMPLEMENTED[command]}", file=sys.stderr)
        return EX_UNAVAILABLE

    print(f"catena: unknown command {command!r}\n\n{USAGE}", file=sys.stderr, end="")
    return EX_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
