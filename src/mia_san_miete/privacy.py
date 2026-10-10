"""Scan tracked files for private data before it reaches a remote.

Two layers: generic patterns (email addresses, mobile numbers, IBANs) and a local,
gitignored terms file (`.private-terms`, one term per line) holding your own employers,
addresses, figures and names. The terms file itself is never committed, so the scanner
does not leak what it protects.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

PATTERNS = {
    "email address": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "mobile number": re.compile(r"(?<!\d)(?:\+49|0049|0)\s?1[5-7]\d[\s/-]?\d{6,8}(?!\d)"),
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}(?:\s?\d{4}){4,7}(?:\s?\d{1,2})?\b"),
}
ALLOWED_EMAIL = re.compile(
    r"@(?:[\w-]+\.)*(?:test|example|invalid|localhost)\b|@example\.(?:com|org)"
    r"|@users\.noreply\.github\.com$|^noreply@(?:anthropic|github)\.com$")
PLACEHOLDER_NUMBERS = {"+49 170 0000000"}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str      # never contains the matched text, so reports are safe to share


def load_terms(path: str | Path) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    terms = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            terms.append(line.lower())
    return terms


def scan_text(path: str, text: str, terms: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for n, line in enumerate(text.splitlines(), start=1):
        low = line.lower()
        if any(t in low for t in terms):
            findings.append(Finding(path, n, "private term"))
        for kind, pattern in PATTERNS.items():
            for m in pattern.finditer(line):
                hit = m.group(0)
                if kind == "email address" and ALLOWED_EMAIL.search(hit):
                    continue
                if hit in PLACEHOLDER_NUMBERS:
                    continue
                findings.append(Finding(path, n, kind))
    return findings


def tracked_files(root: str | Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True, capture_output=True, text=True,
    )
    return [f for f in out.stdout.splitlines() if f]


def scan_repo(root: str | Path, terms_path: str | Path | None = None) -> list[Finding]:
    root = Path(root)
    terms = load_terms(terms_path if terms_path else root / ".private-terms")
    findings: list[Finding] = []
    for rel in tracked_files(root):
        path = root / rel
        if not path.is_file() or path.name == ".private-terms":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue   # binary file
        findings.extend(scan_text(rel, text, terms))
    return findings


@dataclass(frozen=True)
class HistoryFinding:
    where: str      # blob | commit message | author | ref name
    commit: str     # short hash (for a blob: the oldest commit that contains it)
    path: str
    line: int
    kind: str       # never the matched text


@dataclass
class HistoryReport:
    findings: list[HistoryFinding]
    binaries: list[str]        # binary files in history: look at them by hand
    commits: int
    blobs: int
    refs: int
    shallow: bool


def _git(root: Path, *args: str, text: bool = True,
         stdin: str | bytes | None = None) -> subprocess.CompletedProcess:
    if stdin is not None and text and isinstance(stdin, bytes):
        stdin = stdin.decode()
    if stdin is not None and not text and isinstance(stdin, str):
        stdin = stdin.encode()
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=text, input=stdin)


def scan_history(root: str | Path, terms_path: str | Path | None = None) -> HistoryReport:
    """Scan everything reachable from any ref: every version of every file, commit messages,
    author and committer names and addresses, and branch and tag names. A flat file you deleted
    last week is still in the history, and so is a typo in a commit message.

    Reports commit, path and line, never the matched text."""
    root = Path(root)
    terms = load_terms(terms_path if terms_path else root / ".private-terms")
    shallow = _git(root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    findings: list[HistoryFinding] = []

    refs = _git(root, "for-each-ref", "--format=%(refname)").stdout.split()
    for ref in refs:
        for f in scan_text(ref, ref, terms):
            findings.append(HistoryFinding("ref name", "-", "ref", f.line, f.kind))

    log = _git(root, "log", "--all", "--format=%h%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B%x1e").stdout
    commits = [c for c in log.split("\x1e") if c.strip()]
    for entry in commits:
        h, an, ae, cn, ce, body = (entry.strip("\n").split("\x1f", 5) + [""] * 6)[:6]
        for label, value in (("author", f"{an} <{ae}>"), ("author", f"{cn} <{ce}>")):
            for f in scan_text(label, value, terms):
                findings.append(HistoryFinding(label, h, label, 1, f.kind))
        for f in scan_text("message", body, terms):
            findings.append(HistoryFinding("commit message", h, "message", f.line, f.kind))

    listing = _git(root, "rev-list", "--objects", "--all").stdout.splitlines()
    paths: dict[str, str] = {}
    for line in listing:
        oid, _, path = line.partition(" ")
        paths.setdefault(oid, path)
    check = _git(root, "cat-file", "--batch-check", text=True, stdin="\n".join(paths).encode()).stdout
    blobs = [row.split()[0] for row in check.splitlines() if row.split()[1] == "blob"]
    binaries: list[str] = []
    blob_findings: list[tuple[str, Finding]] = []
    if blobs:
        raw = _git(root, "cat-file", "--batch", text=False, stdin=("\n".join(blobs) + "\n").encode()).stdout
        pos = 0
        while pos < len(raw):
            end = raw.index(b"\n", pos)
            oid, _, size = raw[pos:end].decode().split()
            body = raw[end + 1:end + 1 + int(size)]
            pos = end + 1 + int(size) + 1
            path = paths.get(oid, oid)
            if b"\x00" in body:
                binaries.append(path)
                continue
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                binaries.append(path)
                continue
            if path.split("/")[-1] == ".private-terms":
                blob_findings.append((oid, Finding(path, 1, "terms file committed")))
                continue
            blob_findings.extend((oid, f) for f in scan_text(path, text, terms))
    for oid, f in blob_findings:
        found = _git(root, "log", "--all", "--format=%h", f"--find-object={oid}").stdout.split()
        findings.append(HistoryFinding("blob", found[-1] if found else "?", f.path, f.line, f.kind))
    return HistoryReport(sorted(set(findings), key=lambda x: (x.commit, x.path, x.line, x.kind)),
                         sorted(set(binaries)), len(commits), len(blobs), len(refs), shallow)


HOOK = """#!/bin/sh
# Installed by `mia install-hook`: block commits that contain private data.
exec "{python}" -m mia_san_miete.cli check-private
"""
