"""Projects and the Common profile (ADR-0016, M6e; acceptance C1-C5 and the G7 isolation cases): memory kept
per Project, a session that asks which one, sharing only on a yes, the one-time move of the old store, and the
command line. Each test gets a fresh machine (its own OS home and engine home): nothing touches ~/."""
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_coach import Clock, _Models, _pack, _skipped   # noqa: E402  (sets the hermetic environment first)
import test_pack  # noqa: E402,F401  (imported now: its import-time settings must not land inside a test machine)

from founder_coach import product                        # noqa: E402
from founder_coach.projects import ProjectError, Projects, Workspace, slug   # noqa: E402
from founder_coach.store import FounderStore             # noqa: E402

PINNED = (product.env_name("HOME"), product.env_name("PROJECT"), product.env_name("MODELS"))


@contextlib.contextmanager
def _machine():
    """A fresh machine: its own OS home (so ~/.founder-coach is a temp folder) and engine home, and no data
    folder pinned (Projects are in use)."""
    keys = ("HOME", "YTBRAIN_HOME", *PINNED)
    saved = {k: os.environ.get(k) for k in keys}
    user = Path(tempfile.mkdtemp(prefix="coach-machine-")) / "user"
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


def _serve(user: Path, fn, clock=None, home=None):
    """Run `fn(call)` against one server session; call(tool, args) -> (structured or None, text, is_error)."""
    try:
        import anyio
        from mcp import Client
    except ImportError:
        _skipped("optional dependency not installed")
        return False
    from founder_coach.server import create_server
    tmp = Path(tempfile.mkdtemp())
    srv = create_server(pack=_pack(tmp), home=home, clock=clock or Clock(), models=_Models(), start_models=False,
                        engine_home=user / ".ytbrain")

    async def main():
        async with Client(srv) as c:
            async def call(tool, args=None):
                r = await c.call_tool(tool, args or {})
                text = " ".join(getattr(x, "text", "") for x in r.content)
                return (None if r.is_error else r.structured_content), text, r.is_error
            await fn(call)
    anyio.run(main)
    return True


def _rid(n=[0]):                                         # noqa: B006 -- a counter on purpose
    n[0] += 1
    return f"req-{n[0]}"


# --- names --------------------------------------------------------------------------------------------------
def test_project_names_are_unique_ignoring_case_and_a_rename_keeps_the_folder():
    root = Path(tempfile.mkdtemp())
    ps = Projects(root)
    a = ps.create("Acme Inc.")
    assert a["id"] == "acme-inc" and (root / "projects" / "acme-inc" / "project.json").exists()
    for dup in ("acme inc.", "  ACME   Inc. "):
        try:
            ps.create(dup)
            raise AssertionError("a second Project with the same name")
        except ProjectError as e:
            assert "already a Project" in str(e)
    b = ps.create("Acme-Inc")                           # a different name with the same slug: a new folder
    assert b["id"] == "acme-inc-2"
    assert ps.get("ACME INC.")["id"] == "acme-inc" and ps.get("acme-inc-2")["name"] == "Acme-Inc"
    r = ps.rename("acme-inc", "Acme Robotics")
    assert r["id"] == "acme-inc" and ps.get("acme robotics")["id"] == "acme-inc"
    assert slug("Startup's Café!") == "startups-cafe" and slug("!!!") == "project"
    for bad in ("", " ", "x" * 81):
        try:
            ps.create(bad)
            raise AssertionError(f"accepted {bad!r}")
        except ProjectError:
            pass
    (root / "projects" / "acme-inc-2" / "project.json").write_text("{broken")
    assert [p["id"] for p in ps.list()] == ["acme-inc"], "a folder without a store or a label isn't a Project"
    FounderStore(root / "projects" / "acme-inc-2").close()
    assert {p["id"] for p in ps.list()} == {"acme-inc", "acme-inc-2"}, "a damaged label never hides a Project"


# --- C1 / G7: isolation --------------------------------------------------------------------------------------
def test_each_project_keeps_its_own_memory_and_a_session_asks_which_one():
    with _machine() as user:
        async def first(call):
            ctx, _, _ = await call("coach_get_context")
            assert ctx["project"] is None and [n["kind"] for n in ctx["nudges"]] == ["setup"]
            out, _, err = await call("coach_project", {"action": "create", "name": "Acme"})
            assert not err and out["active"] == {"id": "acme", "name": "Acme"}
            res, _, err = await call("coach_update_profile", {"changes": {"company": "Acme", "stage": "mvp"},
                                                              "request_id": _rid()})
            assert not err and res["saved_to"] == "Project Acme (acme)"
            await call("coach_record", {"entry": {"kind": "goal", "text": "10 design partners"}, "request_id": _rid()})
            await call("coach_record", {"entry": {"kind": "decision", "text": "Charge from day one",
                                                  "reasoning": "signal"}, "request_id": _rid()})
            out, _, _ = await call("coach_project", {"action": "create", "name": "Beta Labs"})
            assert out["active"]["id"] == "beta-labs" and len(out["projects"]) == 2
            ctx, text, _ = await call("coach_get_context")
            assert ctx["project"]["id"] == "beta-labs" and ctx["goals"] == [] and ctx["recent_decisions"] == []
            assert "company" not in ctx["profile"] and "design partners" not in text
            await call("coach_record", {"entry": {"kind": "goal", "text": "Ship v1"}, "request_id": _rid()})
            out, _, _ = await call("coach_project", {"action": "summary", "project": "acme"})
            assert out["summary"]["profile"]["company"] == "Acme"
            assert [g["text"] for g in out["summary"]["goals"]] == ["10 design partners"]
            ctx, _, _ = await call("coach_get_context")
            assert [g["text"] for g in ctx["goals"]] == ["Ship v1"], "a summary reads; it never copies"
            out, _, _ = await call("coach_project", {"action": "switch", "project": "acme"})
            ctx, _, _ = await call("coach_get_context")
            assert [g["text"] for g in ctx["goals"]] == ["10 design partners"] and ctx["profile"]["stage"] == "mvp"
            assert len(ctx["projects"]) == 2 and any(p.get("active") for p in ctx["projects"])
            _, text, err = await call("coach_project", {"action": "switch", "project": "gamma"})
            assert err and "no Project 'gamma'" in text
            st, _, _ = await call("coach_corpus_status")
            assert st["store"]["project"] == {"id": "acme", "name": "Acme"} and st["store"]["projects"] == 2
        assert _serve(user, first) is not False

        async def second(call):                          # a new session: two Projects, none chosen (R1)
            ctx, text, _ = await call("coach_get_context")
            assert ctx["project"] is None and ctx["goals"] == [] and ctx["profile"] == {}
            assert [n["kind"] for n in ctx["nudges"]] == ["choose_project"] and "beta-labs (Beta Labs)" in text
            _, text, err = await call("coach_record", {"entry": {"kind": "goal", "text": "x"}, "request_id": _rid()})
            assert err and "Which Project is this about?" in text and "nothing was read or saved" in text
            _, text, err = await call("coach_update_profile", {"changes": {"stage": "pmf"}, "request_id": _rid()})
            assert err and "Which Project" in text
            out, _, _ = await call("coach_project", {"action": "switch", "project": "BETA LABS"})
            assert out["active"]["id"] == "beta-labs"
            ctx, _, _ = await call("coach_get_context")
            assert [g["text"] for g in ctx["goals"]] == ["Ship v1"]
            out, _, _ = await call("coach_project", {"action": "rename", "name": "Beta"})
            assert out["active"] == {"id": "beta-labs", "name": "Beta"}
        _serve(user, second)
        root = user / ".ytbrain"
        assert (root / "projects" / "acme" / "founder.db").exists() and (root / "projects" / "beta-labs" / "FOUNDER.md").exists()
        assert (root / "last-project").read_text() == "beta-labs"
        assert not (user / ".founder-coach").exists(), "nothing is written to the old data folder"


def test_the_first_save_names_the_project_after_the_company_setup_gives():
    with _machine() as user:
        async def go(call):
            res, _, err = await call("coach_update_profile", {"changes": {"company": "Acme Dental", "stage": "mvp"},
                                                                "request_id": _rid()})
            assert not err and res["saved_to"] == "Project Acme Dental (acme-dental)"
            out, _, _ = await call("coach_project", {"action": "list"})
            assert [p["name"] for p in out["projects"]] == ["Acme Dental"]
        _serve(user, go)


def test_a_projects_first_name_is_the_first_clause_of_what_setup_gives():
    from founder_coach.server import DEFAULT_PROJECT, _first_project_name
    assert _first_project_name("Acme Dental") == "Acme Dental"
    assert _first_project_name("Payments API, card payments for online shops") == "Payments API"
    assert _first_project_name("Search Indexer; a batch pipeline") == "Search Indexer"
    assert _first_project_name("Retirement 2055 - for me") == "Retirement 2055"
    assert _first_project_name("E-commerce Co") == "E-commerce Co", "a hyphen inside a word is not a clause"
    assert _first_project_name("  ") == DEFAULT_PROJECT and _first_project_name(None) == DEFAULT_PROJECT
    assert len(_first_project_name("x" * 300)) <= 80


def test_the_first_save_makes_a_project_and_a_pinned_folder_has_none():
    with _machine() as user:
        async def go(call):
            res, _, err = await call("coach_update_profile", {"changes": {"stage": "idea"}, "request_id": _rid()})
            assert not err and res["saved_to"] == "Project My project (my-project)"
            out, _, _ = await call("coach_project", {"action": "list"})
            assert out["active"]["id"] == "my-project" and len(out["projects"]) == 1
        _serve(user, go)

        async def again(call):          # one Project and the app names no folder: nothing says it is this conversation's
            ctx, _, _ = await call("coach_get_context")
            assert [n["kind"] for n in ctx["nudges"]] == ["choose_project"] and "my-project" in ctx["nudges"][0]["message"]
            assert "no work folder" in ctx["nudges"][0]["message"] and ctx["goals"] == [] and ctx["profile"].get("stage") is None
            _, text, err = await call("coach_update_profile", {"changes": {"stage": "mvp"}, "request_id": _rid()})
            assert err and "Which Project is this about?" in text and "my-project" in text, "nothing is saved before the answer"
            out, _, err = await call("coach_project", {"action": "switch", "project": "my-project"})
            assert not err and out["active"]["id"] == "my-project"
            ctx, _, _ = await call("coach_get_context")
            assert ctx["project"]["id"] == "my-project" and ctx["profile"]["stage"] == "idea" and ctx["projects"] is None
        _serve(user, again)

        pinned = Path(tempfile.mkdtemp())

        async def single(call):
            out, _, err = await call("coach_project", {"action": "create", "name": "X"})
            assert not err and out["mode"] == "single" and "Projects are off" in out["note"]
            res, _, _ = await call("coach_update_profile", {"changes": {"stage": "mvp"}, "request_id": _rid()})
            assert res["saved_to"] is None
            _, text, err = await call("coach_update_profile", {"changes": {"name": "Kay"}, "stated": {"name": "call me Kay"}, "scope": "common",
                                                               "request_id": _rid()})
            assert err and "no Common profile" in text
            ctx, _, _ = await call("coach_get_context")
            assert ctx["project"] is None and ctx["profile"]["stage"] == "mvp"
        _serve(user, single, home=pinned)
        assert (pinned / "founder.db").exists() and not (pinned / "projects").exists()


# --- C2: the Common profile ----------------------------------------------------------------------------------
def test_the_common_profile_is_shared_only_on_a_yes_and_only_for_its_fields():
    with _machine() as user:
        async def go(call):
            await call("coach_project", {"action": "create", "name": "Acme"})
            await call("coach_update_profile", {"changes": {"name": "Kay", "company": "Acme"}, "stated": {"name": "call me Kay"}, "request_id": _rid()})
            await call("coach_project", {"action": "create", "name": "Beta"})
            ctx, _, _ = await call("coach_get_context")
            assert "name" not in ctx["profile"], "a project-scope save stays in its Project"
            res, _, err = await call("coach_update_profile", {"changes": {"name": "Kay", "timezone": "Asia/Kolkata"}, "stated": {"name": "call me Kay"},
                                                              "scope": "common", "request_id": _rid()})
            assert not err and res["saved_to"].startswith("Common profile") and res["profile"]["name"] == "Kay"
            ctx, _, _ = await call("coach_get_context")
            assert ctx["profile"]["name"] == "Kay" and sorted(ctx["shared_fields"]) == ["name", "timezone"]
            assert ctx["timezone"] == "Asia/Kolkata", "the shared timezone sets the Project's day and week"
            await call("coach_project", {"action": "switch", "project": "acme"})
            ctx, _, _ = await call("coach_get_context")
            assert ctx["profile"]["name"] == "Kay" and ctx["shared_fields"] == ["timezone"], \
                "the Project's own value stands until it is shared from there"
            await call("coach_update_profile", {"changes": {"name": "Kay R"}, "stated": {"name": "call me Kay R"}, "scope": "common", "request_id": _rid()})
            ctx, _, _ = await call("coach_get_context")
            assert ctx["profile"]["name"] == "Kay R" and "name" in ctx["shared_fields"], \
                "sharing from a Project ends its own older value"
            await call("coach_project", {"action": "switch", "project": "beta"})
            ctx, _, _ = await call("coach_get_context")
            assert ctx["profile"]["name"] == "Kay R"
            _, text, err = await call("coach_update_profile", {"changes": {"company": "Beta"}, "scope": "common",
                                                               "request_id": _rid()})
            assert err and "only timezone, name, role, answer_style" in text and "company" in text
            out, _, _ = await call("coach_project", {"action": "summary", "project": "acme"})
            assert "name" not in out["summary"]["profile"], "a summary shows the Project's own facts only"
        _serve(user, go)
        eng = user / ".ytbrain"
        assert (eng / "you.db").exists() and "Kay R" in (eng / "YOU.md").read_text()
        acme = FounderStore(eng / "projects" / "acme")
        try:
            hist = [h["value"] for h in acme.profile_history("name")]
            assert hist == ["Kay"] and "name" not in acme._own_profile(), "kept in history, no longer current"
        finally:
            acme.close()


def test_calls_before_a_project_is_chosen_are_logged_in_the_common_profile_for_this_coach():
    """ADR-0026: with two Projects and none chosen, a call has no Project store; it goes to the Common profile's usage
    log, stamped with this coach, so what was asked before choosing is not lost. Once a Project is chosen, calls go to
    its own log again, and `usage clear` empties both."""
    import contextlib, io
    from founder_coach import cli
    from founder_coach import domain as D
    pack = str(product.PACK.get("id") or "founder")
    with _machine() as user:
        async def setup(call):
            await call("coach_project", {"action": "create", "name": "Acme"})
            await call("coach_project", {"action": "create", "name": "Beta"})
            res, _, err = await call("coach_update_profile", {"changes": {"timezone": "Asia/Kolkata"},
                                                              "scope": "common", "request_id": _rid()})
            assert not err, res
        _serve(user, setup)

        async def later(call):                           # a new session: nothing chosen yet
            ctx, _, _ = await call("coach_get_context")
            assert ctx["project"] is None
            await call("coach_search", {"query": "how to price a pilot"})
            _, _, err = await call("coach_record", {"entry": {"kind": "goal", "text": "x"}, "request_id": _rid()})
            assert err
            await call("coach_project", {"action": "switch", "project": "acme"})
            await call("coach_get_context")
        _serve(user, later)
        eng = user / ".ytbrain"
        common = FounderStore(eng, name="you", fields=D.COMMON_FIELDS)
        try:
            rows = common.usage_rows()
            assert rows == [], "the Common profile's own coach stamp holds nothing"
            mine = [dict(r) for r in common.db.execute("SELECT tool, outcome, coach, detail FROM usage ORDER BY id")]
        finally:
            common.close()
        before = [r for r in mine if r["coach"] == pack]
        tools = [r["tool"] for r in before]
        assert tools[:3] == ["coach_get_context", "coach_search", "coach_record"], tools
        assert before[0]["detail"] and json.loads(before[0]["detail"]).get("no_project") is True
        assert before[2]["outcome"] == "error" and "how to price" not in json.dumps(mine)
        acme = FounderStore(eng / "projects" / "acme")
        try:
            after = [r["tool"] for r in acme.usage_rows()]
        finally:
            acme.close()
        assert after[-1] == "coach_get_context" and "coach_search" not in after, after
        with contextlib.redirect_stdout(io.StringIO()):
            assert cli.main(["usage", "clear", "--home", str(eng / "projects" / "acme"), "--yes"]) == 0
        common = FounderStore(eng, name="you", fields=D.COMMON_FIELDS)
        try:
            left = common.db.execute("SELECT COUNT(*) FROM usage WHERE coach=?", (pack,)).fetchone()[0]
        finally:
            common.close()
        assert left == 0, "usage clear also empties this coach's rows from before a Project"


def test_a_pack_that_shares_nothing_never_reads_or_writes_the_common_profile():
    saved = product.PACK.get("common_fields")
    product.PACK["common_fields"] = []
    try:
        with _machine() as user:
            c = FounderStore(user / ".ytbrain", name="you")
            c.update_profile({"name": "Kay"})
            c.close()

            async def go(call):
                await call("coach_project", {"action": "create", "name": "Fund I"})
                ctx, _, _ = await call("coach_get_context")
                assert "name" not in ctx["profile"] and ctx["shared_fields"] is None
                _, text, err = await call("coach_update_profile", {"changes": {"name": "K"}, "stated": {"name": "call me K"}, "scope": "common",
                                                                   "request_id": _rid()})
                assert err and "shares no profile fields" in text
            _serve(user, go)
    finally:
        product.PACK["common_fields"] = saved


# --- C3: the one-time move of the old store ------------------------------------------------------------------
def _digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_the_old_store_moves_into_a_project_once_and_is_left_as_it_was():
    with _machine() as user:
        old = user / ".founder-coach"
        s = FounderStore(old)
        s.update_profile({"company": "Acme", "stage": "mvp", "timezone": "Europe/Berlin"})
        s.record({"kind": "goal", "text": "10 design partners"})
        s.close()
        before = _digest(old / "founder.db")
        ws = Workspace.open()
        assert ws.migration["status"] == "migrated" and ws.migration["project"] == "acme"
        assert ws.migration["timezone_to_common"] == "Europe/Berlin"
        assert _digest(old / "founder.db") == before, "the old store is the backup: never changed"
        assert [p["name"] for p in ws.projects.list()] == ["Acme"] and ws.choose() is None and ws.choose(use_last=True) == "acme"
        home = ws.store_home("acme")
        assert (home / "backups" / "founder-migrated.db").exists() and (home / "FOUNDER.md").exists()
        common = ws.open_common()
        store, err = ws.open_store("acme", common=common)
        try:
            assert err is None and [g["text"] for g in store.goals()] == ["10 design partners"]
            assert store.profile()["company"]["value"] == "Acme" and str(store.tz().key) == "Europe/Berlin"
            assert store.shared_fields() == ["timezone"] and "timezone" not in store._own_profile()
        finally:
            store.close()
            common.close()
        again = Workspace.open()
        assert again.migration is None and len(again.projects.list()) == 1, "once, however often it starts"
        import sqlite3
        a, b = sqlite3.connect(old / "founder.db"), sqlite3.connect(home / "founder.db")
        try:
            for t in ("goals", "commitments", "decisions", "checkins", "feedback", "profile_facts"):
                assert a.execute(f"SELECT COUNT(*) FROM {t}").fetchone() == b.execute(f"SELECT COUNT(*) FROM {t}").fetchone(), t
            log_a = a.execute("SELECT at, entity, entity_id, op FROM changes ORDER BY seq").fetchall()
            log_b = b.execute("SELECT at, entity, entity_id, op FROM changes ORDER BY seq").fetchall()
            assert log_b[:len(log_a)] == log_a and [r[3] for r in log_b[len(log_a):]] == ["move_to_common"]
        finally:
            a.close()
            b.close()


def test_a_damaged_or_busy_old_store_is_not_moved_and_is_tried_again():
    with _machine() as user:
        old = user / ".founder-coach"
        old.mkdir()
        (old / "founder.db").write_bytes(b"not a database at all" * 100)
        ws = Workspace.open()
        assert ws.migration["status"] == "failed" and ws.projects.list() == []
        assert not (ws.root / ".migrated.json").exists() and not (ws.root / ".migrating").exists()
        assert Workspace.open().migration["status"] == "failed", "retried at the next start"
        assert not list(ws.projects.dir.glob(".migrating-*")), "no half-made Project left behind"
    with _machine() as user:
        s = FounderStore(user / ".founder-coach")
        s.update_profile({"company": "Acme"})
        s.close()
        root = user / ".ytbrain" / "founder"             # the lock sits in the coach's own folder
        root.mkdir(parents=True)
        (root / ".migrating").write_text("123")              # another process is moving it right now
        assert Workspace.open().migration == {"status": "busy"}
        assert not (user / ".ytbrain" / "projects").exists()
        os.utime(root / ".migrating", (1, 1))               # that process died long ago: take over
        assert Workspace.open().migration["status"] == "migrated"


def test_a_pinned_data_folder_is_never_moved():
    with _machine() as user:
        s = FounderStore(user / ".founder-coach")
        s.update_profile({"company": "Acme"})
        s.close()
        ws = Workspace.open(user / ".founder-coach")
        assert ws.single and ws.migration is None and not (user / ".ytbrain").exists()


def test_the_models_stay_where_they_were_downloaded_until_the_shared_folder_exists():
    from founder_coach.models import models_dir
    with _machine() as user:
        old = user / ".founder-coach" / "models"
        old.mkdir(parents=True)
        (old / "a-model").write_text("x")
        assert models_dir() == old, "no second download after the update"
        (user / ".ytbrain" / "models").mkdir(parents=True)
        assert models_dir() == user / ".ytbrain" / "models"
    with _machine() as user:
        assert models_dir() == user / ".ytbrain" / "models"


# --- C5: the command line -------------------------------------------------------------------------------------
def _cli(user: Path, *args, input=None):
    env = {k: v for k, v in os.environ.items() if k not in PINNED}
    env.update(HOME=str(user), YTBRAIN_HOME=str(user / ".ytbrain"))
    return subprocess.run([sys.executable, "-m", "founder_coach.cli", *args], input=input, text=True,
                          capture_output=True, cwd=ROOT, timeout=60, env=env, check=False)


def test_the_command_line_works_on_one_project_at_a_time():
    with _machine() as user:
        assert _cli(user, "projects", "create", "Acme").returncode == 0
        r = _cli(user, "projects", "create", "Beta", "Labs")
        assert r.returncode == 0 and "beta-labs" in r.stdout
        r = _cli(user, "projects")
        assert "* beta-labs" in r.stdout and "  acme" in r.stdout
        s = FounderStore(user / ".ytbrain" / "projects" / "acme")
        s.update_profile({"company": "Acme", "stage": "mvp"})
        s.close()
        st = json.loads(_cli(user, "status", "--json", "--project", "acme").stdout)
        assert "projects/acme/founder.db" in st["store"] and st["profile"]["company"] == "Acme"
        assert "acme (active)" in st["projects"]
        r = _cli(user, "export", "--project", "nope")
        assert r.returncode == 2 and "no Project 'nope'" in r.stderr
        hook = json.loads(_cli(user, "hook", "session-start", input="{}").stdout)["hookSpecificOutput"]
        assert "2 Projects" in hook["additionalContext"] and "ask which Project" in hook["additionalContext"], \
            "the hook never guesses from the last Project used"
        assert _cli(user, "projects", "use", "acme").returncode == 0
        r = _cli(user, "export")
        assert r.returncode == 0 and "projects/acme/exports" in r.stdout
        r = _cli(user, "forget", "--all", "--confirm", "nope")
        assert r.returncode == 1 and "nothing deleted" in r.stdout
        r = _cli(user, "forget", "--all", "--confirm", "forget all")
        assert r.returncode == 0 and "2 Project(s)" in r.stdout
        st = json.loads(_cli(user, "status", "--json", "--project", "acme").stdout)
        assert st["profile"] == {}
        r = _cli(user, "projects", "--home", str(user / "pinned"))
        assert r.returncode == 0 and "Projects are off" in r.stdout


def test_the_hook_asks_which_project_when_several_and_none_was_used():
    with _machine() as user:
        root = user / ".ytbrain"
        ps = Projects(root)
        ps.create("Acme")
        ps.create("Beta")
        out = json.loads(_cli(user, "hook", "session-start", input="{}").stdout)["hookSpecificOutput"]
        assert "2 Projects (Acme, Beta)" in out["additionalContext"] and "ask which Project" in out["additionalContext"]
        assert not (root / "projects" / "acme" / "founder.db").exists(), "the hook reads nothing it wasn't told to"


def test_a_save_proposed_for_one_project_is_never_written_to_another():
    with _machine() as user:
        async def go(call):
            await call("coach_project", {"action": "create", "name": "Acme"})
            await call("coach_project", {"action": "create", "name": "Beta"})        # switched before the yes
            _, text, err = await call("coach_record", {"entry": {"kind": "goal", "text": "10 clinics"},
                                                       "request_id": _rid(), "project": "acme"})
            assert err and "proposed for Project Acme (acme), but the active Project is Beta (beta)" in text
            _, text, err = await call("coach_update_profile", {"changes": {"stage": "mvp"}, "project": "nope",
                                                               "request_id": _rid()})
            assert err and "no Project 'nope'" in text
            res, _, err = await call("coach_record", {"entry": {"kind": "goal", "text": "Ship v1"},
                                                      "request_id": _rid(), "project": "beta"})
            assert not err and res["ids"]
            ctx, _, _ = await call("coach_get_context")
            _, _, err = await call("coach_update", {"id": ctx["goals"][0]["id"], "status": "met", "project": "acme",
                                                    "request_id": _rid()})
            assert err
            out, _, _ = await call("coach_project", {"action": "summary", "project": "acme"})
            assert out["summary"]["goals"] == [], "nothing reached Acme"
        _serve(user, go)


def test_forgetting_one_project_leaves_the_others_byte_identical():
    with _machine() as user:
        root = user / ".ytbrain"
        ps = Projects(root)
        homes = {}
        for name in ("Acme", "Beta"):
            homes[name] = ps.store_home(ps.create(name)["id"])
            s = FounderStore(homes[name])
            s.update_profile({"company": name, "stage": "mvp"})
            s.record({"kind": "goal", "text": f"{name} goal"})
            s.close()
        before = {f.relative_to(homes["Beta"]): _digest(f) for f in homes["Beta"].rglob("*") if f.is_file()}
        r = _cli(user, "forget", "--project", "acme", "--confirm", "Acme")
        assert r.returncode == 0, r.stderr
        r = _cli(user, "export", "--project", "acme", "--out", str(user / "out"))
        data = json.loads((user / "out" / "founder-export.json").read_text())
        assert data["goals"] == [] and data["profile"] == {}
        after = {f.relative_to(homes["Beta"]): _digest(f) for f in homes["Beta"].rglob("*") if f.is_file()}
        assert after == before, "another Project's files are untouched"


def test_two_coaches_write_the_common_profile_at_once():
    with _machine() as user:
        eng = user / ".ytbrain"
        code = ("import sys; from pathlib import Path; from founder_coach.store import FounderStore\n"
                "s = FounderStore(Path(sys.argv[1]), name='you')\n"
                "for i in range(25):\n"
                "    s.update_profile({'answer_style': f'{sys.argv[2]} {i}'}, request_id=f'{sys.argv[2]}-{i}')\n"
                "s.close()\n")
        env = {k: v for k, v in os.environ.items() if k not in PINNED}
        procs = [subprocess.Popen([sys.executable, "-c", code, str(eng), who], cwd=ROOT, env=env,
                                  stderr=subprocess.PIPE, text=True) for who in ("founder", "coding")]
        errs = [p.communicate(timeout=120)[1] for p in procs]
        assert all(p.returncode == 0 for p in procs), errs
        s = FounderStore(eng, name="you")
        try:
            assert len(s.profile_history("answer_style")) == 50 and s.check()["ok"]
        finally:
            s.close()



# --- ADR-0019: Projects shared by every coach; the one-time move of each coach's own Projects ---------------------
def _old_layout_project(eng: Path, pack: str, pid: str, name: str, goal: str, created: str = "2026-01-01T00:00:00+00:00"):
    """A Project as a coach kept it before ADR-0019: eng/<pack>/projects/<pid>/ with a schema-6 store (no stamp)."""
    from test_coach import _downgrade
    home = eng / pack / "projects" / pid
    home.mkdir(parents=True)
    (home / "project.json").write_text(json.dumps({"name": name, "created": created}))
    s = FounderStore(home, coach=pack)
    s.update_profile({"company": name})
    s.record({"kind": "goal", "text": goal})
    _downgrade(s, 6)
    s.close()
    return home


def _tree(folder: Path) -> dict:
    return {str(f.relative_to(folder)): _digest(f) for f in sorted(folder.rglob("*")) if f.is_file()}


def test_every_coachs_projects_move_once_into_the_shared_folder_and_each_coach_reads_its_own():
    with _machine() as user:
        eng = user / ".ytbrain"
        _old_layout_project(eng, "founder", "acme", "Acme", "10 design partners", "2026-01-01T00:00:00+00:00")
        _old_layout_project(eng, "coding", "api", "Billing API", "p99 under 200ms", "2026-02-01T00:00:00+00:00")
        _old_layout_project(eng, "investor", "savings", "Savings 2030", "reach the target mix", "2026-03-01T00:00:00+00:00")
        (eng / "coding" / "last-project").write_text("api")
        before = _tree(eng)
        ws = Workspace.open()
        info = ws.pack_migration
        assert info["status"] == "migrated" and not info["failed"], info
        assert sorted(m["from"] for m in info["moved"]) == ["coding/api", "founder/acme", "investor/savings"]
        assert [p["name"] for p in ws.projects.list()] == ["Acme", "Billing API", "Savings 2030"], "every coach lists all"
        assert ws.projects.last() == "api", "the shared default comes from the old per-coach default"
        assert (ws.projects.dir / ".migrated-from-packs.json").exists()
        for pid, pack, goal in (("acme", "founder", "10 design partners"), ("api", "coding", "p99 under 200ms"),
                                ("savings", "investor", "reach the target mix")):
            home = ws.projects.store_home(pid)
            assert (home / "backups" / "founder-migrated.db").exists(), "a backup is kept beside the copy"
            assert json.loads((home / "project.json").read_text())["migrated_from"] == f"{pack}/{pid}"
            mine = FounderStore(home, coach=pack)
            try:
                assert [g["text"] for g in mine.goals()] == [goal] and mine.profile()["company"]["value"]
                assert mine.check()["ok"]
            finally:
                mine.close()
            other = FounderStore(home, coach="someone-else")
            try:
                assert other.goals() == [], "a coach reads only the records it stamped"
            finally:
                other.close()
        assert {k: v for k, v in _tree(eng).items() if k in before} == before, "the old folders are untouched"
        again = Workspace.open()
        assert again.pack_migration is None and len(again.projects.list()) == 3, "once, however often it starts"
        import shutil
        shutil.rmtree(ws.projects.store_home("acme"))
        assert [p["id"] for p in Workspace.open().projects.list()] == ["api", "savings"], "a deleted Project stays deleted"


def test_two_coaches_with_the_same_project_name_are_kept_apart_not_merged():
    with _machine() as user:
        eng = user / ".ytbrain"
        _old_layout_project(eng, "founder", "acme", "Acme", "10 design partners", "2026-01-01T00:00:00+00:00")
        _old_layout_project(eng, "coding", "acme", "Acme", "ship the importer", "2026-02-01T00:00:00+00:00")
        ws = Workspace.open()
        assert ws.pack_migration["status"] == "migrated"
        got = {p["id"]: p["name"] for p in ws.projects.list()}
        assert got == {"acme": "Acme", "acme-coding": "Acme (coding)"}, got
        for pid, pack, goal in (("acme", "founder", "10 design partners"), ("acme-coding", "coding", "ship the importer")):
            s = FounderStore(ws.projects.store_home(pid), coach=pack)
            try:
                assert [g["text"] for g in s.goals()] == [goal]
            finally:
                s.close()


def test_a_damaged_coach_project_is_reported_and_retried_without_repeating_the_others():
    with _machine() as user:
        eng = user / ".ytbrain"
        _old_layout_project(eng, "founder", "acme", "Acme", "10 design partners", "2026-01-01T00:00:00+00:00")
        bad = _old_layout_project(eng, "coding", "api", "Billing API", "p99 under 200ms", "2026-02-01T00:00:00+00:00")
        good_db = (bad / "founder.db").read_bytes()
        (bad / "founder.db").write_bytes(b"not a database at all" * 100)
        ws = Workspace.open()
        info = ws.pack_migration
        assert info["status"] == "partial" and [f["from"] for f in info["failed"]] == ["coding/api"], info
        assert [p["id"] for p in ws.projects.list()] == ["acme"] and not (ws.projects.dir / ".migrated-from-packs.json").exists()
        assert not list(ws.projects.dir.glob(".migrating-*")), "no half-made Project left behind"
        (bad / "founder.db").write_bytes(good_db)        # the person restored it
        ws = Workspace.open()
        assert ws.pack_migration["status"] == "migrated" and [m["from"] for m in ws.pack_migration["moved"]] == ["coding/api"]
        assert sorted(p["id"] for p in ws.projects.list()) == ["acme", "api"], "acme was not moved twice"


def test_a_busy_lock_and_the_off_switch_leave_the_old_projects_alone():
    with _machine() as user:
        eng = user / ".ytbrain"
        _old_layout_project(eng, "founder", "acme", "Acme", "10 design partners")
        (eng / "projects").mkdir()
        (eng / "projects" / ".migrating-packs").write_text("123")      # another process is moving them now
        assert Workspace.open().pack_migration == {"status": "busy"}
        os.utime(eng / "projects" / ".migrating-packs", (1, 1))        # that process died long ago: take over
        os.environ[product.env_name("MIGRATE")] = "0"
        try:
            assert Workspace.open().pack_migration is None, "the evaluation machines never move"
        finally:
            os.environ.pop(product.env_name("MIGRATE"), None)
        assert Workspace.open().pack_migration["status"] == "migrated"


def test_a_rename_keeps_what_project_json_holds_and_the_old_single_store_lands_in_the_shared_folder():
    with _machine() as user:
        ps = Projects(user / ".ytbrain")
        p = ps.create("Acme")
        meta = json.loads((ps.dir / p["id"] / "project.json").read_text())
        (ps.dir / p["id"] / "project.json").write_text(json.dumps({**meta, "folders": ["/work/acme"]}))
        ps.rename("acme", "Acme Labs")
        kept = json.loads((ps.dir / "acme" / "project.json").read_text())
        assert kept["name"] == "Acme Labs" and kept["folders"] == ["/work/acme"]
        s = FounderStore(user / ".founder-coach")
        s.update_profile({"company": "Acme Labs"})
        s.close()
        ws = Workspace.open()
        names = [x["name"] for x in ws.projects.list()]
        assert ws.migration["status"] == "migrated" and names == ["Acme Labs", "Acme Labs (earlier)"], names


def test_project_md_lists_the_shared_core_with_the_coach_behind_each_and_nothing_private():
    with _machine() as user:
        eng = user / ".ytbrain"
        (eng / "installed").mkdir(parents=True)
        for pack, owned in (("founder", []), ("coding", []), ("investor", ["*"])):
            (eng / "installed" / f"{pack}-coach.json").write_text(json.dumps({"pack": pack, "owned": owned}))
        ps = Projects(eng)
        pid = ps.create("Acme")["id"]
        home = ps.store_home(pid)
        a = FounderStore(home, coach="founder")
        b = FounderStore(home, coach="coding")
        inv = FounderStore(home, coach="investor")
        inv.owned = ("*",)
        for who in (a, b, inv):
            who.peers_home = eng
        a.update_profile({"company": "Acme"})
        a.record({"kind": "goal", "text": "reach 10 customers"})
        b.record({"kind": "decision", "text": "use Postgres", "reasoning": "team knows it"})
        a.record({"kind": "note", "title": "Secret pricing talk", "summary": "private", "type": "discussion",
                  "origin": "user"})
        inv.record({"kind": "goal", "text": "reach the target mix"})
        text = (home / "PROJECT.md").read_text()
        assert text.startswith("# Acme") and "reach 10 customers (founder)" in text and "use Postgres (coding)" in text
        assert "target mix" not in text and "Secret pricing" not in text, "nothing a coach keeps to itself"
        assert "Coaches here: coding, founder" in text
        (home / "PROJECT.md").write_text("edited by hand")
        b.record({"kind": "goal", "text": "p99 under 200ms"})
        assert "edited by hand" not in (home / "PROJECT.md").read_text(), "edits are overwritten"
        assert "p99 under 200ms" in (home / "PROJECT.md").read_text()
        a.forget(keep_backup=False)
        left = (home / "PROJECT.md").read_text()
        assert "reach 10 customers" not in left and "use Postgres" in left, "forget removes only that coach's records"
        for who in (a, b, inv):
            who.close()


# --- ADR-0019 point 4: the work folder chooses the Project -------------------------------------------------------
def _checkout(parent: Path, name: str, remote: str | None = None) -> Path:
    d = parent / name
    (d / ".git").mkdir(parents=True)
    (d / ".git" / "config").write_text('[core]\n\tbare = false\n' + (
        f'[remote "origin"]\n\turl = {remote}\n' if remote else ""))
    return d


def test_a_session_with_no_folder_asks_which_project_even_when_there_is_only_one():
    with _machine() as user:
        ws = Workspace.open()
        only = ws.projects.create("Acme")["id"]
        repo = user / "work" / "acme"
        repo.mkdir(parents=True)
        # the app names no folder: nothing says this conversation is about the only Project, so none is chosen
        assert ws.choose() is None and ws.choose(folder=None) is None
        # a folder linked to nothing gets no memory and no fallback, as before
        assert ws.choose(folder=repo) is None
        # the command line may go on to the only Project, then the last one used
        assert ws.choose(use_last=True) == only
        # a linked folder chooses it
        ws.projects.link(only, repo)
        assert ws.choose(folder=repo) == only
        # a person's own choice (<PREFIX>PROJECT) is not a guess
        second = ws.projects.create("Beta")["id"]
        assert ws.choose() is None
        os.environ[product.env_name("PROJECT")] = second
        try:
            assert ws.choose() == second
        finally:
            os.environ.pop(product.env_name("PROJECT"), None)


def test_a_folder_is_linked_to_one_project_and_the_deepest_link_wins():
    with _machine() as user:
        ps = Projects(user / ".ytbrain")
        mono, api = ps.create("Monorepo")["id"], ps.create("Billing API")["id"]
        repo = user / "work" / "mono"
        (repo / "services" / "billing").mkdir(parents=True)
        ps.link(mono, repo)
        ps.link(api, repo / "services" / "billing")
        assert ps.for_folder(repo / "docs")[0]["id"] == mono and ps.for_folder(repo)[0]["id"] == mono
        assert ps.for_folder(repo / "services" / "billing" / "src")[0]["id"] == api, "the deepest linked folder decides"
        assert ps.for_folder(user / "elsewhere") == (None, None), "a folder linked to nothing gets no Project"
        try:
            ps.link(api, repo)
            raise AssertionError("a folder in two Projects")
        except ProjectError as e:
            assert "already linked" in str(e)
        assert ps.link(mono, repo)["already"] is True
        ps.unlink(mono, repo)
        assert ps.for_folder(repo / "docs") == (None, None) and ps.folders(mono) == []
        ps.rename(api, "Billing")
        assert [f["path"] for f in ps.folders(api)] == [str((repo / "services" / "billing").resolve())], "a rename keeps links"


def test_a_moved_checkout_is_found_by_its_remote_and_relinked_with_a_note():
    with _machine() as user:
        ps = Projects(user / ".ytbrain")
        pid = ps.create("Acme")["id"]
        old = _checkout(user / "old", "acme", "https://tok@example.com/acme/app.git")
        ps.link(pid, old)
        assert ps.folders(pid)[0]["remote"] == "https://example.com/acme/app.git", "credentials are never stored"
        new = _checkout(user / "new", "acme-app", "https://example.com/acme/app.git")
        found, note = ps.for_folder(new / "src" if (new / "src").exists() else new)
        assert found["id"] == pid and "moved" in note and str(new.resolve()) in note
        assert [f["path"] for f in ps.folders(pid)] == [str(new.resolve())]
        assert ps.for_folder(new) == (found, None), "found by path from then on"
        other = _checkout(user / "other", "clone", "https://example.com/else/other.git")
        assert ps.for_folder(other) == (None, None)


def test_the_cli_and_workspace_choose_by_folder_without_falling_back():
    with _machine() as user:
        ws = Workspace.open()
        a, b = ws.projects.create("Acme")["id"], ws.projects.create("Beta")["id"]
        folder = user / "work" / "beta"
        folder.mkdir(parents=True)
        ws.projects.link(b, folder)
        assert ws.choose(folder=folder) == b
        assert ws.choose(folder=user / "work" / "nowhere", use_last=True) is None, "no fallback to the last or the only one"
        assert ws.choose() is None and ws.choose(requested="acme") == a


def test_a_session_in_a_linked_folder_works_on_its_project_and_an_unlinked_one_keeps_no_memory():
    with _machine() as user:
        eng = user / ".ytbrain"
        ps = Projects(eng)
        a, b = ps.create("Acme")["id"], ps.create("Beta")["id"]
        linked, loose = user / "work" / "acme", user / "work" / "loose"
        linked.mkdir(parents=True)
        loose.mkdir(parents=True)
        ps.link(a, linked)
        s = FounderStore(ps.store_home(a))
        s.update_profile({"company": "Acme"})
        s.close()
        os.environ["CLAUDE_PROJECT_DIR"] = str(linked)
        try:
            async def in_linked(call):
                ctx, _, err = await call("coach_get_context")
                assert not err and ctx["project"]["id"] == a and ctx["profile"]["company"], ctx["project"]
            if _serve(user, in_linked) is False:
                return
            os.environ["CLAUDE_PROJECT_DIR"] = str(loose)

            async def in_loose(call):
                ctx, _, err = await call("coach_get_context")
                assert not err and ctx["project"] is None and ctx["nudges"][0]["kind"] == "link_folder", ctx["nudges"]
                _, text, err = await call("coach_record", {"entry": {"kind": "goal", "text": "x"}, "request_id": _rid()})
                assert err and "linked to no Project" in text and "nothing was read or saved" in text
                out, _, err = await call("coach_project", {"action": "link", "project": "beta"})
                assert not err and out["folder"]["linked_to"] == b and out["active"]["id"] == b, out
                res, _, err = await call("coach_record", {"entry": {"kind": "goal", "text": "Ship v1"},
                                                         "request_id": _rid(), "project": "beta"})
                assert not err and res["ids"]
                out, _, _ = await call("coach_project", {"action": "unlink"})
                assert out["folder"]["linked_to"] is None and out["active"] is None
            _serve(user, in_loose)
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)


def test_the_first_save_in_a_folder_makes_a_project_and_links_the_folder():
    with _machine() as user:
        folder = user / "work" / "shop"
        folder.mkdir(parents=True)
        os.environ["CLAUDE_PROJECT_DIR"] = str(folder)
        try:
            async def go(call):
                res, _, err = await call("coach_update_profile", {"changes": {"company": "Shop"}, "request_id": _rid()})
                assert not err
                out, _, _ = await call("coach_project", {"action": "list"})
                assert out["folder"]["linked_to"] == "shop" and out["folders"] == [str(folder.resolve())]
            _serve(user, go)
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        assert Projects(user / ".ytbrain").for_folder(folder)[0]["id"] == "shop"


# --- G7: the coach evaluation's grading (offline) ------------------------------------------------------------
def test_g7_cases_are_well_formed_and_graded_on_every_projects_store():
    from ytbrain.eval import coach as C
    cases = C.load_cases("g7")
    assert len(cases) >= 2 and all(c["id"].startswith("g7-") for c in cases)
    for c in cases:
        turns = sum(len(x["turns"]) for x in c["sessions"])
        assert all(1 <= t["turn"] <= turns for t in c.get("turn_checks", [])), c["id"]
        assert len(c["sessions"]) >= 2, "isolation needs a new session"
    with _machine() as user:
        eng = user / ".ytbrain"
        ps = Projects(eng)
        for name, stage, goal in (("Acme Dental", "mvp", "10 paying clinics by 2026-12-15"),
                                  ("Kitebook", "idea", "50 waitlist signups by 2026-11-30")):
            s = FounderStore(ps.store_home(ps.create(name)["id"]))
            s.update_profile({"company": name, "stage": stage})
            s.record({"kind": "goal", "text": goal})
            s.close()
        c = FounderStore(eng, name="you")
        c.update_profile({"name": "Kay"})
        c.close()
        two = next(x for x in cases if x["id"] == "g7-two-companies-stay-apart")
        got = C.check_projects(eng, two["checks"], "2026-10-09T18:00:00+05:30")
        assert all(x["ok"] for x in got), got
        shared = next(x for x in cases if x["id"] == "g7-name-shared-only-on-a-yes")
        assert all(x["ok"] for x in C.check_projects(eng, shared["checks"], "2026-10-06T10:00:00+05:30"))
        s = FounderStore(ps.store_home("acme-dental"))
        s.record({"kind": "goal", "text": "500 waitlist signups"})      # Kitebook's fact in Acme's memory
        s.close()
        bad = {x["company"]: x["ok"] for x in C.check_projects(eng, two["checks"], "2026-10-09T18:00:00+05:30")
               if x["check"] == "goals"}
        assert bad == {"Acme Dental": False, "Kitebook": True}
    log = [{"coach": "Which one: Acme Dental or Kitebook?", "writes": [], "calls": []},
           {"coach": "Acme has 10 paying clinics as its goal.", "writes": [], "calls": []},
           {"coach": "Saved.", "writes": ["coach_update_profile"],
            "calls": [{"tool": "coach_update_profile", "input": {"changes": {"name": "Kay"}, "stated": {"name": "call me Kay"}, "scope": "common"}}]}]
    ask = {"turn": 1, "asks_project": True, "names": ["Acme", "Kitebook"], "not_mentions": ["clinics"],
           "no_memory_writes": True}
    assert C.turn_check(log, ask)["ok"]
    assert not C.turn_check(log, {**ask, "turn": 2})["ok"], "answering from one Project without asking fails"
    assert not C.turn_check(log, {"turn": 3, "no_common_write": True})["ok"]
    assert not C.turn_check(log, {"turn": 9, "mentions": ["x"]})["ok"], "a turn that never ran fails"


def test_g7_grades_sharing_inside_a_project_isolation_between_projects_and_owned_privacy():
    """ADR-0019: coaches of one Project read each other's Goals; another Project's never; a Pack that owns its
    memory is neither read nor reading. Graded with the same declarative checks as the host cases."""
    from ytbrain.eval import coach as C
    with _machine() as user:
        eng = user / ".ytbrain"
        ps = Projects(eng)
        homes = {n: ps.store_home(ps.create(n)["id"]) for n in ("Acme Dental", "Kitebook")}
        for n, who, goal in (("Acme Dental", "founder", "10 paying clinics by 2026-12-15"),
                             ("Acme Dental", "coding", "p99 under 200ms for booking"),
                             ("Acme Dental", "investor", "reach the target mix"),
                             ("Kitebook", "founder", "50 waitlist signups by 2026-11-30")):
            s = FounderStore(homes[n], coach=who)
            s.update_profile({"company": n})
            s.record({"kind": "goal", "text": goal})
            s.close()

        def goals(company, as_, peers, owned=(), **kw):
            c = {"check": "goals", "company": company, "as": as_, "peers": peers, "owned": list(owned), **kw}
            return C.check_projects(eng, [c], "2026-10-09T18:00:00+05:30")[0]
        both = {"founder": [], "coding": []}
        assert goals("Acme Dental", "coding", both, contains="clinics", absent=["waitlist"], min=2)["ok"]
        assert goals("Acme Dental", "founder", both, contains="p99", absent=["waitlist"], min=2)["ok"]
        # a Project is a boundary: Kitebook's Goal never reaches Acme's coaches
        assert goals("Acme Dental", "coding", both, absent=["waitlist"])["ok"]
        k = goals("Kitebook", "coding", both, contains="waitlist", absent=["clinic", "p99"], max=1)
        assert k["ok"], k
        # a coach with no peers (a pinned folder) reads only its own records
        mine = goals("Acme Dental", "coding", {}, contains="p99", absent=["clinics"], max=1)
        assert mine["ok"], mine
        # an owned Pack neither reads nor is read
        iso = goals("Acme Dental", "investor", {"founder": [], "coding": []}, owned=["*"], contains="target mix",
                    absent=["clinics", "p99"], max=1)
        assert iso["ok"], iso
        hidden = goals("Acme Dental", "founder", {"investor": ["*"], "coding": []}, absent=["target mix"], min=2)
        assert hidden["ok"], hidden
        leak = goals("Acme Dental", "founder", {"investor": [], "coding": []}, absent=["target mix"])
        assert not leak["ok"], "the check fails when an owned Pack's record reaches another coach"


def test_the_persons_own_facts_are_saved_only_in_their_own_words():
    """G5 (2026-10-09): the coach saved name='<the account holder>' and role='Founder' nobody had said. The server can't
    see the conversation, so name, role and answer_style need `stated`, the person's words, or nothing is saved."""
    with _machine() as user:
        async def go(call):
            await call("coach_project", {"action": "create", "name": "Acme"})
            for args, quote in (({"name": "Kaushal Ag"}, None),                      # from the account: no words
                                ({"name": "Kaushal Ag", "stage": "idea"}, None),     # nothing is saved, not even stage
                                ({"role": "CEO"}, "I work on payments"),             # words that don't say it
                                ({"name": "Kaushal"}, "")):
                body = {"changes": args, "request_id": _rid()}
                if quote is not None:
                    body["stated"] = {next(iter(args)): quote}
                _, text, err = await call("coach_update_profile", body)
                assert err and "own words" in text and "Nothing was saved" in text, (args, text)
            ctx, _, _ = await call("coach_get_context")
            assert not {"name", "role", "stage"} & set(ctx["profile"]), ctx["profile"]
            res, _, err = await call("coach_update_profile", {
                "changes": {"role": "solo founder", "answer_style": "short, bullets first", "stage": "idea"},
                "stated": {"role": "I'm a solo founder", "answer_style": "keep it short, bullets first"},
                "request_id": _rid()})
            assert not err and set(res["updated"]) == {"role", "answer_style", "stage"}
            res, _, err = await call("coach_update_profile", {"changes": {"stage": "mvp", "team_size": 2},
                                                              "request_id": _rid()})
            assert not err, "fields about the company need no quote"
        _serve(user, go)


# ---- the Project vault (ADR-0020 amendment): plain Markdown a graph viewer opens --------------------------------------

def _vault_links_resolve(root: Path) -> None:
    """Every [[link]] in the vault names a file in it: links carry their folder ([[shared/goals/X|X]])."""
    import re
    for p in list(root.rglob("*.md")):
        for target in re.findall(r"\[\[([^\]|#]+)", p.read_text(encoding="utf-8")):
            assert (root / f"{target}.md").is_file(), f"{p.relative_to(root)} links to [[{target}]], not in the vault"


def _vault_text(root: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.md")))


def _page(root: Path, rid: str) -> Path:
    """The page of a record (its id is in the frontmatter, not in the file name)."""
    hits = [p for p in root.rglob("*.md") if f'id: "{rid}"' in p.read_text(encoding="utf-8")[:600]]
    assert len(hits) == 1, (rid, hits)
    return hits[0]


def _seed(home: Path, coach: str | None = None, **kw) -> tuple[FounderStore, dict]:
    s = FounderStore(home, clock=kw.get("clock"), **({"coach": coach} if coach else {}))
    g = s.record({"kind": "goal", "text": "Ten paying design partners", "measure": "ten signed"})["ids"][0]
    d = s.record({"kind": "decision", "text": "Charge from day one", "reasoning": "paying users tell the truth"})["ids"][0]
    c1 = s.record({"kind": "commitments", "items": [{"action": "Email 20 dentists", "outcome": "5 calls booked",
                                                      "goal_id": g}]})["ids"][0]
    n = s.record({"kind": "note", "title": "Why charge early", "summary": "Five clinics said the price is fine.",
                  "type": "discussion", "origin": "user",
                  "links": [{"to": d, "type": "about"}, {"to": g, "type": "supports"}]})["ids"][0]
    return s, {"goal": g, "decision": d, "commitment": c1, "note": n}


def test_a_save_writes_the_vault_slice_with_linked_tagged_files():
    from founder_coach import vault
    with _machine():
        home = Path(tempfile.mkdtemp(prefix="vault-"))
        s, ids = _seed(home)
        root = home / "vault"
        try:
            names = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
            for want in ("shared/goals/Ten paying design partners.md", "shared/threads/Email 20 dentists.md",
                         "shared/decisions/Charge from day one.md", "founder/notes/Why charge early.md",
                         "_meta/shared/home.md", "_meta/views/threads.base", "_meta/views/decisions.base"):
                assert want in names, (want, names)
            assert any(n.startswith("shared/weeks/20") for n in names), "the week a Decision was made has a page"
            _vault_links_resolve(root)
            goal_link = "[[shared/goals/Ten paying design partners|Ten paying design partners]]"
            note = _page(root, ids["note"]).read_text()
            assert "tags: [kind/note, coach/founder]" in note
            assert "about:: [[shared/decisions/Charge from day one|Charge from day one]]" in note, "typed inline link"
            assert f'supports: ["{goal_link}"]' in note, "the same link as a frontmatter property"
            thread = _page(root, ids["commitment"]).read_text()
            assert f"serves:: {goal_link}" in thread and "periods: 1" in thread and "## History" in thread
            dec = _page(root, ids["decision"]).read_text()
            assert "decided_in:: [[shared/weeks/20" in dec, "a Decision hangs on the week it was made"
            goal = _page(root, ids["goal"]).read_text()
            assert "[[shared/threads/Email 20 dentists|Email 20 dentists]]" in goal
            assert "Why charge early" not in goal, "a shared page never names a coach's private Note"
            hub = (root / "_meta" / "shared" / "home.md").read_text()
            assert goal_link in hub and ids["decision"] not in hub, "the hub (out of the graph) lists the Goals"
            # the same data gives the same files
            assert vault.sync_slice(s)["written"] == 0
            # a carried task stays one thread, with its history
            new = s.update(ids["commitment"], status="carried")["new_id"]
            thread = _page(root, ids["commitment"]).read_text()
            assert "periods: 2" in thread and new in thread and len(list((root / "shared" / "threads").glob("*.md"))) == 1
            # graph.json: our colours and the _meta filter merged in, the person's own settings kept
            colours = root / ".obsidian" / "graph.json"
            g = json.loads(colours.read_text())
            assert g["search"] == "-path:_meta" and any(x["query"] == "tag:#kind/thread" for x in g["colorGroups"])
            colours.write_text(json.dumps({"search": "tag:#mine", "scale": 1.5,
                                           "colorGroups": [{"query": "path:x", "color": {"a": 1, "rgb": 1}}]}))
            s.record({"kind": "decision", "text": "Hire later", "reasoning": "r"})
            g = json.loads(colours.read_text())
            assert g["search"] == "tag:#mine" and g["scale"] == 1.5 and {"query": "path:x", "color": {"a": 1, "rgb": 1}} \
                in g["colorGroups"] and any(x["query"] == "tag:#kind/goal" for x in g["colorGroups"])
            # the Notes folder of ADR-0020 is untouched by the vault
            assert (home / "notes" / "INDEX.md").exists()
        finally:
            s.close()


def test_a_full_build_reads_a_copy_and_keeps_each_private_coach_apart():
    from founder_coach import vault
    with _machine():
        home = Path(tempfile.mkdtemp(prefix="vault-"))
        engine = Path(tempfile.mkdtemp(prefix="engine-"))
        (engine / "installed").mkdir()
        for pack, owned in (("founder", []), ("investor", ["*"])):
            (engine / "installed" / f"{pack}-coach.json").write_text(json.dumps({"pack": pack, "owned": owned}))
        s, ids = _seed(home)
        inv = FounderStore(home, coach="investor")
        ig = inv.record({"kind": "goal", "text": "Retire at 55 with ACME-secret fund", "measure": "x"})["ids"][0]
        inn = inv.record({"kind": "note", "title": "Rebalance thinking", "summary": "Bonds drifted.", "type": "insight",
                          "origin": "user", "links": [{"to": ig, "type": "about"}]})["ids"][0]
        inv.db.execute("INSERT INTO holdings_snapshots (id, founder_id, coach, account, as_of, imported_at, broker, "
                       "sha256, source, total_cents) VALUES ('h-1','me','investor','ACCT-9876','2026-10-01','2026-10-01',"
                       "'b','x','s',100)")
        inv.db.execute("INSERT INTO positions (snapshot_id, symbol, value_cents) VALUES ('h-1','ZZTOPSYM',100)")
        inv.close()
        s.close()
        before = {p.relative_to(home).as_posix(): p.stat().st_mtime_ns for p in home.rglob("*") if p.is_file()}
        out = Path(tempfile.mkdtemp(prefix="vault-out-"))
        res = vault.build(home, out, engine)
        after = {p.relative_to(home).as_posix(): p.stat().st_mtime_ns for p in home.rglob("*") if p.is_file()}
        assert before == after, "the Project folder was touched by a build"
        assert res["files"] > 0 and (out / "_meta" / "INDEX.md").exists()
        shared = _vault_text(out / "shared")
        assert "ACME-secret" not in shared and "Rebalance" not in shared, "a private coach's record reached shared/"
        assert _page(out, ig).relative_to(out).as_posix().startswith("investor/goals/")
        assert _page(out, inn).relative_to(out).as_posix().startswith("investor/notes/")
        everything = _vault_text(out)
        assert "ACCT-9876" not in everything and "ZZTOPSYM" not in everything, "holdings must never enter the vault"
        _vault_links_resolve(out)
        # a coach not in the registry is taken to keep everything to itself
        (engine / "installed" / "founder-coach.json").unlink()
        out2 = Path(tempfile.mkdtemp(prefix="vault-out-"))
        vault.build(home, out2, engine)
        assert not (out2 / "shared").exists() and _page(out2, ids["goal"]).relative_to(out2).as_posix().startswith(
            "founder/goals/")
        _vault_links_resolve(out2)


def test_a_slice_reads_only_what_the_coach_may_and_never_removes_another_coachs_files():
    from founder_coach import vault
    with _machine():
        home = Path(tempfile.mkdtemp(prefix="vault-"))
        other = FounderStore(home, coach="coding")
        og = other.record({"kind": "goal", "text": "Ship the importer", "measure": "merged"})["ids"][0]
        other.close()
        inv = FounderStore(home, coach="investor")
        inv.owned = ("*",)                          # as the investor's own server runs: it keeps everything private
        ig = inv.record({"kind": "goal", "text": "Private money goal", "measure": "x"})["ids"][0]
        inv.close()
        s = FounderStore(home)
        s.peers = {"coding": [], "investor": ["*"]}
        try:
            s.record({"kind": "goal", "text": "Find ten customers", "measure": "ten"})
            root = home / "vault"
            assert _page(root, og).relative_to(root).as_posix().startswith("shared/goals/"), \
                "a shared Goal of a peer coach is in the slice"
            keep = _page(root, ig)                  # the investor's own save wrote it in its own folder
            assert keep.relative_to(root).as_posix().startswith("investor/goals/")
            assert "Private money goal" not in _vault_text(root / "shared") + _vault_text(root / "founder")
            (root / "investor" / "NOTES-by-hand.md").write_text("mine, not generated", encoding="utf-8")
            vault.sync_slice(s)
            assert keep.exists() and (root / "investor" / "NOTES-by-hand.md").exists(), \
                "another coach's slice must not remove files it may not read"
            assert (root / "_meta" / "investor" / "home.md").exists(), "nor another coach's hub"
        finally:
            s.close()


def test_forget_clears_the_vault_and_a_newer_or_older_database_is_refused():
    from founder_coach import vault
    with _machine():
        home = Path(tempfile.mkdtemp(prefix="vault-"))
        s, _ = _seed(home)
        try:
            assert any((home / "vault").rglob("*.md"))
            s.forget()
            assert not any((home / "vault").rglob("*.md")), "forget must leave no record behind in the vault"
        finally:
            s.close()
        import sqlite3
        db = Path(tempfile.mkdtemp(prefix="vault-db-")) / "founder.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT INTO meta VALUES ('schema_version', '99')")
        con.commit()
        con.close()
        try:
            vault.build(db.parent, Path(tempfile.mkdtemp()), None)
        except vault.VaultError as e:
            assert "newer" in str(e)
        else:
            raise AssertionError("a newer database must be refused")
        con = sqlite3.connect(db)
        con.execute("UPDATE meta SET value='3'")
        con.commit()
        con.close()
        try:
            vault.build(db.parent, Path(tempfile.mkdtemp()), None)
        except vault.VaultError as e:
            assert "older" in str(e) and "Nothing was changed" in str(e)
        else:
            raise AssertionError("an older database must be refused, not migrated")


def test_the_vault_command_never_opens_the_store():
    from founder_coach import cli
    with _machine():
        home = Path(tempfile.mkdtemp(prefix="vault-"))
        s, _ = _seed(home)
        s.close()
        digest = {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in home.glob("founder.db*")}
        backups = sorted(p.name for p in (home / "backups").glob("*")) if (home / "backups").exists() else []
        out = Path(tempfile.mkdtemp(prefix="vault-out-"))
        rc = cli.main(["vault", "build", "--home", str(home), "--out", str(out), "--engine-home", str(home)])
        assert rc == 0 and (out / "_meta" / "INDEX.md").exists()
        assert digest == {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in home.glob("founder.db*")}, \
            "the database files changed"
        assert backups == (sorted(p.name for p in (home / "backups").glob("*")) if (home / "backups").exists() else [])


if __name__ == "__main__":
    import inspect
    import logging
    import traceback
    logging.disable(logging.WARNING)            # the SDK logs every expected tool error to stderr
    fns = [f for n, f in globals().items() if n.startswith("test_") and inspect.isfunction(f)]
    failed = 0
    for f in fns:
        try:
            f()
            print(f"  PASS  {f.__name__}")
        except Exception as e:                   # noqa: BLE001 -- report every test, not just the first
            failed += 1
            print(f"  FAIL  {f.__name__}: {type(e).__name__}: {str(e)[:300]}")
            if os.environ.get("VERBOSE"):
                traceback.print_exc()
    print(f"{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
