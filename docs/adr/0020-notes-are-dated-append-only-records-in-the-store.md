---
status: accepted
---
# Notes are dated, append-only records in the store

Extends ADR-0011 (the store keeps a change log and writes only on confirmation) and ADR-0019 (memory belongs to the
work).

Coaching memory held Goals, Commitments, Decisions and Check-ins. The conversations around them (a trade-off weighed,
research done, what an insight rested on) were lost when a conversation ended, so progress could not be traced and an
earlier conclusion could not be recalled. A Decision records a choice; it has no place for the thinking behind it, and
a weekly Check-in is too coarse to carry it.

## Decision

1. **A Note is a record kind.** Fields: title, summary, type (`discussion`, `research`, `insight`), Origin, the
   Citations it rests on, an optional `revisit_on` date, and the date it was made. It lives in the Project's store
   (`notes` table, schema version 6), saved with `coach_record` like any other record.
2. **SQLite is the source of truth; every other view is derived.** The keyword index (`notes_fts`, SQLite FTS5) is
   rebuilt from the Notes (`reindex_notes`) and can be dropped without losing one. FOUNDER.md, the index file and any
   markdown vault are generated from the store and are read-only views, never edited. A SQLite without FTS5 searches
   with LIKE.
3. **Append-only.** A Note's text is never edited; only its `revisit_on` can change. A changed view is a new Note that
   `supersedes` the older one: the older keeps `superseded_by` and `superseded_at`, both stay on record, and the
   default search hides the superseded. Superseding is proposed to the person and saved only on a yes; the coach
   never decides on its own that a Note is out of date. There are no validity windows (`valid_from`/`valid_to`): a
   Note records what was said on a date, not a fact with an interval of truth.
4. **Origin on every Note.** `user` (the person said it) or `coach` (the coach concluded it). A coach-origin Note is
   a lead to check, never a fact about the person, and the write says so in a warning.
5. **Links are rows, not a graph database.** A `links` table holds typed ties (`about`, `supports`, `related`,
   and `supersedes` made only by superseding). A few hundred records need joins, not graph traversal; a recursive
   query answers "everything about this Goal".
6. **Search is keyword first.** `coach_recall` ranks Notes with bm25 over title and summary (title weighted higher)
   and scores the small tables (Decisions, Goals, Commitments, Check-ins) by the share of the query's words they
   contain. No embeddings at this size; the interface lets a semantic ranker slot in behind it when searches start
   missing. `coach_get_context` lists only the newest Note titles.
7. **A Note keeps what it cited.** Each Citation is stored with its title, link and (when given) the supporting
   words, because an item can leave the library when a pack is rebuilt.
8. **Proposed, then confirmed.** The coach proposes a Note and saves it on a yes, with the same rules as the other
   records (the exact text approved, one `request_id`). Nothing is saved from content the person did not say or
   approve.
9. **Privacy.** Notes belong to the Project's store like every record. In a Pack with owned modules (ADR-0019) a
   Note stays in its Pack's module: another coach never reads it. The investor skill keeps account numbers and
   positions out of Notes.

## Considered Options

- **Markdown files as the source of truth** (an LLM-maintained wiki): readable and portable, but the index drifts
  when a model maintains it, a wrong page becomes a prior nothing contradicts, and a second copy must be kept in step
  with the store. A generated view gives the reading benefit without the second source.
- **A graph database or a knowledge-graph memory service:** costly and slow to ingest for a few hundred records; the
  relationships we need are a handful of typed ties.
- **Overwrite a Note in place, or let an LLM decide what to update or drop:** loses what was said and when, and cannot
  be audited. Superseding keeps both.
- **Embeddings from the start:** unnecessary at about a hundred and fifty Notes a year; keyword search with a good
  index is enough, and a semantic ranker can be added behind the same tool.
- **Notes inside the Decision record:** a Decision is a choice, presented as decided. Mixing in discussion would blur
  it and make Decisions harder to find.

## Consequences

- **Migration.** Store schema 6 adds `notes` and `links` (and the FTS index when SQLite has FTS5). Forward-only, with a
  backup first (ADR-0011). ADR-0019's coach stamp moves to schema 7.
- **New tool.** `coach_recall` (read-only) is served by a Pack that keeps the `notes` module; the golden tool schemas
  change. Every shipped Pack keeps `notes`.
- **Export and forget** cover Notes and Links; forget empties the index.
- **Derived views, built with the Notes.** `notes/` beside the store holds `INDEX.md` (a catalogue under 200 lines:
  what to revisit, the newest Notes, one line per quarter, and what the Notes are about, each section capped with a
  pointer to the rest), a sub-index per quarter and one file per Note (frontmatter with its dates, Origin and links,
  the summary, what it cited). The files are regenerated after every write, are read-only for the person (an edit is
  overwritten, a file they add is never touched) and are removed by forget. The index is also the resource
  `founder://notes`. `<coach> notes rebuild` regenerates them and the search index.
- **A report-only lint.** `<coach> notes lint` reports Notes past `revisit_on`, links to records that no longer
  exist, current Notes with the same title, current Notes that link to nothing, the coach's own conclusions that
  stand unconfirmed, and drift between the store and the search index or the notes folder. It changes nothing.
  Contradictions between Decisions are not detected: that takes judgment, and the coach reads the recalled records
  itself.
- **Risk.** A Note is a summary, and a summary of a summary drifts: Origin, the kept quotes and the dates are there so
  a reader can see how far a Note is from what was said.

## Amendment 2026-11-04: recall by date

`coach_recall` takes `since` and `until` (days, inclusive) and `timeline`, which lists matches oldest first and lets the
query be left out. A record's date is when it was made (a Decision: when it was decided); a Note still carries no
validity interval. A markdown vault with `[[wikilinks]]` already opens in Obsidian, which draws the graph; a generated
graph or diagram of Notes, Decisions and Goals is deferred until a person asks for it.
