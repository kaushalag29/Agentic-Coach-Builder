"""The Project vault: a folder of plain Markdown a graph viewer (Obsidian, Foam, Quartz, Logseq) can open (ADR-0020,
amendment 2026-11-05).

A generated, read-only view of what a Project remembers: one file per Note, Decision, Goal and Commitment, `[[links]]`
for the ties between them, tags in the frontmatter, and a hub note per scope. Nothing here is a viewer: the viewer
works out the graph from the links. SQLite stays the source of truth; every file is rebuilt from it, and an edit is
overwritten.

Layout (inside the Project folder, or wherever `vault build --out` says):

    vault/shared/      Goals, Commitments and Decisions the coaches of a Project share, each stamped with its coach
    vault/<coach>/     that coach's Notes and Check-ins; and everything else it keeps to itself (ADR-0019: the investor)
    vault/INDEX.md     the folders (a full build only)

Two ways to write it, one renderer:

* `sync_slice(store)` after a save: a coach writes what ADR-0019 lets it read (its own folder, the shared records
  its `readers()` name). It never reads or removes another coach's private files.
* `build(home, out)`, the person's command: reads the whole database through a READ-ONLY copy (the original is never
  opened, so nothing migrates, backs up or rewrites there) and writes every coach's folder.

A coach whose privacy is unknown (not in the installed registry) is treated as keeping everything to itself.
Holdings, positions and account data are never read here.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import notes_view as NV

VAULT_DIR = "vault"
SHARED = "shared"
HUB = "project"
INDEX_FILE = "INDEX.md"
GENERATED = NV.GENERATED
PLURAL = {"goal": "goals", "commitment": "commitments", "decision": "decisions"}
COLORS = {"note": 0x4C9BE8, "decision": 0xE8A24C, "goal": 0x58B368, "commitment": 0xB067D8, "hub": 0xE05A5A}
_SLUG = re.compile(r"[^a-z0-9]+")


class VaultError(Exception):
    pass


@dataclass
class Snapshot:
    """Everything the files are made of: rows as dicts, each carrying its `coach` stamp."""
    name: str
    owned: dict[str, tuple[str, ...]]                  # coach -> what it keeps to itself; a coach not here keeps all
    notes: list[dict] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    goals: list[dict] = field(default_factory=list)
    commitments: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    checkins: list[dict] = field(default_factory=list)
    profile: list[dict] = field(default_factory=list)  # {field, value, coach}
    readable: dict[str, set[str]] | None = None        # kind -> coaches whose files a slice may rewrite or remove


def _slug(text: str) -> str:
    return _SLUG.sub("-", str(text).lower()).strip("-")[:48].strip("-")


def _one(text: object, width: int = 90) -> str:
    return NV._oneline(text, width)


def keeps(owned: dict[str, tuple[str, ...]], coach: str, kind: str) -> bool:
    """Does `coach` keep records of `kind` (goal, commitment, decision, profile) to itself?"""
    o = owned.get(coach)
    return True if o is None else ("*" in o or PLURAL.get(kind, kind) in o)


def folder_of(snap: Snapshot, kind: str, coach: str) -> str:
    if kind in ("note", "checkin") or keeps(snap.owned, coach, kind):
        return _slug(coach) or "coach"
    return SHARED


def _title(kind: str, r: dict) -> str:
    return str(r.get("action") if kind == "commitment" else r.get("text") if kind != "note" else r["title"]).strip()


def _stem(kind: str, r: dict) -> str:
    s = _slug(_title(kind, r))
    return f"{r['id']}-{s}" if s else r["id"]


def _front(fields: dict, coach: str, kind: str) -> str:
    out = ["---"]
    for k, v in fields.items():
        if v not in (None, ""):
            out.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    out += [f"coach: {_slug(coach) or 'coach'}", f"kind: {kind}", f"tags: [kind/{kind}, coach/{_slug(coach) or 'coach'}]",
            "---"]
    return "\n".join(out)


class _View(NV._Notes):
    """The Notes renderers of notes_view, fed from a Snapshot and linking every record of the vault."""

    def __init__(self, notes: list[dict], links: list[dict], index: dict[str, dict]):
        self.notes = sorted(notes, key=lambda n: (n["created_at"], n["id"]))
        self.by_id = {n["id"]: n for n in self.notes}
        self.out: dict[str, list[tuple[str, str]]] = {}
        self.into: dict[str, list[tuple[str, str]]] = {}
        for ln in sorted(links, key=lambda ln: (ln.get("created_at") or "", ln["dst"], ln["type"])):
            self.out.setdefault(ln["src"], []).append((ln["dst"], ln["type"]))
            self.into.setdefault(ln["dst"], []).append((ln["src"], ln["type"]))
        self._index = index

    def title_of(self, rid: str) -> str | None:
        e = self._index.get(rid)
        return e["title"] if e else None

    def ref(self, rid: str) -> str:
        e = self._index.get(rid)
        return f"[[{e['stem']}]]" if e else f"`{rid}` (not in this vault)"


def _tag_note(text: str, coach: str) -> str:
    head, sep, rest = text.partition("\n---\n")           # the frontmatter ends at the first closing rule
    c = _slug(coach) or "coach"
    return f"{head}\ncoach: {c}\nkind: note\ntags: [kind/note, coach/{c}]{sep}{rest}"


def _mentions(view: _View, rid: str, kinds: tuple[str, ...] = ("about", "supports", "related")) -> list[str]:
    return [src for src, typ in view.into.get(rid, []) if typ in kinds and src in view.by_id]


def render(snap: Snapshot, full: bool = False) -> dict[str, str]:
    """relative path -> file text for everything the snapshot holds (and, for a full build, the top-level INDEX)."""
    kinds = {"goal": snap.goals, "commitment": snap.commitments, "decision": snap.decisions}
    index: dict[str, dict] = {}
    for n in snap.notes:
        index[n["id"]] = {"kind": "note", "coach": n["coach"], "title": n["title"], "stem": NV.stem(n),
                          "folder": folder_of(snap, "note", n["coach"])}
    for kind, rows in kinds.items():
        for r in rows:
            index[r["id"]] = {"kind": kind, "coach": r["coach"], "title": _title(kind, r), "stem": _stem(kind, r),
                              "folder": folder_of(snap, kind, r["coach"])}
    scopes = {e["folder"] for e in index.values() if e["kind"] != "note"}
    scopes |= {folder_of(snap, "profile", p["coach"]) for p in snap.profile}
    hub_stem = {s: (HUB if s == SHARED else f"{s}-home") for s in scopes}
    files: dict[str, str] = {}

    def put(folder: str, stem: str, text: str) -> None:
        files[f"{folder}/{stem}.md"] = text

    by_goal: dict[str, list[dict]] = {}
    for c in snap.commitments:
        if c.get("goal_id"):
            by_goal.setdefault(c["goal_id"], []).append(c)
    carried_to: dict[str, list[dict]] = {}
    for c in snap.commitments:
        if c.get("carried_from"):
            carried_to.setdefault(c["carried_from"], []).append(c)
    all_view = _View(snap.notes, snap.links, index)

    def ref(rid: str) -> str:
        return all_view.ref(rid)

    def hub_line(folder: str) -> str:
        return f"Part of [[{hub_stem[folder]}]]." if folder in hub_stem else ""

    for g in snap.goals:
        e = index[g["id"]]
        fm = _front({"id": g["id"], "title": e["title"], "status": g.get("status"), "target_date": g.get("target_date"),
                     "created": g.get("created_at")}, g["coach"], "goal")
        body = [GENERATED, "", f"# {e['title']}", "", hub_line(e["folder"]), ""]
        if g.get("measure"):
            body += [f"Measure: {g['measure']}", ""]
        if g.get("note"):
            body += [str(g["note"]), ""]
        cs = sorted(by_goal.get(g["id"], []), key=lambda c: (c["week"], c["id"]))
        if cs:
            body += ["## Commitments", ""] + [f"- {ref(c['id'])} ({c['week']}, {c['status']})" for c in cs] + [""]
        ns = _mentions(all_view, g["id"])
        if ns:
            body += ["## Notes about this", ""] + [f"- {ref(i)}" for i in ns] + [""]
        put(e["folder"], e["stem"], fm + "\n" + "\n".join(body).rstrip() + "\n")
    for c in snap.commitments:
        e = index[c["id"]]
        fm = _front({"id": c["id"], "title": e["title"], "week": c.get("week"), "status": c.get("status"),
                     "created": c.get("created_at"), "closed": c.get("closed_at")}, c["coach"], "commitment")
        body = [GENERATED, "", f"# {e['title']}", ""]
        for label, key in (("When", "cue"), ("Outcome", "outcome"), ("Result", "result_note")):
            if c.get(key):
                body.append(f"{label}: {c[key]}")
        body.append("")
        rel = []
        if c.get("goal_id"):
            rel.append(f"- goal {ref(c['goal_id'])}")
        if c.get("carried_from"):
            rel.append(f"- carried from {ref(c['carried_from'])}")
        rel += [f"- carried to {ref(x['id'])}" for x in sorted(carried_to.get(c["id"], []), key=lambda x: x["id"])]
        if rel:
            body += ["## Links", ""] + rel + [""]
        put(e["folder"], e["stem"], fm + "\n" + "\n".join(body).rstrip() + "\n")
    for d in snap.decisions:
        e = index[d["id"]]
        fm = _front({"id": d["id"], "title": e["title"], "decided": d.get("decided_at"),
                     "revisit_on": d.get("revisit_on")}, d["coach"], "decision")
        body = [GENERATED, "", f"# {e['title']}", "", str(d.get("reasoning") or ""), ""]    # no hub link: see below
        ns = _mentions(all_view, d["id"])
        if ns:
            body += ["## Notes about this", ""] + [f"- {ref(i)}" for i in ns] + [""]
        if d.get("citations"):
            body += ["## Cited", ""] + [f"- `{i}`" for i in d["citations"]] + [""]
        put(e["folder"], e["stem"], fm + "\n" + "\n".join(body).rstrip() + "\n")
    for coach in sorted({n["coach"] for n in snap.notes}):
        mine = [n for n in snap.notes if n["coach"] == coach]
        folder = folder_of(snap, "note", coach)
        view = _View(mine, [ln for ln in snap.links if ln["src"] in {n["id"] for n in mine}], index)
        for n in view.notes:
            put(folder, NV.stem(n), _tag_note(NV.render_note(view, n), coach))
        put(folder, "INDEX", NV.render_index(view))
        for q in sorted({NV._quarter(n["created_at"]) for n in mine}):
            put(folder, q, NV.render_quarter(view, q))
    for coach in sorted({k["coach"] for k in snap.checkins}):
        rows = sorted((k for k in snap.checkins if k["coach"] == coach), key=lambda k: (k["created_at"], k["id"]))
        c = _slug(coach) or "coach"
        lines = [GENERATED, "", f"# Check-ins ({coach})", ""] + [
            f"- {k['created_at'][:10]} ({k['week']}): {_one(k['summary'], 140)}" for k in rows]
        put(folder_of(snap, "checkin", coach), f"checkins-{c}",
            _front({"title": f"Check-ins ({coach})"}, coach, "checkin") + "\n" + "\n".join(lines) + "\n")
    for scope, stem in sorted(hub_stem.items()):
        def mine(kind: str, rows: list[dict]) -> list[dict]:
            return [r for r in rows if index[r["id"]]["folder"] == scope]
        goals, comms, decs = mine("goal", snap.goals), mine("commitment", snap.commitments), mine("decision", snap.decisions)
        prof = [p for p in snap.profile if folder_of(snap, "profile", p["coach"]) == scope]
        lines = [GENERATED, "", f"# {snap.name}" + ("" if scope == SHARED else f" ({scope})"), "",
                 "The Project's shared core." if scope == SHARED else f"What the {scope} coach keeps for this Project.", ""]
        if prof:
            lines += ["## Profile", ""] + [f"- {p['field']}: {p['value']}" for p in prof] + [""]
        lines += ["## Goals", ""] + ([f"- {ref(g['id'])}" for g in goals] or ["- none yet"]) + [""]
        # Only Goals are linked from the hub. Linking every Decision and open Commitment too made a star around the
        # hub that said nothing (19 of the 41 edges in a real Project); they are counted, and found in this folder.
        n_open = sum(1 for c in comms if c.get("status") == "open")
        lines += ["## In this folder", "",
                  f"{len(comms)} Commitment(s) ({n_open} open) and {len(decs)} Decision(s). They show up in the graph "
                  "through their links (a Commitment to its Goal, a Note to what it is about), not through this note.", ""]
        fm = _front({"title": snap.name}, scope, "hub")
        put(scope, stem, fm + "\n" + "\n".join(lines).rstrip() + "\n")
    if full and files:
        folders = sorted({p.split("/", 1)[0] for p in files})
        lines = [GENERATED, "", f"# {snap.name}: vault", "",
                 "Open this folder as a vault in Obsidian (or Foam, Quartz, Logseq). A read-only view of the Project's "
                 "memory: the coach rewrites these files, so edits are lost.", ""]
        for f in folders:
            n = sum(1 for p in files if p.startswith(f + "/"))
            hub = f"[[{hub_stem[f]}]]" if f in hub_stem else f"[{f}/INDEX]({f}/INDEX.md)" if f"{f}/INDEX.md" in files else f
            lines.append(f"- `{f}/`: {n} file(s); start at {hub}")
        files[INDEX_FILE] = "\n".join(lines) + "\n"
    return files


def graph_json() -> str:
    groups = [{"query": f"tag:#kind/{k}", "color": {"a": 1, "rgb": rgb}} for k, rgb in COLORS.items()]
    return json.dumps({"colorGroups": groups}, indent=2) + "\n"


def _front_of(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")[:1500]
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    out = {}
    for line in text[4:].split("\n---\n", 1)[0].splitlines():
        k, _, v = line.partition(": ")
        out[k] = v.strip().strip('"')
    return out


def _generated(path: Path) -> bool:
    try:
        return GENERATED in path.read_text(encoding="utf-8")[:2000]
    except OSError:
        return False


def write(root: Path, files: dict[str, str], readable: dict[str, set[str]] | None, own: str | None = None) -> dict:
    """Write the files that differ; remove generated files that no longer belong. With `readable` (a slice) only files
    of a kind and coach the writer may read, and anything generated in its own folder `own`, are removed; a person's
    own file (no generated marker) never is."""
    from .store import _atomic
    written = removed = 0
    for rel, text in files.items():
        path = root / rel
        try:
            if path.read_text(encoding="utf-8") == text:
                continue
        except OSError:
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic(path, text)
        written += 1
    if files:
        g = root / ".obsidian" / "graph.json"
        if not g.exists():                             # once: Obsidian rewrites this file itself
            g.parent.mkdir(parents=True, exist_ok=True)
            _atomic(g, graph_json())
    if root.exists():
        for p in sorted(root.rglob("*.md")):
            rel = p.relative_to(root).as_posix()
            if rel in files or not _generated(p):
                continue
            if readable is not None and rel.split("/", 1)[0] != own:
                fm = _front_of(p)
                if fm.get("coach") is None or fm.get("coach") not in readable.get(fm.get("kind", ""), set()):
                    continue
            p.unlink(missing_ok=True)
            removed += 1
        for d in sorted((x for x in root.rglob("*") if x.is_dir() and x.name != ".obsidian"), reverse=True):
            mds = [m for m in d.glob("*.md") if _generated(m)]
            if mds and all(_front_of(m).get("kind") == "hub" for m in mds) and not any(
                    m.suffix != ".md" or not _generated(m) for m in d.iterdir() if m.is_file()):
                for m in mds:                          # a hub with nothing left to point at (e.g. after forget)
                    m.unlink(missing_ok=True)
                    removed += 1
            if not any(d.iterdir()):
                d.rmdir()
    return {"files": len(files), "written": written, "removed": removed}


# ---- a coach after a save: only what it may read ---------------------------------------------------------------

def from_store(store) -> Snapshot:
    from . import product
    me = store.coach
    owned = {me: tuple(store.owned), **{p: tuple(o) for p, o in store._peer_map().items()}}

    def rows(sql: str, shared: str | None = None) -> list[dict]:
        out = store._rows(sql, shared=shared)
        for r in out:
            r.setdefault("coach", me)
        return out

    keep_notes = product.has("notes")
    snap = Snapshot(name=_project_name(store.home), owned=owned)
    own = "WHERE founder_id=? AND coach=?"
    if keep_notes:
        snap.notes = rows(f"SELECT * FROM notes {own} ORDER BY created_at, id")
        snap.links = rows(f"SELECT src, dst, type, created_at FROM links {own}")
    snap.goals = rows(f"SELECT * FROM goals {own} ORDER BY created_at, id", shared="goals")
    snap.commitments = rows(f"SELECT * FROM commitments {own} ORDER BY week, created_at, id", shared="commitments")
    snap.decisions = rows(f"SELECT * FROM decisions {own} ORDER BY decided_at, id", shared="decisions")
    if product.has("checkins"):
        snap.checkins = rows(f"SELECT * FROM checkins {own} ORDER BY created_at, id")
    snap.profile = [{"field": f, "value": v["value"], "coach": me} for f, v in store.profile().items()]
    snap.readable = {"note": {me}, "checkin": {me}, "hub": {me},
                     **{k: set(store.readers(PLURAL[k])) for k in PLURAL}}
    return snap


def sync_slice(store) -> dict:
    """After a save: refresh the part of the vault this coach may read. Best effort (the caller never fails a save)."""
    snap = from_store(store)
    return write(store.home / VAULT_DIR, render(snap), snap.readable, _slug(store.coach) or "coach")


def clear(store) -> dict:
    snap = Snapshot(name=_project_name(store.home), owned={}, readable={
        "note": {store.coach}, "checkin": {store.coach}, "hub": {store.coach},
        **{k: set(store.readers(PLURAL[k])) for k in PLURAL}})
    return write(store.home / VAULT_DIR, {}, snap.readable, _slug(store.coach) or "coach")


def _project_name(home: Path) -> str:
    try:
        data = json.loads((home / "project.json").read_text())
        if isinstance(data, dict) and data.get("name"):
            return str(data["name"])
    except (OSError, ValueError):
        pass
    return home.name


# ---- the person's command: every coach, from a read-only copy ----------------------------------------------------

def _decode(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("citations", "evidence", "wins", "blockers"):
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    d.pop("founder_id", None)
    d["coach"] = d.get("coach") or "founder"
    return d


def registry(engine_home: Path | None) -> dict[str, tuple[str, ...]]:
    """pack -> what it keeps to itself, from the installed coaches' registry files."""
    out: dict[str, tuple[str, ...]] = {}
    if engine_home is None:
        return out
    for f in sorted((engine_home / "installed").glob("*.json")):
        try:
            e = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(e.get("pack"), str) and e["pack"]:
            out[e["pack"]] = tuple(str(x) for x in (e.get("owned") or []) if isinstance(x, str))
    return out


def from_db_file(db: Path, engine_home: Path | None) -> Snapshot:
    """Every coach's records, read from a COPY of the database in a scratch folder: the original (and its -wal and
    -shm) is only ever read as bytes. A copy taken while a coach writes may miss the last change; build again."""
    from .store import SCHEMA_VERSION
    if not db.is_file():
        raise VaultError(f"no coach database at {db}")
    with tempfile.TemporaryDirectory(prefix="vault-read-") as tmp:
        dst = Path(tmp) / "read.db"
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(db) + suffix)
            if src.is_file():
                shutil.copyfile(src, Path(str(dst) + suffix))
        con = sqlite3.connect(dst)
        con.row_factory = sqlite3.Row
        try:
            try:
                ver = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                ver = int(ver[0]) if ver else 0
            except sqlite3.Error as e:
                raise VaultError(f"{db} is not a coach database ({e})") from e
            if ver > SCHEMA_VERSION:
                raise VaultError(f"{db} is from a newer coach (schema {ver}); update this coach first")
            if ver < 7:
                raise VaultError(f"{db} is from an older coach (schema {ver}); open the Project once with its coach "
                                 "so it migrates, then build again. Nothing was changed.")

            def all_(table: str, order: str) -> list[dict]:
                return [_decode(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY {order}")]
            snap = Snapshot(name=_project_name(db.parent), owned=registry(engine_home))
            snap.notes = all_("notes", "created_at, id")
            snap.links = all_("links", "created_at, dst")
            snap.goals = all_("goals", "created_at, id")
            snap.commitments = all_("commitments", "week, created_at, id")
            snap.decisions = all_("decisions", "decided_at, id")
            snap.checkins = all_("checkins", "created_at, id")
            snap.profile = [{"field": r["field"], "value": r["value"], "coach": r["coach"] or "founder"}
                            for r in con.execute("SELECT field, value, coach FROM profile_facts "
                                                 "WHERE superseded_at IS NULL ORDER BY field")]
            return snap
        finally:
            con.close()


def build(home: Path, out: Path | None = None, engine_home: Path | None = None) -> dict:
    """The full vault of the Project in `home` (a folder holding founder.db), written to `out` (default
    <home>/vault). Reads a copy of the database; writes only inside `out`."""
    snap = from_db_file(Path(home) / "founder.db", engine_home)
    root = Path(out) if out else Path(home) / VAULT_DIR
    res = write(root, render(snap, full=True), None)
    res["path"] = str(root)
    return res
