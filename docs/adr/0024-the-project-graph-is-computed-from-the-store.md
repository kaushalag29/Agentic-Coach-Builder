---
status: accepted
---
# The Project graph is computed from the store on every read

Builds on ADR-0019 (memory belongs to the work), ADR-0020 (Notes, and its vault amendments) and ADR-0022 (the loop).

## The problem

A real Project after six weeks: 22 Commitment rows that were 11 tasks (each carry wrote a new row), 17 Decisions with no
tie to anything, 34 blockers and 27 wins as text inside 9 Check-ins, one Goal everything hung off. The vault drew that
faithfully: a star around the Goal, duplicate tasks, floating Decisions. And the coach could not answer questions that
follow ties or ask about time ("what is carried three weeks or more", "what did we believe in September", "how is this
Note connected to that Goal"): `coach_recall` matches words, and ADR-0020's "a recursive query answers everything
about this Goal" was never built.

## Decision

- **A graph computed on every read, never stored** (`founder_coach/graph.py`). It is built from the same snapshot the
  vault is written from, so a coach sees exactly what ADR-0019 lets it read: a record it can't read is never a node,
  and no walk, count or path passes through it. SQLite stays the only source of truth (ADR-0020 point 2). No graph
  database: at 10^2 to 10^4 records a breadth-first walk in Python answers in milliseconds.
- **Nodes:** Goals, Decisions, Notes, Check-ins; a **Thread** per Commitment and all its carries (its id is the first
  row's; any row id resolves to it); a **Week** ("2026-W44"), the time spine; a Source per library item a record cites
  (left out of walks unless asked).
- **Edges, a closed vocabulary.** Derived from stored columns, so they claim nothing new: `serves` (Thread -> Goal, the
  goal_id), `decided_in` (Decision -> Week, in the Project's time zone), `reviewed_in` (Thread -> each Week it was
  planned in; Check-in -> its Week), `cites` (record -> Source). Said by the person: a Note's `about`, `supports`,
  `related` and `supersedes`. Nothing is inferred; a tie the graph doesn't show is not there.
- **Time is the change log.** "As of" a day is what the store held at the end of it (transaction time): the first change
  after that point holds the whole record as it was before (`before`), a record created later did not exist yet. Ordered
  by `seq`, never by the clock.
- **One read tool, `coach_graph`:** `around` (what is tied to a record, up to 3 steps), `why` (the shortest path
  between two records, as sentences), `thread`, `history`, `as_of`, `open_loops` (open Threads planned in N periods or
  more). Titles first, at most 20 items with an offset. `coach_recall` finds a record by its words; `coach_graph`
  follows it.
- **Fix found on the way:** `coach_recall` read only its own coach's Goals, Commitments and Decisions; it now reads the
  Project's shared core like every other read (ADR-0019).

## Consequences

- The vault is written from the graph (ADR-0020 amendment 2026-11-09): one page per Thread with its history, typed
  links, a week spine, scaffolding out of the graph view.
- Existing Projects get the derived ties at once (they are facts about saved rows). Ties the person must say (a
  Decision that supersedes another, who owns a task, a blocker that blocks a Goal) come later, from proposals the
  person confirms (next slice: Person and Issue nodes, typed links between any records, a proposals table).
- Ranking by the graph (personalized PageRank from search seeds) waits for the graph benchmark to show it helps.
- Amendment 2026-11-09: the next slice is ADR-0025 (People, Issues, typed links, proposals, decision status, why and
  by whom for every change, `coach_recall expand` behind a measured gain, the canvas and HTML views, gate G9).

## Considered and rejected

- **An embedded graph database** (Kùzu, archived in October 2025; its forks are young; DuckPGQ is research;
  FalkorDBLite runs a server process): a second store to keep in sync, for queries SQLite and a breadth-first walk
  already answer.
- **Letting the model write SQL or Cypher:** the best text-to-SQL systems trail people by about 11 points and
  text-to-Cypher by more, and text stored in memory can carry an injection. Fixed operations with parameters instead.
- **Community summaries (GraphRAG, RAPTOR):** worth it for themes over a large corpus, not for one Project; Threads and
  Weeks are the clusters.
