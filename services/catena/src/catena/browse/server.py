"""The HTTP surface: two routes, no state, loopback only.

This is not the Phase 4 web UI and must not grow into it. It is a read-only
developer affordance over gitignored local files, on the same footing as
`make show-diagnostic` -- which is what ADR-0021 chose over committing text so a
human could check an edition. It touches no database, no model, no proto, and
does not cross the Go/Python seam.

**Loopback only, never 0.0.0.0.** The pages carry corpus text. `local-only`
corpora are servable solely under a deployer opt-in and `refused` corpora never
are (ADR-0017), and a bind address is the difference between honouring that and
publishing to the LAN.

Corpora are read per request rather than cached. Re-running acquisition and
hitting reload is the loop this exists to serve, and a cache would show the run
before last.
"""

from __future__ import annotations

import http.server
import pathlib
import secrets
import urllib.parse
from typing import Callable

from catena.acquire import fetch as fetching
from catena.acquire.record import AcquisitionError
from catena.browse import render, staged, verify

#: 3000, 5432, 9000, 9001 and 11434 are taken by the compose stack.
DEFAULT_PORT = 8730
HOST = "127.0.0.1"


def route(
    path: str,
    query: dict[str, list[str]],
    *,
    data_dir: pathlib.Path,
    corpora_dir: pathlib.Path,
    serve_local_only: bool,
    token: str = "",
    verify_error: str | None = None,
) -> tuple[int, str]:
    """A request path to a status and a page.

    Separated from the handler so the routing is testable without binding a
    socket -- the Python suite is hermetic and touches no network.
    """
    if path == "/":
        corpora = []
        for corpus_id in staged.discover(data_dir=data_dir):
            try:
                corpora.append(staged.load(corpus_id, data_dir=data_dir, corpora_dir=corpora_dir))
            except (AcquisitionError, OSError, ValueError, KeyError):
                # One unreadable corpus must not take down the index; the
                # corpus's own page reports what is wrong with it.
                continue
        return 200, render.index_page(corpora)

    if path.startswith("/c/"):
        corpus_id = urllib.parse.unquote(path[len("/c/") :])
        if not corpus_id or "/" in corpus_id:
            return 404, render.error_page(404, f"No such corpus: {corpus_id!r}")
        try:
            corpus = staged.load(corpus_id, data_dir=data_dir, corpora_dir=corpora_dir)
        except AcquisitionError as error:
            return 404, render.error_page(404, str(error))
        except (OSError, ValueError, KeyError) as error:
            return 500, render.error_page(500, f"{corpus_id}: staged output unreadable — {error}")

        try:
            page = int(query.get("page", ["0"])[0])
        except ValueError:
            page = 0

        withheld = staged.text_withheld_reason(corpus.work, serve_local_only=serve_local_only)
        # No verification offer when the text is withheld: approving an edition
        # you are not permitted to read is not a verification of anything.
        offer = None
        if withheld is None and corpus.fingerprint_status == staged.UNBLESSED:
            try:
                offer = verify.offer(corpus)
            except verify.NotVerifiable:
                offer = None
        return 200, render.corpus_page(
            corpus,
            page=page,
            withheld=withheld,
            offer=offer,
            token=token,
            verify_error=verify_error,
        )

    return 404, render.error_page(404, f"No such page: {path}")


def bless_route(
    path: str,
    form: dict[str, list[str]],
    *,
    data_dir: pathlib.Path,
    corpora_dir: pathlib.Path,
    serve_local_only: bool,
    token: str,
    downloader: fetching.Downloader = fetching.download,
) -> tuple[int, str, str | None]:
    """Handle a bless submission. Returns (status, body, redirect_to).

    Separated from the handler for the same reason `route` is: the whole decision
    -- token, licence gate, verification -- is exercisable without a socket.
    """
    corpus_id = urllib.parse.unquote(path[len("/bless/") :])
    if not corpus_id or "/" in corpus_id:
        return 404, render.error_page(404, f"No such corpus: {corpus_id!r}"), None

    submitted = (form.get("token") or [""])[0]
    if not token or not secrets.compare_digest(submitted, token):
        # Deliberately terse. A localhost write endpoint is reachable from any
        # page the browser has open, and a detailed rejection is a hint.
        return 403, render.error_page(
            403,
            "This request did not come from the browser page. Blessing is a write, so it "
            "carries a token issued when the server started; reload the corpus page and "
            "submit the form there.",
        ), None

    try:
        corpus = staged.load(corpus_id, data_dir=data_dir, corpora_dir=corpora_dir)
    except AcquisitionError as error:
        return 404, render.error_page(404, str(error)), None

    withheld = staged.text_withheld_reason(corpus.work, serve_local_only=serve_local_only)
    if withheld is not None:
        return 403, render.error_page(403, withheld), None

    try:
        verify.apply(
            corpus_id,
            name=(form.get("name") or [""])[0],
            read_hash=(form.get("read_sha256") or [""])[0],
            data_dir=data_dir,
            corpora_dir=corpora_dir,
            downloader=downloader,
        )
    except verify.NotVerifiable as error:
        # Re-render the corpus page carrying the complaint, so the passage is
        # still in front of the person who has to decide what to do about it.
        status, body = route(
            f"/c/{corpus_id}",
            {},
            data_dir=data_dir,
            corpora_dir=corpora_dir,
            serve_local_only=serve_local_only,
            token=token,
            verify_error=str(error),
        )
        return (409 if status == 200 else status), body, None

    # Redirect so a reload does not re-submit, and so the page that comes back is
    # read from the manifest that was just written rather than from this handler.
    return 303, "", f"/c/{urllib.parse.quote(corpus_id)}"


#: Cap on a bless submission. The form carries a name, a token and a hash; a body
#: larger than this is not that form.
MAX_FORM_BYTES = 8 * 1024


def origin_ok(origin: str | None, site: str | None, *, host: str, port: int) -> bool:
    """Whether a write may be accepted from this request's origin.

    Defence in depth behind the token. A browser sends `Origin` on every POST, so
    a mismatch is a cross-site write attempt; `Sec-Fetch-Site` covers the browsers
    that send it. A request with neither header did not come from a form on this
    page, and the only reason to allow it would be convenience for a client that
    should be using the CLI.
    """
    if origin is not None:
        return origin in {f"http://{host}:{port}", f"http://localhost:{port}"}
    return site == "same-origin"


def make_handler(
    *,
    data_dir: pathlib.Path,
    corpora_dir: pathlib.Path,
    serve_local_only: bool,
    token: str = "",
    host: str = HOST,
    port: int = DEFAULT_PORT,
) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "catena-browse"
        # Default is HTTP/1.0, which closes the connection per request and makes
        # a page of many sections feel slower than it is.
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - the stdlib's spelling
            parsed = urllib.parse.urlparse(self.path)
            status, body = route(
                parsed.path,
                urllib.parse.parse_qs(parsed.query),
                data_dir=data_dir,
                corpora_dir=corpora_dir,
                serve_local_only=serve_local_only,
                token=token,
            )
            self._respond(status, body)

        def do_POST(self) -> None:  # noqa: N802 - the stdlib's spelling
            parsed = urllib.parse.urlparse(self.path)
            if not parsed.path.startswith("/bless/"):
                self._respond(404, render.error_page(404, f"No such page: {parsed.path}"))
                return

            if not origin_ok(
                self.headers.get("Origin"),
                self.headers.get("Sec-Fetch-Site"),
                host=host,
                port=port,
            ):
                self._respond(
                    403,
                    render.error_page(
                        403, "Cross-site writes are refused. Submit the form on the page."
                    ),
                )
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= MAX_FORM_BYTES:
                self._respond(400, render.error_page(400, "Malformed submission."))
                return

            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            status, body, redirect = bless_route(
                parsed.path,
                form,
                data_dir=data_dir,
                corpora_dir=corpora_dir,
                serve_local_only=serve_local_only,
                token=token,
            )
            self._respond(status, body, redirect=redirect)

        def _respond(self, status: int, body: str, *, redirect: str | None = None) -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            if redirect is not None:
                self.send_header("Location", redirect)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            # The page carries corpus text. Nothing between here and the browser
            # should keep a copy of it.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args) -> None:
            """Log the request line, never a response body.

            Acquisition is careful never to print corpus text to a terminal or a
            log (`fingerprints.py`), and the viewer keeps that rule: text goes to
            the browser and nowhere else.
            """
            super().log_message(format, *args)

    return Handler


def serve(
    *,
    data_dir: pathlib.Path,
    corpora_dir: pathlib.Path,
    serve_local_only: bool,
    port: int = DEFAULT_PORT,
    host: str = HOST,
    announce: Callable[[str], None] = print,
) -> None:
    # One token per run. Blessing is a write, and a localhost port is reachable
    # from every page the browser has open; the token is what makes the form on
    # this page the only thing that can submit it.
    token = verify.new_token()
    handler = make_handler(
        data_dir=data_dir,
        corpora_dir=corpora_dir,
        serve_local_only=serve_local_only,
        token=token,
        host=host,
        port=port,
    )
    with http.server.ThreadingHTTPServer((host, port), handler) as httpd:
        announce(f"catena browse: http://{host}:{port}  (ctrl-c to stop)")
        announce(f"  data    {data_dir}")
        announce(f"  corpora {corpora_dir}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            announce("")
