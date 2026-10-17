# Commands by phase

Every command is resumable: Ctrl+C keeps finished work, and re-running continues. Install once:
`uv pip install -e ".[extract,index,serve,eval,pack,dev,pot,web,pdf]"` (everything), then
`playwright install chromium` for JavaScript-only websites.

## Every command

| Command | Does | Useful flags |
|---|---|---|
| `ops [ingest\|eval\|plugin]` | The whole loop in one resumable, change-detecting command: ingest, then eval when the index changed, then the plugin when it passed; asks the plugin version, handles retries and stop reasons, notifies ([docs/ops.md](ops.md)) | `--dry-run`, `--max-cost`, `--max-extract`, `--no-sync`, `--coach` (the coach eval, before a release), `--restart`, `--force`, `--version patch\|minor\|skip`, `--no-notify` |
| `discover` | Build/extend `sources.yaml` | `--method ytdlp\|api`, `--channel` |
| `sync` | List playlists and download captions + `info.json` (no video); crawl websites | `--type website\|youtube\|book`, `--source ID`, `--limit N` (per Source), `--strict-domains` (exit 1 on a Book folder that is not a Domain), `--force` (re-fetch), `--reconcile` (mark removed videos), `--backfill` (slowly retry rate-limited videos only), `--per-hour N`, `--sleep-subtitles S`, `--ignore-pause` (try YouTube during the YouTube pause) |
| `clean` | Caption file → deduplicated, ~10–25 s timestamped utterances; web page → numbered paragraphs | `--limit N`, `--retry-failed` |
| `extract` | One LLM call per Document → structured record | `--limit N`, `--workers N`, `--retry-failed`, `--doc PREFIX` (e.g. a Book's ISBN) |
| `verify` | Locate every evidence quote in the transcript; write pages | `--limit N`, `--retry-failed`, `--doc PREFIX` |
| `books inspect PATH…` | Check Books before any LLM call: metadata, Chapters, repaired words, refused files | `--expect FILE` (exit 1 on a mismatch) |
| `index` | Build the Knowledge index (advice, takeaways, summaries, transcript passages) with local embeddings; only Verified knowledge | `--limit N`, `--device auto\|mps\|cpu\|cuda`, `--retry-failed` |
| `search "question"` | Hybrid search (vector + full-text, reranked) with deep-link citations | `--stage`, `--require-stage`, `--kind`, `--topic`, `--top-k`, `--no-rerank`, `--device`, `--json`, `--pack [PATH]` |
| `eval build` | Build or resume the eval benchmark ([docs/eval-spec.md](eval-spec.md)): one Tuning question set per source kind (Talks, Articles, public Books, your private Sources), each at most 20 % of its Documents; generated questions, pooled candidates, two-judge grading; resumable and spend-capped | `--set dev\|dev-articles\|dev-chapters\|dev-private\|test` (default: every split), `--top-up` (only questions for new Documents), `--max-cost`, `--workers`, `--limit`, `--device` |
| `eval run` | Score a search configuration: nDCG@10, recall, MRR with 95 % intervals; compare with a baseline and apply the regression gate (0.03 nDCG@10 for pack configs) | `--set` (default `all`: every Tuning split, one nDCG row per source kind), `--config full\|no-rerank\|stage-boost\|pack\|pack-no-rerank\|full-no-passages\|full-route\|pack-route`, `--save-baseline`, `--compare CONFIG`, `--pack PATH`, `--label NAME` (a variant saved as `<config>-NAME`), `--smoke`, `--device` |
| `eval route` | Score the Domain router with no LLM: single questions (is the best Domain one of the seed Document's?) and composed two-Domain prompts (is every Domain routed?), swept over the margin | `--set`, `--pack PATH`, `--composed N`, `--device` |
| `eval calibrate` | Fit the curve that turns a hit's similarity into the probability it is relevant (isotonic, on your judged hits), check it on held-out questions and save `data/eval/calibration.json` if it beats the provisional curve; `pack build` ships it | `--set`, `--pack PATH`, `--k N`, `--force`, `--no-save` |
| `eval gap` | Measure whether `coverage` is honest, no LLM: wrongful answers on Gap questions (target <= 10 %), wrongful refusals on answerable ones (<= 15 %), swept over the border; exit 0 pass, 1 fail, 3 inconclusive | `--set`, `--pack PATH`, `--questions FILE`, `--tune` |
| `pack build` | Build the Knowledge pack the coach plugin ships: every Verified advice/takeaway/summary (Passages only with `--with-passages`) embedded with a small ONNX model into one SQLite file; resumable, re-embeds only new or changed items | `--for PACK` (a Pack's Domains only, packs/<id>/pack.toml; default founder), `--embed-model`, `--rerank-model` (`none` = no reranker, the default), `--batch`, `--device cpu\|coreml\|cuda`, `--with-passages`, `--include-private` (your Books; never released), `--route` (turn on the server's automatic Domain routing for this pack), `--out DIR` |
| `pack info` | Describe the pack and verify its checksum | `--out DIR` |
| `eval judge` | Grade the Moments a saved run retrieved that no judge has seen (pool extension), then re-release the labels as a new minor version; resumable and spend-capped | `--config C` (repeatable), `--set`, `--depth`, `--max-cost`, `--workers` |
| `eval rescore` | Score a saved run again against the current labels, without searching (seconds); only the questions the run was asked | `--config`, `--set`, `--compare`, `--save-baseline`, `--refresh-baseline`, `--run FILE --as NAME` |
| `eval status` | Progress and LLM spend per split | |
| `pages` | Re-render all markdown pages from the JSON records | |
| `refresh` | Re-apply Series and provenance from `sources.yaml` and yt-dlp metadata to documents, records and pages (no network, no LLM) | |
| `run` | sync → clean → extract → verify → index: the scheduled job (launchd), ingest only; `ops ingest` runs the same steps with checkpoints, and `ops` adds eval and plugin | `--limit` (per playlist for sync, per Step after), `--workers`, `--device`, `--force`, `--reconcile`, `--source ID`, `--type website\|youtube\|book` |
| `report` | Acceptance numbers + last three runs | |
| `sample` | Stratified review sheet in `data/reports/` | `--n`, `--seed`, `--doc PREFIX` |
| `status` | Count of finished items per stage, and records per extraction version (ADR-0018) | |
| `upgrade` | Re-extract valid records a new extraction would make differently (an older prompt version), on purpose and within a cap; marks them, then run `extract`, `verify`, `index` | `--dry-run`, `--max-cost USD`, `--variant NAME`, `--doc PREFIX` |
| `invalidate <stage>` | Mark `fetch`, `clean`, `extract`, `verify` or `index` for redo | `--only-flagged`, `--source ID`, `--reason` |
| `drop --source ID` | Take a Source's Documents out of the knowledge (then `index`) | |
| `domains [list\|add\|ignore\|alias\|why\|review\|propose\|sample]` | The Library's Domains in `domains.yaml` (comments kept): list them, declare one (`add NAME --risk low\|medium\|high --description "…"`), mark a sorting folder (`ignore FOLDER`), another name for one (`alias DOMAIN NAME`); why a Document has its Domains (`why DOC`); high-tier tags awaiting confirmation (`review`, `--accept SOURCE:DOMAIN`); proposed Domains for content none fits (`propose`); labelling sheets for `eval tags` (`sample`) | `--example Q`, `--freshness DAYS`, `--web-policy`; `review --accept`; `propose --min-size N`; `sample --n --docs --seed` |
| `enrich` | Add Rules, and Facts to records without any, for investment, coding and system-design Documents (ADR-0018): one call per Document, every item quoted; marks `verify` stale so the quotes are checked, then `index` turns them into `rule` and `fact` items; once per extraction and enrich prompt | `--dry-run`, `--max-cost USD`, `--doc PREFIX`, `--limit N` |
| `eval latency` | Search p95 the way the plugin runs it (its runtime, a Knowledge pack, ONNX models), on real Tuning questions after a warm-up; gate 1.5 s; writes data/eval/latency.json | `--pack PATH`, `--n`, `--no-rerank` |
| `eval parity` | The subject-neutral extraction prompt against the startup one on ~30 startup talks (shadow extractions, the Library untouched): the neutral verifier pass rate within 2 points and at least 80 % of the Verified items; a pass makes new founder content use it | `--n`, `--max-cost` (default $1) |
| `tag` | Tag Passages and items with Domains by what they say (ADR-0017): embedding scores, a cheap model for close calls only (cached), Document Domains by Passage share; nothing re-extracted or re-embedded | `--dry-run`, `--max-cost USD`, `--no-llm`, `--no-apply`, `--gated` |
| `eval coach` | Gates G2 and G4–G8 (G8 for the investor coach) on the real host: the local Claude Code on your plan (Haiku, token-saving). Each gate is cached on what it reads (runtime, pack content, its skills, its cases) and how it is graded (rubric, judges, turn cap, the grading code), so only gates whose inputs changed run; a failed G4-G6 case gets up to three runs and a majority decides; stops if the plugin is reassembled mid-run with a change the gate reads | `--gate`, `--limit`, `--model`, `--max-turns`, `--host claude\|openrouter`, `--max-cost`, `--plugin DIR` (default `dist/plugin`) |
| `claude [--model M] [--openrouter] -- <args>` | The local Claude Code for plugin work, on your plan with Haiku | `--model`, `--openrouter` (before `--`) |

`--limit` counts Documents per Step (for `sync`, per Source). A Document that fails a Step 3 runs in a row is parked;
`--retry-failed` tries it again.

## The whole loop ([ops.md](ops.md))

```bash
ytbrain ops                 # ingest -> eval when the index changed -> plugin when it passed; resumable
ytbrain ops --dry-run       # what is due
```

## Tests (run after any change)

The whole system, end to end, cheapest level first: [testing.md](testing.md). The offline suites:

```bash
for t in core eval pack coach projects invest plugin web books gaps docs; do YTBRAIN_DOTENV=0 python tests/test_$t.py | tail -1; done
```

## Corpus (sync → clean → extract → verify)

```bash
ytbrain discover                      # list the channel's playlists into sources.yaml candidates
ytbrain run                           # the whole pipeline: sync, clean, extract, verify, index
ytbrain sync --backfill               # retry caption downloads that hit HTTP 429, slowly
ytbrain sync --reconcile              # tombstone videos removed upstream (weekly)
ytbrain refresh                       # backfill Series and provenance without re-extracting
ytbrain clean ; ytbrain extract --workers 4 ; ytbrain verify     # one Step at a time
ytbrain status                        # per-Step counts, and records per extraction version (ADR-0018)
ytbrain tag --dry-run                 # Domains by content (ADR-0017): close calls, their cost, Documents per Domain
ytbrain tag --no-apply                # store the tags for review and labelling; the index keeps its Domains
ytbrain tag --no-apply --retry-undecided   # ask again about close calls the model left undecided (cached otherwise)
ytbrain domains sample                # labelling sheets (100 items, 30 Documents) in data/reports/
ytbrain eval tags --items domain-labels-items-<date>.csv --documents domain-labels-documents-<date>.csv
ytbrain eval tags --items ... --documents ... --tune --save   # thresholds that pass on your labels
ytbrain tag                           # apply (ops runs `tag --gated`: every run under the default auto policy, only after eval tags passed under reviewed)
ytbrain domains why <doc>             # where a Document's Domains came from
ytbrain domains review                # high-tier tags awaiting your yes (--accept SOURCE:DOMAIN)
ytbrain domains propose               # content no Domain fits, grouped, checked against the list
ytbrain gaps [--pack P] [--days 30] [--json]  # what the dogfooded coaches could not answer well (their usage logs)
ytbrain eval run --config pack-oracle-domains|pack-oracle-topic --compare pack-no-rerank   # a perfect hard filter vs the whole Library
ytbrain upgrade --dry-run             # records a new extraction would make differently: how many, at what cost
                                      #   (coding and system-design chapters move to the subject-neutral prompt)
ytbrain eval parity                   # the neutral prompt vs the startup one on ~30 startup talks (shadow, ~$0.10)
ytbrain enrich --dry-run              # Rules (and Facts) for investment, coding, system-design Documents
ytbrain enrich --max-cost 2 && ytbrain verify && ytbrain index
ytbrain enrich --workers 4            # parallel model calls (default YTBRAIN_LLM_WORKERS, as for extract); progress as extract's
ytbrain upgrade --max-cost 2          # re-extract as many of them as fit $2 (then extract, verify, index)
ytbrain report                        # quality gates
ytbrain sample --n 10                 # human review sheet in data/reports/ (fill the verdicts)
ytbrain pages                         # readable Markdown per talk in data/pages/
ytbrain invalidate extract --only-flagged   # re-run one Step for flagged records
ytbrain extract --retry-failed        # also retry talks parked after failing 3 runs in a row
                                      # (same flag on clean, verify and index)
```

## Knowledge index and search

```bash
ytbrain index                         # embed Verified items into LanceDB (part of `run`)
ytbrain search "how do I price a B2B pilot" --stage mvp
ytbrain search "..." --no-rerank --kind advice --json
```

## Retrieval eval (Tuning sets)

```bash
ytbrain eval build --set dev --limit 5            # smoke test in data/eval/smoke
ytbrain eval build                                # every Tuning split (talks, articles, books, private), spend-capped per split
ytbrain eval build --top-up                       # grow each split to 20% of its Documents (at most)
ytbrain eval build --set dev-private              # one split
ytbrain eval status                               # each split's questions, target and spend
ytbrain eval run --set dev --save-baseline        # full setup = the baseline
ytbrain eval run --set dev --config no-rerank --compare full
ytbrain eval run --set dev --config full-no-passages --compare full
ytbrain eval run --set dev --config pack --compare full           # G1: within 0.03 nDCG@10
ytbrain eval run --set dev --config pack-no-rerank --compare full
ytbrain eval judge --set dev --config full --config pack   # grade Moments no judge has seen (pool extension)
ytbrain eval rescore --set dev --config full --save-baseline      # score a saved run again, no search
ytbrain eval rescore --set dev --config pack --compare full
ytbrain eval rescore --config full --refresh-baseline   # the baseline, re-scored on new labels
```

Exit codes: 0 pass, 1 regression, 3 inconclusive (read the verdict). After new Documents are
indexed: `pack build`, then `eval run` for full (`--save-baseline`) and pack, `eval judge` on both, and
`eval rescore` (full `--save-baseline`, then pack `--compare full`). `eval judge` and `eval run --config
pack` say so when a saved run or the pack is older than the index.

## Knowledge pack

```bash
ytbrain pack build                    # data/pack: knowledge.sqlite + pack.json (resumable); the founder Pack's Domains
ytbrain pack build --for coding --include-private   # another Pack (packs/<id>/pack.toml): data/packs/coding/pack-private
python scripts/assemble_plugin.py --for coding --pack data/packs/coding/pack-private --check --zip   # its plugin
ytbrain eval latency --pack data/pack-private      # search p95 as the plugin runs it (gate 1.5 s)
ytbrain eval run --config pack --pack data/packs/coding/pack-private --only-pack-docs   # a Pack on its own questions
ytbrain eval gap --pack data/packs/coding/pack-private --questions data/eval/gap-questions-coding.txt --only-pack-docs
ytbrain eval coach --plugin dist/coding-coach-private   # a Pack's own coach gates (cases in ytbrain/eval/coach_cases/<pack>/)
ytbrain eval choice --plugin dist/plugin-private --plugin dist/coding-coach-private --plugin dist/investor-coach-private   # P12, your Claude plan, no judges
ytbrain eval choice --quick --plugin dist/plugin-private --plugin dist/coding-coach-private --plugin dist/investor-coach-private   # 15 of the 45 prompts, one of every kind
ytbrain pack info                     # counts, models, checksum OK
ytbrain pack build --device coreml    # experimental: Apple GPU/Neural Engine for embedding (default cpu)
ytbrain search "..." --pack           # search the pack with the ONNX runtime path
ytbrain pack build --with-passages --out data/pack-passages       # a variant with transcript Passages (ADR-0009)
ytbrain pack build --embed-model snowflake/snowflake-arctic-embed-m --with-passages --out data/pack-arctic
ytbrain eval run --set dev --config pack-no-rerank --pack data/pack-arctic --label arctic --compare full
```

## Coach runtime (`founder-coach` CLI and MCP server)

```bash
founder-coach warmup                              # download the ONNX query models
founder-coach status                              # pack, models, store integrity, Nudges
founder-coach serve --pack data/pack              # stdio MCP server (the host starts this)
npx @modelcontextprotocol/inspector founder-coach serve --pack data/pack   # try the 9 tools by hand
echo '{}' | founder-coach hook session-start      # prints SessionStart JSON only when something is due
founder-coach export [--out DIR]
founder-coach restore --list ; founder-coach restore            # put back the newest good backup
founder-coach forget [--confirm "<company>"] [--no-backup]
founder-coach forget --all [--confirm "forget all"]   # every Project and the Common profile
founder-coach projects                            # list (* = the one the CLI and the hook use)
investor-coach holdings import positions.csv [--account NAME] [--as-of YYYY-MM-DD]   # the investor Pack only
investor-coach holdings label VTI=us_equity BND=bonds ; investor-coach holdings ; investor-coach holdings review
founder-coach projects create "Kitebook" ; founder-coach projects rename kitebook "Kitebook Inc" ; founder-coach projects use acme
founder-coach feedback list ; founder-coach feedback export [--out DIR]   # the Founder's Feedback, as one file to send
founder-coach usage summary [--days 30] [--json] ; founder-coach usage export [--out DIR]
founder-coach usage clear --yes                  # the local usage log (docs/usage-log.md)
```

Memory commands act on one Project: `--project ID` (or its name), else the only one, else the last used, else
`$FOUNDER_COACH_PROJECT`; with several and none of those, they ask for `--project`. Use `--home /tmp/fc-test` on
any of these to try them on one folder without Projects, without touching your real store.

Settings (`FOUNDER_COACH_*`, listed in `.env.example`) come from the environment, then
`$FOUNDER_COACH_ENV_FILE`, `./.env` and `~/.founder-coach/.env`. Only `FOUNDER_COACH_*` lines are
read, never API keys; `founder-coach status` shows which files were used. Without any file,
nothing changes and every default applies.

## Plugins, skills and hook

```bash
python scripts/assemble_plugin.py --pack data/pack --check [--zip]   # -> dist/plugin; --zip adds the Cowork upload file
claude plugin validate dist/plugin --strict
ytbrain claude -- --plugin-dir dist/plugin      # your Claude plan on Haiku (--openrouter: paid per token)
#   then in the session: /founder-coach:setup, /founder-coach:ask <question>,
#   /founder-coach:weekly-focus, /founder-coach:check-in, /founder-coach:status,
#   /founder-coach:feedback <what was wrong> (after an answer that missed), /founder-coach:export,
#   /founder-coach:forget (test data only)
#   and start a new session to see the SessionStart Nudge when something is due
```

## Evaluating the coach's answers and memory

```bash
# fast, mocked behaviour checks of the skills (no pack, no Founder data)
python scripts/assemble_plugin.py --pack data/pack --with-evals --out dist/plugin-eval
ytbrain claude -- plugin eval dist/plugin-eval --runs 1 --threshold 0.8   # --runs 3 before a release
# `ytbrain claude [--model sonnet] [--openrouter] -- <claude args>` = the local Claude Code on your
# Claude plan with Haiku (--openrouter: through OpenRouter instead, paid per token)
# --ablation none skips the without-plugin comparison runs (half the usage) while iterating

# gates on the real host, server and pack: G2 citation support, G4 sycophancy, G5 multi-week memory,
# G6 decomposition, G7 Project isolation, G8 no security picks (investor). The host is the local Claude Code on
# your Claude plan, token-saving: Haiku, 16 turns per call, no repo context (judges spend a few cents, --max-cost)
python scripts/assemble_plugin.py --pack data/pack --check
ytbrain eval coach --limit 2                      # a quick end-to-end check first
ytbrain eval coach                                # every gate of the plugin's Pack; resumable per plugin build and model
ytbrain eval coach --gate g5                      # one gate (repeatable)
ytbrain eval coach --max-turns 16                 # turns per host call (the default)
ytbrain eval coach --model sonnet                 # sign a release off on the model founders use
ytbrain eval coach --host openrouter              # optional: through OpenRouter, paid per token
ytbrain claude -- --plugin-dir dist/plugin        # a live session with the plugin (your plan, Haiku)
```

Results: `data/eval/coach/<gate>-<build>[-<model>]-<harness>.jsonl` (one line per case, with answers, judge reasons
and the memory checks) and `report-<time>.json`. Don't reassemble `dist/plugin` while `eval coach` runs:
it stops rather than mixing two builds' results.


## Product name, CI and releases

```bash
$EDITOR packs/founder/pack.toml                        # a coach's id, display name, SEO description ([product]); product.toml: shared author, license, repos
python scripts/assemble_plugin.py --pack data/pack     # regenerates founder_coach/product.json and the playbooks
python scripts/check_secrets.py                        # what CI and the pre-commit hook run
python scripts/release.py --pack data/pack --marketplace <your-plugin-repo> --version 0.1.1 [--push]   # optional: publish a build to a plugin repo of your own
```

## Website Sources (ADR-0013)

```bash
uv pip install -e ".[web]" && playwright install chromium   # once; the browser is only for JavaScript sites
# add `- type: website` + `url:` entries to sources.yaml (see sources.example.yaml)
ytbrain sync                          # every enabled Source: playlists and websites
ytbrain sync --source <id> --limit 50 # one Source, at most 50 pages this run (the rest resume next run)
ytbrain sync --type website           # only websites (talks found on them still get their captions)
ytbrain sync --type book              # only PDF Books: one Document per Chapter (then `ytbrain clean`)
ytbrain sync --type youtube           # only YouTube playlists
ytbrain run                           # sync -> clean -> extract -> verify -> index, articles and talks alike
ytbrain invalidate clean --source <id> # re-run one Step for one Source
ytbrain drop --source <id>            # take a Source's Documents out of the knowledge (then `ytbrain index`)
```

## PDF Books (ADR-0014)

```bash
ytbrain books inspect <pdf-or-folder> # refused or not, metadata, chapters found and how (no LLM; parse cached)
ytbrain books inspect data/books --expect data/books/expected.yaml   # exit 1 on any mismatch
ytbrain sync --type book && ytbrain clean
ytbrain extract --doc <ISBN>          # one Book's Chapters (pilot), then plain `ytbrain extract`
ytbrain verify --doc <ISBN> && ytbrain sample --doc <ISBN> --n 10
ytbrain index                         # Books join the index, marked private
ytbrain pack build --include-private --out data/pack-mine   # your own coach only; release refuses it
```

## Parallelism: what runs on threads, and what stays serial

Workers only make the slow call (a model, or a `claude -p` host run). Every database and file write stays on the
calling thread, in completion order, so there is one SQLite writer; Ctrl+C keeps what finished and redoes what was in
flight. Each setting is limited by something different, which is why there are three:

| Setting | Used by | What limits it |
|---|---|---|
| `YTBRAIN_LLM_WORKERS` / `--workers` (default 1) | `extract`, `enrich` | the model provider's rate (`YTBRAIN_LLM_MAX_RPM` per model, shared by every worker; a 429 halves that model's rate, or every model's when it is the account's) |
| `YTBRAIN_EVAL_WORKERS` (default 8) | `eval build` and the judges | the same provider rate |
| `YTBRAIN_COACH_WORKERS` / `--workers` (default 1) | `eval coach` gates, `eval choice` (so `ops plugin --coach`) | **your Claude plan**: each case is a `claude -p` run; raise it from 1 gradually and stop at the first plan-limit message |

`enrich --max-cost` counts a call's cost when it returns and starts no new call after the cap, so a parallel run goes
over by at most the calls in flight. A call with no answer after `3 × YTBRAIN_EVAL_TIMEOUT_S + 60` s is given up on (that Document is recorded as failed and
the next run redoes it). `extract` gives up on a Document that reports no new step for `YTBRAIN_LLM_TIMEOUT_S + 300` s the same way; a slow
Document that keeps reporting steps is never cut off. Left serial on purpose: `verify`, `clean`, `pages`, `refresh` (pure-Python CPU work,
the GIL gives threads nothing), `index`, `pack build` and `eval run` (one shared embedding model and device), web and
YouTube `sync` (politeness limits per host and per IP), PDF book parsing (CPU: a process pool, if it is ever worth it).
