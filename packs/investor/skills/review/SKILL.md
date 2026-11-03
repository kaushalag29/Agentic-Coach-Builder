---
name: review
description: Reviews the Investor's holdings for one goal against their own Investment Policy Statement, exact allocation, drift and concentration as of their broker export's date, stated as facts against their rules, never as a trade. Use when an investor asks how their portfolio is doing against targets, whether they are off their allocation or over a limit, wants to rebalance, or types /{{id}}:review.
argument-hint: "[positions CSV path]"
---

# Review

Positions file (optional): $ARGUMENTS

Follow the coaching contract of the coach skill, rules 5 and 6 above all.

## Checklist

1. **Context.** `coach_get_context`: the goal, its policy, and Nudges. With `holdings_stale` or `holdings_missing`, ask for a fresh positions export from each account first (or use the file given above).
2. **Import, if a file was given.** `coach_holdings` action `import` with its path (and `account` or `as_of` if the tool asks for them). If it is refused, tell them exactly what it needs. Symbols it reports without an asset class: ask them for each, then save their answers with action `label`. Never guess a class.
3. **Review.** `coach_review`. If `missing_policy` lists fields, say which and offer `/{{id}}:setup` for them; review what can be reviewed.
4. **Earlier reviews.** Before you report, call `coach_recall` for earlier review Notes on this goal and add one line comparing with the last one ("outside the band last time too"), only from what the Note says.
5. **Theses.** Name each holding in the review that has no assumption Note ("Assumption: why I hold <symbol>"), and each whose Note is past its `revisit_on` (`coach_recall` with the symbol and "Assumption"). List them under the template's "Theses" line as facts, one line each, and offer to write the missing ones with them (an assumption Note: their reason and what would make them sell, in their words, saved on a yes). A holding the policy exempts as a broad index fund needs none. Never write a thesis for them or judge one.
6. **Report** with the template. Numbers exactly as the tool returned them, always with the "as of" date. A holding over their limit is stated with its amount over the limit; the action is theirs, and what their policy says about it is quoted.
7. **Their decision.** If they decide something ("I'll rebalance by new contributions, not sales"), offer to save it as a Decision with `coach_record` kind `decision`, on a yes. A rebalance they choose to make is a Decision too: what they will do, by which route (new contributions, sales) and by when, in their words.
8. **Keep the review.** Offer one Note for the review itself, saved with `coach_record` kind `note` only on a yes: title "Review <as-of date>: <goal>", type `discussion` (or `insight` when the review changed how they see the portfolio), origin `coach`, a summary of a few sentences with the figures exactly as `coach_review` returned them (allocation, classes outside the band, the holding over the limit, what was not counted), what they said about it, and links to the goal and to the Decision from step 5 if one was saved. Set `revisit_on` to the as-of date plus their `review_days`, so the next review comes back as a Nudge. Never put a recommendation in the Note: it holds what was found and what the person decided.

## Template

```
**As of <date>** · <accounts> · total <total>

| Asset class | Value | Now | Target | Drift | To target |
|---|---|---|---|---|---|
| ... from coach_review ... |

**Outside your <band>-point band:** <classes>, or none.
**Over your <limit> % limit:** <holding>: <value>, <percent> %; <amount> over it. Or none.
**Not counted:** unlabelled holdings (<percent> %), if any.
**Theses:** holdings without a thesis Note or with one past its date, or none.
**What your policy says:** the rebalancing rule and limit, quoted.
<`limits.warning`, only when you gave an opinion beyond the facts above>
```

## Gotchas

- Never turn a number into an instruction: "VTI is 49 % of the goal" is a fact; "sell some VTI" is not yours to say.
- `stale: true` means the holdings are older than their review interval: say so before any number.
- A rebalance is the Investor's call: the facts and what their policy says are yours; "which fund to buy with new money" is an Opinion (rank by named criteria, with `limits.warning`), never a size or a timing call beyond their policy (`coach_split`).
- Taxes on rebalancing (selling in a taxable account) are a tax professional's question: say so in one sentence if they ask.
