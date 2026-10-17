# Security and privacy

## Reporting a problem

Report a vulnerability or a leak (a secret in the history, a person's data where it shouldn't be) privately
through GitHub's **Security → Report a vulnerability** on this repository, not in a public issue. Include what you
found and where; don't include the secret itself.

## Secrets

- API keys live only in `.env`, which is git-ignored; `.env.example` is the template.
- `scripts/check_secrets.py` scans every tracked file for API keys, tokens, private keys and
  env files. CI runs it on every push, `scripts/release.py` runs it on the repo and on the
  built plugin, and `CONTRIBUTING.md` shows the pre-commit hook.
- If a key is ever committed: revoke it at the provider first, then remove it from the history.
  Deleting it in a later commit is not enough.

## Coach memory

- A coach keeps everything about the person it coaches on their own machine, in
  `~/.ytbrain/<pack>/projects/<id>/` (or the folder `FOUNDER_COACH_HOME` pins): the store, FOUNDER.md, backups, Feedback, the usage log and any exports in
  `exports/`. There is no server and nothing is sent automatically; the only network call is the
  one-time download of the ONNX query models. The usage log (docs/usage-log.md) stays local, holds
  no Founder text unless `FOUNDER_COACH_USAGE_TEXT=1` (search text only), and is turned off with
  `FOUNDER_COACH_USAGE=0`.
- Coach memory is never sent to an LLM by the build tools. Source text, including your private Books, goes to the
  LLM endpoint and the eval judges you configure while building and evaluating (ADR-0006, ADR-0008).
- Feedback and the usage log leave the machine only when the Founder runs `founder-coach feedback export`
  or `founder-coach usage export` and sends the file. `founder-coach forget` empties the store and FOUNDER.md,
  Feedback and the usage log included; it keeps one final backup unless run with `--no-backup`, and
  does not delete earlier exports in `exports/`.
- The runtime reads only `FOUNDER_COACH_*` lines from any `.env` file, so a shared `.env` never
  hands it an API key.
- Quoted talk text reaches the host model wrapped as untrusted reference material, never as
  instructions. Write tools save only what the Founder approved (ADR-0011).

## Supply chain

- The runtime's dependencies are declared in `plugin/pyproject.toml` (a test checks every
  import is covered) and installed by `uv` on the Founder's machine.
- The Knowledge pack ships with a sha256 manifest; the runtime refuses a pack that fails it.
