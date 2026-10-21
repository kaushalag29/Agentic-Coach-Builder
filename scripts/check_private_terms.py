#!/usr/bin/env python3
"""Refuse a commit or push that contains one of your private terms (company, book titles, ISBNs, local paths).

    python scripts/check_private_terms.py              # tracked and new (not ignored) files, file names, unpushed commit messages
    python scripts/check_private_terms.py --pre-push   # as the git pre-push hook (scripts/hooks/pre-push)

The terms live outside the repo, in the file YTBRAIN_PRIVATE_TERMS names (shell or the repo's .env): one term per
line, matched case-insensitively anywhere in a line; blank lines and lines starting with # are skipped. With no
such file (a fresh clone, CI) the check says it was skipped and passes. Standard library only.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 5_000_000          # larger tracked files are reported as not scanned


def _terms_file() -> Path | None:
    raw = os.environ.get("YTBRAIN_PRIVATE_TERMS")
    if raw is None:                                     # check.sh and git hooks don't load .env: read this one key
        env = ROOT / ".env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
                key, sep, val = line.strip().removeprefix("export ").partition("=")
                if sep and key.strip() == "YTBRAIN_PRIVATE_TERMS":
                    val = val.strip()
                    raw = val[1:-1] if val[:1] in "\"'" and val.endswith(val[:1]) and len(val) > 1 else val
    return Path(raw).expanduser() if raw else None


def load_terms(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if t and not t.startswith("#"):
            out.append(t)
    return out


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def find(terms: list[str], name: str, text: str) -> list[str]:
    """`name:line: term` for every line of `text` holding a term (each term once per line)."""
    low = [t.lower() for t in terms]
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        ll = line.lower()
        hits += [f"{name}:{n}: {t}" for t, lt in zip(terms, low) if lt in ll]
    return hits


def pushed_messages(stdin: str | None) -> str:
    """Commit messages that would leave this machine: the ranges git hands the pre-push hook, else every commit
    on HEAD that no remote has yet."""
    if not stdin:
        return _git("log", "--format=%B", "HEAD", "--not", "--remotes")
    msgs = []
    for line in stdin.splitlines():
        parts = line.split()
        if len(parts) != 4 or set(parts[1]) == {"0"}:         # a deleted ref sends nothing
            continue
        local, remote = parts[1], parts[3]
        rng = [local, "--not", "--remotes"] if set(remote) == {"0"} else [f"{remote}..{local}"]
        msgs.append(_git("log", "--format=%B", *rng))
    return "\n".join(msgs)


def main(argv: list[str]) -> int:
    path = _terms_file()
    if path is None or not path.is_file():
        print("check_private_terms: skipped (no YTBRAIN_PRIVATE_TERMS file)")
        return 0
    try:
        path.resolve().relative_to(ROOT)
        inside = True
    except ValueError:
        inside = False
    if inside and subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=ROOT).returncode != 0:
        print(f"check_private_terms: {path} is inside the repo and not git-ignored: move it out first")
        return 1
    terms = load_terms(path)
    if not terms:
        print(f"check_private_terms: skipped ({path} holds no terms)")
        return 0
    hits: list[str] = []
    files = [f for f in _git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0") if f]   # tracked + new, never ignored
    for f in files:
        hits += [f"(file name) {f}: {t}" for t in terms if t.lower() in f.lower()]
        p = ROOT / f
        if not p.is_file() or p.is_symlink():
            continue
        if p.stat().st_size > MAX_BYTES:
            print(f"check_private_terms: not scanned (over {MAX_BYTES // 1_000_000} MB): {f}")
            continue
        hits += find(terms, f, p.read_bytes().decode("utf-8", errors="replace"))
    stdin = sys.stdin.read() if "--pre-push" in argv and not sys.stdin.isatty() else None
    hits += find(terms, "(commit message)", pushed_messages(stdin))
    if hits:
        print(f"check_private_terms: {len(hits)} private term(s) found ({path.name}); remove them or edit the list:")
        print("\n".join(f"  {h}" for h in hits[:200]))
        return 1
    print(f"check_private_terms: no private terms in {len(files)} files (tracked or new) or unpushed commit messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
