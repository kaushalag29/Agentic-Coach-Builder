"""Derived views of a Project's Notes (ADR-0020): an INDEX.md that is read first, a sub-index per quarter and one
file per Note, written beside the store; and a lint that reports what needs a person's attention.

Everything here is generated from the store and can be deleted and rebuilt (`<coach> notes rebuild`). Nothing here
changes a record: the vault is read-only for the person (edits are overwritten), and the lint only reports.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import domain as D

VAULT_DIR = "notes"
INDEX_FILE = "INDEX.md"
INDEX_MAX_LINES = 200          # the index is read whole, so it has a ceiling (sections are capped, with a pointer)
INDEX_NEWEST = 15
INDEX_DUE = 15
INDEX_QUARTERS = 12
INDEX_LINKED = 10
GENERATED = "<!-- Generated from the coach's store. Edits are overwritten: change a Note through the coach. -->"
_SLUG = re.compile(r"[^a-z0-9]+")
_VAULT_FILE = re.compile(r"^(INDEX|\d{4}-Q[1-4]|n-[0-9a-f]{4}(-[a-z0-9-]*)?)\.md$")


def vault_path(store) -> Path:
    return store.home / store.vault_dir


def _slug(title: str) -> str:
    return _SLUG.sub("-", title.lower()).strip("-")[:48].strip("-")


def stem(note: dict) -> str:
    """A Note's file name without .md: its id and a short slug of its title."""
    s = _slug(note["title"])
    return f"{note['id']}-{s}" if s else note["id"]


def _quarter(created_at: str) -> str:
    d = dt.date.fromisoformat(created_at[:10])
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def _oneline(text: str, width: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width - 1].rstrip() + "…"


class _Notes:
    """Everything the views need, read once: the Notes (oldest first), their links both ways, and a title for any
    record id a Note links to."""

    def __init__(self, store):
        self.store = store
        with store._lock:
            self.notes = store._rows("SELECT * FROM notes WHERE founder_id=? AND coach=? ORDER BY created_at, id")
            rows = store.db.execute("SELECT src, dst, type FROM links WHERE founder_id=? AND coach=? "
                                    "ORDER BY created_at, dst", (store.fid, store.coach)).fetchall()
        self.by_id = {n["id"]: n for n in self.notes}
        self.out: dict[str, list[tuple[str, str]]] = {}
        self.into: dict[str, list[tuple[str, str]]] = {}
        for r in rows:
            self.out.setdefault(r["src"], []).append((r["dst"], r["type"]))
            self.into.setdefault(r["dst"], []).append((r["src"], r["type"]))
        self._titles: dict[str, str | None] = {}

    def title_of(self, rid: str) -> str | None:
        """The text of any record (None when it doesn't exist): a Note's title, else the record's own words."""
        if rid in self.by_id:
            return self.by_id[rid]["title"]
        if rid not in self._titles:
            rec = self.store.get(rid)
            self._titles[rid] = None if rec is None else str(
                rec.get("text") or rec.get("action") or rec.get("summary") or rid)
        return self._titles[rid]

    def ref(self, rid: str) -> str:
        """A link as text: `[[file]]` for a Note (the vault links), else the id and the record's words."""
        if rid in self.by_id:
            return f"[[{stem(self.by_id[rid])}]]"
        title = self.title_of(rid)
        return f"`{rid}` {_oneline(title, 60)}" if title else f"`{rid}` (no longer exists)"

    def active(self) -> list[dict]:
        return [n for n in self.notes if not n.get("superseded_by")]


def render_note(v: _Notes, note: dict) -> str:
    fm = ["---", f"id: {note['id']}", f"title: {json.dumps(note['title'], ensure_ascii=False)}",
          f"type: {note['type']}", f"origin: {note['origin']}", f"created: {note['created_at']}"]
    if note.get("revisit_on"):
        fm.append(f"revisit_on: {note['revisit_on']}")
    if note.get("superseded_by"):
        fm += [f"superseded_by: {note['superseded_by']}", f"superseded_at: {note['superseded_at']}"]
    fm.append("---")
    body = [GENERATED, "", f"# {note['title']}", ""]
    if note["origin"] == "coach":
        body += ["_The coach's own conclusion: a lead to check, not something the person said._", ""]
    if note.get("superseded_by"):
        body += [f"_Superseded on {note['superseded_at'][:10]} by {v.ref(note['superseded_by'])}._", ""]
    body += [note["summary"], ""]
    links = v.out.get(note["id"], [])
    back = [(s, t) for s, t in v.into.get(note["id"], []) if s in v.by_id]
    if links or back:
        body += ["## Links", ""]
        body += [f"- {t} {v.ref(d)}" for d, t in links]
        body += [f"- {t} by {v.ref(s)}" for s, t in back]
        body.append("")
    if note.get("evidence"):
        body += ["## Cited", ""]
        for e in note["evidence"]:
            label = e.get("title") or e["id"]
            label = f"[{label}]({e['deep_link']})" if e.get("deep_link") else label
            body.append(f"- {label}" + (f": “{_oneline(e['quote'], D.NOTE_QUOTE_MAX)}”" if e.get("quote") else ""))
        body.append("")
    return "\n".join(fm + body)


def _line(v: _Notes, n: dict, summary: bool = False) -> str:
    mark = " (coach's conclusion)" if n["origin"] == "coach" else ""
    sup = f" (superseded by {n['superseded_by']})" if n.get("superseded_by") else ""
    rev = f" (revisit {n['revisit_on']})" if n.get("revisit_on") and not n.get("superseded_by") else ""
    link = f"[{_oneline(n['title'], 80)}]({stem(n)}.md)"
    out = f"- `{n['id']}` {n['created_at'][:10]} {n['type']}: {link}{mark}{rev}{sup}"
    return out + (f" — {_oneline(n['summary'], 100)}" if summary else "")


def render_quarter(v: _Notes, quarter: str) -> str:
    notes = [n for n in v.notes if _quarter(n["created_at"]) == quarter]
    lines = [GENERATED, "", f"# Notes, {quarter}", "", f"{len(notes)} Note(s), oldest first. [Index]({INDEX_FILE})", ""]
    lines += [_line(v, n, summary=True) for n in notes]
    return "\n".join(lines) + "\n"


def render_index(v: _Notes) -> str:
    """The catalogue read first: what is due, the newest Notes, where the rest are, and what the Notes are about.
    Every section is capped so the whole stays under INDEX_MAX_LINES; a capped section says how to reach the rest."""
    active, total = v.active(), len(v.notes)
    L: list[str] = [GENERATED, "", "# Notes index", "",
                    f"{len(active)} current Note(s)" + (f", {total - len(active)} superseded" if total > len(active) else "")
                    + ". Search the rest with `coach_recall`; read one whole with its id.", ""]
    # the index never depends on today's date, so it only changes when a record does (lint compares it to the store)
    due = sorted((n for n in active if n.get("revisit_on")), key=lambda n: (n["revisit_on"], n["id"]))
    if due:
        L += ["## To revisit", ""]
        L += [f"- `{n['id']}` by {n['revisit_on']}: [{_oneline(n['title'], 80)}]({stem(n)}.md)" for n in due[:INDEX_DUE]]
        if len(due) > INDEX_DUE:
            L.append(f"- … and {len(due) - INDEX_DUE} more")
        L.append("")
    L += ["## Newest", ""]
    newest = list(reversed(active))[:INDEX_NEWEST]
    L += [_line(v, n) for n in newest] or ["_None yet._"]
    if len(active) > INDEX_NEWEST:
        L.append(f"- … {len(active) - INDEX_NEWEST} older: see the quarters below")
    L.append("")
    quarters: dict[str, list[dict]] = {}
    for n in v.notes:
        quarters.setdefault(_quarter(n["created_at"]), []).append(n)
    if quarters:
        L += ["## By quarter", ""]
        for q in sorted(quarters, reverse=True)[:INDEX_QUARTERS]:
            kinds = {t: sum(1 for n in quarters[q] if n["type"] == t) for t in D.NOTE_TYPES}
            L.append(f"- [{q}]({q}.md): {len(quarters[q])} Note(s) ("
                     + ", ".join(f"{t} {c}" for t, c in kinds.items() if c) + ")")
        if len(quarters) > INDEX_QUARTERS:
            L.append(f"- … {len(quarters) - INDEX_QUARTERS} earlier quarters in the vault folder")
        L.append("")
    about: dict[str, list[str]] = {}
    for n in active:
        for dst, typ in v.out.get(n["id"], []):
            if typ == "about":
                about.setdefault(dst, []).append(n["id"])
    if about:
        L += ["## What the Notes are about", ""]
        ranked = sorted(about.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        for rid, ids in ranked[:INDEX_LINKED]:
            shown = ", ".join(f"`{i}`" for i in ids[:4]) + (f" +{len(ids) - 4}" if len(ids) > 4 else "")
            L.append(f"- {v.ref(rid)}: {len(ids)} Note(s) ({shown})")
        if len(ranked) > INDEX_LINKED:
            L.append(f"- … {len(ranked) - INDEX_LINKED} more records have Notes")
        L.append("")
    lines = L[:INDEX_MAX_LINES]          # a ceiling, not a design: the caps above keep it far below
    return "\n".join(lines).rstrip() + "\n"


def index_text(store) -> str:
    v = _Notes(store)
    return render_index(v) if v.notes else "# Notes index\n\n_No Notes yet._\n"


def render_all(store) -> dict[str, str]:
    """file name -> content for the whole vault."""
    v = _Notes(store)
    if not v.notes:
        return {}
    files = {INDEX_FILE: render_index(v)}
    for q in {_quarter(n["created_at"]) for n in v.notes}:
        files[f"{q}.md"] = render_quarter(v, q)
    for n in v.notes:
        files[f"{stem(n)}.md"] = render_note(v, n)
    return files


def sync_vault(store, files: dict[str, str] | None = None) -> dict:
    """Write the vault so it matches the store: new and changed files written, generated files that no longer belong
    removed (a file the person put there is never touched). Returns {"written": n, "removed": n, "files": n}."""
    from .store import _atomic
    files = render_all(store) if files is None else files
    folder = vault_path(store)
    written = removed = 0
    if files:
        folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = folder / name
        try:
            same = path.read_text(encoding="utf-8") == text
        except OSError:
            same = False
        if not same:
            _atomic(path, text)
            written += 1
    if folder.exists():
        for p in folder.iterdir():
            if p.is_file() and _VAULT_FILE.match(p.name) and p.name not in files:
                p.unlink(missing_ok=True)
                removed += 1
        if not files and not any(folder.iterdir()):
            folder.rmdir()
    return {"written": written, "removed": removed, "files": len(files)}


def clear_vault(store) -> int:
    return sync_vault(store, {})["removed"]


def lint(store) -> list[dict]:
    """What needs a person's attention, most important first: [{check, severity, ids, message}]. Report-only: it
    changes nothing, not even the derived files (`notes rebuild` does that)."""
    v = _Notes(store)
    out: list[dict] = []
    today = store.today().isoformat()

    def add(check: str, severity: str, ids: list[str], message: str) -> None:
        out.append({"check": check, "severity": severity, "ids": ids, "message": message})

    due = [n for n in v.active() if n.get("revisit_on") and n["revisit_on"] <= today]
    if due:
        add("revisit_due", "warn", [n["id"] for n in due],
            f"{len(due)} Note(s) are past their revisit date: " + "; ".join(
                f"{n['id']} {_oneline(n['title'], 50)} (by {n['revisit_on']})" for n in due[:5])
            + ". Read each and decide: still true, supersede it, or set a new date.")
    broken = [(s, d) for s, outs in v.out.items() for d, _ in outs if v.title_of(d) is None]
    broken += [(s, "?") for s in v.out if s not in v.by_id]
    if broken:
        add("dangling_link", "warn", sorted({s for s, _ in broken}),
            f"{len(broken)} link(s) point at a record that no longer exists: "
            + ", ".join(f"{s} → {d}" for s, d in broken[:5]))
    seen: dict[str, list[dict]] = {}
    for n in v.active():
        seen.setdefault(re.sub(r"[^a-z0-9]+", " ", n["title"].lower()).strip(), []).append(n)
    dup = [ns for ns in seen.values() if len(ns) > 1]
    if dup:
        add("duplicate_title", "warn", [n["id"] for ns in dup for n in ns],
            f"{len(dup)} title(s) are used by more than one current Note: "
            + "; ".join(" / ".join(n["id"] for n in ns) + f" “{_oneline(ns[0]['title'], 40)}”" for ns in dup[:3])
            + ". Likely one should supersede the other.")
    lone = [n for n in v.active() if not v.out.get(n["id"]) and not v.into.get(n["id"])]
    if lone:
        add("unlinked", "info", [n["id"] for n in lone],
            f"{len(lone)} current Note(s) link to nothing and nothing links to them; linking a Note to the Goal or "
            "Decision it is about makes it findable by what it is for.")
    leads = [n for n in v.active() if n["origin"] == "coach"]
    if leads:
        add("coach_conclusions", "info", [n["id"] for n in leads],
            f"{len(leads)} current Note(s) are the coach's own conclusions, not things the person said: confirm or "
            "supersede the ones that matter.")
    if store.has_fts():
        with store._lock:
            indexed = store.db.execute("SELECT COUNT(*) FROM notes_fts").fetchone()[0]
        if indexed != len(v.notes):
            add("index_drift", "warn", [], f"the search index holds {indexed} Note(s) but the store has "
                f"{len(v.notes)}: run `{_cmd()} notes rebuild`.")
    want = render_all(store)
    folder = vault_path(store)
    have = {p.name for p in folder.iterdir() if p.is_file() and _VAULT_FILE.match(p.name)} if folder.exists() else set()
    stale = [name for name in want if not (folder / name).exists()
             or (folder / name).read_text(encoding="utf-8") != want[name]]
    extra = sorted(have - set(want))
    if stale or extra:
        add("vault_drift", "warn", [], f"the notes folder is out of date ({len(stale)} file(s) missing or changed, "
            f"{len(extra)} left over): run `{_cmd()} notes rebuild`.")
    order = {"warn": 0, "info": 1}
    return sorted(out, key=lambda f: order[f["severity"]])


def _cmd() -> str:
    from . import product
    return product.ID
