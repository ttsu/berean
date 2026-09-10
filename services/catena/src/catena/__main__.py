"""The `catena` command.

Every subcommand is implemented as of Task 7. The `NOT_IMPLEMENTED` mechanism
stays: a planned command exits 69 (EX_UNAVAILABLE) rather than 0, because a
provisioning step that reports success while doing nothing is the failure this
project can least afford, and the next phase will want it again.
"""

from __future__ import annotations

import sys

USAGE = """catena — Berean retrieval and citation service

Usage:
  catena acquire (--corpus <id> | --all) [--bless] [--verify-only]
                 [--show-diagnostic] [--from-file PATH]
  catena browse  [--port N] [--data-dir PATH] [--corpora-dir PATH]
  catena ingest  (--corpus <id> | --all) [--apply] [--budget N]
  catena serve   [--port N] [--probe]
  catena version

Phase 1 is under construction. See specs/001-phase-1-pca-baseline/PLAN.md.
"""

#: Planned commands, so a caller gets 69 rather than a silent success. Empty
#: while every documented command is implemented.
NOT_IMPLEMENTED: dict[str, str] = {}

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
    if command == "browse":
        from catena.browse import cli as browse_cli

        return browse_cli.main(args[1:])
    if command == "ingest":
        from catena.ingest import cli as ingest_cli

        return ingest_cli.main(args[1:])
    if command == "serve":
        from catena.serve import cli as serve_cli

        return serve_cli.main(args[1:])
    if command in NOT_IMPLEMENTED:
        print(f"catena: {NOT_IMPLEMENTED[command]}", file=sys.stderr)
        return EX_UNAVAILABLE

    print(f"catena: unknown command {command!r}\n\n{USAGE}", file=sys.stderr, end="")
    return EX_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
