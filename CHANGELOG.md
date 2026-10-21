# Changelog

User-visible changes, newest first. Coach plugins carry their own version (asked by `ytbrain ops plugin`); the
released benchmark carries its version in `eval/VERSION`.

## Unreleased

- **Data outside the checkout:** new settings `YTBRAIN_DATA` (the `data/` folder) and `YTBRAIN_DIST` (built plugins);
  a relative path in `sources.yaml` now follows that file's folder (unchanged when it is in the repo). See
  [configuration.md](docs/configuration.md#keep-your-data-outside-the-checkout).
- **Private-terms check:** `scripts/check_private_terms.py`, run by `scripts/check.sh` and an optional pre-push hook
  (`scripts/hooks/pre-push`), refuses a commit or push holding a term from a list you keep outside the repo
  (`YTBRAIN_PRIVATE_TERMS`).
- **Tagging:** under `auto`, a high-tier Domain's share is now taken over a Document's tagged Passages (Passages that
  fit no Domain no longer count against it), with at least two decided Passages; videos mostly about investing now
  reach the investor coach instead of falling to the default Domain. A Document about nothing but an unconfirmed
  high-tier Domain is now *unplaced* (in no coach) until it is confirmed, never given the default Domain
  (ADR-0017 amendment).
- **Coach status reports how the app runs it:** `coach_corpus_status` gains `host` (process id and start time,
  the folder the app named, whether it offers workspace roots), to settle ADR-0019's open question before Projects
  follow the work folder.
- **ADR-0019 (accepted): memory belongs to the work.** Projects will be shared by every coach and chosen by the work
  folder; ADR-0016 is amended. Not built yet.
- **Checks run the repo's own Python:** `scripts/check.sh` and the pre-push hook now prefer the repo's `.venv` over an
  environment left active from another checkout (which would have tested that checkout's code), via `scripts/python.sh`.
- **`finance` says what it is not:** markets, the economy and investing your own money belong to `investment`; the
  tie-break reads it on close calls between the two (ADR-0017).
- **`ytbrain ops`:** the coverage step's note now reads `eval gap`'s exit code right (1: targets missed, 3: too
  few questions).
- **Builds leave the repo clean:** `ytbrain ops plugin` keeps its build counter in the data folder and passes it to
  `scripts/assemble_plugin.py --version`; the repo's version changes only with a release.

## 0.1.0 — 2026-10-16 — first public release

The pipeline, three example coaches and the evaluation framework.

- **Sources:** YouTube playlists (one caption track per talk, never video; a pause after an HTTP 429), any website
  through a polite crawler (robots.txt, per-host pacing, a headless browser only when needed), and PDF books as a
  private Source (PDFium, one Document per Chapter, never shipped in a release build).
- **Verified knowledge:** one LLM call per Document extracts advice, takeaways, facts and rules with quotes; `verify`
  locates every quote and derives its timestamp, paragraph or page. Extraction releases are versioned per prompt, and
  compatible records are kept.
- **Domains by content:** `ytbrain tag` scores items against a controlled Domain list and lets a cheap model decide
  only close calls; a high-tier Domain is applied only when it covers at least half of a Document, a Source
  names it, or you confirm it.
- **Packs:** one engine, one plugin per coach (`packs/<id>/pack.toml`): founder, coding and investor coaches, each
  with Projects (separate memory per company, system or goal) and a shared, opt-in Common profile.
- **Coach runtime:** a light MCP server (no PyTorch) with hybrid search over an ONNX Knowledge pack, honest
  `coverage` (strong, partial, none), Search rounds of up to 5 rounds and 12 searches, 10 hits per search, local
  memory with a change log and backups, and a local usage log with `ytbrain gaps` to see what coaches couldn't answer.
- **Evaluation:** a retrieval benchmark (Tuning sets per source kind, two judges and a tie-breaker, nDCG@10 with
  intervals and a regression gate), coverage-honesty checks (`eval gap`), plugin choice across coaches
  (`eval choice`), and coach gates G2–G8 on the real host, each cached on its inputs and on how it is graded.
- **Operations:** `ytbrain ops` runs ingest, evaluation and the plugin builds in one resumable command that does only
  what changed.
- **Experiment:** [Laya as the tagging tie-break](docs/experiments/laya-tagging-tiebreak.md), rejected.
