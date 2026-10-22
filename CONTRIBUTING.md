# Contributing

Thanks for helping. Bug reports, docs fixes, new Source adapters and new example coaches are all welcome. Open an
issue first for anything large, so we can agree on the approach.

## Set up

```bash
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[serve,pack,dev,web]" "lancedb>=0.39.0"     # what CI installs; with less, some tests skip
sh scripts/check.sh                                              # everything CI runs, offline and free
printf '#!/bin/sh\nexec sh scripts/check.sh\n' > .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit   # optional
```

`git commit --no-verify` skips the hook for a work-in-progress commit. If you keep private material beside the repo
(your own Sources, data, names), list the words that must never be published in a file outside the repo, point
`YTBRAIN_PRIVATE_TERMS` at it, and install the pre-push hook that checks every push against it:
`ln -s ../../scripts/hooks/pre-push .git/hooks/pre-push` (`scripts/check.sh` runs the same check).

## Tests

```bash
for s in core eval pack coach projects invest plugin web books gaps docs; do YTBRAIN_DOTENV=0 python tests/test_$s.py || break; done
python -m pytest tests -q -p no:cacheprovider       # all suites in one process
```

| Suite | Guards |
|---|---|
| `test_core.py` | caption dedup, human-over-auto captions, evidence grounding both ways, per-Step checkpoints and parking, schema-version invalidation, atomic writes, rate pacing, extraction retries and windows |
| `test_eval.py` | benchmark build and release sealing, judges, metrics and gates, run labels, the coach eval harness (resume, usage-limit stop, persona checks) |
| `test_pack.py` | the Knowledge pack format, checksums, incremental rebuilds, shared search |
| `test_coach.py` | the Founder store (history, idempotent writes, migrations, backups, forget/restore, Feedback, the usage log, Check-in warnings), Nudges, all 9 MCP tools through the SDK client, the tool-schema snapshot, stdio under both protocol versions, concurrent writers |
| `test_projects.py` | Projects and the Common profile (M6e): each Project's memory kept apart, a session that asks which one, the write guard, sharing only on a yes and only a Pack's fields, the one-time move of `~/.founder-coach` (counts and change log kept, the old folder unchanged, once, damaged or busy), forget per Project, two coaches writing `you.db` at once, the command line, G7's grading |
| `test_invest.py` | the investor Pack: Fidelity, Schwab, Vanguard and named-column exports read or refused with what they need, allocation, drift and concentration to the cent across accounts (I1-I5), splits that add up exactly, the policy as profile facts, Holdings imported once, the tools end to end, nothing promoted to the shared profile (C3) |
| `test_plugin.py` | manifest, skills and their invocation, the assembler (template filling, atomic swap, `--check`), each coach's identity living only in its `pack.toml`, releases (tags, version checks, renames) |
| `test_books.py` | PDF Books on synthetic text and fixture PDFs only: probe, ligature repair, metadata, Chapters, ids and resume, private visibility, the sample sheet, folders found recursively |
| `test_web.py` | website Sources (ADR-0013): config, ids, scope and depth, robots.txt, page types, rendering, retries and host pausing, conditional re-checks, aliases, resume, articles through clean → extract → verify → items → pages, the CLI over a localhost server |
| `test_gaps.py` | `ytbrain gaps`: strong/partial/none searches per level and Domain, question text listed only when recorded (else how to turn it on), a read that leaves the store byte-identical and touches only the usage table, the window and Pack filter, a store without a usage log, the command's text and JSON, and the per-Domain fields on a search's usage row |
| `test_docs.py` | the docs say only what the code does: every `ytbrain` / `founder-coach` command and flag, `YTBRAIN_*` / `FOUNDER_COACH_*` setting, link and repo path named in the README and docs/ exists |

The tests use fakes (a hashing embedder, stubbed yt-dlp and LLM calls), so they need no keys, models or YouTube
access. They are hermetic: every suite sets `YTBRAIN_DOTENV=0`, so your `.env` and `sources.yaml` are never read.
CI (`.github/workflows/ci.yml`) runs a secret scan, `ruff check .`, every suite on Python 3.11 and 3.13 (a skipped
test fails the run), all suites again in one process, assembles each coach's plugin from a test pack, checks that the
generated files are current, and runs `claude plugin validate --strict`. What needs your Sources, models or keys is a
command, not a CI job: [docs/testing.md](docs/testing.md) lists them, cheapest first.

## Rules of the codebase

[AGENTS.md](AGENTS.md) holds the invariants. The ones that matter most:

1. Add a test for any behaviour change, especially resume, retries, verification or the coach's memory.
2. A change to `ytbrain/extract/schema.py` or an extraction prompt is a new release in `ytbrain/extract/versions.py`,
   compatible or breaking; a memory-store table change is a new numbered migration.
3. Never spell a coach's product id out in `plugin/` or `founder_coach/`: use `{{id}}` / `founder_coach.product`.
4. After an intended MCP tool change, review and regenerate the snapshot: `UPDATE_GOLDEN=1 python tests/test_coach.py`.
5. Record a hard-to-reverse choice as an ADR in `docs/adr/`, a new term in `CONTEXT.md`, and user-visible changes
   in `CHANGELOG.md`.
6. Keep the docs true: `tests/test_docs.py` fails on a command, flag, setting or path that doesn't exist.

By contributing you agree that your contribution is licensed under the repository's [license](LICENSE).
