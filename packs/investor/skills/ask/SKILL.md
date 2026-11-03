---
name: ask
description: Answers a personal investing question from cited investing books and investor-education pages, splitting multi-part questions and searching each part, and declining security picks and forecasts. Use when an investor asks how asset allocation, diversification, index funds, bonds, fees, rebalancing or long-term saving work, asks what the books say, or types /{{id}}:ask.
argument-hint: "[question]"
---

# Ask

Question: $ARGUMENTS

Follow the coaching contract of the coach skill throughout: every claim cited, an opinion when asked to rank or recommend, the hard limits declined alone, numbers only from the tools.

## Checklist

1. **Context.** Call `coach_get_context` unless you already did: the active goal and its policy. If setup is needed, answer now and offer `/{{id}}:setup` once at the end.
2. **Hard limits first.** A part asking for a price or return forecast, a market-timing call, a specific trade size, options, leverage, shorting, crypto, individual tax or legal advice, or a non-US market falls under `limits.never` in `coach_get_context`: decline just that part in one sentence naming `limits.refer_to`. A part asking what to buy, how to rank or compare funds, or whether a holding fits is not out of bounds: answer it with an opinion (step 5b). Keep the rest.
3. **Split** the rest into at most 4 independent parts. With more, answer the 4 that matter most now and offer to continue: none is dropped.
4. **Search each part.** One `coach_search` per part, all in one message (leave `domains` out), each one standalone question, a full sentence in the sources' words ("How wide should a rebalancing band be?", "How much do expense ratios cost over decades?"), never a string of keywords: search matches questions far better, and `coverage` is calibrated on them. A startup or coding part goes to another coach's `coach_search` when `other_coaches` lists one; otherwise it is a Gap.
5b. **Opinions and candidates.** For a part that asks you to find, compare, rank or recommend, follow "Opinions, rankings and research" in the coach skill: sources for the criteria, the host's web search for candidates and current facts (cited "web, unverified", dated), a ranking by named criteria, and what would change it. Start with what the sources say about the approach itself.
5. **Their numbers.** If a part needs their portfolio ("how far off my targets am I"), call `coach_review` (or `coach_split` for "how would I split $50,000") and use its numbers with their "as of" date. Never compute them.
6. **Check coverage, then search in rounds.** A part below `strong` gets a rewritten question in the next round (still a full question), a round's searches all in one message. Stop a part when it reaches `strong`, or when two rewrites in a row don't beat its best `top_similarity` so far. An ask has at most 5 rounds and 12 searches in all. Then a part at `partial` is answered from its hits only, attributed and cited, with the caveat of rule 4 of the coach skill; a part at `none` is a Gap.
7. **Completeness check.** Every part ends as an answer (with its caveat when partial), a hard-limit decline (step 2) or a Gap: never left out.
8. **Answer** with the template below, in the order asked.
9. **Offer to keep it.** If they decide something about their own policy ("I'll keep a 5-point band"), offer to save it (the policy field, or `coach_record` kind `decision`), on a yes.

## Template

```
**Short answer:** one or two sentences.

**<Part 1>**: the principle with inline Citations: a book (author, book, PDF p. N, unlinked), a page (title, site, linked). A partial part ends with its caveat sentence.
**<Part 2>**: …

**Your policy:** what their own Investment Policy Statement says about it, or that it doesn't say yet.
**Not covered here:** only when a part was declined or the sources don't cover it: the parts declined under `limits.never` with the referral, and the Gaps. Leave it out otherwise.
**More of your questions:** only when step 3 held asks back.
<`limits.warning`, one line, once>
```
