# The pipeline

How Sources become Verified, citable knowledge, Step by Step. The diagram is in
[architecture.md](architecture.md#pipeline-data-flow); every command is in [commands.md](commands.md).

- [Run it](#run-it)
- [Search the knowledge](#search-the-knowledge)
- [What each Step writes](#what-each-step-writes)
- [Parallelism, rate limits and retries](#parallelism-rate-limits-and-retries)
- [Interrupting and resuming](#interrupting-and-resuming)
- [Quality checks](#quality-checks)
- [Output format](#output-format)

## Run it

### First run

```bash
ytbrain sync --limit 5                         # fetch captions for 5 videos per playlist (try it)
ytbrain sync                                   # then everything (long; resumable)
ytbrain clean                                  # captions → transcripts (seconds)
caffeinate -i ytbrain extract --workers 5      # LLM extraction (the long step)
ytbrain verify                                 # check every quote, write the pages
ytbrain report                                 # acceptance numbers
ytbrain sample --n 10                          # review sheet for a human read
```

(`caffeinate -i` is macOS-only and just keeps the machine awake; omit it on Linux.)

Then, with the `index` extra installed:

```bash
caffeinate -i ytbrain index                    # embed Verified knowledge (~1 h on an M2 Air)
ytbrain search "how do I find product-market fit" --stage idea
```

### Every run after that

```bash
caffeinate -i sh -c 'ytbrain run; ytbrain report'
```

`run` = sync → clean → extract → verify → index. Every Step only processes what is new,
changed or previously failed, so a daily run over an unchanged corpus finishes in seconds.

- **Index:** skipped with a note if the optional `index` extra isn't installed.
- **Sync failure:** if sync fails for every source (YouTube throttling your IP), `run` stops
  there and nothing downstream runs.
- **Refused LLM:** if the endpoint refuses the requests (key, credit, quota), `run` still
  verifies what was extracted, then stops and records the run as *failed*.

### Re-extracting without touching YouTube

After a schema bump or a model switch, extraction must be redone. Sync has nothing to do
then, and it could stop the run if YouTube throttles you, so skip it:

```bash
caffeinate -i sh -c 'ytbrain extract && ytbrain verify && ytbrain index; ytbrain report'
```

`extract` returns an error only when the LLM endpoint refuses the requests. Videos that
fail one by one don't break the chain, and `report` runs either way. `index` then re-embeds
only the talks whose records changed.

## From Sources to plugin: the whole flow

```bash
ytbrain ops                                        # all of it, resumable: ingest -> eval -> plugin (docs/ops.md)
# or one step at a time:
ytbrain run                                        # sync -> clean -> extract -> verify -> index
ytbrain report && ytbrain sample --n 10            # quality gates + a human read
ytbrain pack build                                 # the Knowledge pack (data/pack)
python scripts/assemble_plugin.py --pack data/pack --check    # -> dist/plugin
ytbrain eval coach --limit 2 && ytbrain eval coach # the gates (your Claude plan, Haiku)
ytbrain claude -- --plugin-dir dist/plugin         # a live session: /founder-coach:setup
```

## Search the knowledge

```bash
uv pip install -e ".[index]"          # LanceDB + sentence-transformers + PyTorch (MPS on Apple silicon)
python -c "import torch; print(torch.backends.mps.is_available())"   # True on Apple silicon
ytbrain index --limit 5               # try it; first run downloads the embedding model (~2.3 GB)
ytbrain index                         # the rest; resumable, re-embeds only changed talks
ytbrain search "how should I price a B2B pilot" --stage mvp
ytbrain search "cofounder conflict" --kind advice --device cpu --no-rerank
```

What gets indexed are **Knowledge items**, and only Verified ones:

| Kind | One item per | Why |
|---|---|---|
| `advice` | advice atom with a verified quote | the coach's main currency |
| `takeaway` | verified highlight | broader lessons |
| `summary` | talk | "which talk covers X" |
| `passage` | ~550-token (2–3 min) transcript window, slightly overlapping | anything the extraction missed |

Each item is embedded together with a short header (talk title, speaker, series) and its quote.
Every result links to the exact second in the video.

How `search` ranks results:

1. **Candidates.** It takes the top 50 from vector search and the top 50 from full-text
   search, and merges them (reciprocal-rank fusion).
2. **Rerank.** The cross-encoder re-scores the merged list.
3. **Boosts.** Small boosts apply for a matching `--stage` (Stage ranks results, it never
   filters them, unless you add `--require-stage`), for the kind of item (advice first),
   and for recent talks.
4. **Diversity.** At most 3 results come from one talk, and only one per quote (an advice
   item and a takeaway often cite the same sentence).

- **First `search`:** downloads the reranker (~2.3 GB) once; `--no-rerank` skips it.
- **`--json`:** prints results for scripts and agents.
- **Longer items:** a note is printed if an item may exceed the 1024-token embedding window.
  On the YC corpus none do; the longest passage is ~870 tokens.

## What each Step writes

| Stage | Output |
|---|---|
| sync | `data/raw/<id>.info.json`, `data/raw/<id>.<track>.srt` (one track: `en-orig` or a human `en*`) |
| clean | `data/transcripts/<id>.json` |
| extract | `data/metadata/<id>.json` |
| extract (failures) | `data/reports/extract-failures/<id>.json` — the call log of a video extract gave up on; removed once it succeeds |
| verify | updates `data/metadata/<id>.json` (match scores, timestamps) and writes `data/pages/<id>.md` |
| index | `data/lancedb/` — one `knowledge` table of Knowledge items with vectors and a full-text index |
| pack build | `data/pack/knowledge.sqlite` + `pack.json` (sha256, models, corpus stats) + `embed-cache.db` |
| all | `data/manifest.db` — SQLite: one row per video, per-stage status, run history |

Progress at any time:

```bash
sqlite3 data/manifest.db "SELECT stage, status, COUNT(*) FROM stage_state GROUP BY 1,2;"
```

## Parallelism, rate limits and retries

### extract

- `--workers N` (or `YTBRAIN_LLM_WORKERS`) runs N LLM calls in parallel. Results are still
  saved one at a time, so resume works exactly as with one worker. With several workers a
  video's line prints when it finishes, and a *still working on …* line appears if nothing
  finishes for 60 s.
- **Rate pacing only for hosted endpoints** (anything not `localhost`/`127.*`/`*.local`/Ollama):
  all workers share one budget of `YTBRAIN_LLM_MAX_RPM` requests/min per model (default 30;
  18 for OpenRouter `:free` models). A 429 that names an upstream provider ("qwen/x is
  temporarily rate-limited upstream") belongs to that model: only its calls pause and slow
  down (the working rate halves, then climbs back after quiet minutes), so a throttled judge
  doesn't hold the others back. Any other 429 is the account's limit and slows every model.
- **Per request**, exponential backoff with jitter (10, 20, 40, 80, 160 s; the server's
  `Retry-After` wins) for: 429 and 5xx, dropped connections, and HTTP 200 responses that
  carry an error or no content. A timed-out request (default 900 s) is retried once.
- **Per video**, if a video still fails it is retried twice more (30 s, 60 s).
  If the model cannot produce valid JSON even after two repair prompts, the video is marked
  failed and not retried in that run (same prompt, same answer).
- **Per answer** (schema 2.2.0), a few retries target specific problems:
  - A reply cut off at the token cap is asked again with a "be concise" instruction instead
    of being repaired. On OpenRouter the retry skips the provider that produced it. In
    practice these were providers looping on one value, not long answers. A cut-off reply
    that is already complete JSON is simply kept.
  - A repair prompt includes the whole previous answer and the transcript.
  - If fewer than 90 % of quotes are found in the transcript, or a talk of 1 000+ words
    yields no advice, the video is retried once with that feedback, and the better attempt
    is kept.
  - Transcripts over `YTBRAIN_SINGLE_CALL_MAX_TOKENS` are split into a few ~8k-token
    windows, plus one overview call for title, speaker, category and
    summary.
- Every LLM call (kind, tokens, seconds, outcome) is logged in the record's
  `extraction_meta.calls`.
- **Stops the run** (without marking anything failed) on a bad key or model
  (401/403/404/410), no credit (402) or an exhausted daily quota.

### sync (YouTube)

- ytbrain is anonymous; YouTube allows guests roughly 300 videos / ~1 000 requests per
  hour per IP (yt-dlp wiki). `sleep_requests: 5` keeps you under that.
- **Two kinds of pause:**
  - `sleep_requests` (in `sources.yaml`, default 5 s) is yt-dlp's pause between *every*
    request: the watch page, player API calls and each caption file. A video needs about
    5–8 requests, so this caps you at roughly 720 requests an hour, under the guest
    limit of about 1 000.
  - The subtitle pause (`YTBRAIN_YT_SLEEP_SUBTITLES`, default 10 s; `--sleep-subtitles`)
    is an extra wait before the caption file. A talk has one (see below).
- **`ytbrain sync --backfill`** retries only videos whose caption fetch failed for a
  reason a retry can fix, such as HTTP 429.
  - It doesn't list playlists, pauses 15 s before each subtitle file, and paces itself
    to 60 videos an hour (`--per-hour N`).
  - Leave it running (`caffeinate -i ytbrain sync --backfill`). It stops on its own if
    YouTube keeps refusing.
- yt-dlp itself retries 5xx and connection errors, with exponential sleeps configured by
  ytbrain (`--retry-sleep http:exp=2:60`, `extractor:exp=5:120`).
- **The first HTTP 429 stops YouTube for the run.** It means YouTube is throttling this IP, and
  every further request (a retry, the next video) only extends that. The video stays *failed*
  and is fetched by a later run. Other transient errors retry the same video after 10 s and
  20 s (up to `YTBRAIN_YT_VIDEO_RETRIES`, default 2).
- **The YouTube pause:** after a 429, later syncs (and `ytbrain ops`) skip YouTube for 24 h
  (`YTBRAIN_YT_PAUSE_HOURS`; `0` turns it off), doubling if the first run after a pause gets
  another 429, up to 7 days. Websites and Books still sync, and the ops summary says when
  YouTube is tried again. A run that fetches captions without a 429 lifts it.
  `ytbrain sync --ignore-pause` (or `--backfill`) tries now. The state is
  `data/ops/youtube-pause.json`.
- Private, removed and members-only videos are recorded as *unavailable* and never
  retried; videos without English captions as *no captions*.
- Playlist listing is retried after 30 s and 60 s.

#### Caption tracks

Sync reads a talk's `info.json` first (no subtitle request), picks one track, then downloads
only that one from the saved info (`yt-dlp --load-info-json`, no second page fetch):

1. a human English track (`en` first, then `en-US`, `en-GB` …);
2. else the auto `en-orig`: the speech as YouTube recognised it. It exists only when the audio
   is English (a French talk has `fr-orig`), so ytbrain needs no language field or detector;
3. else nothing: the talk is recorded as *no captions*, with no subtitle request made.

ytbrain never asks for the plain auto `en` track. YouTube makes it with its translation
endpoint, even from English speech: that request is the one it throttles (yt-dlp
issue #13831), and on 20 of our 740 talks it rewrote what the speaker said ("the best tool that
you've got" became "the best tool you have"). The uploader's `language` field isn't used: it
was missing on 20 English talks and wrong on 2. If the saved info can't be loaded (say, after
a yt-dlp update), the track is fetched once more with a single full call; a 429 is never
retried. `sub_langs` and `sub_format` in `sources.yaml` are no longer read.

Talks fetched before 2026-10-13 were cleaned from whichever file the old rule picked.
`ytbrain reselect-captions --dry-run` lists the ones whose file the rule now changes, from
files already on disk (no YouTube request); without `--dry-run` it sends them back to clean,
and the next `ytbrain ops` re-extracts only those whose transcript changed.
- **Proxy (optional):** `YTBRAIN_YTDLP_PROXY` is passed to yt-dlp's `--proxy`, for
  example behind a company network. ytbrain adds no IP rotation of its own. Rotating IPs
  to get around YouTube's rate limits is circumvention, which YouTube's terms prohibit.
  Slower pacing and `--backfill` are the supported answer.

## Interrupting and resuming

Stop any command at any time — **Ctrl+C**, closing the terminal, `kill`, a launchd stop,
even a crash or power loss — and run the same command again. It continues where it stopped.

- A video is marked done only **after** its output file is complete. The one in flight
  was never marked, so it is simply redone.
- Every file is written to a temporary name and renamed (yt-dlp does the same), so no
  output is ever half-written. Leftover temp files are cleaned up on the next run.
- A single run at a time is enforced with an OS file lock (`flock`) on `data/ytbrain.lock`.
  The operating system releases it the moment the holding process exits, even on `kill -9` or a
  crash, so a dead run can never block the next one (a reused PID can't fool it either).
- Damaged or missing inputs are **sent back to the stage that produces them, never
  silently skipped**: a missing caption file goes back to `sync`, a corrupt transcript to
  `clean`, a corrupt record to `extract`.
- `report` counts only current records; files left by an interrupted re-extraction are
  shown as *outdated on disk* and excluded.
- `index` checkpoints per talk. An interrupted index run leaves every finished talk in
  place and redoes the one in flight. A talk is re-embedded when its record or transcript
  changes, or when the embedding model changes.

---

## Quality checks

- **`verify`** fuzzy-matches every evidence quote and derives the timestamp from the
  transcript; the model never emits timestamps. A quote passes if either test holds:
  - word-level Jaccard ≥ 0.70 against a quote-sized window, ignoring "um/uh";
  - ≥ 90 % of its words (at least 8 distinct ones) appear within a window up to 1.5× its
    length. This accepts quotes the model tidied (dropped "like", "you know", repeated
    words) while still rejecting invented words and repetition loops.

  Each part of a `...`-joined quote is checked separately.
- **Empty records are flagged, not passed.** A talk of 1 000+ words that yields no items,
  or a practical (non-story, non-trends) talk that yields no advice, is marked *flagged*
  with the reason, so `invalidate extract --only-flagged` picks it up.
- **Pages withhold unverified claims.** A takeaway or advice item whose quote is not in
  the transcript is left out of `data/pages/*.md` (kept in the JSON with its score); the
  page says how many were withheld (`withheld_unverified` in the front matter).
  Typical cause: the model "remembers" a famous quote shown on a slide but never spoken.
- **`report`** gates: record rate ≥ 90 % (captioned videos with a record) and evidence
  pass rate ≥ 90 %. It also lists:
  - why videos have no transcript: private, no English captions, or rate-limited and due
    for another `sync`;
  - every flagged record with its reason;
  - every failed extraction, with a call log under `data/reports/extract-failures/`
    (each LLM call's finish reason, token usage including hidden reasoning tokens,
    provider, seconds, and the start and end of any answer that failed).
- **`sample --n 10`** writes a stratified review sheet (unverified claims included and
  flagged) — read it against the videos and confirm nothing is fabricated.
- **Redo weak records** with a stronger model:

```bash
ytbrain invalidate extract --only-flagged
YTBRAIN_LLM_MODEL=<stronger-model> ytbrain extract && ytbrain verify && ytbrain report
```

- **Re-check only** (after a verifier change, no LLM cost): `ytbrain invalidate verify && ytbrain verify`.

---

## Output format

Each video gets `data/metadata/<video_id>.json` (canonical) and `data/pages/<video_id>.md`
(readable projection, regenerated — don't edit by hand). A record contains:

- `title_canonical`, `speaker`, `summary` (~150 words)
- `category` — exactly one of: `ideation-problem-selection`, `customer-discovery`,
  `product-mvp`, `product-market-fit`, `growth-distribution`, `marketing-gtm`, `sales`,
  `fundraising`, `finance-metrics`, `hiring-team`, `cofounder-dynamics`, `legal-equity`,
  `operations-execution`, `founder-psychology`, `ai-and-tech-trends`, `founder-story`, `other`
- `stage_relevance` — any of `pre-idea`, `idea`, `mvp`, `pmf`, `growth`, `fundraising`,
  `scaling`, `exit`
- `highlights` and `advice_atoms`, each with `evidence_span`, `timestamp_ms`, `match_score`
- `entities` (people, companies, frameworks, books, YC jargon), `unknowns_and_gaps`
- `chapters` (uploader's when present, otherwise LLM-generated and snapped to real timestamps)
- `extraction_meta`: model, backend, schema version, prompt hash, verification result

To change the category list: edit `Category` in `ytbrain/extract/schema.py`, bump
`SCHEMA_VERSION` in `ytbrain/config.py` and add a release in `ytbrain/extract/versions.py`
([ADR-0018](adr/0018-extraction-is-versioned-per-prompt-and-old-records-stay-compatible.md)): a
**compatible** release keeps older records (the next `extract` leaves them be; `ytbrain upgrade --dry-run`
shows what re-extracting them would cost), a **breaking** one makes the next `extract` redo them.
