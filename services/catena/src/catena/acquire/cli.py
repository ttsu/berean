"""`catena acquire` — argument parsing and the per-corpus run.

`make provision-corpus` runs `--all`; `make corpus-verify` runs
`--all --verify-only`, which is how upstream drift gets noticed without
disturbing staged records an ingestion may be reading.
"""

from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import sys
from typing import Sequence, TextIO

from catena.acquire import corpora
from catena.acquire import fetch
from catena.acquire import fingerprints as fp
from catena.acquire import manifest as mf
from catena.acquire import pipeline
from catena.acquire.record import AcquisitionError

#: Both are bind mounts in compose. Acquired text lands in `/data` and never
#: leaves it; `/corpora` is writable only because the first acquisition of a
#: corpus is the one that blesses.
DATA_DIR_ENV = "CATENA_DATA_DIR"
CORPORA_DIR_ENV = "CATENA_CORPORA_DIR"

EX_OK = 0
EX_FAIL = 1
EX_USAGE = 64


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catena acquire",
        description="Acquire a corpus: fetch, extract, segment, normalise, verify, stage.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--corpus", metavar="ID", help="the corpus ID, which is edition-specific")
    target.add_argument("--all", action="store_true", help="every registered corpus")
    parser.add_argument(
        "--bless",
        action="store_true",
        help="record a human's edition verification and write the manifest and fingerprints",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="re-fetch and diff against the committed fingerprints; stage nothing",
    )
    parser.add_argument(
        "--show-diagnostic",
        action="store_true",
        help="print the edition diagnostic's text and hash for reading by hand; stage nothing",
    )
    parser.add_argument(
        "--from-file",
        metavar="PATH",
        type=pathlib.Path,
        help="use a local copy instead of fetching, for when upstream is dead or moved",
    )
    return parser


def main(argv: Sequence[str], *, stream: TextIO = sys.stderr) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_code:
        return EX_USAGE if exit_code.code else EX_OK

    if args.bless and args.verify_only:
        return _usage(
            parser, "--bless writes the fingerprints and --verify-only writes nothing", stream
        )
    if args.bless and args.all:
        return _usage(
            parser,
            "--bless takes one --corpus. Blessing is a human reading one edition "
            "diagnostic and approving it; a flag that blessed seven corpora at once "
            "would record seven verifications nobody made",
            stream,
        )
    if args.from_file and args.all:
        return _usage(parser, "--from-file names one file, so it takes one --corpus", stream)
    if args.show_diagnostic and (args.bless or args.verify_only):
        return _usage(
            parser,
            "--show-diagnostic only reads; it does not combine with --bless or --verify-only",
            stream,
        )
    if args.show_diagnostic and args.all:
        return _usage(
            parser,
            "--show-diagnostic prints one edition diagnostic, so it takes one --corpus",
            stream,
        )

    data_dir = pathlib.Path(os.environ.get(DATA_DIR_ENV, "/data"))
    corpora_dir = pathlib.Path(os.environ.get(CORPORA_DIR_ENV, "/corpora"))

    try:
        adapters = corpora.load_all() if args.all else [corpora.load(args.corpus)]
    except (KeyError, ValueError) as error:
        print(f"catena acquire: {error}", file=stream)
        return EX_USAGE

    failed = []
    for adapter in adapters:
        try:
            ok = run_one(
                adapter,
                data_dir=data_dir,
                corpora_dir=corpora_dir,
                bless=args.bless,
                verify_only=args.verify_only,
                show_diagnostic=args.show_diagnostic,
                from_file=args.from_file,
                stream=stream,
            )
        except AcquisitionError as error:
            print(f"catena acquire: {adapter.corpus_id}: {error}", file=stream)
            ok = False
        except Exception as error:  # noqa: BLE001
            # A stack trace out of `make provision-corpus` tells a deployer
            # nothing they can act on. Anything unforeseen is reported against
            # the corpus it happened to, and the run continues to the next one.
            print(
                f"catena acquire: {adapter.corpus_id}: unexpected "
                f"{type(error).__name__}: {error}",
                file=stream,
            )
            ok = False
        if not ok:
            failed.append(adapter.corpus_id)

    if failed:
        print(f"\ncatena acquire: FAILED — {', '.join(failed)}", file=stream)
        return EX_FAIL
    return EX_OK


def run_one(
    adapter: pipeline.Adapter,
    *,
    data_dir: pathlib.Path,
    corpora_dir: pathlib.Path,
    bless: bool,
    verify_only: bool,
    from_file: pathlib.Path | None,
    show_diagnostic: bool = False,
    stream: TextIO = sys.stderr,
    today: datetime.date | None = None,
    prompt=input,
    interactive: bool | None = None,
    downloader=fetch.download,
) -> bool:
    committed_dir = corpora_dir / adapter.corpus_id
    manifest = mf.read(committed_dir / mf.FILENAME)
    committed = fp.read(committed_dir / mf.FINGERPRINTS_FILENAME)

    if manifest is None and verify_only:
        raise AcquisitionError(
            "no committed manifest. `--verify-only` compares an acquisition against a "
            "blessed record and this corpus has none, so there is nothing to compare. "
            "Drift detection over a corpus nobody has verified is a check with nothing "
            f"to evaluate — bless it first: `make bless CORPUS={adapter.corpus_id}`."
        )

    acquired = pipeline.acquire(
        adapter,
        data_dir=data_dir,
        manifest=manifest,
        from_file=from_file,
        # Noticing upstream drift is the entire job of `make corpus-verify`; a
        # cache hit here would report success while evaluating nothing.
        refetch=verify_only,
        downloader=downloader,
    )

    if show_diagnostic:
        # Reading the diagnostic must work before a corpus has ever been
        # blessed, because the first bless is when someone most needs to read
        # it. Nothing is staged and nothing is verified.
        pipeline.show_diagnostic(adapter, acquired, stream=stream)
        return True

    if bless:
        day = (today or datetime.date.today()).isoformat()
        pipeline.bless(
            adapter,
            acquired,
            corpora_dir=corpora_dir,
            retrieved=day,
            verified=day,
            existing=committed,
            stream=stream,
            prompt=prompt,
            interactive=interactive,
        )
        pipeline.write_stage(acquired, data_dir=data_dir)
        return True

    if manifest is None:
        # Never blessed. Stage it anyway: there is no committed record to drift
        # from, so verification has nothing to do, and refusing here made the
        # browser's first-bless flow unreachable by construction — a corpus
        # reaches `make browse` by being staged, staging required a successful
        # verify, and verifying required the blessing the browser exists to
        # perform. Text still lands only in gitignored local storage, nothing
        # renders unverified, and no bless happens without a human typing a name.
        out = pipeline.write_stage(acquired, data_dir=data_dir)
        print(f"{adapter.corpus_id}: UNVERIFIED — never blessed", file=stream)
        print(f"  staged {len(acquired.records)} records in {out}", file=stream)
        print(
            "  nothing was checked: there is no committed record to check against. "
            "Read it and bless it — `make browse`, or "
            f"`make bless CORPUS={adapter.corpus_id}`.",
            file=stream,
        )
        return True

    if committed is None:
        raise AcquisitionError(
            f"{committed_dir / mf.FINGERPRINTS_FILENAME} is missing while the manifest "
            "is present. Half a blessing verifies nothing; re-bless the corpus."
        )

    report = pipeline.verify(adapter, acquired, manifest, committed)
    for line in report.lines():
        print(line, file=stream)
    if not report.ok:
        return False

    if not verify_only:
        out = pipeline.write_stage(acquired, data_dir=data_dir)
        print(f"  staged {len(acquired.records)} records in {out}", file=stream)
    return True


def _usage(parser: argparse.ArgumentParser, message: str, stream: TextIO) -> int:
    print(f"{parser.prog}: {message}", file=stream)
    return EX_USAGE
