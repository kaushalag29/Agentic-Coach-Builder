"""The Project graph (ADR-0024): a typed graph computed from the store, and the graph benchmark.

A made-up Project ("Acme Dental") is written through the store over three weeks with a fake clock: Goals, carried
Commitments, Decisions (one edited later), Check-ins and Notes (one superseded). The benchmark questions below are
the kinds a person asks the coach: multi-hop, carried work, what we believed on a date, what changed, a path between
two records, and questions whose honest answer is "nothing recorded". Each is answered through graph.py only and
scored against the ids we know are right. Offline and hermetic."""
import contextlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_coach import Clock  # noqa: E402  (sets the hermetic environment first)

from founder_coach import graph as G                     # noqa: E402
from founder_coach import product                        # noqa: E402
from founder_coach.store import FounderStore             # noqa: E402
from ytbrain.eval.graph_seed import acme                 # noqa: E402,F401  (the made-up Project, shared with G9)

PINNED = (product.env_name("HOME"), product.env_name("PROJECT"), product.env_name("MODELS"))


@contextlib.contextmanager
def _machine():
    keys = ("HOME", "YTBRAIN_HOME", *PINNED)
    saved = {k: os.environ.get(k) for k in keys}
    user = Path(tempfile.mkdtemp(prefix="graph-machine-")) / "user"
    user.mkdir()
    os.environ["HOME"] = str(user)
    os.environ["YTBRAIN_HOME"] = str(user / ".ytbrain")
    for k in PINNED:
        os.environ.pop(k, None)
    try:
        yield user
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _ids(items: list[dict]) -> set[str]:
    return {i["id"] for i in items}


def benchmark(s: FounderStore, ids: dict) -> list[tuple[str, bool]]:
    """(question, answered right) for the graph benchmark. Every answer comes from graph.py alone."""
    g = G.for_store(s)
    t_email, t_call, t_check = (g.resolve(ids[k]) for k in ("c_email", "c_call", "c_check"))
    res: list[tuple[str, bool]] = []

    def q(text: str, ok: bool) -> None:
        res.append((text, bool(ok)))

    # carried work
    q("a task carried three weeks is one thread", t_email == ids["c_email"] and g.resolve(ids["c_email3"]) == t_email
      and len(g.nodes[t_email].data["rows"]) == 3)
    q("what has been planned 3+ periods and is still open", {t.id for t in g.open_loops(3)} == {t_email, t_call})
    q("what has been planned 2+ periods (the done task is not open)", t_check not in {t.id for t in g.open_loops(1)})
    q("which goal does the email task serve", [e.dst for e in g.out[t_email] if e.type == "serves"] == [ids["g_partners"]])
    q("how many tasks are open", sorted(t.id for t in g.threads() if t.status == "open") == sorted([t_email, t_call]))
    q("which open work has no goal", [t.id for t in g.threads() if t.status == "open" and not t.data["goal_id"]]
      == [t_call])
    # multi-hop
    near = g.around(ids["g_partners"], hops=1)
    q("what serves the design-partner goal", _ids(near) == {t_email})
    two = g.around(ids["g_onboard"], hops=2)
    q("what is two steps from the onboarding goal (note, its decision, the checklist and its week)",
      {ids["n_scope"], ids["d_dash"], t_check} <= _ids(two))
    q("which decision was made in week 40", [e.src for e in g.into.get("2026-W40", []) if e.type == "decided_in"]
      == [ids["d_dash"]])
    q("which check-ins were in week 39", [e.src for e in g.into.get("2026-W39", [])
                                          if g.nodes[e.src].kind == "checkin"] == [ids["k1"]])
    p = g.path(ids["n_scope"], ids["g_partners"], max_depth=6)
    q("why is the dashboard note connected to the design-partner goal",
      p is not None and p[0]["from"] == ids["n_scope"] and p[-1]["to"] == ids["g_partners"])
    q("a path only uses the edge types asked for", g.path(ids["n_scope"], ids["g_partners"], 6, ("about",)) is None)
    q("notes about the dashboard decision (both, old and new)",
      {e.src for e in g.into[ids["d_dash"]] if e.type == "about"} == {ids["n_scope"], ids["n_scope2"]})
    q("the newer note supersedes the older", any(e.type == "supersedes" and e.dst == ids["n_scope"]
                                                for e in g.out[ids["n_scope2"]]))
    q("nothing is isolated except what truly has no tie", g.isolated() == [])
    # time: the change log
    log = G.changes(s, g.record_ids())
    tz = s.tz()
    import datetime as dt
    seq39 = G.last_seq_at(s, G.end_of_day_utc(dt.date(2026, 9, 21), tz))
    rows = {ids["d_dental"]: g.nodes[ids["d_dental"]].data["row"]}
    then = G.state_at(rows, log, seq39)
    q("what did we believe in week 39 about who we sell to",
      then[ids["d_dental"]]["text"] == "Sell to dental clinics first")
    now = G.state_at(rows, log, 10 ** 9)
    q("what do we believe now", now[ids["d_dental"]]["text"] == "Sell to independent dental clinics first")
    drows = {n.id: n.data["row"] for n in g.nodes.values() if n.kind == "decision"}
    q("which decisions existed at the end of week 39", set(G.state_at(drows, log, seq39)) == {ids["d_dental"],
                                                                                                ids["d_charge"]})
    nrows = {n.id: n.data["row"] for n in g.nodes.values() if n.kind == "note"}
    seq40 = G.last_seq_at(s, G.end_of_day_utc(dt.date(2026, 9, 28), tz))
    q("in week 40 the first note was not yet superseded", G.state_at(nrows, log, seq40)[ids["n_scope"]]
      .get("superseded_by") is None)
    hist = [c for c in log if c["entity_id"] == ids["d_dental"] and c["op"] == "update"]
    q("what changed in the dental decision", len(hist) == 1 and G.diff(hist[0]["before"], hist[0]["after"])
      .get("text") == ["Sell to dental clinics first", "Sell to independent dental clinics first"])
    q("the email thread's history is its three rows", [c["entity_id"] for c in log if c["op"] == "create"
                                                      and g.alias.get(c["entity_id"]) == t_email]
      == [ids["c_email"], ids["c_email2"], ids["c_email3"]])
    # abstention: the honest answer is "nothing recorded"
    q("an id that doesn't exist resolves to nothing", g.resolve("d-0000") is None)
    q("no decision was recorded in week 42", not [e for e in g.into.get("2026-W42", []) if e.type == "decided_in"])
    q("no path between two unrelated records within one hop", g.path(ids["d_charge"], ids["g_partners"], 1) is None)
    q("sources are not walked unless asked", all(n["edge"] != "cites" for n in g.around(ids["d_dash"], 3)))
    return res


def test_the_graph_benchmark_answers_every_question():
    with _machine():
        s, ids = acme(Path(tempfile.mkdtemp(prefix="graph-")))
        try:
            res = benchmark(s, ids)
        finally:
            s.close()
    wrong = [qn for qn, ok in res if not ok]
    assert len(res) >= 25 and not wrong, f"{len(res) - len(wrong)}/{len(res)} right; wrong: {wrong}"


def test_another_coachs_private_records_are_never_nodes_and_no_path_crosses_them():
    with _machine():
        home = Path(tempfile.mkdtemp(prefix="graph-priv-"))
        inv = FounderStore(home, coach="investor")
        inv.owned = ("*",)
        ig = inv.record({"kind": "goal", "text": "Private money goal", "measure": "x"})["ids"][0]
        inv.close()
        coding = FounderStore(home, coach="coding")
        cn_goal = coding.record({"kind": "goal", "text": "Ship the importer", "measure": "merged"})["ids"][0]
        coding.close()
        s = FounderStore(home)
        s.peers = {"coding": [], "investor": ["*"]}
        try:
            d = s.record({"kind": "decision", "text": "Use the importer", "reasoning": "r"})["ids"][0]
            n = s.record({"kind": "note", "title": "Importer", "summary": "s", "type": "discussion", "origin": "user",
                          "links": [{"to": cn_goal, "type": "about"}, {"to": d, "type": "related"}]})["ids"][0]
            g = G.for_store(s)
            assert cn_goal in g.nodes, "a peer's shared Goal is part of the graph"
            assert ig not in g.nodes and not any(e.src == ig or e.dst == ig for e in g.edges), \
                "a private coach's records are never nodes or edge ends"
            assert g.path(n, cn_goal) == [{"from": n, "to": cn_goal, "edge": "about", "direction": "out"}]
        finally:
            s.close()
        peer = FounderStore(home, coach="coding")
        peer.peers = {"founder": [], "investor": ["*"]}
        try:
            g2 = G.for_store(peer)
            assert n not in g2.nodes, "a Note is read only by the coach that wrote it"
            assert d in g2.nodes and not g2.into.get(d), "a link another coach made from its private Note is not seen"
        finally:
            peer.close()


def test_recall_finds_a_peer_coachs_shared_decision():
    with _machine():
        home = Path(tempfile.mkdtemp(prefix="graph-recall-"))
        c = FounderStore(home, coach="coding")
        cd = c.record({"kind": "decision", "text": "Adopt Postgres for the importer", "reasoning": "r"})["ids"][0]
        c.close()
        s = FounderStore(home)
        s.peers = {"coding": []}
        try:
            assert cd in {h["id"] for h in s.recall("postgres importer", kinds=["decision"])}, \
                "recall reads the shared Decisions of the Project's other coaches (ADR-0019)"
        finally:
            s.close()


def _raises(fn, words: str) -> None:
    from founder_coach.store import StoreError
    try:
        fn()
    except StoreError as e:
        assert words in str(e), (words, str(e))
    else:
        raise AssertionError(f"expected an error containing {words!r}")


def test_nothing_about_a_change_is_lost_why_by_whom_and_every_version():
    """ADR-0025: a change of mind is a new Decision that supersedes the old one (kept, marked superseded); a correction
    is logged with its reason; final statuses need a reason; every change-log row says why and by whom."""
    with _machine():
        s, ids = acme(Path(tempfile.mkdtemp(prefix="graph-why-")))
        try:
            marco = s.record({"kind": "person", "name": "Marco", "role": "advisor"})["ids"][0]
            _raises(lambda: s.record({"kind": "person", "name": "marco"}), "already")
            _raises(lambda: s.record({"kind": "decision", "text": "Sell to hospitals", "reasoning": "bigger deals",
                                      "supersedes": ids["d_dental"]}), "needs `reason`")
            new = s.record({"kind": "decision", "text": "Sell to hospitals first", "reasoning": "bigger deals",
                            "supersedes": ids["d_dental"], "reason": "two hospital pilots asked", "by": marco,
                            "links": [{"to": marco, "type": "decided_by"}]})["ids"][0]
            old = s.get(ids["d_dental"])
            assert old["status"] == "superseded" and old["superseded_by"] == new, "the old Decision is kept, marked"
            _raises(lambda: s.record({"kind": "decision", "text": "x", "reasoning": "y", "supersedes": ids["d_dental"],
                                      "reason": "z"}), "already superseded")
            _raises(lambda: s.update(ids["d_charge"], changes={"text": "Charge from week two"}), "needs `reason`")
            _raises(lambda: s.update(ids["d_charge"], status="superseded", reason="r"), "newer one")
            _raises(lambda: s.update(ids["g_partners"], status="dropped"), "needs `reason`")
            s.update(ids["d_charge"], status="reversed", reason="free pilots convert better", by=marco)
            _raises(lambda: s.update(ids["d_charge"], status="reversed", by="pe-0000", reason="r"), "`by`")
            g = G.for_store(s)
            assert any(e.type == "supersedes" and e.dst == ids["d_dental"] for e in g.out[new])
            assert any(e.type == "decided_by" and e.dst == marco for e in g.out[new])
            h = G.history(s, g, ids["d_dental"])
            sup = next(x for x in h if x["op"] == "supersede")
            assert sup["why"] == "two hospital pilots asked" and sup["by"] == "Marco" and sup["changed"]["status"] == \
                ["accepted", "superseded"]
            rev = next(x for x in G.history(s, g, ids["d_charge"]) if x["op"] == "status")
            assert rev["why"] == "free pilots convert better" and rev["by"] == "Marco"
            first = next(x for x in G.history(s, g, ids["d_dental"]) if x["op"] == "update")
            assert first["why"] == "chains buy centrally; independents decide in a week" and "by" not in first, \
                "nobody said who: the person recorded it, which doesn't make them its decider"
            assert first["recorded_by"].startswith("the person")
            assert s.get(ids["d_dental"])["decided_by"].startswith("not recorded")
            assert "not recorded" in G.decided_by_note(g, ids["d_dental"])
            page = next(p for p in (s.home / "vault" / "shared" / "decisions").glob("*.md")
                        if f'id: "{ids["d_dental"]}"' in p.read_text())
            text = page.read_text()
            assert "## History" in text and "two hospital pilots asked" in text and "Marco" in text \
                and "status: \"superseded\"" in text, "the vault page carries every change with why and by whom"
        finally:
            s.close()


def test_links_people_and_issues_follow_the_closed_vocabulary_and_are_ended_not_deleted():
    with _machine():
        s, ids = acme(Path(tempfile.mkdtemp(prefix="graph-links-")))
        try:
            lena = s.record({"kind": "person", "name": "Lena", "aliases": ["Len"]})["ids"][0]
            issue = s.record({"kind": "issue", "text": "Bakeries want a price before a trial",
                              "links": [{"to": ids["g_partners"], "type": "blocks"},
                                        {"to": lena, "type": "owned_by"}]})["ids"][0]
            _raises(lambda: s.update(ids["g_partners"], links=[{"to": lena, "type": "blocks"}]), "can't go from")
            _raises(lambda: s.update(issue, links=[{"to": "g-0000", "type": "blocks"}]), "no record")
            s.update(ids["c_email3"], links=[{"to": lena, "type": "owned_by"}])
            g = G.for_store(s)
            t = g.resolve(ids["c_email"])
            assert any(e.type == "owned_by" and e.dst == lena for e in g.out[t]), "a row's link reaches its thread"
            assert {e.src for e in g.into[lena] if e.type == "owned_by"} == {t, issue}
            p = g.path(issue, t)
            assert p is not None and len(p) == 2, "who owns the work a blocker stands in front of"
            s.update(issue, links=[{"to": lena, "type": "owned_by", "action": "end"}], reason="Tomas took it")
            assert not any(e.type == "owned_by" for e in G.for_store(s).out.get(issue, []))
            ended = [r for r in s.db.execute("SELECT * FROM links WHERE src=? AND type='owned_by'", (issue,))]
            assert ended and ended[0]["ended_at"], "an ended link is kept, with when it ended"
            log = [dict(r) for r in s.db.execute("SELECT op, reason FROM changes WHERE entity='link' AND entity_id=?",
                                                 (f"{issue}|owned_by|{lena}",))]
            assert [x["op"] for x in log] == ["create", "end"] and log[1]["reason"] == "Tomas took it"
            s.update(issue, status="resolved", reason="published a price list")
            assert s.get(issue)["status"] == "resolved"
            # a mention: the person's name (or alias) in a record's words
            s.record({"kind": "commitments", "items": [{"action": "Len drafts the pricing page", "outcome": "a draft"}]})
            g = G.for_store(s)
            assert any(g.nodes[e.src].title.startswith("Len drafts") for e in g.into[lena] if e.type == "mentions")
        finally:
            s.close()


def test_a_link_between_shared_records_is_shared_and_a_notes_link_stays_private():
    with _machine():
        home = Path(tempfile.mkdtemp(prefix="graph-share-"))
        s = FounderStore(home)
        s.peers = {"coding": []}
        try:
            d = s.record({"kind": "decision", "text": "Use Postgres", "reasoning": "r"})["ids"][0]
            pe = s.record({"kind": "person", "name": "Tomas"})["ids"][0]
            s.update(d, links=[{"to": pe, "type": "decided_by"}])
            n = s.record({"kind": "note", "title": "Why Postgres", "summary": "s", "type": "discussion",
                          "origin": "user", "links": [{"to": d, "type": "about"}]})["ids"][0]
        finally:
            s.close()
        c = FounderStore(home, coach="coding")
        c.peers = {"founder": []}
        try:
            g = G.for_store(c)
            assert pe in g.nodes and any(e.type == "decided_by" for e in g.out[d]), "shared core, shared ties"
            assert n not in g.nodes and not any(e.type == "about" for e in g.into.get(d, []))
        finally:
            c.close()


def test_the_link_rules_propose_and_only_a_yes_saves_and_a_no_is_remembered():
    from founder_coach import proposals as P
    with _machine():
        s, ids = acme(Path(tempfile.mkdtemp(prefix="graph-prop-")))
        try:
            g2 = s.record({"kind": "decision", "text": f"Price at 99 a month instead of free pilots, replaces "
                                                      f"{ids['d_charge']}", "reasoning": "pilots stalled"})["ids"][0]
            for i in range(3):
                s.record({"kind": "checkin", "summary": f"Week {i}: Marco was busy again",
                          "wins": [f"Marco replied {i}"], "blockers": ["clinics want a price before a trial"]})
            s.record({"kind": "note", "title": "Onboarding checklist feedback", "summary": "the checklist was too "
                      "long for onboarding", "type": "research", "origin": "user"})
            assert P.refresh(s) > 0 and P.refresh(s) == 0, "the same finding is queued once"
            items, total = P.pending(s, limit=20)
            rules = {i["rule"] for i in items}
            assert {"R1", "R4", "R6", "R7"} <= rules, rules
            assert any("Marco" in i["what"] for i in items if i["rule"] == "R4")
            assert not any(i["what"].startswith("add Week") for i in items), "a sentence's first word is no name"
            sup = next(i for i in items if i["rule"] == "R1")
            assert sup["tier"] == "high" and ids["d_charge"] in sup["why"]
            assert s.get(ids["d_charge"])["status"] == "accepted", "nothing is saved before the yes"
            s.update(sup["id"], status="accepted")
            old = s.get(ids["d_charge"])
            assert old["status"] == "superseded" and old["superseded_by"] == g2
            reason = s.db.execute("SELECT reason FROM changes WHERE entity='decision' AND entity_id=? AND op='supersede'",
                                  (ids["d_charge"],)).fetchone()[0]
            assert reason and sup["id"] in reason, "the change log says the change came from an accepted proposal"
            person = next(i for i in P.pending(s, limit=20)[0] if i["rule"] == "R4" and "Marco" in i["what"])
            s.update(person["id"], status="rejected")
            P.refresh(s)
            assert not any("Marco" in i["what"] for i in P.pending(s, limit=20)[0] if i["rule"] == "R4"), \
                "a rejected proposal is never asked again"
            issue = next(i for i in P.pending(s, limit=20)[0] if i["rule"] == "R6")
            s.update(issue["id"], status="snoozed")
            assert issue["id"] not in {i["id"] for i in P.pending(s, limit=20)[0]}
            _raises(lambda: s.update(issue["id"], status="done"), "accepted, rejected or snoozed")
        finally:
            s.close()


def test_a_v7_store_migrates_to_v8_with_a_backup_and_keeps_everything():
    from test_coach import _downgrade
    with _machine():
        home = Path(tempfile.mkdtemp(prefix="graph-mig-"))
        s, ids = acme(home)
        s.db.execute("DROP TABLE IF EXISTS proposals")
        _downgrade(s, 7)
        s.close()
        s = FounderStore(home)
        try:
            assert s._version() == 8 and list((home / "backups").glob("*pre-migration-v7*"))
            assert s.get(ids["d_dental"])["status"] == "accepted", "old Decisions read as accepted"
            assert G.for_store(s).resolve(ids["c_email3"]) == ids["c_email"]
        finally:
            s.close()


def test_expand_ranks_what_is_tied_to_the_hits_and_beats_words_alone_on_multi_hop():
    """S7: the graph benchmark's multi-hop questions, answered from a keyword search alone and then with the records
    tied to its hits (personalized PageRank). Expansion must find the tied record the words miss, and is measured
    here before it ever becomes a default."""
    with _machine():
        s, ids = acme(Path(tempfile.mkdtemp(prefix="graph-rank-")))
        try:
            g = G.for_store(s)
            cases = [("dashboard", ids["g_onboard"]),          # the Note about it supports the onboarding Goal
                     ("dentists", ids["g_partners"]),          # the task serves the design-partner Goal
                     ("pilots exports", ids["d_dash"])]        # the newer Note is about the dashboard Decision
            words = hits_ranked = 0
            for q, want in cases:
                hits = s.recall(q, limit=5)
                words += want in {h["id"] for h in hits}
                rel = G.rank(g, {h["id"]: float(h.get("score") or 1) for h in hits}, s.today())
                hits_ranked += want in {h["id"] for h in hits} | {r["id"] for r in rel[:5]}
                assert all("how" in r and r["id"] not in {h["id"] for h in hits} for r in rel)
            assert hits_ranked == len(cases) and hits_ranked > words, (words, hits_ranked)
        finally:
            s.close()


def test_the_vault_draws_a_canvas_per_goal_and_one_offline_html_page_that_text_cannot_break():
    """S8/S9: a JSON Canvas per Goal (week columns, typed edges) and `vault build --html`: everything inline, a policy
    that blocks the network, and record text that tries to close the script or inject markup stays data."""
    import json
    import re
    from founder_coach import vault as V
    with _machine():
        home = Path(tempfile.mkdtemp(prefix="graph-views-"))
        s, ids = acme(home)
        evil = '</script><img src=x onerror=alert(1)> __DATA__'
        s.record({"kind": "decision", "text": evil, "reasoning": "x", "links": [{"to": ids["g_partners"],
                                                                             "type": "serves"}]})
        s.close()
        out = home / "vault"
        V.build(home, out, None, with_html=True)
        canvases = sorted(out.glob("_meta/*/canvas/*.canvas"))
        assert len(canvases) == 2, canvases
        board = json.loads(next(c for c in canvases if "paying" in c.name.lower()).read_text())
        files = {n["file"] for n in board["nodes"] if n["type"] == "file"}
        assert all((out / f).is_file() for f in files), files            # every card opens a real page
        assert any(n["type"] == "group" and n["label"] == "2026-W39" for n in board["nodes"])
        assert any(e["label"] == "serves" and e["toNode"] == ids["g_partners"] for e in board["edges"])
        page = (out / "_meta" / "graph.html").read_text()
        assert "default-src 'none'" in page and "http://" not in page.split("<script>", 1)[0]
        assert not re.search(r"<script[^>]+src=|<link[^>]+href=", page)    # nothing fetched
        data = page.split('id="data">', 1)[1].split("</script>", 1)[0]  # the data block ends where it should
        assert "<img" not in page.replace(data, "") or "onerror" not in page.replace(data, "")
        assert json.loads(data)["nodes"] and any(n["title"] == evil for n in json.loads(data)["nodes"])
        assert page.count("</script>") == 3                                # data, library, viewer: none injected
        V.build(home, out, None)                                           # without --html the page goes
        assert not (out / "_meta" / "graph.html").exists()


def test_an_undone_carry_never_closes_its_task_and_page_names_read_cleanly():
    """A carry made twice and dropped again (the earlier row still open) stays in the history but never decides the
    task's status, periods or weeks; page names drop a leading [note], dangling words and an unclosed bracket."""
    from founder_coach import vault as V
    rows = [{"id": "c-1", "week": "2026-W45", "status": "carried"},
            {"id": "c-2", "week": "2026-W46", "status": "open", "carried_from": "c-1"},
            {"id": "c-3", "week": "2026-W47", "status": "dropped", "carried_from": "c-2"}]
    assert [r["id"] for r in G.live_rows(rows)] == ["c-1", "c-2"]
    rows[1]["status"] = "carried"                                  # a real carry, then dropped: the task is dropped
    assert [r["id"] for r in G.live_rows(rows)] == ["c-1", "c-2", "c-3"]
    assert V.short_name("Review the Marco draft as a team (30 min), make the fixes") == \
        "Review the Marco draft as a team"
    assert V.short_name("[Superseded 5 Oct by d-1: X] Launch scope = signup, billing, onboarding emails") == \
        "Launch scope = signup, billing"
    assert not V.short_name("Build the Google Doc for the plant in the shared Drive").endswith((" in", " the"))
    with _machine():
        home = Path(tempfile.mkdtemp(prefix="graph-undo-"))
        s, ids = acme(home)
        try:
            k = s.record({"kind": "checkin", "summary": "Second one this week", "wins": [], "blockers": []})["ids"][0]
            g = G.for_store(s)
            assert {g.nodes[ids["k1"]].title, g.nodes[k].title} == {"Check-in 2026-W39 (21 Sep)",
                                                                     "Check-in 2026-W41 (5 Oct)"}
        finally:
            s.close()


def test_a_read_says_when_a_record_changed_and_how_long_work_was_carried():
    """The first G9 run answered from coach_get_context and coach_recall, which show records as they read now: a
    changed record now says so (and points at coach_graph history), and carried work says since when."""
    with _machine():
        s, ids = acme(Path(tempfile.mkdtemp(prefix="graph-edited-")))
        try:
            hit = next(h for h in s.recall("dental clinics")[:5] if h["id"] == ids["d_dental"])
            assert "coach_graph history" in hit["edited"] and "2026-10-05" in hit["edited"]
            assert "edited" not in next(d for d in s.decisions(10) if d["id"] == ids["d_charge"])
            assert "edited" in s.get(ids["d_dental"]) and "edited" not in s.get(ids["d_dental"], links=False)
            assert next(h for h in s.recall("onboarding checklist") if h["id"] == ids["c_check"])["status"] == "done"
            assert ids["d_charge"] in {h["id"] for h in s.recall("charging")}, "a word finds its other forms"
            then = next(h for h in s.recall("dental clinics", until="2026-09-28") if h["id"] == ids["d_dental"])
            assert then["title"] == "Sell to dental clinics first" and then["now"].startswith("Sell to independent"), \
                "a search about a period shows each record as it read then"
            from founder_coach import nudges as N
            idx = N.memory_index(s)
            assert "Email 20 dentists" in idx and "memory first" in idx
            assert ids["c_email"] in {h["id"] for h in s.recall("emailing", kinds=["commitment"])} or \
                ids["c_email3"] in {h["id"] for h in s.recall("emailing", kinds=["commitment"])}
            from founder_coach import server as SV
            hits = s.recall("dashboard")
            SV._mark_ties(s, hits)
            assert "coach_graph around" in next(h for h in hits if h["id"] == ids["d_dash"])["ties"]
            row = next(c for c in s.commitments("2026-W41") if c["id"] == ids["c_email3"])
            assert row["planned_since"].startswith("2026-W39, planned in 3 periods")
        finally:
            s.close()


if __name__ == "__main__":
    import inspect
    import logging
    import traceback
    logging.disable(logging.WARNING)
    fns = [f for n, f in globals().items() if n.startswith("test_") and inspect.isfunction(f)]
    failed = 0
    for f in fns:
        try:
            f()
            print(f"  PASS  {f.__name__}")
        except Exception as e:                   # noqa: BLE001 -- report every test, not just the first
            failed += 1
            print(f"  FAIL  {f.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
