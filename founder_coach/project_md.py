"""PROJECT.md: the shared core of a Project in one readable file (ADR-0019).

A generated, read-only view in the Project's folder: its name, the folders it belongs to, the profile facts and the
active Goals, recent Decisions and open Commitments that every coach of the Project reads, each with the coach that
made it. It holds nothing a coach keeps to itself (Notes, Check-ins, holdings), and a coach that keeps everything
to itself (the investor) neither writes nor appears in it. Edits are overwritten at the next write.
"""
from __future__ import annotations

import json
from pathlib import Path

FILE = "PROJECT.md"
DECISIONS = 10


def _meta(home: Path) -> dict:
    try:
        data = json.loads((home / "project.json").read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _by(rec: dict, me: str) -> str:
    return f" ({rec.get('coach') or me})"


def render(store) -> str:
    meta = _meta(store.home)
    me = store.coach
    coaches = sorted({me, *(p for p, o in store._peer_map().items() if "*" not in o)})
    lines = [f"# {meta.get('name') or store.home.name}", "",
             "Generated from the Project's memory: a read-only view, rewritten after every change. The coach that made "
             "each record is in brackets.", ""]
    folders = [str(f) for f in (meta.get("folders") or []) if isinstance(f, str)]
    if folders:
        lines += ["Folders: " + ", ".join(folders), ""]
    lines += ["Coaches here: " + ", ".join(coaches), ""]
    prof = store.profile()
    if prof:
        lines += ["## Profile", ""] + [f"- {f}: {v['value']}" for f, v in prof.items()] + [""]
    goals = store.goals()
    lines += ["## Goals", ""] + ([f"- {g['id']}: {g['text']}"
                                  + (f" (by {g['target_date']})" if g.get("target_date") else "")
                                  + _by(g, me) for g in goals] or ["- none yet"]) + [""]
    open_ = [c for c in store.commitments(status="open")]
    if open_:
        lines += ["## Open Commitments", ""] + [f"- {c['id']} ({c['week']}): {c['action']}" + _by(c, me)
                                                for c in open_] + [""]
    decisions = store.decisions(DECISIONS)
    lines += ["## Decisions", ""] + ([f"- {d['id']}: {d['text']}" + _by(d, me) for d in decisions] or ["- none yet"]) + [""]
    return "\n".join(lines).rstrip() + "\n"


def sync(store) -> None:
    """Write PROJECT.md for a Project in the shared folder. A coach that keeps everything private, a pinned folder and
    a store with no records at all write nothing (an emptied Project loses the file)."""
    if store.name != "founder" or store.peers_home is None or "*" in store.owned:
        return
    path = store.home / FILE
    with store._lock:
        anything = any(store.db.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone()
                       for t in ("profile_facts", "goals", "commitments", "decisions"))
        if not anything:
            path.unlink(missing_ok=True)
            return
        from .store import _atomic
        _atomic(path, render(store))
