---
status: accepted
---
# Memory use is measured by record ids, never words

Builds on the usage log (docs/usage-log.md), ADR-0024 (the Project graph) and ADR-0025 (nothing lost).

## The problem

Gate G9 says whether a coach *can* use the Project graph on fixed questions; nothing said whether it *does* on real
ones. Every memory call already left a usage row, but `coach_graph` and `coach_recall` rows said only "ok": not which
operation ran, which records came back, or whether a read that marked a record `edited` (it has history) or `ties`
(it is tied to others) was followed by the graph call it asked for. `ytbrain gaps` read searches only. Calls made
before a Project was chosen were not logged at all, because there was no Project store to log them in.

## Decision

- **What a memory call logs.** `coach_recall`: its mode (search, timeline, one id), hit count and total, the ids of the
  first 10 hits, whether `expand` or a date window was used, the query's length, and the ids it showed marked `edited`,
  `ties` or `planned` (carried work). `coach_get_context`: the marked ids, whether `follow_ties` was given, and whether
  no Project was chosen yet. `coach_graph`: the operation, the record (`id`, `to`) or week, how many items or path steps
  came back. `coach_update`: its target id, status, whether a reason was given, ties added and ended. `coach_record`:
  the kind, the new ids, ties added. A refused call keeps the record id it named (and the operation or status), so a
  refusal says which record it was about.
- **Ids, never words.** Only values shaped like a record id (`g-`, `c-`, `d-`, `k-`, `n-`, `pe-`, `i-`, `p-`) or a week
  are kept; anything else the host passed in their place (words) is dropped. The query text of a recall is kept only
  under the existing opt-in, `<PREFIX>USAGE_TEXT=1`, like a search's (usage-log D10). The rows live in the Project's own
  store, beside the records they name, so an id there reveals nothing the store didn't hold.
- **Follow-through.** A read that showed a record marked `edited` or `ties` is one chance. It is *followed* when a later
  `coach_graph` call of the same session names one of those records (as `id` or `to`), and *loosely followed* when any
  later `coach_graph` call of the session ran. One chance per read, not per marked record: a coach is not asked to trace
  records that had nothing to do with the question. The rate is a lead to read sessions, not a pass or fail.
- **Judged only on enough cases.** `ytbrain gaps` always shows the counts ("6 of 8"). It warns only from 10 chances
  in the window and below 80 % (G9's bar), and lists the reads that were not followed, newest first, by date and id.
- **Calls before a Project is chosen** go to the Common profile's usage log (`you.db`), stamped with the coach that
  made them, when that store exists; they carry no record ids, since there is no Project. `ytbrain gaps` shows them as
  their own block per coach, and `usage clear` for a Project also clears that coach's rows there.
- **Forget.** A coach's `forget` deletes its own usage rows, as before. Other coaches' rows in the same Project keep
  their counts, and every id of a record no longer in the store becomes `forgotten`: a row never points at a forgotten
  record, and last week's "9 of 11" doesn't quietly become "7 of 8".
- **What else the report shows.** Recall, context and graph calls (operations, nothing found, unknown ids), ties added
  and ended, suggestions answered (yes, never, later), writes refused (to an old copy, with the live copy; a field no one
  may change; other), and rows from before these details were logged, counted as not rated.

## Consequences

- No store migration: `usage.detail` is JSON already; the MCP tool schemas are unchanged.
- A forgotten record's follow-through can no longer be matched, so a chance on it counts as not followed; this only
  ever lowers the rate, never inflates it.
- Gate G9 stays answer-graded on fixed questions; follow-through is not part of its pass mark (a usage rate on 6 to 12
  cases is noise).

## Considered and rejected

- **One chance per marked record:** it rewards tracing records unrelated to the question (Goodhart).
- **Any graph call after a marked read counts as followed:** too loose to tell a near miss from a hit; shown beside the
  strict rate instead.
- **Holding pre-Project calls in memory until a Project is chosen:** lost whenever none is chosen, which is when they
  matter most.
- **Deleting rows that name a forgotten record:** totals would shrink silently.
- **Hashing ids:** matching still works, but a person reading the report can't look the record up.
