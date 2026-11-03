---
name: check-in
description: Runs the {{person}}'s recurring (weekly, by default) Check-in, reviewing each open Commitment with evidence, capturing Decisions and blockers, updating the profile facts that changed, then planning the next period's Focus. Use when the {{person}} wants a check-in, a weekly review or retro, reports how their week or Commitments went, or when a Nudge says a Check-in is overdue.
---

# Check-in

Follow the coaching contract of the coach skill throughout.

## Checklist

1. **Context.** `coach_get_context`: open and overdue Commitments, active Goals (if the Pack keeps them), stale profile facts, Decisions due for a revisit, `loop`.
2. **Is the loop on?** Read `loop` in the context. If `loop.on` is false, the {{person}} asked for this by name, so say that the recurring Focus and Check-in are off for this {{project_noun}} and offer once to turn them on (`coach_update_profile` `loop: on`, and `loop_every`: weekly, fortnightly or monthly), carrying on only after a yes. If `loop` is missing, this coach keeps no recurring loop: say so and stop. `loop.weeks` is the length of a period.
3. **Each open Commitment, one at a time.** Ask what happened and what the evidence is (numbers, names, links). Then propose the status:
   - `done`: the outcome was met or clearly advanced; the evidence goes in `note`.
   - `dropped`: no longer worth doing; the reason goes in `note`.
   - `carried`: still worth doing next period. The response tells you how many times in a row it has been carried (one period each); at 2 or more, ask what's really blocking it.
   When you can read the {{person}}'s calendar, email or documents, look for evidence first, starting where the profile's `workspace` says things live (the meetings, threads or files that match the Commitment) and show it in the proposal as "from your calendar: ..." for the {{person}} to confirm; follow the connector rules of the coach skill.
   Confirm, then `coach_update` with `id`, `status` and `note`. When the {{person}}'s message already says what happened, propose every status together in one reply rather than asking again.
   People name Commitments by position ("the first one", "the rest"): that is the order `coach_get_context` lists them. Resolve it yourself, show each match as id and action in the proposal, and let the {{person}} correct it; asking "which one?" before proposing is the slower path.
   Put every write of this Check-in in one proposal: each Commitment status, Goal change, profile change and the Check-in text. One yes saves all of it, in the same reply.
4. **Goals.** For each active Goal: met, dropped or still active? A Goal past its target date (the `goal_past_target` Nudge) needs one of three answers: met, dropped, or a new date. Update only what changed, on a yes; never change a Goal because its date passed.
5. **Decisions.** Ask whether any real choice was made this period. A Decision is a choice the {{person}} presents as a decision ("I've decided", "we chose A over B"). Record none otherwise: a dropped Commitment, a shift of priorities or a finished piece of work goes in the Commitment's `note` or the Check-in summary. Record each as kind `decision` with its reasoning and Citations if advice informed it. Review Decisions due for a revisit.
6. **The coach's questions and assumptions.** If `loop.questions` is not empty, ask each one in the {{person}}'s terms alongside their Commitments and fold the answers into the Check-in's summary, wins or blockers. When this coach keeps Notes, `coach_recall` the assumption Notes that are due or past `revisit_on` (and the period's other Notes) and ask whether each still holds: a changed one becomes a new Note that supersedes it, on a yes.
7. **Profile.** Confirm stale facts and update the profile facts that changed (whatever this {{project_noun}}'s profile holds) (`coach_update_profile`). Re-stating an unchanged value confirms it.
8. **Record the Check-in** (`coach_record`, kind `checkin`): summary, wins, blockers, in the {{person}}'s words, after they approve the text.
9. **Hand off** to weekly-focus for the next period.

## Why this order

Recorded progress with evidence is the strongest driver of goal attainment; reviewing before planning stops the same Commitment silently rolling forward.

## Gotchas

- A Check-in is complete only when every open Commitment has a status (`coach_update`) and the Check-in itself is recorded (`coach_record`, kind `checkin`). If recording it returns a warning about Commitments still open, finish those first.
- Name the one thing the {{person}} may be avoiding, once and kindly, if the evidence shows it (the same Commitment carried three weeks, no user conversations logged).
- Don't mark `done` on intent alone ("I mostly did it"): ask for the outcome.
