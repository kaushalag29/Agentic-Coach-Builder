---
status: accepted
---
# People, Issues and typed links are said by the person, and no change is lost

Builds on ADR-0024 (the Project graph), ADR-0019 (memory belongs to the work) and ADR-0020 (Notes).

## The problem

ADR-0024 drew the ties that are facts about saved rows. The ties a person cares about most were still text: who decided
something, who owns a task, what blocks a Goal, which Decision replaced which. On a real Project, four names were
mentioned 10 to 29 times each and 34 blockers sat inside Check-in text, none of them a record. And a correction
overwrote the old words with no reason kept, so "why did this change, and who changed it" had no answer.

## Decision

- **Two shared kinds, created only on a yes.** A **Person** (name, aliases, a role only in the person's own words;
  nothing from a connector, an email or the account) and an **Issue** (a blocker: open or resolved, `resolved_by` the
  Decision or task that cleared it). Both belong to the Project and every coach of it reads them (ADR-0019). Whether a
  record names a person (`mentions`) is derived from its words, never stored.
- **Typed links, a closed vocabulary of 13 types** with the kinds each may join: about, supports, contradicts, related,
  serves, sub_goal_of, changes_scope_of, led_to, assumes, blocks, resolved_by, owned_by, decided_by. At most 12 per
  record. Written by `coach_record` (`links` on any record, kinds `person` and `issue`) and `coach_update` (`links` to add
  or end), only after the person said yes. A link is never deleted: ending it keeps when it ended and why.
- **Decision status.** accepted, superseded, reversed. A change of mind is a new Decision with `supersedes` (the old one
  becomes superseded, with `superseded_by`; the graph's `supersedes` edge is computed from that one column); a correction
  of its words is an in-place update with a reason. `superseded` is never set by hand.
- **Nothing is lost.** Every change in the log keeps its before and after, when, **why** (`reason`) and **by whom**
  (`by`: the person when they said it was them, or a Person record; when nobody said, only who recorded it,
  never taken for who decided). A reason is required to close a record for good (met, dropped, done,
  reversed, resolved, merged) and to correct a Decision's words; a Goal's or task's `note` counts as one. Only `forget`
  deletes. `coach_graph history` and the vault's History table show why and by whom.
- **Proposals, never saved without a yes.** Seven deterministic rules (a Note or Decision naming a Goal, a Decision
  naming an earlier one, a carried task with a blocker, a name said often, a blocker said twice, who decided, a task
  without a Goal) write candidates to a `proposals` table (one row per fingerprint, so a "no" is remembered). Two
  tiers: high (pre-ticked) and review. The coach offers at most 3 in a conversation, folded into a save it is already
  asking about, and at most 5 at a Check-in; the first review of an existing Project goes in batches of 8. Answers:
  yes, never (kept, never asked again), later (asked again in 4 weeks).
- **Ranking by the graph waits for evidence.** `coach_recall expand` adds what is tied to the hits (personalized
  PageRank: a restart of 0.15, a 60-day recency half-life, weeks damped as hubs, superseded records lowered). Off by
  default until the benchmark shows a gain of at least 10 points.
- **Views.** A JSON Canvas per Goal (a column per week, lanes for Decisions, tasks, Issues and People) and
  `vault build --html`: one offline page (Cytoscape.js, vendored, MIT; the page's policy blocks every network request,
  record text is data, never markup).
- **Gate G9.** Questions about a made-up Project on the real host, one per coach (12 founder, 9 coding, 8 investor;
  the investor's Project has no Goals) (carried work, why, who decided, what blocks,
  what we believed on a date, a path, and two that must abstain): at least 80 %, with a private set of your own
  Project's questions in the eval's private overlay.

## Consequences

- Store schema v8 (a migration with a backup first): `changes.reason`/`actor`, Decision `status`/`superseded_by`,
  `links.ended_at`, and the tables `people`, `issues`, `proposals`.
- A coach that tries to close a Goal or reverse a Decision without saying why is refused, with the reason it needs.
- Cross-Project links are out of scope: a graph is one Project's, shared by its coaches.

## Considered and rejected

- **Extracting people and blockers from text automatically:** a name in a sentence is not consent to keep a record
  about someone, and a wrong tie the person never saw is worse than a missing one.
- **Storing `supersedes` both ways:** two facts that can disagree; one column and a computed edge cannot.
- **An open link vocabulary:** free-text types fragment ("blocks", "blocked by", "waiting on") and no query can trust
  them.
- **dagre for the HTML layout:** a second library; Cytoscape's own breadth-first layout, turned left to right, is enough
  at a Project's size.
