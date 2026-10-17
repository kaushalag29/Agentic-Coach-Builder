# Can a small local classifier replace the LLM tie-break? (Laya, October 2026)

**Result: no.** On the tag Step's close calls, [Laya](https://huggingface.co/convaiinnovations/laya), a 421M-parameter
ModernBERT decision model, was 13.9 points less accurate than the current LLM tie-break. The experiment also showed
that the weaker link is the embedding stage that picks the candidates, not the tie-break. Code to re-run it:
[experiments/laya/](../../experiments/laya/).

## The question

`ytbrain tag` scores each item against every Domain with embeddings. When two or more Domains are within a small
margin (a *close call*, about 36% of items in our Library), a cheap LLM (`deepseek/deepseek-v4-flash`) chooses among those
candidates. Could a local classifier do that job offline and free, with no loss in quality?

## Method

No hand labels: the reference is a **blind panel of three judges** from model families other than the tie-break's
(`google/gemma-4-31b-it`, `qwen/qwen3.8-flash`, `mistralai/mistral-medium-3.1`). Each labels every sampled item
against all seven Domains, never seeing the candidates or any arm's answer, with the Domain order shuffled per call.
The 2-of-3 majority is the silver label ([Verga et al., 2024](https://arxiv.org/abs/2404.18796)).

| | |
|---|---|
| Library | ≈ 60,000 items from YC talks, web articles and books, in 7 Domains |
| Sample | 2,400 close calls stratified by candidate set, plus 400 single-candidate items; fixed seed |
| Arms | embedding top-1 (no model) · deepseek (cached answers) · Laya choosing among the candidates · Laya choosing among all Domains |
| Metrics | accuracy with Wilson intervals, macro-F1, finance and investment F1, Cohen's and Fleiss' κ, paired bootstrap CI of the difference, exact McNemar test, items moved to a wrong Pack, ECE and Brier with a temperature fitted on a held-out 30% |
| Decision rules | fixed before the run: Δ accuracy CI lower bound above −2 points, high-tier F1 not more than 2 points lower, under 1% wrong-Pack moves, panel Fleiss' κ ≥ 0.6 |
| Cost | $0.32 for the panel; Laya ran locally on Apple silicon (about 34 minutes for 2,800 items, both arms) |

Laya's code was read before it ran, every file is checked against the reviewed SHA-256, and Hugging Face is switched
offline before the model loads.

## Results

The panel was reliable: Fleiss' κ 0.701, with a majority label on 2,733 of 2,800 items.

| Arm (2,342 close calls) | Accuracy (95% CI) | Δ vs deepseek (95% CI) | Investment F1 |
|---|---|---|---|
| deepseek (today) | 59.2% (57.2–61.2) | – | 0.62 |
| Laya, candidates only | 45.3% (43.3–47.3) | −13.9 (−16.1 to −11.7), McNemar p ≈ 4e-33 | 0.23 |
| Laya, all Domains | 36.0% (34.1–38.0) | −23.1 (−25.8 to −20.5) | 0.17 |
| Embedding top-1 | 37.4% (35.5–39.4) | −21.7 (−23.8 to −19.6) | 0.32 |

Laya's confidence did not rescue it: at confidence ≥ 0.8 it answers 11% of close calls, at 66% accuracy.

## What it found instead

- The whole tagger matches the panel's Domain on **62%** of items and its **Pack on about 87%**.
- For **24%** of close calls the panel's Domain is not among the embedding candidates at all, so no tie-break
  could get them right.
- The largest Pack error is general startup content placed in the coding Pack. A hand read of a sample agreed
  with the panel on most of them; the items the panel split on were genuinely multi-topic transcript chunks.

**Next:** test an LLM that classifies each item over all Domains instead of over the embedding candidates,
against the same panel (the tie-break model is not a panel member, so the comparison stays fair).

## Caveats

Silver labels from LLM judges are not ground truth and may favour LLM-style answers. Laya was used zero-shot,
which its model card says is near chance on typed decisions; a fine-tuned checkpoint was out of scope.
