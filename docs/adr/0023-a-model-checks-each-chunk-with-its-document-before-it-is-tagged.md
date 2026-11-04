---
status: accepted
---
# A model checks each chunk with its Document before it is tagged

Amends ADR-0017 (Domains are inferred against a controlled list). The embedding tagger stays the first pass; this
adds a second one for the chunks it cannot decide, and a safe way to apply it to a Library that is already tagged.

## The problem

A sample of the `coding` Domain showed tags that were wrong for the Document's real subject: founder talks tagged
`coding` for mentioning software, and genuine coding talks that also belong elsewhere. They start at the chunk. A chunk
is short and read without its Document, so its embedding scores for two Domains are nearly tied (around 0.5), and the
tie-break model sees only the same chunk (700 characters). A Document then inherits what its chunks say (about a
quarter of the wrong tags came from that inheritance). No Document-share threshold separates the right Documents from
the wrong ones, and the Domain list gave AI engineering nowhere of its own, so those books landed in `coding` or
`system-design` by default.

## Decision

- **A checker reads each flagged chunk with its Document.** It sees the chunk (700 characters), the Document's title
  and the first 300 characters of its summary, and the whole Domain list (description, examples, `not_about`). It
  answers one or two Domains, or none, from the closed list; a name outside it is no answer. Temperature 0, 40 chunks
  a call, the tie-break model unless `YTBRAIN_TAG_CHECK_MODEL` names another.
- **Which chunks:** `flagged` (a chunk the embedding could not place, or where a Domain nobody hinted wins or ties) or
  `all`. A hinted Domain the embedding agrees with is trusted. Summaries never (they take their Document's Domains). A
  chunk with a verdict is not sent to the tie-break.
- **A verdict replaces the chunk's tag, nothing else.** Document Domains are recomputed from the corrected chunks by
  the same Passage-share rule; a chunk the checker says nothing fits takes its Document's Domains and is not counted.
  High-tier Domains still wait for a hint or a confirmation (ADR-0017); a person's confirmation or rejection still
  wins over any model.
- **Cached, so it can be retried:** verdicts live in `tags.db` (`checked`) under a key of the chunk, the Document
  context, every Domain's definition, the prompt version and the model. A changed definition, prompt or model reads
  again; nothing else does. A model that cannot answer, or a spent budget, leaves the chunk with its embedding and
  tie-break tag, counted as unchecked and read again next run. The checker's spend comes off the same `--max-cost`.
- **A rejection removes the Domain from the Document's items too.** Before, `domains review --reject` removed only the
  Document-level tag and low-tier item tags stayed.
- **A new Domain, `ai-engineering`:** building applications on foundation models (prompting, retrieval, agents,
  evaluation, fine-tuning, dataset engineering, inference cost). Low risk, 730-day freshness, listed by the coding Pack
  only. `coding` now names programming languages and AI coding assistants, and its `not_about` points to
  `ai-engineering` and `startup`. `enrich` includes the new Domain.
- **Applying it to what is already tagged is staged:**
  1. `ytbrain tag --check flagged --stage` runs the checker and keeps the whole result beside the tags in use
     (`staged_item_tags`, `staged_doc_tags`); the index and the tags in use are not touched. Verdicts are cached, so a
     stopped run continues.
  2. `ytbrain domains diff` lists, per Domain, the items and Documents that would gain or lose it (`--csv` writes the
     changed chunks with their text, to read them).
  3. `ytbrain domains promote DOMAIN ...` backs up `tags.db`, then in one transaction takes only the staged changes that
     gain or lose those Domains, and puts them on the index in place. It refuses a staged run made against another
     Domain list, or with chunks still unchecked (`--allow-unchecked`). An item never ends with no Domain: losing its last
     one gives it the staged Domains.
  4. `ytbrain domains restore` puts a backup back (the latest by default; what it replaces is backed up first) and its
     Domains on the index.
- **Off by default** (`YTBRAIN_TAG_CHECK=off`). It is switched on for ingest after the backfill has been promoted.
  New content then takes the same path in the `ingest:tag` step, with the same `--max-cost` cap.

## Validation

No human labels. `experiments/laya/panel_sheet.py` has the three-judge panel of the Laya experiment label a `ytbrain
domains sample` sheet: a row's label is the Domains at least two judges named, and a row where none reaches two stays
empty. `ytbrain eval tags --items SHEET --compare` then scores the tags in use and the staged run on those labels. The
staged run must beat the tags in use (precision and recall together), no Pack may be reached wrongly more than one
point more often than before, and a Domain is promotable only if it has at least 10 labelled items, its F1 is within
0.02 of the tags in use and every Pack that lists it passes. A short read of the chunks where the checker, the embedding and the panel disagree (`domains diff
--csv`) guards against judges that share a blind spot. The comparison has three arms: the tags in use, the checker on
flagged chunks, the checker on all chunks (`tag --check all --stage`).

## Consequences

- Cost: about one cheap call per 40 flagged chunks (`EST_COST_PER_CALL`); the first backfill is bounded by `--max-cost`.
  Ingest costs a few cents per new Document.
- The checker reads text, so it inherits a model's mistakes; the panel bar and the per-Domain promotion are what contain
  them. Tags stay inspectable (`domains why` shows a chunk's origin `checked`).
- Not decided here: a browse (catalog) tool beside search, and an index for the coach's own records. Both wait for the
  backfill and for evidence they help.

## Amendment (2026-11-04): the wrong-Pack gate

The first gate said under 1 % of labelled items to a wrong Pack. The first real comparison (295 panel-labelled chunks)
put the tags in use at 13.9 % and the checker at 12.9 %: a panel that reads a chunk without its Document, and a
finance/investment boundary that is arguable chunk by chunk, leave about one chunk in eight "wrong" whoever tags it, so
no tagger could pass. The gate was replaced, with the maintainer's agreement and before anything was promoted, by a
rule that measures what the worry was about: per Pack, wrongly reached items must not rise by more than a point over the
tags in use. On those 295 chunks the checker raised precision 59 -> 73 %, recall 58 -> 68 % and exact matches 155 -> 190,
cut wrong entries to the coding Pack 5.4 -> 3.1 %, and doubled them for the investor Pack 3.4 -> 6.8 %, which holds the
`investment` Domain back.
