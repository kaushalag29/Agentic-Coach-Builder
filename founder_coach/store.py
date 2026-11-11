"""The founder store (ADR-0006, ADR-0011): what the coach remembers about one Founder.

Current-state tables plus one append-only `changes` log. Every write:
  - is a single `BEGIN IMMEDIATE` transaction that includes its log rows, so several host
    processes (and the SessionStart hook) can share the file safely (WAL, busy_timeout);
  - can carry a `request_id`: a retried write returns the first result instead of writing twice;
  - is followed by a regenerated, human-readable FOUNDER.md.
Backups use SQLite's backup API: daily on the first write (7 kept), before every migration
and before `forget`. Nothing here imports numpy, MCP or the models, so the hook stays fast.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import domain as D
from . import product

RECENT_ERRORS = 10                     # usage_summary lists this many of the newest tool errors
SCHEMA_VERSION = 8
MIGRATIONS: dict[int, list[str]] = {
    1: [
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        """CREATE TABLE profile_facts (id INTEGER PRIMARY KEY, founder_id TEXT NOT NULL, field TEXT NOT NULL,
             value TEXT NOT NULL, valid_from TEXT NOT NULL, superseded_at TEXT, confirmed_at TEXT NOT NULL,
             source TEXT NOT NULL)""",
        "CREATE INDEX profile_current ON profile_facts (founder_id, field, superseded_at)",
        """CREATE TABLE goals (id TEXT PRIMARY KEY, founder_id TEXT NOT NULL, text TEXT NOT NULL,
             measure TEXT, target_date TEXT, status TEXT NOT NULL, citations TEXT NOT NULL DEFAULT '[]',
             note TEXT, created_at TEXT NOT NULL, closed_at TEXT)""",
        """CREATE TABLE commitments (id TEXT PRIMARY KEY, founder_id TEXT NOT NULL, week TEXT NOT NULL,
             action TEXT NOT NULL, cue TEXT, outcome TEXT NOT NULL, goal_id TEXT, citations TEXT NOT NULL DEFAULT '[]',
             status TEXT NOT NULL, carried_from TEXT, result_note TEXT, created_at TEXT NOT NULL, closed_at TEXT)""",
        "CREATE INDEX commitments_week ON commitments (founder_id, week, status)",
        """CREATE TABLE decisions (id TEXT PRIMARY KEY, founder_id TEXT NOT NULL, text TEXT NOT NULL,
             reasoning TEXT NOT NULL, citations TEXT NOT NULL DEFAULT '[]', decided_at TEXT NOT NULL,
             revisit_on TEXT)""",
        """CREATE TABLE checkins (id TEXT PRIMARY KEY, founder_id TEXT NOT NULL, week TEXT NOT NULL,
             summary TEXT NOT NULL, wins TEXT NOT NULL DEFAULT '[]', blockers TEXT NOT NULL DEFAULT '[]',
             created_at TEXT NOT NULL)""",
        """CREATE TABLE changes (seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, founder_id TEXT NOT NULL,
             entity TEXT NOT NULL, entity_id TEXT NOT NULL, op TEXT NOT NULL, before TEXT, after TEXT,
             source TEXT NOT NULL)""",
        """CREATE TABLE requests (request_id TEXT PRIMARY KEY, at TEXT NOT NULL, result TEXT NOT NULL)""",
    ],
    # v2: a request_id is bound to the write it was first used for; reusing it for a
    # different write is refused instead of silently replaying the wrong result
    2: ["ALTER TABLE requests ADD COLUMN fingerprint TEXT"],
    # v3: Feedback, the Founder's reports of a wrong answer or record (turned into eval cases)
    3: ["""CREATE TABLE feedback (id TEXT PRIMARY KEY, founder_id TEXT NOT NULL, created_at TEXT NOT NULL,
             category TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL, cited TEXT NOT NULL DEFAULT '[]',
             searches TEXT NOT NULL DEFAULT '[]', note TEXT, expected TEXT, context TEXT NOT NULL DEFAULT '{}')"""],
    # v4: the usage log (docs/usage-log.md): one row per coach tool call, no Founder text by default
    4: ["""CREATE TABLE usage (id INTEGER PRIMARY KEY AUTOINCREMENT, founder_id TEXT NOT NULL, at TEXT NOT NULL,
             run TEXT NOT NULL, tool TEXT NOT NULL, outcome TEXT NOT NULL, duration_ms INTEGER NOT NULL,
             version TEXT, detail TEXT NOT NULL DEFAULT '{}')""",
        "CREATE INDEX usage_at ON usage (founder_id, at)"],
    # v5: Holdings (the investor Pack, M6g): one snapshot per account and date, its positions in cents, and the
    # person's own asset-class label per symbol. Every store gets the tables; only a Pack with `holdings` uses them.
    5: ["""CREATE TABLE holdings_snapshots (id TEXT PRIMARY KEY, founder_id TEXT NOT NULL, account TEXT NOT NULL,
             as_of TEXT NOT NULL, imported_at TEXT NOT NULL, broker TEXT NOT NULL, sha256 TEXT NOT NULL,
             source TEXT NOT NULL, total_cents INTEGER NOT NULL)""",
        "CREATE UNIQUE INDEX holdings_once ON holdings_snapshots (founder_id, account, as_of, sha256)",
        """CREATE TABLE positions (snapshot_id TEXT NOT NULL, symbol TEXT NOT NULL, description TEXT,
             quantity TEXT, value_cents INTEGER NOT NULL, csv_class TEXT)""",
        "CREATE INDEX positions_snapshot ON positions (snapshot_id)",
        """CREATE TABLE asset_classes (founder_id TEXT NOT NULL, symbol TEXT NOT NULL, asset_class TEXT NOT NULL,
             set_at TEXT NOT NULL, PRIMARY KEY (founder_id, symbol))"""],
    # v6: Notes (ADR-0020): dated, append-only memory of a discussion, research or insight, and the typed links
    # between records. The keyword index (notes_fts, SQLite FTS5) is created apart: see FTS_STATEMENT.
    6: ["""CREATE TABLE notes (id TEXT PRIMARY KEY, founder_id TEXT NOT NULL, title TEXT NOT NULL,
             summary TEXT NOT NULL, type TEXT NOT NULL, origin TEXT NOT NULL, citations TEXT NOT NULL DEFAULT '[]',
             evidence TEXT NOT NULL DEFAULT '[]', revisit_on TEXT, created_at TEXT NOT NULL,
             superseded_by TEXT, superseded_at TEXT)""",
        "CREATE INDEX notes_created ON notes (founder_id, created_at)",
        """CREATE TABLE links (founder_id TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL, type TEXT NOT NULL,
             created_at TEXT NOT NULL, PRIMARY KEY (founder_id, src, dst, type))""",
        "CREATE INDEX links_dst ON links (founder_id, dst)"],
    # v7: every record says which coach made it (ADR-0019). Rows from before take the coach that owns the store
    # (_migrate fills them in). Until the read rules of ADR-0019 exist, a coach reads only its own records.
    7: [f"ALTER TABLE {t} ADD COLUMN coach TEXT NOT NULL DEFAULT ''" for t in (
        "profile_facts", "goals", "commitments", "decisions", "checkins", "changes", "feedback", "usage",
        "holdings_snapshots", "asset_classes", "notes", "links")],
    # v8 (ADR-0025): nothing about a change is lost (why and by whom, on every change-log row); a Decision has a
    # status and the newer Decision that superseded it; links between any records, ended instead of deleted; the
    # People and Issues the person names; and the links the coach proposes, with the person's verdict on each.
    8: ["ALTER TABLE changes ADD COLUMN reason TEXT",
        "ALTER TABLE changes ADD COLUMN actor TEXT",
        "ALTER TABLE decisions ADD COLUMN status TEXT NOT NULL DEFAULT 'accepted'",
        "ALTER TABLE decisions ADD COLUMN superseded_by TEXT",
        "ALTER TABLE decisions ADD COLUMN superseded_at TEXT",
        "ALTER TABLE links ADD COLUMN ended_at TEXT",
        "CREATE INDEX IF NOT EXISTS links_src ON links (founder_id, src)",
        """CREATE TABLE people (id TEXT PRIMARY KEY, founder_id TEXT NOT NULL, coach TEXT NOT NULL DEFAULT '',
             name TEXT NOT NULL, aliases TEXT NOT NULL DEFAULT '[]', role TEXT, status TEXT NOT NULL DEFAULT 'active',
             merged_into TEXT, created_at TEXT NOT NULL, closed_at TEXT)""",
        """CREATE TABLE issues (id TEXT PRIMARY KEY, founder_id TEXT NOT NULL, coach TEXT NOT NULL DEFAULT '',
             text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', note TEXT, created_at TEXT NOT NULL,
             closed_at TEXT)""",
        """CREATE TABLE proposals (id TEXT PRIMARY KEY, founder_id TEXT NOT NULL, coach TEXT NOT NULL DEFAULT '',
             fingerprint TEXT NOT NULL, rule TEXT NOT NULL, tier TEXT NOT NULL, payload TEXT NOT NULL,
             why TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', shown INTEGER NOT NULL DEFAULT 0,
             snoozed_until TEXT, created_at TEXT NOT NULL, decided_at TEXT, UNIQUE (founder_id, fingerprint))"""],
}
COACH_TABLES_V7 = ("profile_facts", "goals", "commitments", "decisions", "checkins", "changes", "feedback", "usage",
                   "holdings_snapshots", "asset_classes", "notes", "links")
SHARED_KINDS = ("goals", "commitments", "decisions", "profile", "people", "issues")  # what the coaches of a Project share
COACH_TABLES = ("profile_facts", "goals", "commitments", "decisions", "checkins", "changes", "feedback", "usage",
                "holdings_snapshots", "asset_classes", "notes", "links", "people", "issues", "proposals")
# The Notes keyword index. A derived structure: it is rebuilt from `notes` (reindex_notes) and can be dropped without
# losing a Note. A SQLite build without FTS5 skips it and search falls back to LIKE.
FTS_STATEMENT = ("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(id UNINDEXED, title, summary, "
                 "tokenize='porter unicode61')")
TABLES = ("profile_facts", "goals", "commitments", "decisions", "checkins", "feedback", "changes",
          "holdings_snapshots", "positions", "asset_classes", "notes", "links", "people", "issues", "proposals")
# the usage log is kept apart from TABLES: it isn't coaching memory, so it never makes the store
# "have data" (daily backups) and never shows in FOUNDER.md; forget, export and restore still cover it
USAGE_OUTCOMES = ("ok", "empty", "gap", "error")
USAGE_BUSY_MS = 250                  # a usage write waits this long for a busy store, then gives up
DAILY_BACKUPS_KEPT = 7
WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")
# a record id (g-1a2b, pe-3c4d, ...): what the usage log may keep of a memory call; never a word the person typed
RECORD_ID = re.compile(r"^(?:" + "|".join(sorted(D.KIND_OF_PREFIX, key=len, reverse=True)) + r")-[0-9a-z]{2,16}$")
USAGE_ID_KEYS = ("id", "to")                                   # usage detail fields holding one record id
USAGE_ID_LISTS = ("ids", "edited", "ties", "planned")          # ... and a list of them (ADR-0026)
FORGOTTEN = "forgotten"                                        # what a forgotten record's id becomes in the log


class StoreError(ValueError):
    """A request the store can't carry out; the message says how to fix it."""


class StoreDamaged(StoreError):
    """The store file can't be read or fails its integrity check. Nothing is deleted:
    `founder-coach restore` sets the file aside and copies a backup in."""


RESTORE_HINT = f"Nothing has been deleted: run `{product.ID} restore` to set it aside and restore the latest good backup."


def _utc_now() -> dt.datetime:
    # FOUNDER_COACH_FAKE_NOW (ISO datetime) is for the coach evaluation only: it lets a
    # multi-week persona run through its weeks in minutes. Never set it for real use.
    fake = product.env("FAKE_NOW")
    if fake:
        t = dt.datetime.fromisoformat(fake)
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def iso_week(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_start(week: str) -> dt.date:
    m = WEEK_RE.match(week or "")
    if not m:
        raise StoreError(f"week must look like 2026-W39, got {week!r}")
    return dt.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)


def next_week(week: str) -> str:
    return iso_week(week_start(week) + dt.timedelta(days=7))


def _day_month(iso: str) -> str:
    """'4 Nov' for an ISO timestamp or date (the day it was recorded, as messages show it)."""
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)[:10]
    return f"{d.day} {d:%b}"


def shift_week(week: str, n: int) -> str:
    """The ISO week `n` weeks after `week` (before it when n is negative)."""
    return iso_week(week_start(week) + dt.timedelta(days=7 * n))


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


class FounderStore:
    """One store file. A Project's memory is `founder.db` (with FOUNDER.md); the Common profile the coaches
    share is the same kind of store named `you` (you.db, YOU.md) that keeps only D.COMMON_FIELDS (ADR-0016).
    A Project store given `common` reads the shared facts it doesn't set itself (`common_fields`)."""

    def __init__(self, home: str | Path | None = None, founder_id: str = "me",
                 clock: Callable[[], dt.datetime] | None = None, name: str = "founder",
                 fields: tuple[str, ...] | None = None, coach: str | None = None):
        self.home = Path(home).expanduser() if home else D.home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.name = name
        self.path = self.home / f"{name}.db"
        self.backups = self.home / "backups"
        self.md_path = self.home / f"{name.upper()}.md"
        self.fields = tuple(fields) if fields else tuple(D.PROFILE_FIELDS)
        self.common: FounderStore | None = None          # the Common profile (multi-Project mode only)
        self.common_fields: tuple[str, ...] = ()         # the shared facts this Pack reads from it
        self.fid = founder_id
        # the coach whose records this store reads and writes (ADR-0019): the running Pack's id unless the caller says
        # whose store it is (the move of another Pack's Projects); the Common profile belongs to no coach
        self.coach = (coach if coach is not None else
                      ("" if name != "founder" else str(product.PACK.get("id") or "founder")))
        # what this coach keeps to itself, and the other coaches of the Project (Pack -> what they keep to themselves):
        # the read rules of ADR-0019. With no peers (a pinned folder, a test) a coach reads only its own records.
        self.owned: tuple[str, ...] = (tuple(product.PACK.get("owned") or ())
                                       if self.coach == str(product.PACK.get("id") or "founder") else ())
        self.peers: dict[str, list[str]] = {}
        self.peers_home: Path | None = None              # the engine home whose installed/ registry names the peers
        self._peers_seen: object = None
        # derived files sit in the Project's folder, which coaches share: the founder Pack keeps its names, every other
        # coach gets its own (slice C replaces them with one PROJECT.md)
        own = self.coach not in ("", "founder")
        if own:
            self.md_path = self.home / f"{self.coach.upper()}.md"
        self.vault_dir = f"notes-{self.coach}" if own else "notes"
        self.clock = clock or _utc_now
        self.cite_check: Callable[[list[str]], list[str]] | None = None    # -> unknown ids
        self.cite_lookup: Callable[[str], dict | None] | None = None       # id -> {title, deep_link}
        self._lock = threading.RLock()
        self._why: tuple[str | None, str | None] = (None, None)   # why and by whom, for the write running now
        self._open()

    def _open(self) -> None:
        existed = self.path.exists() and self.path.stat().st_size > 0
        self._conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._file = _file_key(self.path)
        try:
            self._conn.execute("PRAGMA busy_timeout=5000")
            # Switching a new file to WAL needs a moment alone with it, and SQLite answers "locked" at once
            # instead of waiting: two coaches opening the shared Common profile together retry for a while.
            for attempt in range(50):
                try:
                    self._conn.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as e:
                    if "locked" not in str(e).lower() or attempt == 49:
                        raise
                    time.sleep(0.1)
            self._migrate(existed)
        except sqlite3.DatabaseError as e:
            self._conn.close()
            if isinstance(e, sqlite3.OperationalError) and "locked" in str(e).lower():
                raise                                      # busy, not damaged: the caller may retry
            raise StoreDamaged(f"the founder store at {self.path} can't be read ({e}). {RESTORE_HINT}") from e
        except StoreError:
            self._conn.close()
            raise

    @property
    def db(self) -> sqlite3.Connection:
        """The connection, reopened first if a restore renamed another file into place (the
        old one is set aside): a running session reads and writes the restored store, never
        the file that was moved away. Never mid-transaction."""
        if not self._conn.in_transaction:
            self._follow_replaced_file()
        return self._conn

    def _follow_replaced_file(self) -> None:
        key = _file_key(self.path)
        if key is not None and key != self._file:
            import logging
            logging.getLogger("founder_coach").warning("the founder store was replaced (restore); reopening it")
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._open()

    def check(self) -> dict:
        """SQLite's full integrity check: {"ok": bool, "detail": "ok" or the first problems}."""
        with self._lock:
            return _integrity(self.db)

    # ------------------------------------------------------------------ plumbing
    def _version(self) -> int:
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone():
            return 0
        row = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(row[0]) if row else 0

    def _migrate(self, existed: bool) -> None:
        with self._lock:
            v = self._version()
            if v > SCHEMA_VERSION:
                raise StoreError(f"the founder store at {self.path} is schema v{v}, newer than this coach "
                                 f"(v{SCHEMA_VERSION}): update the coach")
            if v == SCHEMA_VERSION:
                return
            if existed and v > 0:
                self.backup(f"pre-migration-v{v}")
            self.db.execute("BEGIN EXCLUSIVE")
            try:
                v = self._version()                  # another process may have migrated meanwhile
                for n in range(v + 1, SCHEMA_VERSION + 1):
                    for stmt in MIGRATIONS[n]:
                        self.db.execute(stmt)
                    if n == 6:
                        self._create_fts()
                    if n == 7 and existed and self.coach:
                        for t in COACH_TABLES_V7:      # the rows that were here belong to the coach that owns this store
                            self.db.execute(f"UPDATE {t} SET coach=?", (self.coach,))
                    self.db.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(n),))
                self.db.execute("COMMIT")
            except BaseException:
                _rollback(self.db)
                raise

    def _create_fts(self) -> bool:
        """Create the Notes keyword index; False when this SQLite has no FTS5 (search then uses LIKE)."""
        try:
            self.db.execute(FTS_STATEMENT)
            return True
        except sqlite3.OperationalError:
            return False

    def has_fts(self) -> bool:
        with self._lock:
            return bool(self.db.execute("SELECT 1 FROM sqlite_master WHERE name='notes_fts'").fetchone())

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def now(self) -> dt.datetime:
        return self.clock().astimezone(dt.timezone.utc)

    def _iso(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def tz(self) -> ZoneInfo:
        name = self._current_value("timezone") or self._common_value("timezone") or D.system_timezone()
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    def today(self) -> dt.date:
        return self.now().astimezone(self.tz()).date()

    def this_week(self) -> str:
        return iso_week(self.today())

    def _new_id(self, kind: str) -> str:
        table = {**D.TABLE_OF, "feedback": "feedback", "holdings": "holdings_snapshots"}[kind]
        while True:
            rid = f"{D.ID_PREFIX[kind]}-{secrets.token_hex(2)}"
            if not self.db.execute(f"SELECT 1 FROM {table} WHERE id=?", (rid,)).fetchone():
                return rid

    def _change(self, entity: str, entity_id: str, op: str, before, after, source: str, reason: str | None = None,
                actor: str | None = None) -> None:
        """One change-log row, in the transaction of the write it logs: when, what, the whole record before and
        after, which tool and coach, and (ADR-0025) why and by whom, as the person said it. `reason` and `actor`
        default to the ones the current write was given (`self._why`)."""
        why, who = self._why
        self.db.execute("INSERT INTO changes (at, founder_id, coach, entity, entity_id, op, before, after, source, reason, "
                        "actor) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (self._iso(), self.fid, self.coach, entity, entity_id, op,
                         None if before is None else _j(before), None if after is None else _j(after), source,
                         reason if reason is not None else why, actor or who))

    def _transact(self, request_id: str | None, fn: Callable[[], dict], what: object = None) -> dict:
        """Run `fn` -- validation and write together -- in one write transaction. A repeated
        request_id returns the first result before anything is re-validated (a retried carry
        replays; it doesn't fail as "already carried"), and only for the same write: `what`
        (the operation and its arguments) is fingerprinted with the id."""
        if request_id is not None and not (1 <= len(request_id) <= 100):
            raise StoreError("request_id must be 1-100 characters; reuse the same one when retrying")
        fp = hashlib.sha256(_j(what).encode()).hexdigest()[:16] if what is not None else None
        with self._lock:
            self._backup_if_due()
            self.db.execute("BEGIN IMMEDIATE")
            try:
                if request_id:
                    row = self.db.execute("SELECT result, fingerprint FROM requests WHERE request_id=?",
                                          (request_id,)).fetchone()
                    if row:
                        if fp and row["fingerprint"] and row["fingerprint"] != fp:
                            raise StoreError(f"request_id {request_id!r} was already used for a different "
                                             "write; use a fresh id for a new write (reuse it only to retry "
                                             "the same one)")
                        self.db.execute("COMMIT")
                        return {**json.loads(row[0]), "replayed": True}
                out = fn()
                if request_id:
                    self.db.execute("INSERT INTO requests (request_id, at, result, fingerprint) VALUES (?,?,?,?)",
                                    (request_id, self._iso(), _j(out), fp))
                self.db.execute("COMMIT")
            except BaseException:
                _rollback(self.db)
                raise
            self._write_markdown()
            self._write_vault()
            self._write_project_md()
        return out

    # ------------------------------------------------------------------ backups
    def backup(self, label: str) -> Path | None:
        """A consistent copy via SQLite's backup API (safe while others read or write)."""
        with self._lock:
            if not self._has_data():
                return None
            self.backups.mkdir(parents=True, exist_ok=True)
            dest = self.backups / f"{self.name}-{label}.db"
            # unique per process: two hosts may take the same daily backup at the same moment
            tmp = dest.with_name(f".{dest.name}.{os.getpid()}.{secrets.token_hex(3)}.tmp")
            try:
                out = sqlite3.connect(tmp)
                try:
                    self.db.backup(out)
                finally:
                    out.close()
                os.replace(tmp, dest)
            finally:
                tmp.unlink(missing_ok=True)
            return dest

    def _has_data(self) -> bool:
        try:
            return any(self.db.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone() for t in TABLES)
        except sqlite3.OperationalError:
            return False

    def _backup_if_due(self) -> None:
        """The day's first write takes a backup. A failed backup is logged, never a failed write."""
        day = self.today().isoformat()                 # the Founder's day, not UTC's
        if (self.backups / f"{self.name}-daily-{day}.db").exists():
            return
        try:
            if self.backup(f"daily-{day}"):
                daily = sorted(self.backups.glob(f"{self.name}-daily-*.db"))
                for old in daily[:-DAILY_BACKUPS_KEPT]:
                    old.unlink(missing_ok=True)
        except (OSError, sqlite3.Error) as e:
            import logging
            logging.getLogger("founder_coach").warning("daily backup failed: %s", e)

    # ------------------------------------------------------------------ validation
    def _check_citations(self, ids) -> list[str]:
        ids = [str(i).strip() for i in (ids or []) if str(i).strip()]
        if len(ids) > 10:
            raise StoreError("at most 10 citations per record")
        if ids and self.cite_check:
            unknown = self.cite_check(ids)
            if unknown:
                raise StoreError(f"unknown citation id(s): {', '.join(unknown)}. Cite only item_ids that "
                                 f"coach_search or coach_read returned in this conversation.")
        return list(dict.fromkeys(ids))

    @staticmethod
    def _text(value, name: str, required: bool = True) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                raise StoreError(f"{name} is required")
            return None
        if not isinstance(value, str):
            raise StoreError(f"{name} must be text")
        value = " ".join(value.split())
        if len(value) > D.TEXT_MAX:
            more = ("; for a longer account, keep this short and save the rest as a Note (coach_record kind note, "
                    "linked to this record)") if product.has("notes") else ""
            raise StoreError(f"{name} is longer than {D.TEXT_MAX} characters ({len(value)}); shorten it{more}")
        return value

    @staticmethod
    def _date(value, name: str) -> str | None:
        if value in (None, ""):
            return None
        try:
            return dt.date.fromisoformat(str(value)).isoformat()
        except ValueError:
            raise StoreError(f"{name} must be a date like 2026-10-31, got {value!r}") from None

    @staticmethod
    def _list(value, name: str) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or len(value) > 10:
            raise StoreError(f"{name} must be a list of up to 10 short texts")
        return [FounderStore._text(v, name) for v in value if str(v).strip()]

    def _profile_value(self, field: str, value):
        kind = D.PROFILE_FIELDS[field][0]
        if kind == "text":
            return self._text(value, field)
        if kind == "stage":
            v = str(value or "").strip().lower().replace(" ", "-").replace("_", "-")
            v = {"product-market-fit": "pmf", "pre-seed": "idea"}.get(v, v)
            if v not in D.STAGES:
                raise StoreError(f"stage must be one of: {', '.join(D.STAGES)}")
            return v
        if kind == "allocation":
            from .invest import check_targets
            try:
                return {k: float(v) for k, v in check_targets(value).items()}
            except ValueError as e:
                raise StoreError(f"{field}: {e}") from None
        if kind == "percent":
            try:
                n = float(str(value).rstrip("%").strip())
            except (TypeError, ValueError):
                raise StoreError(f"{field} must be a percent, e.g. 10") from None
            if not 0 < n <= 100:
                raise StoreError(f"{field} must be more than 0 and at most 100")
            return round(n, 2)
        if kind == "symbols":
            items = value if isinstance(value, list) else [x for x in str(value or "").replace(",", " ").split()]
            out = []
            for x in items:
                sym = re.sub(r"\s+", "", str(x)).upper()
                if not re.fullmatch(r"[A-Z0-9.\-/]{1,12}", sym):
                    raise StoreError(f"{field}: {x!r} isn't a ticker symbol")
                if sym not in out:
                    out.append(sym)
            if len(out) > 50:
                raise StoreError(f"{field} takes at most 50 symbols")
            return out
        if kind == "enum":
            v = str(value or "").strip().lower().replace(" ", "-").replace("_", "-")
            allowed = D.FIELD_VALUES.get(field, ())
            if v not in allowed:
                raise StoreError(f"{field} must be one of: {', '.join(allowed)}")
            return v
        if kind == "int":
            try:
                n = int(value)
            except (TypeError, ValueError):
                raise StoreError(f"{field} must be a whole number") from None
            if not 0 <= n <= 100_000:
                raise StoreError(f"{field} must be between 0 and 100000")
            return n
        if kind == "metrics":
            if not isinstance(value, dict) or len(value) > 20:
                raise StoreError("key_metrics must be an object of up to 20 name -> value pairs")
            out = {}
            for k, v in value.items():
                if not isinstance(v, (str, int, float)) or isinstance(v, bool):
                    raise StoreError(f"key_metrics[{k!r}] must be text or a number")
                out[self._text(str(k), "metric name")] = v if not isinstance(v, str) else self._text(v, str(k))
            return out
        if kind == "places":
            if not isinstance(value, dict) or not value or len(value) > 20:
                raise StoreError(f"{field} must be an object of up to 20 what -> where pairs, "
                                 "e.g. {\"pipeline\": \"HubSpot\"}")
            out = {}
            for k, v in value.items():
                if not isinstance(v, str) or not v.strip():
                    raise StoreError(f"{field}[{k!r}] must say where, as text (a tool, a file or a folder)")
                out[self._text(str(k), f"{field} entry")] = self._text(v, str(k))
            return out
        if kind == "tz":
            try:
                ZoneInfo(str(value))
            except (ZoneInfoNotFoundError, ValueError):
                raise StoreError(f"timezone must be an IANA name like Asia/Kolkata, got {value!r}") from None
            return str(value)
        if kind == "weekday":
            v = str(value or "").strip().lower()[:3]
            if v not in D.WEEKDAYS:
                raise StoreError(f"checkin_day must be one of: {', '.join(D.WEEKDAYS)}")
            return v
        raise StoreError(f"unsupported field {field}")

    # ------------------------------------------------------------------ profile
    def _current(self, field: str) -> sqlite3.Row | None:
        with self._lock:
            return (self._currents(field) or [None])[0]

    def _currents(self, field: str) -> list[sqlite3.Row]:
        """The current fact(s) for `field`, newest first: this coach's, and another coach's when the field is shared
        (the reader declares it) and that coach does not keep it to itself."""
        if field in self.owned or "*" in self.owned:
            who = [self.coach]
        else:
            who = self.readers("profile")
        marks = ",".join("?" * len(who))
        return self.db.execute(f"SELECT * FROM profile_facts WHERE founder_id=? AND coach IN ({marks}) AND field=? "
                               "AND superseded_at IS NULL ORDER BY valid_from DESC, id DESC",
                               (self.fid, *who, field)).fetchall()

    def _current_value(self, field: str):
        row = self._current(field)
        return json.loads(row["value"]) if row else None

    def _common_value(self, field: str):
        """A shared fact from the Common profile, when this Pack reads that field; never fails a read."""
        if self.common is None or field not in self.common_fields:
            return None
        try:
            return self.common._current_value(field)
        except sqlite3.Error:
            return None

    def shared_fields(self) -> list[str]:
        """The profile fields whose value comes from the Common profile (not set in this Project)."""
        if self.common is None or not self.common_fields:
            return []
        try:
            mine = set(self._own_profile())
            return [f for f in self.common._own_profile() if f in self.common_fields and f not in mine]
        except sqlite3.Error:
            return []

    def profile(self) -> dict[str, dict]:
        """{field: {value, since, confirmed_at, stale}} for the fields that have a value: this store's own
        facts, then the Common profile's for the shared fields this store doesn't set."""
        out = self._own_profile()
        if self.common is not None and self.common_fields:
            try:
                shared = self.common._own_profile()
            except sqlite3.Error:
                shared = {}
            for f, v in shared.items():
                if f in self.common_fields and f not in out:
                    out[f] = v
        return {f: out[f] for f in D.PROFILE_FIELDS if f in out}

    def _own_profile(self) -> dict[str, dict]:
        out = {}
        cutoff = self.now() - dt.timedelta(days=D.PROFILE_STALE_DAYS)
        with self._lock:
            sql, who = self._in("profile", "SELECT * FROM profile_facts WHERE founder_id=? AND coach=? "
                                           "AND superseded_at IS NULL ORDER BY valid_from, id")
            rows = self.db.execute(sql, (self.fid, *who)).fetchall()
        for r in rows:
            if r["coach"] != self.coach and (r["field"] not in self.fields or r["field"] in self.owned):
                continue                       # another coach's fact is read only for a field this coach declares
            confirmed = dt.datetime.fromisoformat(r["confirmed_at"])
            out[r["field"]] = {"value": json.loads(r["value"]), "since": r["valid_from"],
                               "confirmed_at": r["confirmed_at"],
                               "stale": r["field"] not in D.NEVER_STALE and confirmed < cutoff}
        return out

    def profile_history(self, field: str) -> list[dict]:
        with self._lock:
            sql, who = self._in("profile", "SELECT * FROM profile_facts WHERE founder_id=? AND coach=? AND field=? "
                                           "ORDER BY id")
            rows = self.db.execute(sql, (self.fid, *who, field)).fetchall()
        return [{"value": json.loads(r["value"]), "valid_from": r["valid_from"],
                 "superseded_at": r["superseded_at"]} for r in rows]

    def update_profile(self, changes: dict, request_id: str | None = None,
                       source: str = "coach_update_profile") -> dict:
        return self._transact(request_id, lambda: self._update_profile(changes, source),
                              what=("profile", changes))

    def _update_profile(self, changes: dict, source: str) -> dict:
        if not isinstance(changes, dict) or not changes:
            raise StoreError("changes must be an object of field -> value, e.g. {\"stage\": \"mvp\"}")
        unknown = [f for f in changes if f not in self.fields]
        if unknown:
            raise StoreError(f"unknown profile field(s): {', '.join(unknown)}. Fields: "
                             + "; ".join(f"{f} ({D.PROFILE_FIELDS[f][1]})" for f in self.fields))
        clean = {f: self._profile_value(f, v) for f, v in changes.items()}

        def apply() -> dict:
            now = self._iso()
            updated, confirmed = [], []
            for field, value in clean.items():
                cur = self._current(field)
                if cur is not None and json.loads(cur["value"]) == value and cur["coach"] == self.coach:
                    self.db.execute("UPDATE profile_facts SET confirmed_at=? WHERE id=?", (now, cur["id"]))
                    self._change("profile", field, "confirm", value, value, source)
                    confirmed.append(field)
                    continue
                for old in self._currents(field):         # one current value per field, whoever wrote it
                    self.db.execute("UPDATE profile_facts SET superseded_at=? WHERE id=?", (now, old["id"]))
                self.db.execute("INSERT INTO profile_facts (founder_id, coach, field, value, valid_from, superseded_at, "
                                "confirmed_at, source) VALUES (?,?,?,?,?,NULL,?,?)",
                                (self.fid, self.coach, field, _j(value), now, now, source))
                self._change("profile", field, "update" if cur is not None else "create",
                             json.loads(cur["value"]) if cur is not None else None, value, source)
                updated.append(field)
            return {"updated": updated, "confirmed": confirmed,
                    "profile": {f: v["value"] for f, v in self.profile().items()}}
        return apply()

    def retire_profile(self, fields, source: str, request_id: str | None = None) -> list[str]:
        """End this store's own value of `fields` (kept in history, logged): used when a fact moves to the
        Common profile, so the shared value isn't hidden behind an older local one. Returns the fields ended."""
        want = [f for f in fields if f in D.PROFILE_FIELDS]

        def apply() -> dict:
            now, done = self._iso(), []
            for f in want:
                cur = self._current(f)
                if cur is None:
                    continue
                self.db.execute("UPDATE profile_facts SET superseded_at=? WHERE id=?", (now, cur["id"]))
                self._change("profile", f, "move_to_common", json.loads(cur["value"]), None, source)
                done.append(f)
            return {"retired": done}
        if not want:
            return []
        return self._transact(request_id, apply, what=("retire", want))["retired"]

    # ------------------------------------------------------------------ records
    def record(self, entry: dict, request_id: str | None = None, source: str = "coach_record") -> dict:
        return self._transact(request_id, lambda: self._record(entry, source), what=("record", entry))

    def _record(self, entry: dict, source: str) -> dict:
        kinds = ("goal", "commitments", "decision", "checkin", "note", "person", "issue")
        if not isinstance(entry, dict) or entry.get("kind") not in kinds:
            raise StoreError("entry.kind must be one of: " + ", ".join(kinds))
        kind = entry["kind"]
        reason = self._text(entry.get("reason"), "reason", False)
        actor = self._actor(entry.get("by"))
        if kind == "note":
            self._why = (reason, actor)
            try:
                return self._record_note(entry, source)
            finally:
                self._why = (None, None)
        if kind in ("person", "issue"):
            return self._record_entity(entry, source, reason, actor)
        now_week = self.this_week()
        top_links = self._clean_links(entry.get("links"), "links")
        supersedes = str(entry.get("supersedes") or "").strip() or None
        if supersedes and kind != "decision":
            raise StoreError("`supersedes` on a new record applies to a Decision (a Note takes it as a Note field)")
        if supersedes and not reason:
            raise StoreError("a Decision that supersedes another needs `reason`: why the earlier one no longer holds, "
                             "in the person's words")
        if kind == "goal":
            rows = [{"text": self._text(entry.get("text"), "text"), "measure": self._text(entry.get("measure"), "measure", False),
                     "target_date": self._date(entry.get("target_date"), "target_date"),
                     "citations": self._check_citations(entry.get("citations"))}]
        elif kind == "commitments":
            items = entry.get("items")
            if not isinstance(items, list) or not 1 <= len(items) <= D.MAX_OPEN_COMMITMENTS_PER_WEEK:
                raise StoreError(f"commitments.items must hold 1-{D.MAX_OPEN_COMMITMENTS_PER_WEEK} Commitments")
            week = entry.get("week") or now_week
            week_start(week)
            rows = []
            for i, it in enumerate(items, 1):
                if not isinstance(it, dict):
                    raise StoreError(f"commitment {i} must be an object with action, cue and outcome")
                gid = it.get("goal_id")
                if gid and not self._goal_visible(gid):
                    raise StoreError(f"commitment {i}: no Goal {gid}; ids come from coach_get_context")
                rows.append({"week": week, "action": self._text(it.get("action"), f"commitment {i} action"),
                             "cue": self._text(it.get("cue"), f"commitment {i} cue", False),
                             "outcome": self._text(it.get("outcome"), f"commitment {i} outcome (measurable)"),
                             "goal_id": gid or None, "citations": self._check_citations(it.get("citations")),
                             "_links": self._clean_links(it.get("links"), f"commitment {i} links")})
        elif kind == "decision":
            rows = [{"text": self._text(entry.get("text"), "text"),
                     "reasoning": self._text(entry.get("reasoning"), "reasoning"),
                     "revisit_on": self._date(entry.get("revisit_on"), "revisit_on"),
                     "citations": self._check_citations(entry.get("citations"))}]
        else:
            rows = [{"week": now_week, "summary": self._text(entry.get("summary"), "summary"),
                     "wins": self._list(entry.get("wins"), "wins"), "blockers": self._list(entry.get("blockers"), "blockers")}]

        def apply() -> dict:
            self._why = (reason, actor)
            try:
                return write()
            finally:
                self._why = (None, None)

        def write() -> dict:
            now, ids = self._iso(), []
            old = None
            if supersedes:
                old = self.get(supersedes, links=False)
                if old is None or old["kind"] != "decision":
                    raise StoreError(f"no Decision {supersedes!r} to supersede; ids come from coach_get_context or "
                                     "coach_recall")
                if old.get("status", "accepted") != "accepted":
                    raise StoreError(f"{old['id']} is already {old['status']}"
                                     + (f" (by {old['superseded_by']}): supersede that one instead"
                                        if old.get("superseded_by") else ""))
            for r in rows:
                links = r.pop("_links", None) or top_links
                if kind == "goal":
                    rid = self._new_id("goal")
                    self.db.execute("INSERT INTO goals (id, founder_id, coach, text, measure, target_date, status, "
                                    "citations, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                                    (rid, self.fid, self.coach, r["text"], r["measure"], r["target_date"], "active",
                                     _j(r["citations"]), now))
                    self._change("goal", rid, "create", None, r, source)
                elif kind == "commitments":
                    rid = self._new_id("commitment")
                    self.db.execute("INSERT INTO commitments (id, founder_id, coach, week, action, cue, outcome, goal_id, "
                                    "citations, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                    (rid, self.fid, self.coach, r["week"], r["action"], r["cue"], r["outcome"], r["goal_id"],
                                     _j(r["citations"]), "open", now))
                    self._change("commitment", rid, "create", None, r, source)
                elif kind == "decision":
                    rid = self._new_id("decision")
                    self.db.execute("INSERT INTO decisions (id, founder_id, coach, text, reasoning, citations, decided_at, "
                                    "revisit_on) VALUES (?,?,?,?,?,?,?,?)",
                                    (rid, self.fid, self.coach, r["text"], r["reasoning"], _j(r["citations"]), now, r["revisit_on"]))
                    self._change("decision", rid, "create", None, r, source)
                else:
                    rid = self._new_id("checkin")
                    self.db.execute("INSERT INTO checkins (id, founder_id, coach, week, summary, wins, blockers, created_at) "
                                    "VALUES (?,?,?,?,?,?,?,?)",
                                    (rid, self.fid, self.coach, r["week"], r["summary"], _j(r["wins"]), _j(r["blockers"]), now))
                    self._change("checkin", rid, "create", None, r, source)
                for to, typ in links:
                    self._link(rid, to, typ, now, source)
                ids.append(rid)
            if old is not None:
                self.db.execute("UPDATE decisions SET status='superseded', superseded_by=?, superseded_at=? WHERE id=?",
                                (ids[0], now, old["id"]))
                self._change("decision", old["id"], "supersede", old, self.get(old["id"], links=False), source)
            warnings = self._warnings(week=rows[0].get("week") if kind == "commitments" else None)
            if kind == "checkin":
                left = self.overdue_commitments()
                if left:        # a Check-in reviews each Commitment; the Founder's report may already say how
                    warnings.append(f"{len(left)} Commitment(s) from earlier weeks are still open ("
                                    + ", ".join(f"{c['id']} {c['action'][:60]!r}" for c in left)
                                    + "): set each to done, dropped or carried with coach_update, from what the "
                                    "Founder reported or after asking.")
            return {"ids": ids, "warnings": warnings}
        return apply()


    # ------------------------------------------------------------------ People, Issues, links (ADR-0025)
    def _actor(self, by) -> str | None:
        """Who made a change or decision, only as the person said it: "self" when they said it was them, a Person
        they named, or None when nobody said (the change is still recorded by them, through the coach: that is not
        who decided). Rows written before this rule say "me" for every change, said or not: read as not said."""
        by = str(by or "").strip()
        if not by:
            return None
        if by.lower() in ("me", "self", "i"):
            return "self"
        if D.KIND_OF_PREFIX.get(by.split("-", 1)[0]) != "person" or self.get(by, links=False) is None:
            raise StoreError(f"`by` is \"me\" or the id of a Person in this Project (pe-...), not {by!r}")
        return by

    def _clean_links(self, links, label: str) -> list[tuple[str, str]]:
        if links in (None, []):
            return []
        if not isinstance(links, list) or len(links) > D.MAX_LINKS_PER_RECORD:
            raise StoreError(f"{label} must be a list of up to {D.MAX_LINKS_PER_RECORD} {{to, type}} objects")
        out = []
        for ln in links:
            if not isinstance(ln, dict) or not ln.get("to") or ln.get("type") not in D.LINK_PAIRS:
                raise StoreError(f"each of {label} needs `to` (a record id) and `type`, one of: "
                                 + ", ".join(D.LINK_PAIRS))
            out.append((str(ln["to"]).strip(), ln["type"]))
        return out

    def _kind(self, rid: str) -> str | None:
        return D.KIND_OF_PREFIX.get((rid or "").split("-", 1)[0])

    def _link(self, src: str, dst: str, typ: str, now: str, source: str) -> None:
        """Save one link the person said, checked against the closed vocabulary (domain.LINK_PAIRS). Linking again a
        link that was ended restores it; both are logged."""
        sk, dk = self._kind(src), self._kind(dst)
        allowed = D.LINK_PAIRS.get(typ)
        if allowed is None or sk not in allowed[0] or dk not in allowed[1]:
            ok = ", ".join(f"{t}: {'/'.join(a)} -> {'/'.join(b)}" for t, (a, b) in D.LINK_PAIRS.items()
                           if sk in a)
            raise StoreError(f"a {typ} link can't go from a {sk} to a {dk}"
                             + (f"; from a {sk}: {ok}" if ok else ""))
        if self.get(dst, links=False) is None:
            raise StoreError(f"no record {dst!r} to link to; ids come from coach_get_context, coach_recall or "
                             "coach_graph")
        n = self.db.execute("SELECT COUNT(*) FROM links WHERE founder_id=? AND src=? AND ended_at IS NULL",
                            (self.fid, src)).fetchone()[0]
        row = self.db.execute("SELECT ended_at FROM links WHERE founder_id=? AND src=? AND dst=? AND type=?",
                              (self.fid, src, dst, typ)).fetchone()
        key = f"{src}|{typ}|{dst}"
        if row is None:
            if n >= D.MAX_LINKS_PER_RECORD:
                raise StoreError(f"{src} already has {n} links (at most {D.MAX_LINKS_PER_RECORD}); end one first")
            self.db.execute("INSERT INTO links (founder_id, coach, src, dst, type, created_at) VALUES (?,?,?,?,?,?)",
                            (self.fid, self.coach, src, dst, typ, now))
            self._change("link", key, "create", None, {"src": src, "dst": dst, "type": typ}, source)
        elif row[0] is not None:
            self.db.execute("UPDATE links SET ended_at=NULL WHERE founder_id=? AND src=? AND dst=? AND type=?",
                            (self.fid, src, dst, typ))
            self._change("link", key, "restore", {"ended_at": row[0]}, {"ended_at": None}, source)

    def _end_link(self, src: str, dst: str, typ: str, now: str, source: str) -> None:
        row = self.db.execute("SELECT ended_at, coach FROM links WHERE founder_id=? AND src=? AND dst=? AND type=?",
                              (self.fid, src, dst, typ)).fetchone()
        if row is None or row[0] is not None:
            raise StoreError(f"no {typ} link from {src} to {dst} to end")
        if not self._link_visible(src, row[1]):
            raise StoreError(f"the {typ} link from {src} to {dst} belongs to another coach's private records")
        self.db.execute("UPDATE links SET ended_at=? WHERE founder_id=? AND src=? AND dst=? AND type=?",
                        (now, self.fid, src, dst, typ))
        self._change("link", f"{src}|{typ}|{dst}", "end", {"ended_at": None}, {"ended_at": now}, source)

    def _link_visible(self, src: str, coach: str) -> bool:
        """A link is read by the coach that made it, and by every coach that reads its source's kind when that kind
        is shared (a link between two shared records is part of the Project's shared core, ADR-0019)."""
        if coach == self.coach:
            return True
        table = D.TABLE_OF.get(self._kind(src) or "")
        return table in SHARED_KINDS and coach in self.readers(table)

    def links_of(self, rid: str) -> tuple[list[dict], list[dict]]:
        """(outgoing, incoming) active links of a record this coach may read."""
        out, into = [], []
        for r in self.db.execute("SELECT src, dst, type, coach FROM links WHERE founder_id=? AND (src=? OR dst=?) "
                                 "AND ended_at IS NULL ORDER BY created_at, dst", (self.fid, rid, rid)):
            if not self._link_visible(r["src"], r["coach"]):
                continue
            other = r["dst"] if r["src"] == rid else r["src"]
            if self.get(other, links=False) is None:
                continue
            (out if r["src"] == rid else into).append(
                {"to": r["dst"], "type": r["type"]} if r["src"] == rid else {"from": r["src"], "type": r["type"]})
        return out, into

    def visible_links(self) -> list[dict]:
        """Every active link this coach may read (both ends are checked by whoever draws them)."""
        with self._lock:
            rows = [dict(r) for r in self.db.execute(
                "SELECT src, dst, type, created_at, coach FROM links WHERE founder_id=? AND ended_at IS NULL",
                (self.fid,))]
        return [r for r in rows if self._link_visible(r["src"], r["coach"])]

    def _record_entity(self, entry: dict, source: str, reason: str | None, actor: str) -> dict:
        kind = entry["kind"]
        links = self._clean_links(entry.get("links"), "links")
        if kind == "person":
            name = self._text(entry.get("name"), "name")
            if len(name) > 120:
                raise StoreError("name is longer than 120 characters")
            aliases = [a for a in self._list(entry.get("aliases"), "aliases") if a.lower() != name.lower()]
            row = {"name": name, "aliases": aliases, "role": self._text(entry.get("role"), "role", False)}
        else:
            row = {"text": self._text(entry.get("text"), "text")}

        def apply() -> dict:
            self._why = (reason, actor)
            try:
                now = self._iso()
                if kind == "person":
                    sql, who = self._in("people", "SELECT id, name, aliases FROM people WHERE founder_id=? AND coach=? "
                                                  "AND status='active'")
                    for r in self.db.execute(sql, (self.fid, *who)):
                        names = {r["name"].lower(), *(a.lower() for a in json.loads(r["aliases"] or "[]"))}
                        if name.lower() in names:
                            raise StoreError(f"{r['id']} is already {r['name']!r}: link to it, or add an alias")
                    rid = self._new_id("person")
                    self.db.execute("INSERT INTO people (id, founder_id, coach, name, aliases, role, status, created_at) "
                                    "VALUES (?,?,?,?,?,?,?,?)", (rid, self.fid, self.coach, row["name"],
                                                                 _j(row["aliases"]), row["role"], "active", now))
                else:
                    rid = self._new_id("issue")
                    self.db.execute("INSERT INTO issues (id, founder_id, coach, text, status, created_at) "
                                    "VALUES (?,?,?,?,?,?)", (rid, self.fid, self.coach, row["text"], "open", now))
                self._change(kind, rid, "create", None, row, source)
                for to, typ in links:
                    self._link(rid, to, typ, now, source)
                return {"ids": [rid], "warnings": []}
            finally:
                self._why = (None, None)
        return apply()

    # ------------------------------------------------------------------ Notes (ADR-0020)
    def _note_fields(self, entry: dict) -> dict:
        title = self._text(entry.get("title"), "title")
        if len(title) > D.NOTE_TITLE_MAX:
            raise StoreError(f"title is longer than {D.NOTE_TITLE_MAX} characters; shorten it")
        kind = entry.get("type")
        if kind not in D.NOTE_TYPES:
            raise StoreError(f"type must be one of: {', '.join(D.NOTE_TYPES)}")
        origin = entry.get("origin") or "coach"
        if origin not in D.NOTE_ORIGINS:
            raise StoreError(f"origin must be one of: {', '.join(D.NOTE_ORIGINS)} (user: the person said it; "
                             "coach: the coach concluded it)")
        citations = self._check_citations(entry.get("citations"))
        quotes = entry.get("quotes") or {}
        if not isinstance(quotes, dict) or any(k not in citations for k in quotes):
            raise StoreError("quotes must map a cited item_id to the words that support the Note")
        evidence = []
        for cid in citations:         # what was cited is kept as it was seen: an item id may vanish when the pack is rebuilt
            info = (self.cite_lookup(cid) if self.cite_lookup else None) or {}
            row = {"id": cid, "title": info.get("title"), "deep_link": info.get("deep_link") or None}
            if cid in quotes:
                q = self._text(quotes[cid], f"quote for {cid}")
                row["quote"] = q[:D.NOTE_QUOTE_MAX]
            evidence.append({k: v for k, v in row.items() if v})
        links = entry.get("links") or []
        if not isinstance(links, list) or len(links) > D.MAX_NOTE_LINKS:
            raise StoreError(f"links must be a list of up to {D.MAX_NOTE_LINKS} {{to, type}} objects")
        clean_links = []
        for ln in links:
            if not isinstance(ln, dict) or not ln.get("to"):
                raise StoreError("each link needs `to` (a record id) and `type`")
            if ln.get("type") not in D.LINK_TYPES:
                raise StoreError(f"link type must be one of: {', '.join(D.LINK_TYPES)}")
            clean_links.append((str(ln["to"]).strip(), ln["type"]))
        return {"title": title, "summary": self._long_text(entry.get("summary"), "summary", D.NOTE_SUMMARY_MAX),
                "type": kind, "origin": origin, "citations": citations, "evidence": evidence,
                "revisit_on": self._date(entry.get("revisit_on"), "revisit_on"), "links": clean_links,
                "supersedes": (str(entry["supersedes"]).strip() or None) if entry.get("supersedes") else None}

    def _record_note(self, entry: dict, source: str) -> dict:
        r = self._note_fields(entry)

        def apply() -> dict:
            now = self._iso()
            for to, _ in r["links"]:
                if self.get(to, links=False) is None:
                    raise StoreError(f"no record {to!r} to link to; ids come from coach_get_context or coach_recall")
            old = None
            if r["supersedes"]:
                old = self.get(r["supersedes"], links=False)
                if old is None or old["kind"] != "note":
                    raise StoreError(f"no Note {r['supersedes']!r} to supersede; ids come from coach_get_context "
                                     "or coach_recall")
                if old.get("superseded_by"):
                    raise StoreError(f"{old['id']} was already superseded by {old['superseded_by']}; "
                                     "supersede that one instead")
            rid = self._new_id("note")
            self.db.execute("INSERT INTO notes (id, founder_id, coach, title, summary, type, origin, citations, "
                            "evidence, revisit_on, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (rid, self.fid, self.coach, r["title"], r["summary"], r["type"], r["origin"], _j(r["citations"]),
                             _j(r["evidence"]), r["revisit_on"], now))
            for to, kind in r["links"]:
                self.db.execute("INSERT OR IGNORE INTO links (founder_id, coach, src, dst, type, created_at) "
                                "VALUES (?,?,?,?,?,?)", (self.fid, self.coach, rid, to, kind, now))
            if self.has_fts():
                self.db.execute("INSERT INTO notes_fts (id, title, summary) VALUES (?,?,?)",
                                (rid, r["title"], r["summary"]))
            self._change("note", rid, "create", None, {k: v for k, v in r.items() if k != "supersedes"}, source)
            if old is not None:
                self.db.execute("UPDATE notes SET superseded_by=?, superseded_at=? WHERE id=?", (rid, now, old["id"]))
                self.db.execute("INSERT OR IGNORE INTO links (founder_id, coach, src, dst, type, created_at) "
                                "VALUES (?,?,?,?,?,?)", (self.fid, self.coach, rid, old["id"], "supersedes", now))
                self._change("note", old["id"], "supersede", {"superseded_by": None}, {"superseded_by": rid}, source)
            return {"ids": [rid], "warnings": self._note_warnings(r, old)}
        return apply()

    def _note_warnings(self, r: dict, old: dict | None) -> list[str]:
        out = []
        if r["origin"] == "coach":
            out.append("origin is coach: this Note is the coach's own conclusion, a lead to check, not something the "
                       "person said")
        if old is not None and old.get("revisit_on") and not r["revisit_on"]:
            out.append(f"the superseded Note {old['id']} had a revisit date ({old['revisit_on']}); the new one has "
                       "none: set one with coach_update if it still applies")
        return out

    def notes(self, limit: int = 5, include_superseded: bool = False) -> list[dict]:
        """Newest Notes first, without their summaries (the context digest and indexes list titles)."""
        sql = ("SELECT id, title, type, origin, revisit_on, created_at, superseded_by FROM notes WHERE founder_id=? AND coach=?"
               + ("" if include_superseded else " AND superseded_by IS NULL") + " ORDER BY created_at DESC, id DESC")
        return self._rows(sql + (" LIMIT ?" if limit else ""), *((limit,) if limit else ()))

    def notes_to_revisit(self) -> list[dict]:
        return self._rows("SELECT id, title, revisit_on FROM notes WHERE founder_id=? AND coach=? AND superseded_by IS NULL "
                          "AND revisit_on IS NOT NULL AND revisit_on<=? ORDER BY revisit_on", self.today().isoformat())

    def note_count(self) -> int:
        with self._lock:
            return self.db.execute("SELECT COUNT(*) FROM notes WHERE founder_id=? AND coach=? AND superseded_by IS NULL",
                                   (self.fid, self.coach,)).fetchone()[0]

    def reindex_notes(self) -> int:
        """Rebuild the keyword index from `notes` (it is derived, so this loses nothing); returns the Notes indexed."""
        with self._lock:
            if not self.has_fts() and not self._create_fts():
                return 0
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute("DELETE FROM notes_fts")
                self.db.execute("INSERT INTO notes_fts (id, title, summary) SELECT id, title, summary FROM notes")
                n = self.db.execute("SELECT COUNT(*) FROM notes WHERE founder_id=? AND coach=?",
                                    (self.fid, self.coach)).fetchone()[0]
                self.db.execute("COMMIT")
            except BaseException:
                _rollback(self.db)
                raise
            return n

    # ------------------------------------------------------------------ keyword search over the Project's memory
    _WORD = re.compile(r"[^\W_]{2,}", re.UNICODE)

    def recall(self, query: str | None, kinds: list[str] | None = None, limit: int = 8,
               include_superseded: bool = False, since: str | None = None, until: str | None = None,
               timeline: bool = False) -> list[dict]:
        """The hits of `recall_page`, without the count."""
        return self.recall_page(query, kinds, limit, include_superseded, since, until, timeline)[0]

    def recall_page(self, query: str | None, kinds: list[str] | None = None, limit: int = 8,
                    include_superseded: bool = False, since: str | None = None, until: str | None = None,
                    timeline: bool = False) -> tuple[list[dict], int]:
        """Keyword search over this Project's Notes, Decisions, Goals, Commitments and Check-ins, best first, as
        ([{id, kind, title, snippet, date, score?, week?, status?, superseded_by?}], how many matched). Notes use the FTS5 index
        (bm25); the other kinds are small and are scored by how many of the query's words they contain.

        `since` and `until` (YYYY-MM-DD, both inclusive) keep the records dated in that window: a Note by the day it
        was made, a Decision by the day it was decided, the others by the day they were created. `timeline` lists the
        matches oldest first instead of best first, and then the query may be left out to list everything in the
        window."""
        text = (query or "").strip()
        # a word matches its other forms ("caching" finds "Cache", "benchmarks" finds "benchmark")
        words = list(dict.fromkeys(_stem(w.lower()) for w in self._WORD.findall(text)))[:12]
        if not words and (text or not timeline):
            raise StoreError("query needs at least one word of two or more letters (or timeline: true to list "
                             "records by date)")
        lo, hi = _day(since, "since"), _day(until, "until")
        if lo and hi and lo > hi:
            raise StoreError(f"since ({lo}) is after until ({hi})")
        limit = max(1, min(25, int(limit)))
        want = set(kinds or ("note", "decision", "goal", "commitment", "checkin"))
        out: list[dict] = []
        with self._lock:
            if "note" in want:
                out += self._recall_notes(words, include_superseded)
            for kind, table, cols, title, day in (
                    ("decision", "decisions", ("text", "reasoning"), "text", "decided_at"),
                    ("goal", "goals", ("text", "measure", "note"), "text", "created_at"),
                    ("commitment", "commitments", ("action", "outcome", "result_note"), "action", "created_at"),
                    ("checkin", "checkins", ("summary",), "summary", "created_at")):
                if kind not in want:
                    continue
                # Goals, Commitments and Decisions are the Project's shared core (ADR-0019): read the coaches whose
                # records of that kind this coach may read; Check-ins stay with the coach that ran them
                sql, who = (self._in(table, f"SELECT * FROM {table} WHERE founder_id=? AND coach=?")
                            if table in SHARED_KINDS else (f"SELECT * FROM {table} WHERE founder_id=? AND coach=?",
                                                           [self.coach]))
                for row in self.db.execute(sql, (self.fid, *who)):
                    hay = " ".join(str(row[c] or "") for c in cols).lower()
                    hit = sum(1 for w in words if w in hay) if words else 1
                    if hit:
                        item = {"id": row["id"], "kind": kind, "title": str(row[title])[:120],
                                "snippet": _snippet(hay, words), "date": str(row[day])[:10], "_t": str(row[day])}
                        if words:
                            item["score"] = round(hit / len(words), 3)
                        if "week" in row.keys() and row["week"]:
                            item["week"] = row["week"]
                        if "status" in row.keys() and row["status"]:        # open, done, dropped, carried, accepted ...
                            item["status"] = row["status"]
                        out.append(item)
        out = [r for r in out if (not lo or r["date"] >= lo) and (not hi or r["date"] <= hi)]
        if timeline:
            out.sort(key=lambda r: (r["_t"], r["id"]))                      # oldest first
        else:
            out.sort(key=lambda r: r["date"], reverse=True)          # newest first, then the best match first
            out.sort(key=lambda r: -r["score"])
        page = [{k: v for k, v in r.items() if k != "_t"} for r in out[:limit]]
        for kind in ("decision", "goal", "note"):
            self.mark_edited([r for r in page if r["kind"] == kind], kind)
        if hi:
            self._as_it_read(page, hi)
        return page, len(out)

    _WORDS_OF = {"decision": "text", "goal": "text", "note": "title", "commitment": "action"}

    def _as_it_read(self, page: list[dict], day: str) -> None:
        """A search with `until` asks about a period: each hit that changed after it reads as it did at the end of
        that day (`title`), with what it says now (`now`): the first G9 runs reported a Decision's current words as
        what had been decided weeks earlier."""
        from .graph import end_of_day_utc
        try:
            end = end_of_day_utc(dt.date.fromisoformat(day), self.tz())
        except ValueError:
            return
        for r in page:
            field = self._WORDS_OF.get(r["kind"])
            if not field:
                continue
            with self._lock:
                row = self.db.execute(
                    "SELECT before FROM changes WHERE entity=? AND entity_id=? AND at>? AND op IN ('update','status',"
                    "'supersede') ORDER BY seq LIMIT 1", (r["kind"], r["id"], end)).fetchone()
            if not row or not row[0]:
                continue
            then = json.loads(row[0]).get(field)
            if then and str(then)[:120] != r["title"]:
                r["now"], r["title"] = r["title"], str(then)[:120]
                r["as_of"] = f"as it read on {day}; `now` is what it says today"

    def _recall_notes(self, words: list[str], include_superseded: bool) -> list[dict]:
        sup = "" if include_superseded else " AND n.superseded_by IS NULL"
        rows: list[sqlite3.Row] = []
        if not words:                                              # a timeline with no query: every Note
            rows = self.db.execute(f"SELECT n.*, 0.0 AS rank FROM notes n WHERE n.founder_id=? AND n.coach=?{sup}",
                                   (self.fid, self.coach)).fetchall()
        elif self.has_fts():
            match = " OR ".join(f"{w}*" for w in words)
            try:
                rows = self.db.execute(
                    "SELECT n.*, bm25(notes_fts, 0.0, 4.0, 1.0) AS rank FROM notes_fts JOIN notes n ON n.id=notes_fts.id "
                    f"WHERE notes_fts MATCH ? AND n.founder_id=? AND n.coach=?{sup}", (match, self.fid, self.coach)).fetchall()
            except sqlite3.OperationalError:
                rows = []
        else:
            rows = [r for r in self.db.execute(f"SELECT n.*, 0.0 AS rank FROM notes n WHERE n.founder_id=? AND n.coach=?{sup}",
                                               (self.fid, self.coach,))
                    if any(w in (r["title"] + " " + r["summary"]).lower() for w in words)]
        out = []
        for r in rows:
            hay = (r["title"] + " " + r["summary"]).lower()
            hit = sum(1 for w in words if w in hay)
            item = {"id": r["id"], "kind": "note", "title": r["title"], "snippet": _snippet(hay, words),
                    "date": r["created_at"][:10], "_t": r["created_at"], "type": r["type"], "origin": r["origin"]}
            if words:
                item["score"] = round(max(hit, 1) / len(words), 3)
            if r["superseded_by"]:
                item["superseded_by"] = r["superseded_by"]
            out.append(item)
        return out

    # ------------------------------------------------------------------ Feedback
    def feedback(self, entry: dict, request_id: str | None = None, context: dict | None = None,
                 source: str = "coach_feedback") -> dict:
        """Save one Feedback record (CONTEXT.md). `context` is what the runtime knows about itself
        (product, version, pack) so an eval case can be rebuilt against the same knowledge."""
        return self._transact(request_id, lambda: self._feedback(entry, context or {}, source),
                              what=("feedback", entry))

    @staticmethod
    def _long_text(value, name: str, limit: int, required: bool = True) -> str | None:
        """Text kept as written (line breaks and all): an answer is evidence, not a label."""
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                raise StoreError(f"{name} is required")
            return None
        if not isinstance(value, str):
            raise StoreError(f"{name} must be text")
        value = value.strip()
        if len(value) > limit:
            raise StoreError(f"{name} is longer than {limit} characters; keep the part the Feedback is about")
        return value

    def _feedback(self, entry: dict, context: dict, source: str) -> dict:
        if not isinstance(entry, dict):
            raise StoreError("feedback must be an object")
        cat = entry.get("category")
        if cat not in D.FEEDBACK_CATEGORIES:
            raise StoreError(f"category must be one of {', '.join(D.FEEDBACK_CATEGORIES)}")

        def strings(value, name: str, most: int, each: int) -> list[str]:
            if value in (None, ""):
                return []
            if not isinstance(value, list) or len(value) > most:
                raise StoreError(f"{name} must be a list of up to {most} texts")
            return list(dict.fromkeys(str(v).strip()[:each] for v in value if str(v).strip()))

        row = {"category": cat,
               "question": self._long_text(entry.get("question"), "question", D.FEEDBACK_QUESTION_MAX),
               "answer": self._long_text(entry.get("answer"), "answer", D.FEEDBACK_ANSWER_MAX),
               "cited": strings(entry.get("cited"), "cited", 50, 200),
               "searches": strings(entry.get("searches"), "searches", 20, 500),
               "note": self._long_text(entry.get("note"), "note", D.TEXT_MAX * 2, required=False),
               "expected": self._long_text(entry.get("expected"), "expected", D.TEXT_MAX * 2, required=False)}

        def apply() -> dict:
            rid, now = self._new_id("feedback"), self._iso()
            self.db.execute("INSERT INTO feedback (id, founder_id, coach, created_at, category, question, answer, "
                            "cited, searches, note, expected, context) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (rid, self.fid, self.coach, now, row["category"], row["question"], row["answer"], _j(row["cited"]),
                             _j(row["searches"]), row["note"], row["expected"], _j(context)))
            self._change("feedback", rid, "create", None, {"category": cat}, source)
            return {"id": rid, "saved_at": now, "category": cat}
        return apply()

    def feedback_list(self) -> list[dict]:
        rows = self._rows("SELECT * FROM feedback WHERE founder_id=? AND coach=? ORDER BY created_at, id")
        for r in rows:
            for k in ("cited", "searches", "context"):
                if isinstance(r.get(k), str):
                    try:
                        r[k] = json.loads(r[k])
                    except ValueError:
                        pass
        return rows

    def export_feedback(self, out_dir: Path | None = None) -> dict:
        """All Feedback as one JSONL file to send to the maintainers (nothing else from the store)."""
        rows = self.feedback_list()
        out_dir = Path(out_dir) if out_dir else self.home / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"feedback-{self.now().strftime('%Y%m%dT%H%M%SZ')}.jsonl"
        _atomic(path, "".join(json.dumps({**r, "product": product.ID}, ensure_ascii=False) + "\n" for r in rows))
        return {"path": path, "count": len(rows)}

    # ------------------------------------------------------------------ usage log
    def log_usage(self, tool: str, outcome: str, duration_ms: int, run: str, version: str | None = None,
                  detail: dict | None = None, coach: str | None = None) -> bool:
        """Append one usage event (docs/usage-log.md). Best effort by design: never raises, never
        waits more than USAGE_BUSY_MS for a busy store, adds no change-log row and no FOUNDER.md
        rewrite. `coach` stamps the row for a store that is no coach's own (the Common profile, which keeps the
        calls a coach made before a Project was chosen: ADR-0026). Returns whether the row was written."""
        try:
            with self._lock:
                self.db.execute(f"PRAGMA busy_timeout={USAGE_BUSY_MS}")
                try:
                    self.db.execute("INSERT INTO usage (founder_id, coach, at, run, tool, outcome, duration_ms, version, "
                                    "detail) VALUES (?,?,?,?,?,?,?,?,?)",
                                    (self.fid, coach or self.coach, self._iso(), str(run)[:40], str(tool)[:60],
                                     outcome if outcome in USAGE_OUTCOMES else "error", max(0, int(duration_ms)),
                                     version, _j(detail or {})))
                finally:
                    self.db.execute("PRAGMA busy_timeout=5000")
            return True
        except Exception as e:                     # noqa: BLE001 -- telemetry must never cost a tool call
            import logging
            logging.getLogger("founder_coach").debug("usage event not logged: %s", e)
            return False

    def prune_usage(self, days: int, coach: str | None = None) -> int:
        """Delete usage events older than `days` days (`coach`: another coach's rows in a shared store, such as the
        Common profile); returns how many."""
        cutoff = (self.now() - dt.timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock:
            n = self.db.execute("DELETE FROM usage WHERE founder_id=? AND coach=? AND at < ?",
                                (self.fid, coach or self.coach, cutoff)).rowcount
        return n

    def blank_usage_ids(self) -> int:
        """After a forget, every coach's usage rows keep their counts, but the id of a record no longer in the store
        becomes FORGOTTEN (ADR-0026): a row never points at what was forgotten. Returns how many rows changed."""
        live: set[str] = set()
        with self._lock:
            for table in sorted(set(D.TABLE_OF.values())):
                live |= {r[0] for r in self.db.execute(f"SELECT id FROM {table}")}
            rows = self.db.execute("SELECT id, detail FROM usage").fetchall()
            gone = lambda v: isinstance(v, str) and bool(RECORD_ID.match(v)) and v not in live   # noqa: E731
            n = 0
            for uid, raw in rows:
                try:
                    d = json.loads(raw or "{}")
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                before = json.dumps(d, sort_keys=True)
                for k in USAGE_ID_KEYS:
                    if gone(d.get(k)):
                        d[k] = FORGOTTEN
                for k in USAGE_ID_LISTS:
                    if isinstance(d.get(k), list):
                        d[k] = [FORGOTTEN if gone(v) else v for v in d[k]]
                if json.dumps(d, sort_keys=True) != before:
                    self.db.execute("UPDATE usage SET detail=? WHERE id=?", (_j(d), uid))
                    n += 1
        return n

    def usage_rows(self, days: int | None = None) -> list[dict]:
        sql, args = "SELECT * FROM usage WHERE founder_id=? AND coach=?", [self.fid, self.coach]
        if days is not None:
            sql += " AND at >= ?"
            args.append((self.now() - dt.timedelta(days=days)).isoformat(timespec="seconds"))
        with self._lock:
            rows = [dict(r) for r in self.db.execute(sql + " ORDER BY at, id", args)]
        for r in rows:
            r.pop("founder_id", None)
            try:
                r["detail"] = json.loads(r["detail"] or "{}")
            except ValueError:
                r["detail"] = {}
        return rows

    def usage_summary(self, days: int = 30) -> dict:
        """Per tool: calls, errors, empty results, Gaps, keyword-mode searches, p50/p95 duration; and the newest
        errors with their (already redacted) messages."""
        rows = self.usage_rows(days)

        def pct(xs: list[int], q: float) -> int | None:
            if not xs:
                return None
            xs = sorted(xs)
            return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]
        tools: dict[str, dict] = {}
        for r in rows:
            t = tools.setdefault(r["tool"], {"calls": 0, "errors": 0, "empty": 0, "gaps": 0, "keyword": 0, "_ms": []})
            t["calls"] += 1
            t["errors"] += r["outcome"] == "error"
            t["empty"] += r["outcome"] == "empty"
            t["gaps"] += r["outcome"] == "gap"
            t["keyword"] += r["detail"].get("mode") == "keyword"
            t["_ms"].append(r["duration_ms"])
        for t in tools.values():
            ms = t.pop("_ms")
            t["p50_ms"], t["p95_ms"] = pct(ms, 0.5), pct(ms, 0.95)
        errors = [{"at": r["at"][:19], "tool": r["tool"], "error": str(r["detail"].get("error") or "")}
                  for r in reversed(rows) if r["outcome"] == "error"]
        return {"days": days, "calls": len(rows), "runs": len({r["run"] for r in rows}),
                "first": rows[0]["at"] if rows else None, "last": rows[-1]["at"] if rows else None,
                "tools": dict(sorted(tools.items(), key=lambda kv: -kv[1]["calls"])),
                "recent_errors": errors[:RECENT_ERRORS]}

    def export_usage(self, out_dir: Path | None = None) -> dict:
        """The usage log as one JSONL file to send to the maintainers (nothing else from the store)."""
        rows = self.usage_rows()
        out_dir = Path(out_dir) if out_dir else self.home / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"usage-{self.now().strftime('%Y%m%dT%H%M%SZ')}.jsonl"
        _atomic(path, "".join(json.dumps({**r, "product": product.ID}, ensure_ascii=False) + "\n" for r in rows))
        return {"path": path, "count": len(rows)}

    def clear_usage(self, coach: str | None = None) -> int:
        with self._lock:
            return self.db.execute("DELETE FROM usage WHERE founder_id=? AND coach=?",
                                   (self.fid, coach or self.coach)).rowcount

    def _goal_visible(self, gid: str) -> bool:
        sql, who = self._in("goals", "SELECT 1 FROM goals WHERE id=? AND founder_id=? AND coach=?")
        return bool(self.db.execute(sql, (gid, self.fid, *who)).fetchone())

    def _warnings(self, week: str | None = None) -> list[str]:
        out = []
        week = week or self.this_week()
        weeks = self.loop_weeks()
        sql, who = self._in("commitments", "SELECT COUNT(*) FROM commitments WHERE founder_id=? AND coach=? AND week>=? "
                                           "AND week<=? AND status='open'")
        n = self.db.execute(sql, (self.fid, *who, shift_week(week, 1 - weeks), week)).fetchone()[0]
        if n > D.MAX_OPEN_COMMITMENTS_PER_WEEK:
            out.append(f"{n} open Commitments in "
                       + (week if weeks == 1 else f"the {weeks}-week period ending {week}")
                       + f"; Focus works best with at most "
                       f"{D.MAX_OPEN_COMMITMENTS_PER_WEEK}. Ask the Founder which to drop or carry.")
        sql, who = self._in("goals", "SELECT COUNT(*) FROM goals WHERE founder_id=? AND coach=? AND status='active'")
        g = self.db.execute(sql, (self.fid, *who)).fetchone()[0]
        if g > D.MAX_ACTIVE_GOALS:
            out.append(f"{g} active Goals; suggest the Founder keeps at most {D.MAX_ACTIVE_GOALS}.")
        return out

    def get(self, rid: str, links: bool = True) -> dict | None:
        kind = D.KIND_OF_PREFIX.get((rid or "").split("-", 1)[0])
        if not kind:
            return None
        table = D.TABLE_OF[kind]
        with self._lock:
            sql, who = self._in(table, f"SELECT * FROM {table} WHERE id=? AND founder_id=? AND coach=?")
            row = self.db.execute(sql, (rid, self.fid, *who)).fetchone()
            if row is None:
                return None
            out = {"kind": kind, **_row(row, self.coach)}
            if links and kind != "proposal":
                out["links"], out["linked_from"] = self.links_of(rid)
        if links and kind in ("decision", "goal", "note", "person", "issue"):      # a read, never a change-log copy
            self.mark_edited([out], kind)
        if links and kind == "decision":                  # who decided, as recorded: a decided_by tie, or no one
            names = []
            for x in out.get("links") or []:
                if x.get("type") == "decided_by":
                    p = self.get(x["to"], links=False) or {}
                    names.append(str(p.get("name") or x["to"]))
            out["decided_by"] = ", ".join(names) if names else "not recorded (saving it isn't deciding it)"
        return out

    def update(self, rid: str, status: str | None = None, changes: dict | None = None, note: str | None = None,
               request_id: str | None = None, source: str = "coach_update", reason: str | None = None,
               by: str | None = None, links: list | None = None) -> dict:
        # read, check and write in one BEGIN IMMEDIATE: two hosts carrying the same Commitment
        # can't both see it "open" and make two copies
        return self._transact(request_id, lambda: self._update(rid, status, changes, note, source, reason, by, links),
                              what=("update", rid, status, changes, note, reason, by, links))

    def _update(self, rid: str, status: str | None, changes: dict | None, note: str | None, source: str,
                reason: str | None = None, by: str | None = None, links: list | None = None) -> dict:
        reason = self._text(reason, "reason", False)
        actor = self._actor(by)
        if self._kind(rid) == "proposal":
            from . import proposals
            self._why = (reason, actor)
            try:
                return proposals.decide(self, rid, status, source)
            finally:
                self._why = (None, None)
        rec = self.get(rid, links=False)
        if rec is None:
            raise StoreError(f"no record {rid!r}; ids come from coach_get_context or coach_record")
        kind = rec["kind"]
        # a write meant for the live copy, aimed at the copy it was carried from (ADR-0025): refused with the live id.
        # A call that is wrong anyway (an unknown status, a field nobody may change) gets that error first.
        if kind == "commitment" and rec["status"] == "carried" and status != "open" \
                and (status is None or status in D.STATUSES[kind]) \
                and all(k in D.EDITABLE[kind] for k in (changes or {})) and not (reason and status is None):
            raise StoreError(self._carried_copy_error(rec, status))
        changes = dict(changes or {})
        link_ops = []
        for ln in links or []:
            if not isinstance(ln, dict) or not ln.get("to") or ln.get("type") not in D.LINK_PAIRS \
                    or ln.get("action", "add") not in ("add", "end"):
                raise StoreError("each link needs `to`, `type` (one of: " + ", ".join(D.LINK_PAIRS)
                                 + ") and `action` (add or end)")
            link_ops.append((str(ln["to"]).strip(), ln["type"], ln.get("action", "add")))
        if status is not None:
            allowed = D.STATUSES.get(kind)
            if not allowed:
                raise StoreError(f"a {kind} has no status; change its fields instead")
            if status not in allowed:
                raise StoreError(f"a {kind}'s status is one of: {', '.join(allowed)}")
            if kind == "decision" and status == "superseded":
                raise StoreError("a Decision is superseded by the newer one: record the new Decision with "
                                 f"`supersedes: {rid}` and `reason`")
            if status in D.NEEDS_REASON and not reason and not (note and kind in ("goal", "commitment", "issue")):
                raise StoreError(f"changing a {kind} to {status} needs `reason`: why, in the person's words "
                                 "(nothing about a change is lost)")
            if kind == "person" and status == "merged" and not changes.get("merged_into"):
                raise StoreError("merging a Person needs changes.merged_into: the Person it is the same as")
        if kind == "decision" and any(k in changes for k in D.DECISION_WORDS) and not reason:
            raise StoreError("correcting a Decision's words needs `reason` (why the correction); a change of mind is "
                             "a new Decision with `supersedes`")
        bad = [k for k in changes if k not in D.EDITABLE[kind]]
        if bad:
            raise StoreError(f"can't change {', '.join(bad)} on a {kind}; editable: {', '.join(D.EDITABLE[kind])}")
        if note is not None:
            if kind not in ("goal", "commitment", "issue"):
                more = (f", or save the thinking around it as a Note (coach_record kind note, linked to {rid})"
                        if product.has("notes") and kind in ("decision", "checkin") else "")
                raise StoreError(f"`note` applies to Goals and Commitments; a {kind} has no note: change "
                                 f"{', '.join(D.EDITABLE[kind])} with `changes`{more}")
            changes["result_note" if kind == "commitment" else "note"] = note
        clean = {}
        for k, v in changes.items():
            if k in ("target_date", "revisit_on"):
                clean[k] = self._date(v, k)
            elif k in ("wins", "blockers"):
                clean[k] = _j(self._list(v, k))
            elif k == "goal_id":
                if v and not self.db.execute("SELECT 1 FROM goals WHERE id=?", (v,)).fetchone():
                    raise StoreError(f"no Goal {v}")
                clean[k] = v or None
            elif k == "aliases":
                clean[k] = _j(self._list(v, k))
            elif k == "merged_into":
                other = self.get(str(v or ""), links=False)
                if other is None or other["kind"] != "person" or other["id"] == rid:
                    raise StoreError(f"merged_into must be another Person of this Project, not {v!r}")
                clean[k] = other["id"]
            else:
                clean[k] = self._text(v, k, required=k in ("text", "action", "outcome", "reasoning", "summary"))
        if status is None and not clean and not link_ops:
            raise StoreError("nothing to change: pass a status, changes, a note or links")
        if status == "carried" and rec["status"] != "open":
            raise StoreError(f"only an open Commitment can be carried; {rid} is {rec['status']}")
        table = D.TABLE_OF[kind]

        def apply() -> dict:
            self._why = (reason, actor)
            try:
                return write()
            finally:
                self._why = (None, None)

        def write() -> dict:
            now = self._iso()
            sets = dict(clean)
            if status is not None:
                sets["status"] = status
                if kind != "decision":
                    sets["closed_at"] = now if status in D.TERMINAL else None
            if sets:
                self.db.execute(f"UPDATE {table} SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                                (*sets.values(), rid))
                after = self.get(rid, links=False)
                self._change(kind, rid, "status" if status is not None else "update", rec, after, source)
            for to, typ, action in link_ops:
                if action == "add":
                    self._link(rid, to, typ, now, source)
                else:
                    self._end_link(rid, to, typ, now, source)
            after = self.get(rid, links=False)
            out = {"id": rid, "before": rec, "after": after}
            if status == "carried":
                week = max(self.this_week(), shift_week(rec["week"], self.loop_weeks()))
                new = self._new_id("commitment")
                self.db.execute("INSERT INTO commitments (id, founder_id, coach, week, action, cue, outcome, goal_id, "
                                "citations, status, carried_from, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                (new, self.fid, self.coach, week, rec["action"], rec["cue"], rec["outcome"], rec["goal_id"],
                                 _j(rec["citations"]), "open", rid, now))
                self._change("commitment", new, "create", None, {"carried_from": rid, "week": week}, source)
                out.update(new_id=new, carried_periods=self._carry_streak(new))
            out["warnings"] = self._warnings(week=rec.get("week"))
            return out
        return apply()

    def _live_copy(self, rid: str) -> dict | None:
        """The live copy of a carried Commitment: follow the carries to the copy that was not carried on. A copy
        dropped when its carry was undone is passed over for the copy made by the carry that stands."""
        cur, seen = self.get(rid, links=False), {rid}
        while cur is not None and cur["status"] == "carried":
            kids = self.db.execute("SELECT id, status FROM commitments WHERE carried_from=? "
                                   "ORDER BY created_at DESC, rowid DESC", (cur["id"],)).fetchall()
            pick = next((k for k in kids if k[1] != "dropped"), kids[0] if kids else None)
            if pick is None or pick[0] in seen:
                break
            seen.add(pick[0])
            cur = self.get(pick[0], links=False)
        return cur

    def _carried_copy_error(self, rec: dict, status: str | None) -> str:
        """Why a write to a carried copy is refused, naming the live copy so the next call goes there (ADR-0025)."""
        rid = rec["id"]
        live = self._live_copy(rid)
        if live is None or live["id"] == rid:
            return (f"{rid} is carried and no copy of it was found; read it with coach_recall (id {rid}) "
                    "before changing it")
        when = f" on {_day_month(live['created_at'])}" if live.get("created_at") else ""
        where = f"{live['id']} ({live['week']}, {live['status']})"
        if status == "carried":
            return (f"only an open Commitment can be carried; {rid} is carried: it was carried to {where}{when}, "
                    f"the live copy: carry or update {live['id']} instead")
        out = (f"{rid} was carried to {where}{when}, the live copy: make this change on {live['id']}. ")
        if status is not None:
            return out + (f"A carried copy keeps the status carried; to undo the carry, set {rid} back to open "
                          f"and drop {live['id']}.")
        return out + (f"Only to correct what {rid} said for its own period ({rec['week']}), pass `reason` "
                      "(why the correction).")

    def _carry_streak(self, rid: str) -> int:
        n, cur = 0, rid
        while True:
            with self._lock:
                row = self.db.execute("SELECT carried_from FROM commitments WHERE id=?", (cur,)).fetchone()
            if not row or not row[0]:
                return n
            n, cur = n + 1, row[0]

    def _first_week(self, rid: str) -> str | None:
        """The week the first row of a carry chain was planned in."""
        cur, week, seen = rid, None, set()
        while cur and cur not in seen:
            seen.add(cur)
            with self._lock:
                row = self.db.execute("SELECT carried_from, week FROM commitments WHERE id=?", (cur,)).fetchone()
            if not row:
                break
            week, cur = row[1] or week, row[0]
        return week

    _EDIT_OPS = ("update", "supersede", "status")

    def mark_edited(self, rows: list[dict], entity: str) -> list[dict]:
        """Say on each record that changed after it was made when it last changed and how many times, and where the
        before, the why and the who are (coach_graph history): a read shows a record only as it reads now, so an
        answer about what it said earlier, or why it changed, needs its history (ADR-0025)."""
        ids = [r["id"] for r in rows if r.get("id")]
        if not ids:
            return rows
        with self._lock:
            got = {r[0]: (r[1], r[2]) for r in self.db.execute(
                f"SELECT entity_id, COUNT(*), MAX(at) FROM changes WHERE entity=? AND op IN "
                f"({','.join('?' * len(self._EDIT_OPS))}) AND entity_id IN ({','.join('?' * len(ids))}) "
                f"GROUP BY entity_id", (entity, *self._EDIT_OPS, *ids))}
        for r in rows:
            if r.get("id") in got:
                n, at = got[r["id"]]
                r["edited"] = (f"changed {n} time(s) since it was made, last on {str(at)[:10]}: for what it said "
                               f"before or on a date, call coach_graph history (id) yourself before answering; "
                               f"don't offer to")
        return rows

    # ------------------------------------------------------------------ reads
    def readers(self, kind: str) -> list[str]:
        """The coaches whose records of `kind` (goals, commitments, decisions, profile) this coach reads: itself
        first, then every other coach of the Project that doesn't keep that kind to itself. Everything else
        (Notes, Check-ins, holdings, usage ...) is read only by the coach that wrote it (ADR-0019, ADR-0020)."""
        if self.name != "founder" or kind not in SHARED_KINDS or "*" in self.owned or kind in self.owned:
            return [self.coach]
        return [self.coach, *sorted(p for p, o in self._peer_map().items() if "*" not in o and kind not in o
                                    and p != self.coach)]

    def _peer_map(self) -> dict[str, list[str]]:
        """The other coaches on this machine, re-read when one registers or goes (the registry folder changed)."""
        if self.peers_home is not None:
            try:
                mark = (self.peers_home / "installed").stat().st_mtime_ns
            except OSError:
                mark = None
            if mark != self._peers_seen:
                from . import installed
                self.peers, self._peers_seen = installed.peers(self.peers_home), mark
        return self.peers

    def _in(self, kind: str, sql: str) -> tuple[str, list[str]]:
        """`sql` with its first `coach=?` widened to the coaches that may be read for `kind`, and those coaches."""
        who = self.readers(kind)
        return sql.replace("coach=?", f"coach IN ({','.join('?' * len(who))})", 1), who

    def _rows(self, sql: str, *args, shared: str | None = None) -> list[dict]:
        who = [self.coach]
        if shared:
            sql, who = self._in(shared, sql)
        with self._lock:
            return [_row(r, self.coach) for r in self.db.execute(sql, (self.fid, *who, *args)).fetchall()]

    def goals(self, status: str | None = "active") -> list[dict]:
        if status:
            return self._rows("SELECT * FROM goals WHERE founder_id=? AND coach=? AND status=? ORDER BY created_at",
                              status, shared="goals")
        return self._rows("SELECT * FROM goals WHERE founder_id=? AND coach=? ORDER BY created_at", shared="goals")

    def commitments(self, week: str | None = None, status: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM commitments WHERE founder_id=? AND coach=?", []
        if week:
            sql += " AND week=?"
            args.append(week)
        if status:
            sql += " AND status=?"
            args.append(status)
        rows = self._rows(sql + " ORDER BY week, created_at", *args, shared="commitments")
        for r in rows:
            if r.get("carried_from"):
                r["carried_periods"] = self._carry_streak(r["id"])
                r["planned_since"] = (f"{self._first_week(r['id'])}, planned in {r['carried_periods'] + 1} periods "
                                      f"(coach_graph thread lists every one)")
        return rows

    def loop(self) -> dict | None:
        """The recurring Focus and Check-in of this Project (ADR-0022): on or off, how often, the Pack's check-in
        questions. A Pack without [loop] that keeps Commitments and Check-ins runs it always, weekly (the way every
        Project did before); a Pack that keeps neither has none (None)."""
        if not (product.has("commitments") and product.has("checkins")):
            return None
        cfg = product.PACK.get("loop") or {}
        mine = self._current_value("loop")
        on = (mine == "on") if mine in ("on", "off") else cfg.get("default", "on") == "on"
        every = self._current_value("loop_every") or cfg.get("every", "weekly")
        if every not in D.LOOP_WEEKS:
            every = "weekly"
        return {"on": on, "every": every, "weeks": D.LOOP_WEEKS[every], "default": cfg.get("default", "on"),
                "questions": list(cfg.get("questions") or [])}

    def loop_weeks(self) -> int:
        lp = self.loop()
        return lp["weeks"] if lp else 1

    def overdue_commitments(self) -> list[dict]:
        """Open Commitments whose period has ended: a Commitment of week W belongs to the loop period of
        `loop_weeks()` weeks starting at W (one week: any earlier week)."""
        weeks, now = self.loop_weeks(), week_start(self.this_week())
        return [c for c in self.commitments(status="open") if (now - week_start(c["week"])).days // 7 >= weeks]

    def checkins(self, limit: int = 5) -> list[dict]:
        return self._rows("SELECT * FROM checkins WHERE founder_id=? AND coach=? ORDER BY created_at DESC LIMIT ?", limit)

    def decisions(self, limit: int = 5) -> list[dict]:
        return self.mark_edited(self._rows("SELECT * FROM decisions WHERE founder_id=? AND coach=? ORDER BY decided_at "
                                           "DESC LIMIT ?", limit, shared="decisions"), "decision")

    def decisions_to_revisit(self) -> list[dict]:
        return self._rows("SELECT * FROM decisions WHERE founder_id=? AND coach=? AND revisit_on IS NOT NULL AND revisit_on<=? "
                          "ORDER BY revisit_on", self.today().isoformat(), shared="decisions")

    def recent_changes(self, limit: int = 10) -> list[dict]:
        return self._rows("SELECT seq, at, entity, entity_id, op, source FROM changes WHERE founder_id=? AND coach=? "
                          "ORDER BY seq DESC LIMIT ?", limit)

    def created_at(self) -> dt.datetime | None:
        with self._lock:
            row = self.db.execute("SELECT MIN(at) FROM changes WHERE founder_id=? AND coach=?", (self.fid, self.coach,)).fetchone()
        return dt.datetime.fromisoformat(row[0]) if row and row[0] else None

    # ------------------------------------------------------------------ Holdings (the investor Pack)
    def import_holdings(self, snapshots, source: str, request_id: str | None = None) -> dict:
        """Save positions snapshots (founder_coach.invest.read_positions), once each: the same account, date and
        file again is skipped, so a retried or repeated import never doubles a Project's money."""
        snaps = list(snapshots)

        def apply() -> dict:
            now, done, skipped = self._iso(), [], []
            for s in snaps:
                if self.db.execute("SELECT 1 FROM holdings_snapshots WHERE founder_id=? AND coach=? AND account=? AND as_of=? "
                                   "AND sha256=?", (self.fid, self.coach, s.account, s.as_of, s.sha256)).fetchone():
                    skipped.append({"account": s.account, "as_of": s.as_of})
                    continue
                sid = self._new_id("holdings")
                self.db.execute("INSERT INTO holdings_snapshots (id, founder_id, coach, account, as_of, imported_at, "
                                "broker, sha256, source, total_cents) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                (sid, self.fid, self.coach, s.account, s.as_of, now, s.broker, s.sha256, source[:200],
                                 s.total_cents))
                self.db.executemany("INSERT INTO positions VALUES (?,?,?,?,?,?)",
                                    [(sid, p.symbol, (p.description or "")[:200], p.quantity, p.value_cents,
                                      p.csv_class) for p in s.positions])
                self._change("holdings", sid, "import", None, {"account": s.account, "as_of": s.as_of,
                                                                "positions": len(s.positions),
                                                                "total_cents": s.total_cents}, source[:200])
                done.append({"id": sid, "account": s.account, "as_of": s.as_of, "positions": len(s.positions),
                             "total_cents": s.total_cents})
            labels = self.asset_labels()
            unlabelled = sorted({p.symbol for s in snaps for p in s.positions
                                 if not labels.get(p.symbol) and not p.csv_class})
            return {"imported": done, "skipped": skipped, "unlabelled": unlabelled}
        what = ("holdings", [(s.account, s.as_of, s.sha256) for s in snaps])
        return self._transact(request_id, apply, what=what)

    def label_assets(self, labels: dict, request_id: str | None = None, source: str = "coach_holdings") -> dict:
        """The person's asset class for each symbol (their word wins over anything a file said)."""
        from .invest import ASSET_CLASSES
        if not isinstance(labels, dict) or not labels:
            raise StoreError("labels must be an object of symbol -> asset class, e.g. {\"VTI\": \"us_equity\"}")
        clean = {}
        for sym, cls in labels.items():
            s = re.sub(r"\s+", "", str(sym)).upper()
            c = str(cls or "").strip().lower().replace(" ", "_").replace("-", "_")
            if not s or len(s) > 40:
                raise StoreError(f"{sym!r} isn't a symbol")
            if c not in ASSET_CLASSES:
                raise StoreError(f"{sym}: asset class must be one of {', '.join(ASSET_CLASSES)}, got {cls!r}")
            clean[s] = c

        def apply() -> dict:
            now = self._iso()
            for s, c in clean.items():
                before = self.db.execute("SELECT asset_class FROM asset_classes WHERE founder_id=? AND coach=? AND symbol=?",
                                         (self.fid, self.coach, s)).fetchone()
                self.db.execute("INSERT OR REPLACE INTO asset_classes (founder_id, coach, symbol, asset_class, set_at) "
                                "VALUES (?,?,?,?,?)", (self.fid, self.coach, s, c, now))
                self._change("asset_class", s, "update" if before else "create", before[0] if before else None, c,
                             source)
            return {"labelled": clean}
        return self._transact(request_id, apply, what=("labels", clean))

    def asset_labels(self) -> dict[str, str]:
        with self._lock:
            return {r[0]: r[1] for r in self.db.execute(
                "SELECT symbol, asset_class FROM asset_classes WHERE founder_id=? AND coach=?", (self.fid, self.coach,))}

    def holdings(self) -> tuple[list[dict], dict[str, list[dict]]]:
        """Every snapshot (oldest first) and its positions, for founder_coach.invest.review."""
        snaps = self._rows("SELECT * FROM holdings_snapshots WHERE founder_id=? AND coach=? ORDER BY as_of, imported_at")
        pos: dict[str, list[dict]] = {s["id"]: [] for s in snaps}
        with self._lock:
            for r in self.db.execute("SELECT p.* FROM positions p JOIN holdings_snapshots h ON h.id = p.snapshot_id "
                                     "WHERE h.founder_id=? AND h.coach=?", (self.fid, self.coach,)):
                pos[r["snapshot_id"]].append({"symbol": r["symbol"], "description": r["description"],
                                              "value_cents": r["value_cents"], "csv_class": r["csv_class"]})
        return snaps, pos

    def holdings_review(self) -> dict:
        """A review of this Project's latest Holdings against its own Investment Policy Statement (profile)."""
        from .invest import review
        snaps, pos = self.holdings()
        ips = {f: v["value"] for f, v in self._own_profile().items()}
        return review(snaps, pos, self.asset_labels(), ips, self.today())

    # ------------------------------------------------------------------ Founder control
    def export(self, out_dir: Path | None = None) -> dict[str, Path]:
        out_dir = Path(out_dir) if out_dir else self.home / "exports" / self.now().strftime("%Y%m%dT%H%M%SZ")
        out_dir.mkdir(parents=True, exist_ok=True)
        data = {"founder_id": self.fid, "exported_at": self._iso(), "schema_version": SCHEMA_VERSION,
                "profile": self.profile(),
                "profile_history": {f: self.profile_history(f) for f in D.PROFILE_FIELDS},
                "goals": self.goals(None), "commitments": self.commitments(),
                "decisions": self._rows("SELECT * FROM decisions WHERE founder_id=? AND coach=? ORDER BY decided_at"),
                "checkins": self._rows("SELECT * FROM checkins WHERE founder_id=? AND coach=? ORDER BY created_at"),
                "notes": self._rows("SELECT * FROM notes WHERE founder_id=? AND coach=? ORDER BY created_at"),
                "links": self._rows("SELECT * FROM links WHERE founder_id=? AND coach=? ORDER BY created_at"),
                "feedback": self.feedback_list(),
                "holdings": self._rows("SELECT * FROM holdings_snapshots WHERE founder_id=? AND coach=? ORDER BY as_of"),
                "positions": self._rows("SELECT p.* FROM positions p JOIN holdings_snapshots h ON h.id = "
                                        "p.snapshot_id WHERE h.founder_id=? AND h.coach=?"),
                "asset_classes": self.asset_labels(),
                "usage": self.usage_rows(),
                "changes": self._rows("SELECT * FROM changes WHERE founder_id=? AND coach=? ORDER BY seq")}
        j, md = out_dir / "founder-export.json", out_dir / "FOUNDER.md"
        _atomic(j, json.dumps(data, indent=1, ensure_ascii=False))
        _atomic(md, self.markdown())
        return {"json": j, "markdown": md}

    def forget(self, keep_backup: bool = True) -> dict:
        """Delete everything the coach remembers. By default one final backup is kept (and
        reported) so an accidental forget can be undone; keep_backup=False removes backups too."""
        # Emptied in place, not unlinked: a coach server another host has open keeps its
        # connection to this file, so it sees the empty store at once instead of carrying on
        # with (and re-saving) data from a deleted file.
        with self._lock:
            final = self.backup("pre-forget-" + self.now().strftime("%Y%m%dT%H%M%SZ")) if keep_backup else None
            self.db.execute("PRAGMA secure_delete=ON")     # overwrite freed pages, don't just unlink them
            self.db.execute("BEGIN IMMEDIATE")
            try:
                # Only this coach's records: another coach may share the Project's store (ADR-0019). The
                # idempotency cache holds no coach, so it is emptied whole; it only costs a repeated request.
                who = (self.fid, self.coach)
                if self.has_fts():
                    self.db.execute("DELETE FROM notes_fts WHERE id IN (SELECT id FROM notes "
                                    "WHERE founder_id=? AND coach=?)", who)
                self.db.execute("DELETE FROM positions WHERE snapshot_id IN (SELECT id FROM holdings_snapshots "
                                "WHERE founder_id=? AND coach=?)", who)
                for t in (*(t for t in TABLES if t != "positions"), "usage"):
                    self.db.execute(f"DELETE FROM {t} WHERE founder_id=? AND coach=?", who)
                self.db.execute("DELETE FROM requests")
                self.db.execute("COMMIT")
            except BaseException:
                _rollback(self.db)
                raise
            try:                                       # other coaches' rows: counts kept, forgotten ids blanked
                self.blank_usage_ids()
            except sqlite3.Error as e:
                import logging
                logging.getLogger("founder_coach").warning("forget: usage ids not blanked (%s)", e)
            for stmt in ("VACUUM", "PRAGMA wal_checkpoint(TRUNCATE)"):
                try:
                    self.db.execute(stmt)
                except sqlite3.Error as e:              # another app mid-read: the data is deleted anyway
                    import logging
                    logging.getLogger("founder_coach").warning("forget: %s skipped (%s)", stmt, e)
            self.md_path.unlink(missing_ok=True)
            self._write_project_md()                   # what the other coaches left (or the file's end)
            try:
                from . import notes_view, vault
                notes_view.clear_vault(self)
                vault.clear(self)
            except OSError as e:
                import logging
                logging.getLogger("founder_coach").warning("forget: the notes folder was not cleared (%s)", e)
            removed = 0
            if not keep_backup and self.backups.exists():
                for p in self.backups.glob("*"):
                    p.unlink(missing_ok=True)
                    removed += 1
                self.backups.rmdir()
        return {"deleted": str(self.path), "backup": str(final) if final else None, "backups_removed": removed}

    # ------------------------------------------------------------------ FOUNDER.md
    def markdown(self) -> str:
        from .nudges import render_common_markdown, render_markdown
        return render_markdown(self) if self.name == "founder" else render_common_markdown(self)

    def _write_vault(self) -> None:
        """The derived, read-only views beside the store (ADR-0020): the notes/ folder (a Pack that keeps Notes, none
        when there are no Notes) and this coach's slice of the Project vault (what ADR-0019 lets it read)."""
        if self.name != "founder":
            return
        if product.has("notes"):
            try:
                from . import notes_view
                with self._lock:
                    notes_view.sync_vault(self)
            except Exception as e:            # noqa: BLE001 -- a view; never fail a write for it
                import logging
                logging.getLogger("founder_coach").warning("the notes folder was not updated: %s", e)
        try:                                  # the Project vault (ADR-0020 amendment): the slice this coach may read
            from . import vault
            with self._lock:
                vault.sync_slice(self)
        except Exception as e:                # noqa: BLE001 -- a view; never fail a write for it
            import logging
            logging.getLogger("founder_coach").warning("the vault was not updated: %s", e)

    def _write_project_md(self) -> None:
        try:
            from . import project_md
            project_md.sync(self)
        except Exception as e:                # noqa: BLE001 -- a view; never fail a write for it
            import logging
            logging.getLogger("founder_coach").warning("PROJECT.md not updated: %s", e)

    def _write_markdown(self) -> None:
        try:
            with self._lock:                  # one consistent snapshot, written by one thread at a time
                _atomic(self.md_path, self.markdown())
        except Exception as e:                # noqa: BLE001 -- FOUNDER.md is a view; never fail a write for it
            import logging
            logging.getLogger("founder_coach").warning("FOUNDER.md not updated: %s", e)


def _file_key(path: Path) -> tuple[int, int] | None:
    """Which file is at `path` (device, inode): changes when another file is renamed into place."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino


def _day(value: str | None, name: str) -> str | None:
    """A date window's edge as YYYY-MM-DD (None when not given); anything else is refused by name."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return dt.date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError:
        raise StoreError(f"{name} must be a date like 2026-10-01") from None


_SUFFIXES = ("ings", "ing", "ied", "ies", "ed", "es", "s", "e")


def _stem(word: str) -> str:
    """A crude stem for keyword recall: the word without a common English ending, never shorter than 4 letters."""
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            return word[:-len(suf)]
    return word


def _snippet(text: str, words: list[str], width: int = 160) -> str:
    """The stretch of `text` around the first word of the query that it contains."""
    at = min((i for i in (text.find(w) for w in words) if i >= 0), default=0)
    start = max(0, at - width // 4)
    return ("..." if start else "") + " ".join(text[start:start + width].split())


def _row(r: sqlite3.Row, me: str | None = None) -> dict:
    """A row as a record. The coach stamp is shown only on a record another coach made (`me` is the reader)."""
    d = dict(r)
    for k in ("citations", "wins", "blockers", "evidence"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    d.pop("founder_id", None)
    who = d.pop("coach", "")
    if me is not None and who and who != me:
        d["coach"] = who
    return d


def _atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(3)}")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)          # disk full mid-write: no partial temp file left behind


def _rollback(db: sqlite3.Connection) -> None:
    """ROLLBACK that never hides the real error: SQLite may already have rolled back by
    itself (disk full, I/O error), and "no transaction is active" would replace it."""
    try:
        db.execute("ROLLBACK")
    except sqlite3.Error:
        pass


# ---------------------------------------------------------------------- integrity and restore
def _integrity(db: sqlite3.Connection) -> dict:
    try:
        rows = [r[0] for r in db.execute("PRAGMA integrity_check(20)").fetchall()]
    except sqlite3.DatabaseError as e:
        return {"ok": False, "detail": str(e)}
    ok = rows == ["ok"]
    return {"ok": ok, "detail": "ok" if ok else "; ".join(rows)[:500]}


def _ro_uri(path: Path) -> str:
    """Read-only, immutable (no -wal/-shm side files); as_uri() escapes spaces, '?' and '#'."""
    return Path(path).resolve().as_uri() + "?mode=ro&immutable=1"


def _check_file(path: Path) -> dict:
    """Integrity of a store file opened read-only, plus a readable schema version."""
    try:
        db = sqlite3.connect(_ro_uri(path), uri=True)   # no -wal/-shm side files
    except sqlite3.Error as e:
        return {"ok": False, "detail": str(e)}
    try:
        res = _integrity(db)
        if res["ok"]:
            try:
                row = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            except sqlite3.DatabaseError as e:
                return {"ok": False, "detail": f"not a founder store ({e})"}
            if not row:
                return {"ok": False, "detail": "not a founder store (no schema_version)"}
            if int(row[0]) > SCHEMA_VERSION:
                return {"ok": False, "detail": f"schema v{row[0]} is newer than this coach (v{SCHEMA_VERSION})"}
        return res
    finally:
        db.close()


def open_store(home: str | Path | None = None, clock: Callable[[], dt.datetime] | None = None
               ) -> tuple[FounderStore | None, str | None]:
    """The store after its integrity check, or (None, why). Callers that must keep running
    (the MCP server, `status`, the hook) use this instead of FounderStore()."""
    try:
        store = FounderStore(home, clock=clock)
    except StoreError as e:                          # damaged (StoreDamaged) or a newer schema
        return None, str(e)
    except (OSError, sqlite3.Error) as e:
        return None, f"the founder store can't be opened ({e}). Nothing has been deleted."
    chk = store.check()
    if not chk["ok"]:
        path = store.path
        store.close()
        return None, f"the founder store at {path} fails its integrity check ({chk['detail']}). {RESTORE_HINT}"
    return store, None


def _home(home: str | Path | None) -> Path:
    return Path(home).expanduser() if home else D.home()


def list_backups(home: str | Path | None = None) -> list[dict]:
    """Backups in <home>/backups, newest first, each with its integrity result."""
    folder = _home(home) / "backups"
    if not folder.exists():
        return []
    out = []
    for p in sorted(folder.glob("founder-*.db"), key=lambda p: (p.stat().st_mtime, p.name), reverse=True):
        st = p.stat()
        chk = _check_file(p)
        out.append({"path": p, "name": p.name, "label": p.stem[len("founder-"):], "size": st.st_size,
                    "modified": dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc).isoformat(timespec="seconds"),
                    "ok": chk["ok"], "detail": chk["detail"]})
    return out


def restore(home: str | Path | None = None, backup: str | Path | None = None) -> dict:
    """Replace the store with a backup (default: the newest one that passes its check).

    Never deletes: the current founder.db and its -wal/-shm files move to
    <home>/before-restore-<time>/ first. The copy goes through SQLite's backup API into a
    temporary file, is checked, then renamed into place; FOUNDER.md is regenerated."""
    home = _home(home)
    backups = list_backups(home)
    if backup:
        want = Path(backup).expanduser()
        match = [b for b in backups if want.name in (b["name"], f"founder-{want.name}.db") or b["label"] == str(backup)]
        if want.is_file():
            chosen = {"path": want, "name": want.name, **_check_file(want)}
        elif match:
            chosen = match[0]
        else:
            raise StoreError(f"no backup {backup!r} in {home / 'backups'}; `{product.ID} restore --list` shows them")
        if not chosen["ok"]:
            raise StoreError(f"backup {chosen['name']} fails its check ({chosen['detail']}); pick another with --list")
    else:
        good = [b for b in backups if b["ok"]]
        if not good:
            raise StoreError(f"no usable backup in {home / 'backups'}"
                             + (f" ({len(backups)} found, none passes its check)" if backups else "")
                             + "; nothing has been changed")
        chosen = good[0]
    src_path = Path(chosen["path"])
    path = home / "founder.db"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    aside, in_place = None, False
    current_ok = path.exists() and _check_file(path)["ok"]
    if current_ok:
        # Online restore: keep a copy of the current store aside (never delete), then copy the
        # backup INTO the live file with SQLite's backup API. A coach server another host has
        # open keeps its connection and sees the restored data on its next call.
        aside = home / f"before-restore-{stamp}"
        aside.mkdir(parents=True, exist_ok=True)
        live = sqlite3.connect(path, timeout=10.0)
        try:
            keep = sqlite3.connect(aside / "founder.db")
            try:
                live.backup(keep)
            finally:
                keep.close()
            src = sqlite3.connect(_ro_uri(src_path), uri=True)
            try:
                src.backup(live)
            finally:
                src.close()
        finally:
            live.close()
        in_place = True
    else:
        # Damaged (or missing): nothing can have it open usefully. Build the copy beside it,
        # check it, move the damaged files aside and rename the copy in.
        tmp = home / f".founder.db.restore-{os.getpid()}.tmp"
        try:
            src = sqlite3.connect(_ro_uri(src_path), uri=True)
            try:
                dst = sqlite3.connect(tmp)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
            chk = _check_file(tmp)
            if not chk["ok"]:
                raise StoreError(f"the restored copy fails its check ({chk['detail']}); nothing has been changed")
            present = [p for p in (path, path.with_name("founder.db-wal"), path.with_name("founder.db-shm"))
                       if p.exists()]
            if present:
                aside = home / f"before-restore-{stamp}"
                aside.mkdir(parents=True, exist_ok=True)
                for p in present:
                    os.replace(p, aside / p.name)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
    store = FounderStore(home)                       # runs any migration an older backup needs
    try:
        final = store.check()
        store._write_markdown()
        store._write_vault()
        store._write_project_md()
    finally:
        store.close()
    return {"restored_from": str(src_path), "set_aside": str(aside) if aside else None,
            "store": str(path), "check": final["detail"], "in_place": in_place}
