#!/usr/bin/env python3
"""Refuse any commit that carries corpus text (ADR-0014).

The rule is structural on purpose. It denies by path and shape and never asks what
a file means, because a rule that needs per-corpus licensing judgement is exactly
the rule ADR-0014 exists to replace. The repository carries acquisition manifests,
fingerprints, and the per-corpus adapters under
`services/catena/src/catena/acquire/corpora/`; text is acquired to gitignored
local storage.

What this catches: text staged under the acquired-data trees, text smuggled into
the `corpora/` tree beside its manifest, and text-bearing or dump file formats
anywhere in the source tree. What it does not catch: a passage pasted into a
`.go` or `.py` test fixture. That case is covered by the invented-text-only rule the two service
AGENTS.md files carry, and by review.

Usage:
    corpus_guard.py              # check the git index (pre-commit)
    corpus_guard.py --tracked    # check every tracked file (CI)
    corpus_guard.py PATH...      # check the named paths
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable, Iterable, NamedTuple

#: Acquired text and model weights live here and are gitignored. Nothing under
#: either tree is ever committable, with no negation patterns and no exceptions.
DENIED_TREES = ("data", "models")

#: `corpora/<corpus-id>/` carries evidence about a corpus, never the corpus.
CORPORA_TREE = "corpora"
CORPORA_ALLOWED = frozenset({"manifest.yaml", "fingerprints.txt"})

#: Formats corpus text arrives in. Denied everywhere except the allowlist below.
TEXT_BEARING_SUFFIXES = frozenset(
    {
        ".txt", ".text", ".xml", ".usfm", ".usx", ".sfm", ".osis", ".vpl",
        ".htm", ".html", ".epub", ".pdf", ".docx", ".doc", ".rtf", ".csv", ".tsv",
    }
)

#: Formats a corpus dump arrives in that are also ordinary structured data. Denied
#: like the rest, except inside a fixture directory, where the size ceiling is
#: already the governing rule — a dump of staged records is large, and invented
#: fixture text is not. Config that legitimately needs one of these suffixes goes
#: in the allowlist below by name, so admitting it is a recorded act.
DUMP_SUFFIXES = frozenset({".json", ".jsonl", ".ndjson"})

#: Files whose suffix is text-bearing but whose role in the repository is not.
TEXT_SUFFIX_ALLOWLIST = frozenset(
    {"requirements.txt", "requirements-dev.txt", "constraints.txt", "fingerprints.txt"}
)

#: Directories where test fixtures live. Invented text is short; corpus text is not.
FIXTURE_DIR_NAMES = frozenset({"testdata", "fixtures", "golden"})
FIXTURE_SIZE_CEILING = 64 * 1024


#: tools/guards/corpus_guard.py -> the repository root, so an absolute path and a
#: repo-relative one name the same file without the guard needing git to run.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Violation(NamedTuple):
    path: str
    reason: str


def _segments(path: str) -> list[str]:
    """Repo-relative components, however the path was written.

    Paths arrive from three places — git's index, `git ls-files`, and argv — and
    only the first two are already clean. A `./` prefix or an absolute path, which
    is what a CI script or an editor integration naturally passes, used to leave
    `parts[0]` as `.` or as a filesystem root, matching no denied tree: the
    hardest rule in the repository failed open on an ordinary way of calling it.
    """
    norm = os.path.normpath(path).replace(os.sep, "/")
    if os.path.isabs(path):
        norm = os.path.relpath(norm, _REPO_ROOT).replace(os.sep, "/")
    return [s for s in norm.split("/") if s and s != "."]


def _violation(path: str, size_of: Callable[[str], int]) -> Violation | None:
    parts = _segments(path)
    if not parts:
        return None
    name = parts[-1]

    if parts[0] == "..":
        return Violation(
            path,
            "resolves outside the repository root, so no denied-tree rule can be "
            "applied to it — pass a repo-relative path (ADR-0014)",
        )

    if parts[0] in DENIED_TREES:
        return Violation(
            path,
            f"/{parts[0]}/ holds acquired text and weights and is never committable (ADR-0014)",
        )

    if parts[0] == CORPORA_TREE:
        if len(parts) == 3 and name in CORPORA_ALLOWED:
            return None
        allowed = ", ".join(sorted(CORPORA_ALLOWED))
        return Violation(
            path,
            f"corpora/<corpus-id>/ admits only {allowed} — evidence about a corpus, "
            "never the corpus (ADR-0014)",
        )

    suffix = os.path.splitext(name)[1].lower()
    allowlisted = name in TEXT_SUFFIX_ALLOWLIST
    in_fixture_dir = bool(FIXTURE_DIR_NAMES.intersection(parts[:-1]))

    if suffix in TEXT_BEARING_SUFFIXES and not allowlisted:
        return Violation(
            path,
            f"'{suffix}' is a format corpus text arrives in; it is not committable "
            "outside corpora/ (ADR-0014)",
        )

    if suffix in DUMP_SUFFIXES and not allowlisted and not in_fixture_dir:
        return Violation(
            path,
            f"'{suffix}' is a format corpus dumps arrive in; outside a fixture "
            "directory it is not committable (ADR-0014)",
        )

    if in_fixture_dir:
        size = size_of(path)
        if size > FIXTURE_SIZE_CEILING:
            return Violation(
                path,
                f"fixture is {size} bytes, over the {FIXTURE_SIZE_CEILING}-byte ceiling — "
                "fixtures use invented text, which is short (ADR-0014)",
            )

    return None


def violations(
    paths: Iterable[str], size_of: Callable[[str], int] = os.path.getsize
) -> list[Violation]:
    """Every path that may not be committed, in the order given."""
    found = []
    for path in paths:
        hit = _violation(path, size_of)
        if hit is not None:
            found.append(hit)
    return found


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def _staged_paths() -> list[str]:
    out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [p for p in out.split("\0") if p]


def _staged_size(path: str) -> int:
    return int(_git("cat-file", "-s", f":{path}").strip())


def main(argv: list[str]) -> int:
    if argv == ["--tracked"]:
        paths, size_of = [p for p in _git("ls-files", "-z").split("\0") if p], os.path.getsize
    elif argv:
        paths, size_of = argv, os.path.getsize
    else:
        paths, size_of = _staged_paths(), _staged_size

    found = violations(paths, size_of=size_of)
    if not found:
        return 0

    print("corpus-guard: FAIL", file=sys.stderr)
    for v in found:
        print(f"  {v.path}\n      → {v.reason}", file=sys.stderr)
    print(
        f"\n{len(found)} file(s) rejected. No corpus text enters this repository, from any "
        "source, whatever its licence.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
