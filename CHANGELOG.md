# Changelog

User-visible changes, newest first. Coach plugins carry their own version (asked by `ytbrain ops plugin`); the
released benchmark carries its version in `eval/VERSION`.

## 0.1.0 — 2026-10-16 — first public release

The pipeline, three example coaches and the evaluation framework, developed privately since September 2026.

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
