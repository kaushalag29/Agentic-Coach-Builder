---
status: accepted
---
# Coaches give an opinion within limits their Pack declares

Extends ADR-0016 (a Pack defines a coach) and ADR-0011 (what a coach may write). Amends the coaching contract
rule that said a coach "points to a professional" for risky decisions.

The investor coach answered "which stocks should I buy?" by declining, and sometimes by calling the request a
security risk, so the person had to ask for web research by hand. The same wall can appear in any coach: a refusal
that covers a whole kind of question (rank, compare, recommend) instead of the one part that is out of bounds.

## Decision

- A coach never declines a request to find, compare, rank or recommend. It gives its best opinion, grounded in cited
  library knowledge and the person's recorded context, ranks by named criteria, says what would change the ranking,
  and says first when its sources argue against the approach itself (for example picking single stocks).
- Candidates and current facts (prices, versions, published figures) come from the host's web search, started by the
  coach without being asked, cited "web, unverified" with a date. The search carries only the question's subject,
  never the person's memory.
- Each Pack declares hard limits in `pack.toml` `[limits]`: `never` (what it will not answer), `refer_to` (who the
  person goes to instead) and `warning` (one line that ends an opinion). `never` requires `refer_to`. They reach the
  coach through `coach_get_context` as `limits`.
- The coach declines only the part under `limits.never`, in one sentence naming `limits.refer_to`, answers the rest,
  and ends with `limits.warning` once, after the answer.
- The investor Pack's limits: no price target or return forecast, no market-timing call, no specific trade size
  (except amounts from the person's policy through `coach_split`), no options, leverage, shorting or crypto, no
  individual tax or legal advice, no non-US markets.
- The G8 safety gate grades this: a rubric for opinion cases (answers, ranks, warns, stays inside the limits) and a
  rule-based check for sentences that cross a limit (a price target, a return forecast, a timing call, a share count).

## Consequences

- Every Pack states its limits in one place; `ytbrain coach new` drafts a `[limits]` block to edit.
- An opinion is not personalized advice: the warning says so, and the project advises checking the feature with a
  qualified person before it is given to others.
- The old "decline every security pick" cases in G8 become opinion cases; declining is graded only for `limits.never`.
