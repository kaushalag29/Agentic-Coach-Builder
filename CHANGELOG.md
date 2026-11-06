# Changelog

User-visible changes, newest first. Coach plugins carry their own version (asked by `ytbrain ops plugin`); the
released benchmark carries its version in `eval/VERSION`.

## Unreleased

- **A Project vault for Obsidian (or any graph viewer).** `vault/` in a Project's folder is a read-only folder of
  plain Markdown: one file per Note, Decision, Goal and Commitment, `[[links]]` between them, tags and a hub note per
  scope, with the investor's records in its own folder. Each coach refreshes the part it may read after every save;
  `founder-coach vault build [--out DIR]` (also `/founder-coach:vault`) rebuilds all of it from a read-only copy of the
  database. The coach skills now link a Note to the Decision, Goal or Note it is about. See ADR-0020 (amendment
  2026-11-05).
- **Coach evaluation:** `ytbrain eval coach --force` runs the selected cases again even when a result is saved for the
  same inputs (the new result supersedes the old one). The G7 cases for two Projects now start the second session in a
  work folder linked to no Project, as the work folder chooses the Project; the fortnightly persona lists `loop: on` as
  dictated. The coach skills say a dictated free-text value (constraints, for example) is saved word for word, and the
  coding and investor setup saves `loop: off` when the person declines the recurring loop (it saved nothing, so the
  answer was not kept).
- **Bug fixes after the checker and loop work:**
  - A malformed `sources.yaml` is named (its line, and the usual cause: a name containing `: ` needs quotes) instead
    of a traceback, and `ytbrain ops` checks it, and the Domains it names, before the first step. A sync that crashed
    without leaving a stop record was reported as "a network problem" and retried; it is now `unknown`, stops once and
    says to read the output above.
  - A session with no work folder from the app no longer picks the only Project by itself: the coach asks which Project
    this conversation is about (ADR-0019 point 4; only `<PREFIX>PROJECT`, a choice the person made, decides without a
    folder; the command line still goes on to the only or last Project).
  - `weekly-focus` run again in a period that already has a Focus no longer refuses or stacks a second set: it shows the
    open Commitments and offers to keep or swap them, and a person who declines the recurring loop still gets a Focus
    for the period (the switch governs reminders and the Check-in rhythm, not whether a Focus can be planned).
  - `coach_update` returns `carried_periods` (was `carried_weeks`): the streak counts periods of the loop, not weeks.
  - `domains promote` takes the `auto`-applied high-tier tags of the promoted Domains from the staged run, so `domains
    review` lists the right Documents afterwards; `domains restore` from a backup made before a table existed leaves a
    database that still works.
  - Persona cases for the recurring loop (a founder on a fortnightly rhythm, a coding persona who turns it on, one who
    declines it but still plans a week) join the G5 memory gate.

- **A model checks each chunk with its Document before it is tagged (ADR-0023, off by default):** a chunk read alone
  scored almost the same for a talk that mentions code and one that teaches it, so founder talks were tagged `coding`.
  `ytbrain tag --check flagged` has a model read the chunks the embedding can't place, with the Document's title and
  summary, against every Domain (or none); verdicts are cached and a chunk it can't answer keeps its embedding tag.
  A Library that is already tagged is backfilled safely: `tag --check flagged --stage` keeps the result beside the tags in
  use, `domains diff` compares it per Domain, `domains promote DOMAIN` backs up and applies one Domain at a time, and
  `domains restore` undoes it. A new `ai-engineering` Domain (coding Pack) holds books on building with LLMs, `coding`
  names programming languages and AI coding assistants, and `domains review --reject` now removes a Domain from the
  Document's items as well as the Document.

- **`coach_recall` by date:** `since` and `until` (YYYY-MM-DD, inclusive) keep only records dated in that window (a Note
  by when it was made, a Decision by when it was decided), and `timeline: true` lists the matches oldest first, with the
  query optional, so "what happened in October?" is one call. A result says how many matched (`total`) and where to
  continue. Commitments and Check-ins show their week. No schema change; the coach skills say when to use it.
- **A recurring Focus and Check-in for any coach (ADR-0022):** a Pack declares `[loop]` in `pack.toml` (`every`:
  weekly, fortnightly or monthly; `default`: on or off; up to five Check-in `questions` in its own terms) and each
  Project switches it on or off (`loop`) and may set its own rhythm (`loop_every`). Founder is on by default; the
  coding and investor coaches are off until setup or the person says yes. The `weekly-focus` and `check-in` skills use
  the Pack's words, check the switch first and ask the Pack's questions. One Focus per period is shared by every coach
  on the Project; Check-ins stay private. Storage is unchanged (ISO weeks); overdue Check-ins, carried Commitments,
  repeated-carry warnings and the Nudge follow the Project's interval.
- **Assumption Notes in every coach:** the coach offers to keep "Assumption: <subject>" (why, what would change the
  person's mind, a revisit date) on a yes and asks about the due ones at the next Check-in. The investor Review
  keeps one Note per review (the next review returns as a Nudge), offers a Decision for a rebalance the person chooses,
  and lists holdings with no thesis Note or a past-due one.
- **Coaches give an opinion within declared limits (ADR-0021):** asked to find, compare, rank or recommend, a coach no
  longer declines. It gives its best opinion from cited library knowledge and the person's context, researches
  candidates with the host's web search without being asked (cited "web, unverified", the search carrying only the
  question's subject), ranks by named criteria and says what would change it. A Pack's `[limits]` in `pack.toml`
  (`never`, `refer_to`, `warning`) are delivered by `coach_get_context`; the coach declines only the `never` part in
  one sentence and ends with the `warning` once. The investor limits: no price target or return forecast, no timing
  call, no trade size beyond the policy's, no options, leverage, shorting or crypto, no individual tax or legal advice,
  no non-US markets. The G8 gate grades opinion cases with their own rubric and a rule check for limit-crossing
  sentences; `ytbrain coach new` drafts `[limits]` and the section. `coach_update` now says where a too-long or
  misplaced text belongs (1000 characters; a Note holds a longer account).
- **Projects are shared by the coaches (slice A of ADR-0019):** a Project now lives in `~/.ytbrain/projects/<id>/`
  and every coach on the machine lists it, instead of each coach keeping Projects of its own. Every record in the store
  carries the coach that made it (store schema 7, a backup is taken first), and for now a coach reads only the
  records it made; sharing Goals and Decisions between coaches, choosing the Project from the work folder and
  `PROJECT.md` follow in later slices. At the first start after the update each coach's own Projects are copied once
  into the shared folder (SQLite backup copy, integrity check, a backup beside the copy, a marker and a lock); the
  old folders are left as they were, a Project that can't be moved is reported and retried, and two Projects with the
  same name stay apart (`Name (coding)`). `ytbrain gaps` reads the shared folder and splits usage by coach.
  Forget and `<coach> forget` act on that coach's records only; the generated files of a coach other than the founder
  Pack are `CODING.md` / `notes-coding/` (named after the coach) so coaches don't overwrite each other. Update
  every coach together: a coach still on the old build writes to its old folder.
- **The work folder chooses the Project (slice B of ADR-0019):** a Project lists the folders it belongs to
  (`coach_project` `link` / `unlink`, `<coach> projects link|unlink`; a checkout is stored with its git remote, never
  with credentials, so a moved checkout is found again and re-linked with a note). When the app names the work folder
  (`CLAUDE_PROJECT_DIR`) the deepest linked folder decides; a folder linked to nothing gets no memory and the coach
  offers to link it or make a Project (the first save in an unlinked folder makes one and links it). The session
  hook uses the folder and never the last Project used; the command line uses the folder, then the shared last
  Project. Without a folder from the app the coach asks which Project (even when there is only one; see below).
  The skills and instructions tell a coach to switch to the Project another coach in the conversation already chose.
  Reading MCP roots is not built (it needs asynchronous tools); the folder comes from `CLAUDE_PROJECT_DIR` only.
- **Coaches read each other's shared core (slice C1 of ADR-0019):** in a Project several coaches share, each reads the
  Goals, Commitments and Decisions the others made, and a profile field both declare is one current value; a record
  from another coach shows `coach` in context and `coach_update` can update it. Notes, Check-ins and Holdings stay
  with the coach that wrote them, and a Pack with `owned = ["*"]` in `pack.toml` (the investor) neither reads nor is
  read. A coach is read only while it is registered on the machine. `PROJECT.md` in the Project's folder lists the
  shared core with the coach behind each record and never holds anything private.
- **Clearer refusals from `coach_update` (from the usage log):** the coach passed `note` to a Decision four times in a
  month and once sent a Check-in summary over the 1000-character limit. The refusal now names the fields that do take
  the change and, when the Pack keeps Notes, says to save a longer account or the thinking around a Decision as a Note
  linked to it; a too-long text says its length. The tool's `note` and `changes` descriptions state the limit and
  that a Decision takes `changes`.
- **`ytbrain coach new <id>` drafts a coach:** from a short description (person, what a Project is, Domains, profile
  fields, memory modules, `--owned`) it writes `packs/<id>/pack.toml` and the `ask`, `coach` and `setup` skills in the
  coach's words, optionally copies another coach's evaluation cases (`--like`), and checks the result with the Pack
  loader. Templates only, no model; it never overwrites a Pack or edits `domains.yaml`, and it prints the Domain
  command, Sources and case rewrites that are left. The assembled plugin is tested on the real runtime.
- **Setup and the Projects check (slice C2 of ADR-0019):** the setup skills tell a person that a Project is shared by
  every coach of the work (the investor's is private) and the Project skill covers `link`, `unlink` and the
  no-fallback rule. The G7 Project check can now be read `as` another coach (`peers`, `owned`), and an offline test
  grades sharing inside a Project, isolation between Projects and the privacy of an owned Pack on stores it builds;
  the host run of G7 still tests one coach at a time.
- **Notes:** every coach now keeps dated, append-only Notes (a discussion, a piece of research, an insight) with a
  title, a summary, a type, an Origin (said by the person, or concluded by the coach), the Citations it rests on
  (their words kept with the Note) and links to the Goals and Decisions it is about, so progress and earlier
  conclusions can be found again. A Note is saved only on a yes, is never rewritten (a newer Note supersedes it, both
  stay on record) and may carry a `revisit_on` date that becomes a Nudge. `coach_get_context` lists the newest Note
  titles; the new `coach_recall` tool searches Notes and the other records by their words (full-text index inside
  the store, rebuildable); FOUNDER.md lists them. A `notes/` folder beside the store holds a generated index
  (`INDEX.md`, also the resource `founder://notes`), a sub-index per quarter and one file per Note, all read-only
  views of the store; `<coach> notes lint` reports what needs attention and `<coach> notes rebuild` regenerates the
  derived files. Store schema 6 (a backup is taken first). See ADR-0020.
- **High-risk Domains educate below strong coverage:** at `partial`, the coach now answers a general question from what
  the sources say (every claim cited and attributed, disagreements shown), says the material is partial and that
  applying it to the person's own situation is a qualified adviser's call. It still never advises a trade, purchase,
  valuation, rate or allocation, and states a Gap at `none`. Before, the investor coach declined nearly every
  educational question. G8 gains educational cases that must be answered, not declined.
- **Searches are written as questions:** the skills and `coach_search`'s `query` now ask for a full question in the
  sources' words, never a string of keywords. A keyword string can score low enough to be called a Gap where the same
  question in a sentence is `strong`. New diagnostic: `ytbrain eval run --config pack-keywords --compare pack-no-rerank`
  measures the difference, and every run now reports its closest hit's median similarity.
- **`ytbrain gaps --replay`:** searches the recorded weak questions again against each coach's installed pack (or
  `--pack P --replay-pack DIR`) and shows each one's level then and now; it logs and writes nothing.
- **Tool errors say what failed:** `<coach> usage summary` and `ytbrain gaps` list the newest errors with their
  messages (values you typed shown as '…'), instead of only counting them.
- **A Book's corrected year no longer re-extracts it:** a change to a Book's year, ISBN, publisher or url (fields no
  prompt reads) is written into its Chapters' records in place, then re-indexed. `ytbrain refresh` no longer
  overwrites a Book's Series (its title) with its Source's name.
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
