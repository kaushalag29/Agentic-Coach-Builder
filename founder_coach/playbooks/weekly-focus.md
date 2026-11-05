<!-- generated from plugin/skills/weekly-focus/SKILL.md by scripts/assemble_plugin.py; edit the skill -->
# Weekly focus

Follow the coaching contract in the server instructions throughout.

## Checklist

1. **Context.** `coach_get_context`: the profile, active Goals, this week's open Commitments, overdue ones, last Check-in, `loop`.
2. **Is the loop on?** Read `loop` in the context. If `loop.on` is false, the Founder asked for this by name, so say that the recurring Focus and Check-in are off for this company and offer once to turn them on (`coach_update_profile` `loop: on`, and `loop_every`: weekly, fortnightly or monthly). On a yes switch it on first; on a no, still agree one Focus for this period (the switch only governs reminders and the Check-in rhythm, never whether a Focus can be planned) and don't ask again. If `loop` is missing, this coach keeps no recurring loop: say so and stop. `loop.weeks` is the length of a period; a Focus covers all of it.
3. **Clear the old period first.** If overdue Commitments exist and no Check-in happened, suggest `the check-in prompt` before planning. Planning on top of unreviewed work hides what slipped.
4. **Find what matters.** For the most important Goal, run `coach_search` for what the library advises for this company's situation as the profile describes it. Use the last Check-in's blockers as queries too. With several Goals, or none, pick from the profile and what the Founder just said, and name that assumption in the proposal. When this coach keeps Notes, `coach_recall` the Notes of the period just ended (the research and discussions the Founder had) and any assumption Note that is due or past its `revisit_on`: a Commitment that follows from one says so in its `why`, and the Note is never cited as a library source.
5. **Propose up to 3 Commitments** (at most three open in all). Asked again in a period that already has a Focus (`this_week` holds open Commitments), never decline and never stack a second set: show the open ones and offer to keep them, to swap the ones the Founder wants to change (drop or carry those, then propose replacements up to three open in all). A repeat on a later day is a review of the Focus, not a refusal. Each:
   - **action**: one concrete thing ("Write the failing test for the retry bug").
   - **cue**: when/if it happens ("Tuesday and Thursday 9-11am, before email"). When you can read the Founder's calendar, pick a cue from time that is really free this week and say so; follow the rule on the Founder's other tools in the server instructions. Booking the time is the Founder's call: offer it, and add events only on a yes.
   - **outcome**: measurable ("the test merged and green on main").
   - **why**: one line with a Citation; pass its item_ids as the Commitment's `citations`.
   - linked `goal_id` when it serves a Goal.
6. **Push back** on a Commitment that doesn't move the biggest risk, and say which one you'd drop.
7. **Confirm.** Show the final list exactly as it will be saved and ask for a yes. Edit until it's right. A yes ("record them", "yes", "save it") is answered by the step-8 `coach_record` call in that same reply: never propose again, never start a Check-in first, no further questions.
8. **Record** with one `coach_record` call, kind `commitments`, all accepted items together. Relay any `warnings`.

## Why this shape

If-then plans with a measurable outcome are followed through far more often than open to-dos, and three is the most a person can protect in one week.

## Gotchas

- The proposal comes in the first reply. A missing Goal, role, name or detail is an assumption you state, never a question asked before the proposal.
- The week is the Founder's ISO week in their time zone; the tool fills it in. A Focus is recorded in the week it is agreed and covers `loop.weeks` weeks, so a fortnightly or monthly cue and outcome span the whole period.
- Carrying last week's Commitment is done in the Check-in (`coach_update`, status `carried`), not by recording a duplicate here.
