# Coaches: Packs, plugins and the runtime

A coach is a **Pack** (`packs/<id>/pack.toml` and its skills) built into a **Claude Code plugin** that runs the shared
**runtime** (`founder_coach/`) over its own **Knowledge pack**. Three coaches ship as examples: `founder-coach`,
`coding-coach` and `investor-coach`. To make your own, see [build-your-own-coach.md](build-your-own-coach.md).

- [The Knowledge pack](#the-knowledge-pack)
- [The plugins](#the-plugins)
- [The runtime (`founder-coach`)](#the-runtime-founder-coach)
- [Developing a plugin with Claude Code](#developing-a-plugin-with-claude-code)

## The Knowledge pack (what the coach plugin ships)

The plugin can't ask founders to install PyTorch or download 4.6 GB of models, so it ships
a **Knowledge pack** instead of the index ([ADR-0009](adr/0009-plugin-ships-a-knowledge-pack-without-passages.md)):

- **What's in it:** every Verified advice, takeaway and summary (transcript Passages only with
  `--with-passages`) with its citation, a full-text index and one vector per
  item. One SQLite file of about 60 MB with the default model.
- **Models:** a small ONNX embedder through fastembed, with no torch. The default is
  `BAAI/bge-base-en-v1.5` (0.21 GB) with no reranker: on labels v1.2.0,
  `jinaai/jina-reranker-v1-turbo-en` lowered the pack's nDCG@10 (0.457 vs 0.479) and slowed every
  search (`pack build --rerank-model` still sets one). Models download once to
  `~/.ytbrain/models`, shared by every coach (an install from before Projects keeps using `~/.founder-coach/models`).
- **Same ranking code:** search, fusion, boosts and diversity are the same code the index
  uses (`founder_coach/search.py`), so `eval run` measures exactly what founders get.

```bash
uv pip install -e ".[pack]"            # fastembed + onnxruntime (already in the eval extra)
ytbrain pack build                     # a few minutes on a laptop CPU; resumable; writes data/pack/
ytbrain pack info                      # items, talks, models, size; verifies the checksum
ytbrain search "how should I price a B2B pilot" --pack
ytbrain eval run --set dev --config pack --compare full            # ADR-0009 gate: within 0.03 nDCG@10
```

To compare a variant, build it into its own folder and score it under its own name:
`ytbrain pack build --embed-model BAAI/bge-small-en-v1.5 --out data/pack-small`, then
`ytbrain eval run --config pack --pack data/pack-small --label small --compare full`, then
`ytbrain eval judge --config pack-small` and `ytbrain eval rescore --config pack-small --compare full`
(a variant returns Moments no judge has seen yet).

### The plugins

`plugin/` is the Claude Code plugin **as a template**: its files say `{{id}}` where the product
id goes, and `scripts/assemble_plugin.py` fills it in from the Pack's `packs/<id>/pack.toml` `[product]` (ADR-0016). It holds
the manifest, the MCP server config (`coach`, started with
`uvx --from ${CLAUDE_PLUGIN_ROOT} founder-coach serve --pack ${CLAUDE_PLUGIN_ROOT}/pack`), a fail-open SessionStart hook and 10
skills: `coach` (the coaching contract, model-only); `ask`, `weekly-focus`, `check-in`
(Playbooks); `project` (loads on its own when Projects come up); `setup`, `status`, `export`, `forget`, `feedback` (typed by the Founder). The skills
are the single source for the MCP prompts: the assembler regenerates `founder_coach/playbooks/*.md`
from them, and `founder_coach/product.json` from the Pack's `pack.toml` and `product.toml`.

```bash
python scripts/assemble_plugin.py --pack data/pack --check   # -> dist/plugin (previous build kept)
claude plugin validate dist/plugin --strict                  # no model call
ytbrain claude -- --plugin-dir dist/plugin                   # then: /founder-coach:setup (your plan, Haiku)
```

**One plugin per Pack** (ADR-0016). `packs/<id>/pack.toml` says what each coach is: its Domains, memory modules,
skills (its own `packs/<id>/skills/` first, then the shared ones above), profile fields, and the words its runtime
uses. The **coding coach** (`coding-coach`, private build only) answers from the coding and system-design Books and
talks, remembers a system's stack, scale, SLOs and constraints with its Goals and Decisions, and adds two Playbooks:
`design-review` (restate, ask for evidence, the single biggest risk, cited) and `decision-record` (a Decision in
memory, and on a second yes an ADR file in your repo).

The **investor coach** (`investor-coach`, private build only) holds your Investment Policy Statement per goal,
imports your broker's positions exports, and reviews allocation, drift and concentration exactly (no live prices); it
never recommends a security (gate G8).

```bash
ytbrain pack build --for coding --include-private --out data/packs/coding/pack-private
python scripts/assemble_plugin.py --for coding --pack data/packs/coding/pack-private --out dist/coding-coach-private --check
ytbrain eval choice --plugin dist/plugin-private --plugin dist/coding-coach-private --plugin dist/investor-coach-private   # P12: each of 45 prompts reaches the right coach (all of them, for a prompt that needs several)
ytbrain eval choice --quick --plugin dist/plugin-private --plugin dist/coding-coach-private --plugin dist/investor-coach-private   # a 15-prompt sample of every kind
```

A Pack's `builds` in its `pack.toml` says which plugins it gets: `private` (with your books) and/or `release` (public
Sources only). The coding and investor Packs list only `private` for now. Adding `release` gives them a public plugin
too: it is built from the public Documents in their Domains, its gates run and P12 covers the public set; while those
Domains have no public Document (the case until you add public playlists or sites to `sources.yaml`), the public build
is skipped with a note in `data/ops/last-run.md`, and the private build is unaffected. Nothing is published by `ops`.

Load `dist/plugin`, never `plugin/` itself. `--check` imports the assembled runtime and verifies
the pack's checksum before swapping the build in, so a broken build never replaces a working
one. Only `knowledge.sqlite` and `pack.json` ship; the embedding cache stays behind. `scripts/release.py`
(optional) publishes a build to a plugin repo of your own.

### The runtime (`founder-coach`)

The plugin runs `founder_coach`, a small package that never imports ytbrain, torch or LanceDB.
It serves the Knowledge pack and remembers the Founder, over MCP.

```bash
uv pip install -e ".[serve,pack]"
founder-coach warmup --pack data/pack        # download the search models once
founder-coach status --json                  # the same as JSON; --project ID picks a Project, --home DIR pins one folder
founder-coach projects [create NAME|rename ID NAME|use ID]   # the Projects; `use` sets the CLI's and hook's default
founder-coach serve --pack data/pack         # the stdio MCP server (what the plugin starts)
founder-coach status --pack data/pack        # pack, models, profile, what's due
founder-coach hook session-start             # what the SessionStart hook prints (silent when nothing is due)
founder-coach export                         # everything remembered, as JSON + Markdown
founder-coach forget                         # delete it all (type the company name; one backup is kept)
founder-coach forget --confirm "Acme"        # the same without a prompt (required when there's no terminal)
founder-coach forget --all                   # every Project and the Common profile (type 'forget all')
founder-coach restore --list                 # backups, newest first, each with its integrity check
founder-coach restore [LABEL]                # restore a backup (default: newest good one); old file set aside
founder-coach feedback list|export [--out D] # the Founder's Feedback; export writes only that, to send
founder-coach usage summary|export|clear     # the local usage log (docs/usage-log.md); clear needs --yes
founder-coach usage summary --days 30 --json # a window, as JSON; forget --no-backup also deletes the backups
ytbrain gaps [--pack founder|coding|investor] [--days 30] [--json]   # strong/partial/none searches per coach and Domain, from the usage logs
```

- **9 MCP tools, in this order:**
  - `coach_search`: cited advice; keyword-only while the models load (a search waits up to 20 s
    first); flags likely Gaps;
  - `coach_read`: a whole talk's items;
  - `coach_get_context`: profile, Goals, Commitments, last Check-in, Decisions, Nudges;
  - `coach_update_profile`, `coach_project`, `coach_record`, `coach_update`: every write needs a `request_id`
    and is logged, and names the Project it was proposed for (another Project's save is refused);
    `coach_project` lists, switches, creates and renames Projects, or summarises one on request;
  - `coach_corpus_status`;
  - `coach_feedback`: a Founder's report of a wrong answer, saved only after they approve it.
- **Also served:** 4 prompts (`ask`, `weekly-focus`, `check-in`, `setup`) and the resources
  `founder://profile`, `founder://this-week`, `corpus://status` and `corpus://item/{id}`.
- **Founder data** lives in one folder per Project, `~/.ytbrain/founder/projects/<id>/` (ADR-0016;
  `YTBRAIN_HOME` moves `~/.ytbrain`, and `FOUNDER_COACH_HOME` pins one folder with no Projects, as before them).
  A session works on one Project: with one it is chosen by itself, with several the coach asks. Facts true in
  every Project (name, role, timezone, answer style) go to the Common profile `~/.ytbrain/you.db` only on a yes.
  The first start after the update copies `~/.founder-coach/` into a Project once and leaves it as it was. Each
  Project folder holds:
  - `founder.db`, with a change log of every write;
  - `FOUNDER.md`, regenerated after every write;
  - `backups/`, daily (7 kept), before migrations and before forget;
  - Feedback, inside `founder.db` (since schema v3); `forget` deletes it too, and it isn't part of FOUNDER.md;
  - the usage log, also inside `founder.db`: one event per tool call (tool, time, duration, outcome,
    counts and item ids, never the Founder's words unless `FOUNDER_COACH_USAGE_TEXT=1`), kept 90 days,
    off with `FOUNDER_COACH_USAGE=0` ([docs/usage-log.md](usage-log.md)). `/founder-coach:setup` tells
    the Founder; `/founder-coach:feedback` offers its export. While dogfooding, the maintainer can
    `export FOUNDER_COACH_USAGE_TEXT=1` to also see the search text (never asked of other users).

  Several host sessions can use the store at once.
- **Failures stay contained.** The pack and the store open independently:
  - a pack that is missing or fails its sha256 check (against `pack.json`) is reported as
    unavailable by `coach_corpus_status` and `coach_search`, and memory keeps working;
  - a store that can't be read or fails `PRAGMA integrity_check` leaves search working, and the
    memory tools answer "nothing has been deleted: run `founder-coach restore`". Restore moves
    the damaged `founder.db` (and `-wal`/`-shm`) to `before-restore-<time>/`, never deletes it;
  - an ONNX error during one search answers with keyword matches (`mode: keyword`, with a note).
- **Settings** (the prefix follows the product id): `FOUNDER_COACH_HOME`, `FOUNDER_COACH_PACK`,
  `FOUNDER_COACH_MODELS`, `FOUNDER_COACH_RERANK` (`0`/`1`, default: what the pack says),
  `FOUNDER_COACH_GAP_SIMILARITY` (provisional 0.60), `FOUNDER_COACH_SEARCH_WAIT_S` (how long the
  first search waits for loading models, default 20), `FOUNDER_COACH_TOP_K` (hits per search when the host
  doesn't say, default 10, 1-15), `FOUNDER_COACH_LOG` (log level, stderr),
  `FOUNDER_COACH_WARMUP=0` (don't load models; tests), `FOUNDER_COACH_USAGE` (`0` turns the usage
  log off), `FOUNDER_COACH_USAGE_TEXT` (`1` also logs search text), `FOUNDER_COACH_USAGE_DAYS`
  (retention, default 90). The pack is looked for in `--pack`, `$FOUNDER_COACH_PACK`, the plugin's
  `pack/`, the repo's `data/pack`, `~/.ytbrain/<pack>/pack`, then `~/.founder-coach/pack` (from before Projects). All of them are listed in `.env.example`.
  They come from the environment, then `$FOUNDER_COACH_ENV_FILE`, `./.env` (the folder Claude Code was
  started in) and `~/.founder-coach/.env`; only `FOUNDER_COACH_*` lines are read, never keys, and
  `founder-coach status` shows which files were used. `ytbrain claude` hands the repo's `.env` to
  `claude plugin eval` too (its sandbox passes only `EVAL_*` variables), minus the location settings.

## Developing a plugin with Claude Code

Everything that runs Claude Code while you develop the plugin (`ytbrain eval coach`,
`claude plugin eval`, a live session with `dist/plugin`) runs the **local `claude` CLI on your
Claude plan by default**, set up to use as little of its limits as possible:

- **Haiku** unless you ask for another model (`--model sonnet`; `YTBRAIN_COACH_MODEL` changes the default);
- `eval coach` caps each call at 16 turns (`--max-turns`) and runs every case in a scratch folder
  outside the repo, so the repo's CLAUDE.md/AGENTS.md never ride along; each gate prints the tokens it used;
- a case that errors (a turn cap, a host hiccup) is not cached and does not fail the gate by itself: when the rest pass,
  the gate is **incomplete** (exit 2) and re-running the same command retries only those cases; if the Claude login has
  expired the run stops at the first case and says to run `claude`, then `/login`;
- the gates run before a release (`ytbrain ops plugin --coach`), not on every build; each is cached on what it reads and how it is
  graded, so editing one skill (or a gate's rubric, judges or grading code) re-runs only the gates it touches, and a
  version bump re-runs nothing;
- `claude plugin eval` with `--runs 1 --ablation none` while iterating (3 runs, with the
  without-plugin comparison, before a release).

```bash
ytbrain claude -- --plugin-dir dist/plugin                    # a live session with the plugin (Haiku)
python scripts/assemble_plugin.py --pack data/pack --with-evals --out dist/plugin-eval   # the eval build (never shipped)
ytbrain claude -- plugin eval dist/plugin-eval --runs 1 --ablation none   # the mocked skill checks
ytbrain eval coach                                            # the gates (Haiku, on your plan); exit 0 pass, 1 FAIL, 2 incomplete
ytbrain eval coach --model sonnet                             # sign a release off on the model founders use
```

**Optional, OpenRouter instead of the plan** (paid per token, e.g. when the plan's limit is
reached): `ytbrain claude --openrouter -- …` or `ytbrain eval coach --host openrouter` with
`YTBRAIN_COACH_HOST_KEY` in `.env` (default model `anthropic/claude-haiku-5.5`; host cost counts in
`--max-cost`). Claude Code is built for Anthropic models; a non-Anthropic model is for smoke tests only.
