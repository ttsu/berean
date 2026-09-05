"""`catena browse` -- argument parsing.

Mirrors `catena acquire`'s shape: a parser, a `main` returning an exit code, and
the same two directory environment variables, so a developer who knows one knows
the other.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Sequence, TextIO

from catena.browse import server, staged

EX_OK = 0
EX_FAIL = 1
EX_USAGE = 64


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catena browse",
        description=(
            "Read acquired corpora in a browser: the staged text, its segmentation, "
            "and its metadata. Local, read-only, loopback only."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=server.DEFAULT_PORT,
        metavar="N",
        help=f"the loopback port to listen on (default {server.DEFAULT_PORT})",
    )
    parser.add_argument(
        "--data-dir",
        type=pathlib.Path,
        metavar="PATH",
        help=f"acquired data, overriding ${staged.DATA_DIR_ENV}",
    )
    parser.add_argument(
        "--corpora-dir",
        type=pathlib.Path,
        metavar="PATH",
        help=f"committed manifests and fingerprints, overriding ${staged.CORPORA_DIR_ENV}",
    )
    return parser


def main(argv: Sequence[str], *, stream: TextIO = sys.stderr) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_code:
        return EX_USAGE if exit_code.code else EX_OK

    data_dir = staged.data_dir(args.data_dir)
    corpora_dir = staged.corpora_dir(args.corpora_dir)

    if not (data_dir / "acquire").is_dir():
        print(
            f"catena browse: nothing acquired under {data_dir / 'acquire'}. "
            "Acquire a corpus first: `make bless CORPUS=<id>`.",
            file=stream,
        )
        return EX_FAIL

    try:
        server.serve(
            data_dir=data_dir,
            corpora_dir=corpora_dir,
            serve_local_only=staged.serve_local_only(),
            port=args.port,
            announce=lambda line: print(line, file=stream),
        )
    except OSError as error:
        print(
            f"catena browse: cannot listen on {server.HOST}:{args.port} — {error}",
            file=stream,
        )
        return EX_FAIL
    return EX_OK
