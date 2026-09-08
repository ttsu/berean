"""`catena ingest` — argument parsing and the per-corpus run.

`make ingest CORPUS=<id>` runs one; `make ingest-all` runs every staged corpus.

It computes and prints its plan, and writes only under `--apply`. That inverts
its sibling — `catena acquire` writes unless told otherwise — and the asymmetry
is deliberate: acquisition writes into gitignored `/data` and a mistake costs
minutes of re-fetching, while ingestion updates and deletes rows that cascade
to embeddings, and a wrong run costs hours of embedding no cache can return.

The dry run is also the progress report, which is what keeps it from decaying
into a flag typed without reading. Its output on a resumed run is a live
measurement and the number moves every time.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Callable, Sequence, TextIO

from catena.acquire import fingerprints as fp
from catena.acquire import manifest as mf
from catena.acquire.record import AcquisitionError
from catena.ingest import IngestionError
from catena.ingest import apply as applying
from catena.ingest import plan as planning
from catena.ingest import source
from catena.ingest.embed import DEFAULT_BUDGET, Embedder

EX_OK = 0
EX_FAIL = 1
EX_USAGE = 64


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catena ingest",
        description=(
            "Make the database agree with the blessed staging directory. "
            "Prints its plan; writes only under --apply."
        ),
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--corpus", metavar="ID", help="the corpus ID, which is edition-specific")
    target.add_argument("--all", action="store_true", help="every staged corpus, smallest first")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="execute the plan. Without it nothing is written.",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_BUDGET,
        metavar="N",
        help=f"padded tokens per embedding batch (default {DEFAULT_BUDGET:,})",
    )
    return parser


def main(
    argv: Sequence[str],
    *,
    stream: TextIO = sys.stderr,
    data_dir: pathlib.Path | None = None,
    corpora_dir: pathlib.Path | None = None,
    open_store: Callable[[], applying.Store] | None = None,
    load_embedder: Callable[[], Embedder] | None = None,
) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_code:
        return EX_USAGE if exit_code.code else EX_OK

    data = source.data_dir(data_dir)
    corpora = source.corpora_dir(corpora_dir)

    if args.all:
        corpus_ids = source.discover(data_dir=data)
        if not corpus_ids:
            print(
                f"catena ingest: nothing staged under {data / 'acquire'}. Acquire a "
                "corpus first: `make provision-corpus`.",
                file=stream,
            )
            return EX_FAIL
    else:
        corpus_ids = [args.corpus]

    # The model is loaded once per invocation regardless of backlog size — about
    # 2.3 GB — so the marginal cost of resuming is fixed and small against a
    # multi-hour run. It is loaded before the first corpus because the
    # over-limit refusal needs its tokeniser.
    embedder = (load_embedder or _default_embedder)()
    store = (open_store or _default_store)()

    failed: list[str] = []
    for corpus_id in corpus_ids:
        try:
            run_one(
                corpus_id,
                store=store,
                embedder=embedder,
                data_dir=data,
                corpora_dir=corpora,
                execute=args.apply,
                budget=args.budget,
                stream=stream,
            )
        except (IngestionError, AcquisitionError) as error:
            print(f"catena ingest: {error}", file=stream)
            failed.append(corpus_id)
        except Exception as error:  # noqa: BLE001
            # A stack trace out of `make ingest-all` tells a deployer nothing
            # they can act on. Anything unforeseen is reported against the
            # corpus it happened to, and the run continues to the next one —
            # each corpus is a separate transaction and a separate decision.
            print(
                f"catena ingest: {corpus_id}: unexpected {type(error).__name__}: {error}",
                file=stream,
            )
            failed.append(corpus_id)

    if failed:
        print(f"\ncatena ingest: FAILED — {', '.join(failed)}", file=stream)
        return EX_FAIL
    return EX_OK


def run_one(
    corpus_id: str,
    *,
    store: applying.Store,
    embedder: Embedder,
    data_dir: pathlib.Path,
    corpora_dir: pathlib.Path,
    execute: bool,
    budget: int = DEFAULT_BUDGET,
    stream: TextIO = sys.stderr,
) -> None:
    """Plan one corpus, and execute it when told to.

    Raises rather than returning a status: every way this can fail is a refusal
    that carries a reason, and a boolean beside it would be a second answer to
    the same question.

    The plan is recomputed rather than carried. No plan file is written between
    the dry run and `--apply`: a plan artefact becomes a second answer to the
    question the command exists to answer, and it can disagree with the
    database while looking authoritative. Recomputing means the diff has one
    implementation that both paths call, and it is never stale.
    """
    staged = source.load(corpus_id, data_dir=data_dir)

    # Every run, not only on insert. Under a second across all 8.2 MB, and a
    # conditional check is one whose skipped path is untested.
    committed = fp.read(corpora_dir / corpus_id / mf.FINGERPRINTS_FILENAME)
    planning.check_fingerprints(corpus_id, staged.records, committed)
    planning.check_token_limit(corpus_id, staged.records, embedder)

    existing = store.existing_chunks(corpus_id, embedder.name)
    plan = planning.diff(
        corpus_id,
        staged.records,
        existing,
        normalisation_version=staged.normalisation_version,
    )

    for line in plan.lines():
        print(line, file=stream)

    if not execute:
        if not plan.converged:
            print("  (nothing written; re-run with --apply to execute)", file=stream)
        return

    applying.apply(
        staged,
        plan,
        store,
        embedder,
        budget=budget,
        report=lambda line: print(line, file=stream),
    )


def _default_store() -> applying.Store:
    from catena.ingest import postgres

    return postgres.connect()


def _default_embedder() -> Embedder:
    from catena.ingest import bge

    return bge.load()
