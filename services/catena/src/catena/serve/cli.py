"""`catena serve` — the request path, and the probe compose runs against it."""

from __future__ import annotations

import sys

from catena.serve import ServeError, server

USAGE = """catena serve — run the retrieval and citation service

Usage:
  catena serve [--port N]
  catena serve --probe [--port N]

  --probe   Exit 0 when the service reports SERVING, 1 otherwise. This is what
            the compose healthcheck runs: the port is open well before the
            encoder has finished loading, and the gateway depends on catena.
"""

EX_USAGE = 64
EX_UNAVAILABLE = 69


def main(argv: list[str]) -> int:
    port: int | None = None
    probe = False

    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--probe":
            probe = True
        elif arg == "--port":
            if not args:
                print("catena serve: --port needs a value\n", file=sys.stderr)
                return EX_USAGE
            port = int(args.pop(0))
        elif arg in ("-h", "--help"):
            print(USAGE, file=sys.stderr, end="")
            return 0
        else:
            print(f"catena serve: unknown argument {arg!r}\n\n{USAGE}",
                  file=sys.stderr, end="")
            return EX_USAGE

    try:
        return server.probe(port) if probe else server.serve(port)
    except ServeError as error:
        # 69 (EX_UNAVAILABLE) rather than 1: the service could not be brought
        # up, which is what the rest of this CLI already uses that code to say.
        print(f"catena serve: {error}", file=sys.stderr)
        return EX_UNAVAILABLE
