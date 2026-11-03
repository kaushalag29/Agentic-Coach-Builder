# Build your own coach

A coach is defined by **what it knows** (your Sources, tagged into Domains) and **how it coaches** (a Pack). The
pipeline, search, memory, plugin packaging and evaluation are shared, so a new coach needs configuration, not code.
The three coaches in `packs/` (founder, coding, investor) are working examples to copy.

```mermaid
flowchart LR
    A["1 · Sources<br/>sources.yaml"] --> B["2 · Domains<br/>domains.yaml"]
    B --> C["3 · Pack<br/>packs/&lt;id&gt;/pack.toml"]
    C --> D["4 · Skills<br/>packs/&lt;id&gt;/skills/"]
    D --> E["5 · Eval cases<br/>coach_cases/&lt;id&gt;/"]
    E --> F["6 · ytbrain ops<br/>build, measure, assemble"]
    F --> G["7 · Install<br/>Claude Code / Cowork"]
```

`ytbrain coach new` drafts steps 3 and 4 for you (below); the Sources, Domains and evaluation cases are still yours,
because they are what makes the coach about your subject.

```bash
ytbrain coach new legal --person Founder --project-noun matter --subject "contract law for founders" \
  --domains legal --field "matter=the matter, in one line" --field "jurisdiction=where it is governed" --like coding
```

It writes `packs/<id>/pack.toml` (identity, words, Domains, memory modules, profile fields, the coaching contract) and
`packs/<id>/skills/<name>/SKILL.md` for `ask`, `coach` and `setup` in the coach's words, copies the cases of `--like` as a start, loads the
result with the same checks as any Pack, and prints what is left: declare any missing Domain, add Sources, rewrite
the copied cases. It uses templates only (no model, so the same input writes the same files), never overwrites a Pack,
and never edits `domains.yaml`. `--owned` keeps this coach's records from the other coaches of a shared Project.

## 1. Add the Sources

List the playlists, websites and PDF folders the coach should learn from in `sources.yaml`
([configuration.md](configuration.md#sources-sourcesyaml)). Books stay private: they reach only builds marked
`private`, never a public pack.

## 2. Declare its Domains

A Domain is a subject with a description, example questions and a risk tier. Content is tagged against the list,
so a Source needs no label:

```bash
ytbrain domains add legal --risk high --description "Law for founders: incorporation, contracts, IP, employment"
ytbrain domains alias legal "law"
ytbrain domains propose           # groups content no Domain fits into proposed Domains (nothing is added)
```

Write the description and examples the way a person would ask: they are what content is scored against. The risk
tier decides how strong the evidence must be before the coach answers (`high`: it never advises a personal call, such as a trade or a dose, and below `strong` coverage it answers
only as education, from the hits, saying the evidence is partial).

## 3. Write the Pack

`ytbrain coach new` drafts it; or copy the closest example to `packs/<id>/pack.toml` and edit it. Every key is checked when the Pack loads.

| Section | What it sets |
|---|---|
| `[pack]` | `id`; `domains` it answers from; memory `modules` (from `goals`, `commitments`, `checkins`, `decisions`, `holdings`, `notes`); `common_fields` it shares across coaches; `owned` (`["*"]`, or modules and profile fields) it keeps from the other coaches of a shared Project; `required` setup fields; `skills` and `prompts`; `builds` (`private`, `release`) |
| `[product]` | the plugin's `id`, `display_name`, `description` and `keywords` |
| `[words]` | what the person and a Project are called (`Engineer`, `system`) |
| `[runtime]` | the coach's name, its setup nudge and its coaching contract (`instructions`) |
| `[limits]` | what the coach never answers (`never`, needs `refer_to`) and the one-line `warning` that ends every opinion (ADR-0021); the coach declines only that part and ranks or recommends the rest |
| `[loop]` | the recurring Focus and Check-in (ADR-0022): `every` (`weekly`, `fortnightly`, `monthly`), `default` (`on` or `off`) and up to five Check-in `questions`; needs the `commitments` and `checkins` modules and the `weekly-focus` and `check-in` skills; a Project overrides it with its `loop` and `loop_every` |
| `[runtime.replace]` | the shared runtime's wording, rewritten for this coach |
| `[[profile]]` | each fact a Project remembers, with its description |

## 4. Add or adapt skills

Shared skills live in `plugin/skills/` (`ask`, `coach`, `setup`, `project`, `status`, `export`, `forget`,
`feedback`, …). A Pack's own `packs/<id>/skills/<name>/SKILL.md` replaces a shared one or adds a new one, like the
coding coach's `design-review` and `decision-record`.

## 5. Add evaluation cases

The gates run your built plugin on the real host ([architecture.md](architecture.md#evaluation-framework)):

- **G2** (Citations supported) works with no extra files: it asks Tuning questions seeded from the Documents in this
  coach's pack.
- **G4–G8** read `ytbrain/eval/coach_cases/<id>/`: `sycophancy.jsonl` (weak plans to push back on),
  `personas.jsonl` (multi-week memory), `decomposition.jsonl` (multi-part questions), `projects.jsonl` (Projects kept
  apart) and `safety.jsonl` (what it must refuse). A gate with no file has no cases; copy the coding or investor files
  as a start.
- Each gate's grading rubric comes from `PACK_RUBRICS` in `ytbrain/eval/coach.py` when the Pack has one, else the
  founder wording; a coach on a different subject should add its own.

## 6. Build and measure

```bash
ytbrain ops                                   # ingest, tag against the new Domains, eval, assemble every Pack
ytbrain ops plugin --coach                    # before you rely on it: the coach gates whose inputs changed
ytbrain gaps --pack <id> --days 30            # later: what the coach couldn't answer, from its local usage log
```

Or one Pack by hand:

```bash
ytbrain pack build --for <id> --include-private --out data/packs/<id>/pack-private
python scripts/assemble_plugin.py --for <id> --pack data/packs/<id>/pack-private --check --zip
ytbrain eval coach --plugin dist/<product-id>
```

## 7. Install it

`claude --plugin-dir dist/<product-id>` in Claude Code, or upload the `.plugin` file in Cowork
([getting-started.md](getting-started.md#install-your-coach-in-claude)). With several coaches installed,
`ytbrain eval choice` checks that each prompt reaches the right one.
