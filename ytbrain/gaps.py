"""`ytbrain gaps`: what the dogfooded coaches could not answer well, from their local usage logs.

Every coach tool call leaves one row in the `usage` table of its Project's store, stamped with the coach that made it
(`~/.ytbrain/projects/<id>/founder.db`, shared by the coaches: ADR-0019; docs/usage-log.md). A store a coach still keeps in
the layout before that (`~/.ytbrain/<pack>/projects/<id>/`) is read too, until the move has copied it. This reads the
usage tables and nothing else:
no goals, decisions or profile, and it never opens a store through the coach's own code (no migration, no
backup, no write). A search is rated `strong`, `partial` or `none` (its coverage); the report counts them per
coach and Domain, shows where the border between strong and partial sits in similarity, and, when the question
text was recorded (`<PREFIX>USAGE_TEXT=1`, your own machine only), lists the questions behind the weak ones.

It also says how each coach used the Project's memory (ADR-0026): recall, context and graph calls, follow-through (a
read that marked a record `edited` or `ties`, followed by coach_graph on that record), ties and suggestion answers, and
refused writes, all from record ids; and the calls a coach made before a Project was chosen, from the Common profile.

A search's level is fixed when it ran. `--replay` searches those weak questions again, the way the coach's server
does, against the Knowledge pack each coach has installed now, and shows each one's level then and now: whether
new Sources or a new build closed the gap. It logs nothing and writes nothing.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import statistics
import tempfile
import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

LEVELS = ("strong", "partial", "none", "empty", "unrated")     # unrated: a search from before coverage was logged
DB_NAME = "founder.db"
ASK_GAP_S = 120          # searches of one session closer than this belong to one ask
ROUND_GAP_S = 5          # ... and closer than this to one round (a round's searches go out together)
SEARCH_GUARD = 12        # the skills' cap on searches per ask (0.1.7)
FOLLOW_MIN = 10          # follow-through is only judged (a warning) on at least this many marked reads (ADR-0026)
FOLLOW_BAR = 0.8         # ... and warns below this share, G9's bar
FORGOTTEN = "forgotten"  # a forgotten record's id in the log (founder_coach.store.FORGOTTEN)
ANSWERS = {"accepted": "yes", "rejected": "never", "snoozed": "later"}   # a proposal's answer, as the person says it
COMMON_DB = "you.db"     # the Common profile: it keeps the calls made before a Project was chosen


def engine_home() -> Path:
    return Path(os.environ.get("YTBRAIN_HOME") or "~/.ytbrain").expanduser()


@dataclass
class Project:
    pack: str                     # founder, coding, investor
    project_id: str
    name: str
    db: Path
    shared: bool = False          # a store in the shared Projects folder: its rows say which coach made each
    common: bool = False          # the Common profile's log: calls made before a Project was chosen (ADR-0026)
    rows: list[dict] = field(default_factory=list)
    note: str = ""                # why it has no rows (no usage table, unreadable)


def _product_id(home: Path, pack: str) -> str:
    """The coach's product id for a Pack folder (its env prefix is this, upper-cased), from the registry
    each coach writes when it starts; `<pack>-coach` if it never registered."""
    try:
        for f in (home / "installed").glob("*.json"):
            d = json.loads(f.read_text())
            if d.get("pack") == pack and d.get("product_id"):
                return str(d["product_id"])
    except (OSError, ValueError):
        pass
    return f"{pack}-coach"


def env_prefix(home: Path, pack: str) -> str:
    return _product_id(home, pack).upper().replace("-", "_") + "_"


def discover(home: Path | None = None, pack: str | None = None) -> list[Project]:
    """Every Project store under the engine home: `<home>/projects/<id>/founder.db` (one for all coaches), and the
    per-coach `<home>/<pack>/projects/<id>/founder.db` of the layout before ADR-0019 that the move has not copied (a
    moved one is skipped: its rows are in the shared store). `pack` keeps one coach's own legacy stores here; the shared
    stores are split by coach, and filtered, in `load`."""
    home = home or engine_home()
    out: list[Project] = []
    if not home.is_dir():
        return out
    moved: set[str] = set()
    shared = home / "projects"
    if shared.is_dir():
        for d in sorted(x for x in shared.iterdir() if not x.name.startswith(".") and (x / DB_NAME).is_file()):
            meta = _meta(d)
            if isinstance(meta.get("migrated_from"), str):
                moved.add(meta["migrated_from"])
            out.append(Project(pack="", project_id=d.name, name=str(meta.get("name") or d.name), db=d / DB_NAME,
                               shared=True))
    for pdir in sorted(p for p in home.iterdir() if p.name != "projects" and (p / "projects").is_dir()):
        if pack and pdir.name != pack:
            continue
        for d in sorted(x for x in (pdir / "projects").iterdir() if (x / DB_NAME).is_file()):
            if f"{pdir.name}/{d.name}" in moved:
                continue
            out.append(Project(pack=pdir.name, project_id=d.name, name=str(_meta(d).get("name") or d.name),
                               db=d / DB_NAME))
    if (home / COMMON_DB).is_file():                 # stamped per coach, like a shared store
        out.append(Project(pack="", project_id="", name="(none chosen)", db=home / COMMON_DB, shared=True,
                           common=True))
    return out


def _meta(folder: Path) -> dict:
    try:
        data = json.loads((folder / "project.json").read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_usage(db: Path) -> tuple[list[dict], str]:
    """The usage rows of one store (each with its `coach`, '' when the store predates the stamp). The store is in WAL
    mode and a running coach keeps its newest rows in the -wal file, so the file and its -wal are copied to a temporary
    folder and read there: the original is never opened, so nothing (not even a -shm file) appears next to it."""
    tmp = tempfile.mkdtemp(prefix="ytbrain-gaps-")
    try:
        for suffix in ("", "-wal"):
            src = Path(str(db) + suffix)
            if src.exists():
                shutil.copy2(src, Path(tmp) / (DB_NAME + suffix))
        c = sqlite3.connect(Path(tmp) / DB_NAME, timeout=1)
        try:
            c.row_factory = sqlite3.Row
            stamped = any(r[1] == "coach" for r in c.execute("PRAGMA table_info(usage)"))
            who = "coach" if stamped else "'' AS coach"
            rows = [dict(r) for r in c.execute(
                f"SELECT {who}, at, run, tool, outcome, duration_ms, version, detail FROM usage ORDER BY at, id")]
            return rows, ""
        finally:
            c.close()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return [], "no usage log yet (the store predates it, or the coach has not run)"
        return [], f"unreadable ({e})"
    except (sqlite3.Error, OSError) as e:
        return [], f"unreadable ({type(e).__name__})"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def load(home: Path | None = None, pack: str | None = None, days: int | None = 30,
         now: dt.datetime | None = None) -> list[Project]:
    cutoff = None
    if days is not None:
        cutoff = ((now or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(days=days)).isoformat(timespec="seconds")
    out: list[Project] = []
    for p in discover(home, pack):
        rows, p.note = _read_usage(p.db)
        for r in rows:
            try:
                r["detail"] = json.loads(r.get("detail") or "{}")
            except ValueError:
                r["detail"] = {}
        if not p.shared:
            for r in rows:
                r.pop("coach", None)                  # the folder says which coach it is
            p.rows = [r for r in rows if cutoff is None or r["at"] >= cutoff]
            out.append(p)
            continue
        by_coach: dict[str, list[dict]] = {}          # a shared store holds every coach's rows: one entry per coach
        for r in rows:
            by_coach.setdefault(r.pop("coach") or "unknown", []).append(r)
        if not by_coach and p.note and not pack and not p.common:
            out.append(p)
        for coach, mine in sorted(by_coach.items()):
            if pack and coach != pack:
                continue
            kept = [r for r in mine if cutoff is None or r["at"] >= cutoff]
            if p.common and not kept:
                continue                              # no calls before a Project in this window: nothing to say
            out.append(Project(pack=coach, project_id=p.project_id, name=p.name, db=p.db, shared=True, note=p.note,
                               rows=kept, common=p.common))
    return out


def level_of(row: dict) -> str:
    """strong / partial / none / empty / unrated for one coach_search row."""
    d = row["detail"]
    if row["outcome"] == "empty":
        return "empty"
    if row["outcome"] == "gap":
        return "none"
    return d.get("coverage") if d.get("coverage") in ("strong", "partial", "none") else "unrated"


class HitDomains:
    """item_id -> Domains, read from the Knowledge pack a coach registered under <home>/installed/ (its pack_path),
    opened read-only and immutable: a search that named no Domain is attributed to the Domain most of its logged
    hits belong to."""

    def __init__(self, pack_file: Path | None):
        self.path = pack_file if pack_file and pack_file.is_file() else None
        self._cache: dict[str, list[str]] = {}

    @classmethod
    def for_pack(cls, home: Path, pack: str) -> "HitDomains":
        path = installed_pack(home, pack)
        return cls(path / "knowledge.sqlite" if path else None)

    def domains(self, item_ids: list[str]) -> list[list[str]]:
        want = [i for i in item_ids if i not in self._cache]
        if want and self.path:
            try:
                c = sqlite3.connect(f"file:{self.path}?mode=ro&immutable=1", uri=True)
                try:
                    q = f"SELECT item_id, domains FROM items WHERE item_id IN ({','.join('?' * len(want))})"
                    for iid, doms in c.execute(q, want):
                        self._cache[iid] = json.loads(doms or "[]")
                finally:
                    c.close()
            except (sqlite3.Error, ValueError):
                self.path = None                     # unreadable: stop trying, the report says how many were unknown
        return [self._cache[i] for i in item_ids if i in self._cache]


def installed_pack(home: Path, pack: str) -> Path | None:
    """The Knowledge pack folder the coach of this Pack folder registered under <home>/installed/ (what it searches
    now), or None."""
    try:
        for f in (home / "installed").glob("*.json"):
            d = json.loads(f.read_text())
            if d.get("pack") == pack and d.get("pack_path"):
                return Path(d["pack_path"])
    except (OSError, ValueError):
        pass
    return None


def domain_levels(row: dict, hits: HitDomains | None = None) -> dict[str, str]:
    """Domain -> level for one search: its per-Domain coverage when logged; else the overall level for each
    Domain it named; else (no Domain named: the whole Library) for the Domain most of its hits belong to.
    The last two are approximate."""
    d = row["detail"]
    by = d.get("coverage_by_domain")
    if isinstance(by, dict) and by:
        return {str(k): str(v) for k, v in by.items()}
    lv = level_of(row)
    if lv not in ("strong", "partial", "none"):
        return {}
    if d.get("domains_searched"):
        return {str(k): lv for k in d["domains_searched"]}
    if hits is None:
        return {}
    counts: dict[str, int] = {}
    for doms in hits.domains([str(i) for i in (d.get("items") or [])]):
        for dom in doms:
            counts[dom] = counts.get(dom, 0) + 1
    if not counts:
        return {}
    top = max(counts.values())
    return {dom: lv for dom, n in counts.items() if n == top}


def _ts(at: str) -> float:
    import datetime as _dt
    try:
        return _dt.datetime.fromisoformat(at).timestamp()
    except ValueError:
        return 0.0


def asks_of(searches: list[dict]) -> list[list[list[dict]]]:
    """Searches grouped into asks (same session, under ASK_GAP_S apart), each ask into rounds (under ROUND_GAP_S
    apart). Timestamps only: an approximation the report labels as such."""
    asks: list[list[list[dict]]] = []
    prev = None
    for r in sorted(searches, key=lambda r: (r.get("run") or "", r["at"])):
        t = _ts(r["at"])
        if prev is None or r.get("run") != prev[0] or t - prev[1] > ASK_GAP_S:
            asks.append([[r]])
        elif t - prev[1] > ROUND_GAP_S:
            asks[-1].append([r])
        else:
            asks[-1][-1].append(r)
        prev = (r.get("run"), t)
    return asks


def _sims(rows: list[dict]) -> dict | None:
    xs = [r["detail"]["top_similarity"] for r in rows if isinstance(r["detail"].get("top_similarity"), (int, float))]
    if not xs:
        return None
    return {"n": len(xs), "min": round(min(xs), 3), "median": round(statistics.median(xs), 3), "max": round(max(xs), 3)}


def summarize(p: Project, questions: int = 15, hits: HitDomains | None = None) -> dict:
    searches = [r for r in p.rows if r["tool"] == "coach_search"]
    by_level = {lv: sum(level_of(r) == lv for r in searches) for lv in LEVELS}
    domains: dict[str, dict[str, int]] = {}
    for r in searches:
        for dom, lv in domain_levels(r, hits).items():
            domains.setdefault(dom, {"strong": 0, "partial": 0, "none": 0})
            if lv in domains[dom]:
                domains[dom][lv] += 1
    by_hits = sum(1 for r in searches if not r["detail"].get("coverage_by_domain") and not r["detail"].get("domains_searched")
                  and domain_levels(r, hits))
    asks = asks_of(searches)
    per_ask = [sum(len(rd) for rd in a) for a in asks]
    rounds = [len(a) for a in asks]
    routed = [r["detail"].get("routing") for r in searches if r["detail"].get("routing")]
    weak = [r for r in searches if level_of(r) in ("partial", "none", "empty")]
    with_text = [r for r in searches if r["detail"].get("query")]
    weak_text = [r for r in weak if r["detail"].get("query")]
    return {
        "pack": p.pack, "project": p.name, "project_id": p.project_id, "note": p.note, "common": p.common,
        "memory": memory(p.rows, questions),
        "calls": len(p.rows), "searches": len(searches), "first": p.rows[0]["at"] if p.rows else None,
        "last": p.rows[-1]["at"] if p.rows else None, "levels": by_level,
        "similarity": {lv: _sims([r for r in searches if level_of(r) == lv]) for lv in ("strong", "partial", "none")},
        "domains": dict(sorted(domains.items())), "domains_from_hits": by_hits,
        "asks": {"n": len(asks), "searches_avg": round(sum(per_ask) / len(asks), 1) if asks else None,
                 "searches_max": max(per_ask, default=None), "rounds_avg": round(sum(rounds) / len(asks), 1) if asks else None,
                 "rounds_max": max(rounds, default=None), "at_guard": sum(n >= SEARCH_GUARD for n in per_ask)},
        "explicit_domains": {"n": sum(x == "explicit" for x in routed), "of": len(routed)},
        "errors": sum(r["outcome"] == "error" for r in p.rows),
        "error_list": [{"at": r["at"][:19], "tool": r["tool"], "error": str(r["detail"].get("error") or "")}
                       for r in reversed(p.rows) if r["outcome"] == "error"][:questions],
        "searches_with_text": len(with_text),
        "weak_questions": [{"at": r["at"][:19], "level": level_of(r), "top_similarity": r["detail"].get("top_similarity"),
                            "domains": sorted(domain_levels(r, hits)) or r["detail"].get("domains_searched") or [],
                            "query": r["detail"]["query"]}
                           for r in reversed(weak_text)][:questions],
    }


def memory(rows: list[dict], questions: int = 15) -> dict:
    """How the coach used the Project's memory (ADR-0026): recall, context and graph calls, follow-through, ties and
    suggestions answered, refused writes. Follow-through: a read (coach_recall or coach_get_context) that showed a
    record marked `edited` or `ties` is one chance; it is followed when a later coach_graph call of the same session
    names one of those records, and loosely followed when any later coach_graph call of the session ran."""
    ok = [r for r in rows if r["outcome"] != "error"]
    recall = [r for r in ok if r["tool"] == "coach_recall"]
    ctx = [r for r in ok if r["tool"] == "coach_get_context"]
    graph = [r for r in ok if r["tool"] == "coach_graph"]
    graph_err = [r for r in rows if r["tool"] == "coach_graph" and r["outcome"] == "error"]
    ops: dict[str, int] = {}
    for r in graph:
        if r["detail"].get("op"):
            ops[r["detail"]["op"]] = ops.get(r["detail"]["op"], 0) + 1
    not_rated = {"recall": sum("hits" not in r["detail"] for r in recall),
                 "context": sum(not r["detail"] for r in ctx), "graph": sum("op" not in r["detail"] for r in graph)}
    order = {id(r): i for i, r in enumerate(rows)}
    chances, missed, strict, loose = 0, [], 0, 0
    for r in sorted(recall + ctx, key=lambda r: order[id(r)]):      # in the order they ran: newest last
        marks = {m: [v for v in r["detail"].get(m) or [] if v != FORGOTTEN] for m in ("edited", "ties")}
        if not any(r["detail"].get(m) for m in ("edited", "ties")):
            continue
        chances += 1
        want = set(marks["edited"]) | set(marks["ties"])
        later = [g for g in graph if g.get("run") == r.get("run") and order[id(g)] > order[id(r)]]
        if later:
            loose += 1
        if any({g["detail"].get("id"), g["detail"].get("to")} & want for g in later):
            strict += 1
        else:
            missed.append({"at": r["at"][:19], "tool": r["tool"],
                           "records": [f"{v} ({m})" for m in ("edited", "ties") for v in marks[m]][:4]})
    links_added = sum(int(r["detail"].get("links_added") or 0) for r in ok if r["tool"] in ("coach_update", "coach_record"))
    links_ended = sum(int(r["detail"].get("links_ended") or 0) for r in ok if r["tool"] == "coach_update")
    answers = {"yes": 0, "never": 0, "later": 0}
    for r in ok:
        d = r["detail"]
        if r["tool"] == "coach_update" and str(d.get("id") or "").startswith("p-") and d.get("status") in ANSWERS:
            answers[ANSWERS[d["status"]]] += 1
    refused = {"old_copy": [], "not_editable": 0, "other": 0}
    for r in rows:
        if r["tool"] not in ("coach_update", "coach_record") or r["outcome"] != "error":
            continue
        msg = str(r["detail"].get("error") or "")
        if "the live copy" in msg:
            live = re.search(r"carried to (\S+)", msg)
            refused["old_copy"].append(f"{r['detail'].get('id') or '?'} → {live.group(1) if live else '?'}")
        elif "can't change" in msg:
            refused["not_editable"] += 1
        else:
            refused["other"] += 1
    return {"recall": len(recall), "expand": sum(bool(r["detail"].get("expand")) for r in recall),
            "recall_empty": sum(r["outcome"] == "empty" for r in recall), "context": len(ctx), "graph": len(graph),
            "graph_ops": dict(sorted(ops.items(), key=lambda kv: -kv[1])),
            "graph_empty": sum(r["outcome"] == "empty" for r in graph),
            "graph_unknown_id": sum("no record" in str(r["detail"].get("error") or "") for r in graph_err),
            "follow": {"chances": chances, "followed": strict, "any_graph": loose, "min": FOLLOW_MIN,
                       "bar": FOLLOW_BAR, "rate": round(strict / chances, 3) if chances else None,
                       "warn": chances >= FOLLOW_MIN and strict / chances < FOLLOW_BAR,
                       "not_followed": list(reversed(missed))[:questions]},
            "links": {"added": links_added, "ended": links_ended}, "suggestions": answers, "refused": refused,
            "not_rated": not_rated}


def _memory_lines(m: dict) -> list[str]:
    """The memory section of one coach's Project, only the lines that have something to say."""
    if not (m["recall"] or m["context"] or m["graph"] or any(m["refused"].values()) or m["links"]["added"]):
        return []
    out = ["  memory:"]
    ops = ", ".join(f"{k} {v}" for k, v in m["graph_ops"].items())
    out.append(f"    recall {m['recall']} (expand {m['expand']}, nothing found {m['recall_empty']}) · context "
               f"{m['context']} · graph {m['graph']}" + (f": {ops}" if ops else "")
               + f" (nothing found {m['graph_empty']}, unknown id {m['graph_unknown_id']})")
    f = m["follow"]
    if f["chances"]:
        pct = round(100 * f["followed"] / f["chances"])
        judged = "" if f["chances"] >= f["min"] else f"   [needs {f['min']} to warn]"
        out.append(f"    follow-through {f['followed']} of {f['chances']} marked reads ({pct}%) went on to coach_graph "
                   f"on a marked record; any coach_graph call after: {f['any_graph']} of {f['chances']}{judged}")
        if f["warn"]:
            out.append(f"    WARNING: follow-through is under {round(100 * f['bar'])}%: read the sessions below; the "
                       f"coach answered about records whose history or ties it didn't open")
        if f["not_followed"]:
            out.append("      not followed: " + " · ".join(f"{x['at'][:10]} {', '.join(x['records'])}"
                                                       for x in f["not_followed"]))
    links, sug = m["links"], m["suggestions"]
    if links["added"] or links["ended"] or any(sug.values()):
        out.append(f"    ties: {links['added']} added, {links['ended']} ended · suggestions answered: {sug['yes']} yes, "
                   f"{sug['never']} never, {sug['later']} later")
    ref = m["refused"]
    if any(ref.values()):
        old = (f"{len(ref['old_copy'])} to an old copy ({', '.join(ref['old_copy'][:6])})" if ref["old_copy"]
               else "0 to an old copy")
        out.append(f"    writes refused: {old}, {ref['not_editable']} field not editable, {ref['other']} other")
    nr = m["not_rated"]
    if any(nr.values()):
        out.append(f"    before details were logged: {nr['recall']} recall, {nr['context']} context, {nr['graph']} graph "
                   "(not rated)")
    return out


def report(projects: list[Project], home: Path | None = None, days: int | None = 30, questions: int = 15) -> dict:
    home = home or engine_home()
    return {"home": str(home), "days": days,
            "projects": [summarize(p, questions, HitDomains.for_pack(home, p.pack)) for p in projects]}


def render(rep: dict, home: Path | None = None) -> str:
    home = home or Path(rep["home"])
    lines: list[str] = []
    if not rep["projects"]:
        return f"gaps: no coach Projects under {rep['home']} (use a coach in a Project first; `/setup` makes one)"
    span = f"last {rep['days']} days" if rep["days"] else "all time"
    for s in rep["projects"]:
        if s.get("common"):
            lines.append(f"{s['pack']} coach · before a Project was chosen (the Common profile's log) · {span}")
        else:
            lines.append(f"{s['pack']} coach · Project {s['project']} ({s['project_id']}) · {span}")
        if s["note"]:
            lines.append(f"  {s['note']}")
            lines.append("")
            continue
        n, lv = s["searches"], s["levels"]
        mem = _memory_lines(s["memory"]) if s.get("memory") else []
        if not n:
            lines.append(f"  {s['calls']} tool call(s), no searches in this window")
            lines.extend(mem)
            lines.append("")
            continue
        rated = n - lv["unrated"]                      # percentages are of the searches that carry a coverage level
        pct = lambda k: f"{lv[k]} ({round(100 * lv[k] / rated)}%)" if rated else str(lv[k])    # noqa: E731
        lines.append(f"  searches {n} ({rated} rated, {lv['unrated']} from before coverage was logged): strong "
                     f"{pct('strong')} · partial {pct('partial')} · none {pct('none')} · empty {lv['empty']}   "
                     f"({s['first'][:10]} to {s['last'][:10]})")
        sim = s["similarity"]
        bits = [f"{k} {v['min']}-{v['max']} (median {v['median']})" for k, v in sim.items() if v]
        if bits:
            lines.append("  top similarity: " + " · ".join(bits))
        a = s["asks"]
        if a["n"]:
            lines.append(f"  asks (grouped by time, approximate) {a['n']}: searches per ask {a['searches_avg']} (max "
                         f"{a['searches_max']}), rounds per ask {a['rounds_avg']} (max {a['rounds_max']}); "
                         f"{a['at_guard']} at the {SEARCH_GUARD}-search guard")
        e = s["explicit_domains"]
        if e["of"]:
            lines.append(f"  Domains named by the host in {e['n']} of {e['of']} searches "
                         f"({round(100 * e['n'] / e['of'])}%); the rest searched the whole Library")
        if s["domains"]:
            note = (f", {s['domains_from_hits']} search(es) attributed by their hits' Domain"
                    if s["domains_from_hits"] else "")
            lines.append(f"  by Domain (strong / partial / none){note}:")
            for dom, c in s["domains"].items():
                lines.append(f"    {dom:14} {c['strong']:3} / {c['partial']:3} / {c['none']:3}")
        if s["errors"]:
            lines.append(f"  {s['errors']} tool error(s), newest first (values typed in are shown as '…'):")
            for e in s.get("error_list") or []:
                lines.append(f"    {e['at']} {e['tool']}: {e['error'] or '(no message)'}")
        weak = lv["partial"] + lv["none"] + lv["empty"]
        if weak and not s["searches_with_text"]:
            lines.append(f"  {weak} weak search(es) but no question text was recorded, so what was missing is unknown. "
                         f"On this machine set {env_prefix(home, s['pack'])}USAGE_TEXT=1 for the {s['pack']} coach "
                         f"(local only; the text never leaves your store).")
        elif s["weak_questions"]:
            lines.append(f"  weak searches (newest first, {len(s['weak_questions'])} of {weak}):")
            for q in s["weak_questions"]:
                sim_s = "" if q["top_similarity"] is None else f" sim {q['top_similarity']}"
                lines.append(f"    {q['at']} {q['level']:7}{sim_s} [{', '.join(q['domains'])}] {q['query']}")
        lines.extend(mem)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ------------------------------------------------------------------------------------------ --replay
RANK = {"empty": 0, "none": 1, "partial": 2, "strong": 3}
# (store, embed, reranker) for one Pack folder's coach, or an exception saying why there is none
Loader = Callable[[str], tuple]


def weak_asks(p: Project) -> list[dict]:
    """The weak searches of one Project whose question text was recorded, newest first, one per distinct search
    (same text, Domains named and Stage)."""
    seen, out = set(), []
    for r in reversed([r for r in p.rows if r["tool"] == "coach_search"]):
        d = r["detail"]
        q = str(d.get("query") or "").strip()
        if not q or level_of(r) not in ("partial", "none", "empty"):
            continue
        named = sorted(d.get("domains_searched") or []) if d.get("routing") == "explicit" else []
        key = (q.lower(), tuple(named), d.get("stage"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"at": r["at"][:19], "query": q, "domains": named, "stage": d.get("stage"),
                    "top_k": d.get("top_k") or 10, "level": level_of(r), "top_similarity": d.get("top_similarity")})
    return out


def search_now(store, embed, reranker, ask: dict) -> dict:
    """One search exactly as the coach's server runs it (`founder_coach.search.search` and
    `founder_coach.coverage.for_search`, routing and calibration from the pack's manifest): {level, top_similarity}."""
    from founder_coach.coverage import Calibration, for_search
    from founder_coach.search import search
    meta = getattr(store, "meta", None) or {}
    gap = meta.get("gap_similarity")
    cal = Calibration.from_meta(meta, float(gap) if isinstance(gap, (int, float)) else None)
    router = meta.get("router") or {}
    route = {k: router[k] for k in ("margin", "max_domains", "top_n") if k in router} if router.get("enabled") else False
    named = [d for d in ask["domains"] if d in set(meta.get("domains") or ())]
    info: dict = {}
    rows = search(store, embed, ask["query"], stage=ask.get("stage"), domains=named or None,
                  route=route if not named else False, top_k=int(ask.get("top_k") or 10), reranker=reranker, info=info)
    cov = for_search(rows, info, meta=meta, calibration=cal, domains=tuple(named), semantic=True)
    sim = info.get("top_similarity")
    return {"level": cov.level if rows else "empty", "top_similarity": None if sim is None else round(sim, 4)}


def replay(projects: list[Project], load: Loader, questions: int = 15,
           run: Callable[..., dict] = search_now) -> dict:
    """Every Project's weak searches with recorded text, searched again against what its coach has installed now.
    One pack per Pack folder, loaded once."""
    loaded: dict[str, tuple] = {}
    out = []
    for p in projects:
        asks = weak_asks(p)
        entry = {"pack": p.pack, "project": p.name, "project_id": p.project_id, "asks": len(asks), "results": [],
                 "note": p.note}
        if not asks:
            entry["note"] = entry["note"] or "no weak search with its question text recorded in this window"
            out.append(entry)
            continue
        if p.pack not in loaded:
            try:
                loaded[p.pack] = ("ok", load(p.pack))
            except Exception as e:                  # noqa: BLE001 -- one coach's missing pack must not stop the rest
                loaded[p.pack] = ("error", f"{type(e).__name__}: {str(e)[:200]}")
        state, got = loaded[p.pack]
        if state == "error":
            entry["note"] = f"cannot search its pack now: {got}"
            out.append(entry)
            continue
        store, embed, reranker = got
        entry["pack_built"] = (getattr(store, "meta", None) or {}).get("built_at")
        for a in asks:
            now = run(store, embed, reranker, a)
            entry["results"].append({**a, "now": now["level"], "now_similarity": now["top_similarity"]})
        res = entry["results"]
        entry["now"] = {lv: sum(r["now"] == lv for r in res) for lv in ("strong", "partial", "none", "empty")}
        entry["better"] = sum(RANK[r["now"]] > RANK[r["level"]] for r in res)
        entry["worse"] = sum(RANK[r["now"]] < RANK[r["level"]] for r in res)
        entry["shown"] = questions
        out.append(entry)
    return {"projects": out}


def render_replay(rep: dict) -> str:
    lines: list[str] = []
    if not rep["projects"]:
        return "gaps --replay: no coach Projects found\n"
    for e in rep["projects"]:
        lines.append(f"{e['pack']} coach · Project {e['project']} ({e['project_id']}) · weak searches replayed now")
        if not e["results"]:
            lines.append(f"  {e['note']}")
            lines.append("")
            continue
        n, now = len(e["results"]), e["now"]
        built = f" (pack built {e['pack_built'][:10]})" if e.get("pack_built") else ""
        lines.append(f"  {n} weak search(es) against the installed pack{built}: now strong {now['strong']} · "
                     f"partial {now['partial']} · none {now['none']} · empty {now['empty']}; "
                     f"better {e['better']}, same {n - e['better'] - e['worse']}, worse {e['worse']}")
        order = sorted(e["results"], key=lambda r: (RANK[r["level"]] - RANK[r["now"]], r["at"]), reverse=False)
        for r in order[:e.get("shown", 15)]:
            then = f"{r['level']}" + ("" if r["top_similarity"] is None else f" {r['top_similarity']}")
            now_s = f"{r['now']}" + ("" if r["now_similarity"] is None else f" {r['now_similarity']}")
            lines.append(f"    {r['at'][:10]} {then:>14} -> {now_s:<14} {r['query']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
