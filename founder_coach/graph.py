"""The Project graph: a typed graph computed from the store on every read (ADR-0024).

Nothing here is stored. The graph is derived from records the person already said yes to, so it holds no claim of
its own (like an index, it is derived from the primary data and can be dropped and rebuilt). It is built from the
same Snapshot the vault is written from, so a coach sees exactly what ADR-0019 lets it read: a record it can't read
is never a node, and no walk, count or path passes through it.

Nodes
    goal, decision, note, checkin   one per record
    thread                          a Commitment and every carry of it (its id is the first row's id; any row id
                                    resolves to it), so a task carried for four weeks is one node with four weeks
    week                            "2026-W44": the time spine Decisions, threads and Check-ins hang on
    source                          "src:<item_id>": a library item a record cites (left out of walks unless asked)

Edges (closed vocabulary; DERIVED ones are facts about stored columns, the rest were said by the person)
    serves        thread -> goal       the Commitment's goal_id
    decided_in    decision -> week     the week of decided_at, in the Project's time zone
    reviewed_in   thread -> week       every week the thread was planned in; checkin -> week
    cites         record -> source     the record's citations
    about | supports | related   note -> any    a Note's own links
    supersedes    note -> note         made by superseding a Note

Time: "as of" a date reads the change log (transaction time: what the store held at the end of that day), ordered
by `seq`, never by the clock, so the same log always gives the same state.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import deque
from dataclasses import dataclass, field

from .store import iso_week

DERIVED = ("serves", "decided_in", "reviewed_in", "cites", "mentions", "supersedes")
PERSON = ("about", "supports", "related", "contradicts", "supersedes", "sub_goal_of", "changes_scope_of", "led_to",
          "assumes", "blocks", "resolved_by", "owned_by", "decided_by", "serves")
EDGE_TYPES = tuple(dict.fromkeys(DERIVED + PERSON))
KINDS = ("goal", "thread", "decision", "note", "checkin", "person", "issue", "week", "source")
WALK_DEFAULT_SKIP = ("cites",)        # sources become hubs; a walk follows them only when asked
MAX_HOPS = 3
MAX_PATH = 6
RECORD_KINDS = {"goal": "goals", "commitment": "commitments", "decision": "decisions", "note": "notes",
                "checkin": "checkins"}


@dataclass
class Node:
    id: str
    kind: str
    title: str
    coach: str = ""
    date: str = ""                    # YYYY-MM-DD (a week node: its Monday)
    status: str | None = None
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    type: str

    @property
    def derived(self) -> bool:
        return self.type in DERIVED


class Graph:
    def __init__(self, name: str = ""):
        self.name = name
        self.nodes: dict[str, Node] = {}
        self.out: dict[str, list[Edge]] = {}
        self.into: dict[str, list[Edge]] = {}
        self.alias: dict[str, str] = {}               # commitment row id -> thread id
        self._edges: set[Edge] = set()

    # -- building ---------------------------------------------------------------------------------------------
    def add(self, node: Node) -> Node:
        self.nodes.setdefault(node.id, node)
        return self.nodes[node.id]

    def link(self, src: str, dst: str, typ: str) -> None:
        src, dst = self.alias.get(src, src), self.alias.get(dst, dst)
        if src == dst or src not in self.nodes or dst not in self.nodes:
            return                                    # an end the reader can't see: no edge (never a dangling one)
        e = Edge(src, dst, typ)
        if e in self._edges:
            return
        self._edges.add(e)
        self.out.setdefault(src, []).append(e)
        self.into.setdefault(dst, []).append(e)

    @property
    def edges(self) -> list[Edge]:
        return sorted(self._edges, key=lambda e: (e.src, e.type, e.dst))

    # -- reading ----------------------------------------------------------------------------------------------
    def resolve(self, ref: str | None) -> str | None:
        """A node id from what a person or coach may pass: a record id, a commitment row id (its thread), a week
        ("2026-W44") or a source ("src:<item_id>")."""
        if not ref:
            return None
        ref = str(ref).strip()
        ref = self.alias.get(ref, ref)
        return ref if ref in self.nodes else None

    def steps(self, nid: str, types: tuple[str, ...] | None = None) -> list[tuple[str, Edge, str]]:
        """(neighbour, edge, "out" | "in") for every edge touching `nid`, in a fixed order."""
        allow = set(types) if types else set(EDGE_TYPES) - set(WALK_DEFAULT_SKIP)
        res = [(e.dst, e, "out") for e in self.out.get(nid, []) if e.type in allow]
        res += [(e.src, e, "in") for e in self.into.get(nid, []) if e.type in allow]
        return sorted(res, key=lambda t: (t[1].type, self.nodes[t[0]].date, t[0]))

    def around(self, nid: str, hops: int = 2, types: tuple[str, ...] | None = None,
               kinds: tuple[str, ...] | None = None) -> list[dict]:
        """Everything within `hops` of `nid` (breadth first, each node once at its smallest depth), with the edge it
        was reached by. O(V' + E') over the nodes reached."""
        hops = max(1, min(MAX_HOPS, int(hops)))
        seen = {nid: None}
        found: list[dict] = []
        q = deque([(nid, 0)])
        while q:
            cur, d = q.popleft()
            if d == hops:
                continue
            for nxt, e, way in self.steps(cur, types):
                if nxt in seen:
                    continue
                seen[nxt] = cur
                q.append((nxt, d + 1))
                if not kinds or self.nodes[nxt].kind in kinds:
                    found.append({"id": nxt, "depth": d + 1, "via": cur, "edge": e.type, "direction": way})
        return found

    def path(self, a: str, b: str, max_depth: int = 4, types: tuple[str, ...] | None = None) -> list[dict] | None:
        """The shortest typed path from `a` to `b` (edges walked either way), as steps, or None. Plain BFS: every
        edge costs one, so the first time `b` is reached is a shortest path."""
        max_depth = max(1, min(MAX_PATH, int(max_depth)))
        if a == b:
            return []
        prev: dict[str, tuple[str, Edge, str]] = {}
        seen = {a}
        q = deque([(a, 0)])
        while q:
            cur, d = q.popleft()
            if d == max_depth:
                continue
            for nxt, e, way in self.steps(cur, types):
                if nxt in seen:
                    continue
                seen.add(nxt)
                prev[nxt] = (cur, e, way)
                if nxt == b:
                    out, x = [], b
                    while x != a:
                        p, edge, w = prev[x]
                        out.append({"from": p, "to": x, "edge": edge.type, "direction": w})
                        x = p
                    return list(reversed(out))
                q.append((nxt, d + 1))
        return None

    def record_ids(self, nid: str | None = None) -> list[str]:
        """The store ids behind one node (a thread: every row) or behind the whole graph (records only)."""
        if nid is not None:
            n = self.nodes.get(nid)
            if n is None or n.kind in ("week", "source"):
                return []
            return [c["id"] for c in n.data["rows"]] if n.kind == "thread" else [nid]
        return [i for n in self.nodes.values() for i in self.record_ids(n.id)]

    def threads(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.kind == "thread"]

    def open_loops(self, min_periods: int = 3) -> list[Node]:
        """Open threads planned in at least `min_periods` periods (rows), longest first."""
        out = [t for t in self.threads() if t.status == "open" and len(t.data["live"]) >= max(1, min_periods)]
        return sorted(out, key=lambda t: (-len(t.data["live"]), t.date, t.id))

    def isolated(self) -> list[str]:
        return sorted(i for i, n in self.nodes.items() if n.kind not in ("week", "source")
                      and not self.out.get(i) and not self.into.get(i))


# ---- building from a vault Snapshot ---------------------------------------------------------------------------

def _tz(snap, tz):
    if tz is not None:
        return tz
    from zoneinfo import ZoneInfo
    for p in snap.profile:
        if p.get("field") == "timezone":
            v = p.get("value")
            if isinstance(v, str) and v.startswith('"'):
                try:
                    v = json.loads(v)
                except ValueError:
                    pass
            try:
                return ZoneInfo(str(v))
            except Exception:                         # noqa: BLE001 -- a bad zone name: fall back to UTC
                break
    return dt.timezone.utc


def local_day(ts: str | None, tz) -> dt.date | None:
    if not ts:
        return None
    try:
        t = dt.datetime.fromisoformat(str(ts))
    except ValueError:
        try:
            return dt.date.fromisoformat(str(ts)[:10])
        except ValueError:
            return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(tz).date()


def week_node(g: Graph, week: str) -> str:
    from .store import week_start
    if week not in g.nodes:
        g.add(Node(week, "week", week, date=week_start(week).isoformat()))
    return week


def thread_rows(commitments: list[dict]) -> dict[str, list[dict]]:
    """thread id (the first row of a carry chain) -> its rows, oldest first. A row whose parent isn't in the list
    starts its own thread; a cycle (never written by the store) is cut where it closes."""
    by = {c["id"]: c for c in commitments}
    root: dict[str, str] = {}
    for c in commitments:
        chain, cur = [], c
        while cur["id"] not in root and cur.get("carried_from") in by and cur["id"] not in chain:
            chain.append(cur["id"])
            cur = by[cur["carried_from"]]
        r = root.get(cur["id"], cur["id"])
        root[cur["id"]] = r
        for x in chain:
            root[x] = r
    out: dict[str, list[dict]] = {}
    for c in commitments:
        out.setdefault(root[c["id"]], []).append(c)
    for rows in out.values():
        rows.sort(key=lambda c: (c.get("week") or "", c.get("created_at") or "", c["id"]))
    return out


def live_rows(rows: list[dict]) -> list[dict]:
    """A thread's rows without undone carries: a copy dropped while the row it was carried from was not marked
    carried (a carry made twice, or by mistake, and dropped again). The copy stays in the history; it never decides
    the thread's status, its periods or its weeks."""
    st = {r["id"]: r.get("status") for r in rows}
    out = [r for r in rows if not (r.get("status") == "dropped" and r.get("carried_from") in st
                                   and st[r["carried_from"]] != "carried")]
    return out or rows


def _cites(r: dict) -> list[str]:
    v = r.get("citations") or []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = []
    return [str(x) for x in v if isinstance(x, str)]


def build(snap, tz=None) -> Graph:
    """The graph of what `snap` holds (a coach's readable slice, or the person's full build)."""
    tz = _tz(snap, tz)
    g = Graph(snap.name)
    for r in snap.goals:
        g.add(Node(r["id"], "goal", str(r.get("text") or r["id"]).strip(), r.get("coach") or "",
                   (r.get("created_at") or "")[:10], r.get("status"), {"row": r}))
    threads = thread_rows(snap.commitments)
    for tid, rows in threads.items():
        live = live_rows(rows)
        last = live[-1]
        goal = next((c["goal_id"] for c in reversed(live) if c.get("goal_id")), None)
        g.add(Node(tid, "thread", str(last.get("action") or tid).strip(), last.get("coach") or "",
                   (rows[0].get("created_at") or "")[:10], last.get("status"),
                   {"rows": rows, "live": live, "goal_id": goal,
                    "weeks": [c.get("week") for c in live if c.get("week")]}))
        for c in rows:
            g.alias[c["id"]] = tid
    for r in snap.decisions:
        day = local_day(r.get("decided_at"), tz)
        g.add(Node(r["id"], "decision", str(r.get("text") or r["id"]).strip(), r.get("coach") or "",
                   day.isoformat() if day else "", r.get("status") or "accepted", {"row": r}))
    for r in snap.notes:
        g.add(Node(r["id"], "note", str(r.get("title") or r["id"]).strip(), r.get("coach") or "",
                   (r.get("created_at") or "")[:10], "superseded" if r.get("superseded_by") else None, {"row": r}))
    for r in snap.checkins:                     # a week can hold several Check-ins: the day tells them apart
        day = local_day(r.get("created_at"), tz)
        when = f" ({day.day} {day:%b})" if day else ""
        g.add(Node(r["id"], "checkin", f"Check-in {r.get('week') or ''}{when}".strip(), r.get("coach") or "",
                   (r.get("created_at") or "")[:10], None, {"row": r}))
    for r in getattr(snap, "people", []):
        g.add(Node(r["id"], "person", str(r.get("name") or r["id"]).strip(), r.get("coach") or "",
                   (r.get("created_at") or "")[:10], r.get("status"), {"row": r}))
    for r in getattr(snap, "issues", []):
        g.add(Node(r["id"], "issue", str(r.get("text") or r["id"]).strip(), r.get("coach") or "",
                   (r.get("created_at") or "")[:10], r.get("status"), {"row": r}))
    # derived edges
    for t in g.threads():
        if t.data["goal_id"]:
            g.link(t.id, t.data["goal_id"], "serves")
        for w in dict.fromkeys(t.data["weeks"]):
            g.link(t.id, week_node(g, w), "reviewed_in")
    for r in snap.decisions:
        day = local_day(r.get("decided_at"), tz)
        if day:
            g.link(r["id"], week_node(g, iso_week(day)), "decided_in")
    for r in snap.checkins:
        if r.get("week"):
            g.link(r["id"], week_node(g, r["week"]), "reviewed_in")
    for r in [*snap.goals, *snap.commitments, *snap.decisions, *snap.notes]:
        for item in _cites(r) + [str(e.get("id")) for e in (r.get("evidence") or []) if isinstance(e, dict)
                                 and e.get("id")]:
            sid = f"src:{item}"
            g.add(Node(sid, "source", item))
            g.link(r["id"], sid, "cites")
    for r in snap.decisions:                          # a Decision's superseded_by (ADR-0025): newer -> older
        if r.get("superseded_by"):
            g.link(r["superseded_by"], r["id"], "supersedes")
    # what the person said
    for ln in snap.links:
        if ln.get("type") in PERSON:
            g.link(ln["src"], ln["dst"], ln["type"])
    mention_edges(g)
    return g


def _record_text(n: Node) -> str:
    r = n.data.get("row") or (n.data.get("rows") or [{}])[-1]
    parts = [n.title]
    for k in ("reasoning", "summary", "outcome", "result_note", "measure", "note", "role"):
        if r.get(k):
            parts.append(str(r[k]))
    for k in ("wins", "blockers"):
        parts += [str(x) for x in (r.get(k) or [])]
    return " ".join(parts)


def mention_edges(g: Graph) -> None:
    """record -> person `mentions` wherever a Person's name or a confirmed alias appears as a whole word. Derived:
    the Person exists because the person said yes to it; the mention is a fact about the record's words."""
    import re
    people = [n for n in g.nodes.values() if n.kind == "person" and n.status != "merged"]
    if not people:
        return
    pats = []
    for p in people:
        al = p.data["row"].get("aliases") or []
        if isinstance(al, str):
            try:
                al = json.loads(al)
            except ValueError:
                al = []
        names = [x for x in [p.title, *al] if x and len(x) >= 2]
        pats.append((p.id, re.compile(r"(?<![\w-])(" + "|".join(re.escape(x) for x in names) + r")(?![\w-])", re.I)))
    for n in list(g.nodes.values()):
        if n.kind in ("person", "week", "source"):
            continue
        text = _record_text(n)
        for pid, pat in pats:
            if pat.search(text):
                g.link(n.id, pid, "mentions")


def for_store(store) -> Graph:
    """The graph a coach may read (ADR-0019), from its live store."""
    from . import vault
    return build(vault.from_store(store), store.tz())


# ---- time: the change log ------------------------------------------------------------------------------------

def changes(store, ids: list[str]) -> list[dict]:
    """Change-log rows of the given record ids, oldest first (by seq). Only ids the caller could read are passed in,
    so another coach's private record never shows up here."""
    if not ids:
        return []
    out: list[dict] = []
    with store._lock:
        for i in range(0, len(ids), 400):
            part = ids[i:i + 400]
            out += [dict(r) for r in store.db.execute(
                f"SELECT seq, at, entity, entity_id, op, before, after, reason, actor FROM changes WHERE founder_id=? "
                f"AND entity IN ('goal','commitment','decision','note','checkin','person','issue') AND entity_id IN "
                f"({','.join('?' * len(part))}) ORDER BY seq", (store.fid, *part))]
    for r in out:
        for k in ("before", "after"):
            if isinstance(r.get(k), str):
                try:
                    r[k] = json.loads(r[k])
                except ValueError:
                    pass
    out.sort(key=lambda r: r["seq"])
    return out


def end_of_day_utc(day: dt.date, tz) -> str:
    t = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0, 0), tzinfo=tz) - dt.timedelta(seconds=1)
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def last_seq_at(store, at_utc: str) -> int:
    with store._lock:
        row = store.db.execute("SELECT MAX(seq) FROM changes WHERE founder_id=? AND at<=?",
                               (store.fid, at_utc)).fetchone()
    return int(row[0] or 0)


_SKIP_DIFF = {"kind", "created_at", "closed_at", "coach", "carried_periods", "links", "linked_from"}


def diff(before, after) -> dict:
    """{field: [old, new]} for the fields an update changed."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {}
    return {k: [before.get(k), after.get(k)] for k in sorted(set(before) | set(after))
            if k not in _SKIP_DIFF and before.get(k) != after.get(k)}


def state_at(rows: dict[str, dict], log: list[dict], seq_t: int) -> dict[str, dict]:
    """What each record looked like once the change with seq `seq_t` was written: a record created later is left
    out; a record changed later reads as the `before` of its first later change (which is the whole record).
    O(len(log))."""
    first_after: dict[str, dict] = {}
    for c in log:
        if c["seq"] > seq_t and c["entity_id"] not in first_after:
            first_after[c["entity_id"]] = c
    out: dict[str, dict] = {}
    for rid, cur in rows.items():
        c = first_after.get(rid)
        if c is None:
            out[rid] = cur
        elif c["op"] == "create":
            continue                                      # did not exist yet
        elif c["op"] == "supersede":
            out[rid] = {**cur, "superseded_by": None, "superseded_at": None}
        elif isinstance(c.get("before"), dict) and c["before"]:
            out[rid] = {**cur, **{k: v for k, v in c["before"].items() if k != "kind"}}
        else:
            out[rid] = cur
    return out


# ---- answers for the coach (coach_graph) ---------------------------------------------------------------------

def card(g: Graph, nid: str) -> dict:
    """A node as the coach reads it: its words first, then what it is."""
    n = g.nodes[nid]
    out = {"title": n.title, "id": n.id, "kind": n.kind}
    if n.date:
        out["date"] = n.date
    if n.status:
        out["status"] = n.status
    if n.kind == "thread":
        out["periods"] = len(n.data["live"])
        if n.data["weeks"]:
            out["weeks"] = f"{n.data['weeks'][0]}..{n.data['weeks'][-1]}" if len(n.data["weeks"]) > 1 \
                else n.data["weeks"][0]
    return out


def sentence(g: Graph, src: str, typ: str, dst: str) -> str:
    """An edge as a sentence a person reads: 'Thread · Email 20 dentists —serves→ Goal · Ten partners'."""
    def name(i: str) -> str:
        n = g.nodes[i]
        return f"{n.kind.capitalize()} · {n.title[:70]}"
    return f"{name(src)} —{typ}→ {name(dst)}"


def as_of(store, g: Graph, day: dt.date,
          kinds: tuple[str, ...] = ("goal", "thread", "decision", "note", "person", "issue")) -> dict:
    """What the store held at the end of `day` (the Project's time zone): each record as it read then, which ones
    were changed since, and how many were made later. Transaction time: what was believed, not when it happened."""
    tz = store.tz()
    seq_t = last_seq_at(store, end_of_day_utc(day, tz))
    log = changes(store, g.record_ids())
    rows: dict[str, dict] = {}
    for n in g.nodes.values():
        if n.kind not in kinds:
            continue
        if n.kind == "thread":
            for c in n.data["rows"]:
                rows[c["id"]] = c
        elif "row" in n.data:
            rows[n.id] = n.data["row"]
    then = state_at(rows, log, seq_t)
    items, later = [], 0
    for n in sorted((x for x in g.nodes.values() if x.kind in kinds), key=lambda x: (x.kind, x.date, x.id)):
        if n.kind == "thread":
            have = live_rows([then[c["id"]] for c in n.data["rows"] if c["id"] in then])
            if not have:
                later += 1
                continue
            last = have[-1]
            item = {"title": str(last.get("action") or n.title), "id": n.id, "kind": "thread",
                    "status": last.get("status"), "periods": len(have), "week": last.get("week")}
            item["changed_since"] = len(have) != len(n.data["live"]) or last.get("status") != n.status
        else:
            if n.id not in then:
                later += 1
                continue
            r = then[n.id]
            title = str(r.get("text") or r.get("title") or r.get("name") or n.title)
            item = {"title": title, "id": n.id, "kind": n.kind}
            st = r.get("status") or ("superseded" if r.get("superseded_by") else None)
            if st:
                item["status"] = st
            item["changed_since"] = bool(diff(r, n.data["row"]))
        items.append(item)
    return {"items": items, "made_later": later, "seq": seq_t}


def decided_by_note(g: Graph, nid: str) -> str:
    """Who made a Decision, only as recorded: its decided_by ties. Saving a record isn't deciding it."""
    who = [g.nodes[e.dst].title for e in g.out.get(nid, []) if e.type == "decided_by" and e.dst in g.nodes]
    if who:
        return "decided by: " + ", ".join(who)
    return ("decided by: not recorded (no one is named as its decider; `recorded_by` is only who saved it, so say "
            "who decided isn't recorded)")


def history(store, g: Graph, nid: str) -> list[dict]:
    """The change log of one node (a thread: every row), oldest first, each change with the fields it changed."""
    out = []
    for c in changes(store, g.record_ids(nid)):
        item = {"date": str(c["at"])[:10], "op": c["op"], "id": c["entity_id"]}
        if c.get("reason"):
            item["why"] = c["reason"]
        # every change is recorded by the person through the coach; `by` only when someone was named (ADR-0025):
        # who decided is a decided_by tie or a `by`, never the fact that the person saved it
        item["recorded_by"] = "the person, through the coach"
        if c.get("actor") == "self":
            item["by"] = "the person (they said so)"
        elif c.get("actor") and c["actor"] != "me":
            who = g.nodes.get(c["actor"])
            item["by"] = who.title if who else c["actor"]
        if c["op"] in ("update", "status"):
            item["changed"] = diff(c.get("before"), c.get("after"))
        elif c["op"] == "create" and isinstance(c.get("after"), dict):
            a = c["after"]
            if a.get("carried_from"):
                item["carried_from"] = a["carried_from"]
            words = a.get("text") or a.get("action") or a.get("title") or a.get("summary")
            if words:
                item["words"] = str(words)[:160]
        elif c["op"] == "supersede" and isinstance(c.get("after"), dict):
            item["superseded_by"] = c["after"].get("superseded_by")
            if c["entity"] == "decision":
                item["changed"] = diff(c.get("before"), c.get("after"))
        out.append(item)
    return out


# ---- ranking: what is tied to the search hits (personalized PageRank on a local subgraph) -----------------------

EDGE_WEIGHT = {"serves": 1.0, "supersedes": 0.9, "led_to": 0.9, "changes_scope_of": 0.9, "blocks": 0.9,
               "resolved_by": 0.8, "decided_by": 0.7, "owned_by": 0.7, "about": 0.8, "supports": 0.7,
               "contradicts": 0.7, "assumes": 0.7, "sub_goal_of": 0.8, "related": 0.5, "mentions": 0.3,
               "decided_in": 0.3, "reviewed_in": 0.3, "cites": 0.0}
RESTART = 0.15
HALF_LIFE_DAYS = 60


def rank(g: Graph, seeds: dict[str, float], today: dt.date, hops: int = 2, cap: int = 300, k: int = 8) -> list[dict]:
    """Records tied to the search hits (`seeds`: node id -> score), best first: a personalized PageRank (HippoRAG 2)
    restarted at the seeds, over the subgraph within `hops` of them (at most `cap` nodes), each edge weighted by its
    type and a hub divided by its degree, times a recency factor. Seeds themselves are left out; each result carries
    `how`, the edge that ties it to the nearest seed. Pure Python: O(iterations x edges of the subgraph)."""
    seeds = {g.resolve(s): v for s, v in seeds.items() if g.resolve(s)}
    if not seeds:
        return []
    parent: dict[str, tuple[str, Edge, str] | None] = {s: None for s in seeds}
    frontier = list(seeds)
    for _ in range(max(1, hops)):
        nxt = []
        for cur in frontier:
            for other, e, way in g.steps(cur):
                if other not in parent and len(parent) < cap:
                    parent[other] = (cur, e, way)
                    nxt.append(other)
        frontier = nxt
    nodes = list(parent)
    idx = {n: i for i, n in enumerate(nodes)}
    out_w: list[list[tuple[int, float]]] = [[] for _ in nodes]
    for n in nodes:
        for other, e, _ in g.steps(n):
            if other in idx:
                w = EDGE_WEIGHT.get(e.type, 0.5)
                if g.nodes[other].kind == "week":
                    w /= max(1, len(g.into.get(other, [])))
                if w > 0:
                    out_w[idx[n]].append((idx[other], w))
    total = sum(seeds.values()) or 1.0
    p = [seeds.get(n, 0.0) / total for n in nodes]
    r = list(p)
    for _ in range(30):
        new = [RESTART * x for x in p]
        for i, edges in enumerate(out_w):
            s = sum(w for _, w in edges)
            if s and r[i]:
                for j, w in edges:
                    new[j] += (1 - RESTART) * r[i] * w / s
        if sum(abs(a - b) for a, b in zip(new, r)) < 1e-6:
            r = new
            break
        r = new

    def recency(n: Node) -> float:
        try:
            age = (today - dt.date.fromisoformat(n.date[:10])).days if n.date else 365
        except ValueError:
            age = 365
        return 0.5 + 0.5 * 0.5 ** (max(0, age) / HALF_LIFE_DAYS)
    scored = []
    for n in nodes:
        node = g.nodes[n]
        if n in seeds or node.kind in ("week", "source"):
            continue
        score = r[idx[n]] * recency(node) * (0.3 if node.status in ("superseded", "merged") else 1.0)
        src, e, way = parent[n]
        how = sentence(g, src, e.type, n) if way == "out" else sentence(g, n, e.type, src)
        scored.append((score, n, how))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [{**card(g, n), "score": round(sc, 4), "how": how} for sc, n, how in scored[:k]]
