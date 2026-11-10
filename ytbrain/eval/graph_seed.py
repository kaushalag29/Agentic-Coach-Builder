"""Made-up Projects written through the coach's store over three weeks, for the graph benchmark (tests/test_graph.py)
and gate G9 (`ytbrain eval coach --gate g9`): "Acme Dental" for the founder coach (the offline benchmark and the
host-run gate ask about exactly the same records), a "Ledger API" system for the coding coach and a retirement goal
for the investor coach (no Goals: the investor Pack keeps none). `seed(pack, home)` picks one.

Imports only the coach runtime (`founder_coach`), never the pipeline, so tests can use it without the extras."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

START = "2026-09-21T09:00:00+00:00"          # Monday of 2026-W39
TODAY = "2026-10-07T10:00:00+00:00"          # Wednesday of 2026-W41: when G9's questions are asked


class Clock:
    def __init__(self, when: str = START):
        self.t = dt.datetime.fromisoformat(when)

    def __call__(self) -> dt.datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t += dt.timedelta(**kw)


def acme(home: Path, people: bool = False, coach: str | None = None, extra: bool = False):
    """Three weeks of a made-up Project. Returns (store, ids by name). `people` adds who decided what, an owner and a
    blocker (ADR-0025), recorded in the third week; `extra` adds what G9's held-out questions ask about (a Decision
    changed twice, a blocked task with an owner); the core benchmark leaves both out."""
    from founder_coach.store import FounderStore
    clock = Clock()
    s = FounderStore(home, clock=clock, **({"coach": coach} if coach else {}))
    s.peers = {}
    s.update_profile({"timezone": "UTC", "company": "Acme Dental"})
    if extra:                                    # a real Project has these: no setup offers in the answers
        s.update_profile({"stage": "mvp", "customer": "independent dental clinics", "checkin_day": "mon"})
    ids: dict[str, str] = {}
    rec = lambda e: s.record(e)["ids"]                                  # noqa: E731
    ids["g_partners"] = rec({"kind": "goal", "text": "Ten paying design partners", "measure": "ten signed"})[0]
    ids["g_onboard"] = rec({"kind": "goal", "text": "Ship self-serve onboarding", "measure": "live"})[0]
    ids["d_dental"] = rec({"kind": "decision", "text": "Sell to dental clinics first", "reasoning": "they feel it"})[0]
    ids["d_charge"] = rec({"kind": "decision", "text": "Charge from day one", "reasoning": "paying users tell"})[0]
    c = rec({"kind": "commitments", "items": [
        {"action": "Email 20 dentists", "outcome": "5 calls booked", "goal_id": ids["g_partners"]},
        {"action": "Write the onboarding checklist", "outcome": "a checklist", "goal_id": ids["g_onboard"]},
        {"action": "Call Marco about the pilot", "outcome": "a yes or a no"}]})
    ids["c_email"], ids["c_check"], ids["c_call"] = c
    ids["k1"] = rec({"kind": "checkin", "summary": "Week one", "wins": ["3 replies"], "blockers": ["no price yet"]})[0]
    clock.advance(days=7)                                               # 2026-W40
    ids["c_email2"] = s.update(ids["c_email"], status="carried",
                               note="3 replies, no calls yet" if extra else None)["new_id"]
    ids["c_call2"] = s.update(ids["c_call"], status="carried")["new_id"]
    s.update(ids["c_check"], status="done", reason="checklist shared with two pilots")
    ids["d_dash"] = rec({"kind": "decision", "text": "Drop the analytics dashboard from the MVP",
                         "reasoning": "nobody asked for it"})[0]
    ids["n_scope"] = rec({"kind": "note", "title": "Why the dashboard went", "summary": "Pilots never opened it.",
                          "type": "discussion", "origin": "user",
                          "links": [{"to": ids["d_dash"], "type": "about"},
                                    {"to": ids["g_onboard"], "type": "supports"}]})[0]
    ids["k2"] = rec({"kind": "checkin", "summary": "Week two", "wins": [], "blockers": ["Marco busy"]})[0]
    if extra:
        ids["d_price"] = rec({"kind": "decision", "text": "Price the pilot at $500 a month",
                              "reasoning": "what clinics pay for software today"})[0]
    clock.advance(days=7)                                               # 2026-W41
    s.update(ids["d_dental"], changes={"text": "Sell to independent dental clinics first"},
             reason="chains buy centrally; independents decide in a week")
    ids["c_email3"] = s.update(ids["c_email2"], status="carried",
                               note="5 calls booked, 2 no-shows" if extra else None)["new_id"]
    ids["c_call3"] = s.update(ids["c_call2"], status="carried")["new_id"]
    ids["n_scope2"] = rec({"kind": "note", "title": "Dashboard: what pilots said", "summary": "Two asked for exports.",
                           "type": "research", "origin": "user", "supersedes": ids["n_scope"],
                           "links": [{"to": ids["d_dash"], "type": "about"}]})[0]
    if people:
        ids["p_neha"] = rec({"kind": "person", "name": "Neha", "role": "my cofounder"})[0]
        ids["p_marco"] = rec({"kind": "person", "name": "Marco", "role": "runs the Smile Studio clinic"})[0]
        s.update(ids["d_charge"], links=[{"to": ids["p_neha"], "type": "decided_by"}],
                 reason="Neha made this call in week one")
        s.update(ids["c_email3"], links=[{"to": ids["p_neha"], "type": "owned_by"}])
        ids["i_travel"] = rec({"kind": "issue", "text": "Marco is travelling until 20 October",
                               "links": [{"to": ids["c_call3"], "type": "blocks"}]})[0]
    if extra:
        ids["p_omar"] = rec({"kind": "person", "name": "Omar", "role": "runs our sales calls"})[0]
        s.update(ids["c_call3"], links=[{"to": ids["p_omar"], "type": "owned_by"}])
        s.update(ids["d_price"], changes={"text": "Price the pilot at $300 a month"},
                 reason="three clinics balked at $500")
        clock.advance(days=1)                                           # Tuesday of 2026-W41
        s.update(ids["d_price"], changes={"text": "Price the pilot at $300 a month, free for the first month"},
                 reason="Marco asked for a trial month before paying")
    return s, ids


def _profile(s, facts: dict) -> None:
    """Profile facts of another Pack than the one this process runs as (its field list is the running Pack's)."""
    import json
    now = s.clock().isoformat()
    for field, value in facts.items():
        s.db.execute("INSERT INTO profile_facts (founder_id, coach, field, value, valid_from, superseded_at, "
                     "confirmed_at, source) VALUES (?,?,?,?,?,NULL,?,?)",
                     (s.fid, s.coach, field, json.dumps(value), now, now, "seed"))


def ledger(home: Path):
    """The coding coach's made-up system: caching and a queue migration over three weeks, an edited Decision, a
    superseded Note, carried work, who decided, who owns and a blocker."""
    from founder_coach.store import FounderStore
    clock = Clock()
    s = FounderStore(home, clock=clock, coach="coding")
    s.peers = {}
    _profile(s, {"timezone": "UTC", "system": "Ledger API, the billing service", "stack": "Python, Postgres, Redis"})
    ids: dict[str, str] = {}
    rec = lambda e: s.record(e)["ids"]                                  # noqa: E731
    ids["g_p99"] = rec({"kind": "goal", "text": "Checkout p99 latency under 200 ms", "measure": "p99 < 200 ms"})[0]
    ids["g_queue"] = rec({"kind": "goal", "text": "Move billing events to the new queue", "measure": "all events"})[0]
    ids["d_cache"] = rec({"kind": "decision", "text": "Cache product reads in Redis",
                          "reasoning": "reads are 90% of checkout traffic"})[0]
    ids["d_pg"] = rec({"kind": "decision", "text": "Keep Postgres as the only database",
                       "reasoning": "one store to operate and back up"})[0]
    c = rec({"kind": "commitments", "items": [
        {"action": "Add tracing to the checkout path", "outcome": "a trace per request", "goal_id": ids["g_p99"]},
        {"action": "Write the queue consumer", "outcome": "consumer merged", "goal_id": ids["g_queue"]},
        {"action": "Ask Ravi for the load-test budget", "outcome": "a number"}]})
    ids["c_trace"], ids["c_consumer"], ids["c_ravi"] = c
    ids["k1"] = rec({"kind": "checkin", "summary": "Week one", "wins": ["cache design agreed"], "blockers": []})[0]
    clock.advance(days=7)                                               # 2026-W40
    ids["c_trace2"] = s.update(ids["c_trace"], status="carried", note="spans missing around the payment call")["new_id"]
    ids["c_ravi2"] = s.update(ids["c_ravi"], status="carried")["new_id"]
    s.update(ids["c_consumer"], status="done", reason="merged behind a flag")
    ids["d_flag"] = rec({"kind": "decision", "text": "Ship the queue behind a feature flag",
                         "reasoning": "roll back without a deploy",
                         "links": [{"to": ids["g_queue"], "type": "changes_scope_of"}]})[0]
    ids["n_bench"] = rec({"kind": "note", "title": "Why Redis: the first benchmark", "summary": "Hit rate 64% at 1k rps.",
                          "type": "research", "origin": "user",
                          "links": [{"to": ids["d_cache"], "type": "about"}, {"to": ids["g_p99"], "type": "supports"}]})[0]
    ids["k2"] = rec({"kind": "checkin", "summary": "Week two", "wins": ["consumer merged"], "blockers": ["no budget"]})[0]
    ids["d_retry"] = rec({"kind": "decision", "text": "Retry failed webhooks 3 times",
                          "reasoning": "most failures are transient"})[0]
    clock.advance(days=7)                                               # 2026-W41
    s.update(ids["d_cache"], changes={"text": "Cache product reads in Redis with a 60 s expiry"},
             reason="stale prices showed for minutes after an update")
    ids["c_trace3"] = s.update(ids["c_trace2"], status="carried", note="could not test: staging went down")["new_id"]
    ids["c_ravi3"] = s.update(ids["c_ravi2"], status="carried")["new_id"]
    ids["n_bench2"] = rec({"kind": "note", "title": "Redis benchmark rerun", "summary": "Hit rate 82% with warm keys.",
                           "type": "research", "origin": "user", "supersedes": ids["n_bench"],
                           "links": [{"to": ids["d_cache"], "type": "about"}]})[0]
    ids["p_mei"] = rec({"kind": "person", "name": "Mei", "role": "our tech lead"})[0]
    ids["p_ravi"] = rec({"kind": "person", "name": "Ravi", "role": "runs SRE"})[0]
    s.update(ids["d_pg"], links=[{"to": ids["p_mei"], "type": "decided_by"}], reason="Mei made this call in week one")
    s.update(ids["c_trace3"], links=[{"to": ids["p_mei"], "type": "owned_by"}])
    ids["i_staging"] = rec({"kind": "issue", "text": "The staging cluster is down until 14 October",
                            "links": [{"to": ids["c_trace3"], "type": "blocks"}]})[0]
    s.update(ids["d_retry"], changes={"text": "Retry failed webhooks 5 times with backoff"},
             reason="a partner's API flapped for minutes at a time")
    clock.advance(days=1)                                               # Tuesday of 2026-W41
    s.update(ids["d_retry"], changes={"text": "Retry failed webhooks 5 times with backoff, then park them in a "
                                              "dead-letter table"}, reason="we lost two events after the fifth retry")
    return s, ids


def retirement(home: Path):
    """The investor coach's made-up goal (no Goals module): rules decided and one edited, carried tasks, a superseded
    Note, who decided and a blocker."""
    from founder_coach.store import FounderStore
    clock = Clock()
    s = FounderStore(home, clock=clock, coach="investor")
    s.peers = {}
    _profile(s, {"timezone": "UTC", "goal": "Retirement in 2055", "horizon": 2055, "rebalance_band": 5.0,
                 "targets": {"us_equity": 60.0, "intl_equity": 20.0, "bonds": 15.0, "cash": 5.0}})
    ids: dict[str, str] = {}
    rec = lambda e: s.record(e)["ids"]                                  # noqa: E731
    ids["d_bonds"] = rec({"kind": "decision", "text": "Hold bonds through a total bond index fund",
                          "reasoning": "the lowest cost way to own them"})[0]
    ids["d_band"] = rec({"kind": "decision", "text": "Rebalance when an asset class drifts 5 points",
                         "reasoning": "bands trade less than a calendar"})[0]
    c = rec({"kind": "commitments", "items": [
        {"action": "Roll the old 401(k) into the IRA", "outcome": "rollover requested"},
        {"action": "Set up automatic monthly contributions", "outcome": "first transfer scheduled"},
        {"action": "Ask Dana about the employer match", "outcome": "the match rate"}]})
    ids["c_401k"], ids["c_auto"], ids["c_dana"] = c
    ids["k1"] = rec({"kind": "checkin", "summary": "Week one", "wins": ["policy written"], "blockers": []})[0]
    clock.advance(days=7)                                               # 2026-W40
    ids["c_401k2"] = s.update(ids["c_401k"], status="carried", note="the old plan wants a paper form")["new_id"]
    ids["c_dana2"] = s.update(ids["c_dana"], status="carried")["new_id"]
    s.update(ids["c_auto"], status="done", reason="first transfer on the 1st")
    ids["d_intl"] = rec({"kind": "decision", "text": "Keep 20% in international stocks",
                         "reasoning": "less home bias"})[0]
    ids["n_fees"] = rec({"kind": "note", "title": "Why fees matter", "summary": "1% a year costs a third by 2055.",
                         "type": "research", "origin": "user", "links": [{"to": ids["d_bonds"], "type": "about"}]})[0]
    ids["k2"] = rec({"kind": "checkin", "summary": "Week two", "wins": ["contributions on"], "blockers": []})[0]
    ids["d_cash"] = rec({"kind": "decision", "text": "Keep 5% in cash", "reasoning": "a cushion for rebalancing"})[0]
    clock.advance(days=7)                                               # 2026-W41
    s.update(ids["d_band"], changes={"text": "Rebalance when an asset class drifts 5 points, checked every quarter"},
             reason="checking every month caused needless trades")
    ids["c_401k3"] = s.update(ids["c_401k2"], status="carried", note="form mailed, waiting on a signature")["new_id"]
    ids["c_dana3"] = s.update(ids["c_dana2"], status="carried")["new_id"]
    ids["n_fees2"] = rec({"kind": "note", "title": "Fee check of our funds", "summary": "They average 0.05% a year.",
                          "type": "research", "origin": "user", "supersedes": ids["n_fees"],
                          "links": [{"to": ids["d_bonds"], "type": "about"}]})[0]
    ids["p_sam"] = rec({"kind": "person", "name": "Sam", "role": "my spouse"})[0]
    ids["p_dana"] = rec({"kind": "person", "name": "Dana", "role": "HR benefits contact"})[0]
    s.update(ids["d_intl"], links=[{"to": ids["p_sam"], "type": "decided_by"}], reason="Sam chose the split")
    ids["i_form"] = rec({"kind": "issue", "text": "The old plan's rollover form needs a signed paper copy",
                         "links": [{"to": ids["c_401k3"], "type": "blocks"}]})[0]
    s.update(ids["c_401k3"], links=[{"to": ids["p_dana"], "type": "owned_by"}])
    s.update(ids["d_cash"], changes={"text": "Keep 3% in cash"}, reason="the emergency fund now sits outside this goal")
    clock.advance(days=1)                                               # Tuesday of 2026-W41
    s.update(ids["d_cash"], changes={"text": "Keep 3% in cash, in a Treasury money market fund"},
             reason="it pays more than the bank sweep")
    return s, ids


def seed(pack: str, home: Path):
    """The made-up Project of a Pack's G9 cases: (store, ids by name)."""
    if pack == "coding":
        return ledger(home)
    if pack == "investor":
        return retirement(home)
    return acme(home, people=True, coach=pack, extra=True)
