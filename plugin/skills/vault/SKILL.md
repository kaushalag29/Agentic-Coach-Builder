---
name: vault
description: Builds the Project's vault, a read-only folder of plain Markdown (one file per Note, Decision, Goal and Commitment, linked) that Obsidian or another graph viewer can open. Use when the person types /{{id}}:vault.
disable-model-invocation: true
argument-hint: "[output folder]"
---

# Vault

The coach already refreshes the part of the vault it may read after every save. This builds all of it again: the first time on a Project that already has records, after a coach was added or removed, or to repair a folder that drifted.

1. **Run** with Bash: `uvx --from "${CLAUDE_SKILL_DIR}/../.." {{id}} vault build` — add `--out "<folder>"` if the {{person}} gave one: $ARGUMENTS. It reads a copy of the database, never the live one, and writes only the vault folder (by default `vault/` inside the {{project_noun}}'s folder).
2. **Report** the folder it printed and how many files it wrote. Tell the {{person}} to open that folder as a vault in Obsidian (File → Open folder as vault) and open the graph view; Foam, Quartz and Logseq read the same files.
3. **Say what it is**: a read-only view. Edits to these files are overwritten at the next save; to change a record, change it through the coach. Records a coach keeps private (the investor's) are in that coach's own folder, never in `shared/`.
4. Don't open or summarise the files unless asked; they hold the {{person}}'s private notes and decisions.

## Gotchas

- If `uvx` can't be found or the command can't see the {{project_noun}}'s folder, say so plainly and stop: the vault still refreshes by itself on every save. Don't copy or move the database to make it work.
- A full build is the {{person}}'s own command, so it shows every coach's folder. It is not one coach reading another's memory.
