---
status: accepted
---
# The vault is rebuilt whole after every save, by any coach

Amends the vault parts of ADR-0020 (Notes, and its vault amendments) and ADR-0024 (the Project graph). Builds on
ADR-0019 (memory belongs to the work) and ADR-0026 (the usage log).

## The problem

- The full vault (the graph page `_meta/graph.html`, the index `_meta/INDEX.md`, every coach's folder) was built only
  by the person's `vault build` command, and the `/vault` skill ran that command through the host's shell. In a hosted
  session the shell runs on a different machine from the coach server and the Project's store, so the skill could not
  build the vault there, and the graph page stayed as old as the last build from a terminal.
- After a save, each coach refreshed only the part of the vault it may read. A whole-Project page written from one
  coach's part would be overwritten by the next coach's save with a different subset, so the graph page and the index
  were left out of that refresh.
- The two paths disagreed. The refresh dated records by the day in the Project's time zone. The full build read the
  database alone, where the time zone is not kept (it is a field shared through the Common profile), and fell back to
  the UTC day: on a real Project it would have renamed 9 Check-in pages and moved 27 Decisions' start dates by a day.

## Decision

- **One build, the whole Project, after every save.** Whichever coach saved rebuilds the full vault, graph page and
  index included, after its transaction has committed. The per-coach partial refresh is removed. On a real Project
  (about 30 Decisions, 34 Commitments, 85 files, 560 KB) a full build takes about 0.1 s.
- **On request, through the server.** `coach_project action="vault"` runs the same build, so the `/vault` skill works
  on every host: the server always runs where the store is. It writes only the Project's own `vault/` and reports the
  folder and file counts, never record text. Choosing another folder (`vault build --out`) stays on the command line.
  The skill keeps `disable-model-invocation`.
- **A consistent snapshot.** The build reads every record in one read transaction on the server's own connection.
  In WAL mode readers don't block writers, so the build never misses a committed save and never holds up another
  coach's.
- **A lock that doesn't wait.** `vault/.lock` stops two coaches writing the vault at once. A coach that finds a build
  running marks the vault as needing another pass and returns; the coach holding the lock builds once more before it
  lets go. A burst of saves costs at most two builds, and no save waits for another coach's build.
- **Delete last.** Every new or changed page is written, each atomically, before any generated page that no longer
  belongs is removed, so a build that fails partway deletes nothing. A file the person made (no generated marker:
  their own canvases, `.obsidian/`) is never touched.
- **One date rule.** Every file name and date in the vault is the day the record is about, in the Project's time zone
  (`graph.local_day`). The first build after this change renames the pages whose day moved, once.
- **Records one coach keeps to itself** are written to that coach's own folder, as the command did before. Building
  files puts nothing into a conversation: ADR-0019 governs what a coach reads, and no skill opens vault files unless
  the person asks.
- **Failure.** A build that fails never fails the save. Every failure is a usage row (`vault`, with the error). Two
  failures in a row, or a vault more than a day behind the newest save, raise a Nudge in the coach's context that names
  the error and the date the vault last updated, with `/vault` as the repair.

## Consequences

- The vault is current after every save, on every host; the graph page no longer needs a terminal.
- Every save does whole-Project work. Revisit when a full build takes about a second: then run it after the save
  returns, coalesced the same way, or update pages incrementally.
- A coach process writes the folders of coaches it may not read. The files are the person's; nothing reaches a
  conversation.
- Pages whose day moved are renamed once; a canvas the person drew that points at an old page name needs relinking.
- The partial-refresh code is removed; `forget` rebuilds the whole vault from what is left.
- Tests: a save by one coach and then another leaves the same bytes; the same store under `TZ=UTC` and a local time
  zone gives the same names and dates; the action builds through the MCP client with no shell; two overlapping saves
  both reach the vault; a failing build keeps the save, logs a row and raises the Nudge only the second time; three
  Check-ins in one week give three pages; the person's own files are untouched; a build that fails before it finishes
  deletes nothing.

## Considered and rejected

- **Keep the partial refresh for pages and rebuild only the graph page and index:** two build paths, which is what
  produced the date mismatch.
- **Rebuild only on request, or at the end of a Check-in:** the graph is out of date between them.
- **Leave records one coach keeps to itself out of automatic builds:** a second build again; the boundary that matters
  is what enters a conversation.
- **Build from a copy of the database, as the command does:** a copy taken while another coach writes can miss that
  write; a read transaction can't.
- **A lock that waits:** one coach's save would wait on another coach's build.
- **No lock, last build wins:** two saves within a second could leave a page missing one of them until the next save.
- **A new `coach_vault` tool:** a new tool for one action that fits the Project tool.
- **Letting the tool write to any folder it is given:** a larger permission than the vault needs.
- **Running the build in the host's shell, or copying the store to where the shell is:** the store stays where it is,
  and the server can already reach it.
