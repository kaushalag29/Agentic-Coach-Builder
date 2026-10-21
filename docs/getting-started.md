# Getting started

From an empty machine to your first coach running in Claude. Commands are for macOS; Linux is the same without
`brew` and `caffeinate`.

- [Requirements](#requirements)
- [Install](#install)
- [Configure an LLM backend](#configure-an-llm-backend-env)
- [Add your Sources](#add-your-sources)
- [Build your first coach](#build-your-first-coach)
- [Install your coach in Claude](#install-your-coach-in-claude)
- [Tested setup](#tested-setup)
- [Responsible use](#responsible-use)

## Requirements

| Need | Why | Check |
|---|---|---|
| macOS or Linux | The full pipeline is tested on macOS (Apple silicon); the test suites also run on Ubuntu in CI. Windows is untested (WSL2 is the likeliest route). | |
| A desktop or laptop | Coaches are local MCP servers that Claude starts on your computer: the Claude apps on iOS and Android can't run them | |
| Python **3.11+** and [uv](https://docs.astral.sh/uv/) | The virtualenv and every dependency (uv can install Python itself) | `uv --version` |
| git | To clone the repo | `git --version` |
| [Deno](https://deno.com) (or Node ≥ 20) | yt-dlp needs a JavaScript runtime for full YouTube support | `deno --version` |
| An LLM endpoint | `extract`, `tag` close calls and `enrich`: a local model (Ollama, LM Studio) or any OpenAI-compatible API (OpenRouter, vLLM, llama.cpp) | [below](#configure-an-llm-backend-env) |
| [Claude Code](https://code.claude.com/docs/en/setup) or Cowork, with a paid Claude plan | Runs your coaches; the coach gates also run on it | `claude --version` |
| Disk | About 5 GB of local models for the index (embedding and reranker, downloaded once), plus your Library: ours, about 1,000 talks, articles and books, is 4.5 GB | |

No ffmpeg, YouTube API key or Google account is needed: captions are fetched anonymously, never video.

## Install

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh          # uv (or: brew install uv)
git clone https://github.com/kaushalag29/Agentic-Coach-Builder.git && cd Agentic-Coach-Builder
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[extract,index,serve,eval,pack,dev,pot,web,pdf]"   # everything
brew install deno                    # JavaScript runtime for yt-dlp
playwright install chromium          # only for JavaScript-heavy websites
cp sources.example.yaml sources.yaml && cp .env.example .env   # both git-ignored
ytbrain --help
```

The extras are independent: `extract` (LLM extraction), `index` (LanceDB, sentence-transformers, PyTorch), `serve` and
`pack` (the coach runtime and its Knowledge pack), `eval`, `web` (websites), `pdf` (PDF Books), `pot` (a YouTube
PO-token plugin), `dev` (tests and lint).

Every new terminal needs `source .venv/bin/activate` before `ytbrain` is on your PATH.

**Keep yt-dlp current.** YouTube changes often and yt-dlp follows within days. If fetching
suddenly breaks, update it first:

```bash
uv pip install -U "yt-dlp[default]"
```

**Give yt-dlp a JavaScript runtime.** Since yt-dlp 2025.11.12, full YouTube support needs
two things: the `yt-dlp-ejs` package, which `yt-dlp[default]` installs, and a JavaScript
runtime on your PATH. Without them yt-dlp falls back to fewer clients and hits more rate
limits. `ytbrain sync` checks this at the start and tells you what is missing.

```bash
brew install deno          # recommended; node >= 20, bun or quickjs also work
```

**Optional: a PO-token provider.** YouTube wants a proof-of-origin token on caption
requests from the web client. The [bgutil provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider)
generates one, and yt-dlp uses it automatically. It is a yt-dlp plugin plus a small local
server:

```bash
uv pip install -e ".[pot]"      # the yt-dlp plugin (or add pot to your other extras); same version as the server

# the provider, pick one:
# (a) Docker
docker run --name bgutil-provider -d --init -p 127.0.0.1:4416:4416 brainicism/bgutil-ytdlp-pot-provider

# (b) no Docker: run the server with Deno (leave this terminal open)
git clone --single-branch --branch 2.0.0 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git ~/bgutil-ytdlp-pot-provider
cd ~/bgutil-ytdlp-pot-provider/server
deno install --allow-scripts=npm:canvas --frozen
cd node_modules && deno run --allow-env --allow-net --allow-ffi=. --allow-read=. ../src/main.ts

# (c) no server: script mode. Keep the checkout from (b) in ~/bgutil-ytdlp-pot-provider
#     (or set YTBRAIN_POT_SCRIPT_HOME); the plugin then runs the provider per token.
```

`sync` reports which provider it found, or warns when the plugin is installed but
neither a server nor a script-mode checkout is there.

**Data location.** Everything ytbrain produces goes to `data/` inside the repo. If the repo
lives in a synced folder (iCloud, Dropbox, OneDrive), point ytbrain at a local folder —
SQLite needs real file locking:

```bash
export YTBRAIN_DATA=~/ytbrain-data/data   # or put it in .env
```

## Configure an LLM backend (`.env`)

`extract`, `enrich`, the `tag` Step's close calls and the eval judges use an LLM. ytbrain reads a **`.env` file in the repo root
automatically** — no need to `source` it. `.env` is git-ignored; never commit API keys.

Precedence: a variable already set in your shell **overrides** `.env` (handy for one-off
runs: `YTBRAIN_LLM_MODEL=other ytbrain extract --limit 3`). When that happens ytbrain
prints a `note:` line so a leftover value can't silently win — open a new terminal or
`unset` it to go back to `.env`.

Start from `cp .env.example .env` (OpenRouter), or pick a template below and fill in the placeholders.

<details open>
<summary><b>OpenRouter</b> — recommended: fast, reliable, under $1 for ~700 videos</summary>

1. Create an account and API key at [openrouter.ai](https://openrouter.ai) and add a few
   dollars of credit. Consider setting a credit limit on the key (e.g. $5).
2. `.env`:

```bash
export YTBRAIN_LLM_BACKEND=openai
export YTBRAIN_LLM_BASE_URL=https://openrouter.ai/api/v1
export YTBRAIN_LLM_API_KEY=sk-or-v1-...your-key...
export YTBRAIN_LLM_MODEL=deepseek/deepseek-v4-flash
export YTBRAIN_LLM_JSON_MODE=response_format
# only use providers that support JSON-schema output; no hidden "thinking"
export YTBRAIN_LLM_EXTRA_BODY='{"provider":{"require_parameters":true},"reasoning":{"enabled":false}}'
export YTBRAIN_LLM_WORKERS=5
export YTBRAIN_LLM_MAX_TOKENS=8192            # per-reply cap; a record is 2-3k tokens
export YTBRAIN_SINGLE_CALL_MAX_TOKENS=60000   # long-context model: whole talk in one call
```

Notes
- Keep `YTBRAIN_LLM_MAX_TOKENS` at 8192, the default. A complete record is 2–3k
  tokens. Replies that hit the cap were a provider looping on one value, e.g. `"idea",
  "idea", ...`, not a long answer. A higher cap only makes each loop take longer: 500 s
  and 16k tokens at 16384. ytbrain retries such a video with a shorter answer and, on
  OpenRouter, on a different provider.
- Paid models have no published per-key rate limit; ytbrain still caps itself at 30
  requests/min per model across all workers (`YTBRAIN_LLM_MAX_RPM`). 5–8 workers is a good range.
- **Free models** (`...:free`) are limited to 20 requests/min and **50 per day** (1 000 per
  day once you have bought ≥ $10 of credit). ytbrain automatically lowers its cap to 18/min
  for `:free` models and stops cleanly when the daily quota is used up.
- Out of credit (HTTP 402) stops the run; nothing is marked failed.

</details>

<details>
<summary><b>LM Studio</b> — local, free, private (tested on M2 Air 16 GB)</summary>

1. Install [LM Studio](https://lmstudio.ai) and download **Gemma 4 E4B** (MLX, 4-bit;
   id `gemma-4-e4b-it`). On 16 GB RAM, models much larger than ~8B will not fit.
2. Load the model with **Context Length 32768** (model loader → advanced settings, or
   `lms load gemma-4-e4b-it --context-length 32768`). The default context is far too small
   for a 10–20k-token transcript.
3. Developer tab → **Start Server** (default `http://localhost:1234/v1`).
4. `.env`:

```bash
export YTBRAIN_LLM_BACKEND=openai
export YTBRAIN_LLM_BASE_URL=http://localhost:1234/v1
export YTBRAIN_LLM_MODEL=gemma-4-e4b-it
export YTBRAIN_LLM_JSON_MODE=response_format
```

Notes
- No API key needed. Local endpoints are never rate-paced.
- `curl http://localhost:1234/v1/models` lists the exact model ids; if yours differs,
  `ytbrain extract` prints the valid ids and stops.
- To use `--workers N`, set **Max Concurrent Predictions ≥ N** in the model's load
  settings, otherwise requests just queue. On a fanless Air the gain is modest.
- Long runs: `caffeinate -i ytbrain extract` keeps the Mac awake; keep it plugged in.

</details>

<details>
<summary><b>Ollama</b> — local, free</summary>

1. Install [Ollama](https://ollama.com), then:

```bash
ollama serve                         # in its own terminal, if not already running
ollama pull qwen3:30b-a3b            # needs ~32 GB RAM; on 16 GB use qwen3:8b
```

2. `.env`:

```bash
export YTBRAIN_LLM_BACKEND=ollama
export YTBRAIN_LLM_BASE_URL=http://localhost:11434
export YTBRAIN_LLM_MODEL=qwen3:30b-a3b          # or qwen3:8b on 16 GB machines
export YTBRAIN_LLM_NUM_CTX=32768                # Ollama silently truncates beyond its default window
```

Notes
- ytbrain checks up front that Ollama is running and the model is pulled.
- JSON output is constrained with Ollama's native `format` (JSON Schema); no
  `YTBRAIN_LLM_JSON_MODE` needed.

</details>

<details>
<summary><b>NVIDIA NIM</b> — free tier (build.nvidia.com); good for experiments</summary>

1. Get an API key (`nvapi-...`) at [build.nvidia.com](https://build.nvidia.com).
2. Find a model that actually answers for your account — the catalog lists models that
   return 404 ("Function not found for account") or queue for minutes on the free tier:

```bash
python ops/probe_models.py                         # tests a list of candidates
python ops/probe_models.py nvidia/nemotron-3.5-lightning-30b-a3b
```

   The script prints the `.env` lines for the best working model.
3. `.env` (the combination that worked for us):

```bash
export YTBRAIN_LLM_BACKEND=openai
export YTBRAIN_LLM_BASE_URL=https://integrate.api.nvidia.com/v1
export YTBRAIN_LLM_API_KEY=nvapi-...your-key...
export YTBRAIN_LLM_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
export YTBRAIN_LLM_JSON_MODE=json_object
export YTBRAIN_LLM_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":false}}'
```

Notes
- NVIDIA's hosted models reject the legacy `nvext.guided_json`; `json_schema` requests
  timed out for Nemotron, `json_object` worked. The schema is still enforced by ytbrain's
  own validation + repair loop.
- Free-tier capacity is shared and unpredictable (see NVIDIA developer-forum threads from
  Sep 2026). Models are retired without much notice (HTTP 410) — ytbrain stops cleanly
  instead of failing every video.

</details>

<details>
<summary><b>Any other OpenAI-compatible API</b> (vLLM, llama.cpp server, Gemini, hosted APIs)</summary>

```bash
export YTBRAIN_LLM_BACKEND=openai
export YTBRAIN_LLM_BASE_URL=https://your-endpoint/v1
export YTBRAIN_LLM_API_KEY=...
export YTBRAIN_LLM_MODEL=...
export YTBRAIN_LLM_JSON_MODE=response_format    # or json_object if json_schema is rejected
# per-model request fields, e.g. switching a model's "thinking" off:
# export YTBRAIN_LLM_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":false}}'
```

Requirements: `POST {base}/chat/completions` and ideally `GET {base}/models`. Test with
`python ops/probe_models.py <model-id>` first.

</details>

**Before a long run, always probe and test on a few videos:**

```bash
python ops/probe_models.py <model-id>                       # expect "valid-json"
ytbrain extract --limit 5 && ytbrain verify && ytbrain report
```

## Add your Sources

`sources.yaml` lists what to ingest: YouTube playlists, websites and folders of PDF Books. Start from the template and
see [configuration.md](configuration.md#sources-sourcesyaml) for every option:

```yaml
sources:
- id: startup_school
  name: Startup School
  kind: playlist
  playlist_id: PLxxxxxxxxxxxx      # a playlist id (PL…/UU…), never a channel id
- type: website
  url: https://paulgraham.com/articles.html
  depth: 1
```

`ytbrain discover --method ytdlp --channel @ycombinator` lists a channel's playlists and writes the ones you pick.
Domains (the subjects your coaches answer from) are declared in `domains.yaml`; content is tagged against them
automatically ([configuration.md](configuration.md#domains-and-tagging)).

## Build your first coach

One command runs the whole loop, resumably, doing only what changed ([ops.md](ops.md)):

```bash
ytbrain ops --dry-run              # what is due, nothing run
ytbrain ops --max-extract 20       # a first, small batch: ingest -> eval -> plugin
ytbrain ops                        # everything; re-run any time
```

The eval step needs an OpenAI-compatible endpoint for its judges (OpenRouter is the tested one); with a local model
only, go step by step instead:

```bash
ytbrain run                        # sync -> clean -> extract -> verify -> index
ytbrain tag                        # Domains by content
ytbrain pack build                 # the Knowledge pack (data/pack)
python scripts/assemble_plugin.py --pack data/pack --check --zip   # -> dist/plugin and dist/founder-coach-<version>.plugin
```

The founder coach builds into `dist/plugin`, and into `dist/plugin-private` when you have a private Source (Books).
The coding and investor coaches are private builds: `ytbrain ops` makes `dist/coding-coach-private` and
`dist/investor-coach-private` once a private Source exists. [pipeline.md](pipeline.md) explains every Step.

## Install your coach in Claude

**Claude Code:** start a session with the built plugin loaded, then run its setup:

```bash
claude --plugin-dir dist/plugin    # or: ytbrain claude -- --plugin-dir dist/plugin  (Haiku, on your plan)
```

```
/founder-coach:setup
```

**Cowork** (the Claude desktop app): **Customize → Plugins**, upload `dist/founder-coach-<version>.plugin`. A build that
includes your Books is named `…-private.plugin`: keep it to your own account. An installed plugin belongs to your
account, so every Cowork project has it; to update, build with a higher version (`ytbrain ops plugin` counts them;
by hand, `assemble_plugin.py --version`), remove the old plugin and upload the new file.

**First run and everyday use**

- `/founder-coach:setup` is a short interview: company, customer, Stage, one Goal, Check-in day. The search models
  (about 0.2 GB, once) download in the background, so there is nothing to run; search uses keywords until they finish.
  It saves to a Project named after the company, in `~/.ytbrain/founder/projects/<id>/` (`FOUNDER.md` is readable),
  and nothing leaves the machine. A second company is a second Project (`/founder-coach:project`), with its own memory.
- After that, just talk. `coach`, `ask`, `weekly-focus`, `check-in` and `project` load on their own for startup questions, plans
  and weekly reviews; a multi-part question is split and each part searched, with cited talks. Only `setup`, `status`,
  `export`, `feedback` and `forget` need typing. `/founder-coach:status` shows what is saved, what is due and whether
  semantic search is ready.

## Tested setup

Developed and tested on a **MacBook Air M2, 16 GB RAM, macOS**, Python 3.11+, yt-dlp
2026.08.19, against the Y Combinator channel (56 playlists, ~860 videos, ~710 with
English captions).

| Backend | Model | Result on our test videos |
|---|---|---|
| **OpenRouter** (paid, pennies) | `deepseek/deepseek-v4-flash` | **Recommended.** 4 workers: ~12–17 s per video overall; 10-video sample: 96 % of evidence quotes verified, 9/10 records pass. Whole ~700-video corpus ≈ $0.40–0.80. |
| OpenRouter | `google/gemma-4-31b-it` | 5-video sample: 51/51 quotes verified; ≈ $1.10 for the corpus. Slower providers. |
| **LM Studio** (local, free) | `gemma-4-e4b-it` (MLX, 4-bit), 32k context | Works on 16 GB. ~1 m 54 s per video → ~22 h for ~700 videos. Weaker on people/category extraction. |
| NVIDIA NIM (free tier) | `nvidia/nemotron-3.5-lightning-30b-a3b` | Works, but free-tier latency varied from 1 s to 100 s per request and several listed models were not callable for our account. Fine for trying things, not for a full run. |
| Ollama | any (default `qwen3:30b-a3b`) | Supported and covered by tests; not benchmarked by us on the M2. |

**Full-corpus runs** with DeepSeek V4 Flash on OpenRouter, 5 workers:

| Run | Records | Evidence quotes verified | Pass / flagged / failed |
|---|---|---|---|
| Schema 2.1 | 710 of ~712 (99.7 %) | 95.6 % | 659 / 29 / 22 |
| Schema 2.2.0 | 708 of 712 (99.4 %) | 98.5 % | 686 / 21 / 1 |
| + current verifier | 708 of 712 (99.4 %) | 99.1 % | 688 / 19 / 1 |

With 2.2.0, a normal record is 2–3k output tokens. The few replies that hit the output cap
were a provider stuck in a loop, now retried on a different provider (see
[extract](pipeline.md#extract)).

**Knowledge index** on the M2 Air: 708 talks produced 24 814 items in 53 min.
`BAAI/bge-m3` runs on the Apple GPU (`mps`) at about 5 s per talk. The two local models
(embedding + reranker) are ~2.3 GB each, downloaded once to `~/.cache/huggingface`.

**YouTube** rate-limits anonymous caption downloads per IP. Until 2026-10-13 most of our
429s came from our own requests: sync also asked for the plain auto `en` track, which YouTube
serves through its translation endpoint (the one it throttles). Since then ytbrain reads each
talk's info first and downloads one track, `en-orig` or a human English track, so a talk costs
one page fetch and one subtitle request ([Caption tracks](pipeline.md#caption-tracks)).

Prices and free-tier limits are as of September 2026 — check your provider.

## Responsible use

- **Captions are the uploader's content.** `data/` (raw captions, transcripts) is
  git-ignored on purpose: use it as ingestion material, and publish only what you derive
  (summaries, taxonomy, advice) with links back to the original video. Respect the
  YouTube Terms of Service and the uploader's rights.
- **Be gentle with YouTube.** ytbrain spaces requests (`sleep_requests`), asks for one
  caption track per talk, stops YouTube for the run at the first HTTP 429 and then leaves it
  alone for a day (the YouTube pause). Don't lower those defaults to go faster.
- **No IP rotation.** Rotating proxies to get around YouTube's rate limits is
  circumvention, which its terms prohibit. ytbrain only passes one proxy through
  (`YTBRAIN_YTDLP_PROXY`, e.g. a company network). The supported answer to 429s is
  slower pacing: `sync --backfill`.
- **Run it from a normal (residential) connection.** YouTube blocks or heavily limits
  cloud/datacenter IPs, and sandboxes that proxy traffic (`Tunnel connection failed: 403`).
- **ytbrain never logs in to YouTube.** It uses no cookies or Google account. (yt-dlp can,
  but its authors warn that accounts used this way can be banned.)
