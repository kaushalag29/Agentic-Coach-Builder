---
name: vault
description: Builds the Project's vault, a read-only folder of plain Markdown (one file per Note, Decision, Goal and Commitment, linked) that Obsidian or another graph viewer can open. Use when the person types /{{id}}:vault.
disable-model-invocation: true
argument-hint: "[output folder]"
---

# Vault

The coach already refreshes the part of the vault it may read after every save. This builds all of it again: the first time on a Project that already has records, after a coach was added or removed, or to repair a folder that drifted.

1. **Which {{project_noun}}.** One at a time: the one this conversation chose. Call `coach_get_context` and take the {{project_noun}}'s `id` from its `project`. If no {{project_noun}} has been chosen yet, ask which one first, as for any save, and don't guess. If the context has no `project` (a single data folder), leave `--project` out.
2. **Run** with Bash: `uvx --from "${CLAUDE_SKILL_DIR}/../.." {{id}} vault build --project "<id>"` — add `--out "<folder>"` if the {{person}} gave one: $ARGUMENTS. It reads a copy of the database, never the live one, and writes only the vault folder (by default `vault/` inside the {{project_noun}}'s own folder). It builds everything from the saved records, so a {{project_noun}} with no vault yet gets one now, and one that has a vault is brought up to date.
3. **Report** the folder it printed and how many files it wrote. Tell the {{person}} to open that folder as a vault in Obsidian (File → Open folder as vault) and open the graph view; Foam, Quartz and Logseq read the same files.
4. **Say what it is**: a read-only view. Edits to these files are overwritten at the next save; to change a record, change it through the coach. Records a coach keeps private (the investor's) are in that coach's own folder, never in `shared/`.
5. Don't open or summarise the files unless asked; they hold the {{person}}'s private notes and decisions.

## Gotchas

- If `uvx` can't be found or the command can't see the {{project_noun}}'s folder, say so plainly and stop: the vault still refreshes by itself on every save. Don't copy or move the database to make it work.
- A full build is the {{person}}'s own command, so it shows every coach's folder. It is not one coach reading another's memory.
