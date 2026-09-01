#!/usr/bin/env python3
"""Fail when documentation names a `make` target the Makefile does not define.

The README's clone-to-first-answer path is the project's acceptance test. A target
that is renamed or never written breaks that path silently, and only for someone
running it for the first time — which is the one reader who cannot tell the
difference between a broken command and a broken project.

Only `make` invocations inside code markup count: inline `code spans` and fenced
blocks. Prose says "make sure" and "make it work", and neither is a target.

Usage:
    make_targets_guard.py                    # every tracked Markdown file
    make_targets_guard.py DOC.md [DOC.md...]
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

FENCED = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1", re.DOTALL | re.MULTILINE)
INLINE = re.compile(r"(`+)(.+?)\1", re.DOTALL)
MAKE_CALL = re.compile(r"\bmake\b(?P<rest>[^\n]*)")
TARGET_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")


def _targets_in_command_line(rest: str) -> str | None:
    for token in rest.split():
        if token.startswith("-") or "=" in token:
            continue  # a flag, or a variable override
        return token if TARGET_NAME.match(token) else None
    return None


def referenced_targets(markdown: str) -> set[str]:
    """Every make target named inside code markup in one Markdown document."""
    spans: list[str] = []
    remainder = FENCED.sub(lambda m: spans.append(m.group(0)) or "", markdown)
    spans.extend(m.group(2) for m in INLINE.finditer(remainder))

    found = set()
    for span in spans:
        for line in span.splitlines():
            for call in MAKE_CALL.finditer(line):
                target = _targets_in_command_line(call.group("rest"))
                if target:
                    found.add(target)
    return found


def makefile_targets(makefile: str) -> set[str]:
    """Every target the Makefile defines, including `.PHONY` declarations."""
    found = set()
    for line in makefile.splitlines():
        if not line or line.startswith(("\t", "#")):
            continue
        head, sep, rest = line.partition(":")
        if not sep or head.strip().endswith(("+", "?", "!")) or rest.startswith(("=", ":=")):
            continue  # `X := y`, `X ::= y`, `X ?= y`, `X += y`, `X != y`
        names = head.split()
        if names[:1] == [".PHONY"]:
            found.update(n for n in rest.split() if TARGET_NAME.match(n))
            continue
        found.update(n for n in names if TARGET_NAME.match(n))
    return found


def missing(docs: dict[str, str], makefile: str) -> list[tuple[str, str]]:
    """Every (document, target) pair naming a target with no rule."""
    defined = makefile_targets(makefile)
    return sorted(
        (path, target)
        for path, text in docs.items()
        for target in referenced_targets(text)
        if target not in defined
    )


def _tracked_markdown() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.md"], check=True, capture_output=True, text=True
    ).stdout
    return [p for p in out.split("\0") if p]


def main(argv: list[str]) -> int:
    paths = argv or _tracked_markdown()
    docs = {p: Path(p).read_text(encoding="utf-8") for p in paths}
    gaps = missing(docs, Path("Makefile").read_text(encoding="utf-8"))
    if not gaps:
        return 0

    print("make-targets: FAIL", file=sys.stderr)
    for path, target in gaps:
        print(f"  {path}\n      → documents `make {target}`, which the Makefile does not define", file=sys.stderr)
    print(f"\n{len(gaps)} undocumented-command reference(s).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
