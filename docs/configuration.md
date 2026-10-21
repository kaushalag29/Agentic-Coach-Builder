# Configuration

- [Sources (`sources.yaml`)](#sources-sourcesyaml)
- [Domains and tagging](#domains-and-tagging)
- [Choosing and switching models](#choosing-and-switching-models)
- [Environment variables](#environment-variables)
- [Scheduling (macOS launchd)](#scheduling-macos-launchd)

## Sources (`sources.yaml`)

`sources.yaml` lists the Sources to ingest: YouTube playlists and websites (next section). It
is git-ignored (your list stays private);
start from `cp sources.example.yaml sources.yaml`, then build it interactively with
`discover` or edit it by hand. `discover` creates it if it doesn't exist.

### Discover playlists with yt-dlp (no API key)

```bash
ytbrain discover --method ytdlp --channel @ycombinator      # a channel: lists its playlists
ytbrain discover --method ytdlp --channel PLxxxxxxxxxxxx     # a single playlist id or URL
```

For a channel it lists every playlist on the `/playlists` tab; you choose which to keep
(`1,3,5-9`, `all`, or blank), name them, optionally add the channel's **uploads
catch-all** (`UU…`), and add extra playlists from other channels as
`Series Name|PLxxxx`. Re-running `discover` merges into the existing file without
creating duplicates.

`ytbrain discover --method api` instead prints YouTube Data API v3 calls for you to run
with your own key.

### Format

```yaml
defaults:                      # applied to every source unless the source overrides it
  sleep_requests: 5            # seconds between yt-dlp requests; 5+ avoids most YouTube 429s
sources:
- id: startup_school_2026      # stable slug, unique
  name: Startup School 2026
  kind: playlist
  playlist_id: PLxxxxxxxxxxxx  # must be a PLAYLIST id (PL…/UU…), never a channel id (UC…)
  fallback: false
  verify: false
- id: yc_uploads
  name: YC uploads (catch-all)
  kind: playlist
  playlist_id: UUxxxxxxxxxxxx  # the channel's uploads playlist
  fallback: true               # catch-all: never overrides a video's specific series
  verify: false
```

A video that appears in both a specific playlist and the catch-all keeps the specific
playlist's series. Put `enabled: false` on a source to skip it.

### Websites

Any website can be a Source: give the URL, and optionally how far to follow links and whether
to use a browser. Nothing about the site's structure is configured; each page says what it is.

```yaml
- type: website
  url: https://paulgraham.com/articles.html
  depth: 1          # link hops from the start page (default 3)
  render: auto      # auto: a headless browser only when a page's text comes back thin | always | never
  enabled: true     # false: stop fetching (Documents stay until `ytbrain drop --source ID`)
  author: Paul Graham   # optional: the speaker when pages name no author
  id: paulgraham    # optional; default: the host + a short hash of the URL (used by --source)
  name: PG essays   # optional: the Series (default: the host)
  max_pages: 10000  # pages fetched per run (default 10 000)
```

```bash
uv pip install -e ".[web]"       # trafilatura (main text) + Playwright
playwright install chromium      # once, only needed for JavaScript sites
ytbrain sync                     # playlists and websites; then clean/extract/verify/index as usual
ytbrain sync --type website      # websites only (talks embedded on them still get their captions)
ytbrain sync --source ID --limit 20   # one Source, a small batch first
```

Point `url` at the page that lists what you want (an archive or index page) and keep `depth`
small; a trailing slash matters (`…/blog/` keeps the crawl inside `/blog/`, `…/blog` doesn't).

How a site is read (design: [ADR-0013](adr/0013-sources-plug-in-through-adapters.md)):

- **Politely:** robots.txt obeyed (unreachable robots.txt means nothing is fetched that run), one
  request per second per host or the site's `Crawl-delay`, retries with backoff that honour
  `Retry-After`, an honest User-Agent, a 15 MB page limit, never logs in, no IP rotation, no
  browser-fingerprint tricks, no CAPTCHA solving.
- **Scope:** the start URL's host and directory; sitemaps seed the queue; `depth` link hops.
- **Each page** is typed from what it declares (schema.org JSON-LD, OpenGraph, meta tags,
  `rel=canonical`, `lang`) and its main text (trafilatura): an **article** becomes a Document
  (title, author as Speaker, date, site as provenance, paragraphs with their headings);
  a **listing** only contributes links; a page embedding a **YouTube talk** hands the video to
  YouTube sync (if YouTube has no captions for it, the page's own transcript is kept as an
  article); non-English pages are skipped for now.
- **Identity:** a page's id is a hash of its canonical URL (`w-` + 16 hex; the full hash is kept
  and a clash is refused, never merged). The same text at a new URL, even on a new domain, is
  the same Document: no second extraction.
- **Incremental and resumable:** the crawl queue lives in `data/manifest.db`, so an interrupted
  crawl continues; known pages are re-checked after 7 days (leaf pages at the Source's `depth`
  with a conditional GET, pages whose links are followed in full), and only a
  changed text goes through clean and extract again; a page that answers 404/410 leaves the
  index at the next `index`.
- **Same pipeline after `clean`:** articles are extracted with an article-worded prompt into the
  same record as talks, verified against their paragraphs, and cited as
  "Author, Title, year" linked to the page with a text fragment that opens at the quoted words
  (`https://…/essay.html#:~:text=…`), and shown as `¶4` in pages instead of `mm:ss`.

---

### Books (PDF)

Books are the third Source type ([ADR-0014](adr/0014-books-are-private-chapters-parsed-with-docling.md)): one PDF per Book, one Document per Chapter, text only, parsed with PDFium (no
model, no download, about a second per book). Use copies you own. Books are a **Private Source**: indexed
for your own use and never shipped in the Knowledge pack (`distribute: false`, the only value in v1).

PDF fonts that lost their ligatures ("di@erent", "signi%cant") and hyphens stored as control characters are
repaired when a Book is parsed, only where the result is a real word (`ytbrain/books/ligatures.py`); `books inspect`
reports what it repaired and what it could not.

```bash
uv pip install -e ".[pdf]"                       # pypdfium2 only
ytbrain books inspect data/books/startup/ data/books/leadership/   # check first (no LLM)
ytbrain sync --type book && ytbrain clean        # register one Document per Chapter, write their transcripts
ytbrain extract --doc 9780000001016              # one Book first (its ISBN picks its Chapters); then all
ytbrain verify --doc 9780000001016 && ytbrain sample --doc 9780000001016 --n 10
ytbrain index                                    # Books become searchable in `ytbrain search`
```

Add the folder to `sources.yaml` (template in `sources.example.yaml`) and correct only what `inspect` gets
wrong, per file: `title`, `subtitle`, `authors`, `year`, `isbn`, `url`, or a `chapters:` fix.

- **Refused:** encrypted, scanned (no text layer) and garbled text layers; there is no OCR. A few garbled lines
  are dropped and reported.
- **Metadata** (never from the LLM): `sources.yaml`, then the copyright page (the ebook ISBN, the year of the
  book's own copyright line), then the PDF's metadata (title and subtitle, authors), then Open Library by ISBN
  if the Source says `lookup: openlibrary`. Missing or suspect fields are flagged, e.g. a person on the
  copyright line who isn't among the authors.
- **Chapters:** the first plausible of a `chapters_only` list, the bookmarks (Parts opened into their chapters),
  the printed contents page, headings, then 15-page windows; front and back matter skipped.
- **One file per Book:** two PDFs with the same id (two editions, a copy, two untitled books) would overwrite each other's
  Chapters, so the second is refused (`same book id`): keep one, or `skip: true` for the other under `books:`.
- **Ids:** `<ISBN-13>__<chapter-title>`, so a re-split or a renamed file keeps them. An unchanged Chapter is
  never cleaned again; a book removed from the folder leaves the index; a PDF that fails to parse keeps what it had.
- **Check your books:** keep the expected title, authors, year, ISBN and chapters in a local YAML and run
  `ytbrain books inspect data/books --expect data/books/expected.yaml` (exit 1 on any mismatch).
- **Extraction** uses the chapter prompt: the Book and its authors are given (never generated), and the
  authors' own advice is kept, not the lines they quote from others. A Chapter's headings are its Sections.
- **Citations** name the page: `p. 47` when the PDF has printed page numbers, else `PDF p. 47`, with no link
  (your copy is private). The coach cites book, chapter, year and page.
- **Private:** book items are marked private in the index. `ytbrain pack build` leaves them out;
  `--include-private` keeps them for your own coach, and `scripts/release.py` refuses such a pack. The released
  eval never seeds from or labels them.
- **Ranking and evals:** Chapters compete with Talks and Articles under the same rules (nothing is Book-only). Your private
  Books get their own question set (`dev-private`), graded and scored but never released.
  Docling (`pdf-docling` extra) is parked.

## Domains and tagging

`domains.yaml` (committed) declares the **Domains** of the Library: `startup`, `gtm` (sales, marketing, positioning,
pricing, launches), `leadership`, `system-design`, `finance`, `investment`, `coding`, each with a description, example questions, a risk tier, a freshness
half-life, a web policy and `aliases` (other names: `go-to-market` and `sales` are `gtm`).

**Domains are tagged by content** ([ADR-0017](adr/0017-domains-are-inferred-against-a-controlled-domain-list.md)):
`ytbrain tag` scores every Passage and item against each Domain's description, examples and aliases (the vectors are
already in the index), lets a cheap model decide only close calls between two Domains (cached, temperature 0), and
gives a Document every Domain that covers at least a fifth of its Passages, so one talk can be `leadership` and `gtm`.
Nothing is re-extracted or re-embedded. A Source's `domains: [...]`, a Book's folder (`data/books/leadership/…`, any
case or spacing, or an alias) and `books: {"X.pdf": {domains: [...]}}` are **hints**: they break ties and confirm a
high-tier tag. A folder that is no Domain name is only noted by `sync`; its Books are tagged by what they say.

A Source needs no `domains:` line: the content decides, and every new Source, talk, page or Book reaches the coaches
whose Packs list its Domains with no configuration. A new coach is a Pack (`packs/<id>/pack.toml`) plus its Domain in
`domains.yaml`; the next `ytbrain ops` run retags the Library against the new list (cached, so only close calls cost).

High-tier Domains (`finance`, `investment`) are held to a higher bar. Under the default policy (`YTBRAIN_TAG_POLICY=auto`)
one is applied from the content when it covers at least half of a Document's tagged Passages (`YTBRAIN_TAG_AUTO_SHARE`;
Passages that fit no Domain don't count), counting only decided tags, never an unresolved close call, and at least two
of them; anything weaker stays *suggested* and out of every pack. A Document about nothing else is *unplaced* meanwhile:
no coach gets it (never the default Domain's coach) until `ytbrain domains review --accept SOURCE:DOMAIN` confirms it.
`ytbrain domains review` lists the tags applied this way by Source (`ytbrain domains why <doc>` marks them per Document),
and `ytbrain domains review --reject SOURCE:DOMAIN` removes one
for good (a rejection always wins, and so does your yes). Under `reviewed`, every high-tier tag waits for your yes
(`ytbrain domains review`, a whole Source at once) and never reaches a pack before. A new Domain is proposed, never
created (`ytbrain domains propose` groups content no Domain fits and checks each proposal against the list: spelling,
aliases, meaning, and the model's same/narrower/new), and its risk tier is asked
(`ytbrain domains add legal --risk high --description "Law for founders"`, `ytbrain domains alias gtm "growth"`).
`ytbrain domains why <doc>` shows where a Document's Domains came from.

`ytbrain ops` runs `tag --gated`. With `auto` (the default) it applies the tags every run, so ingestion is fully
automatic; a labelled set is optional and, when you have one, only reported on. With `reviewed` the tags reach the index
only once the tagger passes its gate on your labels: `ytbrain domains sample` (sheets of 100 items and 30 Documents),
fill the `label` column, `ytbrain eval tags --items … --documents …` (precision >= 90 %, recall >= 85 %, no high-tier
label missed; `--tune --save` picks the thresholds); until then a run keeps the tags already applied. A bad value in
either setting stops the tag Step with the reason and changes nothing. A Document may belong to several Domains, and
`coach_search` takes several (`domains: ["startup", "leadership"]`), but since 0.1.7 the coach leaves them out and
searches the whole Library unless you restrict it ("only my finance books"): even a perfectly chosen Domain filter ranked
worse offline (`ytbrain eval run --config pack-oracle-domains --compare pack-no-rerank`). An automatic router exists
but is off; measure it on your corpus with `ytbrain eval route` and `ytbrain eval run --config pack-route --compare
pack-no-rerank` before `ytbrain pack build --route`. Adding a Domain is one entry in `domains.yaml` and its books or Sources.

**Coverage.** Every `coach_search` answer says `coverage`: `strong` (answer with Citations), `partial` (answer what is
covered and say what is not) or `none` (state a Gap; the coach goes to the web only when the Domain's `web_policy`
allows it). Thresholds follow the Domain's `risk_tier`, and `coverage_basis` says whether the curve behind them is
`calibrated` on your labels or `provisional`. To calibrate: build the benchmark and judge it (`ytbrain ops eval`), then
`ytbrain eval calibrate --pack data/pack-private`, rebuild the pack, and check `ytbrain eval gap --pack data/pack-private`
(add your own out-of-corpus questions to `data/eval/gap-questions.txt`, one per line, or `question | domain` for one that
is a Gap only while that Domain is empty; `--tune` saves the best border). `ytbrain ops` prints this report for the
shipped pack on every plugin build but never stops on it.

## Choosing and switching models

1. `python ops/probe_models.py <model-a> <model-b>` — which models answer, with valid JSON, how fast.
2. Try each on the same 5 videos (extract always processes the newest videos first):

```bash
ytbrain invalidate extract --reason "try model A"
YTBRAIN_LLM_MODEL=<model-a> ytbrain extract --limit 5 && ytbrain verify && ytbrain report
```

3. Pick on evidence pass rate, category/people quality in `data/pages/`, speed and cost.
4. **Use one model for the whole corpus.** Every record stores its model and prompt hash;
   mixed models make the quality numbers uninterpretable. To switch after a full run:
   `ytbrain invalidate extract` then `ytbrain extract`.

## Keep your data outside the checkout

The code, `packs/` and `eval/` stay in the repo; everything that is yours can live in a separate folder (a private
workspace): `data/`, `sources.yaml` and the list of private terms. Point the checkout at it in the repo's `.env`:

```bash
export YTBRAIN_DATA="$HOME/coach-workspace/data"
export YTBRAIN_SOURCES_FILE="$HOME/coach-workspace/sources.yaml"
export YTBRAIN_PRIVATE_TERMS="$HOME/coach-workspace/private-terms.txt"
```

Existing data is read in place: nothing is fetched or extracted again. Built plugins still go to the repo's `dist/`
(git-ignored) unless `YTBRAIN_DIST` says otherwise. Before you push, the private-terms check
(`python scripts/check_private_terms.py`, also in `scripts/check.sh`) refuses any tracked or new file, file name or
unpushed commit message that holds a term from your list; install it as a git hook once with
`ln -s ../../scripts/hooks/pre-push .git/hooks/pre-push`.

## Environment variables

All settings are environment variables (`.env` or shell). Defaults in parentheses.

| Variable | Purpose |
|---|---|
| `YTBRAIN_DATA` (`data/` in the repo) | Your pipeline data: manifest, transcripts, index, tags, eval runs, built packs. See [Keep your data outside the checkout](#keep-your-data-outside-the-checkout) |
| `YTBRAIN_SOURCES_FILE` (`sources.yaml` in the repo) | Your Sources. A relative path in it (a `pdf_books` folder) is relative to the folder this file is in |
| `YTBRAIN_DOMAINS_FILE` (`domains.yaml` in the repo) | The controlled Domain list |
| `YTBRAIN_DIST` (`dist/` in the repo) | Where `ytbrain ops plugin` and `scripts/assemble_plugin.py` put built plugins |
| `YTBRAIN_PRIVATE_TERMS` (none) | A text file outside the repo, one term per line (company, book titles, ISBNs, local paths): `scripts/check.sh` and the pre-push hook refuse files or commit messages that hold one |
| `YTBRAIN_ROOT` (repo dir) | Older: moves `data/` and the `eval/` benchmark files together; prefer `YTBRAIN_DATA` |
| `YTBRAIN_LLM_BACKEND` (`ollama`) | `ollama` or `openai` (any OpenAI-compatible API) |
| `YTBRAIN_LLM_BASE_URL` (`http://localhost:11434`) | Endpoint base URL |
| `YTBRAIN_LLM_API_KEY` (none) | API key for hosted providers |
| `YTBRAIN_LLM_MODEL` (`qwen3:30b-a3b`) | Model id |
| `YTBRAIN_LLM_JSON_MODE` (`response_format`) | `response_format` (JSON schema), `json_object`, or legacy `nvext` |
| `YTBRAIN_LLM_EXTRA_BODY` (none) | JSON merged into every request, e.g. provider routing or thinking switches |
| `YTBRAIN_LLM_WORKERS` (1) | Default for `--workers` of `extract` and `enrich` |
| `YTBRAIN_COACH_WORKERS` (1) | Default for `--workers` of `eval coach` and `eval choice`: host runs at a time on your Claude plan |
| `YTBRAIN_LLM_MAX_RPM` (30; 18 for `:free`) | Requests/min cap per model for hosted endpoints, shared by every worker |
| `YTBRAIN_LLM_MAX_TOKENS` (8192) | Output token cap per request |
| `YTBRAIN_LLM_NUM_CTX` (32768) | Ollama context window |
| `YTBRAIN_LLM_TIMEOUT_S` (900) | Per-request timeout |
| `YTBRAIN_LLM_MAX_RETRIES` (5) | Per-request retries |
| `YTBRAIN_LLM_PREFLIGHT_S` (20) | Timeout per try of the start-up "model responds?" check |
| `YTBRAIN_SINGLE_CALL_MAX_TOKENS` (20000) | Transcripts larger than this are extracted in ~8k-token windows; raise it (e.g. 60000) for long-context hosted models |
| `YTBRAIN_EXTRACT_VIDEO_RETRIES` (2) | Whole-video retries in extract |
| `YTBRAIN_YT_VIDEO_RETRIES` (2) | Same-video retries in sync, for errors other than HTTP 429 |
| `YTBRAIN_YT_PAUSE_HOURS` (24) | After an HTTP 429, how long later runs leave YouTube alone (doubles after a pause, up to 168; `0` = off) |
| `YTBRAIN_YT_SLEEP_SUBTITLES` (10) | Seconds yt-dlp waits before the subtitle file (`--backfill` uses at least 15) |
| `YTBRAIN_YTDLP_PROXY` (none) | Passed to yt-dlp `--proxy`; credentials are never printed |
| `YTBRAIN_POT_PROVIDER_URL` (`http://127.0.0.1:4416`) | Where the optional bgutil PO-token server listens |
| `YTBRAIN_POT_SCRIPT_HOME` (`~/bgutil-ytdlp-pot-provider/server`) | bgutil checkout for script mode (no server) |
| `YTBRAIN_EVAL_GENERATOR` (`YTBRAIN_LLM_MODEL`, else `deepseek/deepseek-v4-flash`) | Writes the eval questions |
| `YTBRAIN_EVAL_JUDGES` (`google/gemma-4-31b-it,qwen/qwen3.8-flash,mistralai/mistral-medium-3.1`) | Two judges and a tie-breaker from other model families; an unlisted model falls back to the cheapest of its family |
| `YTBRAIN_EVAL_WORKERS` (8) · `YTBRAIN_EVAL_MAX_RPM` (60) · `YTBRAIN_EVAL_MAX_COST` (5) · `YTBRAIN_EVAL_TIMEOUT_S` (120) | Eval parallelism, the request-rate ceiling (the working rate halves on 429s and climbs back), the per-split USD spend cap, and how long one eval call may take before it's retried |
| `YTBRAIN_ENRICH_MODEL` (the tag model, else `YTBRAIN_LLM_MODEL`) | The model `enrich` uses for Rules and Facts |
| `YTBRAIN_TAG_POLICY` (`auto`) · `YTBRAIN_TAG_AUTO_SHARE` (`0.5`) | The tag Step: `auto` applies every run with no labelled set and applies `finance`/`investment` on a Document when they cover at least the share of its tagged Passages (two or more); `reviewed` waits for a passing `eval tags` and keeps the tags already applied |
| `YTBRAIN_EMBED_MODEL` (`BAAI/bge-m3`) | Local embedding model for the Knowledge index; changing it rebuilds the index |
| `YTBRAIN_RERANK_MODEL` (`BAAI/bge-reranker-v2-m3`) | Cross-encoder reranker for `search`; `none` disables |
| `YTBRAIN_PACK_EMBED_MODEL` (`BAAI/bge-base-en-v1.5`) · `YTBRAIN_PACK_RERANK_MODEL` (`none`) | ONNX models for `pack build` (fastembed names); the pack records them, so its searches always use the same ones |
| `YTBRAIN_HOME` (`~/.ytbrain`) | The engine home: every coach's Projects (`<pack>/projects/<id>/`), the Common profile `you.db` and the downloaded ONNX models |
| `FOUNDER_COACH_HOME` (unset) · `FOUNDER_COACH_MODELS` (`~/.ytbrain/models`) | Pin one coach's data to a single folder with no Projects; where its ONNX models go. The other `FOUNDER_COACH_*` settings are in [coaches.md](coaches.md#the-runtime-founder-coach) |
| `YTBRAIN_COACH_MODEL` (`claude-haiku-5-5`) | Default host model for `eval coach` and `ytbrain claude` |
| `YTBRAIN_COACH_HOST_KEY` (none) | OpenRouter key for `--host openrouter` / `--openrouter`; falls back to `YTBRAIN_LLM_API_KEY` when `YTBRAIN_LLM_BASE_URL` is OpenRouter |
| `YTBRAIN_BOOK_TIMEOUT_S` (`1800`) · `YTBRAIN_BOOK_THREADS` (`0` = all cores but one, max 8) | Parked Docling parser only: one book's parse timeout (a timeout fails the book, never half of it); its threads |
| `YTBRAIN_WEB_CONTACT` (this repo's URL) · `YTBRAIN_WEB_USER_AGENT` (`ytbrain/0.1 (+<contact>; polite research crawler)`) | The crawler's honest User-Agent; set your own contact before crawling |
| `YTBRAIN_DOTENV` (on) | `0` skips loading `.env` (the tests set it) |
| `YTBRAIN_DEVICE` (`auto`) | PyTorch device: `auto` (mps > cuda > cpu), `mps`, `cpu`, `cuda`; an unavailable explicit device is an error, not a silent fallback |

Tunables without an environment variable (thresholds, backoff bases, minimum transcript
length) are documented in `ytbrain/config.py`.

## Scheduling (macOS launchd)

`ops/com.ytbrain.sync.plist` runs `ytbrain run` daily at 03:15. launchd (not cron) runs a
missed job when the Mac wakes. Edit the absolute paths inside, then:

```bash
cp ops/com.ytbrain.sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ytbrain.sync.plist
launchctl list | grep ytbrain
```

`ops/logrotate-run-log.sh` rotates `data/run.log` past 5 MB. `ytbrain report` shows
whether recent runs succeeded (a refused LLM endpoint marks the run *failed*).
