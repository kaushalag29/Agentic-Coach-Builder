# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ytbrain: command not found` | Activate the venv: `source .venv/bin/activate` |
| `HTTP Error 429: Too Many Requests` in sync | YouTube is rate-limiting your IP: sync stops YouTube at the first one and pauses it for 24 h (the ops summary says until when). First fix any `WARNING` lines `sync` prints (missing yt-dlp-ejs or JavaScript runtime). Keep `sleep_requests` ≥ 5. After the pause, or with `ytbrain sync --ignore-pause`, `caffeinate -i ytbrain sync --backfill` retries the failed talks slowly |
| `Sign in to confirm you're not a bot` / PO-token errors | YouTube anti-bot checks. `uv pip install -U yt-dlp`, run from a home connection; see the [yt-dlp wiki](https://github.com/yt-dlp/yt-dlp/wiki/Extractors) |
| `UNAVAILABLE (private video)` | The playlist lists a private/removed video; nothing to do |
| `Tunnel connection failed: 403` | You are behind a proxy/sandbox that blocks YouTube; run on your own machine |
| `note: X from your shell … overrides .env` | An old value is exported in this terminal; open a new one or `unset X` |
| `model '…' not served … Set YTBRAIN_LLM_MODEL to one of: …` | Wrong model id; copy one from the list |
| `… is listed but not callable: HTTP 404` | Provider lists the model but your account can't use it; pick another (`ops/probe_models.py`) |
| `queued or down right now` | Hosted free tier is congested; retry later or switch backend |
| `extract failures` in `report` | Open the call log it names. `"finish": "length"` with a `tail` that repeats one value is a provider loop, retried elsewhere automatically. With large `reasoning_tokens`, hidden thinking used up the cap: check that `YTBRAIN_LLM_EXTRA_BODY` turns reasoning off |
| Every extract shows `repair 1` | Model struggles with the JSON schema; try `YTBRAIN_LLM_JSON_MODE=response_format` or a stronger model |
| LM Studio output truncated or nonsensical on long talks | Context length too small; load the model with 32768 |
| `another ytbrain run is active (pid N)` | Another command is running; only one at a time. A dead PID is cleared automatically |
| `sqlite3: no such table` | The database is `data/manifest.db`, not `manifest.db` in the repo root |
| `the knowledge index needs the optional "index" extra` | `uv pip install -e ".[index]"` **inside the activated `.venv`** (check with `which python`) |
| `search` / `index` pauses on a big download | First use of each model (~2.3 GB each), cached afterwards in `~/.cache/huggingface` |
| `device 'mps' requested but not available` / MPS errors | Use `--device cpu` (slower, same results); `auto` falls back on its own |
| `search` slow or memory-tight on 16 GB | `--no-rerank` skips the second model |
