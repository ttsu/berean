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
import urllib.parse
from typing import Callable

from catena.acquire.record import AcquisitionError
from catena.browse import render, staged

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
        return 200, render.corpus_page(corpus, page=page, withheld=withheld)

    return 404, render.error_page(404, f"No such page: {path}")


def make_handler(
    *,
    data_dir: pathlib.Path,
    corpora_dir: pathlib.Path,
    serve_local_only: bool,
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
            )
            payload = body.encode("utf-8")
            self.send_response(status)
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
    handler = make_handler(
        data_dir=data_dir, corpora_dir=corpora_dir, serve_local_only=serve_local_only
    )
    with http.server.ThreadingHTTPServer((host, port), handler) as httpd:
        announce(f"catena browse: http://{host}:{port}  (ctrl-c to stop)")
        announce(f"  data    {data_dir}")
        announce(f"  corpora {corpora_dir}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            announce("")
