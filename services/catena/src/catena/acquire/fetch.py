"""The fetch stage and its content-addressed cache.

PLAN says fetch "caches on `upstream_sha256`", which cannot be literally true:
a cache key cannot be the hash of something not yet fetched. What it is
reaching for is content addressing. Fetched bytes are stored at
`<root>/<corpus-id>/fetch/<sha256>`, and the manifest's `upstream_sha256` is
what *selects* a blob rather than what keys the fetch.

Three invocations, three network policies:

* `acquire --corpus <id>` hits the network only on a cache miss, so re-runs and
  downstream stage re-runs are cheap and acquisition works with egress blocked
  once the blob is present.
* `acquire --verify-only` **always** re-fetches. Noticing upstream drift is the
  entire job of `make corpus-verify`; a cache hit there would report success
  while evaluating nothing.
* `acquire --from-file PATH` never touches the network. The local copy is
  hashed into the same cache, so a dead upstream takes an identical path
  through every later stage.
"""

from __future__ import annotations

import hashlib
import http.client
import pathlib
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from catena.acquire.record import AcquisitionError, write_bytes

#: Generous: acquisition is a one-time human-supervised act, not a request path.
TIMEOUT_SECONDS = 60

#: Some publishers refuse a bare urllib default. Saying who we are is politer
#: than pretending to be a browser.
USER_AGENT = "berean-catena-acquire/1 (+https://github.com/ttsu/berean)"

Downloader = Callable[[str], bytes]

#: What a fetch is allowed to fail with before the archive fallback is tried.
#: `HTTPException` is named because it descends from neither of the others —
#: `IncompleteRead` on a truncated response is exactly the case where an archive
#: copy is worth reaching for, and it would otherwise escape as a traceback.
_TRANSPORT_ERRORS = (urllib.error.URLError, http.client.HTTPException, OSError)


@dataclass(frozen=True)
class FetchPlan:
    """Where a corpus's bytes come from.

    `archive_url` is the snapshot fallback for when upstream moves. Its bytes
    will not hash to the same `upstream_sha256` — an archive wraps what it
    stores — so falling back is a reported event, and the fingerprints rather
    than the upstream digest are what say the text is the blessed text.

    `follow` is for a corpus published across several pages rather than as one
    document, which the 1646 confession is: a chapter to a page, and no complete
    single-document source of it exists. The adapter is handed the index's bytes
    and returns the page URLs in reading order; fetch downloads them and hands
    every later stage one blob, so caching, content addressing, `--from-file`
    and drift detection are unchanged.

    The seam falls here rather than inside an adapter's `extract` for the reason
    the stages are separate at all: fetch is the only stage that touches the
    network, and an adapter that downloaded its own pages would put network
    access behind a function the cache cannot see. `follow` reads bytes and
    returns strings; it performs no I/O.

    Discovering the pages also keeps them out of this repository. The 1646
    confession's URLs carry its chapter titles, and a list of 33 of them
    committed to an adapter is the document's table of contents (ADR-0014).
    """

    source_url: str
    archive_url: str
    #: Index bytes to the page URLs to fetch, in order. `None` for a corpus that
    #: is one document, which is every other corpus.
    follow: Callable[[bytes], "tuple[str, ...]"] | None = None


@dataclass(frozen=True)
class Fetched:
    digest: str
    raw: bytes
    #: Where the bytes came from this run: "cache", a URL, or a local path.
    origin: str

    @property
    def from_cache(self) -> bool:
        return self.origin == "cache"


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def cache_dir(root: pathlib.Path, corpus_id: str) -> pathlib.Path:
    return root / corpus_id / "fetch"


def store(root: pathlib.Path, corpus_id: str, raw: bytes) -> str:
    """Put bytes in the cache under their own digest, and return it."""
    digest = hashlib.sha256(raw).hexdigest()
    blob = cache_dir(root, corpus_id) / digest
    if not blob.exists():
        write_bytes(blob, raw)
    return digest


def fetch(
    root: pathlib.Path,
    corpus_id: str,
    plan: FetchPlan,
    *,
    expected_digest: str | None = None,
    refetch: bool = False,
    from_file: pathlib.Path | None = None,
    downloader: Downloader = download,
    sleep: Callable[[float], None] = time.sleep,
) -> Fetched:
    if from_file is not None:
        try:
            raw = from_file.read_bytes()
        except OSError as error:
            raise AcquisitionError(f"--from-file {from_file}: {error}") from error
        return Fetched(store(root, corpus_id, raw), raw, str(from_file))

    if not refetch and expected_digest:
        blob = cache_dir(root, corpus_id) / expected_digest
        if blob.exists():
            raw = blob.read_bytes()
            # Re-hash rather than trust the filename. The cache is a plain
            # directory in a bind mount that `--from-file` also writes into, so
            # a blob can be edited or truncated between runs — and the report
            # line that would then be wrong is the one asserting the upstream
            # bytes are unchanged.
            actual = hashlib.sha256(raw).hexdigest()
            if actual != expected_digest:
                raise AcquisitionError(
                    f"{corpus_id}: the cached blob at {blob} hashes to {actual}, not to the "
                    f"{expected_digest} its name claims. Delete it and re-acquire."
                )
            return Fetched(expected_digest, raw, "cache")

    raw, origin = _download_with_fallback(plan, downloader)
    if plan.follow is not None:
        raw, origin = _download_pages(plan, raw, origin, downloader, sleep)
    return Fetched(store(root, corpus_id, raw), raw, origin)


#: Between concatenated pages. A newline rather than nothing, so a tag closing
#: at the end of one page cannot fuse with one opening at the start of the next.
PAGE_SEPARATOR = b"\n"

#: Waited before each followed page. A page set is one publisher hit dozens of
#: times in a row, and 33 back-to-back requests earned an HTTP 429 from the
#: small denominational server this was first written against. Acquisition is a
#: one-time, human-supervised act; a minute spread over a corpus costs nothing
#: and being throttled mid-set costs the whole acquisition.
PAGE_DELAY_SECONDS = 1.0


def _download_pages(
    plan: FetchPlan,
    index: bytes,
    origin: str,
    downloader: Downloader,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bytes, str]:
    """Fetch every page the adapter finds in the index, in reading order.

    The index itself is dropped: it is a table of contents, which is an index
    rather than text, and the same rule that drops one inside a page.
    """
    assert plan.follow is not None
    pages = plan.follow(index)
    if not pages:
        raise AcquisitionError(
            f"fetch {plan.source_url}: the index named no pages. The source's shape "
            "changed, and acquiring it would produce an empty corpus rather than an error."
        )
    parts: list[bytes] = []
    for url in pages:
        sleep(PAGE_DELAY_SECONDS)
        try:
            parts.append(downloader(url))
        except _TRANSPORT_ERRORS as error:
            # No archive fallback per page: a set of archived snapshots is a
            # second source to keep current, and a partial corpus that acquired
            # cleanly is worse than one that refused to.
            raise AcquisitionError(
                f"fetch {url}: {error}\n"
                f"  This is one of {len(pages)} pages listed by {plan.source_url}, and a "
                "corpus missing a page would stage and bless as though complete.\n"
                "  If this is a 429, the publisher is throttling: raise PAGE_DELAY_SECONDS "
                "rather than retrying into it.\n"
                "  Acquire the pages by hand and pass the concatenation with --from-file."
            ) from error
    return PAGE_SEPARATOR.join(parts), f"{origin} (+{len(pages)} pages)"


def _download_with_fallback(plan: FetchPlan, downloader: Downloader) -> tuple[bytes, str]:
    try:
        return downloader(plan.source_url), plan.source_url
    except _TRANSPORT_ERRORS as source_error:
        if not plan.archive_url:
            raise AcquisitionError(f"fetch {plan.source_url}: {source_error}") from source_error
        try:
            return downloader(plan.archive_url), plan.archive_url
        except _TRANSPORT_ERRORS as archive_error:
            raise AcquisitionError(
                f"fetch failed from both sources.\n"
                f"  source  {plan.source_url}: {source_error}\n"
                f"  archive {plan.archive_url}: {archive_error}\n"
                "  Acquire the bytes by hand and pass them with --from-file."
            ) from archive_error
