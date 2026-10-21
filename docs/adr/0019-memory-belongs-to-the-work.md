---
status: accepted
---
# Memory belongs to the work, not to the coach

Amends ADR-0016. ADR-0016 kept one plugin per Pack and the Common profile; this ADR replaces its rule that each
Pack keeps its own Projects.

Under ADR-0016 every Pack keeps its own Projects (`~/.ytbrain/<pack>/projects/<id>/`). One piece of work is
therefore split into one Project per coach. For example, a founder decides with the founder coach to ship an MVP
in six weeks with two engineers. The coding coach that later helps build it knows none of that: the work must be
set up again, and decisions made with one coach never reach the other. That defeats the point of a set of coaches.
The person works on something and brings whichever coach fits the moment. Each coach should know what the work is
and record what it helped decide against that work.

## Decision

**A Project is a piece of the person's work**, shared by every coach. Examples are a company, a repository or a
savings goal. It is long-lived: tasks inside it are its Goals and Commitments, never Projects of their own.

```
~/.ytbrain/                         the engine home (YTBRAIN_HOME moves it)
  you.db, YOU.md                    the Common profile (unchanged)
  installed/                        which coaches are on this machine (unchanged)
  projects/<id>/                    one Project, for every coach: its store, PROJECT.md, backups/, exports/
    project.json                    display name, the folders it belongs to, when it was made
  last-project                      the command line's default when the folder says nothing
```

1. **One store per Project, central, never inside the work.** The store is outside the work folder, so a
   repository never holds memory that a commit could publish, and work with no folder (a savings goal) still has
   memory.
2. **Every record says which coach made it.** Profile facts, Goals, Commitments, Decisions, Check-ins, holdings,
   feedback and usage each carry a `coach` stamp. Context shows the stamp, and `PROJECT.md` (generated from the
   store, replacing FOUNDER.md) lists Goals and Decisions with the coach behind each.
3. **The shared core and owned modules.**
   - Every coach reads the Project's shared core: its profile, Goals, Decisions and Commitments.
   - A Pack may declare record kinds and profile fields as **owned** (`pack.toml`). Only Packs that declare a
     module read it.
   - The investor Pack owns all its records and its policy fields. Another coach sees an investing Project's name
     and nothing else, so amounts and holdings never leave their module.
   - A profile field that several Packs declare with the same kind (team size, where the work lives) is one shared
     field.
4. **The work folder chooses the Project.**
   - A Project lists the folders it belongs to. For a repository it records the path and its remote URL, so a
     moved checkout is still recognised and re-linked, with a note saying so.
   - When the host gives the working folder (`CLAUDE_PROJECT_DIR`, MCP roots), the deepest linked folder decides.
   - When the host gives no folder, the coach lists the Projects by name and asks once per conversation.
   - A folder linked to nothing gets no memory: the coach answers from its knowledge and offers to create or link a
     Project. There is never a fallback to the only Project or to the last one used. That fallback is how one
     company's context reached advice about another.
5. **One active Project per conversation, across coaches.** Each coach's server keeps its own active Project. When
   one coach has already chosen a Project in a conversation, the skills tell the host to switch the others to the
   same one before they read or save, so the person is asked once.
6. **Isolation between Projects is unchanged.**
   - Separate files mean no query can join two Projects.
   - A save names the Project it was proposed for, and the server refuses it anywhere else.
   - Another Project is read only when the person's message names it: read-only, summaries only, nothing saved.
   - Export and forget act on one Project. Forget can be narrowed to one coach's records by their stamp.
7. **Unchanged:** the Common profile (shared only on a yes, only for `common_fields`), and a pinned data folder
   (`<PREFIX>HOME`, `--home`), which keeps the single-folder layout with no Projects (tests, the G2–G6 evals).
8. **The command line and the hook.** They use the work folder first. After that, the command line uses one shared
   `last-project`; the hook never guesses and says which Project is needed.

## Considered Options

- **Keep per-coach Projects and add a handoff:** a coach copies chosen facts from another coach's Project on a yes.
  Every pair of coaches needs a mapping, copies drift apart, and the person still sets up each coach.
- **One shared Project and every coach reads everything:** simplest, but holdings and amounts reach coaches that
  have no reason to see them, which breaks a guarantee the investor Pack is built on.
- **Memory inside the work folder** (`.coach/` in a repository): it travels with the work, but a commit can publish
  it, and work without a folder has nowhere to keep it.
- **Choosing the Project from the last one used:** convenient with one Project, wrong as soon as there are two, and
  silent about it.

## Consequences

- **Migration.** Existing per-coach Projects move once into `projects/<id>/`. The steps are the ones used for the
  earlier move: a copy with SQLite's backup API, an integrity check, a backup kept beside it, a marker that makes a
  re-run a no-op, and a lock for processes that start together. Each record takes its old Pack as its coach stamp.
  The old folders are left as they were. Store schema version 6 adds the stamp.
- **Several coach processes write one store.** WAL and the busy timeout already allow this. Request ids keep a
  retried save from being written twice.
- **Versions must match.** An older coach still writes to the old per-coach folder, so every coach of a build is
  updated together. `ytbrain ops` builds them together, and setup warns when the coaches installed on a machine mix
  layouts.
- **What changes for the coaches:**
  - The MCP tools: context shows coach stamps, and `coach_project` can link and unlink folders.
  - The skills: setup adds only the coach's own fields to an existing Project.
  - The golden tool schemas.
  - G7 now covers sharing within a Project across coaches, isolation between Projects, and privacy of owned
    modules, for every Pack.
- **Open fact.** Whether a host runs one coach process per conversation or shares one across conversations is not
  documented. The first build carrying this change reports it. If processes are shared, the active Project needs a
  per-conversation key, and this ADR is revised before Project choice is built.
