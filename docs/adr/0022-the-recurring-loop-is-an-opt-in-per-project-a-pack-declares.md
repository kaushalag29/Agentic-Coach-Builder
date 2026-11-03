---
status: accepted
---
# The recurring loop is an opt-in per Project that a Pack declares

Extends ADR-0016 (a Pack defines a coach) and ADR-0019 (memory belongs to the work). Supersedes the Phase 3 rule
that a Pack either keeps the weekly Focus and Check-in or does not.

The weekly Focus and Check-in began as the founder's accountability loop. The coding coach got it by keeping the
`commitments` and `checkins` modules; the investor coach did not, yet a person whose Project is only a portfolio
still wants "what do I look at this period, and what did my discussions and research change?". The cadence is not
specific to startups, stocks or code: any coach that tracks work over time can use it, at a rhythm that suits the work.

## Decision

- There is one generic loop: a **Focus** (up to the Pack's limit of Commitments for the period) and a **Check-in**
  (what happened, what was decided, what changed). A general "routine" mechanism is deferred until a second Pack needs
  something this loop cannot express.
- A Pack declares the loop in `pack.toml` `[loop]`: `every` (`weekly`, `fortnightly` or `monthly`, which is four
  weeks), `default` (`on` or `off`) and `questions` (at most five short questions the Check-in asks in the Pack's own
  terms). Focus limits stay in `[limits]`. A Pack with `[loop]` gets the profile fields `loop` (`on` | `off`),
  `loop_every` and `checkin_day`.
- A Project chooses: its `loop` profile value overrides the Pack's `default`, its `loop_every` overrides `every`.
  Setup asks once; the answer is kept and not asked again. Founder is on by default, coding and investor are off.
- Storage does not change. Commitments and Check-ins stay keyed by ISO week; a longer period is a number of weeks.
  A Check-in is overdue when the period ended with none. Carried Commitments, repeated-carry warnings and the Nudge
  all read the Project's interval. The weekday Nudge applies only to a weekly loop.
- A Project has one Focus per period, shared by every coach on it: any coach may propose it and the person's yes
  saves it, and "at most three open" counts across coaches. Check-ins stay private to the coach that ran them.
- Every coach may keep an **Assumption** Note: "Assumption: <subject>" with why the person believes it, what would
  change their mind and a revisit date, offered and saved only on a yes, never written for them. The investor wording
  is a thesis (a reason for a holding, never an amount). When a Check-in runs, assumption Notes past their revisit
  date are asked about. The investor Review lists holdings that have no thesis Note or a past-due one.

## Consequences

- No store migration and no new tables. Older Projects read as before: with no `loop`, the Pack default applies.
- The loop skills check `loop` in `coach_get_context` first and stay silent when it is off.
- A new Pack gets the loop by adding `[loop]`, the two modules (`commitments`, `checkins`) and the two skills;
  `ytbrain coach new` drafts all of this when the described coach tracks ongoing work.
