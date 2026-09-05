"""A staged corpus as an HTML page.

Pure. Nothing here reads a file, opens a socket or consults the environment --
it takes a `Corpus` and returns a string, which is what makes the whole page
testable without a server.

**The markup is generated rather than templated from a file on purpose.**
`tools/guards/corpus_guard.py` denies `.html` anywhere in the tree, because that
is a format corpus text arrives in. Generating the page keeps that bright line
where it is instead of carving the viewer an exception into it.

The design has one idea: **warm text, cold apparatus**. The work's own words are
a warm-black serif; everything the machine added -- locators, hashes, segment
boundaries -- is a colder, smaller monospace that never competes with it. You
should be able to tell at a glance which marks are the document's and which are
ours, because confusing the two is the failure this whole project is about.

Segmentation is drawn as a ruled staff: a hairline across the reading column
with the locator sitting on the rule, so a boundary and its name are one mark
rather than two.

No JavaScript, and no external asset. Disclosure is `<details>`; the typefaces
are system stacks. `make dev-offline` blocks egress, and a page that degraded
under the offline overlay would fail exactly when it is most worth having.
"""

from __future__ import annotations

import html
import unicodedata

from catena import normalise as normalisation
from catena.browse import staged

#: Chunks per page. WCF is 171 and fits in one; WEB is ~31,100 verses and does
#: not. Paging is what keeps the viewer usable for the corpus that arrives after
#: the one it was written against.
PAGE_SIZE = 500

#: Stand-ins for characters normalisation removes or collapses. They are shown
#: because they are invisible: the entire reason step 0 of the contract exists is
#: that these survive every later step and produce a mismatch on text that looks
#: identical.
PILCROW = "¶"
OPEN_BOX = "␣"


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _slug(locator: str) -> str:
    """A fragment id for a locator. Not reversible, and does not need to be."""
    return "loc-" + "".join(character if character.isalnum() else "-" for character in locator)


# --- the normalisation view ------------------------------------------------


def normalisation_report(raw: str) -> list[str]:
    """What the contract's steps did to this segment, step by step.

    Derived by applying the steps rather than by describing them, and driven off
    the character sets in `catena.normalise` rather than a second copy of them.
    A viewer that enumerated its own idea of "whitespace" would drift from the
    contract silently, which is the failure mode the shared vectors exist to
    prevent.
    """
    lines: list[str] = []

    removed = [character for character in raw if character in normalisation.FORMAT_CHARACTERS_REMOVED]
    if removed:
        names = sorted({f"U+{ord(character):04X}" for character in removed})
        lines.append(f"Removed {len(removed)} format character(s): {', '.join(names)}")

    stripped = raw.translate({ord(character): None for character in normalisation.FORMAT_CHARACTERS_REMOVED})
    composed = unicodedata.normalize("NFC", stripped)
    if composed != stripped:
        lines.append("Recomposed to NFC")

    # Only runs that actually change the text count. A lone U+0020 is a
    # whitespace run and collapsing it to a single space is a no-op, so counting
    # it would report work on every segment ever written.
    runs = 0
    newlines = 0
    for run, leading, trailing in _whitespace_runs(composed):
        if leading or trailing:
            continue
        if run == " ":
            continue
        runs += 1
        newlines += run.count("\n")

    if runs:
        detail = f"{runs} whitespace run(s) collapsed to a single space"
        if newlines:
            detail += f", {newlines} of them line breaks from the segmenter"
        lines.append(detail)

    if composed != composed.strip():
        lines.append("Trimmed at the ends")

    if not lines:
        lines.append("Nothing to do: the segment was already normalised")
    return lines


def _whitespace_runs(text: str):
    """Every maximal run of contract whitespace, with whether it is at an end.

    A run at either end is trimmed rather than collapsed, and the two are
    different steps of the contract.
    """
    index = 0
    length = len(text)
    while index < length:
        if text[index] not in normalisation.WHITESPACE:
            index += 1
            continue
        start = index
        while index < length and text[index] in normalisation.WHITESPACE:
            index += 1
        yield text[start:index], start == 0, index == length


def visible(raw: str) -> str:
    """The segment with its invisible characters made visible, as HTML.

    Line breaks become a pilcrow and an actual break, so the segmenter's line
    structure is readable. That structure is where a swallowed heading or a
    table flattened down the wrong axis shows up, and it is gone the moment the
    record is normalised.
    """
    out: list[str] = []
    for character in raw:
        if character in normalisation.FORMAT_CHARACTERS_REMOVED:
            out.append(
                f'<span class="gone" title="U+{ord(character):04X}, removed by step 0">'
                f"U+{ord(character):04X}</span>"
            )
        elif character == "\n":
            out.append(f'<span class="ws">{PILCROW}</span>\n')
        elif character == " ":
            out.append(" ")
        elif character in normalisation.WHITESPACE:
            out.append(
                f'<span class="ws" title="U+{ord(character):04X}">{OPEN_BOX}</span>'
            )
        else:
            out.append(_e(character))
    return "".join(out)


# --- the page --------------------------------------------------------------


def _document(title: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_e(title)}</title>\n"
        f"<style>{CSS}</style>\n"
        "</head>\n<body>\n"
        f"{body}\n"
        "</body>\n</html>\n"
    )


def _facts(corpus: staged.Corpus) -> str:
    work = corpus.work
    rows: list[tuple[str, str]] = [
        ("Work", work.work),
        ("Edition", work.edition),
        ("Era", work.era),
        ("Author", work.author or "Corporate — no single author"),
        ("Language", work.language),
        ("Source language", work.source_language),
        ("Text form", work.text_form),
        ("Licence", work.license),
        ("Corpus ID", corpus.corpus_id),
        ("Normalisation", f"version {corpus.normalisation_version}"),
        (
            "Sections",
            str(len(corpus.chunks))
            if corpus.count_matches
            else f"{len(corpus.chunks)} staged, {corpus.chunk_count} declared",
        ),
    ]
    manifest = corpus.manifest
    if manifest is not None:
        rows += [
            ("Source", manifest.source_url),
            ("Retrieved", manifest.retrieved),
            ("Verified by", manifest.edition_check.verified_by),
            ("Verified", manifest.edition_check.verified),
            ("Diagnostic", manifest.edition_check.diagnostic),
        ]
    cells = "".join(
        f"<dt>{_e(label)}</dt><dd>{_e(value)}</dd>" for label, value in rows
    )
    attribution = f'<p class="attribution">{_e(work.attribution)}</p>'
    return f'<dl class="facts">{cells}</dl>{attribution}'


#: Locators named in a banner before it stops naming them and starts counting.
BANNER_SAMPLE = 5


def _sample(locators: list[str]) -> str:
    shown = ", ".join(_e(locator) for locator in locators[:BANNER_SAMPLE])
    if len(locators) > BANNER_SAMPLE:
        shown += f" and {len(locators) - BANNER_SAMPLE} more"
    return shown


def _count_note(corpus: staged.Corpus) -> str:
    """The declared-versus-staged section count, when the two disagree.

    `work.json` and `records.jsonl` are written by the same call, so a
    disagreement is not drift -- it is a staged tree one of whose halves is from
    a run that did not finish. Separate from the fingerprint banner because the
    remedy is different: re-acquire, rather than work out what upstream changed.
    """
    if corpus.count_matches:
        return ""
    return (
        f'<p class="banner flag">Staged output is inconsistent: <code>work.json</code> '
        f"declares {corpus.chunk_count} section(s) and <code>records.jsonl</code> holds "
        f"{len(corpus.chunks)}. They are written by the same run, so one of them is left "
        "over from another. Re-acquire before reading this as the corpus.</p>"
    )


def _overlay_note(corpus: staged.Corpus) -> str:
    """Why the committed evidence could not be read, when it could not.

    Without this the failure is invisible in the direction that matters: absent
    fingerprints and unreadable fingerprints both leave every chunk unchecked,
    and only one of them means nobody has ever verified this corpus.
    """
    if corpus.overlay_error is None:
        return ""
    return (
        f'<p class="banner flag">{_e(corpus.overlay_error)} Nothing below has been checked '
        "against the committed evidence, and the status above is what is knowable without "
        "it -- not a verdict on the text.</p>"
    )


def _banner(corpus: staged.Corpus, offered: bool = False, refusal: str | None = None) -> str:
    status = corpus.fingerprint_status
    if status == staged.BLESSED:
        return (
            f'<p class="banner ok">Blessed. All {len(corpus.chunks)} sections match the '
            "committed fingerprints.</p>"
        )
    if status == staged.DRIFTED:
        drifted = corpus.drifted
        clauses = []
        if drifted:
            clauses.append(
                f"{len(drifted)} section(s) do not match the committed fingerprints: "
                f"{_sample([chunk.locator for chunk in drifted])}"
            )
        if corpus.missing:
            # The class a per-chunk check cannot see. A committed locator with no
            # staged record did not change -- it stopped being produced at all.
            clauses.append(
                f"{len(corpus.missing)} committed section(s) are not in the staged output "
                f"at all: {_sample(corpus.missing)}"
            )
        return (
            f'<p class="banner flag">Drifted. {". ".join(clauses)}. What is on disk is not '
            "what was approved.</p>"
        )
    if offered:
        # Don't send someone to the terminal past the panel that does the same
        # thing three inches to the right.
        return (
            '<p class="banner warn">Unblessed. This corpus has been acquired but never '
            "verified by hand, so there are no committed fingerprints to check it against. "
            "Read the edition diagnostic to verify it.</p>"
        )
    if refusal:
        # Why there is no panel, rather than advice that does not apply. Each
        # reason this corpus cannot be verified here -- no registered adapter,
        # no staged diagnostic, unreadable committed evidence -- is a reason
        # `catena acquire --bless` fails too, so sending the reader to a terminal
        # would send them to the same wall with none of the explanation.
        return (
            '<p class="banner warn">Unblessed, and the verification cannot be offered: '
            f"{_e(refusal)}</p>"
        )
    return (
        '<p class="banner warn">Unblessed. This corpus has been acquired but never verified '
        "by hand, so there are no committed fingerprints to check it against. Run "
        f'<code>make bless CORPUS={_e(corpus.corpus_id)}</code> at a terminal.</p>'
    )


def _index(corpus: staged.Corpus, chunks: list[staged.Chunk]) -> str:
    links = "".join(
        f'<li><a href="#{_slug(chunk.locator)}">{_e(chunk.locator)}</a></li>'
        for chunk in chunks
    )
    return f'<nav class="index" aria-label="Sections"><ol>{links}</ol></nav>'


def _apparatus(chunk: staged.Chunk) -> str:
    if chunk.blessed is None:
        mark = '<span class="dim">not checked</span>'
    elif chunk.blessed:
        mark = '<span class="ok">matches fingerprint</span>'
    else:
        mark = '<span class="flag">does not match fingerprint</span>'

    rows = (
        f"<dt>sha256</dt><dd><code>{_e(chunk.content_hash)}</code></dd>"
        f"<dt>length</dt><dd>{chunk.length} characters</dd>"
        f"<dt>fingerprint</dt><dd>{mark}</dd>"
    )

    if chunk.raw is None:
        raw_view = (
            '<p class="dim">No usable segment output for this section: either '
            "<code>segment/</code> is absent, or what is there no longer normalises to "
            "the text above, which means the two stages are from different acquisition "
            "runs. Re-acquire to see what normalisation did.</p>"
        )
    else:
        steps = "".join(f"<li>{_e(line)}</li>" for line in normalisation_report(chunk.raw))
        raw_view = (
            f"<ul class='steps'>{steps}</ul>"
            f'<pre class="raw">{visible(chunk.raw)}</pre>'
        )

    return (
        f'<div class="panel"><dl class="meta">{rows}</dl>'
        f'<h3>Before normalisation</h3>{raw_view}</div>'
    )


def _chunk(chunk: staged.Chunk) -> str:
    return (
        f'<section class="chunk" id="{_slug(chunk.locator)}">'
        f'<details class="apparatus">'
        f'<summary class="rule"><span class="loc">{_e(chunk.locator)}</span></summary>'
        f"{_apparatus(chunk)}"
        f"</details>"
        f'<p class="text">{_e(chunk.text)}</p>'
        f"</section>"
    )


def verify_panel(offer, token: str, error: str | None = None) -> str:
    """The edition verification, put in front of a human before anything is written.

    The passage is shown in full and in the reading face, because reading it is
    the act. The form carries the hash of what is displayed so the bless can
    refuse if the text moved underneath it (see `browse/verify.py`).
    """
    complaint = f'<p class="verify-error">{_e(error)}</p>' if error else ""
    return (
        '<section class="verify">'
        "<h2>Verify this edition</h2>"
        '<p class="verify-lede">This corpus has never been verified by hand. Read the passage '
        "below in full. If it is the edition this corpus claims to be, record your name to "
        "bless it; the manifest stores only the hash, never the text.</p>"
        f"{complaint}"
        f'<p class="verify-meta">Edition diagnostic <strong>{_e(offer.diagnostic)}</strong></p>'
        f'<p class="text verify-text">{_e(offer.text)}</p>'
        f'<dl class="meta"><dt>sha256</dt><dd><code>{_e(offer.content_hash)}</code></dd>'
        f"<dt>source</dt><dd>{_e(offer.source_url)}</dd></dl>"
        f'<form class="verify-form" method="post" action="/bless/{_e(offer.corpus_id)}">'
        f'<input type="hidden" name="token" value="{_e(token)}">'
        f'<input type="hidden" name="read_sha256" value="{_e(offer.content_hash)}">'
        '<label for="verifier">Your name, recorded as having read the text above</label>'
        '<input id="verifier" name="name" type="text" autocomplete="name" required>'
        '<button type="submit">Bless this corpus</button>'
        "</form>"
        '<p class="verify-note">Submitting re-acquires the corpus from its source, which '
        "reaches the network, and refuses to write if the passage has changed since it was "
        "shown here.</p>"
        "</section>"
    )


def _pager(corpus: staged.Corpus, page: int, pages: int) -> str:
    if pages <= 1:
        return ""
    parts = []
    if page > 0:
        parts.append(f'<a href="/c/{_e(corpus.corpus_id)}?page={page - 1}">Previous</a>')
    parts.append(f"<span>Page {page + 1} of {pages}</span>")
    if page < pages - 1:
        parts.append(f'<a href="/c/{_e(corpus.corpus_id)}?page={page + 1}">Next</a>')
    return f'<nav class="pager">{"".join(parts)}</nav>'


def corpus_page(
    corpus: staged.Corpus,
    *,
    page: int = 0,
    page_size: int = PAGE_SIZE,
    withheld: str | None = None,
    offer=None,
    offer_refusal: str | None = None,
    token: str = "",
    verify_error: str | None = None,
) -> str:
    """One corpus, read as a document.

    `withheld` is the licence gate's reason. When it is set no chunk text is
    emitted at all -- not hidden with CSS, not truncated: absent from the
    markup, because the page is the serving act.
    """
    pages = max(1, -(-len(corpus.chunks) // page_size))
    page = max(0, min(page, pages - 1))
    window = corpus.chunks[page * page_size : (page + 1) * page_size]

    masthead = (
        f'<header class="masthead"><h1>{_e(corpus.work.work)}</h1>'
        f'<p class="sub">{_e(corpus.work.edition)}</p>'
        f'<p class="home"><a href="/">All corpora</a></p></header>'
    )

    if withheld is not None:
        reading = f'<p class="withheld">{_e(withheld)}</p>'
        index = ""
    else:
        if offer is not None:
            verify = verify_panel(offer, token, verify_error)
        elif verify_error:
            # A refusal can be the very thing that withdraws the offer -- an
            # unreadable overlay, a manifest that appeared underneath the page.
            # Dropping the complaint with the panel would answer a submission
            # with a page that says nothing about what happened to it.
            verify = f'<p class="banner flag">{_e(verify_error)}</p>'
        else:
            verify = ""
        reading = (
            verify + "".join(_chunk(chunk) for chunk in window) + _pager(corpus, page, pages)
        )
        index = _index(corpus, window)

    body = (
        f"{masthead}"
        f'<div class="layout">'
        f'<aside class="side">{_banner(corpus, offer is not None, offer_refusal)}'
        f"{_overlay_note(corpus)}{_count_note(corpus)}{_facts(corpus)}{index}</aside>"
        f'<main class="reading">{reading}</main>'
        f"</div>"
    )
    return _document(f"{corpus.work.work} — {corpus.corpus_id}", body)


def index_page(corpora: list[staged.Corpus]) -> str:
    """Every corpus with staged output on disk."""
    if not corpora:
        body = (
            '<header class="masthead"><h1>No corpora acquired</h1></header>'
            '<div class="layout"><main class="reading"><p class="withheld">'
            "Nothing has been acquired into this data directory yet. Run "
            "<code>make bless CORPUS=&lt;id&gt;</code> to acquire and verify a corpus "
            "for the first time, then <code>make provision-corpus</code> afterwards."
            "</p></main></div>"
        )
        return _document("Berean — no corpora", body)

    items = "".join(
        f'<li><a href="/c/{_e(corpus.corpus_id)}"><span class="loc">'
        f"{_e(corpus.corpus_id)}</span> {_e(corpus.work.work)}</a>"
        f'<span class="dim">{_e(corpus.work.edition)} · '
        f"{len(corpus.chunks)} sections · {_e(corpus.fingerprint_status)}</span></li>"
        for corpus in corpora
    )
    body = (
        '<header class="masthead"><h1>Acquired corpora</h1>'
        '<p class="sub">Staged output on this machine</p></header>'
        f'<div class="layout"><main class="reading"><ul class="corpora">{items}</ul></main></div>'
    )
    return _document("Berean — acquired corpora", body)


def error_page(status: int, message: str) -> str:
    body = (
        f'<header class="masthead"><h1>{status}</h1></header>'
        f'<div class="layout"><main class="reading"><p class="withheld">{_e(message)}</p>'
        '<p><a href="/">All corpora</a></p></main></div>'
    )
    return _document(f"Berean — {status}", body)


CSS = """
:root {
  --paper: #FBFAF8;
  --ink: #1A1714;
  --rule: #DAD6CE;
  --apparatus: #3F4C57;
  --apparatus-dim: #5F6C78;
  --flag: #A03E2F;
  --ok: #4A6B52;
  --panel: #F3F1EC;
  /* --apparatus and --apparatus-dim both carry text -- locators, labels, hashes --
     so both clear 4.5:1 against the paper AND against the panel they sit on.
     The locator is meant to read as quiet, not as decoration; quieter than this
     is illegible rather than subtle. */
  --serif: ui-serif, Charter, "Bitstream Charter", "Iowan Old Style", Palatino, Georgia, serif;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #14120F;
    --ink: #E8E2D8;
    --rule: #332E27;
    --apparatus: #AEBCC7;
    --apparatus-dim: #8E99A4;
    --flag: #D9705C;
    --ok: #7FA98A;
    --panel: #1D1A16;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: var(--serif);
  -webkit-text-size-adjust: 100%;
}
a { color: inherit; text-decoration-color: var(--apparatus-dim); text-underline-offset: 2px; }
a:hover { text-decoration-color: var(--apparatus); }
:focus-visible { outline: 2px solid var(--apparatus); outline-offset: 3px; }

.masthead {
  padding: 2.5rem 2rem 1.5rem;
  border-bottom: 1px solid var(--rule);
}
.masthead h1 { margin: 0; font-size: 1.75rem; font-weight: 600; letter-spacing: -0.01em; }
.masthead .sub { margin: 0.35rem 0 0; color: var(--apparatus); font-size: 1rem; }
.masthead .home { margin: 0.75rem 0 0; font-family: var(--mono); font-size: 0.78rem; }

.layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0; }
@media (min-width: 60rem) {
  .layout { grid-template-columns: 21rem minmax(0, 1fr); }
  .side {
    position: sticky; top: 0; align-self: start;
    max-height: 100vh; overflow-y: auto;
    border-right: 1px solid var(--rule);
  }
}
.side { padding: 1.75rem 1.5rem; font-family: var(--mono); font-size: 0.78rem; }
.reading { padding: 2.5rem 2rem 6rem; min-width: 0; }

.banner { margin: 0 0 1.5rem; padding: 0.7rem 0.85rem; border-left: 3px solid; line-height: 1.5; }
.banner.ok   { border-color: var(--ok);   color: var(--ok); }
.banner.warn { border-color: var(--apparatus); color: var(--apparatus); }
.banner.flag { border-color: var(--flag); color: var(--flag); }
.banner code { font-size: 0.95em; }

/* Stacked rather than two columns: a long label ("Source language") would
   otherwise squeeze every value into a narrow column and break URLs mid-token. */
.facts { margin: 0 0 1.5rem; }
.facts dt { color: var(--apparatus-dim); font-size: 0.72rem; }
.facts dd { margin: 0 0 0.7rem; color: var(--apparatus); overflow-wrap: anywhere; }
.attribution {
  margin: 0 0 1.5rem; padding-top: 1rem; border-top: 1px solid var(--rule);
  color: var(--apparatus); line-height: 1.55;
}

.index ol { margin: 0; padding: 0; list-style: none; display: flex; flex-wrap: wrap; gap: 0.3rem 0.6rem; }
.index a { color: var(--apparatus); text-decoration: none; }
.index a:hover { color: var(--ink); }

.chunk { margin: 0 0 2.25rem; max-width: 40rem; }
.apparatus > .rule {
  display: flex; align-items: center; gap: 0.75rem;
  list-style: none; cursor: pointer;
  padding: 0.2rem 0; margin-bottom: 0.9rem;
}
.apparatus > .rule::-webkit-details-marker { display: none; }
.apparatus > .rule::after { content: ""; flex: 1; border-top: 1px solid var(--rule); }
.apparatus > .rule:hover::after, .apparatus[open] > .rule::after { border-color: var(--apparatus-dim); }
.loc {
  font-family: var(--mono); font-size: 0.72rem; letter-spacing: 0.02em;
  color: var(--apparatus-dim);
}
.apparatus > .rule:hover .loc, .apparatus[open] > .rule .loc { color: var(--apparatus); }

.text { margin: 0; font-size: 1.1875rem; line-height: 1.62; max-width: 62ch; }

.panel {
  margin: 0 0 1.1rem; padding: 1rem 1.1rem;
  background: var(--panel); border-left: 2px solid var(--rule);
  font-family: var(--mono); font-size: 0.76rem; line-height: 1.6; color: var(--apparatus);
}
.panel h3 { margin: 1rem 0 0.5rem; font-size: 0.72rem; font-weight: 600; color: var(--apparatus-dim); }
.meta { margin: 0; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 0.25rem 0.9rem; }
.meta dt { color: var(--apparatus-dim); }
.meta dd { margin: 0; overflow-wrap: anywhere; }
.steps { margin: 0 0 0.75rem; padding-left: 1.1rem; }
.raw { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--ink); font-size: 0.76rem; }
.ws { color: var(--apparatus-dim); }
.gone { color: var(--flag); }
.ok { color: var(--ok); }
.flag { color: var(--flag); }
.dim { color: var(--apparatus-dim); }

.verify {
  max-width: 42rem; margin: 0 0 3rem; padding: 1.4rem 1.5rem;
  background: var(--panel); border-left: 3px solid var(--ok);
}
.verify h2 { margin: 0 0 0.6rem; font-size: 1.15rem; font-weight: 600; }
.verify-lede, .verify-note, .verify-meta, .verify-error {
  font-family: var(--mono); font-size: 0.78rem; line-height: 1.65; color: var(--apparatus);
}
.verify-lede { margin: 0 0 1rem; }
.verify-meta { margin: 0 0 0.6rem; }
.verify-error { margin: 0 0 1rem; padding: 0.6rem 0.8rem; border-left: 3px solid var(--flag); color: var(--flag); }
.verify-text {
  margin: 0 0 1rem; padding: 0 0 1rem;
  border-bottom: 1px solid var(--rule); font-size: 1.0625rem;
}
.verify-form { display: grid; gap: 0.45rem; justify-items: start; margin: 1rem 0 0.9rem; }
.verify-form label { font-family: var(--mono); font-size: 0.74rem; color: var(--apparatus-dim); }
.verify-form input[type="text"] {
  font-family: var(--mono); font-size: 0.85rem; padding: 0.45rem 0.6rem; width: min(22rem, 100%);
  color: var(--ink); background: var(--paper);
  border: 1px solid var(--rule); border-radius: 2px;
}
.verify-form button {
  font-family: var(--mono); font-size: 0.8rem; padding: 0.5rem 1rem; cursor: pointer;
  color: var(--paper); background: var(--ink);
  border: 1px solid var(--ink); border-radius: 2px;
}
.verify-form button:hover { background: var(--apparatus); border-color: var(--apparatus); }
.verify-note { margin: 0; color: var(--apparatus-dim); }

.withheld {
  max-width: 42rem; padding: 1rem 1.1rem; border-left: 3px solid var(--flag);
  color: var(--apparatus); font-family: var(--mono); font-size: 0.82rem; line-height: 1.65;
}
.pager { display: flex; gap: 1.25rem; align-items: center; font-family: var(--mono); font-size: 0.78rem; color: var(--apparatus); }
.corpora { margin: 0; padding: 0; list-style: none; max-width: 46rem; }
.corpora li { padding: 1rem 0; border-bottom: 1px solid var(--rule); display: grid; gap: 0.3rem; }
.corpora a { text-decoration: none; font-size: 1.05rem; }
.corpora .loc { display: block; margin-bottom: 0.15rem; }
.corpora .dim { font-family: var(--mono); font-size: 0.74rem; }
"""
