"""The normalisation contract, Python side.

Ingestion normalises here; verification normalises in Go. There is no shared
function and the specs must not ask for one -- what is shared is this ordered
list of steps and the vectors in `testdata/normalisation/vectors.json`, which
both suites read.

Fingerprints are hashes of post-normalisation text, so changing anything in
this module invalidates every committed fingerprint file and forces a re-bless
of every corpus. Bump `NORMALISATION_VERSION` when that happens; the manifests
record which contract version they were blessed under, so the re-bless is
visible rather than silent.

Every code point below is written as an escape. These characters are invisible
by definition, and a table of them written literally cannot be reviewed.

See INTEGRATION-SPEC, "Normalisation contract".
"""

from __future__ import annotations

import unicodedata

#: Bumping this re-blesses every corpus. It is not a version of this file.
NORMALISATION_VERSION = 1

#: Step 0. Invisible, and whitespace in neither language's standard library, so
#: they survive every later step intact and produce a quote mismatch on text
#: that is visually identical. They arrive from ordinary PDF and HTML
#: extraction, which is the whole reason this step exists.
FORMAT_CHARACTERS_REMOVED = frozenset(
    {
        "\uFEFF",   # zero width no-break space, used as a byte order mark
        "\u200B",   # zero width space
        "\u200C",   # zero width non-joiner
        "\u200D",   # zero width joiner
        "\u00AD",   # soft hyphen
    }
)

#: Step 2. Exactly the Unicode `White_Space` property, enumerated rather than
#: tested for.
#:
#: Naming the set is load-bearing. Python's ``\s`` and ``str.isspace`` also
#: match U+001C-U+001F, which Go's ``unicode.IsSpace`` does not, so "collapse
#: whitespace" written against either standard library is two different
#: functions -- and the difference only ever shows up as a quote that will not
#: match a passage it is plainly inside.
WHITESPACE = frozenset(
    {
        "\u0009",   # character tabulation
        "\u000A",   # line feed
        "\u000B",   # line tabulation
        "\u000C",   # form feed
        "\u000D",   # carriage return
        "\u0020",   # space
        "\u0085",   # next line
        "\u00A0",   # no-break space
        "\u1680",   # ogham space mark
        "\u2000",   # en quad
        "\u2001",   # em quad
        "\u2002",   # en space
        "\u2003",   # em space
        "\u2004",   # three-per-em space
        "\u2005",   # four-per-em space
        "\u2006",   # six-per-em space
        "\u2007",   # figure space
        "\u2008",   # punctuation space
        "\u2009",   # thin space
        "\u200A",   # hair space
        "\u2028",   # line separator
        "\u2029",   # paragraph separator
        "\u202F",   # narrow no-break space
        "\u205F",   # medium mathematical space
        "\u3000",   # ideographic space
    }
)

_REMOVE = {ord(character): None for character in FORMAT_CHARACTERS_REMOVED}


def normalise(text: str) -> str:
    """Apply the contract's steps, in order.

    0. Remove the format characters above.
    1. Unicode NFC -- never NFKC, which would rewrite ligatures and fullwidth
       forms into different text.
    2. Collapse runs of `WHITESPACE` to a single U+0020.
    3. Trim the ends.
    4. Nothing else. No case folding, no quote or dash folding, no punctuation
       stripping: a quote differing from its source by a curly apostrophe is a
       genuine mismatch and must fail.

    Step 0 runs before step 1 rather than after, and the order is the decision
    rather than an accident. A zero width joiner sitting between a base letter
    and its combining mark blocks composition, so normalising first leaves a
    decomposed sequence that stripping afterwards cannot repair.
    """
    composed = unicodedata.normalize("NFC", text.translate(_REMOVE))

    # Steps 2 and 3 in one pass. A leading run finds nothing emitted yet and a
    # trailing run is never flushed, which is the trim.
    out: list[str] = []
    pending_space = False
    for character in composed:
        if character in WHITESPACE:
            pending_space = True
            continue
        if pending_space and out:
            out.append(" ")
        pending_space = False
        out.append(character)
    return "".join(out)
