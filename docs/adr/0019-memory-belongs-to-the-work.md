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
  The old folders are left as they were. Store schema version 7 adds the stamp (version 6 is Notes, ADR-0020).
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

## Slice A as built

The layout, the stamp and the move are built; choosing the Project from the work folder, the setup skills and the
G7 rewrite follow. The read rules and `PROJECT.md` are built too (below).

- **Reads:** see "Read rules as built".
- **Generated files:** until `PROJECT.md` replaces them, the founder Pack keeps `FOUNDER.md` and `notes/`; any
  other coach writes `<COACH>.md` and `notes-<coach>/` in the same folder, so coaches never overwrite each other.
- **Forget** deletes the stamped records of the coach that runs it, its usage rows and the idempotency cache. With
  `--no-backup` it also removes every backup in the Project folder, because a backup holds all coaches' memory
  and cannot be scrubbed; the other coaches' records stay in the store.
- **The move** reads `~/.ytbrain/<pack>/projects/<id>/` for every Pack found, oldest first. A Project whose name is
  already taken becomes `Name (pack)`: two Projects are never merged by name. `project.json` records
  `migrated_from` (`<pack>/<id>`), which is how a retry skips a Project that already moved. The marker
  `projects/.migrated-from-packs.json` is written only when every Project moved, so a Project the person deletes
  afterwards stays deleted. The shared `last-project` is taken from this coach's old default, else any coach's.
- **`ytbrain gaps`** reads the shared stores and splits their usage rows by coach stamp; an old-layout store that
  was moved is not counted twice.

## Read rules as built

- **Shared core:** profile facts, Goals, Commitments and Decisions. A coach reads its own records and those of every
  other coach of the Project that is registered on this machine (`~/.ytbrain/installed/`) and does not keep that kind
  to itself. A record from another coach carries `coach` in tool output; one the reader made has none.
- **Kept with the coach that wrote them:** Notes (ADR-0020), Check-ins, holdings, Feedback and usage.
- **`owned` in `pack.toml`:** `["*"]` keeps everything (the investor); a list of modules (`goals`, `commitments`,
  `decisions`, `profile`) or profile fields keeps those. The list is published in the coach's registry entry, so a
  peer's rule is read without opening its Pack. A coach that is not registered, and a pinned folder, have no peers:
  each coach reads only its own records.
- **Profile fields:** another coach's fact is read only for a field the reader declares and does not own, and a
  write supersedes every current value of the field, so there is one current value and both coaches stay in history.
- **Updates** reach a record another coach made (the stamp stays that of its maker); the change log records who.
- **`PROJECT.md`** is written by every coach that keeps anything shareable and never by an isolated one.

## Work folders as built (slice B)

- `project.json` lists `folders` as `{path, remote}`: the absolute path and, for a git checkout, the `origin` URL read
  from `.git/config` without credentials. A folder belongs to one Project; the deepest linked folder that contains the
  work folder decides. A checkout whose remote is linked to exactly one Project at another path is re-linked and the
  coach tells the person (`folder_note`).
- **What the app gives:** only `CLAUDE_PROJECT_DIR`. MCP roots are not read: the tools are synchronous and listing roots
  is a request to the client. If the app gives no folder, the previous rule stands (the only Project is chosen; with
  several the coach asks); that convenience deviates from point 4's "never a fallback to the only Project" and is the
  one place this build is looser than the ADR. A folder the app did give, linked to nothing, has no fallback at all.
- **Hook and command line:** the hook uses the app's folder, never the last Project used, and says when a folder is
  linked to nothing. The command line uses the folder it runs in, then the shared last Project.
- **F4 stays open:** the active Project is per server process. If the app shares one process between conversations
  (`coach_corpus_status` `host.sessions_seen` rising), the active Project needs a per-conversation key.

## Setup text and the Projects check as built (slice C2)

- The setup skills of the founder and coding Packs say the Project is shared by every coach of the work; the
  investor's says its Project is private. The Project skill covers `link`, `unlink` and the folder rules.
- **G7:** `check_projects` goals checks accept `as` (the reading coach), `peers` and `owned`, so sharing inside a
  Project, isolation between Projects and an owned Pack's privacy are graded the same declarative way. The host
  runs one coach per case, so those checks run offline on stores a test builds (`test_g7_grades_sharing...`); a
  two-coach host case needs both coaches installed in the host and is not built.

