---
name: project
description: Lists, switches, creates, renames or links to a work folder the {{person}}'s Projects (one per {{project_noun}}, each with its own memory), or summarises another one on request. Use when the person types /{{id}}:project, or asks to switch {{project_noun}}, start a new one, or see which one is active.
---

# Project

Each Project keeps its own memory: {{memory}}. A session works on one active Project; nothing moves between Projects.

1. **Where we are.** `coach_project` with action `list`. Say which Project is active (or that none is) and list the others by name.
2. **Do what was asked,** one `coach_project` call:
   - *switch:* `switch` with the Project's id or name. Then `coach_get_context` and give a one-line recap of that Project (its key profile facts, the active Goal, what's due).
   - *a new {{project_noun}}:* `create` with its name (it becomes the active Project), then offer `/{{id}}:setup` for its profile.
   - *rename:* `rename` with the new name; its memory stays as it is.
   - *link or unlink a folder:* `link` (the Project, and the `folder` when it isn't the one the app gave) so the work folder chooses this Project from then on, `unlink` to end it. A folder belongs to one Project; a moved checkout is found again by its git remote.
   - *look at or compare another Project:* `summary` with its id. Only when the {{person}} asks; it is read-only, and nothing from it is saved into the active Project.
3. **Name the Project** in every later save you propose ("Save to Acme: …").

## Gotchas

- With no Project active (several, or one and the app named no work folder), ask which one before reading or saving anything about the {{person}}. A question that needs no memory can be answered first.
- A work folder linked to no Project keeps no memory: say so, answer from the knowledge, and offer to link the folder to one of the Projects or make a new one. Never pick one for them because it is the only one or the last used.
- Another coach in this conversation may already have chosen a Project (its `coach_project` result, or the same folder): switch to that one so the {{person}} is asked once.
- A fact true for every Project (their name, role, time zone, how they like answers) may go to the Common profile their coaches share: ask "Use this for all your Projects and coaches?" and save with `scope: "common"` only on a yes.
- `mode: "single"` means one data folder is pinned ({{env_prefix}}HOME): there are no Projects to switch; say so.
