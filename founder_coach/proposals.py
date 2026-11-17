"""Proposed links (ADR-0025): ties the coach suggests between records, saved only on the person's yes.

Seven deterministic rules read the records a coach may see (no model call, nothing sent anywhere) and queue what they
find as proposals (`p-` records). Each proposal says why it was made and how sure the rule is (`high`: pre-ticked in a
review; `review`: shown with its reason). The person answers with coach_update: accepted (the tie is saved, logged
with the proposal's reason), rejected (never proposed again: its fingerprint is kept), snoozed (back in four weeks).

The rules:
  R1 a Decision's words name another Decision's id    -> supersedes (a replace word near it) or related
  R2 a Decision says it replaces something, and an earlier Decision matches its words -> supersedes
  R3 an open task with no Goal while exactly one Goal is active -> set its goal (review tier: a guess, ADR-0028)
  R4 a capitalised name in three or more records, at least once where a person is meant (after with, from, by,
     asked, told, emailed, call or met, or as a task's first word) -> a Person; a name right after a confirmed
     Person's name -> another name (alias) of that Person. Weekdays, months, places and tools are never names.
  R5 a task's words start with a Person's name ("Lena drafts ...") -> owned_by; "<Person> decided" -> decided_by
  R6 the same blocker in two or more Check-ins         -> an Issue that blocks the closest task or Goal
  R7 a Note with no links                              -> about the record it matches best

What the person's answers teach (ADR-0028): one suggestion per pair of records (a pair already tied in any way, in
either direction, or already suggested, is skipped), and a rule rejected MUTE_AFTER times in a Project with no yes is
muted there: the coach says so once, and `coach_update` on the rule's id (`p-r3`) with status accepted brings it back.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re


SNOOZE_DAYS = 28
MUTE_AFTER = 5                    # rejections in a Project, with no yes, that mute a rule there (ADR-0028)
RULES = {"R1": "tie a Decision to another Decision it names", "R2": "mark a Decision as replacing an earlier one",
         "R3": "serve the only active Goal with a task that has none", "R4": "add a name seen in several records as a "
         "person", "R5": "name a task's owner from its first word", "R6": "track a blocker that recurs as an Issue",
         "R7": "tie a Note with no links to the record it matches"}
_RULE_ID = re.compile(r"^p-(r[1-7])$", re.I)
_CUES = {"with", "from", "by", "asked", "ask", "asks", "told", "tell", "tells", "emailed", "email", "emails", "call",
         "called", "calls", "met", "meet", "meets"}
SHOW_MAX = 2                      # a proposal skipped twice is not shown again until the rules find it anew
REVIEW_BATCH = 8
CHECKIN_MAX = 5
TIERS = ("high", "review")
_WORD = re.compile(r"[a-z0-9]+")
_REPLACE = re.compile(r"\b(replac\w*|supersed\w*|instead of|no longer|switch(?:ed|ing)? (?:from|to)|revers\w*|"
                      r"drop(?:ped|ping)? the|scrap\w*|abandon\w*|pivot\w*)\b", re.I)
_DECIDED = re.compile(r"\b(decided|chose|chooses|picked|agreed|approved)\b", re.I)
_ID = re.compile(r"\b([a-z]{1,2})-([0-9a-f]{4})\b")
_NAME = re.compile(r"(?<![\w-])([A-Z][a-z]{2,})\b")
_STOP = set("""
The This That These Those With For And But Not Use Run Send Build Write Check Share Review Ask Lock Message Apply
Until After Before When Each Every Our Their Your His Her Its They Them Then There Here What Which Who Why How Also
Yes Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August
September October November December Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec Week Weeks Today Tomorrow
Team Teams Goal Goals Decision Decisions Note Notes Draft Drafts Plan Plans Call Calls Email Emails Doc Docs Demo MVP
Google Drive Gmail Slack Notion Linear Jira Zoom Meet WhatsApp Telegram Discord Claude ChatGPT OpenAI Anthropic GitHub
Figma Excel Sheets Word Docs LinkedIn Twitter Apple Microsoft Amazon AWS YC Techstars Speedrun Winter Summer Spring
Fall Batch Demo Day Hour Expert Partner Partners Customer Customers Founder Founders Investor Investors Pilot Pilots
Mon Tue Tues Wed Thu Thur Thurs Fri Sat Sun Noon Midnight Morning Evening Tonight Yesterday Weekend Quarter Python
Java Javascript Typescript Rust Swift Kotlin Scala Golang React Vue Angular Node Django Flask Fastapi Rails Docker
Kubernetes Linux Windows Ubuntu Postgres Postgresql Mysql Sqlite Redis Mongo Mongodb Kafka Spark Airflow Pandas Numpy
Jupyter Chrome Safari Firefox Android Iphone Ipad Macos Obsidian Markdown Cursor Gemini Copilot Vercel Heroku Netlify
Supabase Firebase Stripe Shopify Hubspot Salesforce Canva Loom Calendly Typeform Airtable Zapier Trello Asana Dropbox
Outlook Teams Webex Youtube Instagram Facebook Meta Tiktok Reddit Substack Medium Wordpress Webflow Alabama Alaska
Arizona Arkansas California Colorado Connecticut Delaware Florida Hawaii Idaho Illinois Indiana Iowa Kansas Kentucky
Louisiana Maine Maryland Massachusetts Michigan Minnesota Mississippi Missouri Montana Nebraska Nevada Hampshire
Jersey Mexico York Ohio Oklahoma Oregon Pennsylvania Rhode Tennessee Texas Utah Vermont Wisconsin Wyoming America
Canada India China Japan Germany France Italy Spain Brazil Europe Asia Africa Australia England Britain London Berlin
Tokyo Singapore Dubai Seattle Boston Chicago Denver Atlanta Detroit Angeles Bangalore Bengaluru Mumbai Delhi Pune
Hyderabad Chennai Toronto Vancouver Silicon Valley Bay Area
""".split())


def _words(text) -> set[str]:
    return {w for w in _WORD.findall(str(text or "").lower()) if len(w) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _fp(payload: dict) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


def _text_of(kind: str, r: dict) -> str:
    if kind == "decision":
        return f"{r.get('text', '')} {r.get('reasoning', '')}"
    if kind == "commitment":
        return f"{r.get('action', '')} {r.get('outcome', '')} {r.get('result_note') or ''}"
    if kind == "checkin":
        return " ".join([str(r.get("summary") or ""), *map(str, r.get("wins") or []), *map(str, r.get("blockers") or [])])
    if kind == "note":
        return f"{r.get('title', '')} {r.get('summary', '')}"
    if kind == "goal":
        return f"{r.get('text', '')} {r.get('measure') or ''}"
    return str(r.get("text") or r.get("name") or "")


def candidates(snap, profile_words: set[str] | None = None) -> list[dict]:
    """Every proposal the rules find in a snapshot (what one coach may read), as {payload, rule, tier, why}."""
    out: list[dict] = []
    decisions = sorted(snap.decisions, key=lambda d: (d.get("decided_at") or "", d["id"]))
    by_id = {d["id"]: d for d in decisions}
    people = [p for p in getattr(snap, "people", []) if p.get("status", "active") == "active"]
    names = {}
    for p in people:
        for n in [p["name"], *(p.get("aliases") or [])]:
            names[n.lower()] = p["id"]
    # R1 and R2: Decisions that replace or name another
    for i, d in enumerate(decisions):
        if d.get("status", "accepted") != "accepted" and not d.get("superseded_by"):
            continue
        text = f"{d.get('text', '')} {d.get('reasoning', '')}"
        named = [f"{a}-{b}" for a, b in _ID.findall(text) if f"{a}-{b}" in by_id and f"{a}-{b}" != d["id"]]
        for old in dict.fromkeys(named):
            o = by_id[old]
            if _REPLACE.search(text) and (o.get("decided_at") or "") <= (d.get("decided_at") or "") \
                    and o.get("status", "accepted") == "accepted":
                out.append({"payload": {"op": "supersede", "new": d["id"], "old": old}, "rule": "R1", "tier": "high",
                            "why": f"{d['id']} names {old} and says it replaces it"})
            else:
                out.append({"payload": {"op": "link", "src": d["id"], "dst": old, "type": "related"}, "rule": "R1",
                            "tier": "high", "why": f"{d['id']} names {old}"})
        if not named and _REPLACE.search(text) and d.get("status", "accepted") == "accepted":
            mine = _words(text)
            best, score = None, 0.0
            for o in decisions[:i]:
                if o.get("status", "accepted") != "accepted":
                    continue
                sc = _jaccard(mine, _words(f"{o.get('text', '')} {o.get('reasoning', '')}"))
                if sc > score:
                    best, score = o, sc
            if best is not None and score >= 0.2:
                out.append({"payload": {"op": "supersede", "new": d["id"], "old": best["id"]}, "rule": "R2",
                            "tier": "review", "why": f"{d['id']} says it replaces something and its words match "
                                                     f"{best['id']} ({score:.0%})"})
        m = re.match(r"\s*([A-Z][\w'-]+)\s+(?:has\s+)?" + _DECIDED.pattern, d.get("text") or "")
        if m and m.group(1).lower() in names:
            out.append({"payload": {"op": "link", "src": d["id"], "dst": names[m.group(1).lower()],
                                    "type": "decided_by"}, "rule": "R5", "tier": "high",
                        "why": f"{d['id']} says {m.group(1)} decided"})
    # R3: open tasks with no Goal, exactly one active Goal
    active = [g for g in snap.goals if g.get("status") == "active"]
    from .graph import thread_rows
    threads = thread_rows(snap.commitments)
    for tid, rows in threads.items():
        last = rows[-1]
        if last.get("status") == "open" and not any(c.get("goal_id") for c in rows) and len(active) == 1:
            out.append({"payload": {"op": "goal_id", "commitment": last["id"], "goal": active[0]["id"]}, "rule": "R3",
                        "tier": "review", "why": f"{last['id']} serves no Goal and {active[0]['id']} is the only "
                                                 "active one"})
        # R5: owners
        m = re.match(r"\s*([A-Z][\w'-]+)\b", last.get("action") or "")
        if m and m.group(1).lower() in names and last.get("status") == "open":
            out.append({"payload": {"op": "link", "src": last["id"], "dst": names[m.group(1).lower()],
                                    "type": "owned_by"}, "rule": "R5", "tier": "high",
                        "why": f"the task starts with {m.group(1)}"})
    # R4: names in three or more records
    texts = ([("goal", r) for r in snap.goals] + [("commitment", r) for r in snap.commitments]
             + [("decision", r) for r in snap.decisions] + [("checkin", r) for r in snap.checkins]
             + [("note", r) for r in snap.notes])
    seen: dict[str, set[str]] = {}
    lower_seen: set[str] = set()
    follows: dict[str, set[str]] = {}
    cued: set[str] = set()                                   # a person is meant here at least once
    after_person: dict[str, dict[str, set[str]]] = {}         # name -> confirmed Person it follows -> records
    for kind, r in texts:
        t = _text_of(kind, r)
        lower_seen |= set(re.findall(r"\b[a-z][a-z]{2,}\b", t))
        if kind == "commitment":                               # a task's first word is who does it ("Lena drafts")
            first = _NAME.match((r.get("action") or "").lstrip())
            if first:
                cued.add(first.group(1))
        for sent in re.split(r"(?<=[.!?:;])\s+|\n", t):
            toks = list(_NAME.finditer(sent))
            for k, mt in enumerate(toks):
                w = mt.group(1)
                prev = sent[:mt.start()].rstrip().split(" ")[-1] if mt.start() else ""
                bare = prev.strip("(,;:").lower()
                if bare in _CUES:
                    cued.add(w)
                if bare in names and prev.strip("(")[:1].isupper():
                    after_person.setdefault(w, {}).setdefault(names[bare], set()).add(r["id"])
                if mt.start() == len(sent) - len(sent.lstrip()):
                    continue                                   # a sentence's first word proves nothing
                seen.setdefault(w, set()).add(r["id"])
                follows.setdefault(w, set()).add(prev)
    skip = set(_STOP) | {w.capitalize() for w in (profile_words or set())}
    person_name = {p["id"]: p["name"] for p in people}
    for w, ids in sorted(seen.items()):
        if len(ids) < 3 or w in skip or w.lower() in lower_seen or w.lower() in names:
            continue
        if after_person.get(w):                                # right after a confirmed Person: their other name
            pid, recs = max(after_person[w].items(), key=lambda kv: (len(kv[1]), kv[0]))
            out.append({"payload": {"op": "alias", "person": pid, "alias": w}, "rule": "R4", "tier": "review",
                        "why": f"{w} follows {person_name.get(pid, pid)} in {len(recs)} record(s)"})
            continue
        prevs = follows.get(w, set())
        if prevs and all(p[:1].isupper() and p in seen for p in prevs):
            continue                                           # always after another name: a surname
        if w not in cued:
            continue                                           # never where a person is meant: a company, a place
        out.append({"payload": {"op": "person", "name": w}, "rule": "R4", "tier": "review",
                    "why": f"{w} appears in {len(ids)} records"})
    # R6: blockers that recur
    blockers = []
    for k in sorted(snap.checkins, key=lambda k: (k.get("created_at") or "", k["id"])):
        for b in k.get("blockers") or []:
            blockers.append((k["id"], str(b), _words(b)))
    used = set()
    issue_words = [_words(i.get("text")) for i in getattr(snap, "issues", [])]
    for i, (kid, text, ws) in enumerate(blockers):
        if i in used or not ws:
            continue
        group = [j for j, (k2, _, w2) in enumerate(blockers) if j != i and k2 != kid and _jaccard(ws, w2) >= 0.5]
        if not group or any(_jaccard(ws, iw) >= 0.5 for iw in issue_words):
            continue
        used |= {i, *group}
        latest = blockers[max([i, *group])][1]
        target, score = None, 0.0
        for tid, rows in threads.items():
            if rows[-1].get("status") == "open":
                sc = _jaccard(ws, _words(_text_of("commitment", rows[-1])))
                if sc > score:
                    target, score = rows[-1]["id"], sc
        if score < 0.2:
            target = active[0]["id"] if len(active) == 1 else None
        out.append({"payload": {"op": "issue", "text": latest, "blocks": target}, "rule": "R6", "tier": "review",
                    "why": f"this blocker is in {len({kid, *(blockers[j][0] for j in group)})} Check-ins"})
    # R7: Notes with no links
    linked = {ln["src"] for ln in snap.links}
    pool = ([("goal", r) for r in snap.goals] + [("decision", r) for r in snap.decisions]
            + [("commitment", rows[-1]) for rows in threads.values()])
    for n in snap.notes:
        if n["id"] in linked or n.get("superseded_by"):
            continue
        ws = _words(_text_of("note", n))
        best, score = None, 0.0
        for kind, r in pool:
            sc = _jaccard(ws, _words(_text_of(kind, r)))
            if sc > score:
                best, score = r["id"], sc
        if best and score >= 0.12:
            out.append({"payload": {"op": "link", "src": n["id"], "dst": best, "type": "about"}, "rule": "R7",
                        "tier": "review", "why": f"its words match {best} ({score:.0%})"})
    return out


def refresh(store) -> int:
    """Queue what the rules find now. A payload already queued (pending, answered or snoozed) is never queued again:
    a rejection is permanent. Returns how many are new."""
    from . import vault
    snap = vault.from_store(store)
    words = set()
    for p in snap.profile:
        if p["field"] in ("company", "name", "one_liner", "system", "goal"):
            words |= {w for w in re.findall(r"[A-Za-z]{3,}", str(p["value"]))}
    words |= {w for w in re.findall(r"[A-Za-z]{3,}", snap.name)}
    new = 0
    off = muted(store)
    tied = _tied_pairs(snap)
    with store._lock:
        asked = {}
        for r in store.db.execute("SELECT fingerprint, payload FROM proposals WHERE founder_id=? AND coach=?",
                                  (store.fid, store.coach)):
            pr = _pair(json.loads(r["payload"]))
            if pr:
                asked.setdefault(pr, set()).add(r["fingerprint"])
        now = store._iso()
        store.db.execute("BEGIN IMMEDIATE")
        try:
            for c in candidates(snap, {w.lower() for w in words}):
                if c["rule"] in off:
                    continue                                   # muted in this Project (ADR-0028)
                fp = _fp(c["payload"])
                pr = _pair(c["payload"])
                if pr and (pr in tied or asked.get(pr, {fp}) - {fp}):
                    continue                                   # one suggestion per pair of records
                if pr:
                    asked.setdefault(pr, set()).add(fp)
                pid = store._new_id("proposal")
                cur = store.db.execute(
                    "INSERT OR IGNORE INTO proposals (id, founder_id, coach, fingerprint, rule, tier, payload, why, "
                    "status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (pid, store.fid, store.coach, fp, c["rule"], c["tier"], json.dumps(c["payload"]), c["why"],
                     "pending", now))
                new += cur.rowcount
            store.db.execute("COMMIT")
        except BaseException:
            store.db.execute("ROLLBACK")
            raise
    return new


def pending(store, limit: int = REVIEW_BATCH, mark_shown: bool = False) -> tuple[list[dict], int]:
    """Proposals waiting for an answer (snoozed ones come back after their date), high tier first; and how many."""
    today = store.today().isoformat()
    with store._lock:
        rows = [dict(r) for r in store.db.execute(
            "SELECT * FROM proposals WHERE founder_id=? AND coach=? AND (status='pending' OR (status='snoozed' AND "
            "snoozed_until<=?)) AND shown<? ORDER BY CASE tier WHEN 'high' THEN 0 ELSE 1 END, shown, created_at, id",
            (store.fid, store.coach, today, SHOW_MAX))]
    live = []
    off = muted(store)
    for r in rows:
        r["payload"] = json.loads(r["payload"])
        if r["rule"] not in off and _still_applies(store, r["payload"]):
            live.append(r)
    page = live[:limit]
    if mark_shown and page:
        with store._lock:
            store.db.executemany("UPDATE proposals SET shown=shown+1 WHERE id=?", [(r["id"],) for r in page])
    return [describe(store, r) for r in page], len(live)


def _still_applies(store, p: dict) -> bool:
    op = p.get("op")
    ids = [p.get(k) for k in ("src", "dst", "new", "old", "commitment", "goal", "blocks", "person") if p.get(k)]
    if any(store.get(i, links=False) is None for i in ids):
        return False
    if op in ("link", "supersede") and _tied(store, *sorted(_pair(p) or ())):
        return False                                           # the pair got a tie meanwhile: one per pair
    if op == "alias":
        per = store.get(p["person"], links=False) or {}
        have = {str(a).lower() for a in [per.get("name"), *(_aliases(per))]}
        return per.get("status", "active") == "active" and p["alias"].lower() not in have
    if op == "supersede":
        return (store.get(p["old"], links=False) or {}).get("status", "accepted") == "accepted"
    if op == "goal_id":
        return not (store.get(p["commitment"], links=False) or {}).get("goal_id")
    if op == "link":
        out, _ = store.links_of(p["src"])
        return not any(x["to"] == p["dst"] and x["type"] == p["type"] for x in out)
    return True


def _title(store, rid: str | None) -> str:
    if not rid:
        return ""
    r = store.get(rid, links=False) or {}
    return str(r.get("text") or r.get("action") or r.get("title") or r.get("name") or r.get("summary") or rid)[:80]


def describe(store, r: dict) -> dict:
    """A proposal as the person reads it: what would be saved, in words, and why."""
    p = r["payload"]
    op = p["op"]
    if op == "link":
        what = f"{_title(store, p['src'])} —{p['type']}→ {_title(store, p['dst'])}"
    elif op == "supersede":
        what = f"{_title(store, p['new'])} —supersedes→ {_title(store, p['old'])}"
    elif op == "goal_id":
        what = f"{_title(store, p['commitment'])} —serves→ {_title(store, p['goal'])}"
    elif op == "person":
        what = f"add {p['name']} as a person in this Project"
    elif op == "alias":
        what = f"{p['alias']} is another name for {_title(store, p['person'])}"
    else:
        what = f"track as an Issue: {p['text'][:100]}" + (f" (blocks {_title(store, p['blocks'])})"
                                                          if p.get("blocks") else "")
    return {"id": r["id"], "what": what, "why": r["why"], "tier": r["tier"], "rule": r["rule"]}


def decide(store, pid: str, status: str | None, source: str) -> dict:
    """The person's answer to one proposal, inside the caller's transaction: accepted saves the tie (logged with the
    proposal's reason unless the person gave their own), rejected is kept so it is never proposed again, snoozed
    comes back in four weeks."""
    if _RULE_ID.match(pid or ""):
        return _answer_rule(store, _RULE_ID.match(pid).group(1).upper(), status, source)
    row = store.db.execute("SELECT * FROM proposals WHERE id=? AND founder_id=? AND coach=?",
                           (pid, store.fid, store.coach)).fetchone()
    if row is None:
        raise _err(f"no proposal {pid!r}; pending ones come from coach_graph op proposals")
    if status not in ("accepted", "rejected", "snoozed"):
        raise _err("answer a proposal with status accepted, rejected or snoozed")
    if row["status"] in ("accepted", "rejected"):
        raise _err(f"{pid} was already {row['status']}")
    now = store._iso()
    payload = json.loads(row["payload"])
    reason, actor = getattr(store, "_why", (None, None))
    reason = reason or f"{status} proposal {pid}: {row['why']}"
    store._why = (reason, actor)
    out: dict = {"id": pid, "before": {"status": row["status"]}, "warnings": []}
    if status == "accepted":
        if not _still_applies(store, payload):
            raise _err(f"{pid} no longer applies (a record changed or the tie exists already); reject it")
        out["applied"] = _apply(store, payload, now, source)
    until = (store.today() + dt.timedelta(days=SNOOZE_DAYS)).isoformat() if status == "snoozed" else None
    store.db.execute("UPDATE proposals SET status=?, decided_at=?, snoozed_until=? WHERE id=?",
                     (status, now if status != "snoozed" else None, until, pid))
    store._change("proposal", pid, status, {"status": row["status"]},
                  {"status": status, "payload": payload, **({"snoozed_until": until} if until else {})}, source,
                  reason=reason, actor=actor)
    out["after"] = {"status": status, **({"snoozed_until": until} if until else {})}
    return out


def _apply(store, p: dict, now: str, source: str) -> dict:
    op = p["op"]
    if op == "link":
        store._link(p["src"], p["dst"], p["type"], now, source)
        return {"link": [p["src"], p["type"], p["dst"]]}
    if op == "supersede":
        old = store.get(p["old"], links=False)
        store.db.execute("UPDATE decisions SET status='superseded', superseded_by=?, superseded_at=? WHERE id=?",
                         (p["new"], now, p["old"]))
        store._change("decision", p["old"], "supersede", old, store.get(p["old"], links=False), source)
        return {"superseded": p["old"], "by": p["new"]}
    if op == "goal_id":
        before = store.get(p["commitment"], links=False)
        store.db.execute("UPDATE commitments SET goal_id=? WHERE id=?", (p["goal"], p["commitment"]))
        store._change("commitment", p["commitment"], "update", before, store.get(p["commitment"], links=False), source)
        return {"commitment": p["commitment"], "goal_id": p["goal"]}
    if op == "person":
        return {"person": store._record_entity({"kind": "person", "name": p["name"]}, source,
                                               *store._why)["ids"][0]}
    if op == "alias":
        before = store.get(p["person"], links=False)
        aliases = [*_aliases(before), p["alias"]]
        store.db.execute("UPDATE people SET aliases=? WHERE id=?", (json.dumps(aliases), p["person"]))
        store._change("person", p["person"], "update", before, store.get(p["person"], links=False), source,
                      reason=store._why[0], actor=store._why[1])
        return {"person": p["person"], "aliases": aliases}
    links = [{"to": p["blocks"], "type": "blocks"}] if p.get("blocks") else []
    return {"issue": store._record_entity({"kind": "issue", "text": p["text"], "links": links}, source,
                                          *store._why)["ids"][0]}


# ---- one suggestion per pair; a rule the person keeps rejecting is muted in the Project (ADR-0028) -----------------

def _pair(p: dict) -> frozenset | None:
    """The two records a suggestion would tie, in either order; None for one that ties no pair (a person, an Issue)."""
    a, b = {"link": ("src", "dst"), "supersede": ("new", "old"), "goal_id": ("commitment", "goal"),
            "alias": ("person", "alias")}.get(p.get("op"), (None, None))
    return frozenset((p[a], p[b])) if a and p.get(a) and p.get(b) else None


def _tied_pairs(snap) -> set[frozenset]:
    out = {frozenset((ln["src"], ln["dst"])) for ln in snap.links}
    out |= {frozenset((d["id"], d["superseded_by"])) for d in snap.decisions if d.get("superseded_by")}
    out |= {frozenset((c["id"], c["goal_id"])) for c in snap.commitments if c.get("goal_id")}
    return out


def _tied(store, a: str, b: str) -> bool:
    out, into = store.links_of(a)
    if any(x.get("to") == b for x in out) or any(x.get("from") == b for x in into):
        return True
    for x, y in ((a, b), (b, a)):
        r = store.get(x, links=False) or {}
        if r.get("superseded_by") == y or r.get("goal_id") == y:
            return True
    return False


def _aliases(person: dict | None) -> list[str]:
    al = (person or {}).get("aliases") or []
    if isinstance(al, str):
        try:
            al = json.loads(al)
        except ValueError:
            al = []
    return [str(a) for a in al]


def _key(store, rule: str, what: str) -> str:
    return f"proposals:{store.coach}:{rule}:{what}"


def _meta(store, key: str) -> str | None:
    row = store.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def muted(store) -> dict[str, int]:
    """rule -> rejections, for the rules this coach has muted in this Project: MUTE_AFTER rejections and no yes
    since the rule was last brought back."""
    out: dict[str, int] = {}
    with store._lock:
        rows = store.db.execute("SELECT rule, status, decided_at FROM proposals WHERE founder_id=? AND coach=? AND "
                                "status IN ('accepted', 'rejected')", (store.fid, store.coach)).fetchall()
        since = {rule: _meta(store, _key(store, rule, "revived_at")) or "" for rule in RULES}
    counts: dict[str, list[int]] = {}
    for r in rows:
        if (r["decided_at"] or "") <= since.get(r["rule"], ""):
            continue
        c = counts.setdefault(r["rule"], [0, 0])
        c[0 if r["status"] == "accepted" else 1] += 1
    for rule, (yes, no) in counts.items():
        if no >= MUTE_AFTER and not yes:
            out[rule] = no
    return out


def muted_news(store) -> list[dict]:
    """Rules muted since the person was last told, each told once: {id, rule, what, rejected}."""
    news = []
    for rule, n in sorted(muted(store).items()):
        key = _key(store, rule, "told")
        with store._lock:
            told = _meta(store, key)
            if told:
                continue
            store.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, store._iso()))
        news.append({"id": f"p-{rule.lower()}", "rule": rule, "what": RULES[rule], "rejected": n})
    return news


def _answer_rule(store, rule: str, status: str | None, source: str) -> dict:
    """coach_update on `p-r3`: accepted brings a muted rule back in this Project (its answers start again from
    zero); rejected keeps it muted. Inside the caller's transaction."""
    if status not in ("accepted", "rejected"):
        raise _err(f"answer p-{rule.lower()} with status accepted (suggest again) or rejected (keep it muted)")
    was = muted(store)
    if rule not in was:
        raise _err(f"rule p-{rule.lower()} is not muted in this Project; it keeps suggesting")
    if status == "accepted":
        now = store._iso()
        store.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                         (_key(store, rule, "revived_at"), now))
        store.db.execute("DELETE FROM meta WHERE key=?", (_key(store, rule, "told"),))
    reason, actor = getattr(store, "_why", (None, None))
    store._change("proposal", f"p-{rule.lower()}", "unmute" if status == "accepted" else "mute",
                  {"muted": rule in was}, {"muted": status != "accepted"}, source,
                  reason=reason or f"{status} rule {rule}: {RULES[rule]}", actor=actor)
    return {"id": f"p-{rule.lower()}", "before": {"muted": rule in was}, "after": {"muted": status != "accepted"},
            "warnings": []}


def _err(msg: str):
    from .store import StoreError
    return StoreError(msg)
