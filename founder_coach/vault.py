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

import datetime as dt
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
META = "_meta"
HOME = "home"
INDEX_FILE = "INDEX.md"
GENERATED = NV.GENERATED
PLURAL = {"goal": "goals", "commitment": "commitments", "decision": "decisions", "person": "people",
          "issue": "issues"}
SUBFOLDER = {"goal": "goals", "thread": "threads", "decision": "decisions", "note": "notes", "checkin": "checkins",
             "week": "weeks", "person": "people", "issue": "issues"}
COLORS = {"goal": 0x58B368, "thread": 0xB067D8, "decision": 0xE8A24C, "note": 0x4C9BE8, "checkin": 0xE8D44C,
          "person": 0xE06C9F, "issue": 0xE05A5A, "week": 0x9A9A9A}
# the typed links each kind's page writes (frontmatter properties; the INLINE ones also as inline fields the core graph
# draws). `mentions` stays a property only: a name in many records would make every Person a hub.
OUT_TYPES = {
    "goal": ("sub_goal_of", "owned_by"),
    "thread": ("serves", "reviewed_in", "owned_by", "assumes"),
    "decision": ("decided_in", "supersedes", "related", "serves", "changes_scope_of", "led_to", "assumes",
                 "decided_by"),
    "note": ("about", "supports", "related", "contradicts", "supersedes"),
    "checkin": ("reviewed_in",),
    "issue": ("blocks", "resolved_by", "owned_by", "serves"),
    "person": (),
}
INCOMING = {
    "goal": (("Served by", ("serves",), ("thread", "decision", "issue")), ("Blocked by", ("blocks",), ("issue",)),
             ("Scope changed by", ("changes_scope_of",), ("decision",)), ("Sub-goals", ("sub_goal_of",), ("goal",)),
             ("Led to by", ("led_to",), ("decision",))),
    "thread": (("Blocked by", ("blocks",), ("issue",)), ("Led to by", ("led_to",), ("decision",))),
    "decision": (("Superseded by", ("supersedes",), ("decision",)), ("Led to by", ("led_to",), ("decision",)),
                 ("Resolves", ("resolved_by",), ("issue",))),
    "issue": (),
    "person": (("Owns", ("owned_by",), ("thread", "issue", "goal")), ("Decided", ("decided_by",), ("decision",)),
               ("Mentioned in", ("mentions",), ("goal", "thread", "decision", "issue"))),
}
GRAPH_SEARCH = f"-path:{META}"
NAME_MAX = 40
_SLUG = re.compile(r"[^a-z0-9]+")
_BAD_NAME = re.compile(r'[\[\]|#^\\/:*?"<>\n\r\t]+')


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
    people: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)  # change-log rows of the Decisions (ADR-0025)
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
    """The scope folder of a record: `shared`, or its coach's own folder (Notes and Check-ins always; any kind the
    coach keeps to itself)."""
    if kind in ("note", "checkin") or keeps(snap.owned, coach, "commitment" if kind == "thread" else kind):
        return _slug(coach) or "coach"
    return SHARED


_LEAD_NOTE = re.compile(r"^\s*\[[^\]]*\]\s*")          # "[Superseded 25 Oct by ...] MVP scope = ..."
_TAIL_WORDS = {"a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "by", "with", "from", "is", "are",
               "was", "as", "that", "than", "into", "plus", "then", "but", "about", "each", "his", "her", "their",
               "our", "its", "=", "&", "-", "–"}


def short_name(title: str) -> str:
    """A file name a person can read in the graph: the title without a leading [note], cut at a word under NAME_MAX
    characters, never ending on a dangling word ("for", "the") or an unclosed bracket."""
    raw = str(title)
    rest = _LEAD_NOTE.sub("", raw)
    t = " ".join(_BAD_NAME.sub(" ", rest if rest.strip() else raw).split()).strip(" .")
    if len(t) > NAME_MAX:
        cut = t[:NAME_MAX + 1].rsplit(" ", 1)[0].rstrip(" ,;-.")
        if cut.count("(") > cut.count(")"):
            cut = cut[:cut.rindex("(")].rstrip(" ,;-.")
        words = cut.split(" ")
        while len(words) > 2 and words[-1].lower() in _TAIL_WORDS:
            words.pop()
        cut = " ".join(words).rstrip(" ,;-.")
        t = cut if len(cut) >= NAME_MAX // 2 else t[:NAME_MAX].rstrip()
    return t or "untitled"


def _front(fields: dict, coach: str, kind: str) -> str:
    out = ["---"]
    for k, v in fields.items():
        if v not in (None, "", []):
            out.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    c = coach if coach == SHARED else (_slug(coach) or "coach")
    out += [f"coach: {c}", f"kind: {kind}", f"tags: [kind/{kind}, coach/{c}]", "---"]
    return "\n".join(out)


class _Layout:
    """Where every node of the graph lives, and the file name it gets. Names are unique inside a folder; links carry
    the folder (`[[shared/goals/Ten partners|Ten partners]]`), so two folders may hold the same name. A shared folder is
    named from shared records only, so every coach that writes it names it the same way."""

    def __init__(self, snap: Snapshot, g):
        self.g = g
        self.scope: dict[str, str] = {}
        for n in g.nodes.values():
            if n.kind in ("goal", "decision", "thread", "note", "checkin", "person", "issue"):
                self.scope[n.id] = folder_of(snap, n.kind, n.coach or "founder")
        # week pages: the shared folder holds every week from its first to its last record (a continuous spine);
        # a private folder holds the weeks of its own records
        self.weeks: dict[str, set[str]] = {}
        for nid, sc in self.scope.items():
            if g.nodes[nid].kind == "checkin":
                continue
            for nxt, e, way in g.steps(nid, ("decided_in", "reviewed_in")):
                self.weeks.setdefault(sc, set()).add(nxt)
        if self.weeks.get(SHARED):
            ws = sorted(self.weeks[SHARED])
            from .store import next_week
            w, span = ws[0], set()
            while w <= ws[-1] and len(span) < 520:
                span.add(w)
                w = next_week(w)
            self.weeks[SHARED] = span
        for nid, sc in self.scope.items():                   # a Check-in hangs on the shared spine when it can
            if g.nodes[nid].kind == "checkin":
                for nxt, e, way in g.steps(nid, ("reviewed_in",)):
                    if nxt not in self.weeks.get(SHARED, set()):
                        self.weeks.setdefault(sc, set()).add(nxt)
        self.name: dict[tuple[str, str], str] = {}           # (folder, node id) -> name
        by_folder: dict[str, list[str]] = {}
        for nid, sc in self.scope.items():
            by_folder.setdefault(f"{sc}/{SUBFOLDER[g.nodes[nid].kind]}", []).append(nid)
        for folder, nids in sorted(by_folder.items()):
            taken: set[str] = set()
            for nid in sorted(nids, key=lambda i: (g.nodes[i].date, i)):
                n = g.nodes[nid]
                base = short_name(n.title)
                name = base
                for alt in (f"{base} ({n.date})" if n.date else None, f"{base} ({nid})"):
                    if name.lower() not in taken:
                        break
                    name = alt or name
                taken.add(name.lower())
                self.name[(folder, nid)] = name
        for sc, ws in self.weeks.items():
            for w in ws:
                self.name[(f"{sc}/weeks", w)] = w

    def folder(self, nid: str, scope: str | None = None) -> str:
        n = self.g.nodes[nid]
        if n.kind == "week":
            return f"{scope}/weeks"
        return f"{self.scope[nid]}/{SUBFOLDER[n.kind]}"

    def week_scope(self, week: str, scope: str) -> str | None:
        if week in self.weeks.get(scope, set()):
            return scope
        if week in self.weeks.get(SHARED, set()):
            return SHARED
        return None

    def link(self, nid: str, scope: str | None = None) -> str | None:
        """`[[folder/name|name]]` for a node seen from `scope`, or None when it has no page."""
        if nid not in self.g.nodes:
            return None
        if self.g.nodes[nid].kind == "week":
            sc = self.week_scope(nid, scope or SHARED)
            if sc is None:
                return None
            folder = f"{sc}/weeks"
        elif nid in self.scope:
            folder = self.folder(nid)
        else:
            return None
        name = self.name[(folder, nid)]
        return f"[[{folder}/{name}|{name}]]"

    def path(self, nid: str, scope: str | None = None) -> str:
        folder = self.folder(nid, scope)
        return f"{folder}/{self.name[(folder, nid)]}.md"


def _typed(lay: _Layout, nid: str, scope: str, types: tuple[str, ...]) -> dict[str, list[str]]:
    """Outgoing typed edges of a node as links, by type (only ends that have a page)."""
    out: dict[str, list[str]] = {}
    for e in lay.g.out.get(nid, []):
        if e.type in types:
            ln = lay.link(e.dst, scope)
            if ln and ln not in out.setdefault(e.type, []):
                out[e.type].append(ln)
    return {k: v for k, v in out.items() if v}


def _inline(edges: dict[str, list[str]]) -> list[str]:
    """Inline fields (`serves:: [[...]]`): plain links the core graph draws, typed for plugins that read them."""
    return [f"{t}:: {', '.join(v)}" for t, v in edges.items()]


def _incoming(lay: _Layout, nid: str, scope: str, title: str, types: tuple[str, ...], kinds: tuple[str, ...]) -> list[str]:
    """A section listing what points at `nid`, limited to records of the same scope: a shared page never names a
    private record (each coach writing the shared folder writes the same page)."""
    rows = []
    for e in sorted(lay.g.into.get(nid, []), key=lambda e: (lay.g.nodes[e.src].date, e.src)):
        src = lay.g.nodes[e.src]
        if e.type in types and src.kind in kinds and lay.scope.get(e.src) == scope:
            ln = lay.link(e.src, scope)
            if ln:
                quiet = src.status in (None, "accepted", "active")      # say a status only when it tells something
                rows.append(f"- {ln}" + ("" if quiet else f" ({src.status})"))
    return ([f"## {title}", ""] + rows + [""]) if rows else []


def _profile_lines(field: str, value) -> list[str]:
    """A profile fact as bullets: a dict (key metrics) as one sub-bullet per key, never raw JSON."""
    v = _loads(value)
    if isinstance(v, dict):
        return [f"- {field}:"] + [f"    - {k}: {x}" for k, x in v.items()]
    if isinstance(v, list):
        return [f"- {field}: " + "; ".join(str(x) for x in v)]
    return [f"- {field}: {v}"]


def _loads(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def _history(lay: _Layout, snap: Snapshot, nid: str, scope: str) -> list[str]:
    """A Decision's change log as a table: when, what, why and by whom (ADR-0025: nothing about a change is lost)."""
    from . import graph as G
    rows = [c for c in snap.history if c.get("entity_id") == nid]
    if not rows:
        return []
    out = ["## History", "", "| When | What | Why | By |", "|---|---|---|---|"]
    for c in sorted(rows, key=lambda c: c.get("seq") or 0):
        before, after = (_loads(c.get(k)) for k in ("before", "after"))
        if c["op"] == "create":
            what = "decided"
        elif c["op"] == "supersede":
            new = (after or {}).get("superseded_by") if isinstance(after, dict) else None
            what = "superseded" + (f" by {lay.link(new, scope) or new}" if new else "")
        else:
            d = G.diff(before, after)
            what = "; ".join(f"{k}: {_one(v[0], 60)} → {_one(v[1], 60)}" for k, v in d.items()) or c["op"]
        actor = c.get("actor")
        who = ("the person (they said so)" if actor == "self" else "not recorded" if actor in (None, "", "me")
               else (lay.link(actor, scope) or actor))
        cell = lambda x: str(x or "").replace("|", "/").replace("\n", " ")       # noqa: E731
        why = c.get("reason") or ("" if c["op"] == "create" else "not recorded")
        out.append(f"| {str(c.get('at') or '')[:10]} | {cell(what)} | {cell(why)} | {cell(who)} |")
    return out + [""]


def render(snap: Snapshot, full: bool = False, with_html: bool = False) -> dict[str, str]:
    """relative path -> file text for everything the snapshot holds (and, for a full build, the top-level index, and
    with `with_html` the offline graph page)."""
    from . import graph as G
    from .store import week_start
    g = G.build(snap)
    lay = _Layout(snap, g)
    files: dict[str, str] = {}

    def put(rel: str, fm: str, body: list[str]) -> None:
        files[rel] = fm + "\n" + "\n".join(body).rstrip() + "\n"

    for nid, scope in sorted(lay.scope.items()):
        n = g.nodes[nid]
        aliases = [nid]
        if n.kind == "goal":
            r = n.data["row"]
            typed = _typed(lay, nid, scope, OUT_TYPES["goal"])
            fm = _front({"id": nid, "title": n.title, "aliases": aliases, "status": r.get("status"),
                         "target_date": r.get("target_date"), "created": r.get("created_at"),
                         "start": (r.get("created_at") or "")[:10], "end": r.get("target_date"), **typed},
                        n.coach, "goal")
            body = [GENERATED, "", f"# {n.title}", ""]
            if r.get("measure"):
                body += [f"Measure: {r['measure']}", ""]
            if r.get("note"):
                body += [str(r["note"]), ""]
            body += _inline(typed) + ([""] if typed else [])
            for title, types, kinds in INCOMING["goal"]:
                body += _incoming(lay, nid, scope, title, types, kinds)
        elif n.kind == "thread":
            rows = n.data["rows"]
            aliases = [c["id"] for c in rows]
            typed = _typed(lay, nid, scope, OUT_TYPES["thread"])
            goal = g.nodes.get(n.data["goal_id"]) if n.data["goal_id"] else None
            weeks = n.data["weeks"]
            live = n.data["live"]
            last = live[-1]
            fm = _front({"id": nid, "title": n.title, "aliases": aliases, "status": n.status,
                         "periods": len(live), "first_week": weeks[0] if weeks else None,
                         "last_week": weeks[-1] if weeks else None,
                         "goal": typed.get("serves", [None])[0], "serves": typed.get("serves"),
                         "reviewed_in": typed.get("reviewed_in"),
                         "start": week_start(weeks[0]).isoformat() if weeks else None,
                         "end": ((last.get("closed_at") or "")[:10] or (week_start(weeks[-1]).isoformat()
                                                                         if weeks else None)),
                         "group": goal.title if goal else None,
                         **{k: v for k, v in typed.items() if k not in ("serves", "reviewed_in")},
                         "mentions": _typed(lay, nid, scope, ("mentions",)).get("mentions")}, n.coach, "thread")
            body = [GENERATED, "", f"# {n.title}", ""]
            for label, key in (("When", "cue"), ("Outcome", "outcome")):
                if last.get(key):
                    body.append(f"{label}: {last[key]}")
            body += ["", *_inline({k: v for k, v in typed.items() if k != "reviewed_in"}), "", "## History", "",
                     "| Week | Status | Result | Row |", "|---|---|---|---|"]
            live_ids = {c["id"] for c in live}
            for c in rows:
                wk = lay.link(c["week"], scope) if c.get("week") else ""
                st = (c.get("status") or "") + ("" if c["id"] in live_ids else " (an undone carry)")
                body.append(f"| {wk or c.get('week') or ''} | {st} | "
                            f"{_one(c.get('result_note') or '', 80).replace('|', '/')} | `{c['id']}` |")
            body.append("")
            for title, types, kinds in INCOMING["thread"]:
                body += _incoming(lay, nid, scope, title, types, kinds)
        elif n.kind == "decision":
            r = n.data["row"]
            typed = _typed(lay, nid, scope, OUT_TYPES["decision"])
            status = r.get("status") or "accepted"
            fm = _front({"id": nid, "title": n.title, "aliases": aliases, "status": status,
                         "decided": r.get("decided_at"),
                         "week": typed.get("decided_in", [None])[0], **typed,
                         "superseded_at": r.get("superseded_at"),
                         "mentions": _typed(lay, nid, scope, ("mentions",)).get("mentions"),
                         "revisit_on": r.get("revisit_on"), "start": n.date or None,
                         "end": (r.get("superseded_at") or "")[:10] or None,
                         "citations": G._cites(r)}, n.coach, "decision")
            body = [GENERATED, "", f"# {n.title}", ""]
            if status != "accepted":
                by = lay.link(r["superseded_by"], scope) if r.get("superseded_by") else None
                body += [f"_{status.capitalize()}" + (f" on {(r.get('superseded_at') or '')[:10]} by {by}" if by else "")
                         + "._", ""]
            body += [str(r.get("reasoning") or ""), "", *_inline(typed), ""]
            for title, types, kinds in INCOMING["decision"]:
                body += _incoming(lay, nid, scope, title, types, kinds)
            if G._cites(r):
                body += ["## Cited", ""] + [f"- `{i}`" for i in G._cites(r)] + [""]
            body += _history(lay, snap, nid, scope)
        elif n.kind == "note":
            r = n.data["row"]
            typed = _typed(lay, nid, scope, OUT_TYPES["note"])
            fm = _front({"id": nid, "title": n.title, "aliases": aliases, "type": r.get("type"),
                         "origin": r.get("origin"), "created": r.get("created_at"), "start": n.date or None,
                         "revisit_on": r.get("revisit_on"), "superseded_by": r.get("superseded_by"),
                         **typed}, n.coach, "note")
            body = [GENERATED, "", f"# {n.title}", ""]
            if r.get("origin") == "coach":
                body += ["_The coach's own conclusion: a lead to check, not something the person said._", ""]
            if r.get("superseded_by"):
                ln = lay.link(r["superseded_by"], scope) or f"`{r['superseded_by']}`"
                body += [f"_Superseded on {(r.get('superseded_at') or '')[:10]} by {ln}._", ""]
            body += [str(r.get("summary") or ""), "", *_inline(typed), ""]
            ev = [e for e in (r.get("evidence") or []) if isinstance(e, dict)]
            if ev:
                body += ["## Cited", ""]
                for e in ev:
                    label = e.get("title") or e.get("id")
                    label = f"[{label}]({e['deep_link']})" if e.get("deep_link") else label
                    body.append(f"- {label}" + (f": “{_one(e['quote'], 300)}”" if e.get("quote") else ""))
                body.append("")
        elif n.kind in ("person", "issue"):
            r = n.data["row"]
            typed = _typed(lay, nid, scope, OUT_TYPES[n.kind])
            al = r.get("aliases") or []
            if isinstance(al, str):
                try:
                    al = json.loads(al)
                except ValueError:
                    al = []
            fm = _front({"id": nid, "title": n.title, "aliases": [nid, *al], "status": r.get("status"),
                         "role": r.get("role"), "created": r.get("created_at"), "start": n.date or None,
                         "end": (r.get("closed_at") or "")[:10] or None, **typed}, n.coach, n.kind)
            body = [GENERATED, "", f"# {n.title}", ""]
            if r.get("role"):
                body += [f"Role: {r['role']}", ""]
            if r.get("note"):
                body += [str(r["note"]), ""]
            if r.get("merged_into"):
                body += [f"_Merged into {lay.link(r['merged_into'], scope) or r['merged_into']}._", ""]
            body += [*_inline(typed), ""]
            for title, types, kinds in INCOMING[n.kind]:
                body += _incoming(lay, nid, scope, title, types, kinds)
        else:                                              # checkin
            r = n.data["row"]
            typed = _typed(lay, nid, scope, ("reviewed_in",))
            fm = _front({"id": nid, "title": n.title, "aliases": aliases, "week": r.get("week"),
                         "reviewed_in": typed.get("reviewed_in"), "created": r.get("created_at"),
                         "start": n.date or None}, n.coach, "checkin")
            body = [GENERATED, "", f"# {n.title}", "", str(r.get("summary") or ""), "", *_inline(typed), ""]
            for title, key in (("Wins", "wins"), ("Blockers", "blockers")):
                items = [str(x) for x in (r.get(key) or [])]
                if items:
                    body += [f"## {title}", ""] + [f"- {x}" for x in items] + [""]
        put(lay.path(nid), fm, body)

    for scope, weeks in sorted(lay.weeks.items()):
        ordered = sorted(weeks)
        for i, w in enumerate(ordered):
            start = week_start(w)
            fm = _front({"title": w, "week": w, "start": start.isoformat(),
                         "end": (start + dt.timedelta(days=6)).isoformat()}, scope, "week")
            body = [GENERATED, "", f"# {w}", "", f"{start:%d %b} to {start + dt.timedelta(days=6):%d %b %Y}", ""]
            nav = []
            if i > 0:
                nav.append(f"previous {lay.link(ordered[i - 1], scope)}")
            if i + 1 < len(ordered):
                nav.append(f"next {lay.link(ordered[i + 1], scope)}")
            if nav:
                body += [" · ".join(nav), ""]
            body += _incoming(lay, w, scope, "Decided this week", ("decided_in",), ("decision",))
            body += _incoming(lay, w, scope, "Planned this week", ("reviewed_in",), ("thread",))
            put(f"{scope}/weeks/{w}.md", fm, body)

    scopes = sorted({p.split("/", 1)[0] for p in files} | {folder_of(snap, "profile", p["coach"])
                                                         for p in snap.profile})
    for scope in scopes:
        prof = [p for p in snap.profile if folder_of(snap, "profile", p["coach"]) == scope]
        goals = sorted((nid for nid, sc in lay.scope.items() if sc == scope and g.nodes[nid].kind == "goal"),
                       key=lambda i: (g.nodes[i].date, i))
        lines = [GENERATED, "", f"# {snap.name}" + ("" if scope == SHARED else f" ({scope})"), "",
                 "The Project's shared core." if scope == SHARED else f"What the {scope} coach keeps for this Project.",
                 ""]
        if prof:
            lines += ["## Profile", ""] + [ln for p in prof for ln in _profile_lines(p["field"], p["value"])] + [""]
        if scope != SHARED and any(sc == SHARED for sc in lay.scope.values()):
            lines += [f"The Goals, tasks and Decisions every coach shares: [[{META}/{SHARED}/{HOME}|{SHARED}]].", ""]
        if goals or scope == SHARED:
            lines += ["## Goals", ""] + ([f"- {lay.link(i)}" for i in goals] or ["- none yet"]) + [""]
        open_t = [t for t in g.threads() if lay.scope.get(t.id) == scope and t.status == "open"]
        if open_t:
            lines += ["## Open work", ""] + [f"- {lay.link(t.id)}" for t in sorted(open_t, key=lambda t: t.date)] + [""]
        for kind, label in (("checkin", "Check-ins"), ("note", "Notes")):
            mine = sorted((i for i, sc in lay.scope.items() if sc == scope and g.nodes[i].kind == kind),
                          key=lambda i: (g.nodes[i].date, i), reverse=True)
            if mine:
                lines += [f"## {label}, newest first", ""] + [f"- {lay.link(i)}" for i in mine[:12]]
                lines += ([f"- and {len(mine) - 12} more in `{scope}/{SUBFOLDER[kind]}/`"] if len(mine) > 12 else [])
                lines += [""]
        counts = {k: sum(1 for i, sc in lay.scope.items() if sc == scope and g.nodes[i].kind == k)
                  for k in ("goal", "thread", "decision", "checkin", "note", "person", "issue")}
        names = {"goal": "Goal", "thread": "task", "decision": "Decision", "checkin": "Check-in", "note": "Note",
                 "person": "person", "issue": "blocker"}
        what = ", ".join(f"{v} {names[k]}" + ("" if v == 1 else "s") for k, v in counts.items() if v)
        what = what.replace("persons", "people")
        tasks = f"; {len(open_t)} task(s) open" if counts["thread"] else ""
        lines += ["## In this folder", "", f"{what or 'nothing yet'}{tasks}. This page and "
                  f"everything under `{META}/` are left out of the graph view.", ""]
        put(f"{META}/{scope}/{HOME}.md", _front({"title": snap.name}, scope, "hub"), lines)
    if any(p.startswith(f"{SHARED}/") for p in files):
        files.update(bases())
    from . import vault_views as VV
    for nid, scope in sorted(lay.scope.items()):                 # a board per Goal (JSON Canvas)
        if g.nodes[nid].kind == "goal":
            files[f"{META}/{scope}/canvas/{lay.name[(lay.folder(nid), nid)]}.canvas"] = VV.canvas(g, lay, nid, GENERATED)
    if with_html and files:
        files[f"{META}/graph.html"] = VV.html(g, lay, snap.name, COLORS, GENERATED)
    if full and files:
        tops = sorted({p.split("/", 1)[0] for p in files if not p.startswith(META)})
        lines = [GENERATED, "", f"# {snap.name}: vault", "",
                 "Open this folder as a vault in Obsidian (or Foam, Quartz, Logseq). A read-only view of the Project's "
                 "memory: the coach rewrites these files, so edits are lost.", ""]
        for f in tops:
            n = sum(1 for p in files if p.startswith(f + "/"))
            lines.append(f"- `{f}/`: {n} file(s); start at [[{META}/{f}/{HOME}|{f}]]")
        lines += ["", f"Saved views (Obsidian Bases): `{META}/views/`."]
        files[f"{META}/{INDEX_FILE}"] = "\n".join(lines) + "\n"
    return files


def bases() -> dict[str, str]:
    """Saved table views for Obsidian Bases (a core plugin): query views add no edges to the graph."""
    head = f"# {GENERATED}\n"
    cols = "    order:\n      - file.name\n      - status\n      - periods\n      - goal\n      - last_week\n"
    threads = (head + f'filters:\n  and:\n    - file.inFolder("{SHARED}/threads")\nviews:\n'
               '  - type: table\n    name: Open threads\n    filters:\n      and:\n        - \'status == "open"\'\n'
               + cols +
               '  - type: table\n    name: Planned 3+ periods\n    filters:\n      and:\n        - "periods >= 3"\n'
               + cols +
               '  - type: table\n    name: By goal\n    groupBy:\n      property: goal\n      direction: ASC\n' + cols)
    decisions = (head + f'filters:\n  and:\n    - file.inFolder("{SHARED}/decisions")\nviews:\n'
                 '  - type: table\n    name: Decisions by week\n    groupBy:\n      property: week\n'
                 '      direction: DESC\n    order:\n      - file.name\n      - decided\n      - revisit_on\n')
    return {f"{META}/views/threads.base": threads, f"{META}/views/decisions.base": decisions}


def merge_graph_json(old: str | None) -> str:
    """The graph view settings with our colour groups and the `_meta` filter merged in: every other setting the
    person (or Obsidian, which rewrites this file) made is kept, and their own search filter wins."""
    try:
        data = json.loads(old) if old else {}
        if not isinstance(data, dict):
            data = {}
    except ValueError:
        data = {}
    ours = {f"tag:#kind/{k}" for k in COLORS}
    groups = [x for x in (data.get("colorGroups") or []) if isinstance(x, dict) and x.get("query") not in ours
              and not str(x.get("query", "")).startswith("tag:#kind/")]
    data["colorGroups"] = [{"query": f"tag:#kind/{k}", "color": {"a": 1, "rgb": rgb}} for k, rgb in COLORS.items()] + groups
    if not str(data.get("search") or "").strip():
        data["search"] = GRAPH_SEARCH
    data.setdefault("showArrow", True)
    data.setdefault("hideUnresolved", True)
    return json.dumps(data, indent=2) + "\n"


def graph_json() -> str:
    return merge_graph_json(None)


def _front_of(path: Path) -> dict[str, str]:
    """The frontmatter of a generated page; for a Goal's canvas, the kind and coach it records at its top."""
    try:
        text = path.read_text(encoding="utf-8")[:1500]
    except OSError:
        return {}
    if path.suffix == ".canvas":
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {"kind": "goal", "coach": d.get("_coach")} if isinstance(d, dict) and d.get("_coach") else {}
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


_EXTS = (".md", ".base", ".canvas", ".html")


def write(root: Path, files: dict[str, str], readable: dict[str, set[str]] | None, own: str | None = None) -> dict:
    """Write the files that differ; remove generated files that no longer belong. With `readable` (a slice) a file is
    removed only when it is in the writer's own folders (`own/`, `_meta/own/`) or its frontmatter names a kind and a
    coach the writer may read; a person's own file (no generated marker) never is."""
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
        gp = root / ".obsidian" / "graph.json"
        try:
            old = gp.read_text(encoding="utf-8")
        except OSError:
            old = None
        new = merge_graph_json(old)
        if new != old:
            gp.parent.mkdir(parents=True, exist_ok=True)
            _atomic(gp, new)
    mine = (f"{own}/", f"{META}/{own}/") if own else ()
    if root.exists():
        for p in sorted(x for x in root.rglob("*") if x.suffix in _EXTS and x.is_file()):
            rel = p.relative_to(root).as_posix()
            if rel in files or rel.startswith(".obsidian/") or not _generated(p):
                continue
            if readable is not None and not rel.startswith(mine):
                fm = _front_of(p)
                if fm.get("coach") is None or fm.get("coach") not in readable.get(fm.get("kind", ""), set()):
                    continue
            p.unlink(missing_ok=True)
            removed += 1
        for d in sorted((x for x in root.rglob("*") if x.is_dir() and not x.name.startswith(".")), reverse=True):
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
    snap.links = store.visible_links()
    snap.goals = rows(f"SELECT * FROM goals {own} ORDER BY created_at, id", shared="goals")
    snap.people = rows(f"SELECT * FROM people {own} ORDER BY created_at, id", shared="people")
    for r_ in snap.people:
        r_["aliases"] = _loads(r_.get("aliases")) or []
    snap.issues = rows(f"SELECT * FROM issues {own} ORDER BY created_at, id", shared="issues")
    snap.commitments = rows(f"SELECT * FROM commitments {own} ORDER BY week, created_at, id", shared="commitments")
    snap.decisions = rows(f"SELECT * FROM decisions {own} ORDER BY decided_at, id", shared="decisions")
    if product.has("checkins"):
        snap.checkins = rows(f"SELECT * FROM checkins {own} ORDER BY created_at, id")
    snap.profile = [{"field": f, "value": v["value"], "coach": me} for f, v in store.profile().items()]
    ids = [d["id"] for d in snap.decisions]
    if ids:
        with store._lock:
            snap.history = [dict(r) for r in store.db.execute(
                f"SELECT seq, at, entity, entity_id, op, before, after, reason, actor FROM changes WHERE founder_id=? "
                f"AND entity='decision' AND entity_id IN ({','.join('?' * len(ids))}) ORDER BY seq",
                (store.fid, *ids))]
    snap.readable = readable(store, owned)
    return snap


def readable(store, owned: dict[str, tuple[str, ...]]) -> dict[str, set[str]]:
    """kind -> the `coach` stamps whose generated files this coach's slice may rewrite or remove."""
    me = _slug(store.coach) or "coach"
    shared_writer = not keeps(owned, store.coach, "decision") or not keeps(owned, store.coach, "commitment")
    out = {"note": {me}, "checkin": {me}, "hub": {me}, "week": {me},
           "goal": set(store.readers("goals")), "decision": set(store.readers("decisions")),
           "thread": set(store.readers("commitments")), "person": set(store.readers("people")),
           "issue": set(store.readers("issues"))}
    if shared_writer:
        out["week"].add(SHARED)
        out["hub"].add(SHARED)
    return out


def sync_slice(store) -> dict:
    """After a save: refresh the part of the vault this coach may read. Best effort (the caller never fails a save)."""
    snap = from_store(store)
    return write(store.home / VAULT_DIR, render(snap), snap.readable, _slug(store.coach) or "coach")


def clear(store) -> dict:
    """After `forget`: write the slice again from what is left, so this coach's records go and the shared records of
    the Project's other coaches stay."""
    return sync_slice(store)


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
            snap.links = [ln for ln in all_("links", "created_at, dst") if not ln.get("ended_at")]
            if ver >= 8:
                snap.people = all_("people", "created_at, id")
                for r_ in snap.people:
                    r_["aliases"] = _loads(r_.get("aliases")) or []
                snap.issues = all_("issues", "created_at, id")
            why = "reason, actor" if ver >= 8 else "NULL AS reason, NULL AS actor"    # v7 kept no why or who
            snap.history = [dict(r) for r in con.execute(
                f"SELECT seq, at, entity, entity_id, op, before, after, {why} FROM changes "
                "WHERE entity='decision' ORDER BY seq")]
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


def build(home: Path, out: Path | None = None, engine_home: Path | None = None, with_html: bool = False) -> dict:
    """The full vault of the Project in `home` (a folder holding founder.db), written to `out` (default
    <home>/vault). Reads a copy of the database; writes only inside `out`. `with_html` adds `_meta/graph.html`."""
    snap = from_db_file(Path(home) / "founder.db", engine_home)
    root = Path(out) if out else Path(home) / VAULT_DIR
    res = write(root, render(snap, full=True, with_html=with_html), None)
    res["path"] = str(root)
    return res
