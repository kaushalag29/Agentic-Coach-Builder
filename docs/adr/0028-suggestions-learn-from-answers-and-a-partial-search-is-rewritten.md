---
status: accepted
---
# Link suggestions learn from the person's answers; a partial search is rewritten

Amends ADR-0025 (proposals) and the ask skill's search rounds. Builds on ADR-0026 (the usage log).

## The problem

A week of real use, read with `ytbrain gaps`:

- **Suggestions:** 14 of 41 accepted. The pre-ticked high tier did worse (4 of 17) than the review tier (10 of 24).
  The rule that ties a task with no Goal to the only active Goal was rejected 8 times out of 8. The rule that ties a
  Decision to one it names offered the same pair twice, once each way, after the first was accepted. The rule that
  offers a name said in three or more records offered companies, US states, a programming language, a weekday and a
  surname.
- **Searches:** 14 of the coding coach's searches came back partial, and none was rewritten, though the ask skill says
  a partial part gets a rewritten question in the next round. A rewrite during the review that found this went from
  0.624 to 0.772 (strong).
- **Measurement:** a coach's questions about one piece of work were logged under another Project, and the coaches ran
  different versions during the week, so the numbers mixed two things.

## Decision

- **A rule the person keeps rejecting is muted in that Project.** After 5 rejections in a Project with no yes, a rule
  queues and shows nothing there. The coach is told once (in `coach_graph op proposals`) and tells the person;
  `coach_update` on the rule's id (`p-r3`) with status accepted brings it back, its answers counted again from then;
  rejected keeps it muted. A rule with a yes since it came back is never muted. Muting is per coach and Project: a
  rule that misfires for one piece of work can be right for another.
- **The tie to the only active Goal is a guess:** review tier, never pre-ticked.
- **One suggestion per pair of records.** A pair already tied in any way, in either direction (a link of any type, a
  Decision superseded by the other, a task serving the Goal), or already suggested with another payload, gets no new
  suggestion, and a waiting one for a pair that got tied meanwhile is no longer shown.
- **A name is offered only where a person is meant.** At least once in its three records it follows with, from, by,
  asked, told, emailed, call or met, or it is a task's first word. Weekdays, months, places and common tools are never
  names. A name right after a confirmed Person's name is offered as that Person's other name (alias), not as a new
  Person.
- **A partial search asks for the next round.** The result's note asks the coach to rewrite the part as a new full
  question in the sources' terms and search again, stopping after two rewrites that don't beat its top similarity or
  at 12 searches for the question; the server counts the session's searches in the last 10 minutes and stops asking
  at 12.
- **The report measures it.** `ytbrain gaps` shows partial results left without a rewrite, how many were rewritten,
  the median gain in top similarity of the later rounds, and how many reached strong; refused writes gain a "too
  long" group. A rule brought back is not counted as a suggestion answered.
- **Smaller:** the vault action without a Project names the Projects to switch to; a Decision's `text` says it is one
  or two sentences of at most 1,000 characters, the rest in `reasoning` or a Note.

## Consequences

- Fewer suggestions the person has to wave away; a muted rule costs only the suggestions it would have made, and one
  yes brings it back.
- About one more search for each partial part of a question (about 30 % more searches at the rate observed).
- The name filter can miss a real person who is never named next to a cue word or as a task's owner.
- Revisit the fixed threshold of 5 when a Project has a few hundred answers: a rate with a minimum count would replace
  it. Content gaps are confirmed with `ytbrain gaps --replay` (ranking misses against missing material) before any
  source is added; the coaches search without a reranker today.

## Considered and rejected

- **Deleting the rules that misfired:** one Project's misfire is another's hit.
- **Learning a confidence per rule from every Project:** a few dozen answers on one machine is too little to learn from.
- **Leaving partial results to the skill alone:** the week shows the skill's round is skipped.
- **Re-running the search on the server with a rewrite of its own:** the coach knows what the part asks; the server
  doesn't.
